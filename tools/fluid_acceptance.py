# SPDX-License-Identifier: MIT OR Apache-2.0
"""Independent verification of native advanced fluid worker operations."""
import hashlib
import json
import math
import subprocess


def run_worker(worker, candidate, env, operation, request, expected_error=None, *, encoder=None):
    payload = encoder(request) if encoder else json.dumps(request, allow_nan=False).encode()
    result = subprocess.run([str(worker), operation], input=payload, capture_output=True,
                            timeout=20, env=env)
    report = json.loads(result.stdout)
    assert not result.stderr
    if expected_error:
        assert result.returncode == 1 and report == dict(status='failed', code=expected_error)
        return
    assert result.returncode == 0 and report['status'] == 'passed'
    assert report['schema_version'] == 1 and report['execution_mode'] == 'fcst_native'
    assert report['source_revision'] == candidate and report['input_sha256'] == hashlib.sha256(payload).hexdigest()
    return report


def check(worker, candidate, env):
    from scipy.integrate import quad
    def run(request, expected_error=None):
        report = run_worker(worker, candidate, env, '--fluid-duct', request, expected_error)
        if expected_error:
            return
        assert report['mass_flow_kg_s'] == request['mass_flow_kg_s']
        rows = report['stations']
        assert [row['position_m'] for row in rows] == request['positions_m']
        return rows

    # Three scalar observations from the MOOSE pressure_drop regression. The
    # case and gold file are pinned in docs/advanced-physics.md.
    moose = dict(schema_version=1, length_m=1, area_m2=.176752,
                 hydraulic_diameter_m=math.sqrt(4*.176752/math.pi), darcy_friction_factor=1e4,
                 mass_flow_kg_s=1, outlet_pressure_Pa=7e6, inlet_temperature_K=300,
                 gas_constant_J_kg_K=8.3144598/.002016, gamma=1.3066, positions_m=[.005, .495, .995])
    reference_pressures = [7058966.6203404, 7029967.5236528, 7000297.2669155]
    for row, expected in zip(run(moose), reference_pressures, strict=True):
        pressure_drop = expected-moose['outlet_pressure_Pa']
        assert abs(row['pressure_Pa']-expected)/pressure_drop < .0035

    # At higher Mach number the kinetic-energy term matters. Independently
    # integrate the momentum equation between actual returned velocities.
    duct = dict(schema_version=1, length_m=2, area_m2=.004, hydraulic_diameter_m=.08,
                darcy_friction_factor=.04, mass_flow_kg_s=.65, outlet_pressure_Pa=101325,
                inlet_temperature_K=300, gas_constant_J_kg_K=287, gamma=1.4,
                positions_m=[0, .25, 1, 2])
    rows = run(duct)
    assert rows[0]['temperature_K'] == duct['inlet_temperature_K']
    assert rows[-1]['pressure_Pa'] == duct['outlet_pressure_Pa']
    assert rows[0]['pressure_Pa'] > rows[-1]['pressure_Pa'] and rows[0]['temperature_K'] > rows[-1]['temperature_K']
    gas_constant = duct['gas_constant_J_kg_K']
    cp = gas_constant*duct['gamma']/(duct['gamma']-1)
    speed_in = rows[0]['velocity_m_s']
    enthalpy = cp*duct['inlet_temperature_K'] + speed_in**2/2
    for row in rows:
        speed, density, temperature = (row[key] for key in ('velocity_m_s', 'density_kg_m3', 'temperature_K'))
        assert math.isclose(row['pressure_Pa'], density*gas_constant*temperature, rel_tol=2e-14)
        assert math.isclose(density*speed*duct['area_m2'], duct['mass_flow_kg_s'], rel_tol=2e-14)
        assert math.isclose(cp*temperature+speed**2/2, enthalpy, rel_tol=2e-14)
        assert math.isclose(row['stagnation_enthalpy_J_kg'], enthalpy, rel_tol=2e-14)
        length, _ = quad(lambda u: (gas_constant*enthalpy/cp-(1-gas_constant/(2*cp))*u**2)/u**3,
                         speed_in, speed, epsabs=1e-12, epsrel=1e-12)
        length *= 2*duct['hydraulic_diameter_m']/duct['darcy_friction_factor']
        assert abs(length-row['position_m']) < 1e-11

    no_friction = run(dict(duct, darcy_friction_factor=0))
    for row in no_friction:
        assert row['pressure_Pa'] == duct['outlet_pressure_Pa'] and row['temperature_K'] == duct['inlet_temperature_K']
    stopped = run(dict(duct, mass_flow_kg_s=0))
    for row in stopped:
        assert row['velocity_m_s'] == 0 and row['pressure_Pa'] == duct['outlet_pressure_Pa']
    run(dict(duct, mass_flow_kg_s=10), 'fluid_subsonic_domain')
    run(dict(duct, positions_m=[-1]), 'fluid_station')
    run(dict(duct, gamma=1), 'fluid_duct_input')


