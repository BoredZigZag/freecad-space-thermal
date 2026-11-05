# WP-20 open-source reference cases

## Steady adiabatic gas duct

`fcst-worker --fluid-duct` accepts version 1 JSON on standard input. Supply
`length_m`, `area_m2`, `hydraulic_diameter_m`, `darcy_friction_factor`,
`mass_flow_kg_s`, `outlet_pressure_Pa`, `inlet_temperature_K`,
`gas_constant_J_kg_K`, `gamma`, and an array `positions_m` of up to 4,096
positions in the duct. The result gives static pressure, temperature,
velocity, density and stagnation enthalpy at those positions in request order.

The model assumes a straight constant-area duct, a calorically perfect gas
with $1 < \gamma \leq 2$, constant Darcy friction, and steady adiabatic
subsonic flow without gravity. The gas follows $p = \rho R T$.
Mass flux $G = \dot m/A$ and total specific enthalpy
$H = c_p T + u^2/2$ are constant. The momentum equation is
$$
\frac{d(p+Gu)}{dx} = -\frac{f_D G u}{2D_h}.
$$
The implementation solves its integrated velocity relation by bracketing
the inlet velocity against the outlet pressure, then evaluates the
integrated relation at each station. It handles zero flow and zero friction
directly. For positive flow, the outlet velocity computed at inlet
temperature must be subsonic and at least $10^{-9}\sqrt{RT_\mathrm{in}}$.
The dimensionless friction length $f_D L/(2D_h)$ is capped at $10^8$.

The comparison uses three pressure observations from the public MOOSE
Thermal Hydraulics pressure-drop regression, pinned at
`6ea3f753777a0748e624830520a30cf5ffac6386`. The native result must agree
within 0.35% of the local pressure loss relative to the prescribed outlet.
The comparison uses the terminal pressure profile of the upstream
finite-volume transient case with ramped inlet flow. A separate moderate-Mach
synthetic case independently integrates the momentum equation by numerical
quadrature and checks mass and total enthalpy at every station. The
`fluid-moose-pressure-drop` case runs in the thermal acceptance stage on
both Windows configurations.

Sources and attribution for the comparison are the MOOSE project's
[pressure-drop input](https://github.com/idaholab/moose/blob/6ea3f753777a0748e624830520a30cf5ffac6386/modules/thermal_hydraulics/test/tests/problems/pressure_drop/pressure_drop.i),
[reference observations](https://github.com/idaholab/moose/blob/6ea3f753777a0748e624830520a30cf5ffac6386/modules/thermal_hydraulics/test/tests/problems/pressure_drop/gold/pressure_drop_csv_pressure_vpp_FINAL.csv),
and [LGPL-2.1 license](https://github.com/idaholab/moose/blob/6ea3f753777a0748e624830520a30cf5ffac6386/COPYING).
FCST records scalar inputs and observations and implements the equations
independently.

## Thin dielectric beam

The [spectral beam worker](radiation-engine.md#spectral-beam-prototype)
compares two refractive indices at oblique incidence against the
thin-dielectric formulation of pbrt. The Python oracle computes interface
reflectance using Snell's law and sums the internal reflections explicitly.
FCST uses the closed form and traces the two outgoing branches through
the scene. This check runs inside `worker-spectral-beam`.

The formulation is described in [Physically Based Rendering, fourth edition](https://pbr-book.org/4ed/Reflection_Models/Dielectric_BSDF).
The reference implementation is [pbrt-v4 ThinDielectricBxDF](https://github.com/mmp/pbrt-v4/blob/b0bdf461ba5dd6504b70ebf0932acc0fe7aa744f/src/pbrt/bxdfs.h)
by Matt Pharr, Wenzel Jakob, and Greg Humphreys under [Apache-2.0](https://github.com/mmp/pbrt-v4/blob/b0bdf461ba5dd6504b70ebf0932acc0fe7aa744f/LICENSE.txt).
FCST implements the formula independently and uses synthetic test geometry.

These references verify the stated native operating ranges. Detailed heat
pipes, multiphase networks, source-logic translation and the mandatory
FLUINT/FloCAD comparison evidence remain in WP-20 qualification scope.
