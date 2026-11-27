# SPDX-License-Identifier: MIT OR Apache-2.0
"""Bind saved TD finite-difference identities and literal FD brick face power."""
from bisect import bisect_left
import math

from fcst_contracts import BUNDLE

from .core import reject
from .td_decode import decode_drawing
from .td_load import LoadPayload
from .td_node import NodePayload
from .td_writer import load_payload, template_fields


POWER_UNITS = tuple(unit for unit, (dimension, _, _) in BUNDLE['units'].items() if dimension == 'power')

# Marker bits follow the documented XMIN, XMAX, YMIN, YMAX, ZMIN, ZMAX order.
# Each quad is outward-wound in the hex8 point order used by the spatial mesh.
BRICK_FACES = {
    1: (0, False, (0, 4, 7, 3)), 2: (0, True, (1, 2, 6, 5)),
    4: (1, False, (0, 1, 5, 4)), 8: (1, True, (3, 7, 6, 2)),
    16: (2, False, (0, 3, 2, 1)), 32: (2, True, (4, 5, 6, 7)),
}


def saved_node_groups(snapshot, geometry):
    groups = {}
    for handle, payload in geometry:
        primary, secondary = payload.fields['attributes']['references_a']
        handles = tuple(ref['target'] for ref in primary)
        if (not handles or any(not ref for ref in handles) or len(set(handles)) != len(handles)
                or any(ref['target'] for ref in secondary)):
            reject('td_spatial_source_node_references')
        groups[handle] = handles
    requested = {ref for handles in groups.values() for ref in handles}
    nodes = {p.record['handle']: p.fields for p in decode_drawing(snapshot, handles=requested).payloads
             if isinstance(p, NodePayload)}
    if nodes.keys() != requested:
        reject('td_spatial_source_node_missing')
    return {handle: [(ref, nodes[ref]) for ref in handles] for handle, handles in groups.items()}


def node_source_entries(region, grid, handle, records, scale):
    # A complete Cartesian lattice distinguishes a saved vertex from a saved
    # cell center. The latter identifies a conduction element for provenance.
    cuts, origin, axes = grid
    centered = len(records) == len(region.connectivity)
    if not centered and len(records) != len(region.positions):
        reject('td_spatial_source_node_count')
    coordinates = [tuple(a + (b-a)/2 for a, b in zip(axis, axis[1:]))
                   if centered and len(axis) > 1 else axis for axis in cuts]
    spacing = min(b-a for axis in cuts for a, b in zip(axis, axis[1:]))
    for axis in coordinates:
        if len(axis) > 1:
            spacing = min(spacing, min(b-a for a, b in zip(axis, axis[1:])))
    magnitude = max(abs(value) for value in (*origin, *(axis[-1] for axis in cuts)))
    precision = 16 * math.ulp(magnitude)
    tolerance = min(1e-9, spacing / 8)
    if tolerance < precision or tolerance <= 0:
        reject('td_spatial_source_node_precision')

    entries, occupied = [], set()
    for ref, node in records:
        owners = {owner['target'] for owner in node['associations']}
        if owners != {handle} or any(node['offsets']):
            reject('td_spatial_source_node_association')
        if len(node['submodel']) > 256:
            reject('td_spatial_source_node_identity')
        delta = tuple(value * scale - start for value, start in zip(node['basis'][0], origin))
        if any(not math.isfinite(value) or abs(value) > 2 * sum(axis[-1] for axis in cuts) for value in delta):
            reject('td_spatial_source_node_position')
        indices = []
        for axis, basis in zip(coordinates, axes):
            value = math.fsum(x * y for x, y in zip(delta, basis))
            split = bisect_left(axis, value)
            candidates = [i for i in (split-1, split) if 0 <= i < len(axis) and abs(axis[i]-value) <= tolerance]
            if len(candidates) != 1:
                reject('td_spatial_source_node_position')
            indices.append(candidates[0])
        i, j, k = indices
        index = (k * len(coordinates[1]) + j) * len(coordinates[0]) + i
        if index in occupied:
            reject('td_spatial_source_node_position')
        occupied.add(index)
        namespace, target = ('TD.DWG.FD-CELL', 'element') if centered else ('TD.DWG.FD-NODE', 'node')
        entries.append(dict(namespace=namespace, handle=str(ref), entity_id=region.identifier(f'{target}-{index}'),
                            submodel_handle=node['submodel'], node_number=node['identifier']))
    return entries


def face_power(snapshot, load_handle, unit):
    if unit not in POWER_UNITS:
        reject('td_spatial_face_power_unit')
    loads = [p.fields for p in decode_drawing(snapshot, handles={load_handle}).payloads
             if isinstance(p, LoadPayload)]
    if len(loads) != 1:
        reject('td_spatial_face_load_missing')
    fields, = loads
    connections = fields['connections']
    if len(connections) != 1 or connections[0]['kind'] != 'entity-node' or connections[0]['index'] not in BRICK_FACES:
        reject('td_spatial_face_selection')
    connection, = connections
    marker = connection['index']
    target = connection['reference']['target']
    expected = template_fields(load_payload(fields['value'], 1, marker=marker), (target,))
    if any(value != expected[k] for k, value in fields.items()
           if k not in {'common_handles', 'connections', 'name', 'comment'}):
        reject('td_spatial_face_load_mode')
    power = fields['value'] * BUNDLE['units'][unit][1]
    if not math.isfinite(power) or (fields['value'] != 0 and power == 0):
        reject('td_spatial_face_power_range')
    return target, marker, power


def brick_face_surfaces(region, cuts, marker, power, load_handle):
    if region.topology != 'hex8':
        reject('td_spatial_face_load_brick_required')
    axis, maximum, quad = BRICK_FACES[marker]
    nx, ny, nz = (len(partition)-1 for partition in cuts)
    dimensions = (nx, ny, nz)
    plane = dimensions[axis]-1 if maximum else 0
    transverse = tuple(i for i in range(3) if i != axis)
    area = math.prod(cuts[i][-1] - cuts[i][0] for i in transverse)
    if not math.isfinite(area) or area <= 0:
        reject('td_spatial_face_area')
    surfaces = []
    for index, cell in enumerate(region.connectivity):
        indices = (index % nx, (index // nx) % ny, index // (nx * ny))
        if indices[axis] != plane:
            continue
        cell_area = math.prod(cuts[i][indices[i]+1] - cuts[i][indices[i]] for i in transverse)
        triangle_power = power * (cell_area / area) / 2
        if power and triangle_power == 0:
            reject('td_spatial_face_power_range')
        corners = [region.identifier(f'point-{cell[i]}') for i in quad]
        for part, triangle in enumerate(((corners[0], corners[1], corners[2]), (corners[0], corners[2], corners[3]))):
            surfaces.append(dict(id=region.identifier(f'face-{marker}-load-{load_handle}-{index}-{part}'),
                                 kind='power', point_ids=list(triangle), value_SI=triangle_power, ambient_K=0))
    return surfaces
