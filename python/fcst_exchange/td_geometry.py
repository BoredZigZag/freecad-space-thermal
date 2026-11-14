# SPDX-License-Identifier: MIT OR Apache-2.0
"""Owned RcRectangle v7 serialization, with an explicit partial fallback.

The serialization sentinel is a format discriminator, never a model parameter.
No units, surface properties, mesh or thermal assignments are inferred here.
"""
from dataclasses import dataclass,field
from hashlib import sha256
import math
from .core import reject,ExchangeError
from .td_filer import Filer
from .td_node import common_handles
from .td_surface import (ATTRIBUTE_REVISION, EXTENDED_ATTRIBUTE_REVISION, MESH_ATTRIBUTE_REVISION, read_attributes, read_mesh_controls,
    read_solid_attributes, read_text_ids, write_attributes, write_mesh_controls, write_expression, write_solid_attributes)

SENTINEL=float.fromhex('0x1.f07c18386f74ep+295')
EXTENDED_SURFACE_REVISIONS = (EXTENDED_ATTRIBUTE_REVISION, MESH_ATTRIBUTE_REVISION)


@dataclass(frozen=True)
class RectangleEnvelope:
    fields:dict=field(repr=False)
    record:dict=field(repr=False)
    standard:object=field(repr=False)

    @property
    def report(self):
        return {'profile':'td-rcrectangle-envelope-v7/1','handle':self.record['handle'],
                'payload_decoded':False,'geometric_envelope_decoded':True,
                'native_ready':False,'qualified':False,
                'scope':'Six serialized geometric parameters, origin and basis; thermal attributes and units unresolved'}

    def edited_record(self,changes):reject('td_rectangle_thermal_attributes_unmapped')


@dataclass(frozen=True)
class RectanglePayload:
    fields:dict=field(repr=False)
    spans:dict=field(repr=False)
    record:dict=field(repr=False)
    standard:object=field(repr=False)

    @property
    def report(self):
        revision = self.fields['attributes'].get('wire_revision', 54)
        return {'profile':f'td-rcrectangle-v7-attributes{revision}/1','handle':self.record['handle'],
                'payload_decoded':True,'geometric_envelope_decoded':True,'thermal_semantics_decoded':False,
                'native_ready':False,'qualified':False,
                'scope':'Complete serialized rectangle, surface attributes and mesh controls; physical selector mappings and mesh regeneration pending'}

    def edited_record(self,changes):
        if 'extended_attributes' in self.fields['attributes']:
            reject('td_rectangle_extended_edit_unmapped')
        return _edit_geometry(self,changes,decode_rectangle_complete,6,2,self.fields['parameter_expressions'])


def _edit_geometry(payload,changes,decoder,count,dimensions,expressions):
    from .dwg_bits import scalar_record
    from .td_filer import expression_is_constant
    if (not isinstance(changes,dict) or not changes or set(changes)!={'serialized_parameters'}
            or not isinstance(changes['serialized_parameters'],(list,tuple)) or len(changes['serialized_parameters'])!=count):reject('td_geometry_edit_shape')
    values=tuple(changes['serialized_parameters'])
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in values):reject('td_geometry_edit_number')
    if len(expressions) not in (dimensions,12) or any(not expression_is_constant(e) for e in expressions):reject('td_geometry_dynamic_edit')
    changed_indices=[i for i,v in enumerate(values) if v!=payload.fields['serialized_parameters'][i]]
    if len(expressions)==dimensions and (any(i>=dimensions for i in changed_indices) or any(v<=0 for v in values[:dimensions])):
        reject('td_geometry_size_edit_scope')
    selected={f'parameter_{i}':values[i] for i in changed_indices}
    if not 1<=len(selected)<=2:reject('td_geometry_edit_field_limit')
    row=scalar_record(payload.record,payload.spans,selected);after=decoder(row,payload.standard)
    if after.fields!={**payload.fields,'serialized_parameters':values}:reject('td_geometry_edit_reopen')
    return row,{'profile':payload.report['profile'],'changed_fields':sorted(selected),
                'before_sha256':sha256(bytes.fromhex(payload.record['data'])).hexdigest(),
                'after_sha256':sha256(bytes.fromhex(row['data'])).hexdigest(),
                'bit_length_preserved':row['bits']==payload.record['bits'],'native_ready':False,'qualified':False,
                'scope':'Serialized parameter edit only; no mesh regeneration or thermal qualification'}

