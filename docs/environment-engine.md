# Environment and motion

The native worker accepts a mission through `fcst-worker --environment-transient`.
Supply the schema-version-1 facet, sampling and thermal input records used by
`--radiation-steady`. Replace its `environment` record with `mission` and add the
`transient` settings used by `--thermal-transient`. The selected model environment
supplies the solar flux, background temperature, TAI epoch label and time origin.

A portable `.fcst` project can store the same mission object on a transient
`case`. Run it with `fcst solve-case mission.fcst --case <case-id> --worker <worker>`.
The case selects its TAI environment and that environment's diffuse radiation
configuration. The native worker checks that the submitted mission matches the
saved case. A legacy case with zero solar flux can use the static background
profile by omitting `mission`.

A stationary deep-space or chamber mission can use this record.

```json
{
  "sun_direction_inertial": [1, 0, 0],
  "maximum_interval_s": 0.25,
  "attitude": [
    {"time_s": 0, "rotation": [1, 0, 0, 0]}
  ]
}
```

- `orbit` optionally declares `radius_m`, `body_radius_m`,
  `gravitational_parameter_m3_s2`, `phase_rad` and `plane_to_inertial`.
  The circular Keplerian trajectory is centered on a spherical body and starts
  at the given phase at the environment time origin. Angles use radians and
  times use elapsed SI seconds. Supply TAI offsets directly.
- `attitude` uses scalar-first unit quaternions mapping vehicle to inertial
  coordinates. Interpolate between knots along the shorter quaternion arc and
  hold the last pose. Rigid vehicle rotation changes illumination and preserves
  mutual exchange in vehicle coordinates.
- Each optional `joints` entry has an `id`, disjoint `facets`, a vehicle-local
  `pivot_m` and `axis`, and `angles` records with `time_s` and `angle_rad`.
  Interpolate unwrapped angles linearly and hold the last angle.
- Optional `albedo` and `body_exitance_W_m2` declare Lambert surface reflectance
  and uniform outgoing planetary infrared exitance. Deep space and chambers
  use the selected environment's isotropic background temperature.
- A thermal `case_id` selects the model's environment, loads, controls and
  overlays. Flight and chamber cases can select different environments and
  still reference the same facets, thermal nodes and source records. Hot/cold
  and operating/nonoperating cases select environment settings, load and heater
  memberships and thermal overrides. Use one diffuse radiation configuration
  per selected environment.
  For BOL/EOL variants, `mission.case_optics` accepts overrides with `facet_id`,
  `solar_absorptance`, `ir_emittance` and `condition`. These apply to the
  selected case's active facet side and preserve model entity and source IDs.

Circular motion, spherical occultation and a fixed parallel Sun direction allow
closed-form ingress and egress times for a point Sun. The body disk uses 8 cosine
bins and 24 azimuth bins with centroid visibility per triangle. Albedo uses a
Lambert-sphere phase law with uniform effective radiance across the visible disk.
Direct solar uses centroid shadow rays. Refine triangle size for partial mesh
shadows and reduce the maximum interval to resolve changing projected power.
The integrated visible disk weight is capped by the corrected exchange escape
factor. It replaces the corresponding background IR rather than adding a second
background over the same directions. Solar and albedo share the solar optical
band. Thermal emission and body and chamber IR use the infrared band.

The solver holds each prepared load and geometry frame until the next knot.
It lands on orbit transitions, motion samples and load schedules before applying
the right-hand state and reevaluating heaters. A step ending at a mission event
uses the left-hand loading for energy integration. Results include the usual
transient energy budget, event and checkpoint records and the incident solar,
albedo and body IR power history. The exact canonical mesh, sampling, model and
mission dependencies bind the checkpoint. Exchange is rebuilt for changed joint
angles and reused only for consecutive identical geometry within preparation.
Every request starts a fresh preparation.

Generated times within four representable values of an authored boundary align
to that boundary, including the start and end of the run. The first frame uses
the state immediately after any transition at the start. A transition at the
end supplies the final right-hand state and leaves the preceding energy integral
on the left-hand state. Resume with the same mission and time grid.

The acceptance driver exercises eclipse timing in the orbital and inertial
frames, time-origin shifts, transitions near run boundaries and small apparent
disks. It checks a SciPy reduced-network temperature reference, an analytic
projected body disk, chamber exchange, joint and attitude projection, an
independent lower bound on exchange between facing triangles, time refinement
and stale motion and optics checkpoints. A portable save and reopen exercises
flight and chamber cases with shared identities and rejects a substituted mission.
The current profile uses a circular trajectory, hard umbra, a fixed Sun vector
and independent single-axis joints. WP-17 uses independent native cases for
closure. WP-10 owns the paired TD/RadCAD and ESATAN captures of equivalent
missions for v2.
