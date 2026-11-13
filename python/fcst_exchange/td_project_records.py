# SPDX-License-Identifier: MIT OR Apache-2.0
"""Verified project-object wire profiles for the AC1032 TD drawing reader."""
from .core import ExchangeError, reject
from .td_filer import Filer
from .td_project_graph import field, reference_target


# The class identifier, DXF name, object kind and payload version all matter.
# AutoCAD's AC1032 container marker does not select a TD object layout.
PROJECT_CLASSES = {
    'CaseSetManager': ('RCCASESET', 11, 'cases'),
    'RcDbSymbolManager': ('RCDBSYMBOLMANAGER', 7, 'symbols'),
    'RcDbLogicManager': ('RCLOGIC', 4, 'logic'),
    'RcOrbit': ('RCORBIT', 35, 'orbit'),
    'RcOrbitUnits': ('RCORBITUNITS', 7, 'orbit-units'),
    'SubmodelCommentsManager': ('RCSUBMODELCOMMENTSMANAGER', 1, 'submodel-comments'),
    'AtacControlData': ('ATACCONTROLDATA', 3, 'analysis-control'),
    'RcGraphicsSettings': ('RCGRAPHICSSETTING', 6, 'graphics-settings'),
    'TdViewportData': ('RCTD_VIEWPORT_DATA', 1, 'viewport-data'),
}


def object_handles(filer, standard):
    owner = filer.row['handle']
    values = [('owner', field(standard, 'ownerhandle'))]
    values.extend(('reactor', v) for v in field(standard, 'reactors', []))
    if not field(standard, 'is_xdic_missing', 0):
        values.append(('extension-dictionary', field(standard, 'xdicobjhandle')))
    result = []
    for role, value in values:
        expected = reference_target(value, owner)
        if filer.handle()['target'] != expected:
            reject('td_project_common_handle_mismatch')
        result.append({'role': role, 'target': str(expected)})
    return result


def _pairs(filer):
    # Preserve source order rather than normalizing repeated map entries.
    return tuple((filer.text(), filer.text()) for _ in range(filer.count()))


def _read_fields(filer, layout):
    # Preserve the wire order of settings whose physical meaning is unverified.
    b = filer.data
    readers = {'i': b.bl, 'd': b.bd, 't': filer.text, 's': filer.texts, 'l': filer.integers,
               'v': filer.doubles, 'e': filer.expression, 'f': lambda: bool(b.take(1))}
    return tuple(readers[kind]() for kind in layout)


def _radiation_parameter_set(filer):
    filer.version(5)
    b = filer.data
    return {'value': b.bd(), 'selectors': tuple(b.bl() for _ in range(3)),
            'additional_value': b.bd(), 'additional_selectors': (b.bl(), b.bl()),
            'names': filer.texts(), 'indices': filer.integers(),
            'expressions': tuple(filer.expression() for _ in range(4)),
            'final_selectors': tuple(b.bl() for _ in range(3)),
            'wide_values': tuple(str(int.from_bytes(b.raw(b.take(3)), 'little')) for _ in range(2))}


def _radiation_task(filer):
    filer.version(36)
    b = filer.data
    def read(layout):
        return _read_fields(filer, layout)

    settings = {'payload_version': 36, 'analysis_group': filer.text(), 'orbit': filer.text(),
                'calculation_type': b.bl(), 'method': b.bl(),
                'sampling_settings': read('idiiiiidddd'),
                'radk_output': filer.text(), 'radk_submodel': filer.text(),
                'space_node_settings': read('itdi'),
                'heating_output': filer.text(), 'heating_submodel': filer.text(),
                'heating_settings': read('iiiii'), 'form_factor_output': filer.text(),
                'form_factor_settings': read('iiiiiisliiidiiiidtvvitititddiiidtiiv')}
    settings['parameter_sets'] = tuple(_radiation_parameter_set(filer) for _ in range(filer.count()))
    settings['additional_settings'] = read('di')
    settings['object_references'] = tuple(str(filer.handle()['target']) for _ in range(filer.count()))
    settings['output_settings'] = read('iiidddttidddtti')
    settings['expressions'] = read('e' * 20)
    settings['final_settings'] = read('iddiveeeiidddeitdeiiitivvideiiiiii')
    return settings


def _case_manager_trailer(filer):
    b = filer.data
    fields = {'case_indices': filer.integers(), 'flags': (bool(b.take(1)), bool(b.take(1))),
              'selectors': (b.bl(), b.bl())}
    filer.version(1)
    fields['batch_control'] = {'mode': b.bl(), 'text': tuple(filer.text() for _ in range(6)),
                               'flags': tuple(bool(b.take(1)) for _ in range(6))}
    return fields