def _prefix(filer,standard):
    b=filer.data
    if b.bd()!=SENTINEL:reject('td_rectangle_profile_marker')
    filer.version(7)
    return {'serialized_parameters':tuple(filer.number(f'parameter_{i}') for i in range(6)),
            'origin':b.point(),'axes':tuple(b.point() for _ in range(3)),
            'common_handles':common_handles(filer,standard)}


def decode_rectangle_complete(row,standard):
    return _decode_surface(row, standard, RectanglePayload, (ATTRIBUTE_REVISION, *EXTENDED_SURFACE_REVISIONS))


def _decode_surface(row, standard, cls, revisions, *shape):
    filer=Filer(row);fields=_prefix(filer,standard);b=filer.data
    fields['attributes']=read_attributes(filer, revisions=revisions)
    fields['additional_parameters']=tuple(b.bd() for _ in range(6))
    fields['mesh_controls']=read_mesh_controls(filer)
    fields['parameter_expressions']=tuple(filer.expression() for _ in range(filer.count()))
    fields['entity_flags']=b.bl()
    if fields['attributes'].get('wire_revision') == 56:
        fields['mesh_references'] = _mesh_references(filer)
    filer.finish()
    return cls(fields,dict(filer.spans),dict(row),standard,*shape)


@dataclass(frozen=True)
class DiskPayload(RectanglePayload):
    @property
    def report(self):
        revision = self.fields['attributes']['wire_revision']
        return {**super().report, 'profile': f'td-rcdisk-v7-attributes{revision}/1',
                'scope': 'Complete disk geometry, surface attributes and mesh controls'}

    def edited_record(self, changes):
        reject('td_disk_edit_unmapped')


def decode_disk(row, standard):
    return _decode_surface(row, standard, DiskPayload, EXTENDED_SURFACE_REVISIONS)


@dataclass(frozen=True)
class ConicPayload(RectanglePayload):
    shape: str

    @property
    def report(self):
        name = self.shape.replace('-', '')
        revision = self.fields['attributes']['wire_revision']
        return {**super().report, 'profile': f'td-rc{name}-v7-attributes{revision}/1',
                'scope': 'Complete conic serialization, surface attributes and mesh controls'}

    def edited_record(self, changes):
        reject('td_conic_edit_unmapped')


def conic_decoder(shape):
    # These classes share the same data/text/handle filer. The class identity
    # selects the meaning of the parameter slots after structural decoding.
    def decode(row, standard):
        return _decode_surface(row, standard, ConicPayload, EXTENDED_SURFACE_REVISIONS, shape)
    return decode


def decode_rectangle(row,standard):
    try:return decode_rectangle_complete(row,standard)
    except ExchangeError as error:limitation=error.code
    filer=Filer(row);b=filer.data;fields=_prefix(filer,standard)
    if b.position==b.end:reject('td_rectangle_missing_thermal_attributes')
    fields['opaque_data_range']=(b.position,b.end)
    fields['opaque_text_range']=(filer.strings.position,filer.strings.end)
    fields['opaque_handle_range']=(filer.handles.position,filer.handles.end)
    fields['complete_profile_limitation']=limitation
    return RectangleEnvelope(fields,dict(row),standard)


