# SPDX-License-Identifier: MIT OR Apache-2.0
"""Direct typed TD inventory. Undecoded objects remain explicit model holds."""
from dataclasses import dataclass,field
from collections import Counter
from .core import ExchangeError
from .dwg_native import _one
from .td_node import decode_node
from .td_conductor import decode_conductor
from .td_load import decode_load
from .td_mesher import MESHERS, decode_mesher
from .td_geometry import (conic_decoder, decode_rectangle, decode_brick, decode_disk, decode_cylinder, decode_sphere,
                          decode_solid_cone, decode_solid_ellipsoid, decode_linear_brick, decode_linear_wedge,
                          decode_linear_tetra, decode_linear_pyramid, decode_linear_tri, decode_linear_quad,
                          decode_quadratic_tri, decode_quadratic_quad, decode_polygon_mesh, decode_legacy_tri,
                          decode_legacy_quad, solid_decoder, LinearBrickPayload, LinearWedgePayload,
                          LinearTetraPayload, QuadraticBrickPayload, QuadraticWedgePayload,
                          QuadraticTetraPayload, QuadraticPyramidPayload)

CONIC_CLASSES = {
    'RcCone': 'cone', 'RcCylinder': 'cylinder', 'RcEllipse': 'ellipse', 'RcEllipsoid': 'ellipsoid',
    'RcEllipticCone': 'elliptic-cone', 'RcEllipticCylinder': 'elliptic-cylinder',
    'RcOffsetParaboloid': 'offset-paraboloid', 'RcOgive': 'ogive', 'RcParabolicTrough': 'parabolic-trough',
    'RcParaboloid': 'paraboloid', 'RcScarfedCone': 'scarfed-cone', 'RcScarfedCylinder': 'scarfed-cylinder',
    'RcSphere': 'sphere', 'RcTorus': 'torus',
}

WRAPPED_ELEMENTS = {
    'RcLinearTri': ('RCLINEARTRI', decode_legacy_tri),
    'RcLinearQuad': ('RCLINEARQUAD', decode_legacy_quad),
    'RcLinearTet': ('RCLINEARTETRA', solid_decoder(LinearTetraPayload, legacy=True)),
    'RcLinearWedge': ('RCLINEARWEDGE', solid_decoder(LinearWedgePayload, legacy=True)),
    'RcLinearBrick': ('RCLINEARBRICK', solid_decoder(LinearBrickPayload, legacy=True)),
    'RcQuadraticTet': ('RCQUADRATICTETRA', solid_decoder(QuadraticTetraPayload)),
    'RcQuadraticPyramid': ('RCQUADRATICPYRAMID', solid_decoder(QuadraticPyramidPayload)),
    'RcQuadraticWedge': ('RCQUADRATICWEDGE', solid_decoder(QuadraticWedgePayload)),
    'RcQuadraticBrick': ('RCQUADRATICBRICK', solid_decoder(QuadraticBrickPayload)),
}

DECODERS={'RcNode':decode_node,'RcConductor':decode_conductor,'RcHeatLoad':decode_load,'RcRectangle':decode_rectangle,
          'RcFdBrick':decode_brick,'RcDisk':decode_disk,'RcFdSolidCylinder':decode_cylinder,'RcFdSolidSphere':decode_sphere,
          'RcFdSolidCone':decode_solid_cone,'RcFdSolidEllipsoid':decode_solid_ellipsoid,
          'RcLinearBrick2':decode_linear_brick,'RcLinearWedge2':decode_linear_wedge,
          'RcLinearTet2':decode_linear_tetra,'RcLinearPyramid2':decode_linear_pyramid,
          'RcLinearTri2':decode_linear_tri,'RcLinearQuad2':decode_linear_quad,'RcMeshFD':decode_polygon_mesh,
          'RcQuadraticTri':decode_quadratic_tri,'RcQuadraticQuad':decode_quadratic_quad,
          **{name:decoder for name,(_,decoder) in WRAPPED_ELEMENTS.items()},
          **{name:conic_decoder(shape) for name,shape in CONIC_CLASSES.items()}}
