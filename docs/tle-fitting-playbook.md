# The TLE fitting playbook

> **Status: practical guidance (non-binding).** A recipe for getting the most
> forward-prediction accuracy out of `fit_tle` / `fit_tle_detailed`, derived
> from the measured evidence in `experiments/tle-fit-strategy/` (2026-07-19,
> building on the real-world-validation study's GRACE-FO truth data). It uses
> only the shipped §1.2 surface — nothing here amends a contract. Evidence
> base: **one satellite** (GRACE-FO 1, ~500 km polar), one window per drag
> regime; the thresholds below are indicative, not calibrated universals.
> Future validation routes: `docs/tle-fit-strategy-findings.md`. Walkthrough:
> `notebooks/07_tle_fitting.ipynb` §9.

## The problem this solves

A fitted TLE has two error budgets: the **in-arc lossiness** (~500–700 m RMS
for LEO — SGP4's representation floor, largely irreducible) and the **forward
drift** (how fast prediction degrades past the arc), which spans 1 km to
50+ km at +3 days depending entirely on how you handle **B\***. The central
trap, measured repeatedly: **in-arc RMS is an anti-signal** — the
worst-forecasting configurations routinely post the *best* fit RMS, because a
free B\* on a short arc happily absorbs along-track error into a garbage drag
coefficient. Strategy, not fit quality, is what you can control.

Two structural facts frame everything:

- The estimator basis is Cartesian TEME PV + `BSTAR` (`parameter_names`).
  There are no per-element holds, and none are possible; **B\* is the only
  transplantable parameter**. Multi-stage strategies are B\* transplant
  chains, full stop.
- The **carrier idiom** makes the transplant public API: put the B\* you want
  held into a TLE (a previous `FitResult.tle`, a catalog TLE, or
  `TLE.from_state_unfitted(state, bstar=...)` as a bare carrier) and pass it
  as `initial_guess` with `fit_bstar=False`. The fixed-point seed re-derives
  the six elements at the reference start; only B\* rides through.

## The recipe

Given reference knowledge of your orbit (a truth trajectory, a POD product, a
high-fidelity propagation) ending at time T, wanting the best TLE for
predicting past T:

**Step 1 — two staging fits, B\* free** (arcs *ending* at T — always anchor
arcs at the fresh end of your data):

```python
fit2 = pgr.fit_tle_detailed(ref_last_2d, fitting_span=2 * 86400)
fit3 = pgr.fit_tle_detailed(ref_last_3d, fitting_span=3 * 86400)
```

**Step 2 — two numbers from the diagnostics** (B\* is line-1 cols 54–61, or
`float(tle.to_orekit().getBStar())`):

```python
k = fit2.parameter_names.index("BSTAR")
r = fit2.sigma0 * fit2.sigmas[k] / abs(bstar2)   # trust: is B* real?
s = abs(bstar3 - bstar2) / abs(bstar2)           # stationarity: does it hold?
```

**Step 3 — the gate:**

| r < 0.05? | s < 0.1? | regime read | do this |
|---|---|---|---|
| yes | yes | drag active & stationary | **transplant**: hold `fit2`'s B\* on a fresh 1 d element refit |
| no | — | drag quiet, B\* unobservable | fresh 1 d refit; **B\* = 0 is fine to ~3 d horizons**; hold a catalog/known B\* only for ≥4 d horizons |
| yes | no | drag strong but **nonstationary** (storm) | freshest 1 d fit, horizon ≤1 d, expect km-class regardless |

The transplant and the quiet arm in code (the carrier idiom):

```python
tle = pgr.fit_tle(ref_last_1d, fitting_span=86400,
                  initial_guess=fit2.tle, fit_bstar=False)   # transplant
tle = pgr.fit_tle(ref_last_1d, fitting_span=86400,
                  fit_bstar=False)                           # quiet: B* = 0
```

## What the arms bought, measured (GRACE-FO vs GNV1B truth, +3 d 3D RMS)

| regime | playbook arm | naive `fit_tle` (2 d, B\* free) | worst trap |
|---|---|---|---|
| active (4 anchors) | transplant: 1.0–3.1 km | 1.9–3.6 km | B\*=0: ~20 km; 1 d free fit: ~16 km |
| quiet (4 anchors) | B\*=0 fresh 1 d: 1.1–1.9 km | 1.4–4.5 km | physical-formula B\*: 48 km; 1 d free fit: ~14 km |
| storm (+1 d only) | freshest 1 d: 0.9 km | 3.1 km | 3 d fit: 5.7 km |

And the operational headline: every playbook arm beat a ~6-day-stale catalog
TLE by 2× (quiet) to 20–30× (active) — refitting from your own orbit
knowledge is worth it even when a catalog entry exists.

## The reads behind the gate (why it works)

- **r** is the σ₀-scaled B\* sigma against the estimate itself. On weak-drag
  or short arcs the fitted B\* inflates *in step with* its sigma (the pinned
  Chunk 6 finding), so r stays large and those fits self-reject; only a ≥2 d
  arc under real drag drives r decisively down (measured: 0.020–0.024 active
  vs 0.15–1.14 quiet). Never read r off a < 2 d fit.
- **s** exists because r certifies *in-arc observability*, not *forward
  validity*: the storm probe's 3 d fit had the experiment's best r (0.005)
  and its worst forecast — B\* measured superbly for an arc whose density
  didn't repeat. Cross-span disagreement (s = 0.32 storm vs 0.014 active) is
  the internal nonstationarity tell.

## Rules of thumb (all measured, see the experiment README)

- **Never trust a 1-day free-B\* fit's B\*** — garbage in every regime (and r
  flags it every time). Fit 1 d arcs with `fit_bstar=False`.
- **The physical formula B\* = ½ρ₀·Cd·A/m is never the answer** — it cannot
  track the ~16× quiet↔active swing in the *effective* B\* and injects fake
  decay (up to 76 km at +4 d). B\* is a fit residual; treat it as one.
- **Epoch placement is irrelevant** — a TLE is a trajectory; reparameterizing
  the same fit at the arc end changes forecasts by < 2 m. Don't fight the
  §1.2 epoch-at-reference-start rule; anchor your *data*, not the epoch.
- **In-arc residual structure** (`residuals_ric_m`): a secular along-track
  ramp/curvature is a dynamics-mismatch tell in active/storm regimes, but in
  quiet it drowns under SGP4's ~600 m periodic floor — absence of structure
  proves nothing there. The covariance, not the residuals, carries the quiet
  signal.
- **Span rules are realization-dependent** (a "longer is better" trend on one
  week inverted on the next); anchor-to-anchor forecast scatter is 2–3×, so
  treat any strategy difference under ~1.5× as noise. The gate's *decisions*
  replicated across all anchors tested; exact RMS values will not.
- **State-path users**: this evidence is Trajectory-path (truth-grade
  references). Fitting your own `propagate_numerical` output adds
  reference-model error on top — the §1.2 guidance (calibrate the ballistic
  coefficient, or propagate-then-fit externally for attitude-dependent craft)
  still applies before any of this.
