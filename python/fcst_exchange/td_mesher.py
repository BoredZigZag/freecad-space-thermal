# SPDX-License-Identifier: MIT OR Apache-2.0
"""Inspect stored TD mesher links while preserving the opaque settings."""
from dataclasses import dataclass, field
from pathlib import PurePosixPath
import re

from .core import ExchangeError, reject
from .dwg_native import Fields, _one
from .td_filer import Filer
from .td_node import common_handles
from .td_project_graph import field as dwg_field, reference_target


MESHERS = {
    'TdMesher': ('TDMESHER', 43, 5),
    'TdMesherVA': ('TDMESHERVA', 43, 5),
    'TdFiniteElementMeshImporter': ('TDFEMESHIMPORTER', 39, 5),
    'TdScImporter': ('TDSCIMPORTER', 6, 4),
}
MESH_LINK_LIMIT = 50000
CAD_ROLES = {'.scdoc': 'spaceclaim-document', '.dsco': 'td-designer-document'}


@dataclass(frozen=True)
class MesherPayload:
    record: dict = field(repr=False)
    references: tuple = field(repr=False)
    companion: str | None = field(repr=False)
    version: int
    companion_role: str | None = None

    @property
    def fields(self):
        return {'references': self.references, 'companion': self.companion, 'companion_role': self.companion_role}

    def edited_record(self, changes):
        reject('td_mesh_regeneration_settings_unmapped')

    @property
    def report(self):
        return {'profile': f'td-stored-mesh-links-v{self.version}/1', 'handle': self.record['handle'],
                'payload_decoded': False, 'stored_mesh_references': len(self.references),
                'native_ready': False, 'qualified': False,
                'limitation': 'td_mesh_regeneration_settings_unmapped'}


def decode_mesher(row, standard, identity):
    dxf, version, code = MESHERS[identity['cppname']]
    if identity['dxfname'] != dxf or row['kind'] != 'UNKNOWN_ENT':
        reject('td_geometry_class_identity_unmapped')
    filer = Filer(row)
    common_handles(filer, standard)
    filer.version(version)
    companion = role = None
    if identity['cppname'] == 'TdScImporter':
        path = filer.text()
        role = CAD_ROLES.get(PurePosixPath(path.replace('\\', '/')).suffix.casefold())
        if role:
            companion = path
    if filer.data.position == filer.data.end:
        reject('td_mesher_settings_missing')
    links, targets = [], set()
    while filer.handles.end - filer.handles.position >= 8:
        if len(links) == MESH_LINK_LIMIT:
            reject('td_mesh_reference_limit')
        link = filer.handle()
        if link['code'] != code:
            reject('td_mesher_reference_code')
        target = link['target']
        if target:
            if target in targets:
                reject('td_mesher_duplicate_reference')
            targets.add(target)
        links.append(target)
    return MesherPayload(row, tuple(links), companion, version, role)


def _saved_mesh_groups(standard, manager_handle, node_indices, element_keys):
    """Return named DWG groups containing at least one selected mesh member."""
    root_ref = dwg_field(_one(standard, 'HEADER'), 'DICTIONARY_ACAD_GROUP')
    if root_ref is None:
        return []
    root = reference_target(root_ref, 0)
    if not root:
        return []
    objects = {_one(row, 'handle')[2]: row for row in _one(standard, 'OBJECTS')}
    dictionary = objects.get(root, ())
    entries = dwg_field(dictionary, 'items', Fields())
    if (dwg_field(dictionary, 'object') != 'DICTIONARY' or not isinstance(entries, Fields)
            or len(entries) != dwg_field(dictionary, 'numitems') or len(entries) > MESH_LINK_LIMIT):
        reject('td_mesh_group_dictionary')
    names, groups = set(), []
    for name, link in entries:
        handle = reference_target(link, root)
        row = objects.get(handle, ())
        links = dwg_field(row, 'groups', [])
        if (not name or name.casefold() in names or dwg_field(row, 'object') != 'GROUP'
                or not isinstance(links, list) or len(links) > MESH_LINK_LIMIT):
            reject('td_mesh_group_record')
        names.add(name.casefold())
        targets = {reference_target(member, handle) for member in links}
        nodes = sorted(node_indices[h] for h in targets & node_indices.keys())
        elements = sorted(element_keys[h] for h in targets & element_keys.keys())
        if nodes or elements:
            key = name.casefold()
            # Reviewed TD groups append the owning importer handle in hex.
            # Normalize only recognized TD mesh groups with the exact suffix.
            suffix = f'_{manager_handle:x}'
            if key.endswith(suffix) and re.search(r'(?:^tdfem_|_(?:nodes|surfaces|solids)_)', key):
                key = key[:-len(suffix)] + '_<owner>'
            groups.append((key, nodes, elements, len(targets) - len(nodes) - len(elements)))
    return sorted(groups)