GEOMETRY_CLASSES={'RcRectangle':'RCRECTANGLE','RcFdBrick':'RCTD_FDBRICK','RcDisk':'RCDISK',
                  'RcFdSolidCylinder':'RCTD_FDSOLIDCYLINDER','RcFdSolidSphere':'RCTD_FDSOLIDSPHERE',
                  'RcFdSolidCone':'RCTD_FDSOLIDCONE','RcFdSolidEllipsoid':'RCTD_FDSOLIDELLIPSOID',
                  'RcLinearBrick2':'RCLINEARBRICK2','RcLinearWedge2':'RCLINEARWEDGE2',
                  'RcLinearTet2':'RCLINEARTETRA2','RcLinearPyramid2':'RCLINEARPYRAMID2',
                  'RcLinearTri2':'RCLINEARTRI2','RcLinearQuad2':'RCLINEARQUAD2','RcMeshFD':'RCPOLYGON',
                  'RcQuadraticTri':'RCQUADRATICTRI','RcQuadraticQuad':'RCQUADRATICQUAD',
                  **{name:dxf for name,(dxf,_) in WRAPPED_ELEMENTS.items()},
                  **{name:name.upper() for name in CONIC_CLASSES}}
GEOMETRY_DXF_ALIASES = {'RcParabolicTrough': {'RCPARABTROUGH'}, 'RcMeshFD': {'TD_MESH', 'RCMESHFD'}}
UNMAPPED_GEOMETRY_CLASSES = {'RcPolygon'}


@dataclass(frozen=True)
class ThermalInventory:
    payloads:tuple=field(repr=False)
    records:tuple

    @property
    def report(self):
        counts=Counter(row['status'] for row in self.records)
        return {'profile':'td-typed-payloads/1','decoded_objects':counts['payload-decoded'],
                'partial_objects':counts['partial-payload'],
                'retained_objects':counts['retained-opaque']+counts['partial-payload'],'records':list(self.records),
                'native_ready':False,'qualified':False,
                'limitations':['full_model_dependency_and_semantic_closure_unqualified']}


def decode_drawing(snapshot, *, handles=None):
    classes={c['number']:c for c in snapshot.native['classes']};names={k:c['cppname'] for k,c in classes.items()}
    standards={_one(row,'handle')[2]:row for row in _one(snapshot.standard,'OBJECTS')}
    payloads=[];records=[]
    for row in snapshot.native['objects']:
        if row['type'] < 500 or (handles is not None and row['handle'] not in handles):
            continue
        name = names[row['type']]
        if name in MESHERS:
            try:
                payload = decode_mesher(row, standards[row['handle']], classes[row['type']])
            except ExchangeError as error:
                records.append({'handle': row['handle'], 'status': 'retained-opaque', 'limitation': error.code,
                                'native_ready': False, 'qualified': False})
            else:
                payloads.append(payload)
                records.append({**payload.report, 'status': 'partial-payload'})
            continue
        decoder = DECODERS.get(name)
        code = 'td_geometry_profile_unmapped' if name in UNMAPPED_GEOMETRY_CLASSES else 'td_class_profile_unmapped'
        if name in GEOMETRY_CLASSES:
            dxf = classes[row['type']]['dxfname']
            if dxf != GEOMETRY_CLASSES[name] and dxf not in GEOMETRY_DXF_ALIASES.get(name, ()):
                decoder=None;code='td_geometry_class_identity_unmapped'
        if decoder is None and row['kind'] not in {'UNKNOWN_ENT','UNKNOWN_OBJ'}:continue
        if decoder:
            try:
                payload = decoder(row, standards[row['handle']])
                report = payload.report
                payloads.append(payload)
                records.append({**report, 'status': 'payload-decoded' if report['payload_decoded'] else 'partial-payload'})
                continue
            except ExchangeError as error:code=error.code
        records.append({'handle':row['handle'],'status':'retained-opaque','limitation':code,
                        'native_ready':False,'qualified':False})
    return ThermalInventory(tuple(payloads),tuple(records))
