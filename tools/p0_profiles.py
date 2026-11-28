# SPDX-License-Identifier: MIT OR Apache-2.0
"""Run the CLI/API and real stdio MCP paths against the same synthetic model."""
from hashlib import sha256
import json
import os
import subprocess
import sys
import time

from fcst_app.persistence import Package, PersistenceError, encode, publication_lock, semantic_hash
from fcst_app.store import ProjectStore
from fcst_host.review import DEFAULT_SETTINGS
from p0_fixture import CASE, FIXTURE, MODEL, NODES, PROJECT, ROOT, edits, scaffold, temperature_hash, temperature_series


def cli(arguments):
    return json.loads(subprocess.check_output([sys.executable, '-m', 'fcst_cli', *map(str, arguments)],
        env=dict(os.environ, PYTHONPATH=str(ROOT/'python')), timeout=60))


def view_factor(order):
    # Integrate the parallel triangle kernel over two independent unit
    # squares with Duffy transformations. This uses no production ray data.
    import numpy as np
    from numpy.polynomial.legendre import leggauss

    abscissa, weights = leggauss(order)
    abscissa, weights = abscissa/2 + .5, weights/2
    u, v = np.meshgrid(abscissa, abscissa, indexing='ij')
    x, y = u.ravel(), ((1-u)*v).ravel()
    weight = ((1-u)*np.outer(weights, weights)).ravel()
    gap = MODEL['vertices_m'][3][2] - MODEL['vertices_m'][0][2]
    radius_squared = (x[:, None]-x)**2 + (y[:, None]-y)**2 + gap**2
    return float(np.sum(np.outer(weight, weight)*gap**2/(np.pi*radius_squared**2)) / MODEL['area_m2'])


def oracle(result, criteria):
    import numpy as np
    from scipy.integrate import solve_ivp

    orders = criteria['quadrature_orders']
    coarse, factor = (view_factor(order) for order in orders)
    assert 0 < factor < 1 and abs(factor-coarse) <= criteria['quadrature_agreement']
    area, sigma = MODEL['area_m2'], 5.670374419e-8
    capacity = np.asarray(MODEL['capacity_J_K'])

    def powers(temperatures):
        first, second = temperatures
        q_internal = area*sigma*factor*(second**4-first**4)
        radiation = np.array([q_internal, -q_internal])
        environment = area*sigma*(1-factor)*(MODEL['background_K']**4-temperatures**4)
        return radiation, environment

    def rate(_, temperatures):
        radiation, environment = powers(temperatures)
        q = MODEL['conductance_W_K']*(temperatures[1]-temperatures[0])
        return (np.array([q+MODEL['load_W'], -q]) + radiation + environment) / capacity

    times, values = temperature_series(result)
    duration = MODEL['duration_s']
    assert times == [duration*i/(criteria['samples']-1) for i in range(criteria['samples'])]
    reference = solve_ivp(rate, (0, duration), MODEL['temperature_K'], method='DOP853',
                          t_eval=times, rtol=1e-11, atol=1e-11)
    assert reference.success
    expected_powers = [powers(row) for row in reference.y.T]
    def energy_defect(sample):
        ledger = sample['run_energy']
        storage = sum(c*(t-t0) for c,t,t0 in zip(capacity, sample['temperature_K'], MODEL['temperature_K']))
        delivered = sum(ledger['external_energy_J']) + sum(ledger['boundary_energy_J'])
        return max(abs(storage-delivered), abs(ledger['defect_J']))

    metrics = dict(temperature_error_K=float(np.max(abs(np.array(values)-reference.y.T))),
        radiation_power_error_W=max(float(np.max(abs(s['radiation_in_W']-r))) for s,(r,_) in zip(result['samples'],expected_powers)),
        environment_power_error_W=max(float(np.max(abs(s['environment_in_W']-e))) for s,(_,e) in zip(result['samples'],expected_powers)),
        energy_defect_J=max(energy_defect(s) for s in result['samples']),
        view_factor=factor, quadrature_difference=abs(factor-coarse))
    assert all(metrics[key] <= criteria[key] for key in ('temperature_error_K','radiation_power_error_W',
                                                        'environment_power_error_W','energy_defect_J')), metrics
    assert result['exchange_builds'] == 1
    return metrics


