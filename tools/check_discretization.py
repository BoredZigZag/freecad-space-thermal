# SPDX-License-Identifier: MIT OR Apache-2.0
"""Independent native spatial patches, conservation, refinement and rejection cases."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python'))
from fcst_app.discretization import plate,brick,fd_rod,seal,identity
from fcst_app.persistence import semantic_hash
from fcst_tools.discretization import input_hashes,assess
from fcst_tools.gate import evaluate


def nodes(value):
    return sorted((e for e in value['model']['entities'] if e['kind']=='node'),key=lambda e:e['id'])


def coordinate(value):
    return {p['node_id']:p['position'] for p in value['spatial']['points']}


def set_boundary(value, predicate, temperature):
    points=coordinate(value)
    for n in nodes(value):
        if predicate(points[n['id']]):
            n.update(classification='prescribed',capacity=dict(value=0,unit='J/K'),temperature=dict(value=temperature(points[n['id']]),unit='K'))
    return value


def loads(value, power):
    points=coordinate(value)
    for n in nodes(value):
        value['model']['entities'].append(dict(id=identity('load-'+n['id']),kind='load',node_id=n['id'],
            power=dict(value=power(n,points[n['id']]),unit='W')))
    return value


def check(worker, report):
    policy=json.loads((ROOT/'ci/discretization-acceptance.json').read_bytes());criteria=policy['criteria']
    report.unlink(missing_ok=True)
    for name in [*policy['required_cases'],'acceptance-error']:(report.parent/(name+'.log')).unlink(missing_ok=True)
    candidate=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    inputs=input_hashes(ROOT);binary=sha256(worker.read_bytes()).hexdigest()
    env={k:v for k,v in os.environ.items() if k.upper() not in {'PYTHONPATH','PYTHONHOME','FREECAD_LIB','FREECAD_USER_HOME','SINDAPATH','ESATAN'}}
    env['PATH']=str(worker.parent)
    records=[];metrics={};commands=0
    def run(value,flag='--thermal-steady',passed=True):
        nonlocal commands
        commands+=1
        # Valid test changes explicitly prepare a fresh content-bound input.
        # Rejection cases deliberately retain stale bindings when testing them.
        if passed:
            if 'spatial' in value:value=seal(value)
            elif 'thermal_input' in value and 'spatial' in value['thermal_input']:value={**value,'thermal_input':seal(value['thermal_input'])}
        r=subprocess.run([str(worker),flag],input=json.dumps(value,allow_nan=False).encode(),capture_output=True,env=env,timeout=60)
        out=json.loads(r.stdout)
        assert r.returncode==(0 if out['status']=='passed' else 1) and not r.stderr
        assert (out['status']=='passed')==passed, out
        return out
    def field(value, function=lambda p:300+2*p[0]+3*p[1]+4*p[2]):
        p=coordinate(value)
        return run(dict(thermal_input=value,temperature_K=[function(p[n['id']]) for n in nodes(value)]),'--spatial-evaluate')
    def near(a,b,tolerance=1e-9):
        assert math.isfinite(a) and math.isfinite(b) and abs(a-b)<=tolerance,(a,b,tolerance)
    def reject(value,code=None,seal_input=True):
        if seal_input and 'spatial' in value:value=seal(value)
        out=run(value,'--thermal-prepare',False)
        if code:assert out['code'] in code,out
    def fd():
        for n in (1,4,16):
            v=fd_rod(n,conductivity=2,area=3,length=4);out=run(v)
            by_id={r['node_id']:r for r in out['nodes']}
            for i in range(1,n+1):near(by_id[identity(f'fd-node-{i}')]['temperature_K'],300+100*(i-.5)/n)
            near(abs(by_id[identity('fd-node-0')]['boundary_power_W']),150)
    def patches():
        for topology in policy['families']:
            v=plate(2,2,topology=topology,conductivity=2) if topology in ('tri3','quad4') else brick(2,1,1,topology=topology,conductivity=2)
            out=field(v);expected=[-4,-6,0 if topology in ('tri3','quad4') else -8]
            for cell in out['cells']:
                for a,b in zip(cell['heat_flux_W_per_m2'],expected):near(a,b,criteria['patch_absolute'])
            near(sum(out['conductive_in_W']),0,criteria['energy_absolute_W'])
            near(sum(out['capacity_J_per_K']),.1 if topology in ('tri3','quad4') else 1)
    def tensor():
        v=brick(tensor=[[2,0,0],[0,3,0],[0,0,4]],rotation=[[0,-1,0],[1,0,0],[0,0,1]])
        out=field(v)
        for c in out['cells']:
            for a,b in zip(c['heat_flux_W_per_m2'],[-6,-6,-16]):near(a,b)
        v=plate(tensor=[[2,0,1],[0,3,0],[1,0,4]])
        for c in field(v)['cells']:
            for a,b in zip(c['heat_flux_W_per_m2'],[-3.5,-9,0]):near(a,b)
        v=plate(tensor=[[4,1,0],[1,3,0],[0,0,2]])
        for p in v['spatial']['points']:p['position']=[0,p['position'][1],p['position'][0]]
        for c in field(v)['cells']:
            for a,b in zip(c['heat_flux_W_per_m2'],[0,-8.25,-8]):near(a,b)
    def jacobian():
        v=plate(1,1,conductivity=2)
        material=next(e for e in v['model']['entities'] if e['kind']=='material')
        v['material_laws']=[dict(material_id=material['id'],conductivity=dict(temperature=[dict(value=1,unit='K'),dict(value=5000,unit='K')],
            values=[dict(value=1.01,unit='W/(m*K)'),dict(value=51,unit='W/(m*K)')],interpolation='linear',extrapolation='error',discontinuities=[]))]
        p=coordinate(v);t=[300+2*p[n['id']][0]+3*p[n['id']][1] for n in nodes(v)]
        base=run(dict(thermal_input=v,temperature_K=t),'--spatial-evaluate');maximum=0
        matrix={(int(i),int(j)):a for i,j,a in base['jacobian']}
        for j in range(len(t)):
            plus=t.copy();minus=t.copy();plus[j]+=1e-4;minus[j]-=1e-4
            a=run(dict(thermal_input=v,temperature_K=plus),'--spatial-evaluate')['residual_W']
            b=run(dict(thermal_input=v,temperature_K=minus),'--spatial-evaluate')['residual_W']
            for i in range(len(t)):maximum=max(maximum,abs((a[i]-b[i])/2e-4-matrix.get((i,j),0)))
        assert maximum<criteria['jacobian_absolute'];metrics['jacobian_maximum_error']=maximum
    def enthalpy():
        v=brick(density=2,specific_heat=3);m=next(e for e in v['model']['entities'] if e['kind']=='material')
        # cp(T)=0.01*T, exact integrated storage from 300 to 400 is 700 J.
        v['material_laws']=[dict(material_id=m['id'],specific_heat=dict(temperature=[dict(value=1,unit='K'),dict(value=5000,unit='K')],
            values=[dict(value=.01,unit='J/(kg*K)'),dict(value=50,unit='J/(kg*K)')],interpolation='linear',extrapolation='error',discontinuities=[]))]
        out=field(v,lambda p:400);near(sum(out['storage_change_J']),700);near(sum(out['capacity_J_per_K']),8)
    def surface():
        for kind,value,expected in [('flux',4,2),('power',4,4)]:
            v=plate();v['spatial']['surfaces']=[dict(id=identity('surface'),kind=kind,point_ids=v['spatial']['cells'][0]['point_ids'],value_SI=value,ambient_K=0)]
            near(sum(field(v)['load_in_W']),expected)
    def convection():
        v=plate();v['spatial']['surfaces']=[dict(id=identity('surface'),kind='convection',point_ids=v['spatial']['cells'][0]['point_ids'],value_SI=4,ambient_K=400)]
        out=field(v,lambda p:300);near(sum(out['environment_in_W']),200)
    def contact_value(kind):
        v=plate();nn=nodes(v)
        v['spatial']['contacts']=[dict(id=identity('contact'),kind=kind,calibration_id=identity('calibration'),
            **{'from':[dict(node_id=nn[0]['id'],weight=1)],'to':[dict(node_id=nn[1]['id'],weight=1)]},
            area_m2=2,coefficient_SI=.5 if kind=='mli' else 3,gap_m=.2 if kind=='insulation' else 0,
            minimum_temperature_K=100,maximum_temperature_K=1000,maximum_power_W=100000)]
        return v
    def contacts():
        v=contact_value('contact');t=[400,300,300,300];out=run(dict(thermal_input=v,temperature_K=t),'--spatial-evaluate')
        base=deepcopy(v);base['spatial']['contacts']=[];plain=run(dict(thermal_input=base,temperature_K=t),'--spatial-evaluate')
        near(out['conductive_in_W'][0]-plain['conductive_in_W'][0],-600);near(sum(out['conductive_in_W']),0)
    def reduced():
        for kind in ('mli','insulation','heat_pipe'):
            v=contact_value(kind);t=[400,300,300,300];out=run(dict(thermal_input=v,temperature_K=t),'--spatial-evaluate')
            base=deepcopy(v);base['spatial']['contacts']=[];plain=run(dict(thermal_input=base,temperature_K=t),'--spatial-evaluate')
            expected=5.670374419e-8*(400**4-300**4) if kind=='mli' else 3000 if kind=='insulation' else 300
            near(out['conductive_in_W'][0]-plain['conductive_in_W'][0],-expected,1e-8)
    def steady_refine():
        errors=[]
        for n in criteria['steady_refinements']:
            v=plate(n,1,topology='quad4',thickness=1)
            set_boundary(v,lambda p:p[0] in (0,1),lambda p:300)
            loads(v,lambda node,p:2*node['capacity']['value'])
            out=run(v);by_id={r['node_id']:r['temperature_K'] for r in out['nodes']}
            # The complete linear field is sampled at cell centres, not only at nodes.
            expected=lambda x:300+x*(1-x)
            error=0
            for c in v['spatial']['cells']:
                point={p['id']:p for p in v['spatial']['points']};ps=[point[i] for i in c['point_ids']]
                x=sum(p['position'][0] for p in ps)/4
                error=max(error,abs(sum(by_id[p['node_id']] for p in ps)/4-expected(x)))
            errors.append(error);near(out['energy_defect_W'],0,criteria['energy_absolute_W'])
        assert all(a/b>criteria['steady_minimum_error_ratio'] for a,b in zip(errors,errors[1:]));metrics['steady_field_errors_K']=errors
    def transient_case(n,h,end):
        v=plate(n,1,topology='quad4',thickness=1,temperature=lambda i,p:300+math.sin(math.pi*p[0]))
        set_boundary(v,lambda p:p[0] in (0,1),lambda p:300)
        out=run(dict(thermal_input=v,transient=dict(start=0,end=end,output_times=[0,end],initial_step=h,maximum_step=h,
            absolute_temperature_tolerance=1,relative_temperature_tolerance=0,include_steps=False)),'--thermal-transient')
        p=coordinate(v);sample=out['samples'][-1];temperature=dict(zip(out['node_ids'],sample['temperature_K']))
        amplitude=temperature[identity(f'node-{n//2}')]-300
        assert all(s['valid'] for s in out['samples']);near(sum(sample['storage_power_W'])-sum(sample['load_in_W'])-sum(sample['environment_in_W'])-sum(sample['boundary_power_W']),0,criteria['energy_absolute_W'])
        return amplitude
    def spatial_refine():
        exact=math.exp(-math.pi**2*criteria['spatial_end_s']);errors=[]
        for n in criteria['spatial_refinements']:
            errors.append(abs(transient_case(n,criteria['spatial_maximum_step_s'],criteria['spatial_end_s'])-exact))
        assert all(a/b>criteria['spatial_minimum_error_ratio'] for a,b in zip(errors,errors[1:]));metrics['transient_spatial_errors_K']=errors
    def time_refine():
        n=8;end=criteria['time_end_s'];exact=math.exp(-4*n*n*math.sin(math.pi/(2*n))**2*end)
        errors=[abs(transient_case(n,h,end)-exact) for h in criteria['time_steps_s']]
        assert all(a/b>criteria['time_minimum_error_ratio'] for a,b in zip(errors,errors[1:]));metrics['transient_time_errors_K']=errors
    def reordering():
        v=plate(2,2);a=field(v);v['model']['entities'].reverse();v['model']['mappings'].reverse();b=field(v)
        assert a==b
        v['spatial']['points'].reverse();v=seal(v);c=field(v)
        assert a['preparation_hash']!=c['preparation_hash'] and a['conductive_in_W']==c['conductive_in_W']
    def invalid_mesh():
        for change in ('inverted','degenerate','type','volume','capacity','point'):
            v=brick()
            if change=='inverted':v['spatial']['cells'][0]['point_ids'][1:3]=reversed(v['spatial']['cells'][0]['point_ids'][1:3])
            if change=='degenerate':v['spatial']['points'][1]['position']=v['spatial']['points'][0]['position']
            if change=='type':v['spatial']['cells'][0]['topology']='tet10'
            if change=='volume':next(e for e in v['model']['entities'] if e['kind']=='element')['volume']=2
            if change=='capacity':nodes(v)[0]['capacity']['value']*=2
            if change=='point':v['spatial']['points'][1]['node_id']=v['spatial']['points'][0]['node_id']
            reject(seal(v))
    def invalid_mappings():
        v=brick();v['model']['mappings'].pop();reject(v)
        v=brick();v['model']['mappings'][0]['to_id']=identity('absent');reject(v)
    def invalid_materials():
        v=plate();m=next(e for e in v['model']['entities'] if e['kind']=='material');m['conductivity']['value']=-1;reject(v)
        v=plate(tensor=[[1,0,0],[0,1,0],[0,0,1]]);next(e for e in v['model']['entities'] if e['kind']=='material')['conductivity_tensor'][2][2]=-1;reject(v)
    def invalid_contacts():
        for change in ('gap','weight','overlap','calibration','range','limit'):
            v=contact_value('contact');c=v['spatial']['contacts'][0]
            if change=='gap':c['gap_m']=.1
            if change=='weight':c['from'][0]['weight']=.5
            if change=='overlap':c['to']=deepcopy(c['from'])
            if change=='calibration':c['calibration_id']=''
            if change=='range':c['maximum_temperature_K']=20
            if change=='limit':c['maximum_power_W']=.01
            if change=='limit':run(dict(thermal_input=seal(v),temperature_K=[400,300,300,300]),'--spatial-evaluate',False)
            else:reject(v)
    def stale():
        v=plate();v['spatial']['points'][0]['position'][0]+=.1;reject(v,{'spatial_mesh_revision'},False)
        v=plate();next(e for e in v['model']['entities'] if e['kind']=='mesh')['artifact']['sha256']='0'*64;reject(v,{'spatial_mesh_artifact'},False)
        v=plate();v['contract_version']='1.0.0';reject(v,{'schema'})
    def offline():
        r=subprocess.run([str(worker),'--build-info'],capture_output=True,env=env,timeout=30);info=json.loads(r.stdout)
        assert r.returncode==0 and info['source_revision']==candidate and info['engine']=='fcst_native'
        v=plate();set_boundary(v,lambda p:p[0]==0,lambda p:300);out=run(v)
        assert out['backend']['execution_mode']=='fcst_native' and not out['backend']['external_reference']
        assert out['model_hash']==semantic_hash(v['model'])
        from fcst_app.discretization import assignment_payload
        from fcst_app.persistence import Package
        mesh=next(e['artifact'] for e in v['model']['entities'] if e['kind']=='mesh')
        package=Package.create(v['model'],[(identity('input-artifact'),'conduction_input',mesh['path'],assignment_payload(v),[])])
        native_manifest=subprocess.run([str(worker),'--contract','manifest3'],input=json.dumps(package.manifest).encode(),capture_output=True,env=env,timeout=30)
        assert native_manifest.returncode==0 and json.loads(native_manifest.stdout)['status']=='passed' and not native_manifest.stderr
        from fcst_cli.discretization import parsers,execute
        parser=argparse.ArgumentParser();parsers(parser.add_subparsers(dest='command'))
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'input.json';destination=Path(directory)/'result.json'
            source.write_text(json.dumps(v),encoding='utf-8')
            result=execute(parser.parse_args(['spatial-solve',str(source),'--worker',str(worker),'--output',str(destination)]))
            assert result['status']=='passed' and json.loads(destination.read_bytes())['model_hash']==semantic_hash(v['model'])
    def tensor_law():
        v=plate(tensor=[[4,0,.5],[0,5,0],[.5,0,6]],rotation=[[0,-1,0],[1,0,0],[0,0,1]])
        material=next(e for e in v['model']['entities'] if e['kind']=='material')
        v['spatial']['tensor_laws']=[dict(material_id=material['id'],frame_id=material['frame_id'],reference_temperature_K=300,
            temperatures_K=[1,5000],tensors_W_per_mK=[[[1.01,0,.5],[0,2.01,0],[.5,0,3.01]],[[51,0,.5],[0,52,0],[.5,0,53]]],
            interpolation='linear',extrapolation='error')]
        out=field(v,lambda p:400+2*p[0]+3*p[1]);matrix={(int(i),int(j)):a for i,j,a in out['jacobian']}
        p=coordinate(v);t=[400+2*p[n['id']][0]+3*p[n['id']][1] for n in nodes(v)]
        for j in range(len(t)):
            plus=t.copy();minus=t.copy();plus[j]+=1e-4;minus[j]-=1e-4
            a=run(dict(thermal_input=v,temperature_K=plus),'--spatial-evaluate')['residual_W']
            b=run(dict(thermal_input=v,temperature_K=minus),'--spatial-evaluate')['residual_W']
            for i in range(len(t)):near((a[i]-b[i])/2e-4,matrix.get((i,j),0),criteria['jacobian_absolute'])
        bad=deepcopy(v);bad['spatial']['tensor_laws'][0]['tensors_W_per_mK'][1][2][2]=-1;reject(bad,{'range'})
        bad=deepcopy(v);bad['spatial']['tensor_laws'][0]['reference_temperature_K']=400;reject(bad,{'spatial_tensor_reference'})
    def spatial_heating():
        v=plate(topology='quad4',thickness=1,specific_heat=3)
        material=next(e for e in v['model']['entities'] if e['kind']=='material')
        v['material_laws']=[dict(material_id=material['id'],specific_heat=dict(temperature=[dict(value=1,unit='K'),dict(value=5000,unit='K')],
            values=[dict(value=.01,unit='J/(kg*K)'),dict(value=50,unit='J/(kg*K)')],interpolation='linear',extrapolation='error',discontinuities=[]))]
        loads(v,lambda n,p:n['capacity']['value'])
        out=run(dict(thermal_input=v,transient=dict(start=0,end=1,output_times=[0,1],maximum_step=.1,include_steps=False)),'--thermal-transient')
        sample=out['samples'][-1]
        for t in sample['temperature_K']:near(t,math.sqrt(90000+600),1e-7)
        near(sum(sample['storage_change_J']),3,1e-7)
    def mixed_storage():
        v=plate(density=1,specific_heat=1);material=next(e for e in v['model']['entities'] if e['kind']=='material')
        other=deepcopy(material);other['id']=identity('other-material');other['density']['value']=2;other['specific_heat']['value']=3
        v['model']['entities'].append(other)
        changed=v['spatial']['cells'][1];element=next(e for e in v['model']['entities'] if e['id']==changed['element_id']);element['material_id']=other['id']
        affected={p['node_id'] for p in v['spatial']['points'] if p['id'] in changed['point_ids']}
        for n in nodes(v):
            if n['id'] in affected:n['capacity']['value']+=5*element['volume']/3
        out=field(v,lambda p:400);near(sum(out['capacity_J_per_K']),.35);near(sum(out['storage_change_J']),35)
    cases=dict(zip(policy['required_cases'],[fd,patches,tensor,jacobian,enthalpy,surface,convection,contacts,reduced,steady_refine,
        spatial_refine,time_refine,reordering,invalid_mesh,invalid_mappings,invalid_materials,invalid_contacts,stale,offline]))
    cases.update({'temperature-tensor-law':tensor_law,'spatial-transient-heating':spatial_heating,'mixed-material-storage':mixed_storage})
    for name,fn in cases.items():
        started=time.monotonic()
        try:fn();status='passed'
        except Exception:
            status='failed';(report.parent/(name+'.log')).write_text(traceback.format_exc(),encoding='utf-8')
        records.append(dict(id=name,status=status,seconds=round(time.monotonic()-started,3)))
    assert inputs==input_hashes(ROOT) and binary==sha256(worker.read_bytes()).hexdigest()
    result=dict(schema_version=1,candidate=candidate,input_sha256=inputs,worker_sha256=binary,
        policy_sha256=sha256(json.dumps(policy,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        execution_mode='fcst_native',full_wp16_qualified=False,metrics=metrics,commands=commands,
        cases=records,gate=evaluate(policy['required_cases'],records))
    report.write_text(json.dumps(result,indent=2)+'\n');assess(result,policy,inputs,candidate)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--worker',type=Path,required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();args.report.parent.mkdir(parents=True,exist_ok=True)
    try:check(args.worker.resolve(),args.report);print('Native spatial acceptance: passed')
    except Exception:
        (args.report.parent/'acceptance-error.log').write_text(traceback.format_exc(),encoding='utf-8');print('Native spatial acceptance: failed');raise SystemExit(1)
