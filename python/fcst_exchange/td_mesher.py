# SPDX-License-Identifier: MIT OR Apache-2.0
"""Inspect stored TD mesher links while preserving the opaque settings."""
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .core import reject
from .td_filer import Filer
from .td_node import common_handles


MESHERS = {
    'TdMesher': ('TDMESHER', 43, 5),
    'TdFiniteElementMeshImporter': ('TDFEMESHIMPORTER', 39, 5),
    'TdScImporter': ('TDSCIMPORTER', 6, 4),
}
MESH_LINK_LIMIT = 50000


@dataclass(frozen=True)
class MesherPayload:
    record: dict = field(repr=False)
    references: tuple = field(repr=False)
    companion: str | None = field(repr=False)
    version: int

    @property
    def fields(self):
        return {'references': self.references, 'companion': self.companion}

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
    companion = None
    if identity['cppname'] == 'TdScImporter':
        path = filer.text()
        if PurePosixPath(path.replace('\\', '/')).suffix.casefold() == '.scdoc':
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
    return MesherPayload(row, tuple(links), companion, version)
