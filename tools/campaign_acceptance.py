# SPDX-License-Identifier: MIT OR Apache-2.0
"""Synthetic native WP-18 acceptance, called by the thermal stage."""
from copy import deepcopy
from pathlib import Path
from math import exp, isclose
from tempfile import TemporaryDirectory

from fcst_app.campaign import read_json, report_campaign, run_campaign
from fcst_app.persistence import PersistenceError
from fcst_cli.campaign import html_report


def check(worker, fixture):
    envelope = read_json(fixture)
    node = envelope["model"]["entities"][1]["id"]
    conductor = envelope["model"]["entities"][3]["id"]

    def temperature(time, conductance):
        return 300 + 10 * exp(-conductance * time / 2)

    measured_training = temperature(1, 1.5)
    measured_holdout = (temperature(1, 1.5) + temperature(2, 1.5)) / 2
    spec = {
        "seed": 3421, "samples": 3,
        "budget": {"jobs": 9, "compute_s": 30, "per_run_s": 10, "memory_mb": 128,
                   "artifact_bytes": 8 * 1024 * 1024},
        "parameters": {
            "conductance": {"entity": conductor, "field": "conductance", "min": .5,
                            "max": 2, "distribution": "uniform", "step": .04},
            "capacity": {"entity": node, "field": "capacity", "min": 1.9,
                         "max": 2.1, "distribution": "triangular"},
        },
        "correlation": [[1, .65], [.65, 1]],
        "variants": {"test": {"parameters": {"conductance": 1.5}}},
        "sensitivity": {"node": node, "time_s": 2, "absolute_tolerance": .002, "relative_tolerance": 0},
        "observations": [
            {"sensor": "synthetic", "node": node, "time_s": 1, "value": measured_training - 273.15,
             "unit": "degC", "sigma": .05, "split": "training"},
            {"sensor": "synthetic", "node": node, "time_s": 1.5, "value": measured_holdout,
             "unit": "K", "sigma": .05, "split": "holdout"},
        ],
    }
    transient = {"start": 0, "end": 2, "output_times": [0, 1, 2], "include_steps": False,
                 "absolute_temperature_tolerance": 1e-5, "relative_temperature_tolerance": 0}
    limits = {"version": 1, "nodes": {node: {"min_K": 290, "max_K": 315, "margin_K": 2}}}
    with TemporaryDirectory() as scratch:
        root = Path(scratch)
        first = run_campaign(envelope, spec, root / "first", worker, transient=transient)
        second = run_campaign(envelope, spec, root / "replay", worker, transient=transient)
        assert all(row["status"] == "passed" for manifest in (first, second) for row in manifest["runs"])
        assert [(r["inputs"], r["request_sha256"]) for r in first["runs"]] == [
            (r["inputs"], r["request_sha256"]) for r in second["runs"]]
        report = report_campaign(root / "first", limits)
        replay = report_campaign(root / "replay", limits)
        assert report["correlation"] == replay["correlation"]
        assert report["uncertainty"] == replay["uncertainty"]
        assert report["uncertainty"]["successful"] == 3
        assert report["sensitivity"]["conductance"]["status"] == "passed"
        assert isclose(report["sensitivity"]["conductance"]["refined_derivative"], -10 * exp(-1), abs_tol=.003)
        fit = report["correlation"]
        assert fit["fitted_run"] == "run-0001"
        assert fit["metrics"]["fitted"]["training"] < .005
        assert fit["metrics"]["fitted"]["holdout"] < .005
        assert fit["metrics"]["baseline"]["holdout"] > 100
        assert fit["fitted"][1]["bracket_s"] == [1, 2]
        artifact = read_json(root / "first/run-0001-result.json")
        index = artifact["node_ids"].index(node)
        raw_values = [row["temperature_K"][index] for row in artifact["samples"]]
        assert fit["fitted"][1]["predicted_K"] == (raw_values[1] + raw_values[2]) / 2
        assert str(fit["fitted"][1]["predicted_K"]) in html_report(report)
        edited = deepcopy(limits)
        edited["version"] = 2
        edited["nodes"][node]["max_K"] = 310
        revised = report_campaign(root / "first", edited)
        assert revised["limits_sha256"] != report["limits_sha256"]
        assert revised["campaign_sha256"] == report["campaign_sha256"]
        assert report["runs"][0]["limits"][0]["passed"] and not revised["runs"][0]["limits"][0]["passed"]

        def rejected(operation, code):
            try:
                operation()
            except PersistenceError as error:
                assert str(error) == code
            else:
                raise AssertionError(code)

        over_budget = deepcopy(spec)
        over_budget["budget"]["jobs"] = 8
        rejected(lambda: run_campaign(envelope, over_budget, root / "rejected", worker, transient=transient),
                 "campaign_job_budget")
        assert not (root / "rejected").exists()
        with (root / "first/run-0001-result.json").open("ab") as stream:
            stream.write(b" ")
        rejected(lambda: report_campaign(root / "first", limits), "campaign_artifact")
