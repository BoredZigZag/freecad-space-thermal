# SPDX-License-Identifier: MIT OR Apache-2.0
"""Independent geometry-only reconstruction of reviewed TD geometry."""
import math
from dataclasses import replace

from fcst_contracts.spatial import determinant

from .core import Limits, reject
from .td_filer import expression_is_constant
from .td_geometry import (BrickPayload, ConeSolidPayload, ConicPayload, CurvedSolidPayload, CylinderPayload,
                          DiskPayload, EllipsoidSolidPayload, LinearShellPayload, LinearSolidPayload,
                          PolygonMeshPayload, RectangleEnvelope, RectanglePayload, SpherePayload)
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
    if isinstance(payload, (ConicPayload, CurvedSolidPayload, DiskPayload)):
        reject('td_geometry_curved_mesh_unmapped')
    if isinstance(payload, (LinearShellPayload, LinearSolidPayload, PolygonMeshPayload)):
        reject('td_element_physics_unmapped')
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


def _azimuth_cuts(start, end, cuts, *, wrap=False):
    span = end - start
    if not math.isfinite(span) or abs(span) > math.tau + 1e-12:
        reject('td_geometry_angle_range')
    if wrap and span <= 0:
        span = span % math.tau or math.tau
    if not span > 0:
        reject('td_geometry_angle_range')
    closed = math.isclose(span, math.tau, abs_tol=1e-12, rel_tol=0)
    # Reduce the starting azimuth before interpolation. Keep the original span.
    reduced_start = math.remainder(start, math.tau)
    values = []
    for left, right in zip(cuts, cuts[1:]):
        steps = max(1, math.ceil((right - left) * span / (math.pi / 8)))
        values.extend(reduced_start + span * (left + (right - left) * j / steps) for j in range(steps))
    if not closed:
        values.append(end if start == reduced_start and end > start else reduced_start + span)
    return values, closed


def _shell_parameters(shape, parameters, cuts):
    """Return two parameter axes, periodic flags and a local point evaluator."""
    if shape == 'parabolic-trough':
        focus, x0, x1, y0, y1 = parameters[:5]
        if not (focus > 0 and x0 < x1 and y0 < y1):
            reject('td_geometry_size_range')
        u = _interval(x0, x1, cuts[0])
        if x0 < 0 < x1 and 0.0 not in u:
            u = tuple(sorted((*u, 0.0)))
        v = _interval(y0, y1, cuts[1])
        return u, v, False, False, lambda x, y: (x, y, (x / focus) * (x / 4))
    if shape == 'offset-paraboloid':
        height, radius, offset, major, minor = parameters[:5]
        if not (min(height, radius, major, minor) > 0 and abs(offset) + max(major, minor) <= radius):
            reject('td_geometry_size_range')
        u, wrap_u = _azimuth_cuts(0, math.tau, cuts[0])
        v = tuple(1 - fraction for fraction in cuts[1])

        def point(a, fraction):
            x = offset + major * fraction * math.cos(a)
            y = minor * fraction * math.sin(a)
            return x, y, height * ((x / radius) ** 2 + (y / radius) ** 2)

        return u, v, wrap_u, False, point
    if shape == 'torus':
        major, minor, start, end, low, high = parameters[:6]
        if not 0 < minor < major:
            reject('td_geometry_size_range')
        u, wrap_u = _azimuth_cuts(start, end, cuts[0], wrap=True)
        v, wrap_v = _azimuth_cuts(low, high, cuts[1], wrap=True)

        def point(a, b):
            radius = major + minor * math.cos(b)
            return radius * math.cos(a), radius * math.sin(a), minor * math.sin(b)

        return u, v, wrap_u, wrap_v, point
    if shape in ('sphere', 'ellipsoid'):
        if shape == 'sphere':
            radius, low, high, start, end = parameters[:5]
            x, y, z = radius, radius, radius
        else:
            x, y, z, low, high, start, end = parameters[:7]
        if not (min(x, y, z) > 0 and -z <= low < high <= z):
            reject('td_geometry_size_range')
        u, wrap_u = _azimuth_cuts(start, end, cuts[0], wrap=True)
        v, _ = _azimuth_cuts(math.asin(low / z), math.asin(high / z), cuts[1])

        def point(a, b):
            ring = 0.0 if abs(b) == math.pi / 2 else math.cos(b)
            return x * ring * math.cos(a), y * ring * math.sin(a), z * math.sin(b)

        return u, v, wrap_u, False, point
    if shape == 'ellipse':
        major, minor, inner, start, end = parameters[:5]
        if not (0 <= inner < major and 0 < minor <= major):
            reject('td_geometry_size_range')
        u, wrap_u = _azimuth_cuts(start, end, cuts[0], wrap=True)
        v = _interval(1.0, inner / major, cuts[1])
        return u, v, wrap_u, False, lambda a, r: (major * r * math.cos(a), minor * r * math.sin(a), 0.0)

    height, base = parameters[:2]
    aspect, scarf = 1.0, 0.0
    if shape == 'elliptic-cylinder':
        aspect = parameters[2] / base if base > 0 else 0
        top = base
        start, end = parameters[3:5]
    elif shape == 'cylinder':
        top = base
        start, end = parameters[2:4]
    elif shape == 'elliptic-cone':
        top, aspect, start, end = parameters[2:6]
    elif shape == 'scarfed-cylinder':
        top = base
        start, end, scarf = parameters[2:5]
    elif shape == 'scarfed-cone':
        top, start, end, scarf = parameters[2:6]
    else:
        top, start, end = parameters[2:5]
    if not (height > 0 and min(base, top) >= 0 and max(base, top) > 0 and 0 < aspect <= 1):
        reject('td_geometry_size_range')
    if scarf:
        reject('td_geometry_conic_scarf_unmapped')
    u, wrap_u = _azimuth_cuts(start, end, cuts[0], wrap=True)

    def point(a, fraction):
        if shape == 'paraboloid':
            radius = math.hypot(base * math.sqrt(1 - fraction), top * math.sqrt(fraction))
        else:
            radius = _blend(base, top, fraction)
        return radius * math.cos(a), aspect * radius * math.sin(a), height * fraction

    return u, cuts[1], wrap_u, False, point


