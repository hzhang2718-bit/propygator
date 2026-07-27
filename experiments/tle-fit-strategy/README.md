# TLE fit strategy — the v0.8.0 playbook probes

**What this asks:** the `v0.8.0` `FitResult` amendments exposed the estimator's
covariance / `sigma0` and the signed RIC residual structure. This experiment
asks the follow-on question: *what should a user actually DO with those fields?*
Can a fitting **strategy** — multi-fit staging, B\* holds, span/weight choices —
beat the naive single `fit_tle` call, using no external data beyond the
reference orbit itself?

**Provenance:** promoted 2026-07-19 by maintainer election from a
strategy-session's scratchpad probes. Everything reuses the
`experiments/real-world-validation/` kit: the GNV1B parsers, the GRACE-FO leg
configuration, and the truth data under `../real-world-validation/data/gracefo/`
(10 days per quiet/active window on disk — the shipped `--sweep` used only 6;
4 storm days). Catalog TLEs are the study's Space-Track `gp_history` pulls,
duplicated verbatim from `run_fit_vs_catalog.py`. Same rhythm as the study:
reference-only, not shipped, not in CI, outside `testpaths`; committed results
regenerated from these scripts at promotion time.

The user-facing distillation is **`docs/tle-fitting-playbook.md`**; the open
follow-on questions (second-satellite validation, the fading-memory decision)
are **`docs/tle-fit-strategy-findings.md`**.

## Method

