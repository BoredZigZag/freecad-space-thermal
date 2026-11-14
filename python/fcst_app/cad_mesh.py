# SPDX-License-Identifier: MIT OR Apache-2.0
"""Convert immutable, explicitly grouped CAD meshes to owned native inputs.

This module never imports FreeCAD, discovers executables, or evaluates scripts.
CAD face, conduction element, thermal node and radiation facet IDs are distinct.
"""
from copy import deepcopy
from hashlib import sha256
import math
import uuid
import json
from importlib.resources import files

from fcst_contracts import canonical,normalize,quantity,read
from fcst_contracts.spatial import determinant
from .discretization import from_mesh,seal
from .persistence import reject,semantic_hash


def profile():
    return json.loads(files('fcst_contracts').joinpath('cad-mesher-profile.json').read_text(encoding='utf-8'))


def profile_hash():
    return sha256(canonical(profile())).hexdigest()


def _id(namespace,name):
    return str(uuid.uuid5(uuid.UUID(namespace),str(name)))


def _difference(a,b):
    return [x-y for x,y in zip(a,b)]


def triangle_area(points):
    a,b=(_difference(p,points[0]) for p in points[1:])
    return math.sqrt(sum((a[(k+1)%3]*b[(k+2)%3]-a[(k+2)%3]*b[(k+1)%3])**2 for k in range(3)))/2


def _card(value):
    allowed={'id','density','specific_heat','conductivity','temperature','thickness','tensor','rotation','valid_temperature'}
    if not isinstance(value,dict) or set(value)-allowed or not {'density','specific_heat','conductivity','temperature'}<=value.keys():
        reject('cad_material_card')
    out=normalize(deepcopy(value))
    for name,dimension in [('density','density'),('specific_heat','specific_heat'),('conductivity','conductivity')]:
        quantity(out[name],dimension,0,True)
    quantity(out['temperature'],'temperature',0,True)
    if 'thickness' in out:quantity(out['thickness'],'length',0,True)
    if ('tensor' in out)!=('rotation' in out):reject('cad_material_frame')
    return out


