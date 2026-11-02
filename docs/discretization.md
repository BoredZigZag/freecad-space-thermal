# Native spatial thermal profile (WP-16)

Thermal-input version 2 binds the canonical model to SI/global coordinates,
ordered connectivity, material laws and explicit assignments. The installed
native worker accepts it through `--thermal-prepare`, `--thermal-steady`,
`--thermal-transient` and `--spatial-evaluate`, without FreeCAD, Python, a mesher
or an external solver. Durable protocol job publication retains its existing scope.

| Family | Formulation | Integration | Storage |
|---|---|---|---|
| FD rod | Cell-centred flux balance; half-cell boundary distances | Constant isotropic properties | Control-volume capacity |
| tri3 shell | Linear in-plane interpolation | Three-point triangle | Row-sum reference mass |
| quad4 shell | Bilinear, convex planar quadrilateral | Full 2 by 2 Gauss | Row-sum reference mass |
| tet4 solid | Linear, positive orientation | Four-point tetrahedron | Row-sum reference mass |
| hex8 solid | Trilinear, positive integration-point Jacobians | Full 2 by 2 by 2 Gauss | Row-sum reference mass |

Shell thickness is explicit in metres. Solids require zero shell thickness.
Shells have no through-thickness degree of freedom. Higher-order, folded,
degenerate and nonplanar shell elements fail before solving. Fixed geometry is
assumed; no thermal expansion is modeled. Input remains bounded to one MiB.

Shells enforce zero normal heat flux by eliminating the unresolved normal
gradient: `K_shell = K - (K n)(n^T K)/(n^T K n)`. Its full temperature derivative
enters the Jacobian. This supports tensor coupling across the midsurface without
inventing an unmodeled through-thickness heat flow. Constant cross-coupled tensors,
rotated shell planes and temperature-dependent coupled tensors have independent
flux and finite-difference derivative checks.

At each quadrature point, conduction is
`K_ij = volume * grad(N_i)^T * conductivity * grad(N_j)`. Conductivity is sampled
at interpolated temperature and its derivative enters the nonlinear Jacobian.
Flux is `-conductivity * grad(T)` in W/m2, reported as a global element volume
average. It is never relabeled as raw vertex data; spatial-v2 stays unchanged.

Scalar density, specific heat and conductivity use bounded property laws.
Additional tensor tables linearly interpolate symmetric positive-definite
matrices, with explicit clamp/error extrapolation, reference temperature and
local frame. Every knot is checked; convex matrix interpolation preserves
positive definiteness. The reference tensor must equal the canonical tensor.
Parent frame rotations compose before assembly.

Reference mass integrates density at the initial interpolated temperature and
remains fixed during solving. Temperature-dependent density therefore does not
create or destroy mass. Storage sums each material mass times its specific
enthalpy change. Interface nodes retain separate material contributions. Computed
initial capacity must agree with the canonical node capacity. Only capacitive
nodes store energy; overlapping explicit and element-derived storage is rejected.

Boundary triangles must belong to exactly one cell boundary. Positive flux is
into the model; total power integrates once, while flux multiplies geometric
area. Convection uses the consistent triangle boundary matrix. Prescribed
reservoir reactions enter the energy budget.

Contact sides have positive normalized weights and disjoint identities. Opposite
powers scatter to both sides. Every link declares area, calibration UUID,
temperature interval and maximum power:

| Kind | Coefficient SI | Law |
|---|---|---|
| contact | W/(m2 K) | `h A (T_from - T_to)`, closed contact |
| insulation | W/(m K) | `k A/gap (T_from - T_to)`, positive gap |
| mli | Effective emissivity, at most one | `epsilon A sigma (T_from^4 - T_to^4)` |
| heat_pipe | W/K | `G (T_from - T_to)` within its calibration envelope |

Unmodeled contact gaps and exceeded calibration envelopes fail closed. These
abstractions do not claim detailed MLI transport, heat-pipe startup, dryout,
capillary limits or multiphase flow; required advanced physics remains WP-20.

The geometry/connectivity revision is separate from the complete assignment hash.
The canonical mesh artifact binds the exact canonical encoding of `spatial`,
`material_laws` and `node_storage`, so changing any assignment changes model
identity. The native reader checks mesh revision, artifact bytes, volume,
capacity and explicit mapping weights. No CAD, radiation or host row identity
is inferred from coincident geometry.