_SHELL_WIDTHS = {
    'cone': 5, 'cylinder': 4, 'ellipse': 5, 'ellipsoid': 7, 'elliptic-cone': 6, 'elliptic-cylinder': 5,
    'offset-paraboloid': 5, 'parabolic-trough': 5, 'paraboloid': 5, 'scarfed-cone': 6,
    'scarfed-cylinder': 5, 'sphere': 5, 'torus': 6,
}


def _blend(start, end, fraction):
    return (1 - fraction) * start + fraction * end


def _interval(start, end, cuts):
    return tuple(_blend(start, end, fraction) for fraction in cuts)


def _conic_boundary(payload, length_unit, face_limit):
    if not isinstance(length_unit, str) or length_unit not in LENGTH_UNITS:
        reject('td_geometry_length_unit')
    scale = LENGTH_UNITS[length_unit]
    fields = payload.fields
    width = _SHELL_WIDTHS.get(payload.shape)
    if width is None:
        reject('td_geometry_conic_parameters_unmapped')
    parameters = fields['serialized_parameters'] + fields['additional_parameters']
    expressions = fields['parameter_expressions']
    if len(expressions) not in (width, len(parameters)) or any(not expression_is_constant(e) for e in expressions):
        reject('td_geometry_dynamic_size')
    if any(parameters[width:]):
        reject('td_geometry_conic_parameters_unmapped')
    cuts = tuple(_subdivision(row) for row in fields['attributes']['subdivision'])
    u, v, wrap_u, wrap_v, evaluate = _shell_parameters(payload.shape, parameters, cuts)
    nu, nv = len(u) - int(not wrap_u), len(v) - int(not wrap_v)
    if nu * nv > face_limit:
        reject('td_geometry_mesh_limit')
    origin, axes = _frame(fields['origin'], fields['axes'], fields['mesh_controls'], scale)
    points, indices, faces = [], {}, []
    corners = ((0, 0), (1, 0), (1, 1), (0, 1))
    lattice = []
    for second in v:
        row = []
        for first in u:
            local = evaluate(first, second)
            if local not in indices:
                indices[local] = len(points)
                points.append(world_point(origin, axes, tuple(scale * value for value in local)))
            row.append(indices[local])
        lattice.append(row)
    for j in range(nv):
        for i in range(nu):
            face = tuple(dict.fromkeys(lattice[(j + dj) % len(v)][(i + di) % len(u)] for di, dj in corners))
            if len(face) < 3:
                reject('td_geometry_coordinate_precision')
            faces.append(face)
    if len(set(points)) != len(points):
        reject('td_geometry_coordinate_precision')
    return points, faces


