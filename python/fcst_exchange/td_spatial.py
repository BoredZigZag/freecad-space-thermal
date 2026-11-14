# SPDX-License-Identifier: MIT OR Apache-2.0
"""Reconstruct static TD primitives and their thermophysical assignments in SI."""
from hashlib import sha256
from itertools import product
import math
from pathlib import PurePosixPath

from fcst_app.discretization import MeshRegion, from_regions, identity
from fcst_contracts import canonical

from .core import Limits, reject
from .td_filer import expression_is_constant
from .td_geometry import BrickPayload
from .td_geometry_mesh import LENGTH_UNITS, primitive_grid, selected_geometry, world_point
from .td_properties import parse_properties
from .td_spatial_material import bind_profile, material_profile
from .vendor_paths import path_name


def _constant_assignment(payload, scale):
    attrs = payload.fields['attributes']
    if isinstance(payload, BrickPayload):
        advection = attrs['advection']
        if ('extended_attributes' in payload.fields or attrs['selector_a'] != 0
                or attrs['selector_b'] != 1 or attrs['selector_c'] != 0
                or attrs['selector_d'] != 0 or attrs['scalars_a'] != (1,) * 4
                or any(advection['selectors']) or any(advection['values'])
                or any(not expression_is_constant(e) for e in (*attrs['expressions_a'], *advection['expressions']))):
            reject('td_spatial_brick_material_mode')
        return attrs['names_a'][1], 0.0, (1,) * 4

    top, bottom = attrs['property_names']
    if ('extended_attributes' in attrs or attrs['primary_selector'] != 1 or bottom.casefold() not in ('', 'default')
            or attrs['property_label'].casefold() not in ('', 'default') or attrs['property_value']
            or any(attrs['selectors_a']) or any(attrs['selectors_b']) or any(attrs['selectors_f']) or any(attrs['selectors_i'])
            or any(value <= 0 for value in attrs['values_g']) or any(attrs['name_lists']) or any(attrs['name_maps'])
            or any(not expression_is_constant(e)
                   for key in ('expressions_a', 'expressions_b', 'expressions_c') for e in attrs[key])):
        reject('td_spatial_rectangle_material_mode')
    thickness = attrs['property_scalars'][0] * scale
    if not math.isfinite(thickness) or thickness <= 0:
        reject('td_spatial_thickness')
    return top, thickness, attrs['values_g']


def _region(prefix, material, thickness, grid):
    (u, v, w), origin, axes = grid
    positions = [world_point(origin, axes, (x, y, z)) for z, y, x in product(w, v, u)]
    if len(set(positions)) != len(positions):
        reject('td_geometry_coordinate_precision')
    stride = len(u)
    layer = len(v) * stride
    solid = len(w) > 1
    heights = [b - a for a, b in zip(w, w[1:])] if solid else [thickness]
    connectivity, volumes = [], []
    nodal = [0.0] * len(positions)
    for k, height in enumerate(heights):
        for j in range(len(v) - 1):
            for i in range(len(u) - 1):
                a = k * layer + j * stride + i
                face = [a, a + 1, a + 1 + stride, a + stride]
                cell = face + [p + layer for p in face] if solid else face
                volume = (u[i + 1] - u[i]) * (v[j + 1] - v[j]) * height
                share = volume / len(cell)
                if not math.isfinite(share) or share <= 0:
                    reject('td_spatial_volume')
                connectivity.append(cell)
                volumes.append(volume)
                for point in cell:
                    nodal[point] += share
    return MeshRegion(prefix, 'hex8' if solid else 'quad4', positions, connectivity,
                      volumes, nodal, thickness, material)