Manifest version 3 adds the closed `conduction_input` canonical-text role for this bounded
profile and explicitly requires reader 3.0.0. The `.fcstc` payload uses the existing
typed canonical encoding with bounded decoding and exact re-encoding. Payload schema, model and exact bytes
are checked across portable save/reopen. Released manifest-v1/v2, model-v1,
thermal-input-v1 and HDF5 checks stay intact. Ordinary mesh artifacts still require
the established HDF5 format; older readers reject the new version.

**Open spatial thermal model** in the workbench opens a prepared input. Solve
runs the owned worker asynchronously and displays solved temperatures through
FEM mesh/result APIs with a fixed contour scale across time. Direct host edits,
ambiguous face changes and stale inputs prevent current display. The FEM adapter
requires complete explicit host/canonical maps, checks connectivity and mm-to-m
conversion, and rejects a regenerated mesh without explicit reassignment.

The pinned API/source/license assessment in `ci/fem-reuse.json` and
`ci/cad-mesher.json` records API reuse with no copied upstream source. **Mesh
selected CAD thermal model** creates a native project from a selected valid solid
or surface using the official host bundle's Gmsh 4.15.0. The closed profile uses
first-order tet4 solids or tri3 shells, Delaunay algorithms, one thread, a fixed
seed and explicit mesh-size bounds. It accepts constant region material cards;
the native input separately supports the qualified temperature-dependent laws.
The dialog accepts SI material values and explicit `FaceN` temperature, total
power, surface flux or convection conditions. Unassigned exterior faces are
adiabatic. Native mesh/result APIs display exterior faces of volume meshes.

Named FEM physical groups supply CAD face and solid ownership. Conduction
elements, thermal nodes and radiation facets have separate UUIDs and preserve
the original mesher tags and any orientation permutation. Radiation facets in
the receipt describe geometry only; they do not introduce optical assumptions.
Original BREP bytes, source signatures, profile digest, material/face assignments
and complete maps travel with the portable project. Refinement changes mesh and
thermal identities while preserving accepted CAD face identities. Split, merge,
reorder, delete and changed geometry revisions require explicit reassignment.
Duplicate ownership, incomplete groups, unsupported order and stale receipts
fail closed. Touching multi-solid internal interfaces require explicit contact
preparation; this profile accepts exterior ownership only. Netgen generation,
higher-order meshes and integration-point fields remain outside this profile.

Mandatory imported Q1 element/property and source-ecosystem qualification still
requires the licensed source runs and paired evidence recorded as missing in the
inventory. Optional CalculiX/Elmer comparisons remain deferred and never replace
native checks. Complete offline release qualification remains shared with WP-19.

`ci/discretization-acceptance.json` freezes the 22 native cases, tolerances and
mesh/time refinement sequences. Candidate/source/worker-bound evidence runs in
both Windows configurations and the final Foundation gate rejects missing,
substituted or stale evidence. The pinned host harness also maps, solves, displays
and saves/reopens a spatial case without manual acceptance execution.

```powershell
fcst spatial-primitive fd-rod --nx 8 --output rod.json
fcst spatial-solve rod.json --worker fcst-worker.exe --output rod-result.json
python tools/check_discretization.py --worker fcst-worker.exe --native-build out/windows-release/Release --report spatial-report.json
```

Outputs must be new files. A free-floating steady primitive needs prescribed
temperatures or another anchoring boundary and otherwise reports singularity.

## Publication privacy (TST-021)

Only synthetic fixtures, owned sources, schemas, scalar metrics and bounded
candidate-linked reports are publication candidates. Exact outgoing bytes,
metadata, history and GitHub prose pass preflight before upload. Original models,
host files, screenshots, raw compiler/mesher logs, binaries and build trees stay
local. Passing the bounded profile never implies full WP-16/Q1 qualification.

Large host result envelopes preserve the existing 1 MiB JSON reader limit by
referencing a separate immutable, hash-checked request artifact. Portable reopen
checks its dependency identity and exact bytes; legacy result envelopes remain
readable. Generated mesher scripts and AppContainer denial manifests stay local.

The native offline check stages only configured native executables and owned
fixtures in a fresh Windows AppContainer with zero capabilities. Every configured
CTest case and spatial steady/transient analytic solve runs there. A native probe
checks its token, denied reads of actual outside interpreter/host/source files,
and network isolation. Windows can reject a connection immediately or silently
drop it: a five-second nonblocking timeout is accepted only with successful
parent connections to the same live loopback listener immediately before and
after the probe. A readable dependency and an uncontained process are negative
controls. No external endpoint is contacted. Source, inventory, worker and test
binary hashes bind the bounded report; temporary profile identifiers and denial
paths never enter published evidence. This verifies a clean confined native
installation, while complete installer/release qualification remains WP-19.
