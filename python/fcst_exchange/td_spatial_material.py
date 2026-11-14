# SPDX-License-Identifier: MIT OR Apache-2.0
"""Bind TDP material laws in the local axes of Cartesian TD primitives."""
from dataclasses import dataclass
import math

from fcst_app.discretization import identity

from .core import Limits, reject
from .td_property_laws import _span, _validate_aggregate, entry_laws, material_laws


def positive(value):
    if not math.isfinite(value) or value <= 0:
        reject('td_property_material_range')
    return value


def quantity(value, unit):
    return {'value': value, 'unit': unit}


@dataclass(frozen=True)
class MaterialProfile:
    density: float
    temperatures: tuple
    specific_heat: tuple
    conductivity: tuple
    orthotropic: bool
    composite: bool = False


def material_profile(key, entries, temperature_range, profiles):
    entry = entries[key]
    row = entry_laws(entry, 'tdp')
    mode = row['scalars'].get('TYPE', 0)
    if mode == 0:
        return _basic_profile(row, temperature_range)
    if mode not in (1, 2):
        reject('td_spatial_material_mode')
    return _composite_profile(row, entries, temperature_range, profiles)


def _basic_profile(row, temperature_range):
    if not {'DENSITY', 'SPECHEAT', 'CONDUCT'} <= row['scalars'].keys():
        reject('td_property_required_fields_unmapped')
    if 'aggregate' in row:
        _validate_aggregate(row, Limits())
    material = material_laws(row)
    orthotropic = material['mode'] == 'orthotropic'
    if not orthotropic and any(law.mode != 'constant' for law in material['conductivity'][1:]):
        reject('td_spatial_material_axis_mode')
    axes = material['conductivity'] if orthotropic else (material['conductivity'][0],) * 3
    laws = (*axes, material['specific_heat'])
    if any(law.mode not in ('constant', 'temperature-table') for law in laws):
        reject('td_spatial_material_pressure_unmapped')
    low, high = temperature_range
    knots = sorted({knot for law in laws for knot in law.temperature if low < knot < high})
    temperatures = (low, *knots, high)
    samples = tuple(_sample(law, temperatures) for law in laws)
    return MaterialProfile(positive(material['density']['value']), temperatures, samples[3],
                           tuple(zip(*samples[:3])), orthotropic)


def _sample(law, temperatures):
    if law.temperature and (len(law.temperature) < 2 or law.temperature[0] > temperatures[0]
                            or law.temperature[-1] < temperatures[-1]):
        reject('td_spatial_material_table_domain')
    return tuple(positive(law.evaluate(temperature=t, interpolation='linear', extrapolation='error'))
                 for t in temperatures)


def _diagonal(values):
    return tuple(tuple(value if i == j else 0.0 for j in range(3)) for i, value in enumerate(values))


