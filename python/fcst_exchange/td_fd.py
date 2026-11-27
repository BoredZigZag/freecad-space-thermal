# SPDX-License-Identifier: MIT OR Apache-2.0
"""Native Cartesian finite-difference networks from saved TD node attachments."""
from collections import defaultdict
from hashlib import sha256
from itertools import product
import math

from fcst_app.discretization import identity
from fcst_contracts import canonical, read

from .core import Limits, reject
from .td_geometry_mesh import primitive_grid, selected_geometry
from .td_spatial import _constant_assignment, material_input
from .td_spatial_material import bind_profile, material_profile, positive, quantity
from .td_spatial_source import (BRICK_FACES, TEMPERATURE_UNITS, face_power, match_saved_nodes,
                                saved_boundary_temperature, saved_node_groups)


def _widths(cuts, coordinates, centered):
    widths = []
    for partition, centers in zip(cuts, coordinates):
        if len(partition) == 1:
            widths.append((1.0,))
            continue
        boundaries = partition if centered else (
            partition[0], *(a + (b-a)/2 for a, b in zip(centers, centers[1:])), partition[-1])
        widths.append(tuple(b-a for a, b in zip(boundaries, boundaries[1:])))
    return widths


def _add_body(body, grid, matched, conductivity, thickness, material_id, masses, links, selected_face, loads):
    centered, coordinates, nodes = matched
    widths = _widths(grid[0], coordinates, centered)
    dimensions = tuple(map(len, coordinates))
    strides = (1, dimensions[0], dimensions[0] * dimensions[1])
    profile_dimensions = 2 if len(grid[0][2]) == 1 else 3
    if selected_face:
        marker, power, load_handle = selected_face
        if profile_dimensions == 2:
            if marker not in (1, 2):
                reject('td_fd_sheet_face_selection')
            face_axis, maximum = 2, False
        else:
            face_axis, maximum, _ = BRICK_FACES[marker]
        face_area = positive(math.prod(grid[0][axis][-1] for axis in range(profile_dimensions) if axis != face_axis))
        face_index = dimensions[face_axis]-1 if maximum else 0

    for k, j, i in product(*(range(n) for n in reversed(dimensions))):
        indices = (i, j, k)
        index = sum(v*s for v, s in zip(indices, strides))
        ref, _ = nodes[index]
        local = [widths[axis][indices[axis]] for axis in range(profile_dimensions)]
        cross_scale = thickness if profile_dimensions == 2 else 1.0
        volume = positive(math.prod(local) * cross_scale)
        masses[ref][material_id].append(volume)
        for axis in range(profile_dimensions):
            if indices[axis] + 1 == dimensions[axis]:
                continue
            other, _ = nodes[index + strides[axis]]
            area = cross_scale * math.prod(width for j, width in enumerate(local) if j != axis)
            distance = coordinates[axis][indices[axis]+1] - coordinates[axis][indices[axis]]
            pair = tuple(sorted((ref, other)))
            links[pair].append(positive(conductivity[axis] * (area / distance)))
        if selected_face and indices[face_axis] == face_index:
            weight = math.prod(width for j, width in enumerate(local) if j != face_axis) / face_area
            loads[(load_handle, body, ref)] = power * weight


