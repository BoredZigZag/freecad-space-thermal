# SPDX-License-Identifier: MIT OR Apache-2.0
"""Versioned vessel-network inputs and results in the portable project store."""
from hashlib import sha256
import math
import re
import uuid

from fcst_contracts import loads, verify_artifact
from .persistence import encode, reject, semantic_hash

PREFIX = "advanced-physics/vessel-network/"
FORMAT = "fcst-vessel-network/1"
WORKER_LIMIT = 1048576


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() <= set(required) | set(optional):
        reject("network_run_format")


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _integer(value):
    return _number(value) and int(value) == value


def _request_shape(request):
    _keys(request, ("schema_version", "maximum_step_s", "properties", "vessels", "links", "schedule"))
    if not _integer(request["schema_version"]) or request["schema_version"] != 1:
        reject("network_run_format")
    counts = (("vessels", 2, 64), ("links", 1, 256), ("schedule", 1, 256))
    for field, minimum, maximum in counts:
        if not isinstance(request[field], list) or not minimum <= len(request[field]) <= maximum:
            reject("network_run_format")
    if not _number(request["maximum_step_s"]) or request["maximum_step_s"] <= 0:
        reject("network_run_format")
    for node in request["vessels"]:
        _keys(node, ("volume_m3", "initial_mass_kg", "initial_internal_energy_J", "initial_wall_temperature_K",
                     "wall_capacity_J_K", "wall_conductance_W_K"))
        if not all(_number(v) for v in node.values()):
            reject("network_run_format")
    for link in request["links"]:
        _keys(link, ("from", "to", "conductance_kg_s_Pa"), ("inertance_Pa_s2_kg", "initial_flow_kg_s"))
        if (not all(_integer(link[k]) and 0 <= link[k] < len(request["vessels"]) for k in ("from", "to"))
                or link["from"] == link["to"] or not all(_number(v) for v in link.values())):
            reject("network_run_format")
    props = request["properties"]
    if not isinstance(props, dict):
        reject("network_run_format")
    if props.get("kind") == "ideal_gas":
        _keys(props, ("kind", "gas_constant_J_kg_K", "cv_J_kg_K"))
        if not all(_number(props[k]) for k in ("gas_constant_J_kg_K", "cv_J_kg_K")):
            reject("network_run_format")
    elif props.get("kind") == "saturation_table":
        _keys(props, ("kind", "points"))
        _points(props["points"], ("pressure_Pa", "temperature_K", "liquid_volume_m3_kg",
                                  "vapor_volume_m3_kg", "liquid_energy_J_kg", "vapor_energy_J_kg"), 2, 256)
    elif props.get("kind") == "volume_energy_table":
        _keys(props, ("kind", "volumes_m3_kg", "energies_J_kg", "points"))
        for key in ("volumes_m3_kg", "energies_J_kg"):
            axis = props[key]
            if not isinstance(axis, list) or not 2 <= len(axis) <= 64 or not all(_number(x) for x in axis):
                reject("network_run_format")
        count = len(props["volumes_m3_kg"])*len(props["energies_J_kg"])
        _points(props["points"], ("pressure_Pa", "temperature_K", "phase_coordinate"), count, count)
    else:
        reject("network_run_format")
    times = [0.]
    for interval in request["schedule"]:
        _keys(interval, ("duration_s", "wall_power_W", "opening"))
        dt = interval["duration_s"]
        if not _number(dt) or dt <= 0 or not math.isfinite(times[-1]+dt) or times[-1]+dt <= times[-1]:
            reject("network_run_format")
        for field, reference in (("wall_power_W", "vessels"), ("opening", "links")):
            values = interval[field]
            if not isinstance(values, list) or len(values) != len(request[reference]) or not all(_number(x) for x in values):
                reject("network_run_format")
        times.append(times[-1]+dt)
    return times


def _points(points, fields, minimum, maximum):
    if not isinstance(points, list) or not minimum <= len(points) <= maximum:
        reject("network_run_format")
    for point in points:
        _keys(point, fields)
        if not all(_number(v) for v in point.values()):
            reject("network_run_format")


