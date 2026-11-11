# SPDX-License-Identifier: MIT OR Apache-2.0
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fcst_app.discretization import read_input
from fcst_exchange import ExchangeError
from fcst_exchange.td_spatial import prepare_spatial
from td_geometry_fixture import spatial_fields, spatial_preview, spatial_properties


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
                (spatial_properties().replace(b'[CONDUCT]\r\n4\r\n', b'[CONDUCT]\r\n4\r\n[USEANISO]\r\n1\r\n'),
                 'material_frame_required'),
            ):
                with self.subTest(code=code), self.assertRaisesRegex(ExchangeError, code):
                    self.prepare(spatial_preview(root, properties=raw))
