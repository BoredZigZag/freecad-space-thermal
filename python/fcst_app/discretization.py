# SPDX-License-Identifier: MIT OR Apache-2.0
"""Self-contained SI spatial input and bounded structured verification meshes.

These generators cover Cartesian primitives. CAD tessellation belongs to the
qualified host mesher adapter; generated points never inherit CAD face identity.
"""
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import math
import struct
import uuid

from fcst_contracts import canonical, loads, normalize, read, validate
from .persistence import encode

NAMESPACE = uuid.UUID('59071510-6575-494d-b698-3c7dd7dc28de')


def read_input(value):
    """Validate the packaged closed v2 schema and canonical model without executing code."""
    from importlib.resources import files
    schema=loads(files('fcst_contracts').joinpath('thermal-input-v2.json').read_bytes())
    value=loads(encode(value))
    validate(schema,value)
    value=normalize(value)
    value['model']=read('model',value['model'])
    if value['spatial']['mesh_revision']!=sha256(b'FCST-spatial-mesh-v1\0'+mesh_payload(value['spatial'])).hexdigest():
        raise ValueError('spatial_mesh_revision')
    raw=assignment_payload(value)
    meshes=[e for e in value['model']['entities'] if e['kind']=='mesh' and e['role']=='conduction']
    if len(meshes)!=1 or meshes[0]['artifact']['sha256']!=sha256(raw).hexdigest() or meshes[0]['artifact']['byte_length']!=len(raw):
        raise ValueError('spatial_mesh_artifact')
    return value


def identity(name):
    return str(uuid.uuid5(NAMESPACE, str(name)))


def mesh_payload(spatial):
    return canonical({key: spatial[key] for key in ('points', 'cells')})


def assignment_payload(value):
    return canonical({key:value[key] for key in ('spatial','material_laws','node_storage')})


def decode_assignment(raw):
    """Bounded inverse of the existing typed canonical encoding for manifest v3.

    No object construction hooks or executable formats are accepted. Exact
    re-encoding rejects alternate representations, key order and trailing data.
    """
    if not isinstance(raw,bytes) or len(raw)>1048576:raise ValueError('spatial_payload_limit')
    offset=0;items=0
    def parse(depth=0):
        nonlocal offset,items
        items+=1
        if depth>64 or items>100000 or offset>=len(raw):raise ValueError('spatial_payload')
        tag=raw[offset:offset+1];offset+=1
        if tag==b'n':return None
        if tag==b't':return True
        if tag==b'f':return False
        if tag==b'd':
            part=raw[offset:offset+16];offset+=16
            if len(part)!=16:raise ValueError('spatial_payload')
            value=struct.unpack('>d',bytes.fromhex(part.decode('ascii')))[0]
            if not math.isfinite(value):raise ValueError('spatial_payload')
            return value
        if tag not in (b's',b'a',b'o'):raise ValueError('spatial_payload')
        end=raw.find(b':',offset,offset+9)
        if end<0 or not raw[offset:end].isdigit():raise ValueError('spatial_payload')
        count=int(raw[offset:end]);offset=end+1
        if count>1048576 or (tag!=b's' and count>100000):raise ValueError('spatial_payload_limit')
        if tag==b's':
            part=raw[offset:offset+count];offset+=count
            if len(part)!=count:raise ValueError('spatial_payload')
            return part.decode('utf-8')
        if tag==b'a':return [parse(depth+1) for _ in range(count)]
        result={}
        for _ in range(count):
            key=parse(depth+1)
            if not isinstance(key,str) or key in result:raise ValueError('spatial_payload')
            result[key]=parse(depth+1)
        return result
    try:value=parse()
    except (UnicodeError,struct.error,OverflowError):raise ValueError('spatial_payload') from None
    if offset!=len(raw) or canonical(value)!=raw:raise ValueError('spatial_payload')
    return value


def seal(value):
    """Bind explicit ordered connectivity to both mesh revision and model artifact.

    Re-sealing is an explicit preparation action, never a result-validity check.
    """
    value = deepcopy(value)
    value['spatial']['mesh_revision'] = sha256(b'FCST-spatial-mesh-v1\0' + mesh_payload(value['spatial'])).hexdigest()
    raw=assignment_payload(value)
    meshes = [e for e in value['model']['entities'] if e['kind'] == 'mesh' and e['role'] == 'conduction']
    if len(meshes) != 1:
        raise ValueError('spatial_mesh_count')
    meshes[0]['artifact'] = dict(path='meshes/conduction.fcstc', sha256=sha256(raw).hexdigest(), byte_length=len(raw))
    return value


def _number(value, positive=True):
    if type(value) not in (int, float) or not math.isfinite(value) or (value <= 0 if positive else value < 0):
        raise ValueError('spatial_parameter')
    return float(value)


def _count(n):
    if type(n) is not int or not 1 <= n <= 32:
        raise ValueError('spatial_subdivisions')
    return n


