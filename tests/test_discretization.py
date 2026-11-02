# SPDX-License-Identifier: MIT OR Apache-2.0
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from fcst_app.discretization import plate,brick,fd_rod,read_input,seal,assignment_payload,decode_assignment
from fcst_app.persistence import semantic_hash,PersistenceError,Package
from fcst_contracts import ContractError
from fcst_host import review
from fcst_tools.discretization import assess

ROOT=Path(__file__).resolve().parents[1]


class DiscretizationTests(unittest.TestCase):
    def test_canonical_payload_is_bounded_exact_and_rejects_corruption(self):
        value=plate();raw=assignment_payload(value)
        self.assertEqual(decode_assignment(raw),{key:value[key] for key in ('spatial','material_laws','node_storage')})
        for bad in (raw[:-1],raw+b'n',b'o2:s1:ans1:an',b'a999999999:',b'a1:'*66+b'n',b'd7ff0000000000000',b's3:ab',b'a00:',b'x'):
            with self.assertRaises(ValueError):decode_assignment(bad)

    def test_portable_v3_preserves_input_and_does_not_weaken_legacy_mesh_checks(self):
        value=plate();artifact=next(e['artifact'] for e in value['model']['entities'] if e['kind']=='mesh')
        record=(str(__import__('uuid').uuid4()),'conduction_input',artifact['path'],assignment_payload(value),[])
        package=Package.create(value['model'],[record])
        self.assertEqual(package.manifest['contract_version'],'3.0.0');self.assertEqual(package.manifest['minimum_reader'],'3.0.0')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'spatial.fcst';path.write_bytes(package.zip_bytes())
            reopened=Package.open(path)
        self.assertEqual(reopened.model,value['model'])
        self.assertEqual(reopened.files[artifact['path']],assignment_payload(value))
        with self.assertRaises(PersistenceError):Package.create(value['model'],[(record[0],'mesh',*record[2:])])
        with self.assertRaises(PersistenceError):Package.create(value['model'],[(record[0],record[1],record[2],b'{}',[])])

    def test_all_families_have_closed_identities_positive_mass_and_independent_volume(self):
        for topology in ('tri3','quad4','tet4','hex8'):
            value=plate(2,3,topology=topology) if topology in ('tri3','quad4') else brick(2,2,1,topology=topology)
            self.assertEqual(read_input(value),value)
            capacities=sum(e['capacity']['value'] for e in value['model']['entities'] if e['kind']=='node')
            self.assertAlmostEqual(capacities,.1 if topology in ('tri3','quad4') else 1)
            self.assertEqual(len({p['id'] for p in value['spatial']['points']}),len(value['spatial']['points']))
            artifact=next(e['artifact'] for e in value['model']['entities'] if e['kind']=='mesh')
            self.assertEqual(artifact['sha256'],sha256(assignment_payload(value)).hexdigest())

    def test_material_and_load_changes_change_canonical_identity_and_require_repreparation(self):
        value=plate();original=semantic_hash(value['model'])
        material=next(e for e in value['model']['entities'] if e['kind']=='material')
        value['material_laws']=[dict(material_id=material['id'],conductivity=dict(temperature=[dict(value=1,unit='K'),dict(value=5000,unit='K')],
            values=[dict(value=1,unit='W/(m*K)'),dict(value=2,unit='W/(m*K)')],interpolation='linear',extrapolation='error',discontinuities=[]))]
        with self.assertRaisesRegex(ValueError,'spatial_mesh_artifact'):read_input(value)
        value=seal(value);self.assertNotEqual(semantic_hash(value['model']),original)
        self.assertEqual(read_input(value),value)
        value['spatial']['points'][0]['position'][0]+=.1
        with self.assertRaisesRegex(ValueError,'spatial_mesh_revision'):read_input(value)

    def test_generation_rejects_unbounded_nonfinite_fractional_and_wrong_families(self):
        for fn in (lambda:plate(0),lambda:brick(33),lambda:plate(True),lambda:plate(1.5),lambda:plate(length=float('nan')),
                   lambda:brick(topology='tet10'),lambda:plate(topology='tet4'),lambda:fd_rod(area=-1)):
            with self.assertRaises(ValueError):fn()

    def test_fd_half_cell_boundaries_preserve_volume_and_total_resistance(self):
        value=fd_rod(4,length=2,area=3,density=2,specific_heat=5,conductivity=7)
        nodes=[e for e in value['model']['entities'] if e['kind']=='node'];links=[e for e in value['model']['entities'] if e['kind']=='conductor']
        self.assertEqual(sum(e['capacity']['value'] for e in nodes),60)
        self.assertAlmostEqual(sum(1/e['conductance']['value'] for e in links),2/21)

    def test_packaged_schema_rejects_future_units_elements_and_unknown_fields(self):
        for key,value in [('length_unit','mm'),('unexpected',True)]:
            v=plate();v['spatial'][key]=value
            with self.assertRaises(ContractError):read_input(v)
        v=plate();v['spatial']['cells'][0]['topology']='tri6'
        with self.assertRaises(ContractError):read_input(v)

    def test_host_request_keeps_complete_spatial_input_and_rejects_stale_models(self):
        value=plate();flag,envelope=review.request(value['model'],{**review.DEFAULT_SETTINGS,'mode':'steady'},thermal_input=value)
        self.assertEqual(flag,'--thermal-steady');self.assertEqual(envelope,value)
        flag,envelope=review.request(value['model'],review.DEFAULT_SETTINGS,thermal_input=value)
        self.assertEqual(flag,'--thermal-transient');self.assertEqual(envelope['thermal_input'],value)
        model=deepcopy(value['model']);next(e for e in model['entities'] if e['kind']=='node')['temperature']['value']+=1
        with self.assertRaisesRegex(PersistenceError,'stale_spatial_input'):review.request(model,review.DEFAULT_SETTINGS,thermal_input=value)

    def test_evidence_rejects_stale_candidate_sources_binary_qualification_and_missing_cases(self):
        policy=json.loads((ROOT/'ci/discretization-acceptance.json').read_bytes())
        cases=[dict(id=case,status='passed') for case in policy['required_cases']]
        from fcst_tools.gate import evaluate
        report=dict(schema_version=1,candidate='a'*40,input_sha256={'synthetic':'b'*64},execution_mode='fcst_native',
                    policy_sha256=sha256(json.dumps(policy,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                    worker_sha256='c'*64,full_wp16_qualified=False,cases=cases,gate=evaluate(policy['required_cases'],cases),
                    commands=100,metrics=dict(jacobian_maximum_error=1e-10,steady_field_errors_K=[.16,.04,.01],
                        transient_spatial_errors_K=[.16,.04,.01],transient_time_errors_K=[.04,.02,.01]))
        from fcst_contracts import canonical
        report['offline_native']=dict(kind='windows-appcontainer-v1',execution_mode='fcst_native',app_container=True,capabilities=0,
            network_denied=True,network_denial='controlled_loopback_timeout',network_positive_controls=2,negative_probes=2,
            outside_files_denied=4,cases=[dict(id=c,status='passed') for c in policy['offline_native_cases']],
            binary_sha256={name:'c'*64 for name in policy['offline_native_binaries']},
            inventory_sha256=sha256(canonical(policy['offline_native_cases'][:-2])).hexdigest())
        self.assertTrue(assess(report,policy,report['input_sha256'],'a'*40))
        for key,bad in [('candidate','d'*40),('input_sha256',{}),('worker_sha256','bad'),('full_wp16_qualified',True),('cases',cases[:-1]),('metrics',{})]:
            with self.assertRaises(ValueError):assess({**report,key:bad},policy,report['input_sha256'],'a'*40)
        for key,bad in [('cases',report['offline_native']['cases'][:-1]),('network_denied',False),('network_positive_controls',0),
                        ('binary_sha256',{}),('app_container',False),('capabilities',1),('inventory_sha256','0'*64)]:
            value=deepcopy(report);value['offline_native'][key]=bad
            with self.assertRaises(ValueError):assess(value,policy,report['input_sha256'],'a'*40)

    def test_cli_prepares_new_files_and_cannot_overwrite_existing_inputs(self):
        from fcst_cli.discretization import execute,parsers
        import argparse
        parser=argparse.ArgumentParser();parsers(parser.add_subparsers(dest='command'))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.json'
            args=parser.parse_args(['spatial-primitive','plate','--output',str(path)])
            self.assertEqual(execute(args)['status'],'prepared');original=path.read_bytes();read_input(json.loads(original))
            with self.assertRaises(PersistenceError):execute(args)
            self.assertEqual(path.read_bytes(),original)
