# SPDX-License-Identifier: MIT OR Apache-2.0
"""Bounded local spatial primitive preparation and native execution."""
import json
import os
from pathlib import Path
import subprocess
from fcst_contracts import loads
from fcst_app.discretization import plate, brick, fd_rod, read_input
from fcst_app.persistence import encode, reject, PersistenceError


def parsers(commands):
    primitive=commands.add_parser('spatial-primitive')
    primitive.add_argument('kind',choices=('plate','brick','fd-rod'))
    primitive.add_argument('--nx',type=int,default=2);primitive.add_argument('--ny',type=int,default=2);primitive.add_argument('--nz',type=int,default=2)
    primitive.add_argument('--topology',choices=('tri3','quad4','tet4','hex8'))
    primitive.add_argument('--output',type=Path,required=True)
    solve=commands.add_parser('spatial-solve')
    solve.add_argument('input',type=Path);solve.add_argument('--worker',type=Path,required=True)
    solve.add_argument('--mode',choices=('steady','transient'),default='steady')
    solve.add_argument('--end',type=float,default=1);solve.add_argument('--samples',type=int,default=11)
    solve.add_argument('--output',type=Path,required=True)


def _execute(args):
    if args.output.exists():reject('output_exists')
    if args.command=='spatial-primitive':
        if args.kind=='plate':value=plate(args.nx,args.ny,topology=args.topology or 'tri3')
        elif args.kind=='brick':value=brick(args.nx,args.ny,args.nz,topology=args.topology or 'tet4')
        else:
            if args.topology:reject('unsupported_element')
            value=fd_rod(args.nx)
        raw=encode(value)
        if len(raw)>1048576:reject('spatial_input_limit')
        with args.output.open('xb') as stream:stream.write(raw)
        return dict(status='prepared',contract_version=value['contract_version'])
    if args.input.stat().st_size>1048576:reject('spatial_input_limit')
    value=loads(args.input.read_bytes())
    if value.get('contract_version')=='2.0.0':value=read_input(value)
    from fcst_host.review import request,DEFAULT_SETTINGS
    options={**DEFAULT_SETTINGS,'mode':args.mode,'end':args.end,'samples':args.samples}
    if value.get('contract_version')=='2.0.0':flag,request_value=request(value['model'],options,thermal_input=value)
    else:
        flag,request_value=request(value['model'],options)
        if args.mode=='steady':request_value=value
        else:request_value['thermal_input']=value
    worker=args.worker.resolve();env={k:v for k,v in os.environ.items() if k.upper() not in {'PYTHONPATH','PYTHONHOME','FREECAD_LIB','SINDAPATH','ESATAN'}}
    env['PATH']=str(worker.parent)
    try:result=subprocess.run([str(worker),flag],input=encode(request_value),capture_output=True,timeout=120,env=env)
    except subprocess.TimeoutExpired:reject('spatial_execution_timeout')
    if len(result.stdout)>16*1024*1024 or result.stderr:reject('spatial_execution_protocol')
    output=loads(result.stdout)
    if result.returncode!=(0 if output.get('status')=='passed' else 1):reject('spatial_execution_protocol')
    with args.output.open('xb') as stream:stream.write(encode(output))
    return dict(status=output['status'],execution_mode='fcst_native')


def execute(args):
    try:return _execute(args)
    except PersistenceError:raise
    except (ValueError,TypeError,KeyError,IndexError):reject('spatial_input_invalid')
