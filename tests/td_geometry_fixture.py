# SPDX-License-Identifier: MIT OR Apache-2.0
"""Owned analytic serialization records, without acquired model fields or bytes."""
from copy import deepcopy
from fcst_exchange.td_surface import ATTRIBUTE_LAYOUT,SOLID_LAYOUT


def expression():
    return {'selectors':(-1,0,0),'text':'','alternate':'',
            'table':{'column_a':(),'column_b':(),'enabled':()},'mode':0,'dimension':-1,'dimensional':False,
            'dimension_table':{'column_a':(),'column_b':(),'enabled':()}}


def mesh():
    return {'values':(1,2,3,4,5,6),'selectors':(0,1,2),'expressions':tuple(expression() for _ in range(6))}


def value(kind):
    if kind=='integer':return 2
    if kind=='double':return 1.25
    if kind=='flag':return False
    if kind=='text':return 'OWNED surface \u03b1'
    if kind=='expression':return expression()
    if kind=='breakdown':return {'mode':0,'intervals':2,'boundaries':(0,.5,1),'expression':expression()}
    if kind=='mesh_controls':return mesh()
    if kind=='advection':return {'selectors':(1,2),'values':(.25,.75),'expressions':(expression(),)}
    if kind in {'handles','texts','expressions','integer_lists','text_pair_lists'}:return ()
    if kind=='integers':return (0,1,2)
    if kind=='doubles':return (.25,.5,.75)
    if kind=='text_pairs':return (('OWNED key','OWNED value'),)
    raise AssertionError('unhandled owned fixture field')


def groups(layout):
    return {name:value(kind) if count==1 else tuple(value(kind) for _ in range(count)) for name,kind,count in layout}


def rectangle_fields():
    attrs=groups(ATTRIBUTE_LAYOUT)
    attrs.update(groups=(('MAIN',1),),legacy_names=('',''),legacy_selectors=(0,0),names=('OWNED A','OWNED B',''))
    attrs['name_lists']=(('OWNED first','OWNED second'),())
    attrs['expressions_a'][0]['text']='SOURCE_EXPRESSION';attrs['flag_j']=True
    return {'serialized_parameters':(0,1,0,2,0,0),'origin':(1,2,3),'axes':((1,0,0),(0,1,0),(0,0,1)),
            'attributes':attrs,'additional_parameters':(0,0,0,0,0,0),'mesh_controls':mesh(),
            'parameter_expressions':tuple(expression() for _ in range(12)),'entity_flags':1}


def brick_fields():
    attrs=groups(SOLID_LAYOUT);attrs['parameter_expressions']=tuple(expression() for _ in range(12))
    attrs['name_maps']=((('OWNED A','OWNED B'),),())
    attrs['index_lists']=((1,2),(3,4,5));attrs['face_names']=tuple((f'OWNED face {i}',) for i in range(6))
    return {'serialized_parameters':(0,1,0,2,0,3,0,0,0,0,0,0),'origin':(1,2,3),'axes':((1,0,0),(0,1,0),(0,0,1)),
            'attributes':attrs}


def rectangle_boundary_fields():
    fields = rectangle_fields()
    fields.update(serialized_parameters=(4, 6, 0, 0, 0, 0), origin=(10, 20, 30),
                  axes=((0, 1, 0), (-1, 0, 0), (0, 0, 1)),
                  parameter_expressions=tuple(expression() for _ in range(2)))
    fields['mesh_controls'].update(values=(5, 6, 7, 90, 90, 0), selectors=(2, 0, 1))
    fields['attributes']['subdivision'][0]['boundaries'] = (0, .25, 1)
    return fields


def brick_boundary_fields():
    fields = brick_fields()
    fields.update(serialized_parameters=(4, 6, 8, 0, 0, 0, 0, 0, 0, 0, 0, 0), origin=(20, 30, 40))
    fields['attributes']['parameter_expressions'] = tuple(expression() for _ in range(3))
    fields['attributes']['mesh_controls'].update(values=(0, 0, 0, 0, 0, 0))
    return fields


def spatial_fields():
    rectangle, brick = rectangle_boundary_fields(), brick_boundary_fields()
    surface = rectangle['attributes']
    surface.update(primary_selector=1, property_names=('OWNED sheet', 'Default'),
                   property_scalars=(2, 19), property_label='Default', property_value=0,
                   selectors_a=(0,) * 6, selectors_b=(0, 0), selectors_f=(0,) * 9, selectors_i=(0, 0),
                   values_g=(1,) * 4, name_lists=((), ()), name_maps=((), ()))
    surface['expressions_a'][0]['text'] = ''
    brick['attributes'].update(selector_a=0, selector_b=1, selector_c=0, selector_d=0,
                               scalars_a=(1,) * 4, names_a=('OWNED submodel', 'owned solid', 'OWNED optical'),
                               advection={'selectors': (0, 0, 0), 'values': (0, 0, 0),
                                          'expressions': tuple(expression() for _ in range(3))})
    return rectangle, brick


def spatial_properties():
    from fcst_exchange.td_property_laws import write_laws

    materials = [
        {'name': 'OWNED SHEET', 'scalars': {'CONDUCT': 4, 'DENSITY': 20, 'SPECHEAT': 30},
         'aggregate': {'scalars': {'WEIGHTTYPE': 1},
                       'components': [{'material': 'OWNED inactive', 'scalars': {'WEIGHT': 0}}]}},
        {'name': 'OWNED solid', 'scalars': {'CONDUCT': 7, 'DENSITY': 10, 'SPECHEAT': 50, 'EFFECTIVEEMISS': .4}},
    ]
    return write_laws({'profile': 'td-property-laws/1', 'kind': 'tdp',
                       'entries': [{**entry, 'tables': {}, 'vectors': {}} for entry in materials]})


def spatial_law_properties():
    from fcst_exchange.td_property_laws import write_laws

    entries = [
        {'name': 'OWNED SHEET', 'scalars': {'CONDUCT': 4, 'DENSITY': 20, 'SPECHEAT': 30, 'USEANISO': 1,
                                         'CONDUCTY': 8, 'CONDUCTZ': 9, 'USEVARCONDUCT': 1, 'USEVARSPECHEAT': 1},
         'tables': {'VARCONDUCT': [[250, 2], [350, 6], [450, 14]], 'VARSPECHEAT': [[250, 25], [450, 45]]}},
        {'name': 'OWNED solid', 'scalars': {'CONDUCT': 7, 'DENSITY': 10, 'SPECHEAT': 50, 'USEVARCONDUCT': 1},
         'tables': {'VARCONDUCT': [[250, 6], [450, 10]]}},
    ]
    return write_laws({'profile': 'td-property-laws/1', 'kind': 'tdp',
                       'entries': [{'vectors': {}, **entry} for entry in entries]})


def spatial_preview(root, fields=None, properties=None):
    from fcst_exchange.independent_td import DwgPreview
    from fcst_exchange.source_tree import capture_project
    from fcst_exchange.td_geometry import rectangle_payload, brick_payload
    from td_fixture import drawing

    rectangle, brick = fields or spatial_fields()
    (root / 'fixture.dwg').write_bytes(b'AC1032-owned')
    (root / 'fixture.tdp').write_bytes(spatial_properties() if properties is None else properties)
    return DwgPreview(capture_project(root, 'fixture.dwg'),
                      drawing([rectangle_payload(rectangle), brick_payload(brick)]))