def check(root, worker, client_factory):
    root.mkdir()
    criteria = json.loads((ROOT/'ci/p0-acceptance.json').read_bytes())
    initial = scaffold()
    fixture_hash = sha256(FIXTURE.read_bytes()).hexdigest()
    mesh_hash = next(e['artifact']['sha256'] for e in initial.model['entities'] if e['kind']=='mesh')
    change = dict(upsert=edits(initial.model), delete=[])
    # Build via the shared transactional API, then reopen and solve through the CLI.
    with ProjectStore.create(root/'cli.db', package=initial) as store:
        model_hash = store.apply('local', {'changes.apply'}, PROJECT, 0, 'build', change)['semantic_hash']
        store.save(root/'cli.fcst')
    assert cli(['project-inspect', root/'cli.fcst'])['semantic_hash'] == model_hash
    result = cli(['solve-case', root/'cli.fcst', '--case', CASE, '--worker', worker])
    assert result['model_hash'] == model_hash
    metrics = oracle(result, criteria)
    times, values = temperature_series(result)
    actor = 'p0-acceptance'

    def config(name):
        path = root/(name+'.json')
        path.write_bytes(encode(dict(database=name+'.db', worker=str(worker), policy=dict(
            project_id=PROJECT, case_ids=[CASE], root=str(root), actor=actor, allow_export=True))))
        return path

    def wait_scheduler(name):
        deadline = time.monotonic()+10
        while True:
            try:
                with publication_lock(root/(name+'.db.scheduler')):
                    return
            except PersistenceError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.05)

    with ProjectStore.create(root/'build.db', package=initial):
        pass
    client = client_factory(config('build'))
    try:
        assert client.request('server/discover')['resultType'] == 'complete'
        built = client.call('changes_apply', dict(project_id=PROJECT, expected_revision=0,
                                                  idempotency_key='build', changes=change))
        assert built['semantic_hash'] == model_hash
        client.call('snapshot_create', dict(project_id=PROJECT, expected_revision=built['revision'], destination='mcp.fcst'))
    finally:
        client.close()
        wait_scheduler('build')
    with ProjectStore.create(root/'reopen.db', package=Package.open(root/'mcp.fcst')) as reopened:
        assert semantic_hash(reopened.snapshot()) == model_hash
    config_path = config('reopen')
    submit = dict(project_id=PROJECT, expected_revision=built['revision'], case_id=CASE,
                  idempotency_key='solve', options=DEFAULT_SETTINGS)
    try:
        client = client_factory(config_path)
        try:
            job = client.call('solve_submit', submit)
        finally:
            client.close()
        client = client_factory(config_path)
        try:
            replay = client.call('solve_submit', submit)
            assert replay['job_id'] == job['job_id']
            query = dict(project_id=PROJECT, job_id=job['job_id'])
            deadline = time.monotonic()+30
            while True:
                job = client.call('jobs_get', query)
                if job['state'] not in ('queued','running','cancelling') or time.monotonic() >= deadline:
                    break
                time.sleep(.05)
            assert job['state']=='succeeded' and job['semantic_hash']==model_hash and job['execution_mode']=='fcst_native', job
            data = client.call('results_query', dict(**query, quantity='temperature', entity_ids=NODES))
        finally:
            client.close()
    finally:
        wait_scheduler('reopen')
    assert data['node_ids'] == NODES and data['time'] == times and data['next_offset'] is None and not data['historical']
    parity_error = max(abs(a-b) for native, mcp in zip(values, data['values']) for a,b in zip(native,mcp))
    assert parity_error <= criteria['parity_error_K']
    return dict(model_hash=model_hash, fixture_hash=fixture_hash, mesh_hash=mesh_hash, samples=len(times),
                cli_temperature_hash=temperature_hash(times,values),
                mcp_temperature_hash=temperature_hash(data['time'],data['values']), parity_error_K=parity_error,
                reconnect=True, metrics=metrics)
