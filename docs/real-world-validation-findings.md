# Real-world validation findings

> **Status: findings record (non-binding).** The evidence body lives in
> `experiments/real-world-validation/` (committed results files + per-leg
> READMEs, regenerable via `run_all.py`); the study's working blueprint is
> `docs/build-plan-real-world-validation.md` (kept active — Chunks 5–6 and
> follow-ons remain open). This doc consolidates what the study measured and
> what it means, in the style of `docs/history/prospective-forces-and-progress-findings.md`;
> archive it to `docs/history/` when superseded. Nothing here amends a shipped
> contract — where the study touched shipped behavior, the outcome was either
> "validated as documented" or a named fix chunk (Chunk 5).

## 1. Why this study exists

Every propygator surface is extensively tested, but until this study the
numerical propagator and the TLE fitter had never been compared against a
**measured orbit** — their external anchors were internal consistency, SGP4's
Vallado vectors, and the passes' Skyfield cross-check. The physics engine is
Orekit (flight-proven), so the realistic risk class is **self-consistent
wiring bugs** — a factor-of-2 in area, a frame-convention flip, a config
toggle that never reaches Orekit — which pass every propygator-vs-propygator
test *because they are consistent*. A measured orbit is the one oracle that
can't share the misconception.

Three legs, each building on the last: **LAGEOS-2 vs. ILRS precise orbits**
(conservative forces + frame/time wiring), **GRACE-FO vs. GNV1B
reduced-dynamic orbits** (the drag stack, in quiet / active / storm windows),
and **the TLE fitter vs. reality** (fitted TLE vs. the operational catalog at
predicting real truth). Throughout, the study separates **correctness** (is
the wiring right?) from **predictability** (thermospheric density is
inherently 10–30 % uncertain — that error belongs to the atmosphere model, not
propygator, and part of the study's value is writing down what "normal" looks
like).

## 2. Truth data and provenance

| Truth source | Product | Arc(s) | Class |
|---|---|---|---|
| ILRS precise orbit (LAGEOS-2, NORAD 22195) | ESA AC weekly SP3-c, frame `SLR08`, **with V-records** | 2023-04-16 → 04-23 (7 d, 120 s) | cm-level SLR |
| GRACE-FO 1 GNV1B (NORAD 43476) | PO.DAAC L1B RL04 daily (`GNV1B`, 1 Hz, ECEF), DOI 10.5067/GFJPL-L1B04 | quiet 2019-11-14+ (F10.7 ≈ 70), active 2023-12-20+ (F10.7 ≈ 190), storm 2024-05-10/11+ (Gannon) | cm-level GPS reduced-dynamic |
| Catalog TLEs | Space-Track `gp_history`, nearest epoch to each fit start (−6.1 h / −4.2 h) | quiet + active fit days | operational elements |

Conventions: GPS-time products convert leap-second-free as GPS + 19 s = TAI
(never a hand-rolled leap-second table); UTC-tagged products go into `Epoch`
directly. Truth frames are ITRF realizations (SLRF2008/ITRF2014-class) — the
cm-level realization difference vs. Orekit's IERS-2010 ITRF is far below every
threshold here (noted, not modeled). Raw truth files are never committed;
parsers (`sp3.py`, `gnv1b.py`) verify bit-clean epoch round-trips, exact grid
uniformity, and QC flags before anything is diffed. The study runs in the
propygator **conda env** (propygator itself is the system under test) — the
one locked departure from `docs/experiments_venv.md`.

## 3. Leg 1 — conservative forces and wiring (LAGEOS-2, Chunks 0–1)

The t₀ diff isolates frame/time conversion from all dynamics: ITRF → EME2000 →
ITRF round trip and first-propagated-sample diffs are both **~9e-10 m** —
conversion clean to float noise. The 7-day arc (70×70 gravity, Sun/Moon,
cannonball SRP with Cr 1.13, solid + ocean tides, relativity, drag off,
`high_precision`) against the ILRS orbit:

| horizon | radial RMS | along RMS | cross RMS | 3D RMS / max |
|---|---|---|---|---|
| 1 d | 0.11 m | 3.62 m | 0.05 m | **3.62 / 6.19 m** |
| 3 d | 0.13 m | 10.61 m | 0.10 m | 10.61 / 18.23 m |
| 7 d | 0.28 m | 23.65 m | 0.16 m | 23.65 / 40.55 m |

