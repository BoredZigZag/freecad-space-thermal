# SPDX-License-Identifier: MIT OR Apache-2.0
"""Unattended WP-12 acceptance with all frozen seeds and bounded public evidence."""
import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'python'))
from fcst_tools.radiation import assess, assess_report, require, validate_run


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def input_hashes():
    paths = ['ci/radiation-acceptance-v1.json', 'ci/numerical-criteria-v1.json', 'tools/check_radiation.py',
             'python/fcst_tools/radiation.py', 'engine/src/radiation.cpp', 'engine/src/radiation_loading.inc',
             'engine/include/fcst/radiation.hpp', 'engine/tests/radiation_fixtures.hpp', 'engine/tests/radiation_tests.cpp',
             'engine/tests/radiation_subject.cpp', 'tests/fixtures/radiation/plates.json', 'tests/fixtures/radiation/steady.json',
             'engine/include/fcst/environment.hpp', 'engine/src/environment.cpp',
             'engine/src/thermal_transient.cpp', 'engine/include/fcst/thermal_transient.hpp',
             'engine/src/thermal_execution.inc', 'engine/src/thermal_loading.inc', 'engine/worker/main.cpp']
    return {p: digest(ROOT/p) for p in paths}


def check_environment(execute, worker, steady_fixture):
    from scipy.integrate import solve_ivp

    fixture = deepcopy(steady_fixture)
    fixture.pop('environment')
    fixture['sampling']['samples'] = 128
    thermal = fixture['thermal_input']
    entities = thermal['model']['entities']
    environment = next(e for e in entities if e['kind'] == 'environment')
    environment['solar_flux']['value'] = 20
    environment['background_temperature']['value'] = 0
    facet = fixture['facets'][0]
    facet['vertices_m'] = [[0, 0, 0], [0, 2, 0], [0, 0, 1]]
    start, end = 0, 2*math.pi
    entry, exit_ = math.pi-math.pi/6, math.pi+math.pi/6
    fixture['transient'] = dict(start=start, end=end, output_times=[start, end], maximum_step=.1,
                                absolute_temperature_tolerance=1e-5, relative_temperature_tolerance=1e-7,
                                include_steps=False)
    load = next(e for e in entities if e['kind'] == 'load')
    fixture['transient']['schedules'] = [dict(load_id=load['id'], points=[dict(time=0, factor=1),
                                                                         dict(time=entry, factor=.5)])]
    fixture['mission'] = dict(sun_direction_inertial=[1, 0, 0], maximum_interval_s=2,
                              orbit=dict(radius_m=2, body_radius_m=1, gravitational_parameter_m3_s2=8,
                                         phase_rad=0, plane_to_inertial=[1, 0, 0, 0]),
                              attitude=[dict(time_s=0, rotation=[1, 0, 0, 0])])

    def run(value, name, passed=True):
        r = execute(worker, ['--environment-transient'], 'environment-'+name, json.dumps(value).encode())
        report = json.loads(r.stdout)
        require(not r.stderr and r.returncode == (0 if passed else 1)
                and report['status'] == ('passed' if passed else 'failed'))
        return report

    result = run(fixture, 'orbit')
    events = [e for e in result['events'] if e['kind'] == 'eclipse']
    require(len(events) == 2 and abs(events[0]['time_s']-entry) < 1e-12
            and abs(events[1]['time_s']-exit_) < 1e-12 and [e['after'] for e in events] == [1, 0])
    require([e['kind'] for e in result['events'] if e['time_s'] == entry] == ['eclipse', 'schedule'])
    require(result['exchange_builds'] == 1)
    require(all(abs(row['solar_W']-(0 if row['eclipsed'] else 20)) < 1e-12
                for row in result['loading_history']))
    # Independent scalar ODE after eliminating the algebraic series resistor.
    # Capacity is 2 kg times the tabulated linear specific heat.
    t = 300.
    sigma = 5.670374419e-8
    for first, last, solar, heat in [(start, entry, 20, 5), (entry, exit_, 0, 2.5), (exit_, end, 20, 2.5)]:
        ref = solve_ivp(lambda _, y: (300+heat+solar-y-sigma*y**4)/(6+.02*(y-300)),
                        (first, last), [t], rtol=1e-11, atol=1e-12)
        require(ref.success)
        t = ref.y[0, -1]
    require(abs(result['samples'][-1]['temperature_K'][0]-t) < .02)
    require(abs(result['samples'][-1]['run_energy']['defect_J']) < 1e-7)
    require(result['samples'][0]['environment_in_W'][0] < 0)

    # At full phase an unobstructed panel normal to the body disk sees R²/r².
    body = deepcopy(fixture)
    next(e for e in body['thermal_input']['model']['entities'] if e['kind']=='environment')['background_temperature']['value'] = 250
    body['transient'].update(end=.25, output_times=[0, .25])
    body['transient'].pop('schedules')
    body['facets'][0]['vertices_m'].reverse()
    body['mission'].update(albedo=.3, body_exitance_W_m2=100)
    report = run(body, 'body-disk')
    row = report['loading_history'][0]
    require(abs(row['body_ir_W']-25) < 1e-10 and abs(row['albedo_W']-1) < 1e-10 and row['solar_W'] == 0)
    expected_power = 25+1+sigma*(.75*250**4-300**4)
    require(abs(report['samples'][0]['environment_in_W'][0]-expected_power) < 1e-10)
    chamber = deepcopy(body)
    for key in ('orbit', 'albedo', 'body_exitance_W_m2'):
        chamber['mission'].pop(key)
    report = run(chamber, 'chamber')
    require(report['exchange_builds'] == 1
            and abs(report['samples'][0]['environment_in_W'][0]-sigma*(250**4-300**4)) < 1e-10)

    # A rotating panel has exact projected power P cos(theta). The hold
    # refinement must reduce integrated heating error at fixed geometry.
    moving = deepcopy(fixture)
    moving['mission'].pop('orbit')
    next(e for e in moving['thermal_input']['model']['entities'] if e['kind']=='environment')['background_temperature']['value'] = 300
    moving['mission']['joints'] = [dict(id='panel', facets=[facet['id']], pivot_m=[0, 0, 0], axis=[0, 1, 0],
                                        angles=[dict(time_s=0, angle_rad=0), dict(time_s=1, angle_rad=math.pi/2)])]
    moving['transient'].update(end=1, output_times=[0, 1])
    moving['transient'].pop('schedules')
    errors = []
    for interval in [.5, .25, .125]:
        moving['mission']['maximum_interval_s'] = interval
        report = run(moving, f'motion-{interval}')
        rows = report['loading_history']
        require(report['exchange_builds'] == len(rows))
        for row in rows:
            require(abs(row['solar_W']-20*math.cos(math.pi*row['time_s']/2)) < 1e-11)
        integral = sum((right['time_s']-left['time_s'])*left['solar_W'] for left, right in zip(rows, rows[1:]))
        errors.append(abs(integral-40/math.pi))
    require(errors[2] < errors[1] < errors[0] and errors[2] < 1.3)
    interrupted = deepcopy(moving)
    interrupted['transient']['maximum_attempts'] = 10
    partial = run(interrupted, 'interrupted', False)
    checkpoint = partial['checkpoint']
    require(partial['reason'] == 'attempt_limit' and 0 < checkpoint['time'] < 1)
    resume = deepcopy(moving)
    resume['checkpoint'] = checkpoint
    replay = run(resume, 'restart')
    require(replay['checkpoint']['checksum'] == report['checkpoint']['checksum'])
    changed = deepcopy(moving)
    changed['checkpoint'] = checkpoint
    changed['mission']['joints'][0]['angles'][1]['angle_rad'] = 1.4
    require(run(changed, 'reject-stale-motion', False).get('code') == 'checkpoint')
    changed = deepcopy(moving)
    changed['checkpoint'] = checkpoint
    changed['facets'][0]['front']['dataset']['condition'] = 'EOL'
    require(run(changed, 'reject-stale-optics', False).get('code') == 'checkpoint')

    case = deepcopy(moving)
    case['mission'].pop('joints')
    model = case['thermal_input']['model']
    next(e for e in model['entities'] if e['kind']=='environment')['background_temperature']['value'] = 295
    node = next(e for e in model['entities'] if e['kind'] == 'node')
    load = next(e for e in model['entities'] if e['kind'] == 'load')
    case_id = '00000000-0000-4000-8000-000000000023'
    case['thermal_input']['case_id'] = case_id
    model['entities'].append(dict(id=case_id, kind='case', mode='transient',
                                  start=dict(value=0, unit='s'), end=dict(value=1, unit='s'),
                                  environment_id=environment['id'], control_ids=[], load_ids=[load['id']],
                                  overlays=[dict(entity_id=load['id'], field='power', value=dict(value=7, unit='W'))]))
    case['mission']['case_optics'] = [dict(facet_id=facet['id'], solar_absorptance=.5,
                                         ir_emittance=.75, condition='EOL')]
    result = run(case, 'case-overlay')
    require(result['samples'][0]['load_in_W'][0] == 7 and result['node_ids'][0] == node['id'])
    require(abs(result['samples'][0]['environment_in_W'][0]-(10+.75*sigma*(295**4-300**4))) < 1e-10)

    # Vehicle attitude rotates inertial source directions but leaves the
    # internal exchange geometry unchanged.
    attitude = deepcopy(moving)
    attitude['mission'].pop('joints')
    attitude['mission']['attitude'].append(dict(time_s=1, rotation=[math.sqrt(.5), 0, math.sqrt(.5), 0]))
    result = run(attitude, 'attitude')
    require(result['exchange_builds'] == 1 and abs(result['loading_history'][-1]['solar_W']) < 1e-11)
    for row in result['loading_history']:
        require(abs(row['solar_W']-20*math.cos(math.pi*row['time_s']/2)) < 1e-11)


