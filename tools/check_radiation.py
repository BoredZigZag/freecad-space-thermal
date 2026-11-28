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
             'engine/src/thermal_execution.inc', 'engine/src/thermal_loading.inc', 'engine/worker/main.cpp',
             'tools/p0_fixture.py', 'tests/fixtures/radiation/p0-two-surfaces.json',
             'python/fcst_app/radiation_case.py', 'python/fcst_host/review.py',
             'python/fcst_cli/solve.py', 'python/fcst_cli/__main__.py', 'python/fcst_app/persistence.py',
             'python/fcst_contracts/__init__.py', 'python/fcst_contracts/bundle.json', 'engine/src/contracts.cpp']
    return {p: digest(ROOT/p) for p in paths}


def check_spectral_beam(execute, worker, candidate):
    def law(reflectance, transmittance=0):
        return dict(specular_reflectance=reflectance, transmittance=transmittance)

    black = [law(0), law(0)]

    def facet(name, node, x, z, front, back):
        return dict(id=name, node=node, vertices_m=[[x-.3, 0, z], [x+.3, 0, z], [x, .6, z]],
                    front=front, back=back)

    def run(value, name, status='passed', code=None):
        payload = json.dumps(value).encode()
        completed = execute(worker, ['--radiation-beam'], 'beam-'+name, payload)
        report = json.loads(completed.stdout)
        require(not completed.stderr and completed.returncode == (0 if status == 'passed' else 1))
        require(report['status'] == status)
        if status == 'failed':
            require(report == dict(status='failed', code=code))
            return
        require(report['source_revision'] == candidate and report['schema_version'] == 1
                and report['input_sha256'] == hashlib.sha256(payload).hexdigest())
        absorbed = {row['node']: row['power_W'] for row in report['absorbed']}
        escaped, blocked, unresolved = (report[k+'_W'] for k in ('escaped', 'blocked', 'unresolved'))
        require(all(watts >= 0 for watts in (*absorbed.values(), escaped, blocked, unresolved)))
        require(abs(math.fsum([*absorbed.values(), escaped, blocked, unresolved])-value['power_W']) < 1e-12)
        return absorbed, escaped, blocked, unresolved

    # An oblique ray hits the splitter at x=0. Reflection hits the back of
    # the upper target at x=.75 and transmission hits the lower target at x=.75.
    scene = dict(schema_version=1, wavelengths_nm=[450, 850], band=0,
                 ray=dict(origin_m=[-.75, .25, 1], direction=[.6, 0, -.8]),
                 power_W=8, maximum_interactions=16,
                 facets=[facet('splitter', 0, 0, 0, [law(.25, .5), law(.75, 0)], []),
                         facet('upper', 1, .75, 1, [], black),
                         facet('lower', 2, .75, -1, black, [])])
    require(run(scene, 'split') == ({0: 2, 1: 2, 2: 4}, 0, 0, 0))

    # The pbrt ThinDielectricBxDF formulation sums incoherent internal
    # reflections. Evaluate it independently using Snell's law and a series.
    window = deepcopy(scene)
    window['facets'][0]['front'] = [dict(refractive_index=1.5), dict(refractive_index=1.7)]
    theta = math.acos(.8)
    for band, index in enumerate((1.5, 1.7)):
        window['band'] = band
        inside = math.asin(math.sin(theta)/index)
        rs = math.sin(theta-inside)/math.sin(theta+inside)
        rp = math.tan(theta-inside)/math.tan(theta+inside)
        interface = (rs**2+rp**2)/2
        reflected = interface+math.fsum((1-interface)**2*interface**(2*i+1) for i in range(30))
        absorbed, escaped, blocked, unresolved = run(window, f'thin-dielectric-{band}')
        require(absorbed[0] == escaped == blocked == unresolved == 0)
        require(abs(absorbed[1]-8*reflected) < 1e-12 and abs(absorbed[2]-8*(1-reflected)) < 1e-12)
    window['facets'][0]['front'][1]['refractive_index'] = .9
    run(window, 'reject-index', 'failed', 'beam_optics')

    scene['band'] = 1
    require(run(scene, 'wavelength') == ({0: 2, 1: 6}, 0, 0, 0))
    scene['facets'].reverse()
    require(run(scene, 'reordered') == ({0: 2, 1: 6}, 0, 0, 0))
    scene['facets'].pop(1)
    require(run(scene, 'escape') == ({0: 2}, 6, 0, 0))
    scene['facets'].insert(1, facet('upper', 1, .75, 1, black, []))
    require(run(scene, 'blocked-back') == ({0: 2}, 0, 6, 0))

    # Alternating half-power absorption. The unresolved tail is exactly 8/2^n.
    half = [law(.5), law(.5)]
    cavity = deepcopy(scene)
    cavity.update(ray=dict(origin_m=[0, .25, .5], direction=[0, 0, -1]),
                  facets=[facet('floor', 0, 0, 0, half, []), facet('ceiling', 1, 0, 1, [], half)])
    for budget in (2, 8, 16):
        cavity['maximum_interactions'] = budget
        absorbed, escaped, blocked, unresolved = run(cavity, f'cavity-{budget}', 'incomplete')
        require(unresolved == 8/2**budget and escaped == blocked == 0)
        require(abs(absorbed[0]-(16/3)*(1-2**-budget)) < 1e-12)
        require(abs(absorbed[1]-(8/3)*(1-2**-budget)) < 1e-12)

    invalid = deepcopy(scene)
    invalid['facets'][-1]['front'][0] = law(.7, .5)
    run(invalid, 'reject-coefficients', 'failed', 'beam_optics')
    invalid = deepcopy(scene)
    invalid['wavelengths_nm'].reverse()
    run(invalid, 'reject-wavelengths', 'failed', 'beam_wavelength')
    invalid = deepcopy(scene)
    invalid['ray']['direction'] = [0, 0, -2]
    run(invalid, 'reject-direction', 'failed', 'radiation_ray')