def rectangle_payload(fields):
    """Serialize a complete declared profile from owned inputs, without a DWG."""
    from .td_writer import FilerWriter
    expected={'serialized_parameters','origin','axes','attributes','additional_parameters','mesh_controls','parameter_expressions','entity_flags'}
    if not isinstance(fields,dict) or set(fields)!=expected:reject('td_rectangle_writer_shape')
    if len(fields['serialized_parameters'])!=6 or len(fields['axes'])!=3 or len(fields['additional_parameters'])!=6:reject('td_rectangle_writer_shape')
    f=FilerWriter();b=f.data;b.bd(SENTINEL);b.bl(7)
    for value in fields['serialized_parameters']:b.bd(value)
    b.point(fields['origin'])
    for axis in fields['axes']:b.point(axis)
    write_attributes(f,fields['attributes'])
    for value in fields['additional_parameters']:b.bd(value)
    write_mesh_controls(f,fields['mesh_controls'])
    if len(fields['parameter_expressions'])>10000:reject('td_rectangle_writer_limit')
    b.bl(len(fields['parameter_expressions']))
    for expression in fields['parameter_expressions']:write_expression(f,expression)
    b.bl(fields['entity_flags']);return f.result(4)


@dataclass(frozen=True)
class BrickPayload(RectanglePayload):
    @property
    def report(self):
        version = self.fields.get('wire_version', 21)
        return {'profile':f'td-rcfdbrick-v{version}/1','handle':self.record['handle'],'payload_decoded':True,
                'geometric_envelope_decoded':True,'thermal_semantics_decoded':False,'native_ready':False,'qualified':False,
                'scope':'Complete serialized brick, subdivision, material/face fields, mesh controls and advection; physical selector bindings and mesh regeneration pending'}

    def edited_record(self,changes):
        if 'extended_attributes' in self.fields:
            reject('td_brick_extended_edit_unmapped')
        return _edit_geometry(self,changes,decode_brick,12,3,self.fields['attributes']['parameter_expressions'])


def decode_brick(row,standard):
    return _decode_solid(row, standard, BrickPayload, 21, 23)


@dataclass(frozen=True)
class CurvedSolidPayload(BrickPayload):
    @property
    def report(self):
        return {**super().report, 'profile': f'td-rcfdsolid{self.shape}-v23/1',
                'scope': 'Complete curved-solid geometry, face attributes and mesh controls'}

    def edited_record(self, changes):
        reject('td_curved_solid_edit_unmapped')


class CylinderPayload(CurvedSolidPayload):
    shape = 'cylinder'


class SpherePayload(CurvedSolidPayload):
    shape = 'sphere'


class ConeSolidPayload(CurvedSolidPayload):
    shape = 'cone'


class EllipsoidSolidPayload(CurvedSolidPayload):
    shape = 'ellipsoid'


def decode_cylinder(row, standard):
    return _decode_solid(row, standard, CylinderPayload, 23)


def decode_sphere(row, standard):
    return _decode_solid(row, standard, SpherePayload, 23)


def decode_solid_cone(row, standard):
    return _decode_solid(row, standard, ConeSolidPayload, 23)


def decode_solid_ellipsoid(row, standard):
    return _decode_solid(row, standard, EllipsoidSolidPayload, 23)


def _decode_solid(row, standard, cls, *versions):
    f=Filer(row);b=f.data;version=f.version_one_of(*versions)
    fields={'serialized_parameters':tuple(f.number(f'parameter_{i}') for i in range(12)),
            'origin':b.point(),'axes':tuple(b.point() for _ in range(3)),
            'common_handles':common_handles(f,standard),'attributes':read_solid_attributes(f)}
    if version == 23:
        fields['wire_version'] = 23
        fields['extended_attributes'] = {'names': f.texts(), 'indices': f.integers(), 'text_ids': read_text_ids(f)}
    f.finish();return cls(fields,dict(f.spans),dict(row),standard)