def check_flow_boiling(worker, candidate, env):
    def run(request, error=None):
        return run_worker(worker, candidate, env, '--fluid-heated-stream', request, error)

    # Isobaric reduction of OpenFLUME's nitrogen flow-boiling regression.
    # Thermodynamic scalars and independent P/H flash outputs are from CoolProp 6.6.0.
    saturation = dict(pressure_Pa=300000, temperature_K=87.90726165451751,
                      liquid_enthalpy_J_kg=-100002.9578523641, vapor_enthalpy_J_kg=83958.9047132675,
                      liquid_density_kg_m3=755.7118027910059, vapor_density_kg_m3=12.670252507020633,
                      liquid_cp_J_kg_K=2066.0241202361176, vapor_cp_J_kg_K=1233.5335294931997,
                      minimum_temperature_K=74.9, maximum_temperature_K=100)
    boiling = dict(schema_version=1, saturation=saturation, mass_flow_kg_s=.1,
                   inlet_enthalpy_J_kg=-126669.67175679601, segment_heat_W=[5000]*4)
    output = run(boiling)
    assert output['pressure_Pa'] == 300000 and output['mass_flow_kg_s'] == .1
    inlet, *heated = output['stations']
    assert math.isclose(inlet['temperature_K'], 75, abs_tol=1e-12, rel_tol=0)
    assert inlet['phase'] == 'liquid' and inlet['quality'] is None and inlet['density_kg_m3'] is None
    qualities = [.12683762694152717, .3986330920595303, .6704285571775334, .9422240222955365]
    densities = [89.55694338297376, 31.000168561875856, 18.744248503257403, 13.433365838153039]
    for i, (state, quality, density) in enumerate(zip(heated, qualities, densities, strict=True), 1):
        assert state['phase'] == 'saturated' and state['temperature_K'] == saturation['temperature_K']
        assert math.isclose(state['quality'], quality, rel_tol=1e-12)
        assert math.isclose(state['density_kg_m3'], density, rel_tol=1e-12)
        assert state['heat_added_W'] == i*5000
        assert abs(.1*(state['enthalpy_J_kg']-inlet['enthalpy_J_kg'])-i*5000) < 1e-10

    # Exact endpoint and reversal checks, independent of external property data.
    synthetic = dict(schema_version=1, saturation=dict(pressure_Pa=100000, temperature_K=350,
                     liquid_enthalpy_J_kg=-10000, vapor_enthalpy_J_kg=90000, liquid_density_kg_m3=1000,
                     vapor_density_kg_m3=10, liquid_cp_J_kg_K=1000, vapor_cp_J_kg_K=1000,
                     minimum_temperature_K=300, maximum_temperature_K=400),
                     mass_flow_kg_s=.5, inlet_enthalpy_J_kg=-20000,
                     segment_heat_W=[5000, 25000, 25000, 5000, -60000])
    states = run(synthetic)['stations']
    assert [row['phase'] for row in states] == ['liquid', 'saturated', 'saturated', 'saturated', 'vapor', 'liquid']
    assert [row['temperature_K'] for row in states] == [340, 350, 350, 350, 360, 340]
    assert [row['quality'] for row in states] == [None, 0, .5, 1, None, None]
    assert states[0] == states[-1]
    run(dict(synthetic, segment_heat_W=[100000]), 'fluid_temperature_domain')
    run(dict(synthetic, mass_flow_kg_s=0), 'fluid_heated_input')
    run(dict(synthetic, saturation=dict(synthetic['saturation'], vapor_density_kg_m3=1000)), 'fluid_heated_input')


