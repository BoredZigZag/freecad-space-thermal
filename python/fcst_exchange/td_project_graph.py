# SPDX-License-Identifier: MIT OR Apache-2.0
"""Inspect the TD project's DWG dictionary and captured file dependencies."""
from collections import Counter, deque
from hashlib import sha256
from pathlib import PurePosixPath

from fcst_contracts import ContractError, dependency_order

from .core import ExchangeError, Limits, reject
from .dwg_native import Fields, _one
from .sinda import parse as parse_sinda
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
             '.hrl': 'heating-lookup', '.hra': 'heating-array', '.k': 'radiation-data', '.k_in': 'radiation-input',
             '.inc': 'sinda-include', '.sav': 'sinda-restart'}
    captured = dict(files)
    members = {name.casefold(): name for name, _ in files}
    inventory = [{'path': name, 'role': 'entry-drawing' if name == entry else
                  roles.get(PurePosixPath(name).suffix.casefold(), 'unclassified'),
                  'bytes': len(raw), 'sha256': sha256(raw).hexdigest()} for name, raw in files]
    def resolve(reference, base):
        try:
            relative = path_name(reference['path'].replace('\\', '/'))
        except ExchangeError:
            return {**reference, 'status': 'external-or-unsafe'}
        if base is None:
            return {**reference, 'status': 'run-directory-unmapped'}
        candidate = str(base / relative)
        target = members.get(candidate.casefold())
        if target is None:
            return {**reference, 'status': 'missing'}
        # SINDA INSERT accepts arbitrary filenames. Inspect their contents with
        # the bounded lexical reader and retain unsupported source as inert data.
        if reference['role'] != 'sinda-include' and roles.get(PurePosixPath(target).suffix.casefold()) != reference['role']:
            return {**reference, 'status': 'wrong-file-role', 'member': target}
        return {**reference, 'status': 'resolved', 'member': target}

    drawing_directory = PurePosixPath(entry).parent
    bindings = [resolve(ref, drawing_directory if not ref.get('run_directory_selector') else None) for ref in references]
    include_roots = {r['member'] for r in bindings if r['role'] == 'sinda-include' and r['status'] == 'resolved'}
    includes = _include_inventory(captured, include_roots, resolve)
    return {'files': inventory, 'declared_inputs': bindings,
            'resolution_counts': dict(Counter(r['status'] for r in bindings)), 'sinda_includes': includes}


def _include_inventory(captured, roots, resolve):
    limits = Limits()
    graph, edges, diagnostics = {}, [], []
    pending, visited = deque(sorted(roots)), set(roots)
    total_bytes = total_records = 0
    while pending:
        if len(visited) > limits.files:
            reject('td_project_include_file_limit')
        name = pending.popleft()
        raw = captured[name]
        total_bytes += len(raw)
        if total_bytes > limits.total_bytes:
            reject('td_project_include_byte_limit')
        children = graph[name] = set()
        try:
            records = parse_sinda(name, raw, limits)
        except ExchangeError as error:
            diagnostics.append({'member': name, 'code': error.code})
            continue
        total_records += len(records)
        if total_records > limits.records:
            reject('td_project_include_record_limit')
        for record in records:
            if record.kind != 'INCLUDE':
                # An undecodable line or content after END can hide a directive.
                if record.code in {'unsupported_encoding', 'sinda_data_after_end'}:
                    diagnostics.append({'member': name, 'line': record.line, 'code': record.code})
                continue
            if record.code:
                diagnostics.append({'member': name, 'line': record.line, 'code': record.code})
                continue
            edge = resolve({'source': name, 'line': record.line, 'path': record.value['path'], 'role': 'sinda-include'},
                           PurePosixPath(name).parent)
            edges.append(edge)
            if edge['status'] == 'resolved':
                target = edge['member']
                children.add(target)
                if target not in visited:
                    visited.add(target)
                    pending.append(target)
    try:
        depths = {}
        for name in dependency_order(graph, 'depth'):
            depths[name] = 1 + max((depths[child] for child in graph[name]), default=0)
        if max(depths.values(), default=0) > limits.include_depth:
            diagnostics.append({'code': 'td_project_include_depth'})
    except ContractError:
        diagnostics.append({'code': 'td_project_include_cycle_or_depth'})
    return {'roots': sorted(roots), 'edges': edges, 'diagnostics': diagnostics}
