# SPDX-License-Identifier: MIT OR Apache-2.0
"""Independent verification of native advanced fluid worker operations."""
import hashlib
import json
import math
import subprocess


def run_worker(worker, candidate, env, operation, request, expected_error=None):
    payload = json.dumps(request, allow_nan=False).encode()
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