def check_heat_pipe(worker, candidate, env):
    def run(request, error=None):
        return run_worker(worker, candidate, env, '--heat-pipe-capillary', request, error)

    # NASA NTRS 20230009276, slides 12, 16, 18, and 19. Calibrate the
    # capillary head from the zero-g W-inch figure, then predict adverse tilt.
    inch = .0254
    pipe = dict(schema_version=1, length_m=60*inch, evaporator_length_m=10*inch,
                condenser_length_m=20*inch, evaporator_elevation_m=0,
                capillary_head_Pa=4200*(.032+.0006), liquid_density_kg_m3=652.0140983939064,
                gravity_m_s2=9.80665, liquid_loss_Pa_W_m=.032/inch,
                vapor_loss_Pa_W_m=.0006/inch, heat_load_W=20)
    zero_g = run(pipe)
    assert math.isclose(zero_g['effective_length_m'], 45*inch, rel_tol=1e-14)
    assert abs(zero_g['power_limit_W']-93) < .5
    assert math.isclose(zero_g['liquid_loss_Pa'], 28.8, rel_tol=1e-14)
    assert math.isclose(zero_g['vapor_loss_Pa'], .54, rel_tol=1e-14)
    assert zero_g['capillary_supported'] is True
    adverse = dict(pipe, evaporator_elevation_m=.1*inch)
    tilted = run(adverse)
    assert abs(tilted['power_limit_W']-84) < 3
    assert tilted['power_limit_W'] < zero_g['power_limit_W']
    assert math.isclose(tilted['margin_Pa'], pipe['capillary_head_Pa']-tilted['hydrostatic_head_Pa']
                        -tilted['liquid_loss_Pa']-tilted['vapor_loss_Pa'], abs_tol=1e-12)
    assert run(dict(adverse, heat_load_W=90))['capillary_supported'] is False
    assert run(dict(adverse, evaporator_elevation_m=-.1*inch))['power_limit_W'] > zero_g['power_limit_W']
    static_dry = run(dict(adverse, evaporator_elevation_m=.1, heat_load_W=0))
    assert static_dry['power_limit_W'] == 0 and static_dry['capillary_supported'] is False
    run(dict(pipe, condenser_length_m=pipe['length_m']), 'heat_pipe_input')
    run(dict(pipe, liquid_loss_Pa_W_m=0, vapor_loss_Pa_W_m=0), 'heat_pipe_resistance')


def check_heat_pipe_hardware(worker, candidate, env):
    # NASA NTRS 19720018727, Figure 2 (printed page 37). The text
    # defines transport as power times midpoint spacing, in W-in.
    # Fit head and total loss using two points on each measured curve.
    inch, density, gravity = .0254, 610, 9.80665

    def predict(level, tilted, transport, test_tilt):
        loss_per_W_m = density*gravity*(tilted*inch)/(inch*(level-transport))
        pipe = dict(schema_version=1, length_m=48*inch, evaporator_length_m=12*inch,
                    condenser_length_m=12*inch, evaporator_elevation_m=test_tilt*inch,
                    capillary_head_Pa=level*inch*loss_per_W_m, liquid_density_kg_m3=density,
                    gravity_m_s2=gravity, liquid_loss_Pa_W_m=loss_per_W_m, vapor_loss_Pa_W_m=0,
                    heat_load_W=0)
        result = run_worker(worker, candidate, env, '--heat-pipe-capillary', pipe)
        assert math.isclose(result['effective_length_m'], 36*inch, rel_tol=1e-14)
        return result['power_limit_W']*result['effective_length_m']/inch

    # Screen over grooves, pipe 4. Interior points were held out of the fit.
    for tilt, observed in ((.2, 3125), (.3, 2675)):
        assert abs(predict(4300, .5, 1800, tilt)-observed) <= 200
    # Plain grooves, pipe 8. Keep the larger measured discrepancy visible.
    residual = 1450-predict(5750, .2, 3125, .4)
    assert 750 <= residual <= 1150


