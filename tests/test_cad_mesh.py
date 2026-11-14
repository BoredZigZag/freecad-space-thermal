# SPDX-License-Identifier: MIT OR Apache-2.0
from copy import deepcopy
from hashlib import sha256
import unittest
import uuid

from fcst_app.cad_mesh import prepare,profile_hash,validate_receipt,reconcile,package
from fcst_app.discretization import read_input
from fcst_contracts import read


def fixture():
    identifier='a0000000-0000-4000-8000-000000000000';brep=b'owned synthetic geometry identity'
    faces=[dict(id=str(uuid.uuid5(uuid.UUID(identifier),str(i))),ref=f'Face{i+1}',signature=sha256(str(i).encode()).hexdigest(),area_m2=1)
        for i in range(4)]
    source=dict(contract_version='1.0.0',geometry=dict(id=identifier,revision=0,brep_sha256=sha256(brep).hexdigest(),
        signature='0'*64,faces=faces),profile_sha256=profile_hash(),mesher_version='4.15.0',
        options=dict(dimension=3,maximum_size_m=1,minimum_size_m=1,order=1,threads=1,algorithm_2d=5,algorithm_3d=1,random_seed=1,optimize=False),
        nodes=[dict(tag=i+1,position_m=p) for i,p in enumerate([[0,0,0],[1,0,0],[0,1,0],[0,0,1]])],
        cells=[dict(tag=11,topology='tet4',nodes=[1,3,2,4],region='Solid1')],
        facets=[dict(tag=i+20,nodes=p,cad_face_id=faces[i]['id']) for i,p in enumerate([[1,2,3],[1,2,4],[1,3,4],[2,3,4]])])
    card=dict(density=dict(value=2,unit='kg/m3'),specific_heat=dict(value=3,unit='J/(kg*K)'),
        conductivity=dict(value=4,unit='W/(m*K)'),temperature=dict(value=350,unit='K'))
    return source,brep,{'Solid1':card}


