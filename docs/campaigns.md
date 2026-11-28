# Thermal campaigns

Use the Windows FCST application CLI with a trusted installed FCST worker and
a native thermal input envelope. The source file stays in place. Each variant
retains the source project ID, revision and entity IDs. Each run has its own
request, model hash and result hash.

```powershell
fcst campaign-run thermal-input.json campaign-spec.json campaign-output --worker fcst-worker.exe
$run = fcst campaign-run thermal-input.json campaign-spec.json transient-output --worker fcst-worker.exe --transient transient-settings.json | ConvertFrom-Json
fcst campaign-report transient-output limits.json --campaign-sha256 $run.campaign_sha256 --html report.html > report.json
```

The output directory and HTML destination must be new. Use a fresh directory to
replay an attempt. A directory without a completed `campaign.json` is partial.
Reports validate each request and result against the manifest and reconstruct
the planned variants and samples before reading their predictions. Retain the
`campaign_sha256` printed by `campaign-run` outside the output directory to pin
the immutable manifest during later review. An incomplete run returns exit code
1 and retains the completed manifest and each attempted run's outcome. Keep
campaign directories local when they contain engineering data.

## Campaign specification

The following steady example uses the load and node from
`tests/fixtures/thermal/material-network.json`. Add `case_id` to a named variant to
select an existing case from the source model. Variants can represent hot/cold,
operating/nonoperating, BOL/EOL or test/flight settings. When the model has
cases, set `case_id` on the input envelope to select the baseline. Named cases
use their declared load and control selections and overlays. All selected
cases use the campaign solve mode and, for transient sweeps, the supplied time
settings. Named case campaigns accept nodal thermal models. WP-17's portable
mission solver runs geometry-derived environment cases through `solve-case`.

```json
{
  "seed": 42,
  "samples": 4,
  "parameters": {
    "heater": {
      "entity": "00000000-0000-4000-8000-000000000012",
      "field": "power",
      "min": 3,
      "max": 7,
      "distribution": "uniform",
      "step": 0.1
    }
  },
  "variants": {"hot": {"parameters": {"heater": 6}}},
  "sensitivity": {
    "node": "00000000-0000-4000-8000-000000000004",
    "time_s": 0,
    "absolute_tolerance": 0.0001,
    "relative_tolerance": 0.0001
  },
  "budget": {
    "jobs": 10,
    "compute_s": 60,
    "per_run_s": 10,
    "memory_mb": 128,
    "artifact_bytes": 1048576
  }
}
```

Parameter bounds and steps use the target quantity's source unit. Uniform and
symmetric triangular marginals support an optional positive definite latent
normal correlation matrix in alphabetic parameter order. The job cap counts
baseline, variants, random samples and both central-difference refinements.
An overlay for a swept quantity uses the same unit as its source quantity. An
explicit or sampled value updates the applicable overlay in that run's copy.
Runs execute sequentially under the Windows worker tree memory limit. The compute
budget is elapsed campaign time and limits each worker's allowed time. The
artifact budget bounds retained requests, results and the manifest. Reports
retain failed sample statuses, perturbation steps, native diagnostics and
sampled values. Optional `fidelity_losses` records conversion notes supplied
with the campaign. Set `uncertainty` to a `node` and `time_s` to summarize
successful samples independently of sensitivity. Without an `uncertainty`
entry, a declared sensitivity response also serves as the uncertainty response.

To fit parameters, add `observations` rows with `sensor`, `node`, `time_s`,
`value`, `unit` (`K` or `degC`), positive `sigma` and a `split` of `training`
or `holdout`. A mapped node and time may appear only once. Steady runs use time
zero. Transient reports linearly interpolate within the retained output grid.
The fitter selects from successful baseline, explicit and sampled points within
the same case using training residuals weighted by uncertainty. It evaluates
the holdout observations after selection. The report retains the original rows,
uncorrelated baseline, selected candidate and interpolation brackets alongside
both sets of predictions. Increase the bounded candidate grid to refine a fit.

## Versioned limits

For example, `limits.json` can contain:

```json
{
  "version": 1,
  "nodes": {
    "00000000-0000-4000-8000-000000000004": {
      "min_K": 290,
      "max_K": 320,
      "margin_K": 2
    }
  }
}
```

Increment the version when editing limit inputs and generate a new report.
Each check applies to the retained temperatures on the output grid. The limits
hash identifies the checks for that version and changes whenever its inputs
change. The campaign hash, requests and historical results stay available for
rechecking.