def check_vessel(worker, candidate, env):
    def run(request, error=None):
        return run_worker(worker, candidate, env, '--fluid-vessel', request, error)

    def interval(duration, inflow=0, enthalpy=0, outlet=0, vent=0, heating=0):
        return dict(duration_s=duration, inlet_mass_flow_kg_s=inflow, inlet_enthalpy_J_kg=enthalpy,
                    outlet_pressure_Pa=outlet, outlet_conductance_kg_s_Pa=vent, wall_power_W=heating)

    # Rigid adiabatic nitrogen filling, published SINDA/FLUINT Table 1.
    # The feed rate affects elapsed time but cancels from the T(P) relation.
    kelvin = lambda f: (f-32)*5/9+273.15
    psi = 6894.757293168
    pressure, temperature, volume, gas, gamma = 100*psi, kelvin(70), .5*.3048**3, 296.8, 1.4
    cv, flow = gas/(gamma-1), .02
    mass = pressure*volume/(gas*temperature)
    h = (cv+gas)*temperature
    duration = 9*pressure*volume/((gamma-1)*flow*h)
    fill = dict(schema_version=1, volume_m3=volume, initial_mass_kg=mass,
                initial_internal_energy_J=mass*cv*temperature, initial_wall_temperature_K=temperature,
                wall_capacity_J_K=25, wall_conductance_W_K=0, maximum_step_s=.2,
                properties=dict(kind='ideal_gas', gas_constant_J_kg_K=gas, cv_J_kg_K=cv),
                schedule=[interval(duration, flow, h)])
    last = run(fill)['samples'][-1]
    assert math.isclose(last['pressure_Pa'], 1000*psi, rel_tol=1e-12)
    assert math.isclose(last['temperature_K'], temperature*10/(1+9/gamma), rel_tol=1e-12)
    assert abs(last['temperature_K']-kelvin(253.02)) < .5
    assert abs(last['energy_defect_J']) < 1e-7 and abs(last['mass_defect_kg']) < 1e-12

    # Independent pressure and temperature data are from CoolProp 6.6.0
    # saturation queries and direct D/U flashes in a SciPy time integration.
    table = [
        (100000, 77.243499730696, .001239786531, .219467603874, -122370.81790490531, 55126.086752751275),
        (150000, 80.844647600874, .001265827972, .150859135742, -115019.32877956194, 57059.70692466382),
        (200000, 83.625771443592, .001287340403, .115453002013, -109298.81133967191, 58426.03654169384),
        (250000, 85.92652613421, .001306184538, .093702500098, -104532.23861072877, 59462.89580934506),
        (285000, 87.340457802486, .001318285597, .08283862984, -101585.36010526058, 60054.51825528819),
        (300000, 87.907261654518, .001323255765, .078925025326, -100399.93458197422, 60281.39711554845),
        (350000, 89.657494812052, .001339061901, .06820068508, -96723.40435664266, 60942.99764111306),
        (400000, 91.23271574439, .001353922256, .060046264941, -93391.97533575576, 61485.46457917421),
        (450000, 92.669897829381, .00136805254, .053626605025, -90331.88218944285, 61933.75111698527),
        (500000, 93.995017846619, .001381606442, .048434699605, -87491.27651927315, 62305.24130789919),
    ]
    keys = ('pressure_Pa', 'temperature_K', 'liquid_volume_m3_kg', 'vapor_volume_m3_kg',
            'liquid_energy_J_kg', 'vapor_energy_J_kg')
    properties = dict(kind='saturation_table', points=[dict(zip(keys, row, strict=True)) for row in table])
    blowdown = dict(fill, volume_m3=.002, initial_mass_kg=.11873939365139105,
                    initial_internal_energy_J=-8105.58657553057, initial_wall_temperature_K=95,
                    wall_conductance_W_K=.3, properties=properties,
                    schedule=[interval(2, outlet=150000, vent=2e-8, heating=4), interval(1, outlet=150000)])
    initial, vented, closed = run(blowdown)['samples']
    assert [s['time_s'] for s in (initial, vented, closed)] == [0, 2, 3]
    assert abs(initial['pressure_Pa']-300000) < 1e-3
    assert initial['mass_kg'] > vented['mass_kg'] == closed['mass_kg']
    assert closed['pressure_Pa'] > vented['pressure_Pa']
    for row, expected in zip((vented, closed), [(288517.949131, 87.4753315, .203361567),
                                                (288633.449227, 87.4797390, .203439217)], strict=True):
        assert abs(row['pressure_Pa']-expected[0]) < 500
        assert abs(row['temperature_K']-expected[1]) < .05
        assert abs(row['quality']-expected[2]) < .001
        assert abs(row['mass_kg']-.11297141183346904) < 3e-5
        assert abs(row['energy_defect_J']) < 1e-8 and abs(row['mass_defect_kg']) < 1e-13
    # Measure time refinement independently of the saturation-table interpolation error.
    coarse, medium, fine, reference = [run(dict(blowdown, maximum_step_s=dt))['samples'][-1]['pressure_Pa']
                                       for dt in (1, .5, .25, .015625)]
    assert abs(fine-reference) < abs(medium-reference)/8 < abs(coarse-reference)/64
    run(dict(blowdown, initial_internal_energy_J=0), 'vessel_saturation_domain')
    bad_table = [dict(row) for row in properties['points']]
    bad_table[1]['liquid_energy_J_kg'] = bad_table[0]['liquid_energy_J_kg']
    run(dict(blowdown, properties=dict(properties, points=bad_table)), 'vessel_properties')
    run(dict(fill, maximum_step_s=1e-12), 'vessel_step_limit')


