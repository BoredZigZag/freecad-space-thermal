# SPDX-License-Identifier: MIT OR Apache-2.0
from pathlib import Path
import tempfile
import unittest

from fcst_exchange import ExchangeError
from fcst_exchange.sinda import SindaAdapter, SindaUnits
from fcst_exchange.time_loads import prepare_drawing_transient
from td_sinda_time_fixture import SINDA, UNITS, td_preview, td_records


class TdSindaTimeTests(unittest.TestCase):
    def test_sinda_tvs_and_per_resolve_owned_arrays_and_preserve_original(self):
        adapter = SindaAdapter(UNITS)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'network.sin'
            source.write_bytes(SINDA)
            request = adapter.prepare_transient(root, source.name, end=2.5, samples=6)
            self.assertEqual(source.read_bytes(), SINDA)
            with self.assertRaises(ExchangeError):
                adapter.preview(root, source.name).require_native()
        model = request['thermal_input']['model']
        expressions = {e['id'] for e in model['entities'] if e['kind'] == 'expression'}
        loads = {e['id']: e for e in model['entities'] if e['kind'] == 'load'}
        self.assertEqual({e['expression_id'] for e in loads.values()}, expressions)
        self.assertEqual([e['power']['value'] for e in loads.values()], [0, 0])
        tables = {row.get('period_s'): row['points'] for row in request['time_loads']}
        self.assertEqual(tables, {None: [[0, 0], [1, 4], [2, 0]], 1: [[0, 2], [.5, 6], [1, 4]]})

    def test_sinda_transient_rejects_missing_tables_mismatched_storage_and_source_logic(self):
        adapter = SindaAdapter(UNITS)
        variants = [
            (SINDA.replace(b'TABLES.A2, GAIN', b'TABLES.A9, GAIN'), 'array_reference'),
            (SINDA.replace(b'3 = 0.0, 0.5, 1.0', b'3 = 0, 1, 2'), 'array_reference'),
            (SINDA.replace(b'2 = 0.0, 2.0, 0.0', b'2 = 0.0, 2.0'), 'array_pair'),
            (SINDA.replace(b'1.0, 0.0, 1.0\nEND', b'1.0, 0.5, 1.0\nEND'), 'phase_unmapped'),
            (SINDA.replace(b'END OF DATA', b'HEADER VARIABLES 0, MAIN\n      CALL QVTIME(\'MAIN\')\nEND OF DATA'),
             'untranslated_section_or_logic'),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for raw, code in variants:
                with self.subTest(code=code), self.assertRaisesRegex(ExchangeError, code):
                    (root / 'network.sin').write_bytes(raw)
                    adapter.prepare_transient(root, 'network.sin', end=1, samples=2)

    def test_td_time_table_uses_multiplier_and_period_in_declared_source_units(self):
        units = SindaUnits('K', 'J/K', 'W/K', 'mW', 'min')
        with tempfile.TemporaryDirectory() as tmp:
            staged = td_preview(Path(tmp), units=units)
            request = prepare_drawing_transient(staged, end=150, samples=6)
            self.assertFalse(staged.conversion.report['native_ready'])
            (staged.original.root / 'network.dwg').write_bytes(b'AC1032-stale')
            with self.assertRaisesRegex(ExchangeError, 'stale_td_project'):
                prepare_drawing_transient(staged, end=150, samples=6)
        row, = request['time_loads']
        self.assertEqual(row['period_s'], 60)
        self.assertEqual(row['points'], [[0, .002], [30, .006], [60, .004]])
        self.assertEqual(request['transient']['output_times'], [0, 30, 60, 90, 120, 150])

    def test_td_transient_rejects_unordered_time_and_unknown_steady_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for records, code in (
                (td_records(((0, 1), (0, 2))), 'time_load_axis'),
                (td_records(steady_mode=3), 'td_time_load_mode'),
                (td_records(((1, 1), (2, 2))), 'time_load_period'),
            ):
                with self.subTest(code=code), self.assertRaisesRegex(ExchangeError, code):
                    prepare_drawing_transient(td_preview(root, records), end=1, samples=3)