def _curved_boundary(payload, length_unit, face_limit):
    if not isinstance(length_unit, str) or length_unit not in LENGTH_UNITS:
        reject('td_geometry_length_unit')
    scale = LENGTH_UNITS[length_unit]
    fields, solid = payload.fields, isinstance(payload, CurvedSolidPayload)
    attrs = fields['attributes']
    parameters = fields['serialized_parameters']
    expressions = attrs['parameter_expressions'] if solid else fields['parameter_expressions']
    width = {'sphere': 6, 'cone': 7, 'ellipsoid': 12, 'cylinder': 5}.get(
        payload.shape if solid else 'disk', 4)
    if len(expressions) not in (width, len(parameters)) or any(not expression_is_constant(e) for e in expressions):
        reject('td_geometry_dynamic_size')
    if any(parameters[width:]):
        reject('td_geometry_curved_parameters_unmapped')
    partitions = tuple(_subdivision(row) for row in attrs['subdivision'])
    # Curved primitives store angular and radial subdivisions first. The third
    # solid direction is height (cylinder) or polar angle (sphere).
    cone = isinstance(payload, ConeSolidPayload)
    ellipsoid = isinstance(payload, EllipsoidSolidPayload)
    sphere = isinstance(payload, SpherePayload)
    if cone:
        height, inner, outer, top_inner, top_outer, start, end = parameters[:7]
        if (height <= 0 or not (0 <= inner <= outer and 0 <= top_inner <= top_outer)
                or outer == inner != 0 or top_outer == top_inner != 0
                or max(outer, top_outer) == 0):
            reject('td_geometry_size_range')
        vertical = partitions[2]
    elif ellipsoid:
        x_radius, y_radius, z_radius, low, high, start, end, ix, iy, iz, ilow, ihigh = parameters
        if not (min(x_radius, y_radius, z_radius) > 0 and -z_radius <= low < high <= z_radius):
            reject('td_geometry_size_range')
        if any((ix, iy, iz, ilow, ihigh)):
            if not (0 < ix < x_radius and 0 < iy < y_radius and 0 < iz < z_radius and -iz <= ilow < ihigh <= iz):
                reject('td_geometry_size_range')
            ratio = iz / z_radius
            proportional = all(math.isclose(i / o, ratio, rel_tol=1e-12)
                               for i, o in ((ix, x_radius), (iy, y_radius)))
            matching_trims = math.isclose(ilow / iz, low / z_radius, abs_tol=1e-12) and math.isclose(
                ihigh / iz, high / z_radius, abs_tol=1e-12)
            if not (proportional and matching_trims):
                if (low, high, ilow, ihigh) == (-z_radius, z_radius, -iz, iz) and math.isclose(
                        end - start, math.tau, abs_tol=1e-12, rel_tol=0):
                    outer_payload = replace(payload, fields={**fields, 'serialized_parameters': (*parameters[:7], 0, 0, 0, 0, 0)})
                    cavity = (ix, iy, iz, ilow, ihigh, start, end, 0, 0, 0, 0, 0)
                    inner_payload = replace(payload, fields={**fields, 'serialized_parameters': cavity})
                    outer_points, outer_faces = _curved_boundary(outer_payload, length_unit, face_limit)
                    inner_points, inner_faces = _curved_boundary(inner_payload, length_unit, face_limit - len(outer_faces))
                    if set(outer_points).intersection(inner_points):
                        reject('td_geometry_coordinate_precision')
                    return outer_points + inner_points, outer_faces + [
                        tuple(len(outer_points) + index for index in reversed(face)) for face in inner_faces]
                reject('td_geometry_ellipsoid_inner_layout_unmapped')
            inner = ratio
        else:
            inner = 0
        outer = 1
        vertical, _ = _azimuth_cuts(math.acos(high / z_radius), math.acos(low / z_radius), partitions[2])
    elif isinstance(payload, CylinderPayload):
        height, inner, outer, start, end = parameters[:5]
        if height <= 0:
            reject('td_geometry_size_range')
        vertical = tuple(c * height for c in partitions[2])
    else:
        inner, outer, start, end = parameters[:4]
        if sphere:
            low, high = parameters[4:6]
            if not 0 <= low < high <= math.pi:
                reject('td_geometry_angle_range')
            vertical, _ = _azimuth_cuts(low, high, partitions[2])
        else:
            vertical = (0.0,)
    if not cone and not 0 <= inner < outer:
        reject('td_geometry_size_range')
    radii = partitions[1] if cone else _interval(inner, outer, partitions[1])
    if any(a >= b for a, b in zip(radii, radii[1:])):
        reject('td_geometry_coordinate_precision')
    azimuths, closed = _azimuth_cuts(start, end, partitions[0])
    frame = attrs['mesh_controls'] if solid else fields['mesh_controls']
    origin, axes = _frame(fields['origin'], fields['axes'], frame, scale)
    limits = (len(radii) - 1, len(azimuths) if closed else len(azimuths) - 1, len(vertical) - 1)
    radial, angular, axial = limits
    polar = sphere or ellipsoid
    end_caps = (int(outer > 0) + int(top_outer > 0)) if cone else sum(
        not polar or level not in (0, math.pi) for level in (vertical[0], vertical[-1]))
    inner_wall = inner > 0 or (cone and top_inner > 0)
    face_count = (axial * angular * (1 + inner_wall) + radial * angular * end_caps
                  + (0 if closed else 2 * radial * axial)) if solid else radial * angular
    if face_count > face_limit:
        reject('td_geometry_mesh_limit')
    vertices, faces, lookup = [], [], {}
    factors = tuple(radius * scale for radius in (x_radius, y_radius, z_radius)) if ellipsoid else (scale,) * 3

    def vertex(index):
        r, a, z = index
        radial, level = radii[r], vertical[z]
        if cone:
            radial = _blend(_blend(inner, top_inner, level), _blend(outer, top_outer, level), radial)
        at_pole = polar and level in (0, math.pi)
        if radial == 0 or at_pole:
            a = 0
        if radial == 0 and polar:
            z = 0
        if cone and radial == 0:
            r = 0
        key = r, a % len(azimuths), z
        if key not in lookup:
            angle = azimuths[key[1]]
            if polar:
                ring = 0.0 if at_pole else radial * math.sin(level)
                axial = radial * math.cos(level)
            elif cone:
                ring, axial = radial, height * level
            else:
                ring, axial = radial, level
            lookup[key] = len(vertices)
            vertices.append(world_point(origin, axes, (factors[0] * ring * math.cos(angle),
                                                       factors[1] * ring * math.sin(angle), factors[2] * axial)))
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
                        reverse = polar != (solid and layer == 0)
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
    'tetra': ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)),
    'pyramid': ((0, 3, 2, 1), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)),
}