def check_vessel_network(worker, candidate, env):
    from scipy.integrate import solve_ivp

    def run(request, error=None):
        return run_worker(worker, candidate, env, '--fluid-vessel-network', request, error)

    # A manufactured saturation table with an analytic (V/M,U/M) inverse.
    # With constant phase volumes and latent energy, pressure is affine in
    # specific energy and quality. The oracle uses no native flash code.
    liquid_volume, vapor_volume, latent, slope = .001, .1, 20000, .3
    anchor = 300000
    points = [dict(pressure_Pa=p, temperature_K=350+(p-anchor)/20000,
                   liquid_volume_m3_kg=liquid_volume, vapor_volume_m3_kg=vapor_volume,
                   liquid_energy_J_kg=slope*(p-anchor), vapor_energy_J_kg=slope*(p-anchor)+latent)
              for p in (250000, 300000, 400000)]
    volumes = [.002, .002, .002]
    masses = [.12, .1, .08]
    pressures = [310000, 290000, 300000]
    capacity, wall_conductance = 20, 15
    vessels = []
    initial = []
    for volume, mass, pressure in zip(volumes, masses, pressures, strict=True):
        quality = (volume/mass-liquid_volume)/(vapor_volume-liquid_volume)
        energy = mass*(slope*(pressure-anchor)+latent*quality)
        wall = 350+(pressure-anchor)/20000
        vessels.append(dict(volume_m3=volume, initial_mass_kg=mass, initial_internal_energy_J=energy,
                            initial_wall_temperature_K=wall, wall_capacity_J_K=capacity,
                            wall_conductance_W_K=wall_conductance))
        initial.extend([mass, energy, wall])
    links = [{'from': 0, 'to': 1, 'conductance_kg_s_Pa': 1e-7},
             {'from': 1, 'to': 2, 'conductance_kg_s_Pa': 8e-8}]
    schedule = [dict(duration_s=1, wall_power_W=[0, 0, 0], opening=[1, 1]),
                dict(duration_s=2, wall_power_W=[0, 600, 0], opening=[0, 0]),
                dict(duration_s=1, wall_power_W=[0, 0, 0], opening=[.5, 1])]
    request = dict(schema_version=1, maximum_step_s=.025, properties=dict(kind='saturation_table', points=points),
                   vessels=vessels, links=links, schedule=schedule)

    def equilibrium(values):
        quality = [(volumes[i]/values[3*i]-liquid_volume)/(vapor_volume-liquid_volume) for i in range(3)]
        pressure = [anchor+(values[3*i+1]/values[3*i]-latent*quality[i])/slope for i in range(3)]
        return quality, pressure

    def rate(values, interval):
        _, pressure = equilibrium(values)
        transfer = []
        for i in range(3):
            heat = wall_conductance*(values[3*i+2]-(350+(pressure[i]-anchor)/20000))
            transfer.extend([0, heat, (interval['wall_power_W'][i]-heat)/capacity])
        for i, opening in enumerate(interval['opening']):
            flow = opening*links[i]['conductance_kg_s_Pa']*(pressure[i]-pressure[i+1])
            donor = i if flow >= 0 else i+1
            advected = flow*(values[3*donor+1]+pressure[donor]*volumes[donor])/values[3*donor]
            transfer[3*i] -= flow
            transfer[3*(i+1)] += flow
            transfer[3*i+1] -= advected
            transfer[3*(i+1)+1] += advected
        return transfer

    reference = [initial]
    for interval in schedule:
        solution = solve_ivp(lambda _, y: rate(y, interval), [0, interval['duration_s']], reference[-1],
                             rtol=1e-12, atol=1e-13)
        assert solution.success
        reference.append(solution.y[:, -1])
    rows = run(request)['samples']
    assert [s['time_s'] for s in rows] == [0, 1, 3, 4]
    assert rows[0]['link_flow_kg_s'][0] > 0 and rows[-1]['link_flow_kg_s'][0] < 0
    assert rows[2]['link_flow_kg_s'] == [0, 0]
    for left, right in zip(rows[1]['vessels'], rows[2]['vessels'], strict=True):
        assert left['mass_kg'] == right['mass_kg']
    for row, expected in zip(rows, reference, strict=True):
        assert abs(row['mass_defect_kg']) < 1e-13 and abs(row['energy_defect_J']) < 1e-8
        quality, pressure = equilibrium(expected)
        for i, node in enumerate(row['vessels']):
            assert abs(node['mass_kg']-expected[3*i]) < 1e-8
            assert abs(node['internal_energy_J']-expected[3*i+1]) < .001
            assert abs(node['wall_temperature_K']-expected[3*i+2]) < 1e-5
            assert abs(node['pressure_Pa']-pressure[i]) < .02
            assert abs(node['quality']-quality[i]) < 1e-7
    errors = []
    expected_pressure = equilibrium(reference[-1])[1]
    for step in (.5, .25, .125):
        final = run(dict(request, maximum_step_s=step))['samples'][-1]['vessels']
        errors.append(max(abs(node['pressure_Pa']-p) for node, p in zip(final, expected_pressure, strict=True)))
    assert errors[2] < errors[1]/8 < errors[0]/64
    run(dict(request, links=[dict(links[0], to=0)]), 'vessel_network_link')
    run(dict(request, schedule=[dict(schedule[0], opening=[1, 2])]), 'vessel_network_schedule')
    run(dict(request, maximum_step_s=1e-12), 'vessel_step_limit')


