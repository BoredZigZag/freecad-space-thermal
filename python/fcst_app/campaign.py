# SPDX-License-Identifier: MIT OR Apache-2.0
"""Bounded local thermal campaigns and artifact-backed comparison reports."""
from bisect import bisect_left
from copy import deepcopy
from hashlib import sha256
import math
import os
from pathlib import Path
import random
from statistics import NormalDist, fmean, pstdev
import subprocess
from tempfile import TemporaryFile
from time import monotonic

from fcst_contracts import MAX_BYTES
from .persistence import encode, loads, reject, semantic_hash
from .process_limits import WorkerLimits


def digest(data):
    return sha256(data).hexdigest()


def read_json(path, expected=None):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES or (expected is not None and digest(raw) != expected):
        reject("campaign_artifact")
    return loads(raw)


def write_json(path, value):
    raw = encode(value)
    with path.open("xb") as stream:
        stream.write(raw)
    return digest(raw)


def fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() <= set(required) | set(optional):
        reject("campaign_fields")


def number(value, low=-1e12, high=1e12):
    if type(value) not in (int, float) or not low <= value <= high:
        reject("campaign_range")
    return value


def integer(value, low, high):
    if number(value, low, high) % 1:
        reject("campaign_range")
    return int(value)


def sequence(value, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        reject("campaign_size")
    return value


def label(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        reject("campaign_label")
    return value


def parameter_targets(envelope, parameters):
    model = envelope.get("model", {})
    entities = {item["id"]: item for item in model["entities"]}
    targets = {}
    occupied = set()
    for name, spec in parameters.items():
        label(name)
        fields(spec, ("entity", "field", "min", "max", "distribution"), ("step",))
        key = (label(spec["entity"]), label(spec["field"]))
        target = entities.get(key[0], {}).get(key[1])
        low, high = number(spec["min"]), number(spec["max"])
        if (key in occupied or not isinstance(target, dict) or set(target) != {"unit", "value"}
                or low >= high or spec["distribution"] not in ("uniform", "triangular")):
            reject("campaign_parameter")
        number(target["value"], low, high)
        occupied.add(key)
        targets[name] = target
    return targets


def factor(matrix, count):
    """Cholesky factor of a positive definite latent normal correlation matrix."""
    if len(sequence(matrix, count)) != count:
        reject("campaign_correlation")
    if any(len(sequence(row, count)) != count for row in matrix):
        reject("campaign_correlation")
    lower = [[0.0] * count for _ in matrix]
    for i, row in enumerate(matrix):
        for j in range(i + 1):
            value = number(row[j], -1, 1)
            if matrix[j][i] != value or (i == j and value != 1):
                reject("campaign_correlation")
            residual = value - math.fsum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j and residual <= 1e-12:
                reject("campaign_correlation")
            lower[i][j] = math.sqrt(residual) if i == j else residual / lower[j][j]
    return lower


def schedule(envelope, spec):
    fields(spec, ("seed", "parameters", "samples", "budget"),
           ("correlation", "variants", "sensitivity", "observations", "fidelity_losses"))
    for entry in sequence(spec.get("fidelity_losses", []), 256):
        label(entry)
    seed = integer(spec["seed"], 0, 2**32 - 1)
    budget = spec["budget"]
    fields(budget, ("jobs", "compute_s", "per_run_s", "memory_mb", "artifact_bytes"))
    integer(budget["jobs"], 1, 512)
    number(budget["compute_s"], .01, 3600)
    number(budget["per_run_s"], .01, budget["compute_s"])
    integer(budget["memory_mb"], 32, 4096)
    integer(budget["artifact_bytes"], 1024, 512 * 1024 * 1024)
    params = spec["parameters"]
    if not isinstance(params, dict) or len(params) > 16:
        reject("campaign_parameter")
    names = sorted(params)
    targets = parameter_targets(envelope, params)
    baseline = {name: targets[name]["value"] for name in names}
    base_case = envelope.get("case_id")
    jobs = [("baseline", baseline, base_case)]
    variants = spec.get("variants", {})
    if not isinstance(variants, dict) or len(variants) > 64:
        reject("campaign_variants")
    for name, changes in sorted(variants.items()):
        label(name)
        fields(changes, ("parameters",), ("case_id",))
        values = changes["parameters"]
        if not isinstance(values, dict) or not values.keys() <= params.keys():
            reject("campaign_variants")
        case = changes.get("case_id", base_case)
        if "case_id" in changes and not any(
                e["kind"] == "case" and e["id"] == label(case) for e in envelope["model"]["entities"]):
            reject("campaign_case")
        values = {key: number(value, params[key]["min"], params[key]["max"]) for key, value in values.items()}
        jobs.append(("variant/" + name, baseline | values, case))
    samples = integer(spec["samples"], 0, 512)
    matrix = spec.get("correlation", [[int(i == j) for j in range(len(names))] for i in range(len(names))])
    lower = factor(matrix, len(names))
    rng = random.Random(seed)
    normal = NormalDist()
    for i in range(samples):
        draws = [normal.inv_cdf(max(2**-53, rng.random())) for _ in names]
        values = {}
        for j, name in enumerate(names):
            fraction = normal.cdf(math.fsum(a * b for a, b in zip(lower[j], draws)))
            if params[name]["distribution"] == "triangular":
                fraction = (math.sqrt(fraction / 2) if fraction < .5 else
                            1 - math.sqrt((1 - fraction) / 2))
            low, high = params[name]["min"], params[name]["max"]
            values[name] = low + (high - low) * fraction
        jobs.append((f"sample/{i}", values, base_case))
    if "sensitivity" in spec:
        fields(spec["sensitivity"], ("node", "time_s", "absolute_tolerance", "relative_tolerance"))
        label(spec["sensitivity"]["node"])
        number(spec["sensitivity"]["time_s"], 0)
        number(spec["sensitivity"]["absolute_tolerance"], 0)
        number(spec["sensitivity"]["relative_tolerance"], 0, 1)
    for name, parameter in sorted(params.items()):
        if "step" not in parameter:
            continue
        if "sensitivity" not in spec:
            reject("campaign_sensitivity")
        step = number(parameter["step"], 1e-15)
        center = baseline[name]
        if not parameter["min"] <= center - step < center - step / 2 < center < center + step / 2 < center + step <= parameter["max"]:
            reject("campaign_sensitivity")
        for key, offset in (("minus", -step), ("plus", step), ("half_minus", -step / 2), ("half_plus", step / 2)):
            jobs.append((f"sensitivity/{name}/{key}", baseline | {name: center + offset}, base_case))
    if len(jobs) > budget["jobs"]:
        reject("campaign_job_budget")
    return jobs, matrix


def sensor_rows(spec):
    rows = sequence(spec.get("observations", []), 4096)
    locations = set()
    splits = set()
    mapping = {}
    for row in rows:
        fields(row, ("sensor", "node", "time_s", "value", "unit", "sigma", "split"))
        sensor, node = label(row["sensor"]), label(row["node"])
        time = number(row["time_s"], 0)
        if (mapping.setdefault(sensor, node) != node or (node, time) in locations
                or row["unit"] not in ("K", "degC") or row["split"] not in ("training", "holdout")):
            reject("campaign_observations")
        number(row["value"], 0 if row["unit"] == "K" else -273.15)
        number(row["sigma"], 1e-12)
        locations.add((node, time))
        splits.add(row["split"])
    if rows and splits != {"training", "holdout"}:
        reject("campaign_holdout")
    return rows


def run_worker(worker, mode, raw, timeout, memory_mb, limit):
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR") if key in os.environ}
    env["PATH"] = str(worker.parent)
    with TemporaryFile() as request, TemporaryFile() as output:
        request.write(raw)
        request.seek(0)
        with subprocess.Popen([str(worker), "--thermal-" + mode], env=env, stdin=request,
                              stdout=output, stderr=subprocess.DEVNULL, creationflags=4) as process:
            limits = None
            try:
                limits = WorkerLimits(process, memory_mb)
                process.wait(timeout)
                output.seek(0)
                result = output.read(limit + 1)
                if len(result) > limit:
                    return {"status": "failed", "code": "campaign_artifact_budget"}
                if not result:
                    return {"status": "failed", "code": "worker_exit"}
                value = loads(result)
                if value.get("status") != ("failed" if process.returncode else "passed"):
                    return {"status": "failed", "code": "worker_exit"}
                return value
            except subprocess.TimeoutExpired:
                return {"status": "failed", "code": "worker_timeout"}
            finally:
                if limits:
                    limits.close()
                if process.poll() is None:
                    process.kill()


def run_campaign(thermal_input, spec, directory, worker, *, transient=None):
    if os.name != "nt":
        reject("unsupported_worker_platform")
    directory, worker = Path(directory), Path(worker).resolve()
    jobs, matrix = schedule(thermal_input, spec)
    sensor_rows(spec)
    budget = spec["budget"]
    if len(encode(thermal_input)) > MAX_BYTES or len(encode(spec)) > MAX_BYTES:
        reject("campaign_size")
    worker_hash = digest(worker.read_bytes())
    source = thermal_input["model"]
    source_hash = semantic_hash(source)
    mode = "transient" if transient is not None else "steady"
    directory.mkdir()
    started = monotonic()
    remaining = budget["artifact_bytes"]
    records = []
    for index, (name, values, case_id) in enumerate(jobs):
        envelope = deepcopy(thermal_input)
        if case_id is not None:
            envelope["case_id"] = case_id
        targets = parameter_targets(envelope, spec["parameters"])
        for key, value in values.items():
            targets[key]["value"] = value
        request = envelope if transient is None else {"thermal_input": envelope, "transient": transient}
        raw = encode(request)
        remaining -= len(raw)
        if len(raw) > MAX_BYTES or remaining <= 0:
            reject("campaign_artifact_budget")
        snapshot_hash = semantic_hash(envelope["model"])
        run_id = f"run-{index:04d}"
        timeout = min(budget["per_run_s"], budget["compute_s"] - (monotonic() - started))
        if timeout <= 0:
            result = {"status": "failed", "code": "campaign_compute_budget"}
        else:
            result = run_worker(worker, mode, raw, timeout, budget["memory_mb"], min(remaining, MAX_BYTES))
        if result.get("status") == "passed" and result.get("model_hash") != snapshot_hash:
            reject("campaign_result_binding")
        remaining -= len(encode(result))
        if remaining < 0:
            reject("campaign_artifact_budget")
        request_hash = write_json(directory / (run_id + "-input.json"), request)
        result_hash = write_json(directory / (run_id + "-result.json"), result)
        records.append(dict(run_id=run_id, name=name, inputs=values, case_id=case_id, model_hash=snapshot_hash,
                            request_sha256=request_hash, result_sha256=result_hash, status=result["status"]))
    if digest(worker.read_bytes()) != worker_hash:
        reject("campaign_worker_changed")
    status = "passed" if all(run["status"] == "passed" for run in records) else "incomplete"
    manifest = dict(version=1, status=status, mode=mode, project_id=source["project_id"], revision=source["revision"],
                    source_model_hash=source_hash, worker_sha256=worker_hash, specification=spec,
                    correlation_order=sorted(spec["parameters"]), latent_correlation=matrix, runs=records)
    if len(encode(manifest)) > min(remaining, MAX_BYTES):
        reject("campaign_artifact_budget")
    # A directory without the final manifest is an incomplete attempt.
    write_json(directory / "campaign.tmp", manifest)
    (directory / "campaign.tmp").rename(directory / "campaign.json")
    return manifest


def temperature_series(result):
    if "nodes" in result:
        return [0], {row["node_id"]: [row["temperature_K"]] for row in result["nodes"]}
    samples = result["samples"]
    if not samples or any(not row["valid"] for row in samples):
        reject("campaign_invalid_samples")
    return [row["time_s"] for row in samples], {
        node: [row["temperature_K"][index] for row in samples]
        for index, node in enumerate(result["node_ids"])
    }


def interpolate(times, values, at):
    index = bisect_left(times, at)
    if index < len(times) and times[index] == at:
        return values[index], [at, at]
    if not 0 < index < len(times):
        reject("campaign_time_outside_grid")
    left, right = times[index - 1:index + 1]
    fraction = (at - left) / (right - left)
    return values[index - 1] + fraction * (values[index] - values[index - 1]), [left, right]


def compare(rows, times, series):
    comparisons = []
    for row in rows:
        if row["node"] not in series:
            reject("campaign_sensor_mapping")
        predicted, bracket = interpolate(times, series[row["node"]], row["time_s"])
        measured = row["value"] + (273.15 if row["unit"] == "degC" else 0)
        comparisons.append(dict(observation=row, measured_K=measured, predicted_K=predicted,
                                bracket_s=bracket, normalized_residual=(predicted - measured) / row["sigma"]))
    return comparisons


def objective(comparisons, split):
    squares = [row["normalized_residual"] ** 2 for row in comparisons if row["observation"]["split"] == split]
    return math.fsum(squares) / len(squares)


def limit_inputs(limits):
    fields(limits, ("version", "nodes"))
    integer(limits["version"], 1, 2**31 - 1)
    nodes = limits["nodes"]
    if not isinstance(nodes, dict) or len(nodes) > 4096:
        reject("campaign_limits")
    for node, limit in nodes.items():
        label(node)
        fields(limit, ("min_K", "max_K", "margin_K"))
        low = number(limit["min_K"], 0)
        high = number(limit["max_K"], low)
        number(limit["margin_K"], 0, (high - low) / 2)
    return nodes


def report_campaign(directory, limits):
    directory = Path(directory)
    nodes = limit_inputs(limits)
    manifest_path = directory / "campaign.json"
    with manifest_path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        reject("campaign_artifact")
    manifest = loads(raw)
    if manifest["version"] != 1 or manifest["mode"] not in ("steady", "transient"):
        reject("campaign_artifact")
    spec = manifest["specification"]
    observations = sensor_rows(spec)
    response = spec.get("sensitivity")
    summaries, sensitivities, responses, sampled = [], {}, {}, []
    baseline, fitted, winner = None, None, None
    run_records = sequence(manifest["runs"], 512)
    if not run_records or len(run_records) * len(nodes) > 65536:
        reject("campaign_report_size")
    for index, run in enumerate(run_records):
        run_id = f"run-{index:04d}"
        if run["run_id"] != run_id:
            reject("campaign_result_binding")
        request = read_json(directory / (run_id + "-input.json"), expected=run["request_sha256"])
        envelope = request["thermal_input"] if manifest["mode"] == "transient" else request
        model = envelope["model"]
        if (semantic_hash(model) != run["model_hash"] or model["project_id"] != manifest["project_id"]
                or model["revision"] != manifest["revision"]):
            reject("campaign_result_binding")
        if index == 0:
            if run["name"] != "baseline" or run["model_hash"] != manifest["source_model_hash"]:
                reject("campaign_result_binding")
            jobs, matrix = schedule(envelope, spec)
            if (len(jobs) != len(run_records) or matrix != manifest["latent_correlation"]
                    or manifest["correlation_order"] != sorted(spec["parameters"])):
                reject("campaign_result_binding")
            source_envelope = envelope
            configuration = request.get("transient")
        if (run["name"], run["inputs"], run["case_id"]) != jobs[index] or request.get("transient") != configuration:
            reject("campaign_result_binding")
        expected = deepcopy(source_envelope)
        if run["case_id"] is not None:
            expected["case_id"] = run["case_id"]
        for name, target in parameter_targets(expected, spec["parameters"]).items():
            target["value"] = run["inputs"][name]
        if expected != envelope:
            reject("campaign_result_binding")
        result = read_json(directory / (run_id + "-result.json"), expected=run["result_sha256"])
        if result["status"] != run["status"]:
            reject("campaign_result_binding")
        summary = dict(run, outcome=result.get("outcome", result.get("reason", result.get("code"))))
        summaries.append(summary)
        if result["status"] != "passed":
            continue
        if result["model_hash"] != run["model_hash"]:
            reject("campaign_result_binding")
        times, series = temperature_series(result)
        summary["limits"] = []
        for node, limit in nodes.items():
            if node not in series:
                reject("campaign_limit_mapping")
            values = series[node]
            low, high = min(values), max(values)
            margin = min(low - limit["min_K"], limit["max_K"] - high)
            summary["limits"].append(dict(node=node, min_K=low, max_K=high, available_margin_K=margin,
                                          passed=margin >= limit["margin_K"]))
        summary["diagnostics"] = {key: result[key] for key in (
            "energy_defect_W", "internal_exchange_defect_W", "scaled_residual_norm",
            "scaled_correction_norm", "iterations", "step_count", "backend") if key in result}
        if "samples" in result:
            summary["diagnostics"]["final_run_energy"] = result["samples"][-1]["run_energy"]
        if response and run["name"].startswith(("sensitivity/", "sample/")):
            if response["node"] not in series:
                reject("campaign_sensor_mapping")
            temperature = interpolate(times, series[response["node"]], response["time_s"])[0]
            responses[run["name"]] = temperature
            if run["name"].startswith("sample/"):
                summary["response_K"] = temperature
                sampled.append(temperature)
        if (observations and not run["name"].startswith("sensitivity/")
                and run["case_id"] == source_envelope.get("case_id")):
            compared = compare(observations, times, series)
            score = objective(compared, "training")
            summary["training_mean_squared_normalized_residual"] = score
            if index == 0:
                baseline = compared
            if winner is None or score < winner[0]:
                winner, fitted = (score, run_id), compared
    for name, param in spec["parameters"].items():
        if "step" not in param:
            continue
        keys = [f"sensitivity/{name}/{suffix}" for suffix in ("minus", "plus", "half_minus", "half_plus")]
        if any(key not in responses for key in keys):
            sensitivities[name] = {"status": "incomplete", "step": param["step"]}
            continue
        minus, plus, half_minus, half_plus = (responses[key] for key in keys)
        step = param["step"]
        central = (plus - minus) / (2 * step)
        refined = (half_plus - half_minus) / step
        sensitivities[name] = dict(step=step, derivative=central, refined_derivative=refined,
                                   runs=[run["run_id"] for run in summaries if run["name"] in keys],
                                   status="passed" if math.isclose(
                                       central, refined, abs_tol=response["absolute_tolerance"],
                                       rel_tol=response["relative_tolerance"]) else "failed")
    fit = None
    if observations:
        fit = {"status": "incomplete"}
        if baseline is not None and fitted is not None:
            selected = next(run for run in summaries if run["run_id"] == winner[1])
            fit = dict(status="complete", baseline_run="run-0000", fitted_run=winner[1],
                       parameter_changes={key: {"before": value, "after": selected["inputs"][key]}
                                          for key, value in summaries[0]["inputs"].items()
                                          if value != selected["inputs"][key]},
                       rationale="Lowest training mean squared uncertainty-normalized residual among successful bounded candidates. Ties retain the first candidate.",
                       interpolation="linear within each immutable result time grid",
                       baseline=baseline, fitted=fitted,
                       metrics={name: {split: objective(rows, split) for split in ("training", "holdout")}
                                for name, rows in (("baseline", baseline), ("fitted", fitted))})
    uncertainty = dict(requested=spec["samples"], successful=len(sampled), mean_K=fmean(sampled),
                       population_stddev_K=pstdev(sampled), min_K=min(sampled), max_K=max(sampled)) if sampled else None
    model = source_envelope["model"]
    status = "passed" if all(run["status"] == "passed" for run in summaries) else "incomplete"
    if status != manifest["status"]:
        reject("campaign_result_binding")
    return dict(campaign_sha256=digest(raw), status=status, project_id=manifest["project_id"], revision=manifest["revision"],
                source_model_hash=manifest["source_model_hash"], worker_sha256=manifest["worker_sha256"],
                limits=limits, limits_sha256=digest(encode(limits)), configuration=configuration,
                assumptions=model.get("assumptions", []), limitations=model.get("limitations", []),
                source_maps=model.get("source_maps", []), mappings=model.get("mappings", []),
                fidelity_losses=spec.get("fidelity_losses", []),
                specification=spec, latent_correlation=manifest["latent_correlation"],
                correlation_order=manifest["correlation_order"], runs=summaries,
                sensitivity=sensitivities, uncertainty=uncertainty, correlation=fit)
