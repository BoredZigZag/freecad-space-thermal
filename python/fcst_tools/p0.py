# SPDX-License-Identifier: MIT OR Apache-2.0
"""Verify and combine the experimental P0 receipts from both Windows presets."""
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import subprocess
from .gate import evaluate


PRESETS = ('windows-debug', 'windows-release')
CRITERIA = 'ci/p0-acceptance.json'
FIXTURE = 'tests/fixtures/radiation/p0-two-surfaces.json'
INPUTS = (CRITERIA, FIXTURE, 'tools/p0_fixture.py', 'tools/p0_profiles.py', 'tools/p0_host_payload.py',
          'python/fcst_tools/p0.py', 'python/fcst_app/radiation_case.py', 'python/fcst_cli/solve.py',
          'engine/src/radiation_loading.inc', 'engine/src/environment.cpp')
METRICS = ('temperature_error_K', 'radiation_power_error_W', 'environment_power_error_W', 'energy_defect_J')
HOST_FIELDS = {'model_hash', 'edited_model_hash', 'temperature_hash', 'samples', 'contour_error',
               'history_matches', 'stale_rejected', 'terminal_states', 'partial_results', 'recovered'}
CLIENT_FIELDS = {'model_hash', 'fixture_hash', 'mesh_hash', 'samples', 'cli_temperature_hash',
                 'mcp_temperature_hash', 'parity_error_K', 'reconnect', 'metrics'}


def digest(value):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None


def within(value, maximum):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= maximum


def assess(host, mcp, criteria):
    metrics = mcp['metrics']
    if (set(host) != HOST_FIELDS or set(mcp) != CLIENT_FIELDS
            or set(metrics) != {*METRICS, 'view_factor', 'quadrature_difference'}
            or not all(digest(x) for x in (host['model_hash'], host['edited_model_hash'], host['temperature_hash'],
                                  mcp['mesh_hash'], mcp['cli_temperature_hash'], mcp['mcp_temperature_hash']))
            or host['model_hash'] != mcp['model_hash'] or host['edited_model_hash'] == host['model_hash']
            or host['temperature_hash'] != mcp['cli_temperature_hash'] or host['temperature_hash'] != mcp['mcp_temperature_hash']
            or type(host['samples']) is not int or host['samples'] != criteria['samples'] or host['samples'] != mcp['samples']
            or not within(host['contour_error'], criteria['contour_rgb_error'])
            or not all(host[k] is True for k in ('history_matches', 'stale_rejected', 'recovered'))
            or host['terminal_states'] != ['cancelled', 'interrupted']
            or type(host['partial_results']) is not int or host['partial_results'] != 0
            or mcp['reconnect'] is not True or not within(mcp['parity_error_K'], criteria['parity_error_K'])
            or not all(within(metrics[key], criteria[key]) for key in METRICS)
            or not within(metrics['quadrature_difference'], criteria['quadrature_agreement'])
            or not within(metrics['view_factor'], 1) or not 0 < metrics['view_factor'] < 1):
        raise ValueError('p0_parity_or_recovery')


def qualify(root, directory):
    def load(path):
        raw = path.read_bytes()
        return json.loads(raw), sha256(raw).hexdigest()

    candidate = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    inputs = {name: sha256((root/name).read_bytes()).hexdigest() for name in INPUTS}
    criteria, _ = load(root/CRITERIA)
    host_policy, _ = load(root/'ci/host-acceptance.json')
    mcp_policy, _ = load(root/'ci/mcp-acceptance.json')
    host_asset = load(root/'ci/host-profile.json')[0]['platforms']['Windows']['sha256']
    checks = {}
    for preset in PRESETS:
        matches = [p for p in directory.rglob('verification.json') if load(p)[0].get('preset') == preset]
        if len(matches) != 1:
            raise ValueError('p0_configuration_missing_or_duplicate')
        verification = matches[0]
        paths = (verification, *(verification.with_name(name) for name in ('host.json','mcp.json','thermal.json')))
        (run, run_hash), (host, host_hash), (mcp, mcp_hash), (thermal, thermal_hash) = map(load, paths)
        worker = thermal['binary_sha256']['worker']
        if (any(e['candidate'] != candidate or e['gate']['status'] != 'passed' for e in (run, host, mcp, thermal))
                or not digest(worker) or host['worker_sha256'] != worker or mcp['native_worker_sha256'] != worker
                or host['host_version'] != ['1','1','4'] or host['python_abi'] != 'cp311'
                or host['asset_sha256'] != host_asset or mcp['protocols'] != mcp_policy['protocols']
                or mcp['protocols'][0] != criteria['mcp_profile'].split()[0]
                or mcp['p0']['fixture_hash'] != inputs[FIXTURE]
                or evaluate(host_policy['required_cases'], host['cases'])['status'] != 'passed'
                or evaluate(mcp_policy['required_cases'], mcp['cases'])['status'] != 'passed'
                or any(host['input_sha256'].get(name) != inputs[name] for name in (CRITERIA, FIXTURE, 'tools/p0_host_payload.py'))
                or any(mcp['input_sha256'].get(name) != inputs[name] for name in (CRITERIA, FIXTURE, 'tools/p0_profiles.py'))):
            raise ValueError('p0_evidence_identity_or_coverage')
        assess(host['p0'], mcp['p0'], criteria)
        checks[preset] = dict(host=host['p0'], cli_mcp=mcp['p0'], worker_sha256=worker,
            evidence={path.relative_to(directory).as_posix(): value
                      for path, value in zip(paths, (run_hash, host_hash, mcp_hash, thermal_hash))})
    debug, release = (checks[p]['cli_mcp'] for p in PRESETS)
    if debug['model_hash'] != release['model_hash'] or debug['mesh_hash'] != release['mesh_hash']:
        raise ValueError('p0_configuration_parity')
    return dict(schema_version=1, gate='P0', status='passed', qualification='experimental',
                execution_mode='fcst_native', candidate=candidate, criteria_sha256=inputs[CRITERIA],
                fixture_sha256=inputs[FIXTURE], input_sha256=inputs,
                profiles={k:criteria[k] for k in ('host_profile','mcp_profile')}, configurations=checks)


def write_report(directory, report):
    root = Path.cwd()
    try:
        data = qualify(root, directory)
    except (ValueError, KeyError, OSError, TypeError, IndexError, subprocess.SubprocessError):
        data = dict(schema_version=1, gate='P0', status='failed', reason='missing_or_invalid_p0_evidence')
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(data, sort_keys=True, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    return data
