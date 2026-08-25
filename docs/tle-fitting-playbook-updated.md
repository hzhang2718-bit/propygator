# The TLE fitting playbook (updated)

> **Status: practical guidance (non-binding), revised 2026-08-24.** Supersedes
> `experiments/tle-fit-strategy/tle-fitting-playbook.md` (archived unchanged)
> now that the extended-validation study tested it at scale. Evidence base:
> ten GRACE-FO C windows across four solar-activity bands (low / moderate /
> intense / storm) — still one body. Full evidence, every benchmark number,
> and every caveat: `docs/validation-findings.md` §14 (Part 3), §16 (honest caveats),
> §17 (follow-ons). Walkthrough (not yet updated to this revision):
> `notebooks/07_tle_fitting.ipynb` §9.

## The problem this solves

A fitted TLE has two error budgets: the **in-arc lossiness** (~500–700 m RMS
for LEO — SGP4's representation floor, largely irreducible) and the
**forward drift** (how fast prediction degrades past the arc), which spans
1 km to tens of km at +3 days depending entirely on how you handle **B\***.
The central trap, measured repeatedly: **in-arc RMS is an anti-signal** —
the worst-forecasting configurations routinely post the *best* fit RMS,
because a free B\* on a short arc happily absorbs along-track error into a
garbage drag coefficient. Strategy, not fit quality, is what you control.

Two structural facts:

- The estimator basis is Cartesian TEME PV + `BSTAR`. There are no
  per-element holds; **B\* is the only transplantable parameter**.
- The **carrier idiom** makes the transplant public API: put the B\* you
  want held into a TLE (a previous `FitResult.tle`, a catalog TLE, or
  `TLE.from_state_unfitted(state, bstar=...)`) and pass it as
  `initial_guess` with `fit_bstar=False`. The fixed-point seed re-derives
  the six elements at the reference start; only B\* rides through.

## The recipe

One recipe, no branch.

**Step 1 — fit B\* free on the freshest 2-day arc** ending at your reference
epoch:

```python
fit2 = pgr.fit_tle_detailed(ref_last_2d, fitting_span=2 * 86400)
```

**Step 2 — transplant that B\* onto a fresh 1-day refit:**

```python
tle = pgr.fit_tle(ref_last_1d, fitting_span=86400,
                  initial_guess=fit2.tle, fit_bstar=False)
```

That is the entire recipe. There is no longer a decision gate: this one
configuration (`arm_transplant` in the extended-validation study) tied or
beat both alternatives tested (a fresh B\*=0 refit, a fresh free-B\* refit)
in **all 30 of 30** window-by-day cells across four solar-activity bands on
GRACE-FO C — including the **quiet** band, where the original
single-satellite evidence had recommended B\*=0 instead. It also beat a
naive one-shot 2-day fit in 27 of 30 cells (90%, against a 70% bar).

## What changed from the original playbook

The original recipe gated between three arms using two diagnostics, r and
s, computed from the 2-day and 3-day staging fits. Tested at scale, that
gate added no measurable value over always running the transplant — one arm
did the job everywhere, so the study's own revision rule points the recipe
at that arm rather than keeping the gate. **r and s are dropped from this
document entirely**: they were only ever the gate's selection inputs, never
inputs to the fit itself, and the gate they fed is retired. They remain
recorded in `docs/validation-findings.md` §14 as measured, but this
document makes no claim about their standalone diagnostic value — that was
never separately tested.

## Rules of thumb (still measured, unchanged by the extended study)

- **Never trust a 1-day free-B\* fit's B\*** — garbage in every regime. Fit
  1 d arcs with `fit_bstar=False`, always holding something (a transplant,
  or B\*=0 as a last resort with no staging arc available).
- **The physical formula B\* = ½·ρ₀·Cd·A/m is never the answer** — it
  cannot track the multi-× quiet↔active swing in the *effective* B\* and
  injects fake decay (up to 76 km at +4 d, measured in the original
  single-anchor test). B\* is a fit residual, not a ballistic coefficient;
  treat it as one.
- **Epoch placement is irrelevant** — a TLE is a trajectory;
  reparameterizing the same fit at the arc end changes forecasts by < 2 m.
  Anchor your *data*, not the epoch.
- **In-arc residual structure** (`residuals_ric_m`): a secular along-track
  ramp/curvature is a dynamics-mismatch tell in active/storm regimes, but
  drowns under SGP4's ~600 m periodic floor in quiet — absence of structure
  proves nothing there.
- **Anchor-to-anchor forecast scatter runs 2–3×**; treat any strategy
  difference under ~1.5× as noise. The transplant recipe's advantage held
  up across all ten windows and four bands tested; exact RMS values will
  not replicate.
- **State-path users**: this evidence is Trajectory-path (truth-grade
  references). Fitting your own `propagate_numerical` output adds
  reference-model error on top — roughly tracking the reference's own drift
  from truth (`docs/validation-findings.md` §14) — so the §1.2 guidance
  (calibrate the ballistic coefficient, or propagate-then-fit externally
  for attitude-dependent craft) still applies before any of this.

## Fading memory — not part of the default recipe

Age-weighted fitting (measurement sigma inflating with sample age) was
tested as a rival to the transplant recipe across ten windows and six τ
values. It provisionally cleared its pre-registered promotion bar at
τ = 1.5 d, but that result is carried by one window whose gate
misclassification also contaminates its baseline, and it tested only
uniform sampling — a log-spaced axis that pairs naturally with short τ
remains unmeasured. Not adopted here. Full detail:
`docs/validation-findings.md` §14, §16, §17.

## What's still unvalidated

- **One body.** All thirteen configurations ran on GRACE-FO C only; the
  recipe above is regime-validated (ten windows, four solar-activity
  bands) but not body-validated.
- **Refit-cadence tuning** (rolling operations) is still an open,
  unexecuted route.

## See also

- Full evidence and every benchmark number: `docs/validation-findings.md`
  §14 (Part 3), §16 (caveats), §17 (follow-ons).
- The original single-satellite recipe and its open-questions companion,
  archived unchanged in `experiments/tle-fit-strategy/`:
  `tle-fitting-playbook.md`, `tle-fit-strategy-findings.md`.