def prepare(source,brep,materials,boundaries=()):
    """Prepare constant-property region cards and explicit face assignments.

    Source records are copied. Orientation conversions, mesher tags and boundary
    ownership remain in the immutable receipt; original BREP bytes stay separate.
    """
    source=read('cad_mesh',source)
    # Contract JSON numbers are binary64. Mesher tags remain integer labels,
    # including after a JSON round trip; never stringify them as "1.0".
    source=deepcopy(source)
    for point in source['nodes']:point['tag']=int(point['tag'])
    for cell in source['cells']+source['facets']:
        cell['tag']=int(cell['tag']);cell['nodes']=[int(n) for n in cell['nodes']]
    if source['profile_sha256']!=profile_hash():reject('cad_mesher_profile')
    if not isinstance(brep,bytes) or sha256(brep).hexdigest()!=source['geometry']['brep_sha256']:
        reject('cad_geometry_identity')
    if source['options']['minimum_size_m']>source['options']['maximum_size_m']:reject('cad_mesh_options')
    nodes={p['tag']:p['position_m'] for p in source['nodes']}
    cells={c['tag']:c for c in source['cells']};faces={f['id']:f for f in source['geometry']['faces']}
    refs={f['ref'] for f in faces.values()}
    if (len(nodes)!=len(source['nodes']) or len(cells)!=len(source['cells']) or len(faces)!=len(source['geometry']['faces'])
            or len(refs)!=len(faces) or len({f['signature'] for f in faces.values()})!=len(faces)):
        reject('cad_mesh_identity')
    regions={c['region'] for c in cells.values()}
    if set(materials)!=regions:reject('cad_material_coverage')
    cards={name:_card(card) for name,card in materials.items()}
    initial={c['temperature']['value'] for c in cards.values()}
    if len(initial)!=1:reject('cad_initial_temperature_conflict')
    topology='tet4' if source['options']['dimension']==3 else 'tri3'
    ordered=sorted(nodes);index={tag:i for i,tag in enumerate(ordered)}
    connectivity=[];volumes=[];orientations=[];nodal=[0.0]*len(nodes)
    for cell in sorted(cells.values(),key=lambda c:c['tag']):
        if cell['topology']!=topology or len(cell['nodes'])!=(4 if topology=='tet4' else 3) or any(n not in nodes for n in cell['nodes']):
            reject('unsupported_element')
        p=[nodes[n] for n in cell['nodes']];order=list(cell['nodes'])
        if topology=='tet4':
            volume=determinant([_difference(a,p[0]) for a in p[1:]])/6
            if volume<0:order[1],order[2]=order[2],order[1];volume=-volume
        else:volume=triangle_area(p)*cards[cell['region']].get('thickness',{}).get('value',0)
        if not math.isfinite(volume) or volume<=0:reject('cad_mesh_geometry')
        orientations.append([cell['nodes'].index(n) for n in order])
        connectivity.append([index[n] for n in order]);volumes.append(volume)
        for n in order:nodal[index[n]]+=volume/len(order)
    first=cards[sorted(cards)[0]]
    value=from_mesh([nodes[n] for n in ordered],connectivity,topology=topology,volumes=volumes,nodal_volumes=nodal,
        thickness=first.get('thickness',{}).get('value',0) if topology=='tri3' else 0,
        density=first['density']['value'],specific_heat=first['specific_heat']['value'],conductivity=first['conductivity']['value'],
        temperature=next(iter(initial)))
    seed=sha256(canonical(source)).hexdigest();geometry=source['geometry'];namespace=geometry['id']
    ids={e['id'] for e in value['model']['entities']}|{m['id'] for m in value['model']['mappings']}|{p['id'] for p in value['spatial']['points']}
    remap={old:_id(namespace,seed+':'+old) for old in ids}
    def replace(v):
        if isinstance(v,dict):return {k:replace(x) for k,x in v.items()}
        if isinstance(v,list):return [replace(x) for x in v]
        return remap.get(v,v) if isinstance(v,str) else v
    value=replace(value);model=value['model'];model['project_id']=_id(namespace,'native-cad-project')
    entities=model['entities'];entities[:]=[e for e in entities if e['kind']!='material']
    frame=next(e['id'] for e in entities if e['kind']=='frame')
    point_map={tag:p for tag,p in zip(ordered,value['spatial']['points'])}
    node_values={e['id']:e for e in entities if e['kind']=='node'}
    element_values={e['id']:e for e in entities if e['kind']=='element'}
    region_ids={}
    for region,card in sorted(cards.items()):
        mid=card.get('id',_id(namespace,'material:'+region));region_ids[region]=mid
        material=dict(id=mid,kind='material',density=card['density'],specific_heat=card['specific_heat'],conductivity=card['conductivity'],
            valid_temperature=card.get('valid_temperature',[dict(value=1,unit='K'),dict(value=5000,unit='K')]))
        if 'tensor' in card:
            fid=_id(namespace,'material-frame:'+region)
            entities.append(dict(id=fid,kind='frame',origin=[dict(value=0,unit='m')]*3,rotation=card['rotation']))
            material.update(frame_id=fid,conductivity_tensor=card['tensor'])
        entities.append(material)
    for n in node_values.values():n['capacity']['value']=0
    cell_map={};owners={}
    for c,prepared,volume in zip(sorted(cells.values(),key=lambda c:c['tag']),value['spatial']['cells'],volumes):
        card=cards[c['region']];element_values[prepared['element_id']]['material_id']=region_ids[c['region']]
        cell_map[c['tag']]=prepared['element_id']
        if topology=='tri3':prepared['thickness_m']=card['thickness']['value']
        for tag in c['nodes']:
            node_values[point_map[tag]['node_id']]['capacity']['value']+=volume*card['density']['value']*card['specific_heat']['value']/len(c['nodes'])
        triples=[c['nodes']] if topology=='tri3' else [[c['nodes'][i] for i in range(4) if i!=skip] for skip in range(4)]
        for triangle in triples:owners.setdefault(frozenset(triangle),[]).append(prepared['element_id'])
    geometry_ref=dict(path='geometry/'+namespace+'.brep',sha256=geometry['brep_sha256'],byte_length=len(brep))
    entities.append(dict(id=namespace,kind='geometry',frame_id=frame,artifact=geometry_ref,revision=geometry['revision']))
    for f in faces.values():entities.append(dict(id=f['id'],kind='face',geometry_id=namespace,persistent_ref=f['ref'],
        signature=f['signature'],area=dict(value=f['area_m2'],unit='m2')))
    facets=[];by_face={id_:[] for id_ in faces};tags=set();facet_keys=set()
    for facet in sorted(source['facets'],key=lambda f:f['tag']):
        key=frozenset(facet['nodes'])
        if (facet['tag'] in tags or key in facet_keys or facet['cad_face_id'] not in faces or any(n not in nodes for n in facet['nodes'])
                or len(owners.get(key,[]))!=1):reject('cad_boundary_mapping')
        tags.add(facet['tag']);facet_keys.add(key)
        area=triangle_area([nodes[n] for n in facet['nodes']])
        if not math.isfinite(area) or area<=0:reject('cad_mesh_geometry')
        entry=dict(id=_id(namespace,seed+':radiation-facet:'+str(facet['tag'])),cad_face_id=facet['cad_face_id'],
            point_ids=[point_map[n]['id'] for n in facet['nodes']],thermal_node_ids=[point_map[n]['node_id'] for n in facet['nodes']],
            conduction_element_id=owners[key][0],area_m2=area,source_tag=facet['tag'])
        facets.append(entry);by_face[facet['cad_face_id']].append(entry)
    if any(not group for group in by_face.values()):reject('cad_unassigned_face')
    if {frozenset(f['nodes']) for f in source['facets']}!={key for key,group in owners.items() if len(group)==1}:
        reject('cad_boundary_coverage')
    conditions=deepcopy(list(boundaries));prescribed={};assignments=[]
    for i,boundary in enumerate(conditions):
        if not isinstance(boundary,dict) or boundary.get('face_id') not in by_face:reject('cad_boundary_selection')
        group=by_face[boundary['face_id']];kind=boundary.get('kind')
        if kind not in ('temperature','total_power','surface_flux','convection'):reject('unsupported_boundary')
        expected={'face_id','kind','coefficient_W_per_m2_K','ambient_temperature'} if kind=='convection' else {'face_id','kind','value'}
        if set(boundary)!=expected:reject('cad_boundary_card')
        if kind=='temperature':
            t=quantity(normalize(boundary['value']),'temperature',0)
            for facet in group:
                for id_ in facet['thermal_node_ids']:
                    if id_ in prescribed and prescribed[id_]!=t:reject('cad_boundary_conflict')
                    prescribed[id_]=t;node_values[id_].update(classification='prescribed',capacity=dict(value=0,unit='J/K'),temperature=dict(value=t,unit='K'))
        else:
            area=math.fsum(f['area_m2'] for f in group);power=0
            if kind=='convection':
                h=boundary['coefficient_W_per_m2_K']
                if type(h) not in (int,float) or not math.isfinite(h) or h<0:reject('cad_boundary_card')
                ambient=quantity(normalize(boundary['ambient_temperature']),'temperature',0)
            else:amount=quantity(normalize(boundary['value']),'power' if kind=='total_power' else 'flux')
            native=[]
            for facet in group:
                identifier=_id(namespace,seed+':boundary:'+str(i)+':'+facet['id']);native.append(identifier)
                v=h if kind=='convection' else amount*facet['area_m2']/area if kind=='total_power' else amount
                value['spatial']['surfaces'].append(dict(id=identifier,kind={'total_power':'power','surface_flux':'flux','convection':'convection'}[kind],
                    point_ids=facet['point_ids'],value_SI=v,ambient_K=ambient if kind=='convection' else 0))
                if kind!='convection':power+=v if kind=='total_power' else v*facet['area_m2']
            assignments.append(dict(face_id=boundary['face_id'],kind=kind,surface_ids=native,mesh_area_m2=area,
                integrated_power_W=power if kind!='convection' else None))
    source_revision=sha256(canonical(dict(source=source,materials=cards,boundaries=conditions))).hexdigest()
    entries=[dict(namespace='cad-face',handle=f['ref'],entity_id=f['id']) for f in faces.values()]
    entries += [dict(namespace='gmsh-element',handle=str(tag),entity_id=id_) for tag,id_ in sorted(cell_map.items())]
    entries += [dict(namespace='gmsh-node',handle=str(tag),entity_id=p['node_id']) for tag,p in sorted(point_map.items())]
    model['source_maps']=[dict(id=_id(namespace,'mesher-source:'+source_revision),version='1.0.0',source_revision=source_revision,
        source_tool='FreeCAD FEM / Gmsh',source_version=source['mesher_version'],entries=entries)]
    model['assumptions']+=['CAD-group identities are explicit; radiation facets describe geometry only']
    value['model']=read('model',model);value=seal(value)
    receipt=dict(contract_version='1.0.0',kind='fcst-cad-prepared',source=source,materials=cards,boundaries=conditions,
        source_revision=source_revision,model_hash=semantic_hash(value['model']),mesh_revision=value['spatial']['mesh_revision'],
        node_map=[dict(source_tag=tag,point_id=p['id'],thermal_node_id=p['node_id']) for tag,p in sorted(point_map.items())],
        element_map=[dict(source_tag=c['tag'],element_id=cell_map[c['tag']],permutation=order) for c,order in zip(sorted(cells.values(),key=lambda c:c['tag']),orientations)],
        radiation_facets=facets,assignments=assignments)
    return value,receipt


