# SPDX-License-Identifier: MIT OR Apache-2.0
"""Bind reviewed TD material laws to the existing native thermal input contract."""
from hashlib import sha256
import math

from fcst_contracts import read

from .core import Limits, reject, target_id
from .td_property_laws import material_laws, read_laws

MASS_UNITS = {'kg': 1.0, 'g': 0.001, 'lbm': 0.45359237}
VOLUME_UNITS = {'m3': 1.0, 'cm3': 1e-6, 'mm3': 1e-9, 'in3': 0.0254**3, 'ft3': 0.3048**3}


def prepare_drawing_material_input(staged, bindings, *, mass_unit, volume_unit):
    """Resolve material bindings directly from a closed DWG and its TDP companion."""
    from pathlib import PurePosixPath

    from .independent_td import DwgPreview
    from .td_model import _convert_network

    if not isinstance(staged, DwgPreview):
        reject('independent_td_preview_required')
    if (not isinstance(mass_unit, str) or mass_unit not in MASS_UNITS
            or not isinstance(volume_unit, str) or volume_unit not in VOLUME_UNITS):
        reject('td_material_drawing_units')
    if (not isinstance(bindings, dict) or bindings.keys() != {'materials', 'interpolation', 'extrapolation'}
            or not isinstance(bindings['materials'], dict)):
        reject('td_material_drawing_binding_shape')
    companions = [(name, raw) for name, raw in staged.original.files if name != staged.original.entry]
    if len(companions) != 1 or PurePosixPath(companions[0][0]).suffix.lower() != '.tdp':
        reject('td_material_drawing_dependency_closure')

    material_nodes = {}
    conversion = _convert_network(staged.snapshot, staged.units, staged.original.source_hash,
                                  material_nodes=material_nodes)
    model = conversion.require_native()
    if not material_nodes or bindings['materials'].keys() != {name for name, _, _ in material_nodes.values()}:
        reject('td_material_drawing_binding_coverage')
    node_storage = {}
    for identifier, (entry, mode, value) in material_nodes.items():
        if mode == 0:
            node_storage[identifier] = {'entry': entry, 'volume_m3': value * VOLUME_UNITS[volume_unit]}
        else:
            node_storage[identifier] = {'entry': entry, 'mass_kg': value * MASS_UNITS[mass_unit]}
    result = prepare_material_input(companions[0][1], model, {**bindings, 'node_storage': node_storage})
    staged.original.check_current()
    return result


