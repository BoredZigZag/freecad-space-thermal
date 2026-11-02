# SPDX-License-Identifier: MIT OR Apache-2.0
"""Immutable CAD/mesher value boundary; no executable scripts or host paths."""
def schema(obj, arr, enum):
    uid={'type':'string','pattern':'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'}
    digest={'type':'string','pattern':'^[0-9a-f]{64}$'}
    index={'type':'integer','minimum':1,'maximum':9007199254740991}
    number={'type':'number'};positive={'type':'number','exclusiveMinimum':0}
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'urn:fcst:cad-mesh:1.0.0',**obj({
        'contract_version':{'const':'1.0.0'},
        'geometry':obj({'id':uid,'revision':{'type':'integer','minimum':0,'maximum':9007199254740991},
            'brep_sha256':digest,'signature':digest,'faces':arr(obj({'id':uid,'ref':{'type':'string','pattern':'^Face[1-9][0-9]*$'},
                'signature':digest,'area_m2':positive}),minItems=1,maxItems=4096)}),
        'profile_sha256':digest,'mesher_version':{'const':'4.15.0'},
        'options':obj({'dimension':enum(2,3),'maximum_size_m':positive,'minimum_size_m':positive,
            'order':{'const':1},'threads':{'const':1},'algorithm_2d':{'const':5},'algorithm_3d':{'const':1},
            'random_seed':{'const':1},'optimize':{'const':False}}),
        'nodes':arr(obj({'tag':index,'position_m':arr(number,minItems=3,maxItems=3)}),minItems=3,maxItems=16384),
        'cells':arr(obj({'tag':index,'topology':enum('tri3','tet4'),'nodes':arr(index,minItems=3,maxItems=4,uniqueItems=True),
            'region':{'type':'string','pattern':'^(Solid|Face)[1-9][0-9]*$'}}),minItems=1,maxItems=32768),
        'facets':arr(obj({'tag':index,'nodes':arr(index,minItems=3,maxItems=3,uniqueItems=True),'cad_face_id':uid}),minItems=1,maxItems=32768)
    })}