def validate_receipt(receipt,brep):
    if not isinstance(receipt,dict) or receipt.get('kind')!='fcst-cad-prepared':reject('cad_receipt')
    value,expected=prepare(receipt['source'],brep,receipt['materials'],receipt['boundaries'])
    if expected!=receipt:reject('cad_receipt')
    return value


def reconcile(receipt,geometry):
    """Any unaccepted geometry revision, split/merge/reorder/delete stays invalid."""
    if receipt['source']['geometry']!=geometry:reject('attachment_reassignment_required')
    return True


def synchronize(previous, previous_brep, source, brep, *, region_map=None, face_map=None,
                previous_model=None):
    """Regenerate a prepared CAD project from a fresh mesh and accepted mappings."""
    old_value = validate_receipt(previous, previous_brep)
    if previous_model is not None and old_value['model'] != previous_model:
        reject('td_cad_sync_project_changed')
    source = read('cad_mesh', source)
    old_geometry = previous['source']['geometry']
    geometry = source['geometry']
    if geometry['id'] != old_geometry['id']:
        reject('cad_sync_geometry_identity')
    if source['options']['dimension'] != previous['source']['options']['dimension']:
        reject('cad_sync_geometry_dimension')

    def content(value):
        return {key: item for key, item in value.items() if key != 'revision'}

    unchanged_geometry = content(old_geometry) == content(geometry)
    new_regions = {c['region'] for c in source['cells']}
    if unchanged_geometry and new_regions == previous['materials'].keys() and region_map is None and face_map is None:
        source['geometry']['revision'] = old_geometry['revision']
        if source == previous['source'] and brep == previous_brep:
            return old_value, previous
        materials, boundaries = previous['materials'], previous['boundaries']
    else:
        source['geometry']['revision'] = old_geometry['revision'] + int(not unchanged_geometry)

        def transfer(mapping, old, new):
            if (not isinstance(mapping, dict) or mapping.keys() != old
                    or any(not isinstance(target, str) for target in mapping.values())
                    or set(mapping.values()) != new or len(mapping) != len(new)):
                reject('attachment_reassignment_required')
            return mapping

        regions = transfer(region_map, set(previous['materials']), new_regions)
        assigned_faces = {b['face_id'] for b in previous['boundaries']}
        new_faces = {f['id'] for f in geometry['faces']}
        if (not isinstance(face_map, dict) or face_map.keys() != assigned_faces
                or any(not isinstance(target, str) for target in face_map.values())
                or not set(face_map.values()) <= new_faces or len(set(face_map.values())) != len(face_map)):
            reject('attachment_reassignment_required')
        materials = {target: previous['materials'][old] for old, target in regions.items()}
        boundaries = [{**entry, 'face_id': face_map[entry['face_id']]} for entry in previous['boundaries']]

    return prepare(source, brep, materials, boundaries)