def prepare_material_input(raw, model, bindings):
    """Prepare a new thermal input from a TDP and explicit SI material/node bindings."""
    required = {'materials', 'node_storage', 'interpolation', 'extrapolation'}
    if (not isinstance(bindings, dict) or not required <= bindings.keys()
            or bindings.keys() - required - {'case_id'}):
        reject('td_material_binding_shape')
    interpolation, extrapolation = bindings['interpolation'], bindings['extrapolation']
    if interpolation not in ('linear', 'previous') or extrapolation not in ('error', 'clamp'):
        reject('td_property_law_policy')
    materials, storage = bindings['materials'], bindings['node_storage']
    if (not isinstance(materials, dict) or not materials or not isinstance(storage, dict)
            or len(materials) + len(storage) > Limits().records
            or any(not isinstance(key, str) for key in (*materials, *storage))):
        reject('td_material_binding_shape')

    model = read('model', model)
    entities = {entity['id']: entity for entity in model['entities']}
    if not any(entity['kind'] == 'node' for entity in entities.values()):
        reject('td_material_binding_empty_network')
    cases = {identifier: entity for identifier, entity in entities.items() if entity['kind'] == 'case'}
    case_id = bindings.get('case_id')
    if ('case_id' in bindings or cases) and (not isinstance(case_id, str) or case_id not in cases):
        reject('td_material_binding_case')
    if case_id and any(overlay['field'] == 'temperature' and overlay['entity_id'] in storage
                       for overlay in cases[case_id]['overlays']):
        reject('td_material_binding_temperature_overlay')

    library = {row['name']: row for row in read_laws(raw, 'tdp')['entries']}
    revision = sha256(raw).hexdigest()
    source_id = target_id(('td-material-input-map', revision))
    if any(source['id'] == source_id for source in model['source_maps']):
        reject('td_material_binding_source_exists')
    source_entries = []
    law_rows, node_rows, bound = [], [], {}

    def number(value):
        try:
            if type(value) in (int, float) and math.isfinite(value) and value > 0:
                return float(value)
        except OverflowError:
            pass
        reject('td_material_binding_range')

    def quantity(value, unit):
        return {'value': number(value), 'unit': unit}

    def sample(law, temperature):
        return number(law.evaluate(temperature=temperature, interpolation=interpolation, extrapolation=extrapolation))

    for name, binding in sorted(materials.items()):
        if (name not in library or not isinstance(binding, dict)
                or binding.keys() != {'minimum_K', 'maximum_K', 'reference_K'}):
            reject('td_material_binding_entry')
        low, high, reference = (number(binding[key]) for key in ('minimum_K', 'maximum_K', 'reference_K'))
        if not low < high or not low <= reference <= high:
            reject('td_material_binding_range')
        laws = material_laws(library[name])
        if laws['mode'] != 'isotropic' or laws['effective_emissivity'] != 0:
            reject('td_material_binding_unmapped_mode')
        identifier = target_id(('td-property', 'material', name.casefold()))
        if identifier in entities:
            reject('td_material_binding_identity_exists')
        material = {'id': identifier, 'kind': 'material', 'label': name,
                    'density': quantity(laws['density']['value'], 'kg/m3'),
                    'valid_temperature': [quantity(low, 'K'), quantity(high, 'K')]}
        law_row = {'material_id': identifier}
        for key, law in (('specific_heat', laws['specific_heat']), ('conductivity', laws['conductivity'][0])):
            if law.mode not in ('constant', 'temperature-table'):
                reject('td_material_binding_unmapped_mode')
            material[key] = quantity(sample(law, reference), law.unit)
            if law.mode == 'constant':
                continue
            axis = law.temperature
            if (len(axis) < 2 or axis[0] < low or axis[-1] > high
                    or extrapolation == 'error' and (axis[0] != low or axis[-1] != high)):
                reject('td_material_binding_table_domain')
            values = [number(value * law.scale) for value in law.values]
            jumps = []
            for index, (left, right) in enumerate(zip(values, values[1:]), 1):
                if interpolation == 'linear' and not math.isfinite((right - left) / (axis[index] - axis[index - 1])):
                    reject('td_material_binding_table_slope')
                if interpolation == 'previous' and left != right:
                    jumps.append(index)
            law_row[key] = {'temperature': [quantity(value, 'K') for value in axis],
                            'values': [quantity(value, law.unit) for value in values],
                            'interpolation': interpolation, 'extrapolation': extrapolation,
                            'discontinuities': jumps}
        if len(law_row) > 1:
            law_rows.append(law_row)
        model['entities'].append(material)
        bound[name] = (identifier, low, high, laws['specific_heat'], material['density']['value'])
        source_entries.append({'namespace': 'TD.PROPERTIES',
                               'handle': 'tdp.' + sha256(name.casefold().encode()).hexdigest()[:32],
                               'entity_id': identifier})

    for identifier, binding in sorted(storage.items()):
        node = entities.get(identifier)
        if (not node or node['kind'] != 'node' or node['classification'] != 'capacitive'
                or not isinstance(binding, dict) or binding.keys() not in ({'entry', 'mass_kg'}, {'entry', 'volume_m3'})
                or not isinstance(binding['entry'], str) or binding['entry'] not in bound):
            reject('td_material_binding_storage')
        material_id, low, high, law, density = bound[binding['entry']]
        temperature = node['temperature']['value']
        if not low <= temperature <= high:
            reject('td_material_binding_storage_temperature')
        mass = number(binding['mass_kg']) if 'mass_kg' in binding else number(number(binding['volume_m3']) * density)
        node['capacity'] = quantity(mass * sample(law, temperature), 'J/K')
        node_rows.append({'node_id': identifier, 'material_id': material_id, 'mass': quantity(mass, 'kg')})

    model['source_maps'].append({'id': source_id, 'version': '1.0.0', 'source_revision': revision,
                                 'source_tool': 'Thermal Desktop property text',
                                 'source_version': 'UNICODE bracket-tagged profile 1', 'entries': source_entries})
    model['revision'] += 1
    result = {'contract_version': '1.0.0', 'model': read('model', model),
              'material_laws': law_rows, 'node_storage': node_rows}
    if case_id:
        result['case_id'] = case_id
    return result
