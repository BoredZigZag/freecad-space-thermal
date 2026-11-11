# SPDX-License-Identifier: MIT OR Apache-2.0
"""Owned AC1032 project settings, reference, and dependency regressions."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fcst_exchange.core import ExchangeError
from fcst_exchange.dwg_native import Fields, NativeSnapshot, _one
from fcst_exchange.independent_td import DwgPreview, decode_drawing
from fcst_exchange.sinda import SindaUnits
from fcst_exchange.source_tree import capture_project
from fcst_exchange.td_project_graph import companion_inventory, dictionary_graph
from fcst_exchange.td_project_inventory import inspect_project
from fcst_exchange.td_project_records import decode_project_record
from fcst_exchange.td_writer import FilerWriter, node_payload
from td_fixture import drawing, envelope


ORBIT = 2**60 + 7
ROOT = 50
MANAGER = 60
ENTRY = 'model/main.dwg'


def handle(target, code=0):
    return [code, (target.bit_length() + 7) // 8, target]


def object_record(filer, number, cpp, dxf, target):
    row, common = envelope(filer.result(number - 499), handle=target)
    row['kind'] = 'UNKNOWN_OBJ'
    common.pop('layer')
    common.update({'handle': handle(target), 'ownerhandle': [5, 0, 0], 'reactors': []})
    return row, Fields(common.items()), {'number': number, 'cppname': cpp, 'dxfname': dxf}


def orbit_filer(version=35):
    f = FilerWriter()
    b = f.data

    def ints(n):
        for _ in range(n):
            b.bl(0)

    def doubles(n):
        for _ in range(n):
            b.bd(0)

    def expressions(n):
        for _ in range(n):
            f.expression()

    b.bl(version)
    b.bl(0)
    b.bs(0)
    doubles(9)
    b.bd(37.5)
    doubles(4)
    for number in (400, 600, 0.03, 5400):
        b.bd(number)
    ints(3)
    b.bl(-1)
    doubles(2)
    ints(1)
    doubles(2)
    ints(1)
    doubles(5)
    ints(5)
    doubles(3)
    b.bl(1)
    b.bl(1)
    b.bd(120)
    b.bl(1)
    b.point((0, 1, 0))
    ints(1 + 1 + 6 + 5 + 1 + 1 + 3)
    doubles(1)
    ints(4)
    expressions(21)
    ints(2)
    expressions(1)
    ints(1 + 3 + 1 + 1)
    f.text('synthetic trajectory')
    ints(3)
    for _ in range(2):
        ints(1)
        doubles(1)
        expressions(1)
        ints(3)
    ints(1)
    doubles(1)
    ints(1)
    for _ in range(3):
        doubles(1)
        expressions(1)
    expressions(6)
    ints(4)
    doubles(2)
    expressions(2)
    b.put(1, 1)
    ints(10)
    f.text('fixture orbit')
    return f


def case_filer(orbit_name='TEST ORBIT'):
    f = FilerWriter()
    b = f.data

    def zeros(layout):
        for kind in layout:
            {'i': b.bl, 'd': b.bd, 't': f.text}[kind]('' if kind == 't' else 0)

    for value in (11, 0, 0, 1, 73):
        b.bl(value)
    f.text('Synthetic case')
    zeros('i')
    b.bl(1)
    b.bl(1)
    f.text('generated.inp')
    zeros('i' * 9)
    b.bl(1)
    b.bl(36)
    f.text('Synthetic radiation')
    f.text(orbit_name)
    b.bl(1)
    zeros('iidiiiiidddd' 'ttitdittiiiiit' 'iiiiiiiiiiidiiiidtiiitititddiiidtiii')
    b.bl(1)
    b.bl(5)
    zeros('diiidiiii')
    for _ in range(4):
        f.expression()
    zeros('iii')
    b.put(2, 3)
    b.raw(b'\x34\x12')
    b.put(0, 3)
    zeros('diiiiidddttidddtti')
    for _ in range(20):
        f.expression()
    zeros('iddii')
    for _ in range(3):
        f.expression()
    zeros('iiddd')
    f.expression()
    zeros('itd')
    f.expression()
    zeros('iiitiiiid')
    f.expression()
    zeros('iiiiii')
    b.bl(1)
    b.bl(1)
    f.text('Libraries\\OPTICAL.RCO')
    f.text('libraries/material.tdp')
    zeros('i' * 8)
    f.text('synthetic operations')
    zeros('t' * 11)
    b.bl(99)  # Deliberately opaque remainder of the case.
    return f


def project_snapshot(orbit_name='TEST ORBIT', orbit_version=35):
    base = drawing([node_payload('OWNED', 1, 290, 10, 'capacitive')])
    native = {**base.native, 'objects': list(base.native['objects']), 'classes': list(base.native['classes'])}
    standards = list(_one(base.standard, 'OBJECTS'))
    for specification in ((case_filer(orbit_name), 505, 'CaseSetManager', 'RCCASESET', MANAGER),
                          (orbit_filer(orbit_version), 506, 'RcOrbit', 'RCORBIT', ORBIT)):
        row, common, identity = object_record(*specification)
        native['classes'].append(identity)
        native['objects'].append(row)
        standards.append(common)
    native['objects'].append({'handle': ROOT, 'type': 42, 'kind': 'DICTIONARY', 'bits': 0, 'rest_bits': 0})
    items = Fields([('test orbit', handle(ORBIT, 3)), ('case sets', handle(MANAGER, 3))])
    standards.append(Fields([('handle', handle(ROOT)), ('numitems', 2), ('items', items)]))
    header = Fields([*_one(base.standard, 'HEADER'), ('DICTIONARY_NAMED_OBJECT', handle(ROOT))])
    return NativeSnapshot(native, Fields([('HEADER', header), ('OBJECTS', standards)]), base.digest)


class TdProjectInventoryTests(unittest.TestCase):
    def test_project_inventory_binds_radiation_orbit_and_active_companions(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'model/libraries').mkdir(parents=True)
            (root / ENTRY).write_bytes(b'AC1032 owned fixture')
            (root / 'model/libraries/optical.rco').write_bytes(b'opaque synthetic optics')
            (root / 'model/libraries/material.tdp').write_bytes(b'opaque synthetic properties')
            original = capture_project(root, ENTRY)
            report = inspect_project(DwgPreview(original, project_snapshot()))
            self.assertEqual(capture_project(root, ENTRY), original)
            self.assertEqual(report['dictionary_graph']['diagnostics'], [])
            self.assertEqual(report['status_counts'], {'payload-decoded': 2, 'partial-payload': 1})
            case, orbit = report['configuration']
            settings = case['settings']['cases'][0]
            self.assertEqual((settings['steady'], settings['transient']), (1, 1))
            self.assertEqual(settings['source_sections']['operations'], 'synthetic operations')
            task, = settings['radiation_tasks']
            self.assertEqual(task['orbit_binding'], {'status': 'resolved', 'targets': [str(ORBIT)]})
            self.assertEqual(task['parameter_sets'][0]['wide_values'], ('4660', '0'))
            self.assertEqual(orbit['settings']['inclination'], 37.5)
            self.assertEqual(orbit['settings']['times'], (120,))
            self.assertEqual(orbit['settings']['sun_vectors'], ((0, 1, 0),))
            self.assertEqual(report['companion_inventory']['resolution_counts'], {'resolved': 2})
            self.assertFalse(report['full_model_dependency_closure'])
            self.assertFalse(report['native_ready'])
            (root / ENTRY).write_bytes(b'AC1032 stale fixture')
            with self.assertRaisesRegex(ExchangeError, 'stale_td_project'):
                inspect_project(DwgPreview(original, project_snapshot()))

    def test_future_payload_and_damaged_dictionary_links_fail_closed(self):
        snapshot = project_snapshot(orbit_version=36)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'model').mkdir()
            (root / ENTRY).write_bytes(b'AC1032 owned fixture')
            report = inspect_project(DwgPreview(capture_project(root, ENTRY), snapshot))
        case, orbit = report['configuration']
        self.assertEqual(orbit['limitations'], ['td_filer_version'])
        self.assertEqual(case['settings']['cases'][0]['radiation_tasks'][0]['orbit_binding']['status'], 'opaque')

        objects = {r['handle']: r for r in snapshot.native['objects']}
        standards = {_one(r, 'handle')[2]: r for r in _one(snapshot.standard, 'OBJECTS')}
        items = Fields([('self', handle(ROOT)), ('missing', [6, 0, 0, ROOT + 1])])
        standards[ROOT] = Fields([('numitems', len(items)), ('items', items)])
        graph, reached = dictionary_graph(snapshot, objects, standards)
        self.assertEqual(reached, {ROOT})
        self.assertEqual([d['code'] for d in graph['diagnostics']],
                         ['td_project_dictionary_target_missing', 'td_project_dictionary_cycle'])
        items.append(('SELF', handle(ROOT)))
        standards[ROOT][0] = ('numitems', len(items))
        with self.assertRaisesRegex(ExchangeError, 'td_project_dictionary_key'):
            dictionary_graph(snapshot, objects, standards)

    def test_declared_companions_stay_inside_the_captured_tree(self):
        files = ((ENTRY, b'DWG'), ('model/owned.rco', b'optics'), ('shared.tdp', b'materials'))
        references = [{'path': name, 'role': 'thermophysical-library'} for name in
                      ('../shared.tdp', 'C:\\shared.tdp', 'owned.rco', 'missing.tdp')]
        self.assertEqual(companion_inventory(files, ENTRY, references)['resolution_counts'],
                         {'external-or-unsafe': 2, 'wrong-file-role': 1, 'missing': 1})

    def test_symbol_manager_requires_exact_payload_and_preview_reuses_thermal_decode(self):
        f = FilerWriter()
        f.data.bl(7)
        f.data.bl(2)
        for value in ('Ω', 'one', 'Ω', 'two'):
            f.text(value)
        for value in (0, 0, 0, 1):
            f.data.bl(value)
        f.text('Ω')
        for value in (4, 1, 0, 0, 0, 0, 0):
            f.data.bl(value)
        specification = (507, 'RcDbSymbolManager', 'RCDBSYMBOLMANAGER', 99)
        report = decode_project_record(*object_record(f, *specification))
        self.assertEqual(report['settings']['text_maps'][0], (('Ω', 'one'), ('Ω', 'two')))
        f.data.bl(0)
        with self.assertRaisesRegex(ExchangeError, 'td_filer_unconsumed_stream'):
            decode_project_record(*object_record(f, *specification))

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'main.dwg').write_bytes(b'AC1032 owned fixture')
            units = SindaUnits('K', 'J/K', 'W/K', 'W', 's')
            staged = DwgPreview(capture_project(root, 'main.dwg'), drawing([]), units)
            with (patch('fcst_exchange.independent_td.decode_drawing', wraps=decode_drawing) as decode,
                  patch('fcst_exchange.td_model.decode_drawing', wraps=decode_drawing) as conversion_decode,
                  patch('fcst_exchange.td_decode.decode_drawing', wraps=decode_drawing) as property_decode):
                self.assertFalse(staged.report['qualified'])
                decode.assert_called_once_with(staged.snapshot)
                conversion_decode.assert_not_called()
                property_decode.assert_not_called()
