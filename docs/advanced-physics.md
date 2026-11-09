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

## Equilibrium flow boiling and condensation

`fcst-worker --fluid-heated-stream` accepts version 1 JSON with positive
`mass_flow_kg_s`, `inlet_enthalpy_J_kg` and a `segment_heat_W` array of
1 to 4,096 signed heat rates. The `saturation` object gives the fixed
`pressure_Pa` and `temperature_K`, liquid and vapor enthalpies
(`liquid_enthalpy_J_kg`, `vapor_enthalpy_J_kg`), densities
(`liquid_density_kg_m3`, `vapor_density_kg_m3`) and local specific heats
(`liquid_cp_J_kg_K`, `vapor_cp_J_kg_K`). The declared
`minimum_temperature_K` and `maximum_temperature_K` bound the approximation.

At each station, enthalpy increases by net heat added per unit mass flow.
Between saturation endpoints, temperature is constant and quality is
$x=(h-h_f)/(h_g-h_f)$. Homogeneous mixture specific volume is
$(1-x)/\rho_f+x/\rho_g$. Outside the dome, a local constant specific heat
relates enthalpy to temperature. Those states return null quality and
density. The model assumes steady low-speed flow with prescribed uniform
pressure and mass flow. Its approximation excludes pressure loss, phase
slip and transient inventory.

The acceptance case takes the nitrogen inlet, pressure, flow and four
heat additions from OpenFLUME's flow-boiling string. This is an isobaric
reduction of its network case. The test compares each heated station
against independent pressure-enthalpy flashes generated with CoolProp
6.6.0 and checks the energy balance. A synthetic cycle tests both
saturation endpoints, superheating and condensation. The checked-in
reference consists of scalar data and does not add a solver dependency.