class CadMeshTests(unittest.TestCase):
    def test_large_spatial_results_preserve_reader_budget_and_request_dependency(self):
        import tempfile
        from pathlib import Path
        from fcst_app.discretization import brick,assignment_payload
        from fcst_app.persistence import Package,encode,semantic_hash
        from fcst_app.store import ProjectStore
        from fcst_contracts import loads,MAX_BYTES
        from fcst_host import review
        value=brick(7,4,2,topology='tet4');model=value['model']
        result=dict(status='passed',model_hash=semantic_hash(model),energy_defect_W=0,internal_exchange_defect_W=0,
            backend=dict(execution_mode='fcst_native',external_reference=False),
            nodes=[dict(node_id=e['id'],temperature_K=350,boundary_power_W=0) for e in model['entities'] if e['kind']=='node'])
        self.assertGreater(len(encode(dict(model=model,result=result,input=value))),MAX_BYTES)
        mesh=next(e['artifact'] for e in model['entities'] if e['kind']=='mesh')
        portable=Package.create(model,[(str(uuid.uuid4()),'conduction_input',mesh['path'],assignment_payload(value),[])])
        with tempfile.TemporaryDirectory() as directory:
            directory=Path(directory)
            with ProjectStore.create(directory/'project.db',package=portable) as store:
                identifier=review.attach_result(store,result,model,value,'0'*64)
                record=next(a for a in store._artifacts() if a[0]==identifier);saved=loads(record[3])
                self.assertEqual(saved['schema_version'],2);self.assertLess(len(record[3]),MAX_BYTES)
                self.assertEqual(len(record[4]),1);self.assertFalse(review.query_result(store,identifier)['historical'])
                store.save(directory/'large.fcst')
            with ProjectStore.create(directory/'reopened.db',package=Package.open(directory/'large.fcst')) as store:
                self.assertEqual(review.query_result(store,identifier)['node_ids'],[n['node_id'] for n in result['nodes']])
                store.db.execute('UPDATE artifacts SET data=? WHERE id=?',(b'{}',record[4][0]))
                with self.assertRaises(ValueError):review.query_result(store,identifier)

    def test_orientation_units_capacity_maps_and_portable_receipt(self):
        source,brep,cards=fixture();original=deepcopy(source)
        value,receipt=prepare(source,brep,cards)
        self.assertEqual(source,original);self.assertEqual(read_input(value),value)
        self.assertEqual(receipt['element_map'][0]['permutation'],[0,2,1,3])
        self.assertAlmostEqual(sum(e['capacity']['value'] for e in value['model']['entities'] if e['kind']=='node'),1)
        ids=[e['id'] for e in value['model']['entities']]
        self.assertFalse(set(ids)&{f['id'] for f in receipt['radiation_facets']})
        self.assertEqual(validate_receipt(receipt,brep),value)
        from fcst_app.persistence import encode
        from fcst_contracts import loads
        self.assertEqual(validate_receipt(loads(encode(receipt)),brep),value)
        self.assertEqual(package(receipt,brep).model,value['model'])

    def test_face_total_power_flux_and_convection_have_explicit_integrals(self):
        source,brep,cards=fixture();face=source['geometry']['faces'][0]['id']
        for kind,amount,power in [('total_power',10,10),('surface_flux',10,5)]:
            value,receipt=prepare(source,brep,cards,[dict(face_id=face,kind=kind,value=dict(value=amount,unit='W' if kind=='total_power' else 'W/m2'))])
            self.assertAlmostEqual(receipt['assignments'][0]['integrated_power_W'],power)
            self.assertEqual(len(value['spatial']['surfaces']),1)
        value,_=prepare(source,brep,cards,[dict(face_id=face,kind='convection',coefficient_W_per_m2_K=4,ambient_temperature=dict(value=20,unit='degC'))])
        self.assertEqual(value['spatial']['surfaces'][0]['ambient_K'],293.15)

    def test_profile_geometry_coverage_and_ambiguous_mapping_fail_closed(self):
        source,brep,cards=fixture()
        mutations=[lambda s:s.update(profile_sha256='0'*64),lambda s:s['cells'][0].update(nodes=[1,2,3,999]),
            lambda s:s['facets'].pop(),lambda s:s['facets'].append(deepcopy(s['facets'][0])),
            lambda s:s['geometry']['faces'][1].update(ref='Face1'),lambda s:s['options'].update(minimum_size_m=2)]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                bad=deepcopy(source);mutate(bad)
                with self.assertRaises(ValueError):prepare(bad,brep,cards)
        with self.assertRaises(ValueError):prepare(source,brep+b'x',cards)
        with self.assertRaises(ValueError):prepare(source,brep,{})
        duplicate=deepcopy(source);duplicate['facets'].append({**source['facets'][0],'tag':99})
        with self.assertRaisesRegex(ValueError,'cad_boundary_mapping'):prepare(duplicate,brep,cards)

    def test_reordering_is_identity_preserving_but_refinement_and_topology_need_reassignment(self):
        source,brep,cards=fixture();value,receipt=prepare(source,brep,cards)
        # Source order is deliberately part of the receipt; canonical entity
        # identity remains bound to exactly the accepted mesher output.
        other=deepcopy(source);other['nodes'].reverse()
        refined,new_receipt=prepare(other,brep,cards)
        self.assertNotEqual(value['spatial']['mesh_revision'],refined['spatial']['mesh_revision'])
        self.assertEqual([f['id'] for f in receipt['source']['geometry']['faces']],[f['id'] for f in new_receipt['source']['geometry']['faces']])
        self.assertTrue(reconcile(receipt,source['geometry']))
        for change in ('split','merge','reorder','delete'):
            geometry=deepcopy(source['geometry'])
            if change=='split':geometry['faces'].append(deepcopy(geometry['faces'][0]))
            elif change=='merge':geometry['faces']=geometry['faces'][:1]
            elif change=='reorder':geometry['faces'].reverse()
            else:geometry['faces'].pop()
            with self.assertRaisesRegex(ValueError,'attachment_reassignment_required'):reconcile(receipt,geometry)

        from fcst_app.cad_mesh import synchronize_project
        from fcst_contracts import loads

        face=source['geometry']['faces'][0]['id']
        boundary=[dict(face_id=face,kind='total_power',value=dict(value=10,unit='W'))]
        _,accepted=prepare(source,brep,cards,boundary)
        previous=package(accepted,brep)
        reopened,report=synchronize_project(previous,source,brep)
        self.assertIs(reopened,previous)
        self.assertEqual(report,dict(status='reused',geometry_changed=False,mesh_changed=False))
        rebuilt,report=synchronize_project(previous,other,brep)
        self.assertEqual(report,dict(status='synchronized',geometry_changed=False,mesh_changed=True))
        self.assertEqual(loads(rebuilt.files['cad-mesh/prepared.json'])['assignments'][0]['integrated_power_W'],10)

        revised=deepcopy(source)
        updated_brep=brep+b' changed'
        revised['geometry']['brep_sha256']=sha256(updated_brep).hexdigest()
        revised['cells'][0]['region']='Solid2'
        replacement='b0000000-0000-4000-8000-000000000000'
        revised['geometry']['faces'][0]['id']=replacement
        revised['facets'][0]['cad_face_id']=replacement
        with self.assertRaisesRegex(ValueError,'attachment_reassignment_required'):
            synchronize_project(previous,revised,updated_brep)
        rebuilt,report=synchronize_project(previous,revised,updated_brep,
                                            region_map={'Solid1':'Solid2'},face_map={face:replacement})
        self.assertTrue(report['geometry_changed'])
        saved=loads(rebuilt.files['cad-mesh/prepared.json'])
        self.assertEqual(saved['source']['geometry']['revision'],1)
        self.assertEqual(saved['boundaries'][0]['face_id'],replacement)
        self.assertEqual(saved['assignments'][0]['integrated_power_W'],10)
        self.assertEqual(loads(previous.files['cad-mesh/prepared.json'])['boundaries'][0]['face_id'],face)

        from argparse import ArgumentParser
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from fcst_app.persistence import Package,encode
        from fcst_cli.td import execute,parsers
        from fcst_exchange.core import ExchangeError

        parser=ArgumentParser()
        parsers(parser.add_subparsers(dest='command',required=True))
        with TemporaryDirectory() as directory:
            root=Path(directory)
            original,mesh,shape,output,mapping=(root/name for name in ('original.fcst','mesh.json','shape.brep','new.fcst','map.json'))
            original.write_bytes(previous.zip_bytes())
            mesh.write_bytes(encode(revised))
            shape.write_bytes(updated_brep)
            mapping.write_bytes(encode({'region_map':{'Solid1':'Solid2'},'face_map':{face:replacement}}))
            args=parser.parse_args(['td-sync-cad-mesh',str(original),str(mesh),str(shape),str(output)])
            with self.assertRaisesRegex(ValueError,'attachment_reassignment_required'):
                execute(args)
            self.assertFalse(output.exists())
            args.mapping=mapping
            self.assertEqual(execute(args)['status'],'synchronized')
            self.assertEqual(Package.open(output).model,rebuilt.model)
            with self.assertRaisesRegex(ExchangeError,'td_output_exists'):
                execute(args)
            self.assertEqual(original.read_bytes(),previous.zip_bytes())

    def test_assignment_conflicts_receipt_tampering_and_unsupported_orders_reject(self):
        source,brep,cards=fixture()
        boundaries=[dict(face_id=f['id'],kind='temperature',value=dict(value=300+i,unit='K')) for i,f in enumerate(source['geometry']['faces'][:2])]
        with self.assertRaisesRegex(ValueError,'cad_boundary_conflict'):prepare(source,brep,cards,boundaries)
        _,receipt=prepare(source,brep,cards);receipt['element_map'][0]['permutation'].reverse()
        with self.assertRaises(ValueError):validate_receipt(receipt,brep)
        for order in (2,True):
            bad=deepcopy(source);bad['options']['order']=order
            with self.assertRaises(ValueError):read('cad_mesh',bad)
