# SPDX-License-Identifier: MIT OR Apache-2.0
"""Independent geometry-only reconstruction of reviewed TD geometry."""
import math

from fcst_contracts.spatial import determinant

from .core import Limits, reject
from .td_filer import expression_is_constant
from .td_geometry import (BrickPayload, CurvedSolidPayload, CylinderPayload, DiskPayload,
                          LinearSolidPayload, RectangleEnvelope, RectanglePayload, SpherePayload)
from .td_node import NodePayload


LENGTH_UNITS = {'m': 1.0, 'cm': 0.01, 'mm': 0.001, 'ft': 0.3048, 'in': 0.0254}


def _frame(origin, axes, transform, scale):
    if (any(abs(sum(x * y for x, y in zip(a, b)) - (i == j)) > 1e-9
            for i, a in enumerate(axes) for j, b in enumerate(axes)) or determinant(axes) <= 0):
        reject('td_geometry_basis')
    selectors = transform['selectors']
    if any(axis not in (0, 1, 2) for axis in selectors):
        reject('td_geometry_rotation_axis')
    if any(not expression_is_constant(e) for e in transform['expressions']):
        reject('td_geometry_dynamic_transform')

    def world(vector):
        return tuple(sum(value * basis[component] for value, basis in zip(vector, axes)) for component in range(3))

    # The stored local transform is [R1 R2 R3, translation]. It is composed
    # on the right of the drawing basis. Rotation magnitudes are in degrees.
    translation = world(tuple(x * scale for x in transform['values'][:3]))
    origin = tuple(x * scale + offset for x, offset in zip(origin, translation))
    rotations = []
    for selector, angle in reversed(tuple(zip(selectors, transform['values'][3:]))):
        angle = math.radians(angle)
        rotations.append(((selector + 1) % 3, (selector + 2) % 3, math.cos(angle), math.sin(angle)))
    rotated = []
    for axis in range(3):
        vector = [float(i == axis) for i in range(3)]
        for j, k, c, s in rotations:
            vector[j], vector[k] = c * vector[j] - s * vector[k], s * vector[j] + c * vector[k]
        rotated.append(world(vector))
    return origin, rotated


def primitive_grid(payload, length_unit):
    """Return SI local partitions and the world frame for a constant primitive."""
    if not isinstance(payload, RectanglePayload):
        reject('td_geometry_complete_profile_required')
    if isinstance(payload, (CurvedSolidPayload, DiskPayload)):
        reject('td_geometry_curved_mesh_unmapped')
    if isinstance(payload, LinearSolidPayload):
        reject('td_linear_solid_physics_unmapped')
    if not isinstance(length_unit, str) or length_unit not in LENGTH_UNITS:
        reject('td_geometry_length_unit')
    fields = payload.fields
    attributes = fields['attributes']
    solid = isinstance(payload, BrickPayload)
    dimensions = 3 if solid else 2
    expressions = attributes['parameter_expressions'] if solid else fields['parameter_expressions']
    if len(expressions) != dimensions or any(not expression_is_constant(e) for e in expressions):
        reject('td_geometry_dynamic_size')
    scale = LENGTH_UNITS[length_unit]
    sizes = tuple(v * scale for v in fields['serialized_parameters'][:dimensions])
    if any(not math.isfinite(size) or size <= 0 for size in sizes):
        reject('td_geometry_size_range')
    coordinates = []
    for size, subdivision in zip(sizes, attributes['subdivision']):
        coordinates.append(tuple(cut * size for cut in _subdivision(subdivision)))
    if not solid:
        coordinates.append((0.0,))
    transform = attributes['mesh_controls'] if solid else fields['mesh_controls']
    origin, axes = _frame(fields['origin'], fields['axes'], transform, scale)
    return coordinates, origin, axes


def world_point(origin, axes, coordinates):
    position = tuple(offset + sum(axis[i] * distance for axis, distance in zip(axes, coordinates))
                     for i, offset in enumerate(origin))
    if not all(math.isfinite(value) for value in position):
        reject('td_geometry_coordinate_range')
    return position