def check_network_momentum_and_persistence(worker, candidate, env, project_fixture):
    from scipy.integrate import solve_ivp
    from tempfile import TemporaryDirectory
    from pathlib import Path
    from fcst_app.network_runs import load_network_run, store_network_run
    from fcst_app.persistence import Package, PersistenceError, encode
    from fcst_app.store import ProjectStore

    gas, cv, volume, temperature = 287, 717.5, .01, 300
    conductance, inertance = 2e-6, 2e6
    vessels = []
    for pressure in (101000, 99000):
        mass = pressure*volume/(gas*temperature)
        vessels.append(dict(volume_m3=volume, initial_mass_kg=mass, initial_internal_energy_J=mass*cv*temperature,
                            initial_wall_temperature_K=temperature, wall_capacity_J_K=25, wall_conductance_W_K=0))
    schedule = [dict(duration_s=duration, wall_power_W=[0, 0], opening=[opening])
                for duration, opening in ((.6, 1), (.05, .5), (.5, 0), (.1, 1))]
    request = dict(schema_version=1, maximum_step_s=.005,
                   properties=dict(kind='ideal_gas', gas_constant_J_kg_K=gas, cv_J_kg_K=cv), vessels=vessels,
                   links=[{'from': 0, 'to': 1, 'conductance_kg_s_Pa': conductance, 'inertance_Pa_s2_kg': inertance}],
                   schedule=schedule)
    result = run_worker(worker, candidate, env, '--fluid-vessel-network', request, encoder=encode)
    rows = result['samples']
    assert rows[0]['link_flow_kg_s'] == rows[3]['link_flow_kg_s'] == [0]
    assert rows[1]['vessels'][0]['pressure_Pa'] < rows[1]['vessels'][1]['pressure_Pa']
    assert rows[1]['link_flow_kg_s'][0] > rows[2]['link_flow_kg_s'][0] > 0 > rows[4]['link_flow_kg_s'][0]
    initial = [item[key] for item in vessels for key in ('initial_mass_kg', 'initial_internal_energy_J')] + [0]

    def rate(y, opening):
        m0, u0, m1, u1, q = y
        if opening == 0:
            return [0, 0, 0, 0, 0]
        pressure_difference = gas*(u0-u1)/(volume*cv)
        donor_enthalpy = (1+gas/cv)*(u0/m0 if q >= 0 else u1/m1)
        return [-q, -q*donor_enthalpy, q, q*donor_enthalpy,
                (pressure_difference-q/(conductance*opening))/inertance]

    reference = initial
    for interval, sample in zip(schedule, rows[1:], strict=True):
        opening = interval['opening'][0]
        if opening == 0:
            reference[-1] = 0
        solution = solve_ivp(lambda _, y: rate(y, opening), [0, interval['duration_s']], reference,
                             rtol=1e-12, atol=1e-13)
        assert solution.success
        reference = solution.y[:, -1]
        for node, m, u in zip(sample['vessels'], reference[0:4:2], reference[1:4:2], strict=True):
            assert abs(node['mass_kg']-m) < 1e-9
            assert abs(node['pressure_Pa']-gas*u/(cv*volume)) < .01
        assert abs(sample['link_flow_kg_s'][0]-reference[-1]) < 1e-9
        assert abs(sample['mass_defect_kg']) < 1e-14 and abs(sample['energy_defect_J']) < 1e-8
    run_worker(worker, candidate, env, '--fluid-vessel-network',
               dict(request, links=[dict(request['links'][0], inertance_Pa_s2_kg=1)]), 'vessel_momentum_step')

    model = json.loads(project_fixture.read_bytes())
    with TemporaryDirectory() as scratch:
        root = Path(scratch)
        target = root/'network.fcst'
        with ProjectStore.create(root/'authoring.db', model) as store:
            artifact = store_network_run(store, request, result, expected_revision=model['revision'])
            draft = store_network_run(store, request)
            try:
                store_network_run(store, dict(request, maximum_step_s=.01), result)
            except PersistenceError as error:
                assert error.code == 'network_run_input_mismatch'
            else:
                raise AssertionError('mismatched input accepted')
            entity = model['entities'][-1]
            entity = dict(entity, conductance=dict(entity['conductance'], value=4))
            store.apply('synthetic-actor', {'changes.apply'}, model['project_id'], model['revision'],
                        'edit-conductance', {'upsert': [entity], 'delete': []})
            try:
                store_network_run(store, request, result, expected_revision=model['revision'])
            except PersistenceError as error:
                assert error.code == 'stale_revision'
            else:
                raise AssertionError('stale project revision accepted')
            store.save(target)
        package = Package.open(target)
        restored = load_network_run(package, artifact)
        assert restored['request'] == request and restored['result'] == result
        assert restored['revision'] == model['revision'] < package.model['revision']
        assert load_network_run(package, draft)['result'] is None
        with ProjectStore.create(root/'reopened.db', package=package) as reopened:
            again = root/'roundtrip.fcst'
            reopened.save(again)
        assert load_network_run(Package.open(again), artifact) == restored
        replay = run_worker(worker, candidate, env, '--fluid-vessel-network', restored['request'], encoder=encode)
        assert replay == result