End-anchored fit arcs against GNV1B truth, forecasts propagated on the truth
grid and diffed in ITRF (the study's convention). Probes 1–2 use one anchor
(the day-7 start) with a common days 7–10 forecast window; probe 3 replicates
the decision rule at four anchors (day-4/5/6/7 starts, 3-day forecasts);
probe 4 is the storm stress case (day-4 anchor, 1-day forecast). All fits are
public-API `fit_tle_detailed` calls except probe 2, which deliberately drives
`propygator.tle.fitter` internals (unsupported usage, documented in its
docstring) to test two mechanisms the contract does not expose.

The **B\* transplant idiom** used throughout is public API: a TLE carrying the
B\* to hold rides in as `initial_guess`, and `fit_bstar=False` holds it while
the fixed-point seed re-derives the six elements at the reference start (the
carrier pattern pinned by `tests/tle/test_fitter_real_world.py::`
`test_held_catalog_bstar_carrier_configuration`; a `bstar=` kwarg was elected
against in Chunk 6).

## Findings

1. **The two-stage self-calibrated B\* transplant works** (the idea parked
   2026-07-17): fit B\* free on a ~2 d arc, hold it, refit elements on the
   freshest 1 d. In the active window it is the best catalog-free config on
   3 of 4 anchors (+3 d: 1007/1572/2458/3125 m vs held-catalog-B\* 1949–3763 m,
   plain fitted-2d 1945–3632 m, held-zero ~20 km) — the *local* B\* tracks
   current density better than the ~6-day-old catalog value.
2. **A catalog-free trust gate falls out of the v0.8.0 fields.** From a 2 d
   free fit, `r = sigma0·sigma(B*)/|B*|`; across spans,
   `s = |B*(3d)−B*(2d)|/|B*(2d)|`. Measured: active r = 0.020–0.024 (4
   anchors) vs quiet r = 0.15–1.14 (4 anchors) — 6× separation at the 0.05
   threshold, every anchor classified correctly. The storm reads r = 0.011
   (B\* superbly observable in-arc) with a 3.4× *worse* forecast than the
   freshest 1 d fit — r certifies observability, not stationarity — and
   s catches exactly that: 0.323 (storm) vs 0.014 (active) vs 1.65 with a
   sign flip (quiet). This *refines* the pinned Chunk 6 finding rather than
   contradicting it: on weak (~1-rev) arcs B\* inflates in step with its
   sigma so r stays large — weak arcs correctly self-reject; the
   discrimination appears at ≥2 d spans.
3. **Quiet regime:** the shipped sweep's "longer span is better" did NOT
   replicate on new anchors (realization-dependent — probe 1 vs the study's
   `results_fit_span_sweep.txt`). What is robust: fresh 1 d elements. The
   surprise: held-zero-1d beat held-catalog-1d at +3 d on 3 of 4 anchors —
   **B\* = 0 is a fine catalog-free quiet default out to ~3 d horizons**; a
   calibrated B\* only pays at ≥4 d (probe 1's +4 d column: 1270 m held-cat
   vs 2632 m held-zero). Quiet self-calibration stays hopeless (2 d B\*
   swings 4× between anchors; 6 d underestimates 3.5×).
4. **The physical-formula B\*** (`0.5·rho0·Cd·A/m` = 3.09e-4 for GRACE-FO) is
   catastrophic as a hold — 76 km at +4 d quiet, 20 km at +3 d active. It
   cannot track the 16× quiet↔active swing in the *effective* B\*. Never use.
5. **Epoch-at-arc-end fitting is a mathematical no-op** (probe 2: < 2 m
   forecast deltas — the same converged trajectory reparameterized). The
   §1.2 epoch-at-reference-start rule costs nothing; the catalog's forecast
   edge is fresh *data*, never epoch placement. Negative result, kept.
6. **Age-weighted (fading-memory) fits are a real single-fit rival** (probe 2,
   internals): sigma ∝ exp(age/tau) rescued the over-averaged 6 d quiet arc
   (1617 → 1005 m at +3 d with held catalog B\*, tau = 2 d — best quiet
   +2/+3/+4 d rows of the experiment) and matched the transplant class in
   active (fitted 3 d tau = 1 d: 1309 m at +3 d). tau is a sensitive free
   parameter (tau 0.75 vs 1.0 d: 1.75× at +3 d). Whether this deserves a
   §1.2 amendment is the open question in
   `docs/tle-fit-strategy-findings.md`.
7. **Every refit crushes a stale catalog TLE** — the ~6-day-stale catalog row
   reads 2.2 km (+3 d quiet) and 37 km (+3 d active) against 1.0–1.2 km for
   the playbook arms: `fit_tle` as a *TLE refresher* for an operator with
   orbit knowledge is the operational headline.
8. **Honest noise floor:** +3 d forecast RMS varies 2–3× between anchors
   within a fixed config. Strategy differences under ~1.5× are not decisive
   (e.g. the day-4 anchor flips selfcal vs held-cat in active).

## Caveats

One satellite (GRACE-FO 1, ~500 km, polar), one window per regime, 4 anchors
quiet/active + 1 storm anchor. The r/s thresholds (0.05 / 0.1) are calibrated
on this data — margins are wide (6× / 23×) but single-satellite. References
are truth-grade (the 1.2 Trajectory path); State-path users stack
reference-model error on top. Validation routes: see
`docs/tle-fit-strategy-findings.md`.

## Running

Runs in the propygator conda env (JVM + orekit-data + the study's GNV1B data
already on disk); stdout is ASCII-only, fit progress goes to stderr:

    cd experiments/tle-fit-strategy
    conda run -n propygator python probe1_strategy_matrix.py quiet_2019  >  results_probe1_strategy_matrix.txt
    conda run -n propygator python probe1_strategy_matrix.py active_2023 >> results_probe1_strategy_matrix.txt
    conda run -n propygator python probe2_epoch_and_weights.py quiet_2019  >  results_probe2_epoch_weights.txt
    conda run -n propygator python probe2_epoch_and_weights.py active_2023 >> results_probe2_epoch_weights.txt
    conda run -n propygator python probe3_rule_replication.py quiet_2019  >  results_probe3_rule_replication.txt
    conda run -n propygator python probe3_rule_replication.py active_2023 >> results_probe3_rule_replication.txt
    conda run -n propygator python probe4_storm.py > results_probe4_storm.txt

## Files

- `probe1_strategy_matrix.py` → `results_probe1_strategy_matrix.txt` — the
  16-config matrix (fitted/held-cat/held-zero/held-phys/two-stage) + the
  v0.8.0 diagnostics per fit, day-7 anchor, both windows.
- `probe2_epoch_and_weights.py` → `results_probe2_epoch_weights.txt` — the
  two internals mechanisms: epoch-at-end (no-op) + fading-memory weights.
- `probe3_rule_replication.py` → `results_probe3_rule_replication.txt` — the
  r-gate decision rule at 4 anchors per window.
- `probe4_storm.py` → `results_probe4_storm.txt` — the storm stress case and
  the s-gate evidence.