def check_environment(execute, worker, steady_fixture, work):
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

    # Both roots are allowed to round just outside the authored window.
    clipped = deepcopy(fixture)
    first, last = math.nextafter(entry, math.inf), math.nextafter(exit_, -math.inf)
    clipped['transient'].update(start=first, end=last, output_times=[first, last])
    clipped['transient'].pop('schedules')
    result = run(clipped, 'orbit-at-run-limits')
    require([(r['time_s'], r['eclipsed']) for r in result['loading_history']] == [(first, True), (last, False)])
    require([(e['time_s'], e['after']) for e in result['events'] if e['kind'] == 'eclipse'] == [(last, 0)])

    # A small apparent disk can have an eclipse even when cos(half-width)
    # rounds to exactly one. Resolve it against the analytic sine relation.
    small = deepcopy(fixture)
    small['mission']['orbit']['body_radius_m'] = 2e-8
    small['transient'].pop('schedules')
    result = run(small, 'small-body')
    events = [e for e in result['events'] if e['kind'] == 'eclipse']
    half_width = math.asin(1e-8)
    require(len(events) == 2 and [e['after'] for e in events] == [1, 0])
    require(abs(events[0]['time_s']-(math.pi-half_width)) < 1e-13
            and abs(events[1]['time_s']-(math.pi+half_width)) < 1e-13)

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

    pair = deepcopy(moving)
    pair['sampling']['samples'] = 4096
    pair['mission']['maximum_interval_s'] = 1
    entities = pair['thermal_input']['model']['entities']
    next(e for e in entities if e['kind'] == 'environment')['solar_flux']['value'] = 0
    next(e for e in entities if e.get('classification') == 'prescribed')['temperature']['value'] = 320
    other_id = '00000000-0000-4000-8000-000000000024'
    declared = next(e for e in entities if e['kind'] == 'facet')
    entities.append(dict(declared, id=other_id))
    next(e for e in entities if e['kind'] == 'radiation')['facet_ids'].append(other_id)
    other = deepcopy(pair['facets'][0])
    gap = .002
    other.update(id=other_id, surface_id=other_id, node=2,
                 vertices_m=[[gap, y, z] for _, y, z in reversed(other['vertices_m'])])
    pair['facets'].append(other)
    pair['mission']['joints'] = [dict(id='flap', facets=[other_id], pivot_m=[gap, 0, 0], axis=[0, 0, 1],
                                    angles=[dict(time_s=0, angle_rad=0), dict(time_s=1, angle_rad=math.pi)])]
    result = run(pair, 'mutual-exchange-flip')
    initial, final = result['samples']
    # The inset right triangle retains (1-d/r)^2 of the emitting area, with
    # d=.02 m and inradius r. Its cone contributes d^2/(d^2+gap^2).
    inset, inradius = .02, (3-math.sqrt(5))/2
    lower = (1-inset/inradius)**2 * inset**2/(inset**2+gap**2)
    power = sigma*(320**4-300**4)
    require(result['exchange_builds'] == 2 and lower*power < initial['radiation_in_W'][0] <= power)
    require(abs(initial['radiation_in_W'][0]+initial['radiation_in_W'][2]) < 1e-10
            and abs(final['radiation_in_W'][0]) < 1e-10
            and abs(final['run_energy']['defect_J']) < 1e-7)

    check_portable_missions(execute, worker, work, run)