def _element_points(payload, nodes, length_unit):
    if not isinstance(length_unit, str) or length_unit not in LENGTH_UNITS:
        reject('td_geometry_length_unit')
    if payload.fields.get('additional_node_selector', 0):
        reject('td_element_node_selector_unmapped')
    handles = payload.fields['node_handles']
    if nodes is None or any(handle not in nodes for handle in handles):
        reject('td_element_missing_node')
    fields = [nodes[handle].fields for handle in handles]
    if any(any(node['offsets']) for node in fields):
        reject('td_element_node_offset_unmapped')
    scale = LENGTH_UNITS[length_unit]
    points = [tuple(value * scale for value in node['basis'][0]) for node in fields]
    if len(set(points)) != len(handles) or any(not math.isfinite(v) for point in points for v in point):
        reject('td_geometry_coordinate_precision')
    return points


def _delta(point, origin):
    return tuple(a - b for a, b in zip(point, origin))


def _element_shell_boundary(payload, nodes, length_unit, face_limit):
    if face_limit < 1:
        reject('td_geometry_mesh_limit')
    if payload.fields['extra_points'] or payload.order != 1:
        reject('td_element_curved_shell_unmapped')
    points = _element_points(payload, nodes, length_unit)
    normals = []
    for a, b in zip(points[1:], points[2:]):
        u, v = _delta(a, points[0]), _delta(b, points[0])
        normal = tuple(u[(i + 1) % 3] * v[(i + 2) % 3] - u[(i + 2) % 3] * v[(i + 1) % 3]
                       for i in range(3))
        if not all(math.isfinite(value) for value in normal) or not any(normal):
            reject('td_element_invalid_cell')
        normals.append(normal)
    if len(normals) == 2 and sum(a * b for a, b in zip(*normals)) <= 0:
        reject('td_element_invalid_cell')
    return points, [tuple(range(len(points)))]