def _subdivision(subdivision):
    cuts = subdivision['boundaries']
    if (subdivision['mode'] != 0 or not expression_is_constant(subdivision['expression'])
            or len(cuts) < 2 or cuts[0] != 0 or cuts[-1] != 1
            or any(left >= right for left, right in zip(cuts, cuts[1:]))):
        reject('td_geometry_subdivision_unmapped')
    return cuts


def _azimuth_cuts(start, end, cuts):
    span = end - start
    if not 0 < span <= math.tau + 1e-12:
        reject('td_geometry_angle_range')
    closed = math.isclose(span, math.tau, abs_tol=1e-12, rel_tol=0)
    # Reduce the starting azimuth before interpolation. Keep the original span.
    reduced_start = math.remainder(start, math.tau)
    values = []
    for left, right in zip(cuts, cuts[1:]):
        steps = max(1, math.ceil((right - left) * span / (math.pi / 8)))
        values.extend(reduced_start + span * (left + (right - left) * j / steps) for j in range(steps))
    if not closed:
        values.append(end if start == reduced_start else reduced_start + span)
    return values, closed


def _curved_boundary(payload, length_unit, face_limit):
    if not isinstance(length_unit, str) or length_unit not in LENGTH_UNITS:
        reject('td_geometry_length_unit')
    scale = LENGTH_UNITS[length_unit]
    fields, solid = payload.fields, isinstance(payload, CurvedSolidPayload)
    attrs = fields['attributes']
    parameters = fields['serialized_parameters']
    expressions = attrs['parameter_expressions'] if solid else fields['parameter_expressions']
    width = 6 if isinstance(payload, SpherePayload) else 5 if solid else 4
    if len(expressions) != width or any(not expression_is_constant(e) for e in expressions):
        reject('td_geometry_dynamic_size')
    if any(parameters[width:]):
        reject('td_geometry_curved_parameters_unmapped')
    partitions = tuple(_subdivision(row) for row in attrs['subdivision'])
    # Curved primitives store angular and radial subdivisions first. The third
    # solid direction is height (cylinder) or polar angle (sphere).
    if isinstance(payload, CylinderPayload):
        height, inner, outer, start, end = parameters[:5]
        if height <= 0:
            reject('td_geometry_size_range')
        vertical = tuple(c * height * scale for c in partitions[2])
    else:
        inner, outer, start, end = parameters[:4]
        if isinstance(payload, SpherePayload):
            low, high = parameters[4:6]
            if not 0 <= low < high <= math.pi:
                reject('td_geometry_angle_range')
            vertical, _ = _azimuth_cuts(low, high, partitions[2])
        else:
            vertical = (0.0,)
    if not 0 <= inner < outer:
        reject('td_geometry_size_range')
    radii = tuple((inner + (outer - inner) * c) * scale for c in partitions[1])
    if any(a >= b for a, b in zip(radii, radii[1:])):
        reject('td_geometry_coordinate_precision')
    azimuths, closed = _azimuth_cuts(start, end, partitions[0])
    frame = attrs['mesh_controls'] if solid else fields['mesh_controls']
    origin, axes = _frame(fields['origin'], fields['axes'], frame, scale)
    limits = (len(radii) - 1, len(azimuths) if closed else len(azimuths) - 1, len(vertical) - 1)
    radial, angular, axial = limits
    sphere = isinstance(payload, SpherePayload)
    end_caps = sum(not sphere or level not in (0, math.pi) for level in (vertical[0], vertical[-1]))
    face_count = (axial * angular * (1 + (inner > 0)) + radial * angular * end_caps
                  + (0 if closed else 2 * radial * axial)) if solid else radial * angular
    if face_count > face_limit:
        reject('td_geometry_mesh_limit')
    vertices, faces, lookup = [], [], {}

    def vertex(index):
        r, a, z = index
        radial, level = radii[r], vertical[z]
        at_pole = sphere and level in (0, math.pi)
        if radial == 0 or at_pole:
            a = 0
        if radial == 0 and sphere:
            z = 0
        key = r, a % len(azimuths), z
        if key not in lookup:
            angle = azimuths[key[1]]
            if sphere:
                ring = 0.0 if at_pole else radial * math.sin(level)
                axial = radial * math.cos(level)
            else:
                ring, axial = radial, level
            lookup[key] = len(vertices)
            vertices.append(world_point(origin, axes, (ring * math.cos(angle), ring * math.sin(angle), axial)))
        return lookup[key]

    for fixed in (range(3) if solid else (2,)):
        if fixed == 1 and closed:
            continue
        u, v = (fixed + 1) % 3, (fixed + 2) % 3
        for layer in ((0, limits[fixed]) if solid else (0,)):
            for j in range(limits[v]):
                for i in range(limits[u]):
                    corners = []
                    for du, dv in ((0, 0), (1, 0), (1, 1), (0, 1)):
                        index = [0, 0, 0]
                        index[fixed], index[u], index[v] = layer, i + du, j + dv
                        corners.append(vertex(index))
                    face = tuple(dict.fromkeys(corners))
                    if len(face) >= 3:
                        if len(faces) == face_limit:
                            reject('td_geometry_mesh_limit')
                        # (radius, azimuth, polar angle) is left-handed.
                        reverse = sphere != (solid and layer == 0)
                        faces.append(face[::-1] if reverse else face)
    # A degenerate polar face can create an unused vertex at the centre.
    used = sorted({point for face in faces for point in face})
    compact = {old: new for new, old in enumerate(used)}
    points = [vertices[index] for index in used]
    if not faces or len(set(points)) != len(points):
        reject('td_geometry_coordinate_precision')
    return points, [tuple(compact[index] for index in face) for face in faces]