**Checkpoint A: GO (tier 1, ≲ 20 m/day, with a ~3× margin).** The residual is
almost purely along-track and grows secularly (~6 m/day) with sub-meter radial
and cross-track over the full week — the classic signature of the small
unmodeled along-track accelerations (Earth radiation pressure + thermal
thrust), i.e. the literature floor for this force set. The parked
`earth_radiation` toggle is the named next step for lowering it (§8).

**The ablation matrix (Chunk 1) proves every toggle reaches Orekit.** Each
`ForceModelConfig` boolean was flipped individually; the "expected order" is
computed along the truth orbit (actual EIGEN-6S coefficient sums, actual
DE-ephemeris distances, Schwarzschild on the sampled PV), so the matrix is
self-interpreting. Sign-free dynamical effects |case − baseline| at day 7:
sun+moon off → 781 m; gravity 8×8 → 25.6 m; tides off → 14.1 m; SRP off →
5.9 m; relativity off → 4.5 m — **all seven rows inside their predicted-order
windows**. The two predicted-null rows are null at the mm level: gravity
truncated 70→20 (0.001 m — degrees > 20 genuinely don't matter at 5,800 km)
and **`planets_third_body` on (0.001 m)** — the "completeness only" claim
confirmed against a real orbit. (Two ablations *improve* the vs-truth total —
`relativity off`, `tides off` — because those correct contributions happen to
oppose the unmodeled along-track floor this week; the wiring evidence is the
sign-free effect table, and a boolean toggle can only add or omit a force, not
distort one.)

## 4. Leg 2 — the drag stack (GRACE-FO, Chunks 2 + 2b + 2c)

Per window, a 1-day arc from the truth t₀ (t₀ sanity ≤ 5e-9 m everywhere;
maneuver screens CLEAN; the LAGEOS conservative set + NRLMSISE-00 with real
CSSI space weather). Along-track RMS (m), the drag-dominated component:

| | quiet 2019 | active 2023 | storm peak 05-11 | storm onset 05-10 |
|---|---|---|---|---|
| daily Ap (arc) / max 3-h ap | 3 / 7 | 11 / 27 | **271 / 400** | 105 / 300 |
| Run 1 — drag off | 44.2 | 1057.8 | 3812.5 | 1152.5 |
| Run 2 — drag on, Cd 2.3 | 6.0 | 343.7 | 1664.9 | 341.2 |
| Run 3 — scalar Cd fit | **1.9** | **6.4** | **119.0** | 27.4 |
| fitted Cd (A = 1 m²) | 2.03 | 3.40 | 4.08 | 1.78 ⚠ artifact |
| Run 4 — sphere table, no fit | 20.9 | 210.6 | 1418.2 | 545.9 |
| Run 5 — box table, no fit (IPT-ecef) | 55.0 | 222.6 | 155.6 | 1450.9 |

**The pipeline is proven; the remainder is density.** Run 1 clears the
conservative floor by 11× (quiet) to 953× (storm) — the drag signal scales
with solar activity exactly as it should. Run 2 ≪ Run 1 shows NRLMSISE-00
carries the signal. **Run 3's single scalar Cd collapses the residual to
single-meter class in the quiet and active windows** (44 → 1.9 m,
1058 → 6.4 m): the pipeline is wired correctly, and everything the scalar
absorbs is genuine thermospheric-density bias, not a propygator defect.

**The fitted Cd is a density-bias lever, measured across three windows.** On
the common A_ram = 1.027 m² reference the fitted Cd climbs **1.98 → 3.32 →
3.97** (quiet → active → storm-peak) while the physical Cd moved ~10 % the
other way — anchored on the DSMC band (2.65–4.5; Mehta 2013, arXiv
2503.21651), NRLMSISE-00 over-predicts deep-solar-minimum density by ≳ 25 %,
is roughly unbiased at solar max, and runs **cold at storm peak**. This 2×
lever spans the "10–30 % density uncertainty" the plan named — the number
that calibrates solar-sail expectations (a high-A/m sail lives in the same
band).

**The a-priori Cd tables are physically credible — and density-limited by
construction.** With no reference Cd supplied, on A_ram: sphere table 2.92 /
2.70 / 2.51, box table 4.42 / 4.06 / 3.88 (quiet/active/storm) — the sphere at
the DSMC band's low edge, the box inside it (its larger Cd is the edge-on skin
friction a sphere structurally cannot see — more complete, not over-drag). An
orbit residual constrains only ρ·Cd·A, so the no-fit runs expose the *window's
density bias through the table*, never the table alone:

