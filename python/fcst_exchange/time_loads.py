# SPDX-License-Identifier: MIT OR Apache-2.0
"""Convert reviewed source power tables into an owned transient worker request."""
import math
from pathlib import PurePosixPath

from fcst_contracts import BUNDLE, read

from .core import Limits, reject, target_id


def time_table(rows, units, multiplier, *, period=None):
    if not 2 <= len(rows) <= Limits().records:
        reject('time_load_limit')
    time_scale = BUNDLE['units'][units.time][1]
    power_scale = BUNDLE['units'][units.power][1]
    points = [[time * time_scale, power * multiplier * power_scale] for time, power in rows]
    if (any(not math.isfinite(value) for row in points for value in row)
            or any(a[0] >= b[0] or not math.isfinite(b[0] - a[0]) for a, b in zip(points, points[1:]))):
        reject('time_load_axis')
    result = {'points': points}
    if period is not None:
        seconds = period * time_scale
        if not math.isfinite(seconds) or seconds <= 0 or points[0][0] != 0:
            reject('time_load_period')
        result['period_s'] = seconds
    return result


def transient_request(model, time_loads, *, end, samples):
    if (type(end) not in (int, float) or not math.isfinite(end) or end <= 0
            or type(samples) is not int or not 2 <= samples <= Limits().records):
        reject('time_load_run_interval')
    if not 1 <= len(time_loads) <= 1024:
        reject('time_load_inventory')
    times = [end * (i / (samples - 1)) for i in range(samples)]
    if any(a >= b for a, b in zip(times, times[1:])):
        reject('time_load_run_interval')
    entities = {entity['id']: entity for entity in model['entities']}
    markers = []
    for identifier in time_loads:
        load = entities.get(identifier)
        if not load or load['kind'] != 'load' or 'expression_id' in load:
            reject('time_load_reference')
        marker = target_id(('time-load-callback', identifier))
        entities[identifier] = {**load, 'expression_id': marker}
        # A load with an expression requires a bound native power callback.
        # Sending the model alone must not silently solve a constant fallback.
        markers.append({'id': marker, 'kind': 'expression', 'dimension': 'power',
                        'ast': {'op': 'literal', 'quantity': {'value': 0, 'unit': 'W'}}})
    model = read('model', {**model, 'entities': [*entities.values(), *markers],
                           'assumptions': [*model['assumptions'], 'Time-dependent sources require native table bindings']})
    return {
        'thermal_input': {'contract_version': '1.0.0', 'model': model, 'material_laws': [], 'node_storage': []},
        'transient': {'start': 0, 'end': end, 'output_times': times, 'include_steps': False},
        'time_loads': [{'load_id': identifier, **table} for identifier, table in sorted(time_loads.items())],
    }


def prepare_drawing_transient(staged, *, end, samples):
    from .independent_td import DwgPreview
    from .td_model import _convert_network
    from .td_properties import parse_properties

    if not isinstance(staged, DwgPreview):
        reject('independent_td_preview_required')
    for path, raw in staged.original.files:
        if path == staged.original.entry:
            continue
        suffix = PurePosixPath(path).suffix.casefold()
        if suffix not in ('.tdp', '.rco'):
            reject('td_native_companion_unmapped')
        parse_properties(raw, suffix[1:])
    tables = {}
    result = _convert_network(staged.snapshot, staged.units, staged.original.source_hash, time_loads=tables)
    if result.diagnostics:
        reject(result.diagnostics[0]['code'])
    request = transient_request(result.require_native(), tables, end=end, samples=samples)
    staged.original.check_current()
    return request
