# SPDX-License-Identifier: MIT OR Apache-2.0
"""Inspect the TD project's DWG dictionary and captured file dependencies."""
from collections import Counter, deque
from hashlib import sha256
from pathlib import PurePosixPath

from fcst_contracts import ContractError, dependency_order

from .core import ExchangeError, Limits, reject
from .dwg_native import Fields, _one
from .vendor_paths import path_name


def reference_target(value, owner):
    """Resolve the ordered standard-reader representation of a DWG handle."""
    if (not isinstance(value, list) or len(value) not in (3, 4)
            or any(type(v) is not int or v < 0 for v in value)):
        reject('td_project_handle')
    code, length, offset = value[:3]
    if length > 8 or offset.bit_length() > length * 8:
        reject('td_project_handle')
    if code in (0, 2, 3, 4, 5):
        target = offset
    elif code in (6, 8) and not length:
        target = owner + (1 if code == 6 else -1)
    elif code in (10, 12):
        target = owner + (offset if code == 10 else -offset)
    else:
        reject('td_project_handle')
    if not 0 <= target < 2**64 or (len(value) == 4 and value[3] != target):
        reject('td_project_handle')
    return target


def field(fields, name, default=None):
    values = [value for key, value in fields if key == name]
    if len(values) > 1:
        reject('td_project_duplicate_field')
    return values[0] if values else default


def dictionary_graph(snapshot, objects, standards):
    """Walk dictionary entries, preserving repeated references to one object."""
    root_reference = field(_one(snapshot.standard, 'HEADER'), 'DICTIONARY_NAMED_OBJECT')
    if root_reference is None:
        return {'root': None, 'entries': [], 'diagnostics': [{'code': 'td_project_named_dictionary_missing'}]}, set()
    root = reference_target(root_reference, 0)
    if root not in objects or objects[root]['kind'] != 'DICTIONARY':
        reject('td_project_named_dictionary_invalid')
    todo = deque([root])
    dictionaries = {root}
    dependencies = {}
    reached = {root}
    entries, diagnostics = [], []
    limit = Limits().records
    while todo:
        owner = todo.popleft()
        children = dependencies[owner] = set()
        row = standards[owner]
        items = field(row, 'items', Fields())
        if not isinstance(items, Fields) or len(items) != field(row, 'numitems'):
            reject('td_project_dictionary_shape')
        if len(items) + len(entries) > limit:
            reject('td_project_inventory_limit')
        names = set()
        for name, value in items:
            key = name.casefold()
            if not name or len(name) > 32768 or '\0' in name or key in names:
                reject('td_project_dictionary_key')
            names.add(key)
            target = reference_target(value, owner)
            status = 'resolved' if target in objects else 'missing'
            entries.append({'dictionary': str(owner), 'key': name, 'target': str(target), 'status': status})
            if target not in objects:
                diagnostics.append({'code': 'td_project_dictionary_target_missing', 'handle': str(target)})
                continue
            reached.add(target)
            if objects[target]['kind'] in {'DICTIONARY', 'DICTIONARYWDFLT'}:
                children.add(target)
                if target not in dictionaries:
                    dictionaries.add(target)
                    todo.append(target)
    try:
        dependency_order(dependencies, 'depth')
    except ContractError as error:
        diagnostics.append({'code': f'td_project_dictionary_{error.diagnostic.code}'})
    return {'root': str(root), 'entries': entries, 'diagnostics': diagnostics}, reached


def companion_inventory(files, entry, references):
    """Resolve declared paths only against the captured, validated file tree."""
    roles = {'.dwg': 'drawing', '.tdp': 'thermophysical-library', '.rco': 'optical-library',
             '.inp': 'sinda-deck', '.for': 'sinda-source', '.out': 'solver-output',
             '.hrl': 'heating-lookup', '.hra': 'heating-array', '.k': 'radiation-data', '.k_in': 'radiation-input'}
    members = {name.casefold(): name for name, _ in files}
    inventory = [{'path': name, 'role': 'entry-drawing' if name == entry else
                  roles.get(PurePosixPath(name).suffix.casefold(), 'unclassified'),
                  'bytes': len(raw), 'sha256': sha256(raw).hexdigest()} for name, raw in files]
    bindings = []
    for reference in references:
        name = reference['path']
        try:
            relative = path_name(name.replace('\\', '/'))
        except ExchangeError:
            bindings.append({**reference, 'status': 'external-or-unsafe'})
            continue
        candidate = str(PurePosixPath(entry).parent / relative)
        target = members.get(candidate.casefold())
        if target is None:
            bindings.append({**reference, 'status': 'missing'})
        elif roles.get(PurePosixPath(target).suffix.casefold()) != reference['role']:
            bindings.append({**reference, 'status': 'wrong-file-role', 'member': target})
        else:
            bindings.append({**reference, 'status': 'resolved', 'member': target})
    return {'files': inventory, 'declared_inputs': bindings,
            'resolution_counts': dict(Counter(r['status'] for r in bindings))}
