# SPDX-License-Identifier: MIT OR Apache-2.0
import json
from pathlib import Path
from fcst_exchange.sinda import SindaAdapter,SindaUnits


def parsers(commands):
    commands.add_parser('td-probe')
    properties=commands.add_parser('td-write-properties');properties.add_argument('project');properties.add_argument('destination')
    properties_read=commands.add_parser('td-read-properties');properties_read.add_argument('root');properties_read.add_argument('destination')
    properties_import=commands.add_parser('td-import-properties')
    properties_import.add_argument('root');properties_import.add_argument('entry');properties_import.add_argument('destination')
    properties_import.add_argument('--kind',required=True,choices=['tdp','rco']);properties_import.add_argument('--temperature-min',type=float)
    properties_import.add_argument('--temperature-max',type=float);properties_import.add_argument('--name',action='append')
    properties_import.add_argument('--material-frame',help='JSON canonical frame declaring the material property axes')
    material_input = commands.add_parser('td-prepare-materials')
    material_input.add_argument('root')
    material_input.add_argument('entry', help='TDP path relative to root')
    material_input.add_argument('model', help='Canonical model JSON path relative to root')
    material_input.add_argument('bindings', help='Material and node binding JSON path relative to root')
    material_input.add_argument('output', type=Path, help='New native thermal input JSON file')
    drawing_input = commands.add_parser('td-prepare-drawing')
    drawing_input.add_argument('root')
    drawing_input.add_argument('entry', help='DWG path relative to root')
    drawing_input.add_argument('output', type=Path, help='New native thermal input JSON outside the source tree')
    drawing_input.add_argument('--bindings', type=Path, required=True, help='Material policies and validity ranges')
    drawing_input.add_argument('--backend', required=True)
    drawing_input.add_argument('--work', required=True)
    from fcst_exchange.td_material_input import MASS_UNITS, VOLUME_UNITS
    drawing_input.add_argument('--mass-unit', choices=tuple(MASS_UNITS), required=True)
    drawing_input.add_argument('--volume-unit', choices=tuple(VOLUME_UNITS), required=True)
    for field in ('temperature', 'capacity', 'conductance', 'power', 'time'):
        drawing_input.add_argument('--' + field + '-unit', required=True)
    from fcst_exchange.td_geometry_mesh import LENGTH_UNITS
    for name, output in (('td-export-geometry', 'Wavefront OBJ'), ('td-prepare-spatial', 'thermal input JSON')):
        geometry = commands.add_parser(name)
        geometry.add_argument('root')
        geometry.add_argument('entry', help='DWG path relative to root')
        geometry.add_argument('output', type=Path, help=f'New {output} outside the source tree')
        geometry.add_argument('--backend', required=True)
        geometry.add_argument('--work', required=True)
        geometry.add_argument('--length-unit', choices=tuple(LENGTH_UNITS), required=True)
        geometry.add_argument('--handle', action='append', default=[], help='Optional decimal DWG handle')
    geometry.add_argument('--properties', required=True, help='TDP companion path relative to root')
    geometry.add_argument('--temperature', type=float, required=True, help='Initial temperature in kelvin')
    geometry.add_argument('--temperature-min', type=float, required=True, help='Material validity minimum in kelvin')
    geometry.add_argument('--temperature-max', type=float, required=True, help='Material validity maximum in kelvin')
    inventory = commands.add_parser('td-inspect-project')
    inventory.add_argument('root')
    inventory.add_argument('entry', help='DWG path relative to root')
    inventory.add_argument('output', type=Path, help='New local project inventory outside the source tree')
    inventory.add_argument('--backend', required=True)
    inventory.add_argument('--work', required=True)
    mesh_states = commands.add_parser('td-compare-mesh-states')
    mesh_states.add_argument('before_root')
    mesh_states.add_argument('before_entry')
    mesh_states.add_argument('after_root')
    mesh_states.add_argument('after_entry')
    mesh_states.add_argument('output', type=Path)
    mesh_states.add_argument('--before-handle', required=True)
    mesh_states.add_argument('--after-handle', required=True)
    mesh_states.add_argument('--expect', choices=('initial', 'changed', 'unchanged', 'retagged'),
                             help='Require the expected stored-mesh transition before saving the report')
    mesh_states.add_argument('--backend', required=True)
    mesh_states.add_argument('--work', required=True)
    sync = commands.add_parser('td-sync-cad-mesh', help='Transfer an accepted FCST CAD setup to a regenerated mesh')
    sync.add_argument('project', type=Path, help='Previous prepared FCST CAD project')
    sync.add_argument('mesh', type=Path, help='New pinned FreeCAD/Gmsh CAD mesh JSON')
    sync.add_argument('brep', type=Path, help='BREP corresponding to the new mesh')
    sync.add_argument('output', type=Path, help='New portable FCST project')
    sync.add_argument('--mapping', type=Path, help='JSON with region_map and face_map for changed topology')
    for name in ('td-prepare-transient', 'sinda-prepare-transient'):
        transient = commands.add_parser(name)
        transient.add_argument('root')
        transient.add_argument('entry', help='Source path relative to root')
        transient.add_argument('output', type=Path, help='New native worker request outside the source tree')
        transient.add_argument('--end', type=float, required=True, help='Run horizon in seconds from zero')
        transient.add_argument('--samples', type=int, default=11)
        if name.startswith('td-'):
            transient.add_argument('--backend', required=True)
            transient.add_argument('--work', required=True)
        for field in ('temperature', 'capacity', 'conductance', 'power', 'time'):
            transient.add_argument('--' + field + '-unit', required=True)
    for command in ('td-read-property-laws','td-write-property-laws'):
        laws=commands.add_parser(command);laws.add_argument('root');laws.add_argument('entry');laws.add_argument('destination')
        if command=='td-read-property-laws':laws.add_argument('--kind',required=True,choices=['tdp','rco'])
    property_export=commands.add_parser('td-export-property-source');property_export.add_argument('project');property_export.add_argument('destination')
    td_writer=commands.add_parser('td-write-model')
    td_writer.add_argument('project');td_writer.add_argument('destination')
    td_writer.add_argument('--backend',required=True);td_writer.add_argument('--work',required=True)
    native_export=commands.add_parser('td-export-native')
    native_export.add_argument('project');native_export.add_argument('destination')
    native_export.add_argument('--backend',required=True);native_export.add_argument('--work',required=True)
    writer=commands.add_parser('sinda-write-model')
    writer.add_argument('project');writer.add_argument('destination')
    for field in ('temperature','capacity','conductance','power','time'):
        writer.add_argument('--'+field+'-unit',required=True)
    for name in ('td-preview','td-export-source','td-audit-rewrite','td-package'):
        parser=commands.add_parser(name);parser.add_argument('root');parser.add_argument('entry')
        parser.add_argument('--backend',required=True);parser.add_argument('--work',required=True)
        if name!='td-preview':parser.add_argument('destination')
        if name=='td-export-source':parser.add_argument('--edits')
        for field in ('temperature','capacity','conductance','power','time'):
            parser.add_argument('--'+field+'-unit',required=name=='td-package')
    for name in ('sinda-preview','sinda-export','sinda-package','sinda-result'):
        parser=commands.add_parser(name);parser.add_argument('root');parser.add_argument('entry')
        parser.add_argument('--temperature-unit',required=True);parser.add_argument('--capacity-unit',required=True)
        parser.add_argument('--conductance-unit',required=True);parser.add_argument('--power-unit',required=True);parser.add_argument('--time-unit',required=True)
        if name in {'sinda-export','sinda-package'}:parser.add_argument('destination')
        if name=='sinda-result':parser.add_argument('result');parser.add_argument('time',type=float)