def _linear_solid_boundary(payload, nodes, length_unit, face_limit):
    template = _LINEAR_SOLID_FACES[payload.shape]
    if face_limit < len(template):
        reject('td_geometry_mesh_limit')
    points = _element_points(payload, nodes, length_unit)

    directions = (1, 3, 4) if payload.shape in ('brick', 'pyramid') else (1, 2, 3)
    orientation = determinant(tuple(_delta(points[i], points[0]) for i in directions))
    if not math.isfinite(orientation) or orientation == 0:
        reject('td_linear_solid_invalid_cell')
    faces = [face if orientation > 0 else face[::-1] for face in template]
    offsets = [_delta(point, points[0]) for point in points]
    center = tuple(value + sum(offset[i] / len(points) for offset in offsets) for i, value in enumerate(points[0]))
    for first, *rest in faces:
        for j, k in zip(rest, rest[1:]):
            volume = determinant((_delta(points[first], center), _delta(points[j], center), _delta(points[k], center)))
            if not math.isfinite(volume) or volume <= 0:
                reject('td_linear_solid_invalid_cell')
    return points, faces


def boundary_mesh(payload, length_unit, *, face_limit=Limits().records, nodes=None):
    """Return SI vertices and outward faces using stored literal partitions."""
    if isinstance(payload, (CurvedSolidPayload, DiskPayload)):
        return _curved_boundary(payload, length_unit, face_limit)
    if isinstance(payload, ConicPayload):
        return _conic_boundary(payload, length_unit, face_limit)
    if isinstance(payload, LinearSolidPayload):
        return _linear_solid_boundary(payload, nodes, length_unit, face_limit)
    if isinstance(payload, LinearShellPayload):
        return _element_shell_boundary(payload, nodes, length_unit, face_limit)
    if isinstance(payload, PolygonMeshPayload):
        if not isinstance(length_unit, str) or length_unit not in LENGTH_UNITS:
            reject('td_geometry_length_unit')
        if len(payload.fields['faces']) > face_limit:
            reject('td_geometry_mesh_limit')
        if not payload.fields['faces']:
            reject('td_geometry_selection')
        scale = LENGTH_UNITS[length_unit]
        points = [tuple(value * scale for value in point) for point in payload.fields['points']]
        if len(set(points)) != len(points) or any(not math.isfinite(v) for p in points for v in p):
            reject('td_geometry_coordinate_precision')
        return points, payload.fields['faces']
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
        inventory = decode_drawing(staged.snapshot, handles=selected or None)
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
    inventory = decode_drawing(staged.snapshot, handles=set(handles) if handles else None)
    geometry = selected_geometry(staged, handles, inventory=inventory)
    if handles:
        node_handles = {node for _, payload in geometry for node in payload.fields.get('node_handles', ())}
        node_payloads = decode_drawing(staged.snapshot, handles=node_handles).payloads if node_handles else ()
    else:
        node_payloads = inventory.payloads
    nodes = {p.record['handle']: p for p in node_payloads if isinstance(p, NodePayload)}
    lines = ['# FCST TD geometry-only export. Coordinates in metres.']
    vertices = faces = triangles = quads = 0
    for handle, payload in geometry:
        points, boundary = boundary_mesh(payload, length_unit, face_limit=Limits().records - faces, nodes=nodes)
        kind = payload.shape if isinstance(payload, (ConicPayload, CurvedSolidPayload)) else (
            'disk' if isinstance(payload, DiskPayload) else 'brick' if isinstance(payload, BrickPayload)
            else 'polygon_mesh' if isinstance(payload, PolygonMeshPayload)
            else f'linear_{payload.shape}' if isinstance(payload, (LinearShellPayload, LinearSolidPayload)) else 'rectangle')
        lines.append(f'o td_{kind}_{handle}')
        lines.extend('v ' + ' '.join(format(x, '.17g') for x in point) for point in points)
        lines.extend('f ' + ' '.join(str(vertices + index + 1) for index in face) for face in boundary)
        vertices += len(points)
        faces += len(boundary)
        triangles += sum(len(face) == 3 for face in boundary)
        quads += sum(len(face) == 4 for face in boundary)
    staged.original.check_current()
    raw = ('\n'.join(lines) + '\n').encode('ascii')
    return raw, {'objects': len(geometry), 'vertices': vertices, 'quads': quads, 'triangles': triangles,
                 'polygons': faces - triangles - quads, 'length_unit': 'm',
                 'scope': 'geometry-only', 'vendor_runtime_required': False, 'qualified': False}
