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

Each RK4 stage flashes all vessels before computing branch flow. By
default, signed flow is the product of conductance, opening, and
pressure difference. A link can supply positive `inertance_Pa_s2_kg`
and optional signed `initial_flow_kg_s` (default zero) to integrate
the flow as a state. With mass flow `q`, pressure drop `Δp`,
conductance `G`, opening `a`, and inertance `I`, the open-link
equation is `dq/dt = (Δp - q/(G*a))/I`. The rate remains continuous
between nonzero openings. Closure resets the flow to zero and
reopening starts from zero. A step larger than twice the open link's
drag time constant `I*G*a` is rejected. The caller still needs to resolve
pressure–inertance and thermal timescales.

The donor's bulk enthalpy follows the signed flow, including during
reversal. The two endpoints receive equal and opposite mass and
enthalpy fluxes. The wall exchanges energy with its vessel at the same
stage. The model assumes rigid, homogeneous volumes and lumped
low-speed branches. The energy balance includes fluid internal energy
and wall energy. The model has no distributed pipe volume, pressure
waves, branch kinetic-energy storage, or closure impulse.

The output includes the initial state and each interval endpoint, signed
link flows, and network mass and energy defects. Link flows at interval
endpoints use the opening from the interval that just ended. The solver
bounds the request to 64 vessels, 256 links, 256 intervals and a step
budget inversely proportional to the sum of vessels and links.