@dataclass(frozen=True)
class LinearSolidPayload(RectanglePayload):
    @property
    def report(self):
        version = self.fields.get('node_wire_version', 5)
        revision = self.fields['attributes'].get('wire_version', 13)
        return {'profile': f'td-rclinear{self.shape}2-v{version}-attributes{revision}/1', 'handle': self.record['handle'],
                'payload_decoded': True, 'geometric_envelope_decoded': True, 'thermal_semantics_decoded': False,
                'native_ready': False, 'qualified': False,
                'scope': 'Ordered node references, optional element frame and serialized element attributes'}

    def edited_record(self, changes):
        reject('td_linear_solid_edit_unmapped')


class LinearBrickPayload(LinearSolidPayload):
    shape = 'brick'
    node_count = 8


class LinearWedgePayload(LinearSolidPayload):
    shape = 'wedge'
    node_count = 6


class LinearTetraPayload(LinearSolidPayload):
    shape = 'tetra'
    node_count = 4


class LinearPyramidPayload(LinearSolidPayload):
    shape = 'pyramid'
    node_count = 5


@dataclass(frozen=True)
class LinearShellPayload(RectanglePayload):
    shape: str
    order: int = 1

    @property
    def report(self):
        name = f'linear{self.shape}2' if self.order == 1 else f'quadratic{self.shape}'
        revision = self.fields['attributes']['wire_revision']
        version = self.fields.get('node_wire_version', 5)
        return {**super().report, 'profile': f'td-rc{name}-v{version}-attributes{revision}/1',
                'scope': 'Ordered element nodes, surface attributes and linked objects'}

    def edited_record(self, changes):
        reject('td_linear_shell_edit_unmapped')


@dataclass(frozen=True)
class PolygonMeshPayload(RectanglePayload):
    @property
    def report(self):
        revision = self.fields['attributes']['wire_revision']
        return {**super().report, 'profile': f'td-rcmeshfd-v{self.fields["version"]}-attributes{revision}/1',
                'scope': 'Ordered polygon vertices and faces with surface attributes'}

    def edited_record(self, changes):
        reject('td_polygon_mesh_edit_unmapped')


def decode_polygon_mesh(row, standard):
    filer = Filer(row)
    common = common_handles(filer, standard)
    attrs = read_attributes(filer, revisions=EXTENDED_SURFACE_REVISIONS)
    b = filer.data
    version = b.bl()
    if version not in (1, 2):
        reject('td_filer_version')
    filer.version(1)
    points = tuple(b.point() for _ in range(filer.count()))
    filer.version(1)
    faces = []
    for _ in range(filer.count()):
        filer.version(1)
        face = filer.integers()
        if len(face) < 3 or len(set(face)) != len(face) or any(index < 0 or index >= len(points) for index in face):
            reject('td_polygon_mesh_connectivity')
        faces.append(face)
    flags = b.bl() if version == 2 else 0
    fields = {'version': version, 'common_handles': common, 'attributes': attrs,
              'points': points, 'faces': tuple(faces), 'entity_flags': flags}
    if attrs.get('wire_revision') == 56:
        fields['mesh_references'] = _mesh_references(filer)
    filer.finish()
    return PolygonMeshPayload(fields, {}, dict(row), standard)


def _mesh_references(filer):
    # These entity layouts end with soft pointers. Their ownership and thermal
    # meaning are unresolved. The count is bounded by the handle stream itself.
    links = []
    while filer.handles.end - filer.handles.position >= 8:
        if len(links) == 10000:
            reject('td_mesh_reference_limit')
        link = filer.handle()
        if link['code'] != 4:
            reject('td_mesh_reference_code')
        links.append(link)
    return tuple(links)


def decode_linear_tri(row, standard):
    return _decode_linear_shell(row, standard, 'tri', 3)


def decode_linear_quad(row, standard):
    return _decode_linear_shell(row, standard, 'quad', 4)


def decode_quadratic_tri(row, standard):
    return _decode_linear_shell(row, standard, 'tri', 6, order=2)


def decode_quadratic_quad(row, standard):
    return _decode_linear_shell(row, standard, 'quad', 8, order=2)


