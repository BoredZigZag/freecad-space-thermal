# SPDX-License-Identifier: MIT OR Apache-2.0
from copy import deepcopy
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fcst_cli.__main__ import main
from fcst_exchange import ExchangeError
from fcst_exchange.dwg_native import NativeRuntime
from fcst_exchange.independent_td import IndependentTdAdapter
from fcst_exchange.sinda import SindaUnits
from fcst_exchange.td_decode import decode_drawing
from fcst_exchange.td_material_input import prepare_drawing_material_input, prepare_material_input
from fcst_exchange.td_writer import load_payload, node_payload
from td_fixture import PATCH, drawing

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    data = json.loads((ROOT / 'tests/fixtures/thermal/td-material-input.json').read_bytes())
    model = json.loads((ROOT / 'tests/fixtures/thermal/transient-enthalpy.json').read_bytes())['model']
    return data['source_ascii'].encode('ascii'), model, data['bindings']


class TdMaterialInputTests(unittest.TestCase):
    def test_bound_laws_preserve_knots_provenance_and_input(self):
        raw, model, bindings = fixture()
        before = deepcopy(model)
        result = prepare_material_input(raw, model, bindings)
        self.assertEqual(model, before)
        source = result['model']['source_maps'][-1]
        self.assertEqual(source['source_revision'], sha256(raw).hexdigest())
        material_id = source['entries'][0]['entity_id']
        law = result['material_laws'][0]
        self.assertEqual(law['material_id'], material_id)
        self.assertEqual(law['specific_heat']['temperature'], [{'value': 200, 'unit': 'K'}, {'value': 400, 'unit': 'K'}])
        self.assertEqual(law['conductivity']['values'], [{'value': 20, 'unit': 'W/(m*K)'}, {'value': 60, 'unit': 'W/(m*K)'}])
        storage = result['node_storage'][0]
        self.assertEqual(storage['material_id'], material_id)
        self.assertEqual(storage['mass'], {'value': 2, 'unit': 'kg'})
        node = next(entity for entity in result['model']['entities'] if entity['id'] == storage['node_id'])
        self.assertEqual(node['capacity'], {'value': 4, 'unit': 'J/K'})
        stepped = prepare_material_input(raw, model, {**bindings, 'interpolation': 'previous'})
        self.assertEqual(stepped['material_laws'][0]['specific_heat']['discontinuities'], [1])
        clamped = deepcopy(bindings)
        clamped['extrapolation'] = 'clamp'
        clamped['materials']['OWNED TABLE']['minimum_K'] = 180
        self.assertEqual(prepare_material_input(raw, model, clamped)['material_laws'][0]['specific_heat']['extrapolation'], 'clamp')

    def test_invalid_binding_or_unrepresented_material_fails_closed(self):
        raw, model, bindings = fixture()
        node_id = next(iter(bindings['node_storage']))
        invalid = [
            {**bindings, 'interpolation': 'vendor-default'},
            {**bindings, 'case_id': None},
            {**bindings, 'materials': {'OWNED TABLE': {'minimum_K': 199, 'maximum_K': 400, 'reference_K': 300}}},
            {**bindings, 'node_storage': {node_id: {'entry': 'missing', 'mass_kg': 2}}},
            {**bindings, 'node_storage': {node_id: {'entry': 'OWNED TABLE', 'mass_kg': False}}},
        ]
        for value in invalid:
            with self.assertRaises(ExchangeError):
                prepare_material_input(raw, model, value)
        for value in (raw.replace(b'[END]', b'[USEANISO]\n1\n[END]'), raw.replace(b'200 1', b'200 0')):
            with self.assertRaises(ExchangeError):
                prepare_material_input(value, model, bindings)
        result = prepare_material_input(raw, model, bindings)
        with self.assertRaisesRegex(ExchangeError, 'td_material_binding_source_exists'):
            prepare_material_input(raw, result['model'], bindings)

    def test_cli_creates_native_input_without_vendor_and_refuses_overwrite(self):
        raw, model, bindings = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'owned.tdp').write_bytes(raw)
            (root / 'model.json').write_text(json.dumps(model), encoding='utf-8')
            (root / 'bindings.json').write_text(json.dumps(bindings), encoding='utf-8')
            output = root / 'thermal-input.json'
            args = ['fcst', 'td-prepare-materials', directory, 'owned.tdp', 'model.json', 'bindings.json', str(output)]
            with patch('sys.argv', args), patch('sys.stdout', new_callable=io.StringIO) as report, \
                    patch('subprocess.Popen', side_effect=AssertionError('vendor execution forbidden')):
                self.assertEqual(main(), 0, report.getvalue())
                self.assertNotIn('OWNED TABLE', report.getvalue())
                self.assertEqual(json.loads(output.read_bytes()), prepare_material_input(raw, model, bindings))
                self.assertEqual(main(), 2)
                self.assertEqual(json.loads(output.read_bytes()), prepare_material_input(raw, model, bindings))
            self.assertEqual((root / 'owned.tdp').read_bytes(), raw)

    def test_drawing_uses_serialized_mass_and_volume_to_bind_nodes(self):
        raw, _, bindings = fixture()
        policy = {key: bindings[key] for key in ('materials', 'interpolation', 'extrapolation')}
        snapshot = drawing([
            node_payload('MAIN', 1, 26.85, 2000, 'capacitive', 'mass', material=('OWNED TABLE', 1)),
            node_payload('MAIN', 2, 26.85, 2000, 'capacitive', 'volume', material=('OWNED TABLE', 0)),
            load_payload(5, 1),
        ])
        payloads = decode_drawing(snapshot).payloads
        self.assertEqual([p.fields['use_material'] for p in payloads[:2]], [1, 1])
        self.assertTrue(all(not p.fields['user_override'] for p in payloads[:2]))
        self.assertEqual([p.fields['mass_volume_type'] for p in payloads[:2]], [1, 0])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            source.mkdir()
            (source / 'main.dwg').write_bytes(b'AC1032-owned')
            library = source / 'materials.tdp'
            library.write_bytes(raw)
            adapter = IndependentTdAdapter(NativeRuntime(root / 'backend.exe', 'b' * 64, PATCH),
                                           SindaUnits('degC', 'J/K', 'W/K', 'W', 's'))
            with patch.object(NativeRuntime, 'run', return_value=(snapshot, None, {})):
                staged = adapter.preview(source, 'main.dwg', root / 'work')
            self.assertFalse(staged.conversion.report['native_ready'])
            self.assertEqual([r['status'] for r in staged.report['property_dependencies']['references']],
                             ['resolved', 'resolved'])
            result = prepare_drawing_material_input(staged, policy, mass_unit='g', volume_unit='cm3')
            self.assertEqual(result['model']['source_maps'][0]['source_revision'], staged.original.source_hash)
            self.assertEqual(len(result['material_laws']), 1)
            self.assertEqual([r['mass'] for r in result['node_storage']], [{'value': 2, 'unit': 'kg'}] * 2)
            self.assertEqual({n['label']: n['capacity']['value'] for n in result['model']['entities']
                              if n['kind'] == 'node'}, {'mass': 4, 'volume': 4})
            self.assertEqual(library.read_bytes(), raw)

    def test_drawing_material_import_rejects_ambiguity_unknown_modes_and_stale_companions(self):
        from dataclasses import replace

        raw, _, bindings = fixture()
        policy = {key: bindings[key] for key in ('materials', 'interpolation', 'extrapolation')}
        snapshot = drawing([node_payload('MAIN', 1, 300, 2, 'capacitive', material=('OWNED TABLE', 1))])
        inventory = decode_drawing(snapshot)
        payload = inventory.payloads[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            source.mkdir()
            (source / 'main.dwg').write_bytes(b'AC1032-owned')
            library = source / 'materials.tdp'
            library.write_bytes(raw)
            adapter = IndependentTdAdapter(NativeRuntime(root / 'backend.exe', 'b' * 64, PATCH),
                                           SindaUnits('K', 'J/K', 'W/K', 'W', 's'))
            with patch.object(NativeRuntime, 'run', return_value=(snapshot, None, {})):
                staged = adapter.preview(source, 'main.dwg', root / 'work')
                (source / 'other.tdp').write_bytes(raw)
                ambiguous = adapter.preview(source, 'main.dwg', root / 'ambiguous')
                (source / 'other.tdp').unlink()
            with self.assertRaisesRegex(ExchangeError, 'dependency_closure'):
                prepare_drawing_material_input(ambiguous, policy, mass_unit='kg', volume_unit='m3')
            with self.assertRaisesRegex(ExchangeError, 'binding_coverage'):
                prepare_drawing_material_input(staged, {**policy, 'materials': {}}, mass_unit='kg', volume_unit='m3')
            for changes in ({'use_material': 2}, {'user_override': True}, {'mass_volume_type': 2},
                            {'time_table_mode': 1}, {'mass_expression': {**payload.fields['mass_expression'], 'text': 'DYNAMIC'}}):
                fields = {**payload.fields, **changes}
                with patch('fcst_exchange.td_model.decode_drawing', return_value=replace(
                        inventory, payloads=(replace(payload, fields=fields),))):
                    with self.assertRaisesRegex(ExchangeError, 'semantic_or_dependency_hold'):
                        prepare_drawing_material_input(staged, policy, mass_unit='kg', volume_unit='m3')
            library.write_bytes(raw.replace(b'1000', b'2000'))
            with self.assertRaisesRegex(ExchangeError, 'stale_td_project'):
                prepare_drawing_material_input(staged, policy, mass_unit='kg', volume_unit='m3')