- **The storm sign test resolved H1.** The box table's share of the fitted
  product ran 2.23× → 1.21× → **0.97×** (quiet → active → storm): its
  persistent over-prediction in the first two windows was NRLMSISE density
  bias, not geometric over-drag — the curves cross at the storm.
- **The Run 4 vs Run 5 ranking is set by the window, not table fidelity**
  (the error-cancellation caveat, demonstrated in both directions): quiet,
  the sphere's too-low Cd partially cancels the hot density model and "wins"
  (20.9 vs 55.0 m); storm-peak, the box nearly matches the *fitted* run
  (155.6 vs 119.0 m) and beats the sphere 9×. Never read Run 4 < Run 5 as a
  table ranking.
- **The box adds only absorbable scale for this ram-dominated body:** scaling
  its Cd·A onto the fitted product collapses Run 5 onto Run 3 in every window
  (1.85 vs 1.86 m; 6.45 vs 6.36 m; 118.6 vs 119.0 m) — the direct Checkpoint-B
  evidence behind **deferring the `box_and_panels` geometry upgrade** (its
  non-absorbable payoff is the edge-on sail regime GRACE doesn't exercise).
  The +0.33 m length-corrected box moves the residual by ≪ the density
  confound (geometry-insensitive, density-limited).
- **The axis convention is proven live:** the wired +Y-on-wind face-sum
  (4.54 / 4.17 / 3.98 m² per window) is far below the wrong-axis mappings
  (~8–14 m²), and the predicted-vs-realized signed along-track at 24 h agrees
  to 2–11 % — the realized drag matches the hand-summed face table.

**Storm findings (Chunk 2c).** A scalar Cd cannot absorb an hour-scale
time-varying density bias: the storm-peak Run 3 lands at **119 m** vs the
quiet/active 1.9 / 6.4 m — the operational caveat for scalar-Cd fits through
storms. The onset arc exposed the study's one unplanned mechanism finding:
**Orekit's `NRLMSISE00` at default switches — propygator's construction — is
driven by the daily Ap, not the 3-hourly ap.** May 10's daily Ap 105 (an
average dominated by the evening storm) smears storm-level density across the
actually-quiet morning: at the same ECEF point and UT hour, density jumps
1.92× from May 9 to May 10 while the real-time 3-hourly ap sat at 3 vs 9
(`experiments/real-world-validation/gracefo/probes/probe_ap_driving.py`) —
and that 1.92× matches the onset arc's artifact fitted Cd ratio
(3.405/1.777) almost exactly. Consequence, shown by the "storm-surprise" run
(Cd held at the active-window calibration through the onset day): **+614 m
along-track by noon, before the storm existed** — with a daily-driven density
model, the prediction-error boundary around a storm is the UTC day boundary
of the index, not the physical onset. The `CssiSpaceWeatherData` provider
*does* carry the true 3-hourly ap; the model's default switch configuration
doesn't consume the history array. The ap-history mode (`withSwitch(9, -1)`)
is a named follow-on (§8), not wired.

## 5. Leg 3 — the TLE fitter vs. reality (Chunk 3 + elected extensions)

**Primary result: the fitter converges on measured truth at catalog parity.**
One day of GNV1B truth (300 measurements) → `fit_tle_detailed`; the fitted TLE
and the same-epoch Space-Track catalog TLE then predict the next 3 days:

| | quiet 2019 | active 2023 |
|---|---|---|
| fit: iterations / post-fit RMS | 17 / **633.5 m** | 16 / **626.9 m** |
| fit-day 3D RMS, fitted vs catalog | **634 vs 762 m** | **627 vs 798 m** |
| +3 d, fitted (B\* fitted) | 17,986 m | 16,680 m |
| +3 d, fitted (B\* held 0) | **2,074 m** | 21,638 m |
| +3 d, catalog | 1,039 m | 7,928 m |
| forward ratio, best config | 0.83–2.00 (B\* off) | 1.08–2.10 (B\* on) |

The ~630 m post-fit RMS is the §1.2 lossiness class (pinned ~495 m on
synthetic references), now measured against a real orbit, flat across the fit
day — SGP4 representation error, not a trend. On the fit day the fitted TLE
*beats* the catalog in both windows. Forward prediction reaches **parity with
the regime-appropriate `fit_bstar`**: over a 1-day solar-minimum arc drag is
unobservable (~44 m/day signal under ~600 m noise), so a fitted B\* is pure
fit residual that extrapolates quadratically (ratio 17× at +3 d) — holding
B\* collapses it; in the active window B\* is genuinely observable and holding
it *hurts*. This is §1.2's own `fit_bstar` guidance validated against
reality.

