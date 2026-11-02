# SPDX-License-Identifier: MIT OR Apache-2.0
"""Execute the complete configured native inventory in a fresh offline capsule."""
from hashlib import sha256
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import uuid

from profile_support import ROOT
from native_capsule import Capsule
from fcst_app.discretization import plate,seal
from fcst_contracts import canonical
from fcst_tools.verification import check_native_inventory


def inventory(build):
    import cmake
    result=subprocess.run([str(Path(cmake.CMAKE_BIN_DIR)/'ctest.exe'),'--test-dir',str(build.parent),
        '-C',build.name,'--show-only=json-v1'],capture_output=True,timeout=30,check=True)
    value=json.loads(result.stdout)
    check_native_inventory(value,json.loads((ROOT/'ci/thermal-acceptance.json').read_bytes()),
        json.loads((ROOT/'ci/radiation-acceptance-v1.json').read_bytes()),build,ROOT)
    return value['tests']


def check(worker,build,candidate):
    tests=inventory(build);directory=ROOT/'.local/native-offline'/uuid.uuid4().hex
    directory.mkdir(parents=True);(directory/'bin').mkdir()
    sources={Path(t['command'][0]).name:Path(t['command'][0]) for t in tests};sources['fcst-worker.exe']=worker
    hashes={name:sha256(path.read_bytes()).hexdigest() for name,path in sources.items()}
    for name,path in sources.items():shutil.copyfile(path,directory/'bin'/name)
    shutil.copytree(ROOT/'tests/fixtures/thermal',directory/'fixtures')
    outside=directory.parent/('outside-'+uuid.uuid4().hex+'.txt');outside.write_bytes(b'owned access-denial canary')
    denied=[outside,Path(sys.executable),ROOT/'CMakeLists.txt',worker]
    hosts=list((ROOT/'.local/host/Windows/bundle').glob('*/bin/FreeCAD.exe'))
    if len(hosts)>1:raise ValueError('native_offline_host_ambiguous')
    denied+=hosts
    if not all(p.is_file() for p in denied):raise ValueError('native_offline_denial_fixture')
    (directory/'denied.txt').write_text('\n'.join(str(p.resolve()) for p in denied)+'\n',encoding='utf-8',newline='\n')
    (directory/'readable.txt').write_text(str((directory/'denied.txt').resolve())+'\n',encoding='utf-8',newline='\n')
    completed=[]
    with socket.socket() as listener,Capsule(directory) as capsule:
        listener.bind(('localhost',0));listener.listen(8);listener.settimeout(3);port=str(listener.getsockname()[1])
        def reachable():
            with socket.create_connection(listener.getsockname(),timeout=3):
                connection,_=listener.accept();connection.close()
        reachable()
        probe=capsule.run(['fcst-worker.exe','--offline-probe','denied.txt',port])
        reachable()
        proof=json.loads(probe.stdout) if not probe.returncode else {}
        expected=dict(status='passed',app_container=True,capabilities=0,network_denied=True,outside_files_denied=len(denied))
        if (probe.returncode or probe.stderr or proof.get('network_denial') not in ('access_denied','controlled_loopback_timeout')
                or {k:v for k,v in proof.items() if k!='network_denial'}!=expected):raise ValueError('native_offline_isolation',probe.returncode)
        # A readable supposed outside dependency and an uncontained process
        # must both fail the exact same native proof, without publishing paths.
        bad=capsule.run(['fcst-worker.exe','--offline-probe','readable.txt',port])
        parent=subprocess.run([str(worker),'--offline-probe',str(directory/'denied.txt'),port],capture_output=True,timeout=30)
        if bad.returncode==0 or parent.returncode==0:raise ValueError('native_offline_probe_negative')
        for test in tests:
            command=[Path(test['command'][0]).name,*test['command'][1:]]
            if len(command)==3:
                command[2]='fixtures/material-network.json' if command[0]=='fcst-thermal-tests.exe' else 'fixtures'
            result=capsule.run(command,timeout=120)
            if result.returncode or result.stderr:raise ValueError('native_offline_test_failed')
            if test['name']=='native-build-info':
                info=json.loads(result.stdout)
                if info['engine']!='fcst_native' or info['source_revision']!=candidate:raise ValueError('native_offline_identity')
            elif test['name'].startswith('radiation-'):
                if result.stdout.strip()!=b'passed':raise ValueError('native_offline_test_result')
            elif test['name'] in {'thermal-transient-event-refinement','thermal-transient-network-profile','thermal-transient-network-localized'}:
                payload=json.loads(result.stdout)
                if set(payload)!={'status','metrics'} or payload['status']!='passed' or not isinstance(payload['metrics'],dict):
                    raise ValueError('native_offline_test_result')
            elif test['name']!='native-self-test' and json.loads(result.stdout)!={'status':'passed'}:
                raise ValueError('native_offline_test_result')
            completed.append(dict(id=test['name'],status='passed'))
        def run(flag,value):
            result=capsule.run(['fcst-worker.exe',flag],json.dumps(value,allow_nan=False).encode())
            if result.returncode or result.stderr:raise ValueError('native_offline_spatial')
            data=json.loads(result.stdout)
            if data['status']!='passed':raise ValueError('native_offline_spatial')
            return data
        value=plate(2,2,temperature=350)
        position={p['node_id']:p['position'] for p in value['spatial']['points']}
        for n in value['model']['entities']:
            if n['kind']=='node' and position[n['id']][0] in (0,1):
                n.update(classification='prescribed',capacity=dict(value=0,unit='J/K'),
                    temperature=dict(value=300+100*position[n['id']][0],unit='K'))
        result=run('--thermal-steady',seal(value))
        if abs(result['energy_defect_W'])>1e-8 or any(abs(n['temperature_K']-(300+100*position[n['node_id']][0]))>1e-8 for n in result['nodes']):
            raise ValueError('native_offline_spatial_oracle')
        completed.append(dict(id='spatial-steady',status='passed'))
        value=plate(2,2,temperature=350)
        for n in list(value['model']['entities']):
            if n['kind']=='node':value['model']['entities'].append(dict(id=str(uuid.uuid5(uuid.UUID(n['id']),'heating')),
                kind='load',node_id=n['id'],power=dict(value=2*n['capacity']['value'],unit='W')))
        result=run('--thermal-transient',dict(thermal_input=seal(value),transient=dict(start=0,end=.5,output_times=[0,.5],maximum_step=.1,include_steps=False)))
        if any(abs(t-351)>1e-8 for t in result['samples'][-1]['temperature_K']):raise ValueError('native_offline_spatial_oracle')
        completed.append(dict(id='spatial-transient',status='passed'))
    if any(sha256(path.read_bytes()).hexdigest()!=hashes[name] for name,path in sources.items()):raise ValueError('native_offline_sources_changed')
    return dict(kind='windows-appcontainer-v1',execution_mode='fcst_native',app_container=True,capabilities=0,network_denied=True,
        network_denial=proof['network_denial'],network_positive_controls=2,
        outside_files_denied=len(denied),negative_probes=2,binary_sha256=hashes,cases=completed,
        inventory_sha256=sha256(canonical([t['name'] for t in tests])).hexdigest(),
        scope='Clean staged native installation with kernel-denied host/interpreter/source access; complete offline release remains WP-19')