def synchronize_project(saved, source, brep, *, region_map=None, face_map=None):
    """Prepare a new portable project from a validated CAD project and mesh."""
    from fcst_contracts import loads

    geometry = [row for row in saved.model['entities'] if row['kind'] == 'geometry']
    if len(geometry) != 1 or 'cad-mesh/prepared.json' not in saved.files:
        reject('td_cad_sync_project')
    previous = loads(saved.files['cad-mesh/prepared.json'])
    previous_brep = saved.files[geometry[0]['artifact']['path']]
    value, receipt = synchronize(previous, previous_brep, source, brep,
                                 region_map=region_map, face_map=face_map, previous_model=saved.model)
    report = {'status': 'reused' if receipt is previous else 'synchronized',
              'geometry_changed': receipt['source']['geometry'] != previous['source']['geometry'],
              'mesh_changed': receipt['mesh_revision'] != previous['mesh_revision']}
    return (saved if receipt is previous else _package(value, receipt, brep)), report


def package(receipt,brep):
    """Close original geometry, assignments and their re-creatable receipt."""
    return _package(validate_receipt(receipt,brep),receipt,brep)


def _package(value,receipt,brep):
    from .discretization import assignment_payload
    from .persistence import Package,encode
    namespace=value['model']['project_id']
    mesh=next(e['artifact'] for e in value['model']['entities'] if e['kind']=='mesh')
    geometry=next(e['artifact'] for e in value['model']['entities'] if e['kind']=='geometry')
    artifacts=[(_id(namespace,'conduction-input'),'conduction_input',mesh['path'],assignment_payload(value),[]),
        (_id(namespace,'geometry'),'geometry',geometry['path'],brep,[]),
        (_id(namespace,'cad-receipt'),'evidence','cad-mesh/prepared.json',encode(receipt),[]),
        (_id(namespace,'spatial-input'),'evidence','spatial-inputs/cad.json',encode(value),[])]
    return Package.create(value['model'],artifacts)
