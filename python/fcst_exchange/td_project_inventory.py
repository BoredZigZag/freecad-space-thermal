# SPDX-License-Identifier: MIT OR Apache-2.0
"""Project-level inventory for TD settings, ownership and declared companions."""
from collections import Counter

from .core import Limits, reject
from .dwg_native import _one
from .td_decode import decode_drawing
from .td_geometry import LinearSolidPayload
from .td_node import NodePayload
from .td_project_graph import companion_inventory, dictionary_graph
from .td_project_records import project_records
from .td_property_model import dependency_catalog


def _configuration_bindings(configuration, graph, objects):
    orbit_records = {r['handle']: r['status'] for r in configuration if r['class'] == 'RcOrbit'}
    orbits = {}
    for entry in graph['entries']:
        if entry['target'] in orbit_records:
            orbits.setdefault(entry['key'].casefold(), set()).add(entry['target'])
    for record in configuration:
        for case in record.get('settings', {}).get('cases', ()):
            for task in case['radiation_tasks']:
                name = task['orbit']
                if name:
                    targets = sorted(orbits.get(name.casefold(), ()), key=int)
                    status = 'missing'
                    if len(targets) > 1:
                        status = 'ambiguous'
                    elif targets:
                        status = 'resolved' if orbit_records[targets[0]] == 'payload-decoded' else 'opaque'
                    task['orbit_binding'] = {'status': status, 'targets': targets}
                task['object_bindings'] = [{'target': target, 'status': 'resolved' if int(target) in objects else 'missing'}
                                           for target in task['object_references'] if target != '0']


def inspect_project(staged):
    from .independent_td import DwgPreview

    if not isinstance(staged, DwgPreview):
        reject('independent_td_preview_required')
    snapshot = staged.snapshot
    objects = {r['handle']: r for r in snapshot.native['objects']}
    standards = {_one(r, 'handle')[2]: r for r in _one(snapshot.standard, 'OBJECTS')}
    graph, reached = dictionary_graph(snapshot, objects, standards)
    configuration = list(project_records(snapshot, objects, standards))
    configuration_handles = {r['handle'] for r in configuration}
    inventory = decode_drawing(snapshot)
    classes = {row['number']: row for row in snapshot.native['classes']}
    node_handles = {p.record['handle'] for p in inventory.payloads if isinstance(p, NodePayload)}
    element_nodes = {p.record['handle']: p.fields['node_handles'] for p in inventory.payloads
                     if isinstance(p, LinearSolidPayload)}
    thermal = []
    for record in inventory.records:
        handle = record['handle']
        if str(handle) not in configuration_handles:
            identity = classes[objects[handle]['type']]
            item = {**record, 'handle': str(handle), 'class': identity['cppname'],
                    'dxf': identity['dxfname'], 'dictionary_reachable': handle in reached}
            if handle in element_nodes:
                item['node_bindings'] = [
                    {'target': str(node), 'status': 'resolved' if node in node_handles
                     else 'unmapped' if node in objects else 'missing'}
                    for node in element_nodes[handle]]
            thermal.append(item)
    for record in configuration:
        record['dictionary_reachable'] = int(record['handle']) in reached
        for link in record.get('common_references', ()):
            if int(link['target']) and int(link['target']) not in objects:
                graph['diagnostics'].append({'code': 'td_project_common_target_missing', 'handle': link['target']})
    _configuration_bindings(configuration, graph, objects)
    references = [{**ref, 'manager': record['handle']} for record in configuration for ref in record.get('references', ())]
    original = staged.original
    properties = dependency_catalog(snapshot, original.files, inventory=inventory)
    properties['references'] = [{**r, 'handle': str(r['handle'])} for r in properties['references']]
    companions = companion_inventory(original.files, original.entry, references)
    counts = Counter(r['status'] for r in (*configuration, *thermal))
    if len(configuration) + len(thermal) + len(graph['entries']) + len(companions['files']) > Limits().records:
        reject('td_project_inventory_limit')
    staged.original.check_current()
    return {
        'profile': 'td-independent-project-inventory/1', 'source_revision': original.source_hash,
        'source_container': snapshot.report, 'configuration': configuration, 'thermal_objects': thermal,
        'dictionary_graph': graph, 'companion_inventory': companions, 'property_dependencies': properties,
        'status_counts': dict(counts), 'full_model_dependency_closure': False, 'native_ready': False,
        'limitations': ['td_case_runtime_mapping_unqualified', 'td_orbit_environment_mapping_unqualified',
                        'td_complete_dependency_closure_unverified'],
        'qualified': False,
    }