def _case_cyclic_settings(filer):
    # Case payload v73 embeds the older cyclic settings alongside its current
    # controls. Their wire shape is needed to reach the current INSERT list.
    filer.version(9)
    filer.version(4)
    controls = _read_fields(filer, 'i' * 6 + 'de' * 4 + 'vvii' + 'de' * 5 + 'vii' + 'de' * 4 + 'ie')
    filer.version(1)
    selectors = _read_fields(filer, 'i' * 16)
    values = _read_fields(filer, 'tttttitdede')
    filer.version(5)
    label = filer.text()
    tables = tuple(filer.doubles() for _ in range(filer.count()))
    output_settings = _read_fields(filer, 'tieieiiiiii')
    filer.version(1)
    output_rows = []
    for _ in range(filer.count()):
        filer.version(3)
        output_rows.append(_read_fields(filer, 'tiffdi' + 'f' * 155))
    return {'controls': controls, 'selectors': selectors, 'values': values, 'label': label,
            'tables': tables, 'output_settings': output_settings, 'output_rows': output_rows}


def _case_source_sections(filer, case):
    for role, width in (('thermal', 9), ('fluid', 8)):
        count = filer.count()
        case[f'{role}_logic_count'] = count
        blocks = []
        for _ in range(count):
            submodel = filer.text()
            filer.version(1)
            blocks.append({'submodel': submodel, 'sections': _read_fields(filer, 't' * width)})
        case[f'{role}_logic'] = blocks
    case['source_sections'] = {key: filer.text() for key in ('operations', 'subroutine', 'other')}
    case['solver_procedures'] = _read_fields(filer, 't' * 5)
    case['reliability_settings'] = _read_fields(filer, 't' * 4)


def _case_controls(filer, case):
    b = filer.data
    filer.version(6)
    case['solver_controls'] = _read_fields(filer, 'dt' + 'd' * 10 + 'i' * 8 + 'ddddii' + 'e' * 21 + 'ie')
    case['symbol_overrides'] = {'names': filer.texts(), 'values': filer.texts()}
    filer.version(5)
    case['sinda_options'] = _read_fields(filer, 't' * 6 + 'i' * 9 + 'ttt')
    case['sinda_option_selectors'] = _read_fields(filer, 'i' * 7)
    filer.version(15)
    case['sinda_controls'] = _read_fields(filer, 'ddidddddddddiddiiddddddiidddddiddiidddti'
                                         'eeeedeeeeddeief' + 'e' * 29 + 'dedededetttfff')
    case['symbol_comments'] = filer.texts()
    case['dynamic_sinda'] = {'selectors': _read_fields(filer, 'iii'), 'text': filer.text()}

    for key, version, layout in (('register_variables', 2, 'tttiii'), ('solver_design', 2, 'ttttiiiee')):
        rows = case[key] = []
        for _ in range(filer.count()):
            filer.version(version)
            rows.append(_read_fields(filer, layout))
    case['solver_constraint_count'] = filer.count()
    if case['solver_constraint_count']:
        return 'td_case_solver_constraints_unmapped'

    case['analysis_selector'] = b.bl()
    case['build_selector'] = b.bl()
    case['run_selector'] = b.bl()
    case['postprocess_selectors'] = _read_fields(filer, 'ii')
    case['conductance_capacity_output'] = filer.text()
    case['output_submodel'] = {'name': filer.text(), 'selector': b.bl()}
    case['excluded_thermal_submodels'] = filer.texts()
    case['excluded_fluid_submodels'] = filer.texts()
    case['generate_conductance_capacity'] = b.bl()
    case['generate_log'] = b.bl()
    case['log_output'] = filer.text()
    case['run_directory'] = {'selector': b.bl(), 'path': filer.text()}
    case['initial_temperature_file'] = filer.text()
    case['additional_solver_settings'] = _read_fields(filer, 'is' + 'i' * 6 + 'tt' + 'iitdddeee' + 'i' * 14)
    case['cyclic_settings'] = _case_cyclic_settings(filer)
    case['legacy_output_settings'] = _read_fields(filer, 'tit' + 'i' * 8)
    filer.version(1)
    case['insert_files'] = filer.texts()
    case['additional_source_settings'] = _read_fields(filer, 'i')
    case['lump_initialization'] = {'selectors': _read_fields(filer, 'ii'), 'path': filer.text(),
                                   'lumps': filer.texts()}
    case['additional_output_settings'] = _read_fields(filer, 'iiits' + 'i' * 7 + 'tttiiittss')
    case['restart'].update({'file_selector': b.bl(), 'path': filer.text(),
                            'case_time_pointer': b.bl(), 'record_number': b.bl()})
    return 'td_case_settings_unmapped'


