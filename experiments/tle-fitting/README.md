# TLE-fitting feasibility probe (Feature 1.2, Chunk 0)

Evidence for `docs/history/build-plan-feature-1.2.md` Chunk 0 (binding contract:
`docs/features.md` §1.2 → "Validated domain & de-risking"): can Orekit's
`TLEPropagatorBuilder` + `BatchLSEstimator` (Levenberg–Marquardt) recipe,
driven through JPype, converge the TLE fit — before any `src/` surface is
written? **Checkpoint A (GO/STOP) is called on these numbers.**

**Reference-only.** Not shipped, not in CI, outside `testpaths`. Every piece
is shipped propygator + the pinned Orekit 13.1.x, so it runs in the
**propygator conda env** (starts the JVM, needs orekit-data) — no throwaway
venv:

```
conda run -n propygator python experiments/tle-fitting/fit_probe.py > experiments/tle-fitting/results.txt
```

Wall time: a few minutes (the 2-day `high_precision` numerical reference
dominates).

## Method

Three scenarios (the build plan's "Decisions to confirm" defaults), each fit
with **both seeds** (`TLE.from_state_unfitted`, the contract default, and
Orekit's `FixedPointTleGenerationAlgorithm` refinement of it) × **BSTAR
driver on/off**:

- **(i) SGP4 self-fit** — the test-suite ISS TLE, `propagate_tle` 2 d @ 60 s
  (TEME). Known-exact answer: must recover the source TLE nearly exactly.
- **(ii) Numerical fit** — the same orbit's first state through
  `propagate_numerical` (`leo_default`, `IntegratorConfig.high_precision()`),
  2 d @ 600 s → TEME. Records the honest RMS the docs will quote (the
  SGP4-lossiness caveat made quantitative).
- **(iii) Molniya/SDP4 self-fit** — the Vallado 08195 case (e ≈ 0.69,
  deep-space branch): an early read on deep-space fragility.

Fit internals: ~300 evenly subsampled `PV` measurements (σ_pos 1 m, σ_vel
1 mm/s, weight 1), `PositionAngleType.MEAN`, `positionScale` 1 m, parameters
convergence threshold 1e-3, max 100 iterations / 100 evaluations. A
`BatchLSObserver` `@JImplements` proxy prints per-iteration physical position
RMS (observed vs estimated, from the `EstimationsProvider`) + the normalized
LS RMS — this is also the de-risk of the one new JPype proxy Feature 1.2
needs (reflection: single abstract method, **no default methods**). Each
converged fit reports a **propagate-back residual** (fitted TLE re-propagated
over the full reference grid) and, on self-fit legs, fitted-vs-source element
deltas. A `positionScale` {1, 10, 100, 1000 m} / threshold {1e-2, 1e-3, 1e-4}
sensitivity sweep closes the run.

## Files

- `fit_probe.py` — the driver (ASCII-only stdout; cp1252 redirect).
- `results.txt` — captured stdout (the committed evidence).

## Result summary (2026-07-09 run)

**All 19 fits converged — no non-convergence anywhere in the matrix.**

- **(i) Self-fit: exact recovery.** With B\* estimated, the fit reproduces
  the source ISS TLE **to the printed digit** (propagate-back residual 0 m
  over the full 2881-sample grid; every element delta 0; B\* 1.66e-4
  recovered exactly). With `fit_bstar` off, the honest degradation: ~1.2 km
  RMS / 2.6 km max over 2 d, B\* held bit-exact at the seed's 0.0.
- **(ii) Numerical fit: ~495 m RMS / ~1.1 km max over 2 d** (B\* on) — the
  SGP4-lossiness number the docs will quote. B\* on beats B\* off (541 m
  RMS), and the fitted B\* (3.0e-5) is a fit residual, not the catalog value
  — as documented. Both seeds reach the **identical** fitted TLE.
- **(iii) Molniya/SDP4: exact recovery too** (0 m propagate-back, all
  deltas 0, B\* exact) — the deep-space branch fits cleanly, at least for
  this self-consistency case.
- **Seed comparison: fixed-point wins everywhere** — same optimum, fewer
  iterations (14 vs 22 self-fit; 18 vs 22 numerical; 2 vs 24 Molniya). Its
  initial residual is ~7 km where `from_state_unfitted`'s is ~1100 km
  (the osculating-in-mean-slots offset). Chunk 2 should seed with the
  fixed-point refinement of the `from_state_unfitted` template (an internal
  choice the contract sanctions).
- **Sweep: flat.** positionScale 1–1000 m and threshold 1e-2–1e-4 all
  converge in 21–22 iterations to the same TLE — the recipe is insensitive
  to both knobs here; baseline (1 m, 1e-3) carried into Chunk 2.
- **Observer proxy: fired on every evaluation** (note: per *evaluation*,
  not per iteration — LM occasionally re-evaluates within an iteration, so
  Chunk 3's `iter N | rms` line can repeat an N; dedupe or print honestly).
- **Residuals are free** (the `FitResult` revisit input): the observer gets
  an `EstimationsProvider` + LS `Evaluation` every iteration; this probe's
  physical RMS is computed from exactly that.