def check_portable_missions(execute, worker, work, run):
    from fcst_app.persistence import Package
    from fcst_host import review
    from p0_fixture import CASE, LOAD, NODES, SURFACES, edits, quantity, scaffold

    seed = scaffold()
    model = seed.model
    entities = {e['id']: e for e in model['entities']}
    entities.update((e['id'], e) for e in edits(model))
    flight = entities[CASE]
    environment = entities[flight['environment_id']]
    environment.update(solar_flux=quantity(20, 'W/m2'), time_origin=quantity(.75, 's'))
    radiation = next(e for e in entities.values() if e['kind'] == 'radiation')
    mission = dict(sun_direction_inertial=[0, 0, 1], maximum_interval_s=.5,
                   attitude=[dict(time_s=0, rotation=[1, 0, 0, 0])],
                   orbit=dict(radius_m=2, body_radius_m=1, gravitational_parameter_m3_s2=8,
                              phase_rad=0, plane_to_inertial=[math.sqrt(.5),0,math.sqrt(.5),0]),
                   case_optics=[dict(facet_id=SURFACES[0], solar_absorptance=.5, ir_emittance=.6, condition='BOL')])
    control_id = review.uid(143)
    entities[control_id] = dict(id=control_id, kind='control', sensor_node_id=NODES[0], load_id=LOAD,
                                on_below=quantity(400, 'K'), off_above=quantity(410, 'K'))
    flight.update(end=quantity(4, 's'), mission=mission, control_ids=[control_id],
                  overlays=[dict(entity_id=LOAD, field='power', value=quantity(7, 'W'))])
    chamber_id, chamber_env, chamber_group = [review.uid(n) for n in (140, 141, 142)]
    entities[chamber_env] = dict(environment, id=chamber_env, solar_flux=quantity(0, 'W/m2'),
                                 background_temperature=quantity(320, 'K'))
    entities[chamber_group] = dict(radiation, id=chamber_group, environment_id=chamber_env)
    entities[chamber_id] = dict(flight, id=chamber_id, environment_id=chamber_env, load_ids=[], control_ids=[], overlays=[],
                               mission=dict(sun_direction_inertial=[0, 0, 1], maximum_interval_s=4,
                                            attitude=mission['attitude'],
                                            case_optics=[dict(mission['case_optics'][0], ir_emittance=.85, condition='EOL')]))
    model['entities'] = list(entities.values())
    model['source_maps'] = [dict(id=review.uid(144), version='1.0.0', source_revision='0'*64,
                                 source_tool='synthetic', source_version='1.0',
                                 entries=[dict(namespace='example', handle='panel', entity_id=SURFACES[0])])]
    artifacts = [(r['id'], r['role'], r['artifact']['path'], seed.files[r['artifact']['path']], r['dependencies'])
                 for r in seed.manifest['artifacts'] if r['role'] == 'mesh']
    path = work/'mission.fcst'
    path.write_bytes(Package.create(model, artifacts).zip_bytes())
    package = Package.open(path)
    require(package.model['source_maps'] == model['source_maps'])
    flag, flight_request = review.request(package.model, review.DEFAULT_SETTINGS, CASE,
                                          read_mesh=package.files.__getitem__)
    require(flag == '--environment-transient')
    hot = run(flight_request, 'portable-flight')
    cli = execute(sys.executable, ['-c', 'import sys; sys.path.insert(0, "python"); '
                                  'from fcst_cli.__main__ import main; sys.exit(main())',
                                  'solve-case', path, '--case', chamber_id, '--worker', worker], 'portable-chamber-cli')
    require(cli.returncode == 0 and not cli.stderr)
    chamber = json.loads(cli.stdout)
    # +x in the orbital plane maps to -z inertially, centering the shadow
    # at orbital phase zero. The TAI origin shifts both crossings by .75 s.
    events = [e for e in hot['events'] if e['kind'] == 'eclipse']
    require(len(events) == 2 and [e['after'] for e in events] == [1, 0])
    require(abs(events[0]['time_s']-(.75-math.pi/6)) < 1e-12)
    require(abs(events[1]['time_s']-(.75+math.pi/6)) < 1e-12)
    require(hot['node_ids'] == chamber['node_ids'] == NODES and hot['model_hash'] == chamber['model_hash'])
    require(hot['samples'][0]['load_in_W'][0] == 7 and chamber['samples'][0]['load_in_W'][0] == 0)
    require(hot['samples'][-1]['duty_cycles'][control_id] == 1 and not chamber['samples'][-1]['duty_cycles'])
    require(hot['environment_dependency_sha256'] != chamber['environment_dependency_sha256']
            and all(r['solar_W'] == 0 and not r['eclipsed'] for r in chamber['loading_history']))
    flight_request['mission'] = dict(flight_request['mission'], maximum_interval_s=1)
    require(run(flight_request, 'portable-reject-substituted-mission', False).get('code') == 'environment_case')


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
    check_environment(execute, worker, steady_fixture, work)
    records.append(dict(id='worker-environment-transient', status='passed', seconds=round(time.monotonic()-started, 3)))
    started = time.monotonic()
    check_spectral_beam(execute, worker, candidate)
    records.append(dict(id='worker-spectral-beam', status='passed', seconds=round(time.monotonic()-started, 3)))
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
