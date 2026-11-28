# Experimental native P0 demonstration

WP-15 builds the same two-node, two-surface case through the shared application
API, the installed FreeCAD 1.1.4 workbench, and the 2026-07-28 MCP stdio profile.
Each route applies fixed-ID edits and reopens a portable project before solving.
The scaffold supplies the two triangular surfaces, their HDF5 mesh and the
canonical facet-to-node mappings. The edits set the initial temperatures,
lumped capacities, conductor, load, material record, and transient case. The
detached MCP job retains its identity and results across a client reconnect.

The two facing black IR surfaces exchange heat with each other and with the
250 K background. The material card documents the synthetic constant properties.
The lumped thermal equations use the explicitly assigned capacities and
conductance. The runner independently integrates the parallel-triangle view
factor by quadrature and solves the resulting two ordinary differential equations
with DOP853. Acceptance compares 21 temperature samples, internal and background
radiation power, and the energy defect against the frozen limits.
[Fixture](../tests/fixtures/radiation/p0-two-surfaces.json) and
[criteria](../ci/p0-acceptance.json).

The FreeCAD check compares actual surface colors and selected histories against
queried result values. It edits the heat load and checks stale-result rejection,
then cancels and terminates real native worker attempts. Reopening the project
retains the edited model and the original historical result. Both aborted
attempts retain their observed terminal states in the operational database.

The shared saved-case route supports static diffuse-gray triangular radiation
meshes with one thermal target per facet, a root mesh frame, and a single
zero-solar TAI background. The FreeCAD workbench uses the bundle's NumPy and
the locked h5py wheel installed with `install_workbench.py --with-radiation`.
MCP submits this case with `solve_submit`. Dedicated mesh generation and
radiation tracing submissions, moving environments and wider optics
qualification have separate profiles.

The tooling lock includes the dependencies for generating the portable example.
These commands run from the repository root with the FCST CLI installed.

```text
python tools/p0_fixture.py --output .local/p0-demo.fcst
fcst solve-case .local/p0-demo.fcst --case 00000000-0000-4000-8000-00000000006f --worker out/windows-release/Release/fcst-worker.exe
fcst qualify --gate P0 --reports .local/handoff-reports --report .local/p0.json
```

GitHub runs the Windows Debug and Release workflows unattended. The Foundation
gate publishes one `p0.json` alongside the handoff, with exact criteria, source,
fixture and binary hashes and the relative source-report paths and byte hashes.
Qualification remains experimental and applies to this native demonstration.
TST-021 scans the exact published receipts and sources. Generated packages,
operational databases, native output and raw diagnostics stay in local storage.