**Fitting-span sweep (elected):** 1/2/3-day arcs end-anchored on a common
3-day forecast window. A 1-day arc under-conditions B\* in every regime
(12–18.5 km runaways); **2 days is the fitted-B\* sweet spot in both windows**
(4.5 / 2.1 km); 3 days beats 2 nowhere in the default configuration (in-arc
RMS grows with span — SGP4 representation error accumulates — and older data
imports stale density). **The shipped `fitting_span = 2 d` default is
empirically vindicated; the conditional default change was declined.** The
sharpened regime rule: *weak drag → hold a calibrated B\* and fit elements on
the longest clean arc; strong drag → fit B\* on ~2 days* (holding a mismatched
B\* pushes compensation into the fitted mean motion, which extrapolates).
Operational note: at solar max every well-configured fitted TLE beat the
3-day-stale catalog at +3 d by 2–8× — freshness beats catalog pedigree in
high drag.

**State-path check (elected):** the §1.2 `State` reference path — the fitter
propagating its own internal reference, the pre-flight persona's path —
measured against reality for the first time, against a live trajectory-path
twin differing only in reference source (+3 d 3D RMS, m):

| reference | quiet | active |
|---|---|---|
| Trajectory path (truth) | 4,493 | 2,072 |
| State path, Cd 2.3 nominal | 4,954 | 15,285 |
| State path, calibrated Cd (Run 3) | 4,681 | **1,147** |
| State/external, sphere table | 5,632 / 5,630 | 9,484 / 9,484 |
| external, box table (IPT-ecef) | 7,172 | 9,284 |

**The State path is free iff the ballistic coefficient is calibrated.** Quiet:
+4–10 % (reference drift drowns under SGP4 noise). Active with the calibrated
Cd: parity — here even *better* than the truth fit (a smooth model reference
carries no hour-scale density fluctuations for the fit to absorb; single-window
evidence, read as "parity, sometimes better"). Active with the uncalibrated
Cd 2.3: **7.4× the twin** — far beyond the displacement-sum arithmetic,
because the fit inherits the reference's wrong *secular decay* (fitted B\*
1.32e-4 vs the twin's 2.05e-4), a derivative error that compounds through the
forecast. **Nothing in the fit's own diagnostics can see it** — the
uncalibrated fit's in-arc RMS was a beautiful 635 m against its own wrong
reference (the self-consistency trap, live), and the Chunk 6 covariance will
flag conditioning, not reference bias. The guard is a calibrated Cd or a
truth reference.

**A-priori-table rows (elected):** the no-truth persona's calibration source
is the shipped tables — and they are *not* "calibrated" in the State-path
sense. Active: sphere/box land ~4.5× the twin, exactly as their ±20 % product
errors predict; the transfer is ~linear (**~0.4–0.5 km of +3 d error per % of
ρ·Cd·A error at solar max; ~20–25 m/% quiet**), so the State path needs a
**single-digit-% ballistic coefficient** — a bar the tables' density confound
(±20 % at solar max, ×1.5–2.2 in deep minimum) structurally cannot meet. They
buy physical plausibility, not calibration. Two shipped-surface facts fell out:
the **native-State-path ≡ external propagate-then-fit equivalence is now
measured on real data** (every column ≤ 1.9 m, B\* to 2e-8), which validates
the documented remedy for the second fact — **§1.2's State path cannot express
attitude** (no parameter; internal reference pinned to default `LofAligned`),
so an attitude-dependent spacecraft (the box here; a sail in the maintainer's
use case) takes the external route at zero cost.

## 6. What is pinned (the regression guard)

Three test files (the Skyfield-table precedent: fixtures as in-file literals
emitted by the drivers' `--emit-fixture` flags; `orekit` fixture; measured
runtimes in parentheses):

- `tests/propagation/test_real_world_lageos.py` (≈ 7 s) — the pinned ILRS t₀
  state propagated one day; t₀ diff < 1 m (frame/time wiring), day-1 3D RMS
  < 15 m (measured 3.62 — ×4 margin).
- `tests/propagation/test_real_world_gracefo.py` (≈ 17 s) — drag-off day-1
  RMS inside a wide signal band (200–5,000 m; measured 1,058) and drag-on
  < 0.6× drag-off (measured 0.325) — relationships, not absolute meters; plus
  the JVM-free **box face-sum axis pin** at fixed table inputs (wired
  +Y-on-wind mapping smallest, 4.18 m² vs 13.0/8.2 — independent of
  orekit-data, and the Chunk 5 leeward floor moves it ~1e-7).