def compare_mesh_states(before, after, before_handle, after_handle):
    """Compare stored CAD links and FE connectivity in two captured drawings."""
    from hashlib import sha256

    from fcst_app.persistence import encode
    from .independent_td import DwgPreview
    from .td_decode import decode_drawing
    from .td_geometry import LinearShellPayload, LinearSolidPayload
    from .td_geometry_mesh import _stored_mesh_selection
    from .td_node import NodePayload
    from .td_project_graph import companion_inventory

    if not all(isinstance(state, DwgPreview) for state in (before, after)):
        reject('independent_td_preview_required')

    def capture(state, handle):
        original = state.original
        payloads = decode_drawing(state.snapshot, handles={handle}).payloads
        if len(payloads) != 1 or not isinstance(payloads[0], MesherPayload):
            reject('td_mesh_state_manager')
        manager, = payloads
        row_type = manager.record['type']
        name = next(row['cppname'] for row in state.snapshot.native['classes'] if row['number'] == row_type)
        companion = None
        if name == 'TdScImporter' and not manager.companion:
            reject('td_mesh_state_companion_unresolved')
        if manager.companion:
            references = [{'role': manager.companion_role, 'path': manager.companion}]
            catalog = companion_inventory(original.files, original.entry, references)
            binding, = catalog['declared_inputs']
            if binding['status'] != 'resolved':
                reject('td_mesh_state_companion_unresolved')
            companion = {'role': manager.companion_role,
                         'sha256': sha256(dict(original.files)[binding['member']]).hexdigest()}
        try:
            selected = _stored_mesh_selection(state.snapshot, {handle: manager}, (handle,))
        except ExchangeError as error:
            if error.code != 'td_mesher_no_stored_elements':
                raise
            selected = set()
        if len(selected) > MESH_LINK_LIMIT:
            reject('td_mesh_reference_limit')
        elements = decode_drawing(state.snapshot, handles=selected).payloads
        if len(elements) != len(selected) or any(
                not isinstance(element, (LinearShellPayload, LinearSolidPayload)) for element in elements):
            reject('td_mesh_state_element_unmapped')
        node_handles = {node for element in elements for node in element.fields['node_handles']}
        nodes = {node.record['handle']: node.fields for node in
                 decode_drawing(state.snapshot, handles=node_handles).payloads if isinstance(node, NodePayload)}
        if nodes.keys() != node_handles:
            reject('td_element_missing_node')
        if any(any(node['offsets']) for node in nodes.values()):
            reject('td_element_node_offset_unmapped')
        ordered = sorted(nodes, key=lambda h: (nodes[h]['basis'][0], nodes[h]['submodel'].casefold(),
                                               nodes[h]['identifier'], h))
        source_ids = [(nodes[h]['submodel'].casefold(), nodes[h]['identifier']) for h in ordered]
        if len(set(source_ids)) != len(source_ids):
            reject('td_mesh_state_node_identity_collision')
        indices = {handle: i for i, handle in enumerate(ordered)}
        cells = {}
        for element in elements:
            if element.fields.get('additional_node_selector') or element.fields.get('extra_points'):
                reject('td_mesh_state_element_unmapped')
            handles = element.fields['node_handles']
            cells[element.record['handle']] = (element.shape, element.order, tuple(indices[h] for h in handles))
        topology = {'points': [nodes[h]['basis'][0] for h in ordered], 'cells': sorted(cells.values())}
        groups = _saved_mesh_groups(state.snapshot.standard, handle, indices, cells)
        return {'drawing_sha256': original.drawing_hash, 'manager_class': name, 'companion': companion,
                'nodes': len(nodes), 'elements': len(cells),
                'ordered_mesh_sha256': sha256(encode(topology)).hexdigest(),
                'source_node_assignment_sha256': sha256(encode(source_ids)).hexdigest(),
                'mesh_groups': len(groups), 'mesh_group_sha256': sha256(encode(groups)).hexdigest()}

    first = capture(before, before_handle)
    second = capture(after, after_handle)
    if first['manager_class'] != second['manager_class']:
        reject('td_mesh_state_manager_class')
    first_role = first['companion']['role'] if first['companion'] else None
    second_role = second['companion']['role'] if second['companion'] else None
    if first_role != second_role:
        reject('td_mesh_state_companion_role')
    before.original.check_current()
    if after.original != before.original:
        after.original.check_current()
    return {'profile': 'td-stored-mesh-comparison/2', 'before': first, 'after': second,
            'companion_changed': first['companion'] != second['companion'],
            'mesh_changed': first['ordered_mesh_sha256'] != second['ordered_mesh_sha256'],
            'source_node_assignments_changed': first['source_node_assignment_sha256'] != second['source_node_assignment_sha256'],
            'mesh_groups_changed': first['mesh_group_sha256'] != second['mesh_group_sha256'],
            'vendor_runtime_required': False, 'qualified': False}
