# SPDX-License-Identifier: MIT OR Apache-2.0
from copy import deepcopy
from dataclasses import replace
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fcst_exchange import ExchangeError
from fcst_exchange.dwg_native import NativeSnapshot,Fields,_one
from fcst_exchange.td_geometry import (decode_rectangle, decode_rectangle_complete, decode_brick, decode_disk,
                                       decode_cylinder, decode_sphere, decode_linear_brick, decode_linear_wedge,
                                       rectangle_payload, brick_payload, SENTINEL)
from fcst_exchange.td_geometry_mesh import boundary_mesh
from fcst_exchange.td_node import decode_node
from fcst_exchange.td_writer import FilerWriter, node_payload
from fcst_exchange.td_decode import decode_drawing
from fcst_exchange.td_model import convert_network
from fcst_exchange.sinda import SindaUnits
from td_fixture import drawing,envelope,PATCH
from td_geometry_fixture import rectangle_fields,brick_fields,rectangle_boundary_fields,brick_boundary_fields,expression


def rectangle():
    f=FilerWriter();b=f.data;b.bd(SENTINEL);b.bl(7)
    for value in (0,1,0,2,0,0):b.bd(value)
    for point in ((1,2,3),(1,0,0),(0,1,0),(0,0,1)):b.point(point)
    # Independently authored opaque attributes. They are never treated as TD
    # surface/mesh/material semantics or made eligible for thermal edits.
    b.bl(99);f.text('owned opaque attributes');return f.result(1)


def write_owned_surface55(f, attrs):
    from fcst_exchange.td_surface import ATTRIBUTE_LAYOUT, EXTENDED_ATTRIBUTE_REVISION, write_value

    b = f.data
    b.bl(0)
    f.text('')
    f.text('')
    b.bl(0)
    b.bl(0)
    for name in ('front', 'back', 'edge'):
        f.text(name)
    b.bd(EXTENDED_ATTRIBUTE_REVISION)
    for name, field_kind, count in ATTRIBUTE_LAYOUT:
        for value in ((attrs[name],) if count == 1 else attrs[name]):
            write_value(f, field_kind, value)
    b.bl(1)
    f.text('owned identifier')
    b.bl(17)
    b.bl(31)
    f.text('left')
    f.text('right')
    b.bl(0)
    b.bl(0)
    for name in ('first', 'second'):
        f.text(name)
        b.bl(0)


def curved_record(shape, *, trailing=False, shell_parameters=None, solid_parameters=None, kind=None):
    from fcst_exchange.td_surface import write_expression, write_mesh_controls, write_solid_attributes

    f = FilerWriter()
    b = f.data
    shell = shape == 'disk' or shell_parameters is not None
    if shell:
        fields = rectangle_boundary_fields()
        values = (0, 3, 0, math.tau) if shell_parameters is None else shell_parameters
        parameters = (*values[:6], *(0,) * max(0, 6 - len(values)))
        b.bd(SENTINEL)
        b.bl(7)
    else:
        fields = brick_boundary_fields()
        values = solid_parameters if solid_parameters is not None else (
            (5, 1, 3, 0, math.tau) if shape == 'cylinder' else (0, 3, 0, math.tau, 0, math.pi))
        parameters = (*values, *(0,) * (12 - len(values)))
        b.bl(23)
    for value in parameters:
        b.bd(value)
    for p in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)):
        b.point(p)
    attrs = fields['attributes']
    if shell:
        write_owned_surface55(f, attrs)
        additional = values[6:]
        for value in (*additional, *(0,) * (6 - len(additional))):
            b.bd(value)
        fields['mesh_controls']['values'] = (0,) * 6
        write_mesh_controls(f, fields['mesh_controls'])
        b.bl(len(values))
        for _ in values:
            write_expression(f, expression())
        b.bl(0)
    else:
        attrs['parameter_expressions'] = tuple(expression() for _ in values)
        write_solid_attributes(f, attrs)
        b.bl(1)
        f.text('owned face name')
        f.integers((4, 6))
        b.bl(1)
        f.text('owned identifier')
        b.bl(17)
        b.bl(31)
    if trailing:
        b.bl(1)
    return f.result(kind or {'disk': 6, 'cylinder': 7, 'sphere': 8}[shape])