def _validate_result(request, result, times):
    _keys(result, ("status", "schema_version", "execution_mode", "source_revision", "input_sha256", "samples"))
    if (result["status"] != "passed" or not _integer(result["schema_version"]) or result["schema_version"] != 1
            or result["execution_mode"] != "fcst_native" or not isinstance(result["source_revision"], str)
            or not re.fullmatch(r"[0-9a-f]{40}|uncommitted", result["source_revision"])):
        reject("network_run_format")
    if result["input_sha256"] != sha256(encode(request)).hexdigest():
        reject("network_run_input_mismatch")
    if not isinstance(result["samples"], list) or len(result["samples"]) != len(times):
        reject("network_run_format")
    for sample, time in zip(result["samples"], times, strict=True):
        _keys(sample, ("time_s", "mass_defect_kg", "energy_defect_J", "vessels", "link_flow_kg_s"))
        if (not all(_number(sample[k]) for k in ("time_s", "mass_defect_kg", "energy_defect_J"))
                or sample["time_s"] != time or not isinstance(sample["vessels"], list)
                or len(sample["vessels"]) != len(request["vessels"])
                or not isinstance(sample["link_flow_kg_s"], list)
                or len(sample["link_flow_kg_s"]) != len(request["links"])
                or not all(_number(q) for q in sample["link_flow_kg_s"])):
            reject("network_run_format")
        for node in sample["vessels"]:
            positive = ("mass_kg", "wall_temperature_K", "pressure_Pa", "temperature_K")
            _keys(node, (*positive, "internal_energy_J", "quality"), ("phase",))
            quality = node["quality"]
            if (not all(_number(node[k]) and node[k] > 0 for k in positive) or not _number(node["internal_energy_J"])
                    or (quality is not None and (not _number(quality) or not 0 <= quality <= 1))
                    or ("phase" in node and (node["phase"] not in ("liquid", "vapor", "saturated")
                                            or (node["phase"] == "saturated") != (quality is not None)))):
                reject("network_run_format")


def validate_network_run(value, model, path, data):
    _keys(value, ("format", "project_id", "revision", "semantic_hash", "request", "result"))
    if value["format"] != FORMAT or path != PREFIX + sha256(data).hexdigest() + ".json":
        reject("network_run_format")
    revision, digest = value["revision"], value["semantic_hash"]
    if (value["project_id"] != model["project_id"] or not _integer(revision)
            or not 0 <= revision <= model["revision"] or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or (revision == model["revision"] and digest != semantic_hash(model))):
        reject("network_run_snapshot_mismatch")
    request = value["request"]
    times = _request_shape(request)
    if len(encode(request)) > WORKER_LIMIT:
        reject("network_run_format")
    if value["result"] is not None:
        _validate_result(request, value["result"], times)


def store_network_run(store, request, result=None, *, expected_revision=None):
    """Store a request or a run from the exact canonical request bytes."""
    model = store.snapshot()
    if expected_revision is not None and expected_revision != model["revision"]:
        reject("stale_revision")
    data = encode(dict(format=FORMAT, project_id=model["project_id"], revision=model["revision"],
                       semantic_hash=semantic_hash(model), request=request, result=result))
    path = PREFIX + sha256(data).hexdigest() + ".json"
    artifact_id = str(uuid.uuid4())
    store.add_artifact(artifact_id, "evidence", path, data, expected_revision=model["revision"])
    return artifact_id


def load_network_run(package, artifact_id):
    """Retrieve a validated request and its optional result from a package."""
    for record in package.manifest["artifacts"]:
        path = record["artifact"]["path"]
        if record["id"] == artifact_id and record["role"] == "evidence" and path.startswith(PREFIX):
            data = package.files[path]
            verify_artifact(record["artifact"], data)
            value = loads(data)
            validate_network_run(value, package.model, path, data)
            return value
    reject("network_run_missing")
