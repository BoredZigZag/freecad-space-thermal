# SPDX-License-Identifier: MIT OR Apache-2.0
"""Owned analytic serialization records, without acquired model fields or bytes."""
from copy import deepcopy
from itertools import product
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


def spatial_source_records(*, centered=True, marker=1, wrong_position=False, wrong_owner=False,
                           duplicate_number=False, duplicate_position=False, time_table=(), prescribed=False):
    from fcst_exchange.td_geometry import brick_payload
    from fcst_exchange.td_writer import load_payload, node_payload

    _, brick = spatial_fields()
    brick['attributes']['subdivision'][1]['boundaries'] = (0, .25, 1)
    # Independent drawing-space positions for the translated 4 x 6 x 8 mm
    # brick. Store the records in reverse order so list order cannot bind them.
    x, y, z = ((21, 23), (30.75, 33.75), (42, 46)) if centered else (
        (20, 22, 24), (30, 31.5, 36), (40, 44, 48))
    points = [(u, v, w) for w, v, u in product(z, y, x)]
    nodes = []
    for index, point in reversed(list(enumerate(points))):
        if index == 1 and duplicate_position:
            point = points[0]
        if index == 0 and wrong_position:
            point = (-10, -10, -10)
        number = 100 if index == 1 and duplicate_number else 100 + 2 * index
        fixed = prescribed and index==0
        nodes.append(node_payload('OWNED FD', number, 25 if fixed else 300, 0,
                                  'prescribed' if fixed else 'capacitive', position=point,
                                  association=None if index == 0 and wrong_owner else 1))
    brick['attributes']['references_a'] = (tuple(range(2, 2+len(nodes))), ())
    return [brick_payload(brick), *nodes, load_payload(.048, 1, marker=marker, time_table=time_table)]


def spatial_preview(root, fields=None, properties=None, *, records=None, geometry_classes=None):
    from fcst_exchange.independent_td import DwgPreview
    from fcst_exchange.source_tree import capture_project
    from fcst_exchange.td_geometry import rectangle_payload, brick_payload
    from td_fixture import drawing

    if records is None:
        rectangle, brick = fields or spatial_fields()
        records = [rectangle_payload(rectangle), brick_payload(brick)]
    (root / 'fixture.dwg').write_bytes(b'AC1032-owned')
    (root / 'fixture.tdp').write_bytes(spatial_properties() if properties is None else properties)
    return DwgPreview(capture_project(root, 'fixture.dwg'),
                      drawing(records, geometry_classes=geometry_classes))


def shared_fd_records():
    from fcst_exchange.td_geometry import rectangle_payload
    from fcst_exchange.td_writer import node_payload

    records = []
    for i, refs in enumerate(((3,4,6,7), (4,5,7,8))):
        rectangle, _ = spatial_fields()
        rectangle.update(serialized_parameters=(2,3,0,0,0,0), origin=(2*i,0,0),
                         axes=((1,0,0),(0,1,0),(0,0,1)))
        rectangle['mesh_controls'].update(values=(0,)*6, selectors=(0,1,2))
        attrs = rectangle['attributes']
        attrs['subdivision'] = tuple({'mode':0,'intervals':1,'boundaries':(0,1),'expression':expression()}
                                     for _ in range(2))
        attrs.update(references_a=(refs,()),wire_revision=55,
                     extended_attributes={'text_ids':(),'names':('Default','Default'),'name_maps':((),()),
                                          'name_lists':(('OWNED A',()),('OWNED B',()))})
        records.append(rectangle_payload(rectangle))
    for i, (y,x) in enumerate(product((0,3),(0,2,4)),1):
        owners = (1,2) if x==2 else (1,) if x==0 else (2,)
        records.append(node_payload('OWNED SHARED',i,300,0,'capacitive',position=(x,y,0),associations=owners))
    return records


FE_CLASSES = {11: ('RCLINEARTRI2','RcLinearTri2'), 12: ('RCLINEARQUAD2','RcLinearQuad2'),
              13: ('RCLINEARTETRA2','RcLinearTet2'), 14: ('RCLINEARBRICK2','RcLinearBrick2')}


def saved_element_records(*, prescribed=False):
    from fcst_exchange.td_surface import write_attributes
    from fcst_exchange.td_writer import FilerWriter, node_payload

    coordinates = ((0,0,0),(2,0,0),(2.5,3,0),(0,3,0),(4,0,0),(0,0,1),
                   (10,0,0),(12,0,0),(12,3,0),(10,3,0),(10,0,1),(12,0,1),(12,3,1),(10,3,1))
    records = []
    for i,p in enumerate(coordinates,1):
        fixed = prescribed and i==1
        records.append(node_payload('OWNED FE',i,25 if fixed else 300,0,
                                    'prescribed' if fixed else 'capacitive',position=p))
    for kind,keys in ((11,(2,5,3)),(12,(1,2,3,4)),(13,(1,2,4,6)),(14,tuple(range(7,15)))):
        writer = FilerWriter()
        b = writer.data
        if kind in (11,12):
            rectangle, _ = spatial_fields()
            attrs = rectangle['attributes']
            attrs.update(wire_revision=55,extended_attributes={'text_ids':(),'names':('Default','Default'),
                         'name_maps':((),()),'name_lists':(('',()),('',()))})
            write_attributes(writer,attrs)
        b.bl(5);b.bl(len(keys));writer.references.extend(keys)
        writer.text('OWNED element');b.put(0,1);b.bl(1)
        if kind in (11,12):
            b.bl(5);b.bl(0);b.bl(0);b.bl(1)
        else:
            b.bl(13);writer.text('OWNED solid');writer.text('Default');b.bl(0);writer.text('')
            b.bl(63);b.bl(0);b.bl(0);b.put(0,1);b.bl(0);b.bl(1);writer.expression();b.bl(1)
        records.append(writer.result(kind))
    return records
