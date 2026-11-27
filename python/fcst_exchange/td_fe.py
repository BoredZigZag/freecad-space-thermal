# SPDX-License-Identifier: MIT OR Apache-2.0
"""Bind saved first-order TD finite elements to the native conduction mesh."""
from hashlib import sha256
from itertools import product
import math

from fcst_app.discretization import MeshRegion, from_regions, identity
from fcst_contracts import canonical
from fcst_contracts.spatial import determinant

from .core import Limits, reject
from .td_decode import decode_drawing
from .td_filer import expression_is_constant
from .td_geometry import LinearShellPayload, LinearSolidPayload
from .td_geometry_mesh import _element_points, selected_geometry
from .td_node import NodePayload
from .td_spatial import _constant_assignment, material_input
from .td_spatial_material import bind_profile, material_profile, positive
from .td_spatial_source import TEMPERATURE_UNITS, saved_boundary_temperature


TOPOLOGY = {'tri': 'tri3', 'quad': 'quad4', 'tetra': 'tet4', 'brick': 'hex8'}
SHELL_CORNERS = ((-1,-1), (1,-1), (1,1), (-1,1))
SOLID_CORNERS = tuple((*p, sign) for sign in (-1, 1) for p in SHELL_CORNERS)
IDENTITY_AXES = ((1,0,0), (0,1,0), (0,0,1))


def _difference(a, b):
    return tuple(x-y for x, y in zip(a,b))


def _cross(a, b):
    return tuple(a[(i+1)%3]*b[(i+2)%3] - a[(i+2)%3]*b[(i+1)%3] for i in range(3))


def _product_element_measure(points, thickness):
    shell = len(points) == 4
    corners = SHELL_CORNERS if shell else SOLID_CORNERS
    dimension = len(corners[0])
    relative = [_difference(p, points[0]) for p in points]
    if shell:
        normal = _cross(relative[1], relative[3])
        area = positive(math.hypot(*normal))
        if any(abs(sum(x*y for x,y in zip(p,normal))) > 1e-10 * area * max(1, math.hypot(*p)) for p in relative):
            reject('td_fe_nonplanar')

    def sample(location):
        shape = []
        jacobian = [[0.0]*3 for _ in range(dimension)]
        for signs, delta in zip(corners, relative):
            factors = [(1+s*x)/2 for s,x in zip(signs,location)]
            shape.append(math.prod(factors))
            for axis in range(dimension):
                weight = signs[axis] * math.prod(factors[j] for j in range(dimension) if j != axis) / 2
                for j in range(3):
                    jacobian[axis][j] += weight*delta[j]
        if shell:
            surface = _cross(*jacobian)
            if sum(x*y for x,y in zip(surface,normal)) <= 0:
                reject('td_fe_inverted')
            measure = math.hypot(*surface) * thickness
        else:
            measure = determinant(jacobian)
            if measure <= 0:
                reject('td_fe_inverted')
        return shape, positive(measure)

    for location in product((-1,0,1), repeat=dimension):
        sample(location)
    nodal = [0.0]*len(points)
    g = 1/math.sqrt(3)
    for location in product((-g,g), repeat=dimension):
        shape, measure = sample(location)
        for i, weight in enumerate(shape):
            nodal[i] += positive(weight*measure)
    return nodal


def _measure(topology, points, thickness, keys):
    if topology == 'tri3':
        a, b = (_difference(p, points[0]) for p in points[1:])
        nodal = [positive(math.hypot(*_cross(a,b))*thickness/6)]*3
    elif topology == 'tet4':
        volume = determinant([_difference(p, points[0]) for p in points[1:]])/6
        if volume < 0:
            points[1],points[2] = points[2],points[1]
            keys[1],keys[2] = keys[2],keys[1]
        nodal = [positive(abs(volume)/4)]*4
    else:
        nodal = _product_element_measure(points, thickness)
    return positive(math.fsum(nodal)), nodal


def _material_assignment(payload, scale, mesh_importers):
    fields = payload.fields
    attrs = fields['attributes']
    if isinstance(payload, LinearShellPayload):
        if fields['extra_points'] or any(r['target'] not in mesh_importers for r in fields['references'] if r['target']):
            reject('td_fe_shell_extra_geometry')
        return _constant_assignment(payload, scale)
    if ('modifiers' not in attrs or attrs['modifiers'] is not None or attrs['point_values']
            or attrs['selector'] != 1 or attrs.get('additional_selector',0) != 0
            or not expression_is_constant(attrs['expression'])
            or any(r['target'] for key in ('references_a','references_b','references_c') for r in attrs[key])):
        reject('td_fe_solid_material_mode')
    return attrs['names'][0], 0.0, (1,)*4


