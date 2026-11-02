# SPDX-License-Identifier: LGPL-2.1-or-later
"""Narrow FEM boundary. Only immutable values leave the application thread."""
import json
import threading
from hashlib import sha256
from fcst_contracts import read
from fcst_contracts.spatial import field_global
from .persistence import encode, reject, semantic_hash


def capability(module, name):
    symbol = getattr(module, name, None)
    if not callable(symbol):
        reject("host_capability_missing")
    return symbol


def assert_thread():
    if threading.current_thread() is not threading.main_thread():
        reject("host_thread")


class DocumentObserver:
    """Keep service truth dirty after direct host edits, topology changes and Undo."""
    def __init__(self, doc, store):
        self.doc, self.store = doc, store

    def slotChangedObject(self, obj, prop):
        if obj.Document == self.doc:
            self.store.mark_host_dirty()

    def slotDeletedObject(self, obj):
        if obj.Document == self.doc:
            self.store.mark_host_dirty()

    def slotCreatedObject(self, obj):
        if obj.Document == self.doc:
            self.store.mark_host_dirty()


def create(doc, value):
    assert_thread()
    import FreeCAD as App
    import Fem
    import ObjectsFem
    value = read("spatial", value)
    analysis = capability(ObjectsFem, "makeAnalysis")(doc, "FCSTAnalysis")
    obj = capability(ObjectsFem, "makeMeshResult")(doc, "FCSTMesh")
    mesh = Fem.FemMesh()
    for i, point in enumerate(value["vertices"], 1):
        mesh.addNode(*(x*1000 for x in point), i)
    for i, cell in enumerate(value["cells"], 1):
        indices = [int(x)+1 for x in cell["vertices"]]
        if cell["topology"] == "tet4":
            mesh.addVolume(indices, i)
        else:
            mesh.addFace(indices, i)
    obj.FemMesh = mesh
    obj.addProperty("App::PropertyString", "FCSTDescriptor", "FCST")
    obj.FCSTDescriptor = encode(value).decode()
    result = capability(ObjectsFem, "makeResultMechanical")(doc, "FCSTResult")
    result.Mesh = obj
    result.NodeNumbers = list(range(1, len(value["vertex_ids"])+1))
    for name, text in (("FCSTVertexIds", json.dumps(value["vertex_ids"])), ("FCSTUnits", "temperature=K;heat_flux=W/m2;frame=global;projection=raw"), ("FCSTModelHash", value["model_hash"])):
        result.addProperty("App::PropertyString", name, "FCST")
        setattr(result, name, text)
    for f in value["fields"]:
        vectors = field_global(value, f["quantity"])
        if f["quantity"] == "temperature":
            result.Temperature = [v[0] for v in vectors]
        else:
            result.HeatFlux = [App.Vector(*v) for v in vectors]
    analysis.addObject(obj)
    analysis.addObject(result)
    doc.recompute()
    return obj, result


def query(result, value, model_hash, sample=0):
    assert_thread()
    value = read("spatial", value)
    if result.FCSTModelHash != model_hash or model_hash != value["model_hash"]:
        reject("stale_result")
    if (json.loads(result.FCSTVertexIds) != value["vertex_ids"] or list(result.NodeNumbers) != list(range(1, len(value["vertex_ids"])+1))
            or result.FCSTUnits != "temperature=K;heat_flux=W/m2;frame=global;projection=raw"):
        reject("host_field_identity")
    observed = {}
    for f in value["fields"]:
        quantity = f["quantity"]
        actual = [[float(v)] for v in result.Temperature] if quantity == "temperature" else [[v.x, v.y, v.z] for v in result.HeatFlux]
        if actual != field_global(value, quantity, sample):
            reject("host_field_values")
        observed[quantity] = actual
    return observed


def reconcile_attachment(old, candidates):
    # The caller must explicitly reassign after split/merge/delete/replacement.
    exact = [c for c in candidates if c == old]
    if len(exact) != 1:
        reject("attachment_reassignment_required")
    return exact[0]


def conduction_input(value, mesh, node_map, element_map, *, length_unit='mm'):
    """Read pinned FEM mesh APIs through explicit host-number/canonical-ID maps.

    Never infer identity from row order, position, nearest face or coincident
    radiation facets. The caller must explicitly reassign after regeneration.
    """
    assert_thread()
    from copy import deepcopy
    from .discretization import read_input,seal
    value=read_input(value)
    if length_unit!='mm':reject('host_mesh_units')
    points={p['id']:p for p in value['spatial']['points']}
    cells={c['element_id']:c for c in value['spatial']['cells']}
    if (set(node_map)!=set(mesh.Nodes) or set(node_map.values())!=set(points)
            or len(node_map)!=len(points) or set(element_map.values())!=set(cells) or len(element_map)!=len(cells)):
        reject('host_mesh_identity')
    available=set(mesh.Volumes)|set(mesh.Faces)
    if not set(element_map)<=available:reject('host_mesh_identity')
    output=deepcopy(value)
    point_hosts={id_:n for n,id_ in node_map.items()}
    element_hosts={id_:n for n,id_ in element_map.items()}
    for p in output['spatial']['points']:
        host=point_hosts[p['id']]
        p['position']=[float(v)*.001 for v in mesh.Nodes[host]]
    for c in output['spatial']['cells']:
        host=element_hosts[c['element_id']]
        indices=list(mesh.getElementNodes(host))
        expected={'tri3':3,'quad4':4,'tet4':4,'hex8':8}[c['topology']]
        if len(indices)!=expected or any(i not in node_map for i in indices):reject('unsupported_element')
        mapped=[node_map[i] for i in indices]
        if mapped!=c['point_ids']:reject('host_mesh_connectivity')
        c['point_ids']=mapped
    # Extraction does not silently authorize changed coordinates or assignments.
    if seal(output)['spatial']['mesh_revision']!=value['spatial']['mesh_revision']:
        reject('attachment_reassignment_required')
    return seal(output)


def edit_through_service(doc, store, actor, scopes, key, payload):
    assert_thread()
    # Mark dirty before any host edit; a failure after service commit cannot claim clean.
    store.mark_host_dirty()
    doc.openTransaction("FCST operation")
    try:
        model = store.snapshot()
        outcome = store.apply(actor, scopes, model["project_id"], model["revision"], key, payload)
        doc.FCSTMesh.FCSTDescriptor = encode({"model_hash": outcome["semantic_hash"]}).decode()
        doc.commitTransaction()
        return outcome
    except Exception:
        doc.abortTransaction()
        raise