def _read_material_source(path):
    from fcst_exchange.core import Limits, reject

    limit = Limits().file_bytes
    with path.open('rb') as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        reject('td_material_input_limit')
    return content


def _write_new_output(output, raw):
    import os
    from tempfile import NamedTemporaryFile

    from fcst_exchange.core import reject
    from fcst_exchange.export import rename_new

    stream = NamedTemporaryFile(dir=output.parent, prefix='.fcst-material-', delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            if os.name == 'nt':
                rename_new(temporary, output)
            else:
                os.link(temporary, output)
        except FileExistsError:
            reject('td_output_exists')
    finally:
        temporary.unlink(missing_ok=True)


def _write_material_input(operation, result, output):
    from fcst_app.persistence import encode
    from fcst_exchange.core import Limits, reject

    raw = encode(result)
    if len(raw) > Limits().file_bytes:
        reject('td_material_input_limit')
    _write_new_output(output, raw)
    return {'operation': operation, 'status': 'prepared', 'material_laws': len(result['material_laws']),
            'node_storage_bindings': len(result['node_storage']), 'vendor_runtime_required': False,
            'qualified': False}


def _write_transient_request(args, request):
    from fcst_app.persistence import encode
    from fcst_exchange.core import Limits, reject

    raw = encode(request)
    if len(raw) > Limits().file_bytes:
        reject('time_load_input_limit')
    _write_new_output(args.output, raw)
    return {'operation': args.command, 'status': 'prepared', 'time_loads': len(request['time_loads']),
            'vendor_runtime_required': False, 'qualified': False}


def _sync_cad_mesh(args):
    from fcst_app.cad_mesh import synchronize_project
    from fcst_app.persistence import Limits, Package
    from fcst_contracts import MAX_BYTES, loads
    from fcst_exchange.core import reject

    def bounded(path, limit):
        with path.open('rb') as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            reject('td_cad_sync_input_limit')
        return raw

    if args.output.exists() or args.output.is_symlink():
        reject('td_output_exists')
    if any(args.output.resolve().is_relative_to(path.resolve())
           for path in (args.project, args.mesh, args.brep, args.mapping) if path is not None):
        reject('td_cad_sync_output_overlap')
    saved = Package.open(args.project)
    source = loads(bounded(args.mesh, MAX_BYTES))
    brep = bounded(args.brep, Limits().item_bytes)
    mapping = loads(bounded(args.mapping, MAX_BYTES)) if args.mapping else {}
    if not isinstance(mapping, dict) or set(mapping) != ({'region_map', 'face_map'} if args.mapping else set()):
        reject('td_cad_sync_mapping')
    prepared, report = synchronize_project(saved, source, brep, **mapping)
    _write_new_output(args.output, prepared.zip_bytes())
    return {'operation': args.command, **report, 'vendor_runtime_required': False, 'qualified': False}


def execute(args):
    if args.command == 'td-sync-cad-mesh':
        return _sync_cad_mesh(args)
    if args.command in {'td-prepare-transient', 'sinda-prepare-transient'}:
        from fcst_exchange.core import reject

        if args.output.resolve().is_relative_to(Path(args.root).resolve()):
            reject('time_load_output_overlap')
        units = SindaUnits(*(getattr(args, name + '_unit')
                             for name in ('temperature', 'capacity', 'conductance', 'power', 'time')))
        if args.command == 'td-prepare-transient':
            from fcst_exchange.dwg_native import NativeRuntime
            from fcst_exchange.independent_td import IndependentTdAdapter
            from fcst_exchange.time_loads import prepare_drawing_transient

            adapter = IndependentTdAdapter(NativeRuntime.from_receipt(args.backend), units)
            staged = adapter.preview(args.root, args.entry, args.work)
            request = prepare_drawing_transient(staged, end=args.end, samples=args.samples)
        else:
            request = SindaAdapter(units).prepare_transient(args.root, args.entry, end=args.end, samples=args.samples)
        return _write_transient_request(args, request)
    if args.command=='td-probe':
        from fcst_exchange.opentd import discover_runtime
        return discover_runtime().probe()
    if args.command == 'td-prepare-materials':
        from fcst_contracts import loads
        from fcst_exchange.td_material_input import prepare_material_input
        from fcst_exchange.vendor_paths import checked_path

        source, model, bindings = (_read_material_source(checked_path(args.root, name))
                                   for name in (args.entry, args.model, args.bindings))
        result = prepare_material_input(source, loads(model), loads(bindings))
        return _write_material_input(args.command, result, args.output)
    if args.command in {'td-read-property-laws','td-write-property-laws'}:
        from fcst_exchange.td_property_laws import read_laws,export_laws
        from fcst_exchange.vendor_paths import checked_path
        from fcst_exchange.core import reject
        from fcst_contracts import loads
        with checked_path(Path(args.root),args.entry).open('rb') as stream:raw=stream.read(1048577)
        if len(raw)>1048576:reject('td_property_library_limit')
        if args.command=='td-read-property-laws':
            library=read_laws(raw,args.kind)
        else:
            library=loads(raw)
        # The result contains local engineering data. Console reports are counts
        # only, following the same separation as native DWG/property workflows.
        return {'operation':args.command,**export_laws(library,args.destination,json_output=args.command=='td-read-property-laws')}
    if args.command=='td-write-properties':
        from fcst_app.persistence import recover_package
        from fcst_exchange.td_property_model import export_library
        return export_library(recover_package(args.project).model,args.destination)
    if args.command=='td-export-property-source':
        from fcst_app.persistence import recover_package
        from fcst_exchange.td_property_model import export_document_package
        return export_document_package(recover_package(args.project),args.destination)
    if args.command=='td-import-properties':
        from fcst_app.persistence import Package,encode,save_package
        from fcst_exchange.td_property_model import import_document
        from fcst_exchange.vendor_paths import checked_path
        from fcst_exchange.core import target_id,reject
        from hashlib import sha256
        if Path(args.destination).exists():reject('package_requires_new_target')
        with checked_path(Path(args.root),args.entry).open('rb') as stream:raw=stream.read(1048577)
        if len(raw)>1048576:reject('td_property_library_limit')
        if args.kind=='rco' and (args.temperature_min is not None or args.temperature_max is not None):reject('td_property_optics_temperature_interval_unmapped')
        bounds=[args.temperature_min,args.temperature_max] if args.kind=='tdp' else None
        from fcst_contracts import loads
        frame=None
        if args.material_frame:
            with Path(args.material_frame).open('rb') as stream:frame=loads(stream.read(1048577))
        model,report=import_document(raw,args.kind,bounds,names=args.name,material_frame=frame)
        source='source/'+sha256(args.entry.encode()).hexdigest()+'.original';files={'model.json':encode(model),source:raw,
            'exchange/property-source-map.json':encode({'profile':'td-property-document/1','source_paths':{args.entry:source},'report':report,
                'entries':[e['label'] for e in model['entities'] if e['kind']!='frame'],
                'material_frames':[e for e in model['entities'] if e['kind']=='frame']})}
        model_id=target_id(('property-document-model',model['project_id']));source_id=target_id(('property-document-original',args.entry));records=[]
        for name,data in files.items():
            records.append({'id':model_id if name=='model.json' else source_id if name==source else target_id(('property-document-evidence',name)),
                'role':'model' if name=='model.json' else 'source_original' if name==source else 'evidence',
                'artifact':{'path':name,'sha256':sha256(data).hexdigest(),'byte_length':len(data)},'dependencies':[source_id] if name=='model.json' else []})
        save_package(Package({'contract_version':'2.0.0','minimum_reader':'2.0.0','project_id':model['project_id'],'revision':0,'model_artifact_id':model_id,'artifacts':records},files),args.destination)
        return {'operation':'td-import-properties','status':'saved',**report}
    if args.command=='td-read-properties':
        from fcst_app.persistence import Package,encode,save_package
        from fcst_exchange.td_property_model import read_library
        from fcst_exchange.core import target_id,reject
        from hashlib import sha256
        if Path(args.destination).exists():reject('package_requires_new_target')
        model,originals=read_library(args.root);files={'model.json':encode(model)};records=[];source_ids=[];aliases={}
        for name,raw in originals.items():
            alias='source/'+sha256(name.encode()).hexdigest()+'.original';identifier=target_id(('property-original',name));source_ids.append(identifier);files[alias]=raw
            aliases[name]=alias
            records.append({'id':identifier,'role':'source_original','artifact':{'path':alias,'sha256':sha256(raw).hexdigest(),'byte_length':len(raw)},'dependencies':[]})
        map_name='exchange/property-source-map.json';files[map_name]=encode({'profile':'td-property-library/1','source_paths':aliases})
        records.append({'id':target_id(('property-evidence','source-map')),'role':'evidence',
                        'artifact':{'path':map_name,'sha256':sha256(files[map_name]).hexdigest(),'byte_length':len(files[map_name])},'dependencies':source_ids})
        identifier=target_id(('property-model',model['project_id']))
        records.append({'id':identifier,'role':'model','artifact':{'path':'model.json','sha256':sha256(files['model.json']).hexdigest(),'byte_length':len(files['model.json'])},'dependencies':source_ids})
        package=Package({'contract_version':'2.0.0','minimum_reader':'2.0.0','project_id':model['project_id'],'revision':model['revision'],'model_artifact_id':identifier,'artifacts':records},files)
        save_package(package,args.destination)
        return {'operation':'td-read-properties','status':'saved','entities':len(model['entities']),'vendor_runtime_required':False,'qualified':False}
    if args.command.startswith('td-'):
        from fcst_exchange.dwg_native import NativeRuntime
        from fcst_exchange.independent_td import IndependentTdAdapter
        runtime=NativeRuntime.from_receipt(args.backend)
        if args.command == 'td-compare-mesh-states':
            from fcst_app.persistence import encode
            from fcst_exchange.core import reject
            from fcst_exchange.independent_td import source_edit_handle
            from fcst_exchange.td_mesher import compare_mesh_states

            roots = (Path(args.before_root).absolute(), Path(args.after_root).absolute())
            work = Path(args.work).absolute()
            if not work.name:
                reject('td_mesh_state_output_overlap')
            workdirs = (work, work.with_name(work.name + '-after'))
            if any(path.resolve().is_relative_to(root.resolve()) for path in (args.output, *workdirs) for root in roots):
                reject('td_mesh_state_output_overlap')
            if args.output.exists() or args.output.is_symlink():
                reject('td_output_exists')
            handles = (source_edit_handle(args.before_handle), source_edit_handle(args.after_handle))
            adapter = IndependentTdAdapter(runtime)
            before = adapter.preview(roots[0], args.before_entry, workdirs[0])
            after = adapter.preview(roots[1], args.after_entry, workdirs[1])
            report = compare_mesh_states(before, after, *handles)
            if args.expect:
                was_meshed = report['before']['elements'] > 0
                is_meshed = report['after']['elements'] > 0
                changed = report['mesh_changed']
                stable_mesh = was_meshed and is_meshed and not changed and not report['source_node_assignments_changed']
                observed = {
                    'initial': not was_meshed and is_meshed,
                    'changed': was_meshed and is_meshed and changed,
                    'unchanged': stable_mesh and not report['mesh_groups_changed'],
                    'retagged': stable_mesh and report['mesh_groups_changed'],
                }
                if not observed[args.expect]:
                    reject('td_mesh_state_expectation')
                report['expected_transition'] = args.expect
            _write_new_output(args.output, encode(report))
            return {'operation': args.command, 'status': 'compared', **report}
        if args.command == 'td-inspect-project':
            from fcst_app.persistence import encode
            from fcst_exchange.core import Limits, reject
            from fcst_exchange.td_project_inventory import inspect_project

            if args.output.resolve().is_relative_to(Path(args.root).resolve()):
                reject('td_project_output_overlap')
            if args.output.exists() or args.output.is_symlink():
                reject('td_output_exists')
            staged = IndependentTdAdapter(runtime).preview(args.root, args.entry, args.work)
            inventory = inspect_project(staged)
            raw = encode(inventory)
            if len(raw) > Limits().total_bytes:
                reject('td_project_inventory_limit')
            _write_new_output(args.output, raw)
            return {'operation': args.command, 'status': 'inspected',
                    'configuration_records': len(inventory['configuration']),
                    'dictionary_entries': len(inventory['dictionary_graph']['entries']),
                    'status_counts': inventory['status_counts'],
                    'vendor_runtime_required': False, 'native_ready': False, 'qualified': False}
        if args.command=='td-write-model':
            from fcst_app.persistence import recover_package
            from fcst_exchange.td_writer import export_model
            return export_model(recover_package(args.project).model,runtime,args.destination,args.work)
        if args.command=='td-export-native':
            from fcst_app.persistence import recover_package
            from fcst_exchange.source_package import export_td_package
            return export_td_package(recover_package(args.project),runtime,args.destination,args.work)
        if args.command in {'td-export-geometry', 'td-prepare-spatial'}:
            from fcst_exchange.core import Limits, reject
            from fcst_exchange.independent_td import source_edit_handle

            if args.output.resolve().is_relative_to(Path(args.root).resolve()):
                reject('td_geometry_output_overlap')
            handles = [source_edit_handle(value) for value in args.handle]
            staged = IndependentTdAdapter(runtime).preview(args.root, args.entry, args.work)
            if args.command == 'td-export-geometry':
                from fcst_exchange.td_geometry_mesh import render_geometry
                raw, report = render_geometry(staged, args.length_unit, handles)
                status = 'exported'
            else:
                from fcst_app.persistence import encode
                from fcst_exchange.td_spatial import prepare_spatial
                result, report = prepare_spatial(staged, args.properties, args.length_unit, handles=handles,
                    temperature=args.temperature, temperature_range=(args.temperature_min, args.temperature_max))
                raw = encode(result)
                if len(raw) > Limits().file_bytes:
                    reject('td_spatial_input_limit')
                status = 'prepared'
            _write_new_output(args.output, raw)
            return {'operation': args.command, 'status': status, **report}
        unit_values=[getattr(args,field+'_unit') for field in ('temperature','capacity','conductance','power','time')]
        if any(unit_values) and not all(unit_values):
            from fcst_exchange.core import reject
            reject('td_native_all_units_required')
        units=SindaUnits(*unit_values) if all(unit_values) else None
        adapter=IndependentTdAdapter(runtime,units)
        if args.command=='td-prepare-drawing':
            from fcst_contracts import loads
            from fcst_exchange.core import reject
            from fcst_exchange.td_material_input import prepare_drawing_material_input
            if args.output.resolve().is_relative_to(Path(args.root).resolve()):
                reject('td_material_drawing_output_overlap')
            bindings = loads(_read_material_source(args.bindings))
            staged = adapter.preview(args.root, args.entry, args.work)
            result = prepare_drawing_material_input(staged, bindings, mass_unit=args.mass_unit, volume_unit=args.volume_unit)
            return _write_material_input(args.command, result, args.output)
        staged=adapter.preview(args.root,args.entry,args.work)
        if args.command=='td-preview':return staged.report
        if args.command=='td-package':
            from fcst_app.persistence import save_package
            from fcst_exchange.source_package import package_td
            from fcst_exchange.core import reject
            if Path(args.destination).exists():reject('package_requires_new_target')
            save_package(package_td(staged),args.destination)
            return {'operation':'td-package','status':'saved','source_revision':staged.original.source_hash,'native_ready':True,'qualified':False}
        if args.command=='td-export-source':
            edits=()
            if args.edits:
                from fcst_contracts import loads
                from fcst_exchange.core import reject
                with Path(args.edits).open('rb') as stream:raw=stream.read(1048577)
                if len(raw)>1048576:reject('td_source_edit_file_limit')
                edits=loads(raw)
            return adapter.export_source(staged,args.destination,edits,work=Path(args.work).with_name(Path(args.work).name+'-export'))
        return adapter.audit_rewrite(staged,args.destination)
    units=SindaUnits(args.temperature_unit,args.capacity_unit,args.conductance_unit,args.power_unit,args.time_unit)
    if args.command=='sinda-write-model':
        from fcst_app.persistence import recover_package
        from fcst_exchange.sinda_writer import export_model
        return export_model(recover_package(args.project).model,units,args.destination)
    adapter=SindaAdapter(units);staged=adapter.preview(args.root,args.entry)
    if args.command=='sinda-preview':return staged.report
    if args.command=='sinda-export':return adapter.export(staged,args.destination)
    if args.command=='sinda-package':
        from fcst_exchange.source_package import package_sinda
        from fcst_app.persistence import save_package
        from fcst_exchange.core import reject
        if Path(args.destination).exists():reject('package_requires_new_target')
        package=package_sinda(staged);save_package(package,args.destination)
        return {'operation':'sinda-package','status':'saved','source_revision':staged.report['source_revision']}
    from fcst_exchange.sinda_results import read_print
    from fcst_exchange.results import query
    from fcst_exchange.vendor_paths import checked_path
    from fcst_exchange.core import reject
    with checked_path(Path(args.root),args.result).open('rb') as stream:raw=stream.read(16777217)
    if len(raw)>16777216:reject('sinda_result_limit')
    result=read_print(raw,staged.require_native(),quantity='temperature',unit=units.temperature,time_unit=units.time)
    return query(result,args.time)