def prepare_elements(staged, properties, length_unit, *, temperature, temperature_range, handles=(),
                     face_load_handle=None, power_unit=None, node_temperature_unit=None):
    geometry = selected_geometry(staged, handles)
    scale, property_revision, entries = material_input(staged, properties, length_unit, temperature, temperature_range)
    if face_load_handle is not None or power_unit is not None:
        reject('td_fe_source_load_unmapped')
    if node_temperature_unit is not None and node_temperature_unit not in TEMPERATURE_UNITS:
        reject('td_geometry_temperature_unit')
    source = staged.original.source_hash
    selection = sha256(canonical([source, property_revision, length_unit, [str(h) for h, _ in geometry],
                                  node_temperature_unit or ''])).hexdigest()
    identifiers = set()
    for _, payload in geometry:
        if (not isinstance(payload,(LinearShellPayload,LinearSolidPayload)) or payload.order != 1
                or payload.shape not in TOPOLOGY or payload.fields.get('additional_node_selector')):
            reject('td_fe_topology_unmapped')
        identifiers.update(payload.fields['node_handles'])
    if sum(len(payload.fields['node_handles']) for _, payload in geometry)*172 > Limits().file_bytes:
        reject('td_spatial_input_limit')
    nodes = {p.record['handle']: p for p in decode_drawing(staged.snapshot, handles=identifiers).payloads
             if isinstance(p,NodePayload)}
    if nodes.keys() != identifiers:
        reject('td_element_missing_node')
    spaces, shared_points, node_sources, seen = {}, {}, [], set()
    for ref,node in sorted(nodes.items()):
        f = node.fields
        name, number = f['submodel'], f['identifier']
        key = name.casefold(), number
        if key in seen or len(name)>256:
            reject('td_spatial_source_node_identity_collision')
        seen.add(key)
        fixed = saved_boundary_temperature(f, node_temperature_unit, temperature_range, 'td_fe_saved_node_mode')
        space = spaces.setdefault(key[0], dict(id=identity((source,'td-fe-submodel',key[0])), kind='submodel', label=name))
        point, identifier = (identity((source, f'td-fe-{kind}', ref)) for kind in ('point', 'node'))
        shared_points[ref] = point, identifier, space, fixed
        node_sources.append(dict(namespace='TD.DWG.FE-NODE', handle=str(ref), entity_id=identifier,
                                 submodel_handle=name,node_number=number))
    profiles, bindings, regions, laws, property_sources, elements = {}, {}, [], [], [], []
    importer_types = {c['number'] for c in staged.snapshot.native['classes'] if c['cppname']=='TdFiniteElementMeshImporter'}
    mesh_importers = {row['handle'] for row in staged.snapshot.native['objects'] if row['type'] in importer_types}
    for handle, payload in geometry:
        topology = TOPOLOGY[payload.shape]
        name, thickness, multipliers = _material_assignment(payload, scale, mesh_importers)
        key = name.casefold()
        if key in ('','default') or key not in entries:
            reject('td_spatial_material_missing')
        if key not in profiles:
            profiles[key] = material_profile(key,entries,temperature_range,profiles)
        profile = profiles[key]
        if profile.orthotropic or len(set(multipliers[1:])) != 1:
            reject('td_fe_material_axes_unmapped')
        binding = key, multipliers
        if binding not in bindings:
            identifier = identity(('td-fe-material', property_revision,binding))
            material, _, law, _ = bind_profile(profile,entries[key].name,identifier,IDENTITY_AXES,temperature,multipliers)
            if law:
                laws.append(law)
            bindings[binding] = material
            property_sources.append(dict(namespace='TD.PROPERTIES',handle=identifier,entity_id=identifier))
        points = _element_points(payload,nodes,length_unit)
        keys = list(payload.fields['node_handles'])
        volume,nodal = _measure(topology,points,thickness,keys)
        region = MeshRegion(f'td-fe-{source}-{handle}-',topology,points,[list(range(len(points)))],[volume],nodal,
                            thickness,bindings[binding],point_keys=tuple(keys),cell_nodal_volumes=(nodal,))
        regions.append(region)
        elements.append(dict(namespace='TD.DWG.FE-ELEMENT',handle=str(handle),entity_id=region.identifier('element-0')))
    prefix = 'td-fe-' + selection
    sources = [dict(id=identity(prefix+'-dwg'), version='1.0.0', source_revision=source,
                    source_tool='Thermal Desktop DWG',source_version='AC1032', entries=elements+node_sources),
               dict(id=identity(prefix+'-tdp'), version='1.0.0', source_revision=property_revision,
                    source_tool='Thermal Desktop property text',source_version='UNICODE bracket-tagged profile 1',
                    entries=property_sources)]
    value = from_regions(regions,temperature=temperature,prefix=prefix,source_maps=sources,shared_points=shared_points,
                         material_laws=laws,assumptions=['Shared vertices are identified by their source DWG node handles'],
                         limitations=['Only selected linear elements contribute to conduction and storage',
                                      'Contact, source loads and radiation are excluded'])
    staged.original.check_current()
    return value, dict(formulation='elements',objects=len(regions),materials=len(bindings),points=len(nodes),
                       cells=len(regions),source_nodes=len(nodes),vendor_runtime_required=False,qualified=False)