def _decode_linear_shell(row, standard, shape, count, *, order=1):
    filer = Filer(row)
    common = common_handles(filer, standard)
    attrs = read_attributes(filer, revisions=EXTENDED_SURFACE_REVISIONS)
    marker56 = attrs.get('wire_revision') == 56
    if marker56:
        # An optional soft pointer precedes the ordered hard node pointers.
        stream = filer.handles
        position = stream.position
        code = stream.take(4)
        stream.position = position
        if code == 4:
            attrs['leading_soft_reference'] = filer.handle()
    fields = _element_nodes(filer, count, hard_pointers=marker56)
    filer.version(5)
    references = tuple(filer.handle() for _ in range(filer.count()))
    extra_points = tuple(filer.data.point() for _ in range(filer.count()))
    filer.version(1)
    filer.finish()
    fields.update(common_handles=common, attributes=attrs, references=references, extra_points=extra_points)
    return LinearShellPayload(fields, {}, dict(row), standard, shape, order)


def decode_linear_brick(row, standard):
    return _decode_linear_solid(row, standard, LinearBrickPayload)


def decode_linear_wedge(row, standard):
    return _decode_linear_solid(row, standard, LinearWedgePayload)


def decode_linear_tetra(row, standard):
    return _decode_linear_solid(row, standard, LinearTetraPayload)


def decode_linear_pyramid(row, standard):
    return _decode_linear_solid(row, standard, LinearPyramidPayload)


def _decode_linear_solid(row, standard, cls):
    filer = Filer(row)
    common = common_handles(filer, standard)
    fields = _element_nodes(filer, cls.node_count)
    b = filer.data
    revision = filer.version_one_of(13, 14)

    def references():
        return tuple(filer.handle() for _ in range(filer.count()))

    attrs = {'names': (filer.text(), filer.text()), 'references_a': references(),
             'label': filer.text(), 'face_selector': b.bl(), 'references_b': references(),
             'point_values': tuple((b.bd(), b.point()) for _ in range(filer.count()))}
    attrs['modifiers'] = (tuple(b.bd() for _ in range(4)), tuple(filer.expression() for _ in range(4))) if b.take(1) else None
    attrs.update(references_c=references(), selector=b.bl(), expression=filer.expression())
    if revision == 14:
        attrs.update(wire_version=14, additional_selector=b.bl())
    filer.version(1)
    filer.finish()
    fields.update(common_handles=common, attributes=attrs)
    return cls(fields, {}, dict(row), standard)


def _element_nodes(filer, count, *, hard_pointers=False):
    version = filer.version_one_of(5, 6)
    if filer.count() != count:
        reject('td_element_node_count')
    links = tuple(filer.handle() for _ in range(count))
    if hard_pointers and any(link['code'] != 5 for link in links):
        reject('td_element_node_reference_code')
    nodes = tuple(link['target'] for link in links)
    if 0 in nodes or len(set(nodes)) != count:
        reject('td_element_node_identity')
    label = filer.text()
    b = filer.data
    frame = tuple(b.point() for _ in range(4)) if b.take(1) else ()
    fields = {'node_handles': nodes, 'label': label, 'element_frame': frame, 'selector': b.bl()}
    if version == 6:
        fields.update(node_wire_version=6, additional_node_selector=b.bl())
    return fields


def brick_payload(fields):
    from .td_writer import FilerWriter
    if not isinstance(fields,dict) or set(fields)!={'serialized_parameters','origin','axes','attributes'}:reject('td_solid_writer_shape')
    if len(fields['serialized_parameters'])!=12 or len(fields['axes'])!=3:reject('td_solid_writer_shape')
    f=FilerWriter();b=f.data;b.bl(21)
    for value in fields['serialized_parameters']:b.bd(value)
    b.point(fields['origin'])
    for axis in fields['axes']:b.point(axis)
    write_solid_attributes(f,fields['attributes']);return f.result(5)