def prepare_spatial(staged, properties, length_unit, *, temperature, temperature_range, handles=()):
    """Build an independent conduction-only input from captured DWG/TDP bytes."""
    geometry = selected_geometry(staged, handles)
    if staged.snapshot.native['version'] != 'AC1032':
        reject('td_spatial_container_version_unmapped')
    if length_unit not in LENGTH_UNITS:
        reject('td_geometry_length_unit')
    if (len(temperature_range) != 2
            or not all(type(x) in (int, float) and math.isfinite(x) for x in (temperature, *temperature_range))
            or not 0 < temperature_range[0] < temperature_range[1]
            or not temperature_range[0] <= temperature <= temperature_range[1]):
        reject('td_spatial_temperature')
    path_name(properties)
    library = dict(staged.original.files).get(properties)
    if PurePosixPath(properties).suffix.casefold() != '.tdp' or library is None:
        reject('td_spatial_property_companion')
    entries = {entry.name.casefold(): entry for entry in parse_properties(library, 'tdp').entries}
    source_revision = staged.original.source_hash
    property_revision = sha256(library).hexdigest()
    selection = sha256(canonical([properties, [str(handle) for handle, _ in geometry]])).hexdigest()
    prefix = f'td-spatial-{source_revision}-{selection}-'
    profiles, bindings, frames = {}, {}, {}
    material_laws, tensor_laws, regions, bodies, material_sources = [], [], [], [], []
    mapping_count = 0
    for handle, payload in geometry:
        grid = primitive_grid(payload, length_unit)
        name, thickness, multipliers = _constant_assignment(payload, LENGTH_UNITS[length_unit])
        key = name.casefold()
        if key in ('', 'default') or key not in entries:
            reject('td_spatial_material_missing')
        if key not in profiles:
            profiles[key] = material_profile(key, entries, temperature_range, profiles)
        profile = profiles[key]
        axes = tuple(grid[2])
        oriented = profile.orthotropic or len(set(multipliers[1:])) > 1
        binding = (key, multipliers, axes if oriented else ())
        if binding not in bindings:
            base_id = identity(f'td-spatial-property-{property_revision}-{key}')
            if multipliers != (1,) * 4:
                base_id = identity((base_id, multipliers))
            material, frame, scalar_law, tensor_law = bind_profile(profile, entries[key].name, base_id, axes, temperature, multipliers)
            identifier = material['id']
            bindings[binding] = material
            source_handle = sha256(key.encode('utf-8')).hexdigest()
            if frame:
                frames[frame['id']] = frame
            if frame or multipliers != (1,) * 4:
                source_handle += '.' + identifier
            material_sources.append(dict(namespace='TD.PROPERTIES', handle=source_handle, entity_id=identifier))
            if scalar_law:
                material_laws.append(scalar_law)
            if tensor_law:
                tensor_laws.append(tensor_law)

        # Each mandatory mapping carries three UUIDs and a SHA-256 digest.
        # This conservative lower bound avoids building an over-limit grid.
        counts = [len(axis) - 1 for axis in grid[0]]
        mapping_count += counts[0] * counts[1] * (8 * counts[2] if counts[2] else 4)
        if mapping_count * 172 > Limits().file_bytes:
            reject('td_spatial_input_limit')
        region = _region(f'td-spatial-{source_revision}-{handle}-', bindings[binding], thickness, grid)
        regions.append(region)
        bodies.append(dict(namespace='TD.DWG', handle=str(handle), entity_id=region.identifier('submodel')))
    sources = [
        dict(id=identity(prefix + 'source-dwg'), version='1.0.0', source_revision=source_revision,
             source_tool='Thermal Desktop DWG', source_version='AC1032', entries=bodies),
        dict(id=identity(prefix + 'source-tdp'), version='1.0.0', source_revision=property_revision,
             source_tool='Thermal Desktop property text', source_version='UNICODE bracket-tagged profile 1',
             entries=material_sources),
    ]
    value = from_regions(regions, temperature=temperature, prefix=prefix, source_maps=sources,
                         assumptions=['Caller-declared temperature and property validity interval in kelvin',
                                      'Linear interpolation of active TDP temperature tables within the declared interval'],
                         limitations=['Independent bodies with FCST-generated nodes and insulated boundaries',
                                      'Conduction only; source loads, radiation, contact and case controls excluded'],
                         material_frames=frames.values(), material_laws=material_laws, tensor_laws=tensor_laws)
    staged.original.check_current()
    return value, dict(objects=len(regions), materials=len(bindings), points=len(value['spatial']['points']),
                       cells=len(value['spatial']['cells']), vendor_runtime_required=False, qualified=False)
