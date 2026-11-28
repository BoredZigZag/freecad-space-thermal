# SPDX-License-Identifier: MIT OR Apache-2.0
"""Synthetic native WP-18 acceptance, called by the thermal stage."""
from copy import deepcopy
from pathlib import Path
from math import exp, isclose
import json
import subprocess
import sys
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from fcst_app.campaign import digest, read_json, report_campaign, run_campaign
from fcst_app.persistence import PersistenceError, encode, semantic_hash


def rejected(operation, code):
    try:
        operation()
    except PersistenceError as error:
        assert str(error) == code
    else:
        raise AssertionError(code)


def check_named_cases(worker, fixture, root, cli):
    envelope = read_json(fixture)
    model = envelope["model"]
    cold = next(row for row in model["entities"] if row["kind"] == "case")
    cold["mode"] = "steady"
    cold["overlays"][1]["value"]["value"] = 2
    hot = deepcopy(cold)
    hot["id"] = "00000000-0000-4000-8000-000000000017"
    hot["overlays"][2]["value"]["value"] = 10
    disconnected = deepcopy(cold)
    disconnected["id"] = "00000000-0000-4000-8000-000000000018"
    disconnected["overlays"][1]["value"]["value"] = 0
    model["entities"].extend((hot, disconnected))
    load = cold["load_ids"][0]
    node = next(row["node_id"] for row in model["entities"] if row["id"] == load)
    spec = {
        "seed": 6, "samples": 2,
        "budget": {"jobs": 7, "compute_s": 20, "per_run_s": 5, "memory_mb": 128,
                   "artifact_bytes": 512 * 1024},
        "parameters": {"heater": {"entity": load, "field": "power", "min": 0,
                                  "max": 15, "distribution": "uniform"}},
        "variants": {
            "hot-flight": {"case_id": hot["id"], "parameters": {}},
            "hot-test": {"case_id": hot["id"], "parameters": {"heater": 12}},
            "off": {"case_id": cold["id"], "parameters": {"heater": 0}},
            "unconverged": {"case_id": disconnected["id"], "parameters": {}},
        },
        "uncertainty": {"node": node, "time_s": 0},
    }
    source = root / "named.json"
    source.write_bytes(encode(envelope))
    (root / "named-spec.json").write_bytes(encode(spec))
    limits = {"version": 1, "nodes": {node: {"min_K": 300, "max_K": 320, "margin_K": 0}}}
    (root / "named-limits.json").write_bytes(encode(limits))
    directory = root / "named"
    manifest = cli("campaign-run", source, root / "named-spec.json", directory, "--worker", worker, exit_code=1)
    report = cli("campaign-report", directory, root / "named-limits.json",
                 "--campaign-sha256", manifest["campaign_sha256"])
    runs = {row["name"]: row for row in report["runs"]}
    assert read_json(source) == envelope
    assert manifest["source_model_hash"] == semantic_hash(model)
    assert report["project_id"] == model["project_id"] and report["revision"] == model["revision"]
    assert report["status"] == "incomplete" and report["sensitivity"] == {}
    assert runs["variant/unconverged"]["status"] == "failed"
    assert runs["variant/unconverged"]["diagnostics"]["reason"]
    for name, power, case in (("baseline", 7, cold), ("variant/hot-flight", 10, hot),
                              ("variant/hot-test", 12, hot), ("variant/off", 0, cold)):
        run = runs[name]
        assert run["case_id"] == case["id"] and run["inputs"] == {"heater": power}
        # Two 2 W/K conductors in series provide a 1 W/K path to the 300 K boundary.
        assert isclose(run["limits"][0]["max_K"], 300 + power, abs_tol=1e-8)
        assert isclose(run["diagnostics"]["energy_defect_W"], 0, abs_tol=1e-8)
    assert runs["baseline"]["model_hash"] == runs["variant/hot-flight"]["model_hash"]
    assert runs["baseline"]["request_sha256"] != runs["variant/hot-flight"]["request_sha256"]
    for run in (runs["sample/0"], runs["sample/1"]):
        assert isclose(run["response_K"], 300 + run["inputs"]["heater"], abs_tol=1e-8)
    assert report["uncertainty"]["successful"] == 2
    assert isclose(report["uncertainty"]["mean_K"],
                   300 + (runs["sample/0"]["inputs"]["heater"] + runs["sample/1"]["inputs"]["heater"]) / 2,
                   abs_tol=1e-8)


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
                   "artifact_bytes": 768 * 1024},
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
        for name, data in (("spec", spec), ("transient", transient), ("limits", limits)):
            (root / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")

        def cli(*args, exit_code=0):
            result = subprocess.run([sys.executable, "-m", "fcst_cli", *map(str, args)],
                                    capture_output=True, timeout=35)
            assert result.returncode == exit_code and not result.stderr
            return json.loads(result.stdout)

        first = cli("campaign-run", fixture, root / "spec.json", root / "first", "--worker", worker,
                    "--transient", root / "transient.json")
        second = run_campaign(envelope, spec, root / "replay", worker, transient=transient)
        assert all(row["status"] == "passed" for manifest in (first, second) for row in manifest["runs"])
        assert [(r["inputs"], r["request_sha256"]) for r in first["runs"]] == [
            (r["inputs"], r["request_sha256"]) for r in second["runs"]]
        report = cli("campaign-report", root / "first", root / "limits.json", "--html", root / "report.html",
                     "--campaign-sha256", first["campaign_sha256"])
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
        html = (root / "report.html").read_text(encoding="utf-8")
        svg = ElementTree.fromstring("<svg" + html.split("<svg", 1)[1].split("</svg>", 1)[0] + "</svg>")
        def queried(run_id):
            native = read_json(root / "first" / (run_id + "-result.json"))
            node_index = native["node_ids"].index(node)
            _, left, right = (row["temperature_K"][node_index] for row in native["samples"])
            return [left, (left + right) / 2]

        traces = [measured_training, measured_holdout] + queried(fit["baseline_run"]) + queried(fit["fitted_run"])
        lo, hi = min(traces), max(traces)
        for index, (point, value) in enumerate(zip(svg, traces, strict=True)):
            assert float(point.attrib["cx"]) == (15 if index % 2 == 0 else 625)
            assert isclose(float(point.attrib["cy"]), 195 - 180 * (value - lo) / (hi - lo), abs_tol=.00005)
        for before, after in zip(fit["baseline"], fit["fitted"], strict=True):
            row = before["observation"]
            assert "".join(f"<td>{value}</td>" for value in (
                row["sensor"], row["time_s"], row["split"], before["measured_K"],
                before["predicted_K"], after["predicted_K"])) in html
        edited = deepcopy(limits)
        edited["version"] = 2
        edited["nodes"][node]["max_K"] = 310
        revised = report_campaign(root / "first", edited)
        assert revised["limits_sha256"] != report["limits_sha256"]
        assert revised["campaign_sha256"] == report["campaign_sha256"]
        assert report["runs"][0]["limits"][0]["passed"] and not revised["runs"][0]["limits"][0]["passed"]

        over_budget = deepcopy(spec)
        over_budget["budget"]["jobs"] = 8
        rejected(lambda: run_campaign(envelope, over_budget, root / "rejected", worker, transient=transient),
                 "campaign_job_budget")
        assert not (root / "rejected").exists()
        manifest_path = root / "replay/campaign.json"
        legacy = read_json(manifest_path)
        legacy["version"] = 1
        manifest_path.write_bytes(encode(legacy))
        rejected(lambda: report_campaign(root / "replay", limits, campaign_sha256=second["campaign_sha256"]),
                 "campaign_artifact")
        assert report_campaign(root / "replay", limits)["correlation"] == replay["correlation"]
        legacy["specification"]["observations"][1]["value"] = fit["baseline"][1]["predicted_K"]
        manifest_path.write_bytes(encode(legacy))
        altered_holdout = report_campaign(root / "replay", limits)["correlation"]
        assert altered_holdout["fitted_run"] == fit["fitted_run"]
        assert altered_holdout["metrics"]["baseline"]["holdout"] == 0
        assert altered_holdout["metrics"]["fitted"]["holdout"] > 100

        request_path = root / "replay/run-0001-input.json"
        modified = read_json(request_path)
        modified["transient"]["end"] = 3
        raw = encode(modified)
        request_path.write_bytes(raw)
        legacy["runs"][1]["request_sha256"] = digest(raw)
        manifest_path.write_bytes(encode(legacy))
        rejected(lambda: report_campaign(root / "replay", limits), "campaign_result_binding")

        with (root / "first/run-0001-result.json").open("ab") as stream:
            stream.write(b" ")
        rejected(lambda: report_campaign(root / "first", limits), "campaign_artifact")
        check_named_cases(worker, fixture.with_name("case-network.json"), root, cli)