def prepare_fd(staged, properties, length_unit, *, temperature, temperature_range, handles=(),
               face_load_handle=None, power_unit=None, node_temperature_unit=None):
    """Prepare the owned lumped-network contract for saved Cartesian FD bodies."""
    geometry = selected_geometry(staged, handles)
    scale, revision, entries = material_input(staged, properties, length_unit, temperature, temperature_range)
    if node_temperature_unit is not None and node_temperature_unit not in TEMPERATURE_UNITS:
        reject('td_geometry_temperature_unit')
    if (face_load_handle is None) != (power_unit is None):
        reject('td_spatial_face_power_unit')
    selected_face = face_power(staged.snapshot, face_load_handle, power_unit) if face_load_handle is not None else None
    if selected_face and selected_face[0] not in {handle for handle, _ in geometry}:
        reject('td_spatial_face_load_target')

    source = staged.original.source_hash
    prefix = 'td-fd-' + sha256(canonical([source, revision, length_unit, [str(h) for h, _ in geometry],
                                            str(face_load_handle), power_unit or '', node_temperature_unit or ''])).hexdigest()
    groups = saved_node_groups(staged.snapshot, geometry)
    owners = defaultdict(set)
    for owner, records in groups.items():
        for ref, _ in records:
            owners[ref].add(owner)
    profiles, materials, nodes, submodels = {}, {}, {}, {}
    fixed_temperatures = {}
    masses, links, loads = defaultdict(lambda: defaultdict(list)), defaultdict(list), {}
    material_laws, source_nodes, property_sources, body_sources, entities = [], [], [], [], []
    active_laws = set()
    for handle, payload in geometry:
        grid = primitive_grid(payload, length_unit)
        name, thickness, multipliers = _constant_assignment(payload, scale)
        key = name.casefold()
        if key in ('', 'default') or key not in entries:
            reject('td_spatial_material_missing')
        if key not in profiles:
            profiles[key] = material_profile(key, entries, temperature_range, profiles)
        profile = profiles[key]
        if len(set(profile.conductivity)) != 1:
            reject('td_fd_variable_conductance')
        binding = key, multipliers
        if binding not in materials:
            material_id = identity(('td-fd-material', revision, binding))
            material, _, law, _ = bind_profile(profile, entries[key].name, material_id,
                                                ((1,0,0),(0,1,0),(0,0,1)), temperature, multipliers)
            # Each link uses its own local conductivity. Storage uses cp only.
            material.pop('frame_id', None)
            material.pop('conductivity_tensor', None)
            material['id'] = material_id
            entities.append(material)
            materials[binding] = material
            property_sources.append(dict(namespace='TD.PROPERTIES', handle=material_id, entity_id=material_id))
            if law and 'specific_heat' in law:
                material_laws.append(dict(material_id=material_id, specific_heat=law['specific_heat']))
                active_laws.add(material_id)
        material = materials[binding]
        matched = match_saved_nodes(grid, handle, groups[handle], scale, allow_shared=True)
        for ref, node in matched[2]:
            fixed_temperatures[ref] = saved_boundary_temperature(node, node_temperature_unit,
                                                               temperature_range, 'td_fd_saved_node_mode')
            if {item['target'] for item in node['associations']} != owners[ref]:
                reject('td_fd_node_owner_closure')
            nodes[ref] = node
        conductivity = tuple(positive(k*s) for k, s in zip(profile.conductivity[0], multipliers[1:]))
        load = (*selected_face[1:], face_load_handle) if selected_face and selected_face[0] == handle else None
        _add_body(handle, grid, matched, conductivity, thickness, material['id'], masses, links, load, loads)
        if 440*len(nodes) + 235*len(links) + 195*len(loads) > Limits().file_bytes:
            reject('td_spatial_input_limit')
        body_sources.append((handle, matched[2][0][0]))

    by_id = {material['id']: material for material in materials.values()}
    identities, storage, seen = {}, [], set()
    for ref, node in sorted(nodes.items()):
        name, number = node['submodel'], node['identifier']
        key = name.casefold(), number
        if key in seen:
            reject('td_spatial_source_node_identity_collision')
        seen.add(key)
        submodel = submodels.get(key[0])
        if submodel is None:
            submodel = submodels[key[0]] = identity((source, 'td-fd-submodel', key[0]))
            entities.append(dict(id=submodel, kind='submodel', label=name))
        identifier = identities[ref] = identity((source, 'td-fd-node', ref))
        fixed = fixed_temperatures[ref]
        if fixed is None:
            contributions = {material: positive(math.fsum(volumes) * by_id[material]['density']['value'])
                             for material, volumes in masses[ref].items()}
            if len(contributions) > 1 and active_laws.intersection(contributions):
                reject('td_fd_shared_variable_storage')
            capacity = positive(math.fsum(mass * by_id[material]['specific_heat']['value']
                                         for material, mass in contributions.items()))
            if len(contributions) == 1:
                material, mass = next(iter(contributions.items()))
                storage.append(dict(node_id=identifier, material_id=material, mass=quantity(mass, 'kg')))
        else:
            capacity = 0
        entities.append(dict(id=identifier, kind='node', submodel_id=submodel,
                             classification='capacitive' if fixed is None else 'prescribed',
                             temperature=quantity(temperature if fixed is None else fixed, 'K'),
                             capacity=quantity(capacity, 'J/K')))
        source_nodes.append(dict(namespace='TD.DWG.FD-NODE', handle=str(ref), entity_id=identifier,
                                 submodel_handle=name, node_number=number))
    submodel_by_ref = {ref: submodels[node['submodel'].casefold()] for ref, node in nodes.items()}
    for (first, second), values in sorted(links.items()):
        entities.append(dict(id=identity((prefix, 'link', first, second)), kind='conductor',
                             from_node_id=identities[first], to_node_id=identities[second],
                             conductance=quantity(positive(math.fsum(values)), 'W/K')))
    for (load_handle, body, ref), power in sorted(loads.items()):
        identifier = identity((prefix, 'load', load_handle, body, ref))
        entities.append(dict(id=identifier, kind='load', node_id=identities[ref], power=quantity(power, 'W')))
        source_nodes.append(dict(namespace='TD.DWG.FD-FACE-LOAD', handle=f'{load_handle}.{body}.{selected_face[1]}.{ref}',
                                 entity_id=identifier))
    source_nodes.extend(dict(namespace='TD.DWG.FD-BODY', handle=str(handle), entity_id=submodel_by_ref[ref])
                        for handle, ref in body_sources)
    sources = [dict(id=identity(prefix + '-dwg'), version='1.0.0', source_revision=source,
                    source_tool='Thermal Desktop DWG', source_version='AC1032', entries=source_nodes),
               dict(id=identity(prefix + '-tdp'), version='1.0.0', source_revision=revision,
                    source_tool='Thermal Desktop property text', source_version='UNICODE bracket-tagged profile 1',
                    entries=property_sources)]
    model = read('model', dict(contract_version='1.0.0', minimum_reader='1.0.0', project_id=identity(prefix),
        revision=0, entities=entities, source_maps=sources, mappings=[], attachments=[],
        assumptions=['Cartesian finite differences with adjacent-node conductance and control-volume capacity',
                     'Caller-declared uniform initial temperature in kelvin'],
        limitations=['Static diffusive bodies and one optional literal face load',
                     'Radiation, contact and case controls excluded']))
    staged.original.check_current()
    value = dict(contract_version='1.0.0', model=model, material_laws=material_laws, node_storage=storage)
    return value, dict(formulation='fd', objects=len(geometry), nodes=len(nodes), conductors=len(links),
                       source_nodes=len(nodes), face_loads=int(bool(loads)), vendor_runtime_required=False, qualified=False)
