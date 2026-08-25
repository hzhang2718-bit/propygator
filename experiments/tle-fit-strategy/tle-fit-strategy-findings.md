# TLE fit strategy — open questions and validation routes

> **Status: working notes (non-binding, forward-looking).** Companion to
> `tle-fitting-playbook.md` (the recipe, same folder) and this experiment's
> evidence. This note records **how to test the playbook further** and **how
> to decide whether fading-memory weighting deserves a §1.2 amendment** — the
> two threads left open by the 2026-07-19 strategy session. Relocated here
> 2026-08-24 from `docs/` by extended-validation Chunk 22; see
> `docs/validation-findings.md` §14/§16/§17 for what that study resolved.

## 1. What is established vs what is assumed

Established (measured, committed in the experiment): the two-stage B\*
transplant, the r/s gate separating quiet/active/storm on 9 anchor-window
combinations, the quiet B\*=0 default to ~3 d, the physical-B\* and
1-day-free-B\* rejections, the epoch-placement null.

Assumed until tested: that the r/s **thresholds** (0.05 / 0.1) and the
regime **arms** transfer beyond GRACE-FO 1 (~500 km, polar, conventional
bus), beyond one window per regime, and beyond truth-grade Trajectory-path
references. The gate's *margins* were wide (6× on r, 23× on s) — the bet is
reasonable, but it is a bet.

## 2. Validation routes for the playbook

Ordered by evidence-per-effort; each is a self-contained experiments-rhythm
probe reusing the strategy experiment's harness.

1. **More GRACE-FO windows (cheapest — same pipeline, same satellite).**
   GNV1B is available for the full mission; pull 2–3 new 10-day windows per
   regime at different solar-cycle phases (e.g. 2020 deep minimum, 2022
   rising activity, a 2024–25 maximum window that is *not* a named storm) and
   rerun probe 3. This directly tests threshold stability across density
   realizations, which anchor-to-anchor scatter (2–3×) says is the dominant
   noise. Success read: the r-gate keeps classifying correctly; the
   quiet-arm B\*=0-vs-held-B\* crossover stays at the ~3–4 d horizon.
2. **A second satellite at a different altitude (the real generalization
   test).** Candidates with public POD truth: Swarm A/C (~450 km, ESA POD —
   stronger drag, tests the active arm harder), Sentinel-3 (~800 km — a
   near-drag-free LEO, tests whether the quiet arm and the r-gate behave at
   genuinely negligible drag), ICESat-2 (~496 km, ATL POD). One window per
   regime each suffices for a first read. Expect the r threshold to hold
   (it is dimensionless) but verify the 2 d staging span still sits past the
   observability knee at other altitudes.
3. **A storm library.** One storm (Gannon) established the s-gate; 2–3 more
   (e.g. 2017-09, 2022-02 the Starlink event window, 2023-04) would
   establish it. Each needs only the probe-4 pattern: 4 truth days, one
   anchor. Key question: does s < 0.1 ever false-negative through a storm
   (certifying a transplant that then fails)? That is the gate's dangerous
   failure mode; it never occurred in the one storm tested.
4. **A matched-staleness catalog parity test.** The strategy experiment's
   catalog rows were ~6 d stale (honest-labeled context). The fair fight —
   playbook TLE vs a catalog TLE whose epoch is *inside* the last fit day —
   needs per-anchor `gp_history` pulls (maintainer's Space-Track access, per
   the study's data-access rule). This would turn "crushes a stale catalog"
   into a same-footing claim worth putting in the README.
5. **Refit-cadence sweep (operational tuning).** Does selfcal 2d→12h beat
   2d→1d? Is there a horizon beyond which re-staging (fresh 2 d fit) beats
   holding yesterday's transplant? Cheap rows on the existing harness;
   turns the playbook into a rolling-operations recipe.
6. **State-path composition.** All evidence is Trajectory-path. One probe
   fitting `propagate_numerical` references (calibrated vs uncalibrated Cd)
   through the playbook arms would measure how much reference-model error
   erodes the gate's margins — the §1.2 State-path guidance predicts it
   simply adds, but that is unmeasured for r and s.

## 3. The fading-memory decision

**Question:** does age-weighted fitting (measurement sigma ∝ exp(age/τ) —
probe 2's mechanism, currently expressible only through fitter internals)
beat the playbook by enough to justify amending §1.2 with a
`measurement_decay_tau` parameter?

**Why it plausibly might:** it is the continuous version of the two-stage
split — B\* information from a sample of age *a* scales ~a⁴·exp(−2a/τ),
peaking at a = 2τ, while the epoch elements ride the freshest samples: each
parameter picks its own effective span in ONE fit. Measured single-anchor
teasers: it rescued the over-averaged quiet 6 d arc (1617 → 1005 m at +3 d,
the experiment's best quiet rows) and matched the transplant class in active.

**Why it might not:** its margin over the best playbook arm was ~5–10 % at
+3/+4 d — inside the 1.5× anchor-noise floor; τ is a sensitive free
parameter (τ 0.75 → 1.0 d moved +3 d RMS 1.75×) with no principled default;
and it muddies the Chunk 6 statistics (sigma0 and the covariance become
weighted quantities, so the r-gate thresholds do not carry over unexamined).

**Decision experiment (extends probe 2, no API change needed):**

- τ-sweep {0.5, 0.75, 1, 1.5, 2, 3} d × {quiet, active} × ≥3 anchors, in
  both modes (B\* free and B\* held), plus **weighted storm rows** (untested —
  fading memory is exactly the mechanism that *should* help nonstationarity,
  and nobody has measured whether it does).
- A **sampling-skew factor**: with uniform 300-sample subsampling, a short τ
  wastes most of the measurement budget on near-zero-weight samples;
  log-spaced sampling toward recency is the natural pairing and should be a
  second axis, not folded in silently.
- The **r-gate interaction**: decide between "compute r/s on unweighted
  staging fits, forecast with the weighted fit" (keeps the calibrated
  thresholds; two extra cheap fits) vs recalibrating r in weighted mode
  (needs an effective-sample-size correction). The first is the conservative
  default.

**Promotion bar (pre-registered so the outcome is honest):** amend §1.2 only
if the weighted fit's median +3 d improvement over the corresponding playbook
arm is **≥1.5× in at least two regimes** (i.e. above the anchor-noise floor)
**with no regime made >1.25× worse** under a *single* recommended τ (or a τ
rule computable from the fit itself). Anything weaker stays an experiments
recipe: the playbook already captures most of the benefit on the shipped
surface, and a knob without a defensible default is a foot-gun.

## 4. Ideas already closed (do not re-open without new evidence)

- **Epoch-at-arc-end fitting** — measured no-op (< 2 m); the §1.2
  epoch-at-reference-start rule is validated.
- **`bstar=` kwarg** — elected against at Chunk 6; the carrier idiom
  (`initial_guess` + `fit_bstar=False`) is the sanctioned route and the
  playbook builds on it.
- **Physical-formula B\* priors** — measured catastrophic (up to 76 km at
  +4 d); B\* is a fit residual, not a ballistic coefficient.
- **Per-element holds / mean-element basis** — structurally unavailable in
  Orekit's `TLEPropagatorBuilder` (Cartesian TEME + BSTAR is the only
  basis; probe-verified at Chunk 6 Step 0).
