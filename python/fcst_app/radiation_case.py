# SPDX-License-Identifier: MIT OR Apache-2.0
"""Resolve portable diffuse radiation inputs for a native case."""
from math import hypot, isclose
from uuid import UUID

from fcst_contracts import loads, normalize, read, verify_artifact
from .arrays import read_arrays
from .persistence import reject


SAMPLING = {"seed": 29, "samples": 16384, "maximum_entries": 4096}


def mission_path(case_id):
    return f"missions/{case_id}.json"


def validate_mission_artifact(raw, model, record, model_artifact_id):
    document = read('mission', loads(raw))
    case_id = document['case_id']
    if (document['project_id'] != model['project_id'] or record['artifact']['path'] != mission_path(case_id)
            or model_artifact_id not in record['dependencies']):
        reject('mission_binding')
    entities = {e['id']: e for e in model['entities']}
    case = entities.get(case_id, {})
    if case.get('kind') != 'case' or case['mode'] != 'transient':
        reject('mission_case')
    environment_id = case['environment_id']
    configs = [e for e in entities.values() if e['kind'] == 'radiation' and e['environment_id'] == environment_id]
    if len(configs) != 1 or configs[0]['method'] != 'diffuse' or entities[environment_id]['time_scale'] != 'TAI':
        reject('mission_case')
    active = set(configs[0]['facet_ids']) - set(configs[0]['excluded_facet_ids'])
    mission = document['mission']
    joints = mission.get('joints', [])
    moving = [key for joint in joints for key in joint['facets']]
    optical = [item['facet_id'] for item in mission.get('case_optics', [])]
    ids = [joint['id'] for joint in joints]
    if (any(len(set(keys)) != len(keys) for keys in (moving, optical, ids))
            or not active or not set(moving + optical) <= active):
        reject('mission_facets')
    return mission


def read_case_mission(manifest, model, case_id, read_artifact):
    path = mission_path(case_id)
    record = next((r for r in manifest['artifacts']
                   if r['role'] == 'mission' and r['artifact']['path'] == path), None)
    if record is None:
        return None
    raw = read_artifact(path)
    verify_artifact(record['artifact'], raw)
    return validate_mission_artifact(raw, model, record, manifest['model_artifact_id'])


def facets(model, read_mesh, selected=None):
    """Resolve triangles in world metres and map each to one thermal node."""
    entities = {e["id"]: e for e in normalize(model)["entities"]}
    meshes = {}
    nodes = sorted(e["id"] for e in entities.values() if e["kind"] == "node")
    node_index = {key: index for index, key in enumerate(nodes)}
    targets = {}
    for mapping in model["mappings"]:
        if mapping["from_id"] in entities and entities[mapping["from_id"]]["kind"] == "facet":
            targets.setdefault(mapping["from_id"], []).append(normalize(mapping))

    result = {}
    for facet in entities.values():
        if facet["kind"] != "facet" or (selected is not None and facet["id"] not in selected):
            continue
        key = facet["id"]
        assignments = targets.get(key, [])
        area = facet["area"]["value"]
        if (len(assignments) != 1 or assignments[0]["weight"] != 1
                or not isclose(assignments[0]["area"]["value"], area, rel_tol=1e-10)):
            reject("radiation_node_mapping")
        node = assignments[0]["to_id"]
        mesh_id = facet["mesh_id"]
        if mesh_id not in meshes:
            mesh = entities[mesh_id]
            frame = entities[mesh["frame_id"]]
            if "parent_id" in frame:
                reject("radiation_nested_frame_unsupported")
            ref = mesh["artifact"]
            raw = read_mesh(ref["path"])
            verify_artifact(ref, raw)
            values = read_arrays(raw)
            if values["role"] != "radiation_mesh":
                reject("radiation_mesh_role")
            arrays = values["arrays"]
            indices = {str(UUID(bytes=bytes(row))): i for i, row in enumerate(arrays["index/entity_uuid"])}
            declared = {e["id"] for e in entities.values() if e.get("mesh_id") == mesh_id}
            if indices.keys() != declared:
                reject("radiation_mesh_identity")
            meshes[mesh_id] = arrays, indices, frame
        arrays, indices, frame = meshes[mesh_id]
        i = indices[key]
        start, end = arrays["connectivity/offsets"][i:i+2]
        if end - start != 3:
            reject("radiation_triangle_required")
        local = arrays["vertices"][arrays["connectivity/vertex_index"][start:end]].tolist()
        a, b, c = local
        u, v = [b[j]-a[j] for j in range(3)], [c[j]-a[j] for j in range(3)]
        normal = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
        magnitude = hypot(*normal)
        if (not isclose(magnitude / 2, area, rel_tol=1e-10)
                or not all(isclose(n / magnitude, expected, abs_tol=1e-10)
                           for n, expected in zip(normal, arrays["normals"][i]))):
            reject("radiation_mesh_geometry")
        points = [[o["value"] + sum(r*x for r, x in zip(row, point))
                   for o, row in zip(frame["origin"], frame["rotation"])] for point in local]
        result[key] = (points, node, node_index[node])
    return result


def transient_request(model, envelope, options, read_mesh, mission=None):
    entities = {e["id"]: e for e in normalize(model)["entities"]}
    case = entities[envelope["case_id"]]
    environment = entities[case["environment_id"]]
    configurations = [e for e in entities.values() if e["kind"] == "radiation" and e["environment_id"] == environment["id"]]
    if (len(configurations) != 1 or (mission is None and environment["solar_flux"]["value"] != 0)
            or environment["time_scale"] != "TAI"
            or any(e["kind"] == "element" or (e["kind"] == "mesh" and e["role"] != "radiation")
                   for e in entities.values())):
        reject("radiation_case_unsupported")
    config = configurations[0]
    selected = set(config["facet_ids"])
    if config["method"] != "diffuse" or len(selected) > 4096:
        reject("radiation_case_unsupported")
    triangles = facets(model, read_mesh, selected)
    resolved = []
    for key, (points, _, node_index) in triangles.items():
        facet = entities[key]
        optics = entities[facet["optics_id"]]
        if optics["specular_fraction"] != 0 or optics["transmissivity"] != 0:
            reject("radiation_optics_unsupported")
        dataset = dict(solar_band="solar", infrared_band="infrared", valid_temperature_K=[0, 10000],
                       condition="unspecified", absolute_uncertainty=[0, 0], provenance=optics["id"])
        optical = dict(solar_absorptance=optics["solar_absorptivity"], ir_emittance=optics["ir_emissivity"],
                       dataset=dataset)
        resolved.append(dict(id=key, surface_id=key, group=facet["mesh_id"], node=node_index, vertices_m=points,
                             front=dict(**optical, active=facet["side"] == "front"),
                             back=dict(**optical, active=facet["side"] == "back")))
    if mission is None:
        start, end = options["start"], options["end"]
        mission = dict(sun_direction_inertial=[0, 0, 1], maximum_interval_s=end-start,
                       attitude=[dict(time_s=t, rotation=[1, 0, 0, 0]) for t in (start, end)])
    return dict(schema_version=1, facets=resolved, sampling=SAMPLING.copy(), mission=mission,
                excluded_facets=config["excluded_facet_ids"], thermal_input=envelope, transient=options)