class TdGeometryTests(unittest.TestCase):
    def test_extended_conics_and_solids_match_analytic_geometry(self):
        from collections import Counter
        from fcst_contracts.spatial import determinant
        from fcst_exchange.td_decode import CONIC_CLASSES, DECODERS

        geometry = {
            'cone': ((5, 3, 0, 0, math.tau), ((-3, 3), (-3, 3), (0, 5))),
            'cylinder': ((5, 3, 0, math.tau), ((-3, 3), (-3, 3), (0, 5))),
            'ellipse': ((3, 2, 0, 0, math.tau), ((-3, 3), (-2, 2), (0, 0))),
            'ellipsoid': ((3, 2, 1, -1, 1, 0, math.tau), ((-3, 3), (-2, 2), (-1, 1))),
            'elliptic-cone': ((5, 3, 0, 0.5, 0, math.tau), ((-3, 3), (-1.5, 1.5), (0, 5))),
            'elliptic-cylinder': ((5, 3, 2, 0, math.tau), ((-3, 3), (-2, 2), (0, 5))),
            'offset-paraboloid': ((4, 4, 1, 1, 0.5), ((0, 2), (-0.5, 0.5), (0, 1))),
            'parabolic-trough': ((2, -4, 4, -2, 2), ((-4, 4), (-2, 2), (0, 2))),
            'paraboloid': ((5, 0, 3, 0, math.tau), ((-3, 3), (-3, 3), (0, 5))),
            'scarfed-cone': ((5, 3, 0, 0, math.tau, 0), ((-3, 3), (-3, 3), (0, 5))),
            'scarfed-cylinder': ((5, 3, 0, math.tau, 0), ((-3, 3), (-3, 3), (0, 5))),
            'sphere': ((3, -3, 3, 0, math.tau), ((-3, 3), (-3, 3), (-3, 3))),
            'torus': ((3, 1, 0, math.tau, 0, math.tau), ((-4, 4), (-4, 4), (-1, 1))),
        }
        for name, shape in CONIC_CLASSES.items():
            with self.subTest(shape=shape):
                parameters = geometry.get(shape, ((1, 2, 3, 4, 5, 6), None))[0]
                row, common = envelope(curved_record(shape, shell_parameters=parameters, kind=11))
                payload = DECODERS[name](row, Fields(common.items()))
                self.assertEqual(payload.shape, shape)
                self.assertEqual((payload.fields['serialized_parameters'] + payload.fields['additional_parameters'])[:len(parameters)], parameters)
                trailing, trailing_common = envelope(curved_record(shape, trailing=True, shell_parameters=parameters, kind=11))
                with self.assertRaisesRegex(ExchangeError, 'unconsumed_stream'):
                    DECODERS[name](trailing, Fields(trailing_common.items()))
                if shape not in geometry:
                    with self.assertRaisesRegex(ExchangeError, 'conic_parameters_unmapped'):
                        boundary_mesh(payload, 'm')
                    continue
                points, faces = boundary_mesh(payload, 'm')
                self.assertEqual(len(set(points)), len(points))
                for coordinates, bounds in zip(zip(*points), geometry[shape][1]):
                    self.assertAlmostEqual(min(coordinates), bounds[0])
                    self.assertAlmostEqual(max(coordinates), bounds[1])
                self.assertTrue(all(len(face) in (3, 4) for face in faces))
                with self.assertRaisesRegex(ExchangeError, 'mesh_limit'):
                    boundary_mesh(payload, 'm', face_limit=1)
        for name, parameters, expected in (
                ('RcFdSolidCone', (5, 0, 3, 0, 0, 0, math.tau), 15 * math.pi),
                ('RcFdSolidCone', (5, 1, 3, 0.5, 2, 0, math.pi), (5 * math.pi / 6) * (19 - 1.75)),
                ('RcFdSolidEllipsoid', (3, 2, 1, -1, 1, 0, math.tau, 0, 0, 0, 0, 0), 8 * math.pi),
                ('RcFdSolidEllipsoid', (3, 2, 1, -1, 1, 0, math.tau, 1, 1.5, 0.5, -0.5, 0.5), 7 * math.pi),
                ('RcFdSolidEllipsoid', (3, 2, 1, -1, 1, 0, math.tau, 1.5, 1, 0.5, -0.5, 0.5), 7 * math.pi)):
            with self.subTest(name=name, parameters=parameters):
                row, common = envelope(curved_record(name, solid_parameters=parameters, kind=11))
                payload = DECODERS[name](row, Fields(common.items()))
                points, faces = boundary_mesh(payload, 'm')
                edges = Counter((a, b) for face in faces for a, b in zip(face, (*face[1:], face[0])))
                self.assertTrue(all(count == 1 and edges[b, a] == 1 for (a, b), count in edges.items()))
                volume = sum(determinant((points[a], points[b], points[c])) / 6
                             for a, *rest in faces for b, c in zip(rest, rest[1:]))
                self.assertLess(abs(volume / expected - 1), 0.08)

    def test_linear_brick_uses_ordered_source_nodes_and_holds_unmapped_physics(self):
        from fcst_contracts.spatial import determinant

        def element_writer(count):
            writer = FilerWriter()
            writer.data.bl(5)
            writer.data.bl(count)
            writer.references.extend(range(1, count + 1))
            writer.text('owned element')
            writer.data.put(0, 1)
            writer.data.bl(1)
            writer.data.bl(13)
            writer.text('owned material')
            writer.text('owned optics')
            writer.data.bl(0)
            writer.text('owned attribute')
            writer.data.bl(0x3f)
            writer.data.bl(0)
            writer.data.bl(1)
            writer.data.bd(2)
            writer.data.point((1, 2, 3))
            writer.data.put(1, 1)
            for value in (1, 2, 3, 4):
                writer.data.bd(value)
            for _ in range(4):
                writer.expression()
            writer.data.bl(0)
            writer.data.bl(1)
            writer.expression()
            writer.data.bl(1)
            return writer

        writer = element_writer(8)
        handles = tuple(range(201, 209))
        row, common = envelope(writer.result(9), targets=handles)
        brick = decode_linear_brick(row, Fields(common.items()))
        self.assertEqual(brick.fields['node_handles'], handles)
        self.assertTrue(brick.report['payload_decoded'])
        self.assertFalse(brick.report['thermal_semantics_decoded'])
        self.assertFalse(brick.report['native_ready'])
        self.assertEqual(brick.fields['attributes']['point_values'], ((2, (1, 2, 3)),))
        self.assertEqual(brick.fields['attributes']['modifiers'][0], (1, 2, 3, 4))
        with self.assertRaisesRegex(ExchangeError, 'edit_unmapped'):
            brick.edited_record({})

        from fcst_exchange.independent_td import DwgPreview
        from fcst_exchange.td_geometry_mesh import render_geometry
        from fcst_exchange.td_project_inventory import inspect_project
        from fcst_exchange.source_tree import capture_project

        encoded_nodes = [node_payload('OWNED', handle, 300, 1, 'capacitive') for handle in handles]
        inventory = drawing([*encoded_nodes, writer.result(9)], handles=[*handles, 209])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'owned.dwg').write_bytes(b'AC1032-owned')
            preview = DwgPreview(capture_project(root, 'owned.dwg'), inventory)
            element = next(r for r in inspect_project(preview)['thermal_objects'] if r['handle'] == '209')
            self.assertEqual(element['node_bindings'], [{'target': str(handle), 'status': 'resolved'} for handle in handles])
            with self.assertRaisesRegex(ExchangeError, 'coordinate_precision'):
                render_geometry(preview, 'm')

        coordinates = ((1, 1, 1), (3, 1, 1), (3, 4, 1), (1, 4, 1),
                       (1, 1, 5), (3, 1, 5), (3, 4, 5), (1, 4, 5))
        nodes = {}
        for handle, point in zip(handles, coordinates):
            node_row, node_common = envelope(node_payload('OWNED', handle, 300, 1, 'capacitive'), handle)
            node = decode_node(node_row, Fields(node_common.items()))
            nodes[handle] = replace(node, fields={**node.fields, 'basis': (point, *node.fields['basis'][1:])})

        for order in (handles, tuple(handles[i] for i in (0, 3, 2, 1, 4, 7, 6, 5))):
            cell = replace(brick, fields={**brick.fields, 'node_handles': order})
            points, faces = boundary_mesh(cell, 'mm', nodes=nodes)
            self.assertEqual(points, [tuple(v / 1000 for v in coordinates[handles.index(h)]) for h in order])
            self.assertEqual(len(faces), 6)
            signed_volume = sum(determinant((points[a], points[j], points[k])) / 6
                                for a, b, c, d in faces for j, k in ((b, c), (c, d)))
            self.assertAlmostEqual(signed_volume, 24e-9, places=16)
        with self.assertRaisesRegex(ExchangeError, 'missing_node'):
            boundary_mesh(brick, 'm', nodes={})
        wedge_handles = tuple(handles[i] for i in (0, 1, 3, 4, 5, 7))
        wedge_row, wedge_common = envelope(element_writer(6).result(10), targets=wedge_handles)
        wedge = decode_linear_wedge(wedge_row, Fields(wedge_common.items()))
        points, faces = boundary_mesh(wedge, 'mm', nodes=nodes)
        self.assertEqual(wedge.fields['node_handles'], wedge_handles)
        self.assertEqual(sorted(map(len, faces)), [3, 3, 4, 4, 4])
        signed_volume = sum(determinant((points[a], points[j], points[k])) / 6
                            for a, *rest in faces for j, k in zip(rest, rest[1:]))
        self.assertAlmostEqual(signed_volume, 12e-9, places=16)
        from fcst_exchange.td_geometry import decode_linear_pyramid, decode_linear_tetra

        for count, decode, order, expected, face_sizes in (
                (4, decode_linear_tetra, (0, 1, 3, 4), 4e-9, [3, 3, 3, 3]),
                (5, decode_linear_pyramid, (0, 1, 2, 3, 4), 8e-9, [3, 3, 3, 3, 4])):
            targets = tuple(handles[i] for i in order)
            record, common = envelope(element_writer(count).result(11), targets=targets)
            solid = decode(record, Fields(common.items()))
            points, faces = boundary_mesh(solid, 'mm', nodes=nodes)
            self.assertEqual(sorted(map(len, faces)), face_sizes)
            volume = sum(determinant((points[a], points[j], points[k])) / 6
                         for a, *rest in faces for j, k in zip(rest, rest[1:]))
            self.assertAlmostEqual(volume, expected, places=16)
        node = nodes[handles[0]]
        nodes[handles[0]] = replace(node, fields={**node.fields, 'offsets': (1, 0, 0)})
        with self.assertRaisesRegex(ExchangeError, 'offset_unmapped'):
            boundary_mesh(brick, 'm', nodes=nodes)
        duplicate, common = envelope(writer.result(9), targets=(*handles[:7], handles[0]))
        with self.assertRaisesRegex(ExchangeError, 'node_identity'):
            decode_linear_brick(duplicate, Fields(common.items()))
        writer.data.bl(0)
        trailing, common = envelope(writer.result(9), targets=handles)
        with self.assertRaisesRegex(ExchangeError, 'unconsumed_stream'):
            decode_linear_brick(trailing, Fields(common.items()))

    def test_linear_shells_decode_references_and_export_ordered_faces(self):
        from fcst_exchange.td_geometry import (decode_linear_quad, decode_linear_tri,
                                               decode_quadratic_quad, decode_quadratic_tri)

        for count, decode in ((3, decode_linear_tri), (4, decode_linear_quad),
                              (6, decode_quadratic_tri), (8, decode_quadratic_quad)):
            writer = FilerWriter()
            write_owned_surface55(writer, rectangle_boundary_fields()['attributes'])
            writer.data.bl(5)
            writer.data.bl(count)
            writer.references.extend(range(1, count + 1))
            writer.text('owned shell')
            writer.data.put(0, 1)
            writer.data.bl(1)
            writer.data.bl(5)
            writer.data.bl(1)
            writer.references.append(count + 1)
            writer.data.bl(0)
            writer.data.bl(1)
            handles = tuple(range(101, 102 + count))
            row, common = envelope(writer.result(12), targets=handles)
            payload = decode(row, Fields(common.items()))
            self.assertEqual(payload.fields['node_handles'], handles[:-1])
            self.assertEqual(payload.fields['references'][0]['target'], handles[-1])
            if count > 4:
                self.assertEqual(payload.order, 2)
                with self.assertRaisesRegex(ExchangeError, 'curved_shell_unmapped'):
                    boundary_mesh(payload, 'm')
                continue
            nodes = {}
            for i, (handle, point) in enumerate(zip(handles, ((0, 0, 0), (3, 0, 0), (3, 2, 0), (0, 2, 0))), 1):
                row, common = envelope(node_payload('OWNED', i, 300, 1, 'capacitive'), handle)
                node = decode_node(row, Fields(common.items()))
                nodes[handle] = replace(node, fields={**node.fields, 'basis': (point, *node.fields['basis'][1:])})
            points, faces = boundary_mesh(payload, 'm', nodes=nodes)
            self.assertEqual(faces, [tuple(range(count))])
            self.assertEqual(points[-1], nodes[handles[count - 1]].fields['basis'][0])

    def test_polygon_mesh_preserves_face_order_and_rejects_invalid_connectivity(self):
        from fcst_exchange.td_geometry import decode_polygon_mesh

        points = ((0, 0, 0), (3, 0, 0), (3, 2, 0), (1, 3, 0), (0, 2, 0))

        def encoded(faces, version):
            writer = FilerWriter()
            write_owned_surface55(writer, rectangle_boundary_fields()['attributes'])
            b = writer.data
            b.bl(version)
            b.bl(1)
            b.bl(len(points))
            for point in points:
                b.point(point)
            b.bl(1)
            b.bl(len(faces))
            for face in faces:
                b.bl(1)
                writer.integers(face)
            if version == 2:
                b.bl(0)
            row, common = envelope(writer.result(13))
            return row, Fields(common.items())

        faces = ((0, 1, 2, 3, 4), (0, 4, 3))
        for version in (1, 2):
            payload = decode_polygon_mesh(*encoded(faces, version))
            self.assertEqual(boundary_mesh(payload, 'm'), (list(points), faces))
        for invalid in ((0, 1, -1), (0, 1, len(points)), (0, 1, 1), (0, 1)):
            with self.assertRaisesRegex(ExchangeError, 'polygon_mesh_connectivity'):
                decode_polygon_mesh(*encoded((invalid,), 2))

    def test_geometry_selection_covers_registered_classes_and_reports_unmapped_profiles(self):
        from fcst_exchange.independent_td import DwgPreview
        from fcst_exchange.source_tree import capture_project
        from fcst_exchange.td_decode import CONIC_CLASSES, GEOMETRY_CLASSES, UNMAPPED_GEOMETRY_CLASSES
        from fcst_exchange.td_geometry_mesh import render_geometry

        records, classes = [], {}
        for kind, name in enumerate(sorted(CONIC_CLASSES), 20):
            records.append(curved_record(CONIC_CLASSES[name], shell_parameters=(5, 3, 0, 0, math.tau), kind=kind))
            classes[kind] = (GEOMETRY_CLASSES[name], name)
        supported = drawing(records, geometry_classes=classes)
        self.assertEqual(len(decode_drawing(supported).payloads), len(CONIC_CLASSES))
        for kind, name in enumerate(sorted(UNMAPPED_GEOMETRY_CLASSES), 50):
            writer = FilerWriter()
            writer.data.bl(1)
            records.append(writer.result(kind))
            classes[kind] = (name.upper(), name)
        blocked = drawing(records, geometry_classes=classes)
        holds = [r for r in decode_drawing(blocked).records if r.get('limitation') == 'td_geometry_profile_unmapped']
        self.assertEqual(len(holds), len(UNMAPPED_GEOMETRY_CLASSES))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'owned.dwg').write_bytes(b'AC1032-owned')
            preview = DwgPreview(capture_project(root, 'owned.dwg'), blocked)
            with self.assertRaisesRegex(ExchangeError, 'geometry_selection'):
                render_geometry(preview, 'm')
            cone = sorted(CONIC_CLASSES).index('RcCone') + 101
            obj, report = render_geometry(preview, 'm', (cone,))
            self.assertIn(f'o td_cone_{cone}\n'.encode(), obj)
            self.assertEqual(report['objects'], 1)

    def test_curved_dwg_profiles_export_valid_disks_cylinders_and_spheres(self):
        from collections import Counter
        from fcst_contracts.spatial import determinant
        from fcst_exchange.independent_td import DwgPreview
        from fcst_exchange.source_tree import capture_project
        from fcst_exchange.td_geometry_mesh import render_geometry

        decoders = {'disk': decode_disk, 'cylinder': decode_cylinder, 'sphere': decode_sphere}
        for name, decode in decoders.items():
            with self.subTest(name=name):
                row, common = envelope(curved_record(name))
                payload = decode(row, Fields(common.items()))
                extended = (payload.fields['attributes'] if name == 'disk' else payload.fields)['extended_attributes']
                self.assertEqual(extended['text_ids'], (('owned identifier', 17, 31),))
                points, faces = boundary_mesh(payload, 'm')
                self.assertEqual(len(points), len(set(points)))
                self.assertEqual(set(range(len(points))), {i for face in faces for i in face})
                self.assertTrue(all(len(face) in (3, 4) for face in faces))
                if name == 'disk':
                    self.assertEqual(points.count((0, 0, 0)), 1)
                    self.assertTrue(all(p[2] == 0 for p in points))
                    self.assertTrue(any(len(face) == 3 for face in faces))
                else:
                    edges = Counter((a, b) for face in faces for a, b in zip(face, (*face[1:], face[0])))
                    self.assertTrue(all(count == 1 and edges[b, a] == 1 for (a, b), count in edges.items()))
                    volume = sum(determinant((points[f[0]], points[f[i]], points[f[i + 1]])) / 6
                                 for f in faces for i in range(1, len(f) - 1))
                    self.assertGreater(volume, 0)
                    expected = 40 * math.pi if name == 'cylinder' else 36 * math.pi
                    self.assertLess(abs(volume / expected - 1), .08)
                bad, common = envelope(curved_record(name, trailing=True))
                with self.assertRaisesRegex(ExchangeError, 'unconsumed_stream'):
                    decode(bad, Fields(common.items()))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'owned.dwg').write_bytes(b'AC1032-owned')
            preview = DwgPreview(capture_project(root, 'owned.dwg'), drawing([curved_record(name) for name in decoders]))
            obj, report = render_geometry(preview, 'mm')
            self.assertEqual(report['objects'], 3)
            self.assertGreater(report['triangles'], 0)
            self.assertIn(b'o td_disk_101\n', obj)
            self.assertIn(b'o td_cylinder_102\n', obj)
            self.assertIn(b'o td_sphere_103\n', obj)
            self.assertFalse(report['qualified'])

    def test_rectangle_boundary_applies_ordered_local_rotation_and_nonuniform_subdivision(self):
        row, common = envelope(rectangle_payload(rectangle_boundary_fields()))
        points, faces = boundary_mesh(decode_rectangle_complete(row, Fields(common.items())), 'mm')
        self.assertEqual(len(points), 9)
        self.assertEqual(faces[0], (0, 1, 2, 3))
        self.assertEqual(len(faces), 4)
        self.assertEqual({tuple(round(c * 1000, 8) for c in point) for point in points},
                         {(x, 25, z) for x in (0, 3, 4) for z in (37, 40, 43)})
        self.assertEqual(tuple(round(c * 1000, 8) for c in points[faces[0][0]]), (4, 25, 37))
        self.assertEqual(tuple(round(c * 1000, 8) for c in points[faces[0][1]]), (3, 25, 37))

    def test_brick_boundary_is_closed_outward_and_accepts_only_known_size_edits(self):
        fields = brick_boundary_fields()
        row, common = envelope(brick_payload(fields))
        standard = Fields(common.items())
        payload = decode_brick(row, standard)
        vertices, faces = boundary_mesh(payload, 'm')
        self.assertEqual((len(vertices), len(faces)), (26, 24))
        from collections import Counter
        edges = Counter(tuple(sorted((a, b))) for face in faces for a, b in zip(face, (*face[1:], face[0])))
        self.assertTrue(all(count == 2 for count in edges.values()))
        signed_volume = 0
        from fcst_contracts.spatial import determinant
        for a, b, c, d in faces:
            signed_volume += (determinant((vertices[a], vertices[b], vertices[c]))
                              + determinant((vertices[a], vertices[c], vertices[d]))) / 6
        self.assertAlmostEqual(signed_volume, 4 * 6 * 8)
        values = list(fields['serialized_parameters'])
        values[2] = 10
        edited, receipt = payload.edited_record({'serialized_parameters': values})
        self.assertEqual(receipt['changed_fields'], ['parameter_2'])
        resized, _ = boundary_mesh(decode_brick(edited, standard), 'm')
        self.assertEqual(max(point[2] for point in resized), 50)
        for index, value in ((0, 0), (3, 1)):
            invalid = list(fields['serialized_parameters'])
            invalid[index] = value
            with self.assertRaisesRegex(ExchangeError, 'size_edit_scope'):
                payload.edited_record({'serialized_parameters': invalid})

    def test_geometry_boundary_rejects_dynamic_layouts_bad_basis_and_budget(self):
        fields = rectangle_boundary_fields()
        variants = (
            (lambda f: f['parameter_expressions'][0].update(text='VARIABLE'), 'dynamic_size'),
            (lambda f: f['mesh_controls']['expressions'][0].update(text='VARIABLE'), 'dynamic_transform'),
            (lambda f: f['mesh_controls'].update(selectors=(3, 0, 0)), 'rotation_axis'),
            (lambda f: f.update(axes=((1, 0, 0), (0, -1, 0), (0, 0, 1))), 'geometry_basis'),
            (lambda f: f['attributes']['subdivision'][0].update(boundaries=(0, 0, 1)), 'subdivision_unmapped'),
            (lambda f: f['attributes']['subdivision'][0].update(mode=1), 'subdivision_unmapped'),
        )
        for change, code in variants:
            invalid = deepcopy(fields)
            change(invalid)
            row, common = envelope(rectangle_payload(invalid))
            with self.assertRaisesRegex(ExchangeError, code):
                boundary_mesh(decode_rectangle_complete(row, Fields(common.items())), 'm')
        row, common = envelope(rectangle_payload(fields))
        with self.assertRaisesRegex(ExchangeError, 'mesh_limit'):
            boundary_mesh(decode_rectangle_complete(row, Fields(common.items())), 'm', face_limit=3)

    def test_complete_rectangle_and_brick_preserve_all_attribute_mesh_and_advection_fields(self):
        for build,decode,fields in ((rectangle_payload,decode_rectangle_complete,rectangle_fields()),(brick_payload,decode_brick,brick_fields())):
            before=deepcopy(fields);row,common=envelope(build(fields));actual=decode(row,Fields(common.items()))
            native=dict(actual.fields);native.pop('common_handles')
            self.assertEqual(native,before);self.assertEqual(fields,before);self.assertTrue(actual.report['payload_decoded'])
            self.assertFalse(actual.report['thermal_semantics_decoded']);self.assertFalse(actual.report['native_ready'])
            self.assertFalse(actual.report['qualified']);self.assertNotIn('OWNED',str(actual.report))

    def test_complete_geometry_does_not_enable_native_network_or_drop_unknown_physics(self):
        snap=drawing([rectangle_payload(rectangle_fields()),brick_payload(brick_fields())]);inventory=decode_drawing(snap)
        self.assertEqual(inventory.report['decoded_objects'],2);self.assertEqual(inventory.report['partial_objects'],0)
        result=convert_network(snap,SindaUnits('K','J/K','W/K','W','s'),'a'*64)
        self.assertIsNone(result.model);self.assertEqual(sum(d['code']=='td_native_geometry_semantics_unmapped' for d in result.diagnostics),2)
        native=deepcopy(snap.native);next(c for c in native['classes'] if c['cppname']=='RcFdBrick')['dxfname']='RCFDBRICK'
        held=decode_drawing(NativeSnapshot(native,snap.standard,''))
        self.assertEqual(held.report['decoded_objects'],1);self.assertEqual(held.report['retained_objects'],1)
        self.assertEqual(next(r['limitation'] for r in held.records if r['status']=='retained-opaque'),'td_geometry_class_identity_unmapped')

    def test_complete_geometry_scalar_splices_expand_and_preserve_all_other_fields_and_streams(self):
        for build,decode,fields in ((rectangle_payload,decode_rectangle_complete,rectangle_fields()),(brick_payload,decode_brick,brick_fields())):
            row,common=envelope(build(fields));p=decode(row,Fields(common.items()));values=list(fields['serialized_parameters']);values[:2]=[1.25,2.5]
            changed,report=p.edited_record({'serialized_parameters':values});after=decode(changed,Fields(common.items()))
            self.assertEqual(changed['bits']-row['bits'],128);self.assertFalse(report['bit_length_preserved']);self.assertFalse(report['native_ready'])
            self.assertEqual(after.fields,{**p.fields,'serialized_parameters':tuple(values)});self.assertEqual(p.record,row)
            for invalid in ({'serialized_parameters':values[:-1]},{'origin':(2,3,4)},
                    {'serialized_parameters':[True,*values[1:]]},{'serialized_parameters':[float('nan'),*values[1:]]},
                    {'serialized_parameters':[10]*len(values)}):
                with self.assertRaises(ExchangeError):p.edited_record(invalid)

    def test_geometry_parameter_expressions_block_edits_but_other_source_expressions_stay_inert(self):
        fields=rectangle_fields();fields['parameter_expressions'][0]['text']='PARAMETER_FROM_SOURCE()'
        row,common=envelope(rectangle_payload(fields));payload=decode_rectangle_complete(row,Fields(common.items()))
        self.assertTrue(payload.report['payload_decoded'])
        with self.assertRaises(ExchangeError):payload.edited_record({'serialized_parameters':(2,1,0,2,0,0)})
        self.assertEqual(payload.fields['attributes']['expressions_a'][0]['text'],'SOURCE_EXPRESSION')

    def test_full_profiles_reject_truncation_extra_data_unknown_shapes_and_future_versions(self):
        from fcst_exchange.td_writer import network_packet
        for build,decode,fields in ((rectangle_payload,decode_rectangle_complete,rectangle_fields()),(brick_payload,decode_brick,brick_fields())):
            row,common=envelope(build(fields))
            for size in range(0,len(bytes.fromhex(row['data'])),31):
                with self.assertRaises(ExchangeError):decode({**row,'data':bytes.fromhex(row['data'])[:size].hex()},Fields(common.items()))
            bad=deepcopy(fields);bad['future_required_field']=1
            with self.assertRaises(ExchangeError):build(bad)
            bad=deepcopy(fields);bad['axes']=((1,0,0),)
            with self.assertRaises(ExchangeError):build(bad)
            self.assertTrue(network_packet([build(fields)]).startswith(b'FCSTNEW2'))
        fields=rectangle_fields();fields['attributes']['subdivision'][0]['intervals']=10001
        with self.assertRaises(ExchangeError):rectangle_payload(fields)
        fields=brick_fields();fields['attributes']['advection']['future_mode']=True
        with self.assertRaises(ExchangeError):brick_payload(fields)

    def test_geometry_duplicate_map_entries_references_and_unicode_are_not_flattened(self):
        fields=rectangle_fields();fields['attributes']['name_maps']=((('same','first'),('same','second')),())
        fields['attributes']['references_a']=((1,),(0,))
        row,common=envelope(rectangle_payload(fields),targets=(123,));actual=decode_rectangle_complete(row,Fields(common.items()))
        self.assertEqual(actual.fields['attributes']['name_maps'],fields['attributes']['name_maps'])
        self.assertEqual(actual.fields['attributes']['references_a'][0][0]['target'],123)
        self.assertEqual(actual.fields['attributes']['references_a'][1][0]['target'],0)
        self.assertIn('\u03b1',actual.fields['attributes']['property_label'])

    def test_source_edit_handles_survive_uint64_json_strings_and_reject_rounded_numeric_aliases(self):
        from fcst_exchange.independent_td import IndependentTdAdapter
        from fcst_exchange.dwg_native import NativeRuntime
        from fcst_contracts import loads
        import json
        handle=2**63+111;fields=rectangle_fields();before=drawing([rectangle_payload(fields)],[handle])
        changed=deepcopy(fields);changed['serialized_parameters']=(1.25,*changed['serialized_parameters'][1:])
        after=drawing([rectangle_payload(changed)],[handle]);request=loads(json.dumps([{'handle':str(handle),'changes':{'serialized_parameters':changed['serialized_parameters']}}]))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir();raw=b'AC1032-owned';(source/'main.dwg').write_bytes(raw)
            runtime=NativeRuntime(root/'backend.exe','b'*64,PATCH);adapter=IndependentTdAdapter(runtime)
            with patch.object(NativeRuntime,'run',return_value=(before,None,{})):staged=adapter.preview(source,'main.dwg',root/'preview')
            with patch.object(NativeRuntime,'run',side_effect=[(after,b'AC1032-derived',{}),(after,None,{})]):
                report=adapter.export_source(staged,root/'export',request,work=root/'edit')
            self.assertTrue(report['edited_roundtrip_verified']);self.assertEqual((source/'main.dwg').read_bytes(),raw)
            for bad in (float(handle),True,str(2**64),'01','1e2',-1,float('nan')):
                with self.assertRaises(ExchangeError):adapter.export_source(staged,root/'bad',[{'handle':bad,'changes':request[0]['changes']}],work=root/'bad-work')
            with self.assertRaises(ExchangeError):adapter.export_source(staged,root/'duplicate',request*2,work=root/'duplicate-work')

    def test_rectangle_prefix_preserves_unknown_attributes_and_never_claims_thermal_mapping(self):
        row,common=envelope(rectangle());payload=decode_rectangle(row,Fields(common.items()))
        self.assertEqual(payload.fields['serialized_parameters'],(0,1,0,2,0,0));self.assertEqual(payload.fields['origin'],(1,2,3))
        self.assertEqual(payload.record,row);self.assertFalse(payload.report['payload_decoded']);self.assertFalse(payload.report['native_ready'])
        self.assertTrue(payload.report['geometric_envelope_decoded']);self.assertNotIn('owned',str(payload.report))
        self.assertLess(*payload.fields['opaque_data_range']);self.assertLess(*payload.fields['opaque_text_range'])
        with self.assertRaises(ExchangeError):payload.edited_record({'serialized_parameters':(0,2,0,2,0,0)})

    def test_future_version_bad_marker_and_truncated_streams_refuse_geometry_decoding(self):
        record=rectangle();row,common=envelope(record)
        from fcst_exchange.dwg_bits import replace_bits
        raw=bytes.fromhex(row['data'])
        for data in [bytes([raw[0]^64])+raw[1:],replace_bits(raw,66,10,264),raw[:-8]]:
            with self.assertRaises(ExchangeError):decode_rectangle(dict(row,data=data.hex()),Fields(common.items()))

    def test_partial_geometry_inventory_cannot_be_promoted_to_a_native_constant_network(self):
        snap=drawing([rectangle()]);native=deepcopy(snap.native);native['classes'][0].update(cppname='RcRectangle',dxfname='RCRECTANGLE')
        snapshot=NativeSnapshot(native,snap.standard,'');inventory=decode_drawing(snapshot)
        self.assertEqual(inventory.report['decoded_objects'],0);self.assertEqual(inventory.report['partial_objects'],1)
        self.assertEqual(inventory.report['retained_objects'],1)
        result=convert_network(snapshot,SindaUnits('K','J/K','W/K','W','s'),'a'*64)
        self.assertIsNone(result.model);self.assertFalse(result.report['native_ready'])