def check(subject, native, worker, output):
    import numpy as np
    import scipy
    from scipy.integrate import dblquad
    from scipy.optimize import brentq
    from fcst_tools.radiation import wilson
    policy = json.loads((ROOT/'ci/radiation-acceptance-v1.json').read_bytes())
    statistical = json.loads((ROOT/'ci/numerical-criteria-v1.json').read_bytes())['statistical_policy']
    frozen_hashes = input_hashes()
    candidate = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    reference_versions = dict(numpy=np.__version__, scipy=scipy.__version__)
    require(reference_versions == policy['independent_backends'])
    work = output.parent/('radiation-attempt-'+str(time.time_ns()))
    work.mkdir(parents=True)
    env = dict(os.environ, PATH=str(worker.parent))
    for key in ('PYTHONPATH', 'PYTHONHOME', 'FREECAD_LIB', 'SINDAPATH', 'ESATAN'):
        env.pop(key, None)
    records, runs = [], []
    def execute(exe, arguments, stem, data=None):
        r = subprocess.run([str(exe), *map(str, arguments)], input=data, capture_output=True, cwd=ROOT, env=env, timeout=600)
        (work/(stem+'.json')).write_bytes(r.stdout)
        (work/(stem+'.log')).write_bytes(r.stderr)
        return r
    identity = execute(worker, ['--build-info'], 'worker-identity')
    require(identity.returncode == 0 and json.loads(identity.stdout)['source_revision'] == candidate)
    for case in policy['native_cases']:
        started = time.monotonic()
        r = execute(native, [case, ROOT/'tests/fixtures/thermal'], 'native-'+case)
        records.append(dict(id=case, status='passed' if r.returncode == 0 and r.stdout == b'passed\r\n' or r.returncode == 0 and r.stdout == b'passed\n' else 'failed',
                            seconds=round(time.monotonic()-started, 3)))
    for geometry, size in policy['geometry_size'].items():
        for n in statistical['samples_per_replicate']:
            for seed in statistical['seeds']:
                r = execute(subject, [geometry, seed, n, size], f'{geometry}-{seed}-{n}')
                require(r.returncode == 0 and not r.stderr)
                runs.append(validate_run(json.loads(r.stdout), geometry, seed, n, candidate))
        print(geometry+': complete fixed ensemble', flush=True)
    # Persist all samples, including misses, before assessing any aggregate.
    ensemble = assess(runs, policy, statistical, candidate)
    (work/'ensemble.json').write_text(json.dumps(ensemble, indent=2)+'\n')
    records.append(dict(id='fixed-ensemble', status=ensemble['status']))
    # Independently integrate the plate kernel reduced by translation symmetry.
    # This deterministic quadrature does not call the native intersection code.
    quadrature, error = dblquad(lambda y, x: 4*(1-x)*(1-y)/(np.pi*(1+x*x+y*y)**2), 0, 1, lambda _: 0, lambda _: 1, epsabs=1e-12, epsrel=1e-12)
    reference = policy['quantities']['plates']['lower/front->upper/front']
    require(abs(quadrature-reference) < 1e-12 and error < 1e-10)
    fixture = json.loads((ROOT/'tests/fixtures/radiation/plates.json').read_bytes())
    r = execute(worker, ['--radiation-evaluate'], 'worker-evaluation', json.dumps(fixture).encode())
    require(r.returncode == 0 and not r.stderr)
    result = json.loads(r.stdout)
    require(result['source_revision'] == candidate and result['input_sha256'] == hashlib.sha256(json.dumps(fixture).encode()).hexdigest())
    for row in result['raw']:
        for count_entry in row['counts']:
            expected = wilson(count_entry['hits'], row['samples'], 1.959963984540054)
            require(all(abs(count_entry[k]-v) < 1e-14 for k, v in zip(('estimate','lower','upper'), expected)))
    patches = result['patches']; count = len(patches)
    areas = np.array([p['area_m2'] for p in patches]); factors = np.zeros((count, count))
    for edge in result['edges']:
        i, j, g = edge['first'], edge['second'], edge['area_factor_m2']
        factors[i, j] = g/areas[i]
        factors[j, i] = g/areas[j]
    eps = np.array([.7, .4]); alpha = np.array([.3, .8])
    t = np.array(fixture['temperatures_K']); escape = np.array([p['escape'] for p in patches]); sigma = 5.670374419e-8
    eb = sigma*fixture['environment']['temperature_K']**4
    j = np.linalg.solve(np.eye(count)-(1-eps[:, None])*factors, eps*sigma*t**4+(1-eps)*escape*eb)
    direct = np.array(fixture['environment']['solar_incident_W_m2'])
    solar_j = np.linalg.solve(np.eye(count)-(1-alpha[:, None])*factors, (1-alpha)*direct)
    internal = areas*(factors@j-(1-escape)*j)
    environment = areas*(escape*(eb-j)+alpha*(factors@solar_j+direct))
    source_error = max(float(np.max(np.abs(j-np.array([p['radiosity_W_m2'] for p in patches])))),
                       float(np.max(np.abs(internal-np.array([p['internal_W'] for p in patches])))),
                       float(np.max(np.abs(environment-np.array([p['environment_W'] for p in patches])))))
    records.append(dict(id='independent-quadrature-and-radiosity', status='passed' if source_error <= policy['source_comparison_tolerance_W'] else 'failed'))
    require(max(abs(edge['area_factor_m2']-reference) for edge in result['edges']) < statistical['practical_absolute_error'])
    steady_fixture = json.loads((ROOT/'tests/fixtures/radiation/steady.json').read_bytes())
    solved = execute(worker, ['--radiation-steady'], 'worker-steady', json.dumps(steady_fixture).encode())
    require(solved.returncode == 0 and not solved.stderr)
    steady = json.loads(solved.stdout)
    # Two series conductors of 2 W/K give 1 W/K to the 300 K reservoir.
    equilibrium = brentq(lambda t: t-300 + sigma*(t**4-250**4)-5, 100, 400, xtol=1e-12)
    steady_error = abs(steady['temperatures_K'][0]-equilibrium)
    records.append(dict(id='worker-coupled-steady', status='passed' if steady_error < 1e-6 and abs(steady['energy_defect_W']) < 1e-7 else 'failed'))
    bad_steady = deepcopy(steady_fixture); bad_steady['facets'][0]['front']['ir_emittance'] = .9
    rejected = execute(worker, ['--radiation-steady'], 'reject-steady-optics', json.dumps(bad_steady).encode())
    require(rejected.returncode == 1 and json.loads(rejected.stdout)['code'] == 'radiation_mapping')
    started = time.monotonic()
    check_environment(execute, worker, steady_fixture)
    records.append(dict(id='worker-environment-transient', status='passed', seconds=round(time.monotonic()-started, 3)))
    # Actual JSON boundary mutations: no unsupported optics, malformed geometry,
    # missing node temperatures, unknown fields, nonintegral seeds or raw echo.
    mutations = []
    for kind in ('geometry', 'optics', 'node', 'unknown', 'seed'):
        f = deepcopy(fixture)
        if kind == 'geometry': f['facets'][0]['vertices_m'][1] = f['facets'][0]['vertices_m'][0]
        if kind == 'optics': f['facets'][0]['front']['ir_emittance'] = -1
        if kind == 'node': f['temperatures_K'] = [300]
        if kind == 'unknown': f['arbitrary'] = 'synthetic-untrusted-marker'
        if kind == 'seed': f['sampling']['seed'] = .5
        rejected = execute(worker, ['--radiation-evaluate'], 'reject-'+kind, json.dumps(f).encode())
        mutations.append(rejected.returncode == 1 and json.loads(rejected.stdout)['status'] == 'failed' and b'synthetic-untrusted-marker' not in rejected.stdout)
    records.append(dict(id='worker-input-boundary', status='passed' if all(mutations) else 'failed'))
    # Reproducible replay checks the whole non-timing artifact.
    replay = execute(worker, ['--radiation-evaluate'], 'worker-replay', json.dumps(fixture).encode())
    records.append(dict(id='worker-replay', status='passed' if replay.stdout == r.stdout else 'failed'))
    curves = []
    for size in policy['scaling_subdivisions']:
        for replicate in range(policy['scaling_replicates']):
            seed = statistical['seeds'][replicate]
            rscale = execute(subject, ['plates', seed, 0, size], f'scale-{size}-{replicate}')
            require(rscale.returncode == 0 and not rscale.stderr)
            lines = rscale.stdout.splitlines(keepends=True)
            require(len(lines) == len(policy['scaling_samples']))
            for n, raw in zip(policy['scaling_samples'], lines):
                (work/f'scale-{size}-{n}-{replicate}.json').write_bytes(raw)
                run = validate_run(json.loads(raw), 'plates', seed, n, candidate)
                require(run['facets'] == 4*size*size and run['storage_bytes'] <= policy['maximum_storage_bytes_per_facet']*run['facets'])
                estimates = [sum(c['hits'] for c in row['counts'])/n for row in run['rows']]
                practical_error = max(abs(p-reference) for p in estimates)
                require(practical_error <= policy['scaling_practical_error'])
                curves.append(dict(facets=run['facets'], samples=n, replicate=replicate, seed=seed,
                                   storage_bytes=run['storage_bytes'], peak_working_set_bytes=run['peak_working_set_bytes'], build_seconds=run['build_seconds'], trace_seconds=run['trace_seconds'],
                                   rays_per_second=2*n/run['trace_seconds'], maximum_absolute_error=practical_error,
                                   raw_sha256=hashlib.sha256(raw).hexdigest()))
        print(f'scaling: {4*size*size} facets complete', flush=True)
    records.append(dict(id='million-facet-scaling', status='passed'))
    report = dict(schema_version=1, profile=policy['profile'], candidate=candidate, execution_mode='fcst_native',
                  scope=policy['scope'], vendor_compatibility_qualified=False, q1_qualified=False,
                  input_sha256=input_hashes(), native_sha256=digest(subject), worker_sha256=digest(worker),native_tests_sha256=digest(native),
                  status='passed' if all(c['status'] == 'passed' for c in records) else 'failed', cases=records,
                  ensemble=ensemble, runs=[dict(geometry=x['geometry'], seed=x['seed'], samples=x['samples'],
                  build_seconds=x['build_seconds'], trace_seconds=x['trace_seconds'],
                  raw_sha256=digest(work/f"{x['geometry']}-{x['seed']}-{x['samples']}.json")) for x in runs],
                  independent_reference=dict(plate_quadrature=quadrature, quadrature_error_bound=error, maximum_radiosity_error=source_error, coupled_steady_temperature_error_K=steady_error), scaling=curves)
    report['independent_backends'] = reference_versions
    require(frozen_hashes == input_hashes())
    if report['status'] == 'passed': assess_report(report, policy, statistical, frozen_hashes, candidate)
    output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--subject', type=Path, required=True)
    p.add_argument('--native-tests', type=Path, required=True)
    p.add_argument('--worker', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args(); args.report.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = check(args.subject.resolve(), args.native_tests.resolve(), args.worker.resolve(), args.report)
    except (OSError, ValueError, KeyError, AssertionError, subprocess.SubprocessError):
        args.report.write_text(json.dumps(dict(status='failed', reason='radiation_execution_or_acceptance_failed'))+'\n')
        print('radiation: failed; raw attempt retained locally', flush=True)
        return 1
    print('radiation: '+result['status'], flush=True)
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
