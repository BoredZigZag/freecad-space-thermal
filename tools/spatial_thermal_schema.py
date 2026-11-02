# SPDX-License-Identifier: MIT OR Apache-2.0
"""Additive v2 thermal input; released v1/model/spatial contracts stay byte identical."""
from copy import deepcopy


def schema(v1, obj, arr, enum):
    value = deepcopy(v1)
    value['$id'] = 'urn:fcst:thermal-input:2.0.0'
    value['properties']['contract_version'] = {'const': '2.0.0'}
    uid = {'$ref': '#/$defs/uuid'}
    number = {'type': 'number'}
    positive = {'type': 'number', 'exclusiveMinimum': 0}
    nonnegative = {'type': 'number', 'minimum': 0}
    weights = arr(obj({'node_id': uid, 'weight': positive}), minItems=1, maxItems=4096)
    value['properties']['spatial'] = obj({
        'length_unit': {'const': 'm'},
        'mesh_revision': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
        'points': arr(obj({'id': uid, 'node_id': uid, 'position': arr(number, minItems=3, maxItems=3)}), minItems=3, maxItems=16384),
        'cells': arr(obj({'element_id': uid, 'topology': enum('tri3', 'quad4', 'tet4', 'hex8'),
                          'point_ids': arr(uid, minItems=3, maxItems=8, uniqueItems=True),
                          'thickness_m': nonnegative}), minItems=1, maxItems=32768),
        'surfaces': arr(obj({'id': uid, 'kind': enum('flux', 'power', 'convection'),
                             'point_ids': arr(uid, minItems=3, maxItems=3, uniqueItems=True),
                             'value_SI': number, 'ambient_K': nonnegative}), maxItems=16384),
        'contacts': arr(obj({'id': uid, 'kind': enum('contact', 'insulation', 'mli', 'heat_pipe'),
                             'from': weights, 'to': weights, 'area_m2': positive,
                             'coefficient_SI': positive, 'gap_m': nonnegative,
                             'minimum_temperature_K': nonnegative, 'maximum_temperature_K': positive,
                             'maximum_power_W': positive, 'calibration_id': uid}), maxItems=16384),
        'tensor_laws': arr(obj({'material_id':uid,'frame_id':uid,'reference_temperature_K':nonnegative,
            'temperatures_K':arr(nonnegative,minItems=2,maxItems=16384),
            'tensors_W_per_mK':arr(arr(arr(number,minItems=3,maxItems=3),minItems=3,maxItems=3),minItems=2,maxItems=16384),
            'interpolation':{'const':'linear'},'extrapolation':enum('error','clamp')}),maxItems=16384),
    }, ('tensor_laws',))
    value['required'].append('spatial')
    return value