The resistive case compares three two-phase vessels against a SciPy
trajectory with an independently invertible manufactured saturation
table. It checks conservation, reversal, closed links, pressure,
temperature, quality and time refinement. A second SciPy trajectory
checks the inertial pressure-flow lag, reversal, closure, reopening,
and conservation for an ideal gas. NASA's network formulation gives
a reference for spatially distributed branch dynamics.
[NASA GFSSP fluid transients](https://www.nasa.gov/wp-content/uploads/2024/04/gfssp-primingfluidtransient-jpp2014.pdf)

### Phase changes beyond the saturation dome

Both vessel operations also accept `properties.kind = "volume_energy_table"`.
Give increasing axes `volumes_m3_kg` and `energies_J_kg`, each with
2–64 values, and `points` ordered by volume first, then energy. Each
point supplies positive `pressure_Pa`, positive `temperature_K`, and
a continuous `phase_coordinate`. For each fixed volume these quantities
are nondecreasing with energy. The worker interpolates bilinearly at
every RK stage and rejects states outside the grid. Use coordinates
below zero for liquid, quality in [0, 1] for saturation, and above
one for vapor. The network emits `phase` and sets `quality` to null in
single-phase states. Supply a sufficiently resolved property grid
that spans the expected trajectory and phase boundaries.

Acceptance checks a nitrogen trajectory from saturation to vapor
against direct density and internal-energy flashes from CoolProp 6.6.0
and a SciPy wall-coupling trajectory. A manufactured exact thermal
solution checks liquid heating across the bubble point and condensation
back to liquid. The worker runs without a property-library dependency.

### Portable project runs

`fcst_app.network_runs.store_network_run(store, request, result=None)`
registers an immutable versioned network request and optional worker
result in the project. The optional `expected_revision` keyword guards
against saving against a newer model revision. Pass the bytes from
`fcst_app.persistence.encode(request)` to the worker when retaining a
result so the request digest matches. After saving and reopening the
`.fcst` file, `load_network_run(package, artifact_id)` restores the
request, result, and original model revision and semantic hash. The
envelope is subject to the existing 1 MiB JSON item limit. It uses the
existing evidence role and leaves the model and manifest schemas
unchanged. It is available through the project-store API. The
acceptance case checks request-only saves, result binding, mismatched
request rejection, and native replay after reopen.

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
instantaneous transport law. Hardware-specific startup, dryout timing,
and refill qualification remain open.

### Steady hardware comparison

Figure 2 from the NASA heat-pipe tests gives measured transport limits
for 48-inch aluminum pipes with 12-inch evaporator and condenser
sections. The report defines transport as power times the 36-inch
midpoint spacing. For ammonia pipe 4, which uses a screen over grooves,
the level and 0.5-inch elevation points give approximately 4,300 and
1,800 W·in. Fitting the capillary head and total loss to those two
points predicts 3,300 and 2,800 W·in at the held-out 0.2- and 0.3-inch
elevations. The plotted readings are approximately 3,125 and 2,675
W·in. The test uses a 200 W·in comparison band for these coarse
graph readings.

For plain-groove ammonia pipe 8, fitting 5,750 and 3,125 W·in at
0 and 0.2 inches predicts about 500 W·in at 0.4 inches. The plotted
limit is about 1,450 W·in. The regression records this roughly 950
W·in underprediction. The source reports nonlinear tilt dependence
and identifies overcharge as a possible explanation. The fit lumps
liquid and vapor losses, and its assumed density cancels from the
transport prediction. These comparisons bound the applicability of
the steady linear capillary model for the tested hardware.
[NASA A-4047, Figure 2 on printed page 37](https://ntrs.nasa.gov/citations/19720018727)

### Steady axial-groove solver

`fcst-worker --heat-pipe-grooved` accepts a version 1 request for a
straight pipe with uniformly spaced rectangular grooves. Supply
`length_m`, `evaporator_length_m`, `condenser_length_m`,
`evaporator_end_rise_m` (the positive end-to-end adverse elevation),
`vapor_core_diameter_m`, `groove_count`, `groove_width_m`,
`groove_depth_m`, `contact_angle_deg`, `gravity_m_s2` and total
`fluid_charge_kg`. Supply saturated `liquid_density_kg_m3`,
`vapor_density_kg_m3`, `liquid_viscosity_Pa_s`, `vapor_viscosity_Pa_s`,
`surface_tension_N_m` and `latent_heat_J_kg` at the chosen operating
temperature. Optional `liquid_flow_factor` scales the groove
conductance (default 1). `steps_per_section` controls the axial RK4
grid (16–256, default 64).

The calculation shoots from the evaporator tip toward the condenser.
At the limit, the lowest groove reaches its capillary pressure
`2 σ cos(θ) / width`. The other grooves experience different suction
because of their elevation in the cross-section. A circular meniscus
reduces the liquid area in each groove, and a reduced wetting law
drains a groove across the next 15% of critical suction after
depinning. Groove conductance scales with the cube of its remaining
liquid area. A circular-segment puddle contributes a parallel return
path and reduces the vapor area. The axial pressure gradient combines
gravity, separate laminar liquid and vapor losses, and an estimate of
the opposing interfacial shear. Axial flow follows uniform
evaporation and condensation and is constant in the adiabatic zone.
The solver varies the power until the integrated liquid and vapor
masses match the charge. This reduced closure assumes heat spreads to
the remaining wetted grooves at the evaporator.
[NASA CR-156678, sections 3.2 and 3.4](https://ntrs.nasa.gov/citations/19780008374)

Results give `power_limit_W`, `minimum_charge_kg`,
`charge_residual_kg`, `pool_mass_kg` and `maximum_vapor_reynolds`.
Charge below the wetting threshold returns zero power and reports the
charge shortfall as a positive residual. The solver rejects solutions
with puddle depths above three quarters of the core diameter, a
zero-gravity vapor blockage, or vapor Reynolds number above 2,300.
The model covers steady, laminar flow at prescribed temperature. It
does not resolve wall temperature distribution, wick screens, or
startup and refill timing.

For Figure 2 pipe 8, the comparison assumes a 0.4-inch vapor core,
zero contact angle, 293.15 K saturated ammonia, and end-to-end
reported elevation. The nominal-conductance fit uses only the level
and 0.2-inch points and gives about 12.58 g charge and a 1.185 groove
conductance factor. Those are fitted inputs. The report does not give
the charge and the two coarse calibration points do not uniquely
identify it. A preliminary model that used a single groove pressure
around the circumference still predicted about 14 W at 0.4 inches
after calibration. The azimuth-dependent model gives the following
held-out comparison. Figures are approximate chart readings.

| Adverse tilt | Hardware | Linear baseline | Grooved solver |
|---|---:|---:|---:|
| 0.4 in | 40.3 W | 13.9 W | 41.5 W |
| 0.6 in | 9.0 W | 0 W | 7.0 W |

At 0.4 inches, varying the fitted charge by ±5% with all other
inputs fixed gives 37.9–45.2 W. This is a sensitivity check. It does
not estimate the hardware measurement uncertainty.
[NASA TM X-2557, Figure 2](https://ntrs.nasa.gov/citations/19720018727)

An independent run uses the published 11.2 g charge and 273 K
temperature of the ATS extrusion, the nominal flow factor, and a
rectangle of equal opening and area to approximate its tapered groove.
The model gives 134, 103, and 73 W at 8, 10, and 12 mm of tilt. The
plotted operating-to-dryout brackets are about 98–104, 67–75, and
44–48 W. The prediction at 6 mm falls outside the laminar domain.
The solver reproduces the direction of the tilt and charge effects,
but it overpredicts absolute capacity for this pipe. The automated
comparison records this limitation alongside the plain-groove
improvement. A zero-gravity manufactured charge checks the solver
against a SciPy trajectory and an analytic wetting threshold.
[NASA CR-156678, Figures 3-7 and 3-19](https://ntrs.nasa.gov/citations/19780008374)

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