def _composite_profile(row, entries, temperature_range, cache):
    _validate_aggregate(row, Limits())
    aggregate = row['aggregate']
    settings, components = aggregate['scalars'], aggregate['components']
    laminate = row['scalars']['TYPE'] == 1
    if any(settings.get(flag, 0) for flag in ('AGGREGATE_OVERRIDE_CONDUCTIVITY',
                                             'AGGREGATE_OVERRIDE_SPECIFIC_HEAT_DENSITY')):
        reject('td_spatial_composite_override_unmapped')
    profiles, weights, directions = [], [], []
    mass_fractions = not laminate and settings.get('WEIGHTTYPE', 1) == 0
    for component in components:
        name = component['material'].casefold()
        if name not in entries:
            reject('td_property_law_composite_reference')
        if name not in cache:
            basic = entry_laws(entries[name], 'tdp')
            if basic['scalars'].get('TYPE', 0) != 0:
                reject('td_property_law_composite_reference')
            cache[name] = _basic_profile(basic, temperature_range)
        profile = cache[name]
        if profile.composite:
            reject('td_property_law_composite_reference')
        if len(set(profile.specific_heat)) != 1 or len(set(profile.conductivity)) != 1:
            reject('td_spatial_composite_variable_unmapped')
        fields = component['scalars']
        if laminate:
            angle = fields.get('ORIENTATIONANGLE', 0) % 180
            if profile.orthotropic and angle not in (0, 90):
                reject('td_spatial_laminate_orientation_unmapped')
            weight = positive(fields['THICKNESS'])
            k = profile.conductivity[0]
            direction = (k[1], k[0], k[2]) if angle == 90 else k
        else:
            if any(field in fields for field in ('KXP', 'KYP', 'KZP')):
                reject('td_spatial_composite_component_scaling_unmapped')
            weight = fields.get('MASSFRACTION', 1) if mass_fractions else fields.get('WEIGHT', 0)
            direction = profile.conductivity[0]
        profiles.append(profile)
        weights.append(weight)
        directions.append(direction)
    if not laminate and not math.isclose(math.fsum(weights), 1, rel_tol=0, abs_tol=1e-12):
        reject('td_spatial_composite_fraction_sum')
    volumes = [w / p.density if mass_fractions else w for w, p in zip(weights, profiles)]
    volume_scale = positive(max(volumes))
    normalized = [volume / volume_scale for volume in volumes]
    total = math.fsum(normalized)
    fractions = [volume / total for volume in normalized]
    partial_densities = [f * p.density for f, p in zip(fractions, profiles)]
    try:
        density = positive(math.fsum(partial_densities))
        cp = positive(math.fsum((d / density) * p.specific_heat[0] for d, p in zip(partial_densities, profiles)))
    except OverflowError:
        reject('td_property_material_range')
    scales = (1, 1, 0) if laminate else tuple(settings.get(tag, .5) for tag in ('KXP', 'KYP', 'KZP'))
    if any(s not in (0, 1) for s in scales):
        reject('td_spatial_composite_mixed_conductivity_unmapped')
    try:
        axes = [positive(math.fsum(f * k for f, k in zip(fractions, direction)) if scale else
                         1 / positive(math.fsum(f / k for f, k in zip(fractions, direction))))
                for scale, direction in zip(scales, zip(*directions))]
    except OverflowError:
        reject('td_property_material_range')
    return MaterialProfile(density, tuple(temperature_range), (cp, cp), (tuple(axes),) * 2, True, True)


def bind_profile(profile, label, base_id, axes, temperature, multipliers):
    """Prepare canonical reference properties and exact native linear tables."""
    grid = profile.temperatures
    left, right, fraction = _span(grid, temperature, 'linear', 'error')
    cp = profile.specific_heat[left] * (1 - fraction) + profile.specific_heat[right] * fraction
    density_scale, *conductivity_scale = multipliers
    conductivity = tuple(tuple(positive(value * scale) for value, scale in zip(k, conductivity_scale))
                         for k in profile.conductivity)
    reference = tuple(a * (1 - fraction) + b * fraction for a, b in zip(conductivity[left], conductivity[right]))
    frame = None
    identifier = base_id
    if profile.orthotropic or len(set(conductivity_scale)) > 1:
        rotation = tuple(zip(*axes))
        frame_id = identity((base_id, rotation))
        identifier = identity((base_id, frame_id))
        frame = {'id': frame_id, 'kind': 'frame', 'origin': [quantity(0, 'm')] * 3,
                 'rotation': [list(row) for row in rotation]}
    entity = {'id': identifier, 'kind': 'material', 'label': label,
              'density': quantity(positive(profile.density * density_scale), 'kg/m3'), 'specific_heat': quantity(cp, 'J/(kg*K)'),
              'conductivity': quantity(reference[0], 'W/(m*K)'),
              'valid_temperature': [quantity(t, 'K') for t in (grid[0], grid[-1])]}

    def scalar_table(values, unit):
        return {'temperature': [quantity(t, 'K') for t in grid], 'values': [quantity(v, unit) for v in values],
                'interpolation': 'linear', 'extrapolation': 'error', 'discontinuities': []}

    scalar_laws = {}
    if len(set(profile.specific_heat)) > 1:
        scalar_laws['specific_heat'] = scalar_table(profile.specific_heat, 'J/(kg*K)')
    tensor_law = None
    if frame:
        entity.update(frame_id=frame['id'], conductivity_tensor=[list(row) for row in _diagonal(reference)])
        if len(set(conductivity)) > 1:
            tensor_law = {'material_id': identifier, 'frame_id': frame['id'], 'reference_temperature_K': temperature,
                          'temperatures_K': list(grid),
                          'tensors_W_per_mK': [[list(row) for row in _diagonal(k)] for k in conductivity],
                          'interpolation': 'linear', 'extrapolation': 'error'}
    elif len(set(conductivity)) > 1:
        scalar_laws['conductivity'] = scalar_table([k[0] for k in conductivity], 'W/(m*K)')
    return entity, frame, {'material_id': identifier, **scalar_laws} if scalar_laws else None, tensor_law