- `tests/tle/test_fitter_real_world.py` (≈ 2 s) — the fit converges on the
  pinned measured day (145 PV samples); post-fit RMS < 1,500 m (measured
  ~630); identity + epoch policy hold.

**Tolerance policy (binding):** every threshold = measured × a margin generous
enough to absorb orekit-data refreshes (2019–2024 EOP/CSSI are final history;
the margin costs nothing). The pins prove "the wiring didn't regress", not
"the number is exact".

## 7. Honest caveats

- **Thermospheric density is the accuracy floor** for LEO drag work: 10–30 %
  in calm conditions (measured here as the 2× fitted-Cd lever), hour-scale
  and unabsorbable by a scalar in storms (119 m scalar-fit residual), and
  smeared across UTC days by the default daily-Ap driving (§4).
- **Cr sensitivity untested:** the LAGEOS Cr 1.13 vs the literature 1.10–1.13
  band was never swept — SRP is a few-m/day effect there, far below the GO
  tier, but the day-1 pin partially rides it.
- **Sphere-equivalent geometry** for GRACE-FO Runs 1–3 (the scalar fit absorbs
  Cd·A/m, so this is by design); the box run is the base-averaged rectangle
  (ram area exact, wetted side −9.5 % → ~2 % of Cd·A).
- **The Run 4 < Run 5 quiet-window ordering is error cancellation, not table
  fidelity** (§4) — reversed at storm peak.
- **A fitted B\* is a fit residual**, not the catalog value nor a physical
  ballistic coefficient (§1.2's documented behavior, now shown on reality).
- **One-week/one-day arcs per window:** the numbers characterize these arcs;
  the *relationships* are what's pinned.
- `box_face_default` carried noise-level negative leeward entries through
  v0.7.2 (θ=π slice ≤ 0, min −5.8e-4) — harmless in the table path (≤ 0.01 %
  of the face-sum) but `from_callable` rejects Cd < 0, an asymmetry between
  factory paths → **Chunk 5** (floor the generator at zero + validate
  `from_table` inputs; shipped in v0.7.3).

## 8. Named follow-ons (recorded, not built)

- **Chunk 5 — `box_face_default` leeward floor** (order-independent
  maintenance, own branch off `main`; evidence in the build plan). **Shipped
  in v0.7.3.**
- **Chunk 6 — `FitResult` covariance exposure** (order-independent feature,
  own branch, §1.2 amendment at chunk time): sigma(B\*) ≫ estimate reads
  "hold B\*" directly — the clean primitive behind the Chunk 3 B\* regime
  rule. It flags conditioning, **not** State-path reference bias (§5).
  Scope extended 2026-07-17: + the a-posteriori variance factor σ₀ (the
  documented bridge from raw to residual-scaled sigmas) and a derived,
  JVM-free correlation-matrix property (corr(B\*, n) → ±1 is the direct
  collinearity read).
- **Chunk 7 — `FitResult` residual diagnostics** (order-independent feature,
  own branch — or shared with Chunk 6 — §1.2 amendment at chunk time;
  elected 2026-07-17): velocity residual norms + signed
  radial/along-track/cross-track position residuals from the components the
  observer already computes and discards; periodic structure reads "SGP4
  representation error, irreducible", secular along-track reads
  "dynamics/B\* mismatch" — the §5 hand analysis, productized.
- **NRLMSISE-00 ap-history mode** (`withSwitch(9, -1)`): would drive the model
  at 3-hour resolution and fix the daily-Ap smearing (§4); wiring it changes
  all storm-time behavior, so it needs its own validation study — the
  committed Gannon windows are the ready-made test case.
- **`earth_radiation` (parked, upstream-blocked):** when an `orekit_jpype`
  ≥ 13.1.6 wrapper lands, the committed LAGEOS arc is the ready-made
  acceptance test — one new ablation row vs the committed baseline; expected
  signature: the along-track floor *tightens* by the ERP order (meters/day)
  without vanishing (thermal thrust stays unmodeled). Resume kit in
  `experiments/earth-radiation/`.
- **Deferred legs:** GNSS/IGS SP3 (needs box-wing SRP to be interesting), ISS
  OEM (a third drag case), the *fitted* GRACE-FO box (the Checkpoint-B
  deferral — warranted only if a constant cross-section ever fails to explain
  residuals).
- **Watching a predicted ISS pass** — the zero-code end-to-end check; needs a
  clear evening, not a chunk.