_LINEAR_SOLID_FACES = {
    'brick': ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)),
    'wedge': ((0, 2, 1), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)),
}


def _linear_solid_boundary(payload, nodes, length_unit, face_limit):
    if not isinstance(length_unit, str) or length_unit not in LENGTH_UNITS:
        reject('td_geometry_length_unit')
    template = _LINEAR_SOLID_FACES[payload.shape]
    if face_limit < len(template):
        reject('td_geometry_mesh_limit')
    handles = payload.fields['node_handles']
    if nodes is None or any(handle not in nodes for handle in handles):
        reject('td_linear_solid_missing_node')
    fields = [nodes[handle].fields for handle in handles]
    if any(any(node['offsets']) for node in fields):
        reject('td_linear_solid_node_offset_unmapped')
    scale = LENGTH_UNITS[length_unit]
    points = [tuple(value * scale for value in node['basis'][0]) for node in fields]
    if len(set(points)) != payload.node_count or any(not math.isfinite(v) for point in points for v in point):
        reject('td_geometry_coordinate_precision')

    def delta(point, origin):
        return tuple(a - b for a, b in zip(point, origin))

    directions = (1, 3, 4) if payload.shape == 'brick' else (1, 2, 3)
    orientation = determinant(tuple(delta(points[i], points[0]) for i in directions))
    if not math.isfinite(orientation) or orientation == 0:
        reject('td_linear_solid_invalid_cell')
    faces = [face if orientation > 0 else face[::-1] for face in template]
    offsets = [delta(point, points[0]) for point in points]
    center = tuple(value + sum(offset[i] / len(points) for offset in offsets) for i, value in enumerate(points[0]))
    for first, *rest in faces:
        for j, k in zip(rest, rest[1:]):
            volume = determinant((delta(points[first], center), delta(points[j], center), delta(points[k], center)))
            if not math.isfinite(volume) or volume <= 0:
                reject('td_linear_solid_invalid_cell')
    return points, faces