def check_network_phase_transition(worker, candidate, env):
    # CoolProp 6.6.0 direct density/internal-energy flashes. Above the dew
    # point, continue the phase coordinate from 1 using 160 kJ/kg as a scale.
    points = [
        (295407.396289, 87.735986619, .9862493082), (299175.733099, 87.8766647945, .998324529),
        (299816.384785, 87.9248455128, 1.0001438805), (303400.967557, 88.8008169819, 1.0045188805),
        (308525.461334, 90.0562067701, 1.0107688805), (318785.860064, 92.5798271938, 1.0232688805),
        (287906.802642, 87.4519884266, .9869952886), (291570.806844, 87.5913937432, .9990341937),
        (292562.699647, 87.7775199168, 1.0008739792), (296057.955053, 88.6549607277, 1.0052489792),
        (301054.639898, 89.9123565665, 1.0114989792), (311058.812714, 92.4396981699, 1.0239989792),
    ]
    properties = dict(kind='volume_energy_table', volumes_m3_kg=[.079, .081],
                      energies_J_kg=[58000, 60000, 60300, 61000, 62000, 64000],
                      points=[dict(pressure_Pa=p, temperature_K=t, phase_coordinate=x) for p, t, x in points])
    vessel = dict(volume_m3=.01, initial_mass_kg=.125, initial_internal_energy_J=.125*59000,
                  initial_wall_temperature_K=100, wall_capacity_J_K=25, wall_conductance_W_K=15)
    request = dict(schema_version=1, maximum_step_s=.025, properties=properties,
                   vessels=[vessel, dict(vessel, wall_conductance_W_K=0)],
                   links=[{'from': 0, 'to': 1, 'conductance_kg_s_Pa': 1e-7}],
                   schedule=[dict(duration_s=dt, wall_power_W=[0, 0], opening=[0]) for dt in (3, 5)])
    rows = run_worker(worker, candidate, env, '--fluid-vessel-network', request)['samples']
    assert [row['vessels'][0]['phase'] for row in rows] == ['saturated', 'vapor', 'vapor']
    assert rows[0]['vessels'][0]['quality'] > .99 and rows[1]['vessels'][0]['quality'] is None
    for sample, p, t in zip(rows, (293466.714, 299478.490, 300684.896), (87.663021, 88.675967, 88.975177), strict=True):
        node = sample['vessels'][0]
        assert abs(node['pressure_Pa']-p) < 400 and abs(node['temperature_K']-t) < .06
        assert abs(sample['energy_defect_J']) < 1e-9
    run_worker(worker, candidate, env, '--fluid-vessel-network',
               dict(request, vessels=[dict(vessel, initial_internal_energy_J=100), vessel]),
               'vessel_volume_energy_domain')

    # Manufactured constant-capacity fluid and wall. Compare heating
    # through the bubble point and cooling back to liquid to an exact solution.
    energies = [-10000, 0, 10000, 20000]
    liquid_grid = dict(kind='volume_energy_table', volumes_m3_kg=[.079, .081], energies_J_kg=energies,
                       points=[dict(pressure_Pa=p+u, temperature_K=280+u/1000, phase_coordinate=u/10000)
                               for p in (301000, 299000) for u in energies])
    active = dict(vessel, initial_internal_energy_J=-625, initial_wall_temperature_K=300,
                  wall_capacity_J_K=125, wall_conductance_W_K=12.5)
    durations = [(10, 0), (16, -200)]
    liquid_request = dict(request, properties=liquid_grid, vessels=[active, dict(active, wall_conductance_W_K=0)],
                          schedule=[dict(duration_s=dt, wall_power_W=[power, 0], opening=[0])
                                    for dt, power in durations])
    rows = run_worker(worker, candidate, env, '--fluid-vessel-network', liquid_request)['samples']
    assert [row['vessels'][0]['phase'] for row in rows] == ['liquid', 'saturated', 'liquid']
    mean, difference = 287.5, 25
    for (dt, power), sample in zip(durations, rows[1:], strict=True):
        mean += power*dt/250
        equilibrium_difference = power/25
        difference = equilibrium_difference+(difference-equilibrium_difference)*math.exp(-.2*dt)
        temperature = mean-difference/2
        node = sample['vessels'][0]
        assert abs(node['temperature_K']-temperature) < 1e-8
        if node['phase'] == 'saturated':
            assert abs(node['quality']-(temperature-280)/10) < 1e-9
        else:
            assert node['quality'] is None
        assert abs(sample['energy_defect_J']) < 1e-8