def _cases(filer):
    b = filer.data
    options = (b.bl(), b.bl())
    count = filer.count()
    fields = {'manager_options': options, 'case_count': count, 'cases': []}
    references = []
    if not count:
        fields['controls'] = _case_manager_trailer(filer)
        return fields, references, None

    filer.version(73)
    case = {'payload_version': 73, 'name': filer.text(), 'legacy_id': b.bl(),
            'steady': b.bl(), 'transient': b.bl(), 'sinda_output': filer.text(),
            'output_selectors': tuple(b.bl() for _ in range(8)),
            'legacy_analysis_count': b.bl(), 'radiation_task_count': filer.count()}
    if case['steady'] not in (0, 1) or case['transient'] not in (0, 1):
        reject('td_case_solution_selector')
    fields['cases'].append(case)
    case['radiation_tasks'] = tuple(_radiation_task(filer) for _ in range(case['radiation_task_count']))
    selectors = (b.bl(), b.bl())
    property_roles = (('optical', 'optical-library'), ('thermophysical', 'thermophysical-library'))
    for (key, role), selector in zip(property_roles, selectors):
        path = filer.text()
        case[f'{key}_override'] = {'selector': selector, 'path': path}
        if selector == 1:
            references.append({'case_index': 0, 'role': role, 'path': path})
    if any(selector not in (0, 1) for selector in selectors):
        return fields, references, 'td_case_property_override_mode_unmapped'
    for key in ('optical_aliases', 'optical_properties', 'thermophysical_aliases', 'thermophysical_properties'):
        case[key] = filer.texts()
    case['restart'] = {'selector': b.bl(), 'time_pointer': b.bl()}
    _case_source_sections(filer, case)
    streams = (filer.data, filer.strings, filer.handles)
    positions = tuple(stream.position for stream in streams)
    controls = {'restart': dict(case['restart'])}
    try:
        limitation = _case_controls(filer, controls)
    except ExchangeError as error:
        if error.code != 'td_filer_version':
            raise
        for stream, position in zip(streams, positions):
            stream.position = position
        return fields, references, 'td_case_nested_version_unmapped'
    case.update(controls)
    if case['restart']['selector'] == 1 and 'path' in case['restart']:
        references.append({'case_index': 0, 'role': 'sinda-restart', 'path': case['restart']['path'],
                           'run_directory_selector': case['run_directory']['selector']})
    for path in case.get('insert_files', ()):
        references.append({'case_index': 0, 'role': 'sinda-include', 'path': path,
                           'run_directory_selector': case['run_directory']['selector']})
    if case['restart']['selector'] not in (0, 1):
        return fields, references, 'td_case_restart_mode_unmapped'
    return fields, references, limitation


def _symbols(filer):
    fields = {'text_maps': tuple(_pairs(filer) for _ in range(4))}
    count = filer.count()
    fields['definition_count'] = count
    definitions = []
    for _ in range(count):
        name = filer.text()
        filer.version(4)
        definitions.append({'name': name, 'selectors': tuple(filer.data.bl() for _ in range(6))})
    fields['attributes'] = definitions
    return fields, [], None


def _logic(filer):
    count = filer.count()
    if count:
        return {'logic_count': count}, [], 'td_logic_objects_unmapped'
    return {'logic_count': 0, 'manager_selectors': tuple(filer.data.bl() for _ in range(3))}, [], None