Sources are the [OpenFLUME flow-boiling test](https://github.com/OpenFLUME/OpenFLUME/blob/464512786990485de60d16ec5ee39b22df1762bd/src/core/__tests__/twoPhaseFlow.test.ts)
and [MIT license](https://github.com/OpenFLUME/OpenFLUME/blob/464512786990485de60d16ec5ee39b22df1762bd/LICENSE),
the [CoolProp nitrogen equation of state](https://coolprop.org/fluid_properties/fluids/Nitrogen.html),
and [CoolProp 6.6.0](https://pypi.org/project/CoolProp/6.6.0/). Generation
used the CPython 3.11 Windows x64 wheel with SHA-256
`b22c30a23603ce3df88a18a445fad14f93fd9757720f43d3b8041549e93c4b93`.

## Steady capillary heat-pipe envelope

`fcst-worker --heat-pipe-capillary` accepts version 1 JSON with
`length_m`, `evaporator_length_m`, `condenser_length_m`, and
`evaporator_elevation_m` measured upward relative to the condenser.
Supply `capillary_head_Pa`, `liquid_density_kg_m3`, `gravity_m_s2`,
`liquid_loss_Pa_W_m` and `vapor_loss_Pa_W_m` at the selected operating
point, and a nonnegative `heat_load_W`.

Effective flow length is the total length less half the sum of the
evaporator and condenser lengths. The model computes separate liquid and
vapor pressure losses proportional to heat load and effective length.
It subtracts those losses and the signed liquid hydrostatic head from
the maximum capillary head. The result gives the pressure margin, the
nonnegative heat load limit, and whether the requested load is supported.
A head deficit at zero load returns an unsupported state with a zero limit.
This steady, linear-loss envelope uses caller-supplied capillary and
flow properties. It diagnoses capillary margin and does not simulate
startup, dryout or other transport limits.

The ammonia comparison uses the 45-inch effective length of NASA's
worked example. It calibrates the head from the published zero-gravity
capacity product and predicts the adverse-tilt limit using a CoolProp
liquid density at 263.15 K. The result is checked within 3 W of the
chart's approximate 84 W. The separate limit, gravity sign, and margin
checks exercise both supported and unsupported operating points.

Sources are the [NASA axially grooved heat-pipe example, slides 12 and 16–19](https://ntrs.nasa.gov/citations/20230009276),
the [NASA wick pressure-balance report](https://ntrs.nasa.gov/citations/19690020461),
and the [CoolProp ammonia properties](https://coolprop.org/fluid_properties/fluids/Ammonia.html).

The `fluid-openflume-flow-boiling` and `fluid-nasa-heat-pipe-capillary`
cases run in thermal acceptance on both Windows configurations.
## Pressure-coupled vessel transients

`fcst-worker --fluid-vessel` accepts a version 1 request with
`volume_m3`, `initial_mass_kg`, `initial_internal_energy_J`,
`initial_wall_temperature_K`, `wall_capacity_J_K`,
`wall_conductance_W_K`, and `maximum_step_s`. Set `properties.kind`
to `ideal_gas` with `gas_constant_J_kg_K` and `cv_J_kg_K`, or to
`saturation_table` with `points` containing `pressure_Pa`,
`temperature_K`, and paired `liquid_volume_m3_kg`, `vapor_volume_m3_kg`,
`liquid_energy_J_kg`, and `vapor_energy_J_kg` values.

Each `schedule` interval gives `duration_s`, `inlet_mass_flow_kg_s`,
`inlet_enthalpy_J_kg`, `outlet_pressure_Pa`,
`outlet_conductance_kg_s_Pa`, and `wall_power_W`. Outlet flow is
proportional to positive pressure difference and carries the bulk
mixture enthalpy. Heat transfer to the fluid is proportional to the
wall-to-fluid temperature difference. The solver advances mass, internal
energy, wall temperature, and discharged mass and enthalpy with RK4.
It recalculates pressure, temperature and saturation quality from the
conservative state at every stage, including initialization. It lands on
each schedule boundary and reports mass and energy defects.

The two-phase flash interpolates saturation properties by pressure.
It requires a strictly monotone energy relation at fixed specific volume.
The trajectory must stay inside the saturation dome and inside the
specific-volume range common to every row. This lumped model assumes a
rigid, homogeneous equilibrium vessel and an algebraic outlet. It covers
neither phase slip nor the momentum of a multi-branch network.

The fixed-volume, adiabatic nitrogen filling case reproduces the
100-to-1,000 psia comparison published in SINDA/FLUINT Table 1. The
feed rate is normalized because the adiabatic temperature-pressure
relation is independent of it. The native temperature agrees within
0.5 K of the published 253.02 °F result and independently satisfies the
closed-form energy balance. The source is the public conference record
and the test consumes its tabulated observation. Exact source decks,
settings and other mandatory vendor cases still need qualification.
[NASA conference proceedings, Table 1](https://ntrs.nasa.gov/citations/19950020924)

A separate nitrogen blowdown case uses CoolProp 6.6.0 saturation scalars
and compares against a SciPy trajectory with direct density and
internal-energy flashes. It checks pressure, temperature, quality and
mass through a valve closure and subsequent wall heating. An added
285 kPa property row resolves the pressure excursion of this case. The
coarser 50 kPa table produced a pressure error of about 1.1 kPa.
The test preserves the 500 Pa comparison limit and separately measures
fourth-order time refinement on the final table.

## Connected vessel networks

`fcst-worker --fluid-vessel-network` accepts version 1 JSON with a shared
`properties` object in the vessel format, `maximum_step_s`, and arrays of
`vessels`, `links`, and `schedule` intervals. Each vessel supplies the six
initial-state and wall fields from the single-vessel request. A link uses
zero-based `from` and `to` indices and `conductance_kg_s_Pa`. Parallel links
have independent conductances. Each schedule interval supplies
`duration_s`, one `wall_power_W` value per vessel, and one `opening` in
[0, 1] per link.

Each RK4 stage flashes all vessels before computing branch flow. The
linear branch momentum closure gives signed flow as conductance times
opening times the pressure difference. The donor's bulk enthalpy follows
the flow, including during reversal. Both endpoints receive equal and
opposite mass and enthalpy fluxes. The wall exchanges energy with its
vessel at the same stage. This version models rigid, perfectly mixed
volumes and quasi-steady resistive links. The user supplies a step bound
appropriate to the hydraulic and thermal timescales. The saturation
domain restrictions of the single-vessel solver apply at every stage.

The output includes the initial state and each interval endpoint, signed
link flows, and network mass and energy defects. Link flows at interval
endpoints use the opening from the interval that just ended. The solver
bounds the request to 64 vessels, 256 links, 256 intervals and a step
budget inversely proportional to the sum of vessels and links.

The automated case compares three two-phase vessels against a SciPy
trajectory with an independently invertible manufactured saturation
table. It checks conservation, reversal, closed links, pressure,
temperature, quality and time refinement. Dynamic pipe momentum,
single-phase transitions outside the saturation table, and source-case
qualification remain in scope for later work. For a reference with
dynamic branch momentum, see NASA's network formulation.
[NASA GFSSP fluid transients](https://www.nasa.gov/wp-content/uploads/2024/04/gfssp-primingfluidtransient-jpp2014.pdf)

## Heat-pipe startup, dryout and refill

`fcst-worker --heat-pipe-transient` accepts a version 1 request. Supply
the steady envelope fields under `hydraulics` excluding `heat_load_W`.
Supply `condenser_temperature_K`, `initial_temperature_K`,
`startup_temperature_K`, `evaporator_capacity_J_K`,
`passive_conductance_W_K`, `latent_conductance_W_K`, `latent_heat_J_kg`,
`fluid_mass_kg`, `initial_wick_mass_kg`, `reprime_mass_kg` and
`refill_rate_kg_s`. Each schedule interval has `duration_s` and
`heat_load_W`.

A primed evaporator starts when it reaches the declared startup
temperature. In the active mode, latent heat demand beyond the capillary
return capacity depletes the wick liquid. At zero wick mass, latent
transport stops. The dry wick refills at the specified rate limited by
the capillary return capacity and can restart at the reprime threshold.
Total working-fluid mass is conserved between the wick and reservoir.
The worker advances sensible evaporator temperature analytically within
each mode and locates transitions by bracketing. It reports transitions,
rejected energy and an energy defect. The test uses independent startup
and dryout event times and checks schedule-split invariance.

This is a reduced model with a fixed-temperature condenser, prescribed
startup and reprime thresholds, and no latent storage outside the
instantaneous transport law. Hardware-specific startup and dryout
qualification, dynamic pipe momentum, mandatory legacy
procedure mappings and project-level model and result persistence
remain in WP-20 scope.

## Published references for coupled transients

The NBS cryogenic transfer-line experiment has published pressure, flow
and temperature observations. C&R published a comparison against its
SINDA/FLUINT 5.2 and FloCAD calculations. NASA's GFSSP documentation
includes the same experiment as a conjugate heat-transfer example. This
is a candidate for testing two-phase momentum, wall cooling and
conservation against several independent sources. Access to the C&R
model deck and its exact numerical outputs remains unverified.
[NBS experiment](https://ntrs.nasa.gov/citations/19670007291) ·
[C&R comparison report](https://www.crtech.com/sites/default/files/files/NBS1966CryoLineCooldownStudy.pdf) ·
[NASA GFSSP example 14](https://ntrs.nasa.gov/citations/20160005401)

C&R also published steady multi-evaporator loop calculations and a
transient startup study based on test data. These give reference cases
for pressure loss and capillary head under unequal loading, and for
startup under adverse tilt. Input closure and reusable numerical
observations still need review for executable comparisons.
[Multi-evaporator study](https://www.crtech.com/sites/default/files/publications/TFAWS06-1012_Paper_Khrustalev.pdf) ·
[Startup study](https://www.crtech.com/sites/default/files/publications/AIAA2000-2285.PDF)

NASA's miniature loop heat-pipe tests provide a public hardware
comparison candidate for startup, load sharing, and recovery after
dryout. The two-evaporator, two-condenser experiment reported a heat
transport capacity of 100 to 120 W and recovery after the evaporator
loads were reduced. Replaying the test requires coupled evaporators,
condensers, and compensation chambers.
[NASA miniature loop heat-pipe test](https://ntrs.nasa.gov/citations/20070032906)
