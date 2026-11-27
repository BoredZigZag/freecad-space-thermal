# SPDX-License-Identifier: MIT OR Apache-2.0
from pathlib import Path
from tempfile import TemporaryDirectory
import math
import unittest

from fcst_app.discretization import read_input
from fcst_exchange import ExchangeError
from fcst_exchange.td_fd import prepare_fd
from fcst_exchange.td_fe import prepare_elements

from td_geometry_fixture import (FE_CLASSES, saved_element_records, shared_fd_records,
                                 spatial_law_properties, spatial_preview, spatial_properties,
                                 spatial_source_records)


def prepare(converter, staged, **options):
    return converter(staged, 'fixture.tdp', 'mm', temperature=300, temperature_range=(250,450), **options)


class TdThermalGeometryTests(unittest.TestCase):
    def test_centered_and_edge_fd_have_conservative_storage_and_axial_links(self):
        with TemporaryDirectory() as directory:
            for centered, sizes in ((True,(8,12)), (False,(27,54))):
                staged = spatial_preview(Path(directory),records=spatial_source_records(centered=centered))
                value, report = prepare(prepare_fd,staged)
                self.assertEqual((report['nodes'],report['conductors']),sizes)
                self.assertEqual(len(value['node_storage']),sizes[0])
                self.assertAlmostEqual(math.fsum(e['capacity']['value'] for e in value['model']['entities'] if e['kind']=='node'),9.6e-5)
                self.assertEqual(len([e for s in value['model']['source_maps'] for e in s['entries'] if 'node_number' in e]),sizes[0])
                if centered:
                    ids = {e['entity_id']:e['node_number'] for s in value['model']['source_maps'] for e in s['entries'] if 'node_number' in e}
                    links = {tuple(sorted((ids[e['from_node_id']],ids[e['to_node_id']]))):e['conductance']['value']
                             for e in value['model']['entities'] if e['kind']=='conductor'}
                    self.assertAlmostEqual(links[100,102],7*.0015*.004/.002)
                    self.assertAlmostEqual(links[100,104],7*.002*.004/.003)
                    self.assertAlmostEqual(links[100,108],7*.002*.0015/.004)

    def test_fd_merges_shared_nodes_and_parallel_links_with_complete_owner_selection(self):
        with TemporaryDirectory() as directory:
            staged = spatial_preview(Path(directory),records=shared_fd_records())
            value,report = prepare(prepare_fd,staged)
            self.assertEqual((report['nodes'],report['conductors']),(6,7))
            entities = {e['id']:e for e in value['model']['entities']}
            keys = {e['node_number']:e['entity_id'] for s in value['model']['source_maps'] for e in s['entries'] if 'node_number' in e}
            shared = {keys[i] for i in (2,5)}
            self.assertAlmostEqual(entities[keys[2]]['capacity']['value'],2*entities[keys[1]]['capacity']['value'])
            link = next(e for e in entities.values() if e['kind']=='conductor' and {e['from_node_id'],e['to_node_id']}==shared)
            self.assertAlmostEqual(link['conductance']['value'],4*.002*.002/.003)
            with self.assertRaisesRegex(ExchangeError,'owner_closure'):
                prepare(prepare_fd,staged,handles=(101,))

    def test_fd_binds_face_power_to_source_nodes_and_rejects_variable_conductance(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            records = spatial_source_records()
            value,_ = prepare(prepare_fd,spatial_preview(root,records=records),face_load_handle=110,power_unit='mW')
            power = [e['power']['value'] for e in value['model']['entities'] if e['kind']=='load']
            self.assertEqual(sorted(round(p,12) for p in power),[6e-6,6e-6,18e-6,18e-6])
            with self.assertRaisesRegex(ExchangeError,'variable_conductance'):
                prepare(prepare_fd,spatial_preview(root,records=records,properties=spatial_law_properties()))

    def test_saved_finite_elements_share_source_nodes_and_integrate_distinct_materials(self):
        with TemporaryDirectory() as directory:
            staged = spatial_preview(Path(directory),records=saved_element_records(),geometry_classes=FE_CLASSES)
            value,report = prepare(prepare_elements,staged)
            self.assertEqual(value,read_input(value))
            self.assertEqual((report['points'],report['cells'],report['materials']),(14,4,2))
            self.assertEqual({e['topology'] for e in value['spatial']['cells']},{'tri3','quad4','tet4','hex8'})
            expected=(3+6.75)*2e-9*600+(1+6)*1e-9*500
            self.assertAlmostEqual(math.fsum(e['capacity']['value'] for e in value['model']['entities'] if e['kind']=='node'),expected)
            self.assertEqual(len({r['entity_id'] for s in value['model']['source_maps'] for r in s['entries']
                                  if r['namespace']=='TD.DWG.FE-NODE'}),14)

    def test_saved_boundaries_use_declared_units_and_inactive_empty_aggregate(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            # The sheet keeps its existing nonempty aggregate. Only add an
            # empty editor block to the solid after its final scalar field.
            properties = spatial_properties().replace(b'[SPECHEAT]\r\n50\r\n',
                b'[SPECHEAT]\r\n50\r\n[AGGREGATE]\r\n[KXP]\r\n0.5\r\n[ENDAGGREGATE]\r\n',1)
            self.assertNotEqual(properties,spatial_properties())
            for converter, records, classes, diagnostic in (
                    (prepare_fd,spatial_source_records(prescribed=True),None,'td_fd_saved_node_mode'),
                    (prepare_elements,saved_element_records(prescribed=True),FE_CLASSES,'td_fe_saved_node_mode')):
                staged = spatial_preview(root,records=records,properties=properties,geometry_classes=classes)
                with self.assertRaisesRegex(ExchangeError,diagnostic):
                    prepare(converter,staged)
                value, _ = prepare(converter,staged,node_temperature_unit='degC')
                fixed, = [e for e in value['model']['entities'] if e.get('classification')=='prescribed']
                self.assertAlmostEqual(fixed['temperature']['value'],298.15)
                self.assertEqual(fixed['capacity']['value'],0)
                self.assertFalse(any(row['node_id']==fixed['id'] for row in value['node_storage']))
