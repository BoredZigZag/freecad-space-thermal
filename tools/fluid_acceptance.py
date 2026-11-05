# SPDX-License-Identifier: MIT OR Apache-2.0
"""Independent verification of the native steady duct worker."""
import hashlib
import json
import math
import subprocess


def check(worker, candidate, env):
    from scipy.integrate import quad

    def run(request, expected_error=None):
        payload = json.dumps(request, allow_nan=False).encode()
        result = subprocess.run([str(worker), '--fluid-duct'], input=payload, capture_output=True,
                                timeout=20, env=env)
        report = json.loads(result.stdout)
        assert not result.stderr
        if expected_error:
            assert result.returncode == 1 and report == dict(status='failed', code=expected_error)
            return
        assert result.returncode == 0 and report['status'] == 'passed'
        assert report['schema_version'] == 1 and report['execution_mode'] == 'fcst_native'
        assert report['source_revision'] == candidate and report['input_sha256'] == hashlib.sha256(payload).hexdigest()
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