def boundary_mesh(payload, length_unit, *, face_limit=Limits().records, nodes=None):
    """Return SI vertices and outward faces using stored literal partitions."""
    if isinstance(payload, (CurvedSolidPayload, DiskPayload)):
        return _curved_boundary(payload, length_unit, face_limit)
    if isinstance(payload, LinearSolidPayload):
        return _linear_solid_boundary(payload, nodes, length_unit, face_limit)
    coordinates, origin, axes = primitive_grid(payload, length_unit)
    solid = isinstance(payload, BrickPayload)
    counts = tuple(len(axis) - 1 for axis in coordinates)
    if solid:
        face_count = 2 * sum(counts[i] * counts[(i + 1) % 3] for i in range(3))
    else:
        face_count = counts[0] * counts[1]
    if face_count > face_limit:
        reject('td_geometry_mesh_limit')

    vertices, faces, lookup = [], [], {}

    def vertex(index):
        if index not in lookup:
            lookup[index] = len(vertices)
            vertices.append(world_point(origin, axes, tuple(cuts[j] for cuts, j in zip(coordinates, index))))
        return lookup[index]

    for fixed in (range(3) if solid else (2,)):
        u, v = (fixed + 1) % 3, (fixed + 2) % 3
        for layer in ((0, counts[fixed]) if solid else (0,)):
            for j in range(counts[v]):
                for i in range(counts[u]):
                    face = []
                    for du, dv in ((0, 0), (1, 0), (1, 1), (0, 1)):
                        index = [0, 0, 0]
                        index[fixed], index[u], index[v] = layer, i + du, j + dv
                        face.append(vertex(tuple(index)))
                    if solid and layer == 0:
                        face.reverse()
                    faces.append(tuple(face))
    if len(set(vertices)) != len(vertices):
        reject('td_geometry_coordinate_precision')
    return vertices, faces


def selected_geometry(staged, handles, *, inventory=None):
    """Resolve an explicit or complete primitive selection against the DWG."""
    from .independent_td import DwgPreview
    from .td_decode import GEOMETRY_CLASSES, UNMAPPED_GEOMETRY_CLASSES, decode_drawing

    if not isinstance(staged, DwgPreview):
        reject('independent_td_preview_required')
    selected = set(handles)
    if len(selected) != len(handles):
        reject('td_geometry_duplicate_handle')
    if inventory is None:
        inventory = decode_drawing(staged.snapshot)
    geometry = {p.record['handle']: p for p in inventory.payloads if isinstance(p, (RectangleEnvelope, RectanglePayload))}
    if not selected:
        geometry_classes = {row['number'] for row in staged.snapshot.native['classes']
                            if row['cppname'] in GEOMETRY_CLASSES or row['cppname'] in UNMAPPED_GEOMETRY_CLASSES}
        selected = {row['handle'] for row in staged.snapshot.native['objects'] if row['type'] in geometry_classes}
    if not selected or not selected <= geometry.keys():
        reject('td_geometry_selection')
    return [(handle, geometry[handle]) for handle in sorted(selected)]


def render_geometry(staged, length_unit, handles=()):
    """Build a bounded OBJ with drawing handles and no thermal assignments."""
    from .independent_td import DwgPreview
    from .td_decode import decode_drawing

    if not isinstance(staged, DwgPreview):
        reject('independent_td_preview_required')
    inventory = decode_drawing(staged.snapshot)
    nodes = {p.record['handle']: p for p in inventory.payloads if isinstance(p, NodePayload)}
    lines = ['# FCST TD geometry-only export. Coordinates in metres.']
    vertices = faces = triangles = 0
    geometry = selected_geometry(staged, handles, inventory=inventory)
    for handle, payload in geometry:
        points, boundary = boundary_mesh(payload, length_unit, face_limit=Limits().records - faces, nodes=nodes)
        kind = payload.shape if isinstance(payload, CurvedSolidPayload) else (
            'disk' if isinstance(payload, DiskPayload) else 'brick' if isinstance(payload, BrickPayload)
            else f'linear_{payload.shape}' if isinstance(payload, LinearSolidPayload) else 'rectangle')
        lines.append(f'o td_{kind}_{handle}')
        lines.extend('v ' + ' '.join(format(x, '.17g') for x in point) for point in points)
        lines.extend('f ' + ' '.join(str(vertices + index + 1) for index in face) for face in boundary)
        vertices += len(points)
        faces += len(boundary)
        triangles += sum(len(face) == 3 for face in boundary)
    staged.original.check_current()
    raw = ('\n'.join(lines) + '\n').encode('ascii')
    return raw, {'objects': len(geometry), 'vertices': vertices, 'quads': faces - triangles, 'triangles': triangles, 'length_unit': 'm',
                 'scope': 'geometry-only', 'vendor_runtime_required': False, 'qualified': False}