@dataclass(frozen=True)
class MeshRegion:
    """A disconnected structured mesh region with one material."""

    prefix: str
    topology: str
    positions: list
    connectivity: list
    volumes: list
    nodal_volumes: list
    thickness: float
    material: dict

    def identifier(self, name):
        return identity(self.prefix + name)


def _quantity(value, unit):
    return dict(value=value, unit=unit)


def from_regions(regions, *, temperature, prescribed=None, rotation=None, prefix='',
                 source_maps=(), assumptions=(), limitations=(), material_frames=(),
                 material_laws=(), tensor_laws=()):
    """Prepare disconnected regions as a single mesh with explicit material assignments.

    The native reader independently recomputes geometry, mappings and capacity.
    Point positions are global metres. Prescribed indices address the flattened points.
    """
    q = _quantity
    frame, mesh = (identity(prefix + n) for n in ('frame', 'mesh'))
    mesh_entities = [
        dict(id=frame, kind='frame', origin=[q(0, 'm')]*3, rotation=rotation or [[1,0,0],[0,1,0],[0,0,1]]),
        dict(id=mesh, kind='mesh', frame_id=frame, role='conduction', artifact=dict(path='meshes/conduction.json', sha256='0'*64, byte_length=0)),
    ]
    entities, points, cells, mappings, materials = [], [], [], [], {}
    types = dict(tri3='triangle', quad4='quadrilateral', tet4='tetrahedron', hex8='hexahedron')
    prescribed = prescribed or {}
    for region in regions:
        positions, connectivity = region.positions, region.connectivity
        if (region.topology not in types or len(points) + len(positions) > 16384
                or len(cells) + len(connectivity) > 32768):
            raise ValueError('unsupported_element')
        if len(region.volumes) != len(connectivity) or len(region.nodal_volumes) != len(positions):
            raise ValueError('spatial_shape')
        submodel = region.identifier('submodel')
        entities.append(dict(id=submodel, kind='submodel'))
        material = region.material
        material_id = material['id']
        if material_id not in materials:
            materials[material_id] = material
            entities.append(material)
        elif materials[material_id] != material:
            raise ValueError('spatial_material_identity')
        rho = material['density']['value']
        cp = material['specific_heat']['value']
        point_ids = [region.identifier(f'point-{i}') for i in range(len(positions))]
        node_ids = [region.identifier(f'node-{i}') for i in range(len(positions))]
        start = len(points)
        for i, (p, v) in enumerate(zip(positions, region.nodal_volumes)):
            index = start + i
            t = prescribed.get(index, temperature(index, p) if callable(temperature) else temperature)
            entities.append(dict(id=node_ids[i], kind='node', submodel_id=submodel,
                classification='prescribed' if index in prescribed else 'capacitive', temperature=q(t,'K'),
                capacity=q(0 if index in prescribed else _number(v)*rho*cp,'J/K')))
            points.append(dict(id=point_ids[i], node_id=node_ids[i], position=list(p)))
        for i, (indices, volume) in enumerate(zip(connectivity, region.volumes)):
            element = region.identifier(f'element-{i}')
            entities.append(dict(id=element, kind='element', mesh_id=mesh, material_id=material_id, frame_id=frame,
                                 volume=_number(volume), topology=types[region.topology]))
            cells.append(dict(element_id=element, topology=region.topology,
                              point_ids=[point_ids[j] for j in indices], thickness_m=region.thickness))
            provenance = sha256(canonical(list(indices))).hexdigest()
            area = (volume/region.thickness if region.thickness else volume**(2/3)) / len(indices)
            for j in indices:
                mappings.append(dict(id=region.identifier(f'map-{i}-{j}'), from_id=element, to_id=node_ids[j],
                                     weight=1/len(indices), area=q(area,'m2'), provenance=provenance))
    entities[1:1] = [*mesh_entities, *material_frames]
    model = read('model', dict(contract_version='1.0.0', minimum_reader='1.0.0',
        project_id=identity(prefix + 'project'), revision=0, entities=entities,
        assumptions=['Fixed geometry; reference density; row-sum storage', *assumptions],
        limitations=['First-order spatial profile', *limitations], source_maps=list(source_maps),
        mappings=mappings, attachments=[], audit={'timestamp':'2026-01-01'}, gui={'selection':[]}))
    spatial = dict(length_unit='m', mesh_revision='0'*64, points=points, cells=cells, surfaces=[], contacts=[])
    if tensor_laws:
        spatial['tensor_laws'] = list(tensor_laws)
    return seal(dict(contract_version='2.0.0', model=model, material_laws=list(material_laws), node_storage=[],
                     spatial=spatial))


def from_mesh(positions, connectivity, *, topology, volumes, nodal_volumes, thickness=0,
              density=1, specific_heat=1, conductivity=1, temperature=300,
              prescribed=None, tensor=None, rotation=None):
    """Prepare a uniform-material primitive with explicit analytic cell/nodal volumes."""
    q = _quantity
    rho, cp, k = (_number(x) for x in (density, specific_heat, conductivity))
    material = dict(id=identity('material'), kind='material', density=q(rho,'kg/m3'),
                    specific_heat=q(cp,'J/(kg*K)'), conductivity=q(k,'W/(m*K)'),
                    valid_temperature=[q(1,'K'),q(5000,'K')])
    if tensor is not None:
        material.update(conductivity_tensor=deepcopy(tensor), frame_id=identity('frame'))
    return from_regions([MeshRegion('', topology, positions, connectivity, volumes, nodal_volumes, thickness, material)],
                        temperature=temperature, prescribed=prescribed, rotation=rotation)