def _orbit(filer):
    b = filer.data
    def integers(count):
        return tuple(b.bl() for _ in range(count))

    def doubles(count):
        return tuple(b.bd() for _ in range(count))

    def vectors(count):
        return tuple(filer.doubles() for _ in range(count))

    def expressions(count):
        return tuple(filer.expression() for _ in range(count))

    def points():
        return tuple(b.point() for _ in range(filer.count()))

    fields = {
        'base_selector': b.bl(), 'base_short': b.bs(), 'base_values': doubles(9),
        'inclination': b.bd(), 'inclination_settings': doubles(4),
        'minimum_altitude': b.bd(), 'maximum_altitude': b.bd(), 'eccentricity': b.bd(), 'period': b.bd(),
        'shape_selectors': integers(2), 'sampling_selector': b.bl(),
    }
    last_index = b.bl()
    if not -1 <= last_index < 10000:
        reject('td_orbit_legacy_samples_limit')
    fields.update({'sampling_values': doubles(2), 'sampling_mode': b.bl(),
                   'sampling_parameters': doubles(2), 'legacy_samples': doubles(last_index + 1),
                   'environment_selector': b.bl(), 'environment_values': doubles(2),
                   'additional_rotations': doubles(3), 'additional_rotation_axes': integers(3),
                   'trajectory_selectors': integers(2), 'trajectory_values': doubles(3),
                   'orbit_type': b.bl()})
    if fields['orbit_type'] not in range(5):
        reject('td_orbit_type')
    fields.update({'times': filer.doubles(), 'sun_vectors': points(), 'planet_vectors': points(),
                   'orbital_radii': filer.doubles(), 'vector_selectors': integers(6),
                   'vector_tables': vectors(5), 'vector_indices': filer.integers(),
                   'vector_mode': b.bl(), 'additional_tables': vectors(3), 'orientation_value': b.bd(),
                   'orientation_selectors': integers(2), 'orientation_tables': vectors(2),
                   'parameter_expressions': expressions(21)})
    fields.update({'vary_planet': b.bl(), 'planet_table': filer.doubles(), 'planet_expression': filer.expression(),
                   'dark_sun_selector': b.bl(), 'dark_sun_tables': vectors(3),
                   'additional_vectors': points(), 'additional_vector_table': filer.doubles(),
                   'trajectory_text': filer.text(), 'trajectory_tables': vectors(3)})
    for side in ('a', 'b'):
        fields[f'heating_group_{side}'] = {'mode': b.bl(), 'value': b.bd(), 'expression': filer.expression(),
                                          'selector': b.bl(), 'tables': vectors(2)}
    fields.update({'additional_environment_mode': b.bl(), 'additional_environment_value': b.bd(),
                   'environment_mode': b.bl(), 'environment_parameters': tuple(
                       {'value': b.bd(), 'expression': filer.expression()} for _ in range(3)),
                   'vector_expressions': expressions(6), 'environment_selectors': integers(4),
                   'environment_scalars': doubles(2), 'environment_expressions': expressions(2),
                   'environment_flag': bool(b.take(1)), 'final_selectors': integers(3),
                   'final_tables': vectors(7), 'label_text': filer.text()})
    return fields, [], None


def _orbit_units(filer):
    selectors = tuple(filer.data.bl() for _ in range(14))
    if any(selectors[i] for i in (2, 4, 13)):
        reject('td_orbit_units_reserved_selector')
    return {'unit_selectors': selectors}, [], None


def _comments(filer):
    return {'comments': _pairs(filer)}, [], None


def _analysis_control(filer):
    b = filer.data
    fields = {'mode': b.bl(), 'text': (filer.text(), filer.text()), 'selectors': tuple(b.bl() for _ in range(3)),
              'additional_text': filer.text(), 'final_selector': b.bl()}
    return fields, [], None


def _graphics_settings(filer):
    return {'selectors': tuple(filer.data.bl() for _ in range(4))}, [], None


def _viewport_data(filer):
    count = filer.count()
    return {'viewport_count': count}, [], 'td_viewport_records_unmapped' if count else None


READERS = {'cases': _cases, 'symbols': _symbols, 'logic': _logic, 'orbit': _orbit,
           'orbit-units': _orbit_units, 'submodel-comments': _comments, 'analysis-control': _analysis_control,
           'graphics-settings': _graphics_settings, 'viewport-data': _viewport_data}


def decode_project_record(row, standard, identity):
    cpp = identity['cppname']
    dxf, version, role = PROJECT_CLASSES[cpp]
    if identity['dxfname'] != dxf or row['kind'] != 'UNKNOWN_OBJ':
        reject('td_project_class_identity')
    filer = Filer(row)
    links = object_handles(filer, standard)
    filer.version(version)
    fields, references, limitation = READERS[role](filer)
    if limitation is None:
        filer.finish()
    return {
        'role': role, 'payload_version': version, 'settings': fields, 'references': references,
        'common_references': links, 'status': 'partial-payload' if limitation else 'payload-decoded',
        'limitations': [limitation] if limitation else [],
        'remaining_bits': {
            name: stream.end - stream.position for name, stream in
            (('data', filer.data), ('text', filer.strings), ('handles', filer.handles))
        } if limitation else {},
    }


def project_records(snapshot, objects, standards):
    classes = {row['number']: row for row in snapshot.native['classes']}
    for handle, row in objects.items():
        if row['kind'] not in ('UNKNOWN_OBJ', 'UNKNOWN_ENT'):
            continue
        identity = classes.get(row['type'])
        if identity is None:
            continue
        cpp = identity['cppname']
        if cpp not in PROJECT_CLASSES:
            continue
        base = {'handle': str(handle), 'class': cpp, 'dxf': identity['dxfname']}
        try:
            yield {**base, **decode_project_record(row, standards[handle], identity)}
        except ExchangeError as error:
            yield {**base, 'status': 'retained-opaque', 'limitations': [error.code]}