def check_heat_pipe_transient(worker, candidate, env):
    from scipy.optimize import brentq

    def run(request, error=None):
        return run_worker(worker, candidate, env, '--heat-pipe-transient', request, error)

    hydraulics = dict(length_m=2, evaporator_length_m=.5, condenser_length_m=.5, evaporator_elevation_m=0,
                      capillary_head_Pa=5, liquid_density_kg_m3=1000, gravity_m_s2=0,
                      liquid_loss_Pa_W_m=2/3, vapor_loss_Pa_W_m=0)
    pipe = dict(schema_version=1, hydraulics=hydraulics, condenser_temperature_K=300, initial_temperature_K=300,
                startup_temperature_K=302, evaporator_capacity_J_K=10, passive_conductance_W_K=0,
                latent_conductance_W_K=2, latent_heat_J_kg=100, fluid_mass_kg=.5, initial_wick_mass_kg=.05,
                reprime_mass_kg=.025, refill_rate_kg_s=.05, schedule=[dict(duration_s=6, heat_load_W=20)])
    result = run(pipe)
    assert result['capillary_limit_W'] == 5
    start, dry, refill, restart, *_ = result['events']
    assert [row['mode'] for row in (start, dry, refill, restart)] == ['active', 'dry', 'priming', 'active']
    assert math.isclose(start['time_s'], 1, abs_tol=1e-12, rel_tol=0)
    # Starting at a 2 K rise, the active evaporator approaches a 10 K rise.
    # Integrate latent demand above the 5 W cap to find the first dryout.
    above = 5*math.log(8/7.5)
    first_dry = 1+brentq(lambda t: 15*(t-above)+80*(math.exp(-t/5)-math.exp(-above/5))-5,
                         above, 5)
    assert abs(dry['time_s']-first_dry) < 1e-10 and dry['wick_mass_kg'] == 0
    assert abs(refill['time_s']-dry['time_s']-.5) < 1e-12 and refill['wick_mass_kg'] == .025
    assert restart['time_s'] == refill['time_s']
    for row in result['events']+result['samples']:
        assert abs(row['wick_mass_kg']+row['reservoir_mass_kg']-.5) < 1e-14
        assert abs(row['energy_defect_J']) < 1e-10
    split = run(dict(pipe, schedule=[dict(duration_s=.25, heat_load_W=20)]*24))
    assert [row['mode'] for row in split['events']] == [row['mode'] for row in result['events']]
    for a, b in zip(split['events']+split['samples'][-1:], result['events']+result['samples'][-1:], strict=True):
        for key in ('time_s', 'temperature_K', 'wick_mass_kg', 'rejected_energy_J'):
            assert abs(a[key]-b[key]) < 1e-10
    empty = run(dict(pipe, initial_wick_mass_kg=0, refill_rate_kg_s=0))
    assert empty['events'] == [] and empty['samples'][-1]['mode'] == 'dry'
    run(dict(pipe, reprime_mass_kg=.6), 'heat_pipe_transient_input')