def plate(nx=1, ny=1, *, length=1, width=1, thickness=0.1, topology='tri3', **material):
    nx, ny = _count(nx), _count(ny)
    length, width, thickness = (_number(v) for v in (length, width, thickness))
    if topology not in ('tri3','quad4'):
        raise ValueError('unsupported_element')
    positions = [[length*i/nx,width*j/ny,0] for j in range(ny+1) for i in range(nx+1)]
    cells, volumes = [], []
    for j in range(ny):
        for i in range(nx):
            a=j*(nx+1)+i; quad=[a,a+1,a+nx+2,a+nx+1]
            for c in ([quad] if topology=='quad4' else [[quad[0],quad[1],quad[2]],[quad[0],quad[2],quad[3]]]):
                cells.append(c);volumes.append(length*width*thickness/(nx*ny*(1 if topology=='quad4' else 2)))
    nodal=[0.0]*len(positions)
    for c,v in zip(cells,volumes):
        for i in c:nodal[i]+=v/len(c)
    return from_mesh(positions,cells,topology=topology,volumes=volumes,nodal_volumes=nodal,thickness=thickness,**material)


def brick(nx=1, ny=1, nz=1, *, length=1, width=1, height=1, topology='tet4', **material):
    nx,ny,nz=(_count(n) for n in (nx,ny,nz))
    length,width,height=(_number(v) for v in (length,width,height))
    if topology not in ('tet4','hex8') or (nx+1)*(ny+1)*(nz+1)>16384:
        raise ValueError('spatial_subdivisions')
    positions=[[length*i/nx,width*j/ny,height*k/nz] for k in range(nz+1) for j in range(ny+1) for i in range(nx+1)]
    index=lambda i,j,k:k*(ny+1)*(nx+1)+j*(nx+1)+i
    # Six positively oriented tetrahedra sharing the 0-6 body diagonal.
    splits=[[0,1,2,6],[0,2,3,6],[0,3,7,6],[0,7,4,6],[0,4,5,6],[0,5,1,6]]
    cells,volumes=[],[]
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                cube=[index(i,j,k),index(i+1,j,k),index(i+1,j+1,k),index(i,j+1,k),index(i,j,k+1),index(i+1,j,k+1),index(i+1,j+1,k+1),index(i,j+1,k+1)]
                for c in ([cube] if topology=='hex8' else [[cube[p] for p in split] for split in splits]):
                    cells.append(c);volumes.append(length*width*height/(nx*ny*nz*(1 if topology=='hex8' else 6)))
    nodal=[0.0]*len(positions)
    for c,v in zip(cells,volumes):
        for i in c:nodal[i]+=v/len(c)
    return from_mesh(positions,cells,topology=topology,volumes=volumes,nodal_volumes=nodal,**material)


def fd_rod(n=8, *, length=1, area=1, density=1, specific_heat=1, conductivity=1,
           left_temperature=300, right_temperature=400, initial_temperature=300):
    """Cell-centred conservative FD rod, with half-cell boundary distances.

    Uniform isotropic constant properties; nonlinear/spatial materials use FE.
    """
    n=_count(n);length,area,rho,cp,k=(_number(v) for v in (length,area,density,specific_heat,conductivity))
    q=lambda v,u:dict(value=v,unit=u)
    submodel=identity('fd-submodel');entities=[dict(id=submodel,kind='submodel')]
    nodes=[identity(f'fd-node-{i}') for i in range(n+2)];dx=length/n
    for i,node in enumerate(nodes):
        prescribed=i in (0,n+1)
        entities.append(dict(id=node,kind='node',submodel_id=submodel,classification='prescribed' if prescribed else 'capacitive',
            temperature=q(left_temperature if i==0 else right_temperature if i==n+1 else initial_temperature,'K'),
            capacity=q(0 if prescribed else rho*cp*area*dx,'J/K')))
    for i in range(n+1):
        entities.append(dict(id=identity(f'fd-link-{i}'),kind='conductor',from_node_id=nodes[i],to_node_id=nodes[i+1],
                             conductance=q(k*area/(dx/2 if i in (0,n) else dx),'W/K')))
    model=read('model',dict(contract_version='1.0.0',minimum_reader='1.0.0',project_id=identity('fd-project'),revision=0,entities=entities,
        assumptions=['Cell-centred FD; fixed geometry'],limitations=['Constant isotropic rod'],source_maps=[],mappings=[],attachments=[],audit={'timestamp':'2026-01-01'},gui={'selection':[]}))
    return dict(contract_version='1.0.0',model=model,material_laws=[],node_storage=[])
