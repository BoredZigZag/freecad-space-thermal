# SPDX-License-Identifier: MIT OR Apache-2.0
from collections import Counter
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fcst_app.discretization import read_input
from fcst_exchange import ExchangeError
from fcst_exchange.td_spatial import prepare_spatial
from td_geometry_fixture import spatial_fields, spatial_law_properties, spatial_preview, spatial_properties, spatial_source_records


class TdSpatialTests(unittest.TestCase):
    def prepare(self, staged, **options):
        return prepare_spatial(staged, options.pop('properties', 'fixture.tdp'), 'mm',
                               temperature=300, temperature_range=(250, 450), **options)

    def test_spatial_mesh_resolves_materials_capacity_and_source_identity(self):
        with TemporaryDirectory() as tmp:
            staged = spatial_preview(Path(tmp))
            value, report = self.prepare(staged)
            self.assertEqual(value, read_input(value))
            self.assertEqual(value, self.prepare(staged)[0])
        self.assertEqual((report['objects'], report['materials'], report['points'], report['cells']), (2, 2, 36, 12))
        self.assertFalse(report['vendor_runtime_required'])
        self.assertFalse(report['qualified'])
        entities = value['model']['entities']
        materials = {row['id']: row['label'] for row in entities if row['kind'] == 'material'}
        cells = [row for row in entities if row['kind'] == 'element']
        self.assertEqual(Counter((row['topology'], materials[row['material_id']]) for row in cells),
                         {('quadrilateral', 'OWNED SHEET'): 4, ('hexahedron', 'OWNED solid'): 8})
        self.assertEqual([round(row['volume'] * 1e9, 8) for row in cells[:4]], [6, 18, 6, 18])
        self.assertAlmostEqual(sum(n['capacity']['value'] for n in entities if n['kind'] == 'node'),
                               (48 * 600 + 192 * 500) * 1e-9)
        self.assertEqual([len(source['entries']) for source in value['model']['source_maps']], [2, 2])
        self.assertEqual(value['model']['source_maps'][0]['source_revision'], staged.original.source_hash)
        self.assertEqual({c['thickness_m'] for c in value['spatial']['cells']}, {0, .002})

    def test_spatial_selection_requires_a_unique_valid_handle_and_current_sources(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            staged = spatial_preview(root)
            handle = staged.snapshot.native['objects'][0]['handle']
            only, report = self.prepare(staged, handles=[handle])
            self.assertEqual((report['objects'], report['materials']), (1, 1))
            self.assertEqual(only['model']['source_maps'][0]['entries'][0]['handle'], str(handle))
            for handles, code in [([handle, handle], 'duplicate_handle'), ([2**63], 'geometry_selection')]:
                with self.assertRaisesRegex(ExchangeError, code):
                    self.prepare(staged, handles=handles)
            with self.assertRaisesRegex(ExchangeError, 'property_companion'):
                self.prepare(staged, properties='fixture.dwg')
            (root / 'fixture.tdp').write_bytes(spatial_properties() + b'\n')
            with self.assertRaises(ExchangeError):
                self.prepare(staged)

    def test_spatial_binds_temperature_laws_and_reuses_material_only_in_the_same_frame(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = spatial_fields()
            fields[0]['attributes']['values_g'] = (2, 3, 4, 5)
            value, report = self.prepare(spatial_preview(root, fields, spatial_law_properties()))
            self.assertEqual(value, read_input(value))
            self.assertEqual(report['materials'], 2)
            sheet = next(e for e in value['model']['entities'] if e.get('label') == 'OWNED SHEET')
            self.assertEqual(sheet['density']['value'], 40)
            self.assertEqual(sheet['conductivity_tensor'], [[12, 0, 0], [0, 32, 0], [0, 0, 45]])
            self.assertEqual(value['spatial']['tensor_laws'][0]['temperatures_K'], [250, 350, 450])
            self.assertEqual(len(value['material_laws']), 2)
            fields[1]['attributes']['names_a'] = ('OWNED submodel', 'OWNED SHEET', 'OWNED optical')
            fields[0]['attributes']['values_g'] = (1,) * 4
            rebound, report = self.prepare(spatial_preview(root, fields, spatial_law_properties()))
            self.assertEqual(report['materials'], 2)
            self.assertEqual(len({law['frame_id'] for law in rebound['spatial']['tensor_laws']}), 2)
            self.assertEqual(len({e['handle'] for e in rebound['model']['source_maps'][1]['entries']}), 2)

    def test_spatial_binds_constant_laminate_and_series_parallel_aggregate(self):
        from fcst_exchange.td_property_laws import read_laws, write_laws

        library = read_laws(spatial_properties(), 'tdp')
        components = [{'material': name, 'scalars': {'THICKNESS': thickness, 'WEIGHT': thickness / 4}}
                      for name, thickness in [('OWNED SHEET', 1), ('OWNED solid', 3)]]
        library['entries'] += [
            {'name': name, 'scalars': {'TYPE': mode}, 'tables': {}, 'vectors': {},
             'aggregate': {'scalars': {'KXP': 0, 'KYP': 1, 'KZP': 1} if mode == 2 else {}, 'components': components}}
            for name, mode in [('OWNED laminate', 1), ('OWNED aggregate', 2)]]
        fields = spatial_fields()
        fields[0]['attributes']['property_names'] = ('OWNED laminate', 'Default')
        fields[1]['attributes']['names_a'] = ('OWNED submodel', 'OWNED aggregate', 'OWNED optical')
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            value, _ = self.prepare(spatial_preview(root, fields, write_laws(library)))
            materials = {e['label']: e for e in value['model']['entities'] if e['kind'] == 'material'}
            parallel, series = 6.25, 112 / 19
            for name, axes in [('OWNED laminate', (parallel, parallel, series)),
                               ('OWNED aggregate', (series, parallel, parallel))]:
                material = materials[name]
                self.assertEqual(material['density']['value'], 12.5)
                self.assertEqual(material['specific_heat']['value'], 42)
                for i, target in enumerate(axes):
                    self.assertAlmostEqual(material['conductivity_tensor'][i][i], target)
            library['entries'][-1]['aggregate']['scalars']['KXP'] = .5
            with self.assertRaisesRegex(ExchangeError, 'mixed_conductivity_unmapped'):
                self.prepare(spatial_preview(root, fields, write_laws(library)))

    def test_spatial_rejects_layered_dynamic_missing_and_active_material_modes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for change, code in (
                (lambda a: a.update(property_names=('OWNED sheet', 'OWNED solid')), 'rectangle_material_mode'),
                (lambda a: a['expressions_a'][0].update(text='OWNED_SYMBOL'), 'rectangle_material_mode'),
                (lambda a: a.update(property_scalars=(0, 1)), 'spatial_thickness'),
                (lambda a: a.update(property_names=('absent', 'Default')), 'material_missing'),
            ):
                fields = spatial_fields()
                change(fields[0]['attributes'])
                with self.subTest(code=code), self.assertRaisesRegex(ExchangeError, code):
                    self.prepare(spatial_preview(root, fields))
            fields = spatial_fields()
            fields[1]['attributes']['advection']['selectors'] = (1, 0, 0)
            with self.assertRaisesRegex(ExchangeError, 'brick_material_mode'):
                self.prepare(spatial_preview(root, fields))
            for raw, code in (
                (spatial_properties().replace(b'[CONDUCT]\r\n4\r\n', b''), 'required_fields_unmapped'),
                (spatial_law_properties().replace(b'250 2', b'260 2'), 'material_table_domain'),
            ):
                with self.subTest(code=code), self.assertRaisesRegex(ExchangeError, code):
                    self.prepare(spatial_preview(root, properties=raw))

    def test_saved_fd_cell_and_vertex_identities_use_coordinates(self):
        with TemporaryDirectory() as tmp:
            for centered, kind, namespace in ((True, 'element', 'TD.DWG.FD-CELL'),
                                               (False, 'node', 'TD.DWG.FD-NODE')):
                with self.subTest(centered=centered):
                    staged = spatial_preview(Path(tmp), records=spatial_source_records(centered=centered))
                    value, report = self.prepare(staged, source_node_ids=True)
                    self.assertEqual(value, read_input(value))
                    self.assertEqual(report['source_nodes'], 8 if centered else 27)
                    entries = [e for s in value['model']['source_maps'] for e in s['entries'] if 'node_number' in e]
                    targets = (value['spatial']['cells'] if centered else value['spatial']['points'])
                    self.assertEqual({e['node_number']: e['entity_id'] for e in entries},
                                     {100 + 2*i: t[kind+'_id'] for i, t in enumerate(targets)})
                    self.assertEqual({(e['namespace'], e['submodel_handle']) for e in entries}, {(namespace, 'OWNED FD')})

    def test_single_brick_face_power_preserves_marker_area_and_total(self):
        with TemporaryDirectory() as tmp:
            extents = ((.020, .024), (.030, .036), (.040, .048))
            for i in range(6):
                marker = 1 << i
                with self.subTest(marker=marker):
                    staged = spatial_preview(Path(tmp), records=spatial_source_records(marker=marker))
                    value, report = self.prepare(staged, source_node_ids=True, face_load_handle=110, power_unit='mW')
                    self.assertEqual(value, read_input(value))
                    self.assertEqual(report['face_loads'], 1)
                    surfaces = value['spatial']['surfaces']
                    points = {row['id']: row['position'] for row in value['spatial']['points']}
                    self.assertEqual(len(surfaces), 8)
                    self.assertAlmostEqual(math.fsum(s['value_SI'] for s in surfaces), 4.8e-5, places=15)
                    self.assertTrue(all(math.isclose(points[p][i//2], extents[i//2][i%2])
                                        for s in surfaces for p in s['point_ids']))
                    power = Counter(round(s['value_SI'], 12) for s in surfaces)
                    self.assertEqual(power, {6e-6: 8} if i//2 == 1 else {3e-6: 4, 9e-6: 4})
                    self.assertTrue(any(e['namespace'] == 'TD.DWG.FACE-LOAD' and e['handle'] == f'110.101.{marker}'
                                        for s in value['model']['source_maps'] for e in s['entries']))
                    self.assertEqual(self.prepare(staged)[0]['spatial']['surfaces'], [])

    def test_spatial_rejects_incomplete_source_ids_and_unsupported_face_loads(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for fixture, error in (({'wrong_position': True}, 'node_position'),
                                   ({'duplicate_position': True}, 'node_position'),
                                   ({'duplicate_number': True}, 'node_identity_collision'),
                                   ({'wrong_owner': True}, 'node_association')):
                with self.subTest(fixture=fixture), self.assertRaisesRegex(ExchangeError, error):
                    self.prepare(spatial_preview(root, records=spatial_source_records(**fixture)), source_node_ids=True)
            for fixture, request, error in (({'marker': 3}, {}, 'face_selection'),
                                           ({'time_table': ((0, 1), (1, 2))}, {}, 'face_load_mode'),
                                           ({}, {'face_load_handle': 101}, 'face_load_missing'),
                                           ({}, {'power_unit': None}, 'face_power_unit')):
                with self.subTest(fixture=fixture, request=request), self.assertRaisesRegex(ExchangeError, error):
                    self.prepare(spatial_preview(root, records=spatial_source_records(**fixture)),
                                 **({'face_load_handle': 110, 'power_unit': 'mW'} | request))
