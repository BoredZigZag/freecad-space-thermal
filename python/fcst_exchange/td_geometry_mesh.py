# SPDX-License-Identifier: MIT OR Apache-2.0
"""Independent geometry-only reconstruction of constant TD rectangles and bricks."""
import math

from fcst_contracts.spatial import determinant

from .core import Limits, reject
from .td_filer import expression_is_constant
from .td_geometry import BrickPayload, RectangleEnvelope, RectanglePayload


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
        cuts = subdivision['boundaries']
        if (subdivision['mode'] != 0 or not expression_is_constant(subdivision['expression'])
                or len(cuts) < 2 or cuts[0] != 0 or cuts[-1] != 1
                or any(left >= right for left, right in zip(cuts, cuts[1:]))):
            reject('td_geometry_subdivision_unmapped')
        coordinates.append(tuple(cut * size for cut in cuts))
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


def boundary_mesh(payload, length_unit, *, face_limit=Limits().records):
    """Return SI vertices and outward quads using stored literal partitions."""
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


def selected_geometry(staged, handles):
    """Resolve an explicit or complete primitive selection against the DWG."""
    from .independent_td import DwgPreview
    from .td_decode import decode_drawing

    if not isinstance(staged, DwgPreview):
        reject('independent_td_preview_required')
    selected = set(handles)
    if len(selected) != len(handles):
        reject('td_geometry_duplicate_handle')
    inventory = decode_drawing(staged.snapshot)
    geometry = {p.record['handle']: p for p in inventory.payloads if isinstance(p, (RectangleEnvelope, RectanglePayload))}
    if not selected:
        geometry_classes = {row['number'] for row in staged.snapshot.native['classes']
                            if row['cppname'] in ('RcRectangle', 'RcFdBrick')}
        selected = {row['handle'] for row in staged.snapshot.native['objects'] if row['type'] in geometry_classes}
    if not selected or not selected <= geometry.keys():
        reject('td_geometry_selection')
    return [(handle, geometry[handle]) for handle in sorted(selected)]


def render_geometry(staged, length_unit, handles=()):
    """Build a bounded OBJ with drawing handles and no thermal assignments."""
    lines = ['# FCST TD geometry-only export. Coordinates in metres.']
    vertices = faces = 0
    geometry = selected_geometry(staged, handles)
    for handle, payload in geometry:
        points, quads = boundary_mesh(payload, length_unit, face_limit=Limits().records - faces)
        kind = 'brick' if isinstance(payload, BrickPayload) else 'rectangle'
        lines.append(f'o td_{kind}_{handle}')
        lines.extend('v ' + ' '.join(format(x, '.17g') for x in point) for point in points)
        lines.extend('f ' + ' '.join(str(vertices + index + 1) for index in face) for face in quads)
        vertices += len(points)
        faces += len(quads)
    staged.original.check_current()
    raw = ('\n'.join(lines) + '\n').encode('ascii')
    return raw, {'objects': len(geometry), 'vertices': vertices, 'quads': faces, 'length_unit': 'm',
                 'scope': 'geometry-only', 'vendor_runtime_required': False, 'qualified': False}
