# Validation findings

> **Status: findings record (non-binding).** One validation record for two
> studies. §§1–8: the v0.7.2 **real-world validation study** (evidence in
> `experiments/real-world-validation/`, working blueprint archived at
> `docs/history/build-plan-real-world-validation.md`, 2026-07-19). §§9–17:
> the **extended-validation study** (evidence in
> `experiments/extended-validation/`; contract
> `docs/extended-validation-updated.md` + build plan
> `docs/build-plan-extended-validation-updated.md`, both to be archived to
> `docs/history/` at study close). Consolidated into one document rather than
> kept as two that have to be read together. Nothing here amends a shipped
> contract — where either study touched shipped behavior, the outcome was
> either "validated as documented" or a named fix chunk (Chunk 5, §8; the
> extended-validation study's own follow-ons are §17).

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

**DSMC band correction (2026-08-24):** the cited band is withdrawn in full —
both edges trace to the same non-DSMC paper's assumed sensitivity values, not
independent DSMC results; detail in
`experiments/real-world-validation/gracefo/README.md` "DSMC band correction."

**The a-priori Cd tables are physically credible — and density-limited by
construction.** With no reference Cd supplied, on A_ram: sphere table 2.92 /
2.70 / 2.51, box table 4.42 / 4.06 / 3.88 (quiet/active/storm) — the sphere at
the DSMC band's low edge, the box inside it (its larger Cd is the edge-on skin
friction a sphere structurally cannot see — more complete, not over-drag).
**DSMC band correction (2026-08-24):** see the note above — this "low edge"
read rests on the same withdrawn citation. An orbit residual constrains only
ρ·Cd·A, so the no-fit runs expose the *window's density bias through the
table*, never the table alone:

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

**Extended (2026-08-24):** every reading above rests on one satellite. The
extended-validation study widens the drag leg to ten stratified GRACE-FO
windows across four solar-activity bands plus Swarm A/B as a
limited-information stress case — see §13; the identifiability caveat above
("An orbit residual constrains only ρ·Cd·A") is restated as a standing rule
in §15.

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

**Extended (2026-08-24):** the playbook and r/s gate above were tested on ten
GRACE-FO windows across four solar-activity bands (still one body) — see §14.
The gate is retired in favor of always-`arm_transplant` as the default
recipe (Chunk 22 writes the playbook language), and the fading-memory
promotion question is resolved provisionally to PROMOTE, with a caveat (§14,
§16).

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
  **Built 2026-07-18 (branch `feature/fitresult-covariance`, shipped in
  v0.8.0), with two probe-forced corrections to the election as recorded
  above.** (1) The basis is **Cartesian, not mean elements** — Orekit
  13.1.x's `TLEPropagatorBuilder` estimates `Px..Vz` at epoch + `BSTAR` and
  offers no orbit-type option. (2) The correlation-matrix property was
  **dropped**: the corr(B\*, n) read it was elected for is falsified —
  recovered from the Cartesian covariance by delta-method projection, it
  measures ≈ −0.97 on the weak ~1-rev arc *and* the drag-observable full
  day alike (B\*/n collinearity is structural to the TLE fit — both act
  along-track), and whole-matrix conditioning reads invert (the healthy
  long arc scores *worse*). Likewise "sigma(B\*) ≫ estimate" as literally
  recorded above fails — the fitted B\* inflates in step with its sigma on
  weak arcs — so the shipped read is **comparative**: raw sigma(B\*)
  across configurations (~1200× collapse, ~1 rev → 24 h on the pinned
  GNV1B day) or σ₀-scaled sigma(B\*) vs a physically plausible B\* (~17×
  the window catalog at ~1 rev → hold B\*; ~0.15× on the full day →
  usable). Full doctrine + evidence in the §1.2 amendment.
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

## 9. Why the extended-validation study exists

Every claim in §§1–8 rests on **one GRACE-FO satellite**. The r/s trust gate,
the regime arms, and the fitted-Cd density lever are all untested bets on
transfer — validated on a single body over a handful of windows. The
extended-validation study (`study/extended-validation`, contract
`docs/extended-validation-updated.md`) attacks that gap with three
independent parts and no shared benchmark apparatus:

1. **Table noise** — do GRACE-FO's own twins (C and D, essentially the same
   body in the same atmosphere) give consistent drag results? (§12)
2. **Drag propagations** — ten stratified GRACE-FO windows across four solar
   activity bands, plus Swarm A/B as a limited-information stress case where
   mass and geometry are estimates rather than measurements. (§13)
3. **TLE fitting tests** — does the playbook's r/s gate, and the
   fading-memory alternative, generalize past the single window per regime
   that produced them? (§14)

The study went through two designs before this one; the first (a
GRACE-lineage body set with a `T = Cd_table/Cd_fitted` metric) is retired,
and its contract and build plan are deleted from the tree — recoverable only
from git history. The identifiability argument that metric rested on
survives as a guardrail (§15); the metric itself does not.

## 10. Truth provenance — the new windows and the Swarm reader

**GRACE-FO.** Same product family as §2 (GNV1B truth, MAS1B mass, THR1B
maneuver record), landed fresh for all ten windows — 84 files/window, ~2.6 GB
retained across all ten. Two gates run before any compute is spent: a THR1B
tier-1 exact parse (`accum_dur_orb_ctrl` flat and both on-times zero) and a
degree-5 polynomial tier-2 (the §2 screen, reused). **10/10 windows CLEAN on
GRACE-FO C**, both gates. Two windows (`intense_2024_11`, `storm_2025_05`)
carry a real burn on **D** — kept, since every Part 2/3 run is on C and D is
read only as Part 3's cross-tag discriminator. MAS1B outages (one day in
`storm_2024_08`, seven in `moderate_2025_07`, both satellites) are read as
the mean over days that exist and bounded at ≤ 0.0102 kg, never interpolated.

**Tier 2 is now 0-for-3 against known-real burns** — it missed both D burns
(0.8% / 1.9% against its 10% bar) and, per §13, missed the Swarm A window-4
burn too. Its bar is not re-fitted (that would be circular); a CLEAN verdict
from this screen is recorded throughout as weak evidence, not a quiet
window.

**Swarm.** No parser existed in the repository. The contract's four-step
format resolution — inspect one delivered file before writing any code —
resolved at step 2: ESA serves **SP3-d, GPS time, IGS14 frame**, 10 s grid,
Earth-fixed V-records (confirmed by differentiating positions to 1e-4 m/s,
against a 20–500 m/s inertial/Earth-fixed gap). `swarm_sp3.py` is a thin
wrapper over the frozen `lageos/sp3.py`, so **Part B was not dropped**. The
time-scale trap (GPS read as UTC costs ~137 km along-track) is closed by
measurement, not assumption: Swarm's t0 lands at `2019-12-23T00:00:19 TAI`,
bit-identical to GRACE-FO C's, offset 0.000 s. Files are cut on GPS days but
named in UTC, so a window day is found by its file's **second** timestamp.
`LOAD_DAYS = 8` — one 7-day arc plus its endpoint sample.

Swarm A and B are **not a twin pair** — 424–470 km vs 486–507 km across the
ten windows, measured off the delivered ephemerides rather than assumed — so
an A-vs-B difference is an altitude difference before it is a body
difference. Mass (419.0 kg) and geometry (1.0 × 5.0 × 1.0 m box, `A_ref`
1.0 m²) are estimates from a public ESA source, fixed for both satellites and
every window; the fitted-Cd row absorbs their error, the two table rows do
not (§13).

**No Swarm window ever diverged from the GRACE-FO list** — the contract's
provision for substituting a window on a detected Swarm maneuver was never
exercised, because the one real Swarm maneuver in the set (window 4, §13)
was not detected until after every window had already run.

**The TLE catalog.** NORAD 43476 `gp_history`, pulled by hand by the
maintainer (no committed fetcher, frozen literals in `catalog_tles.py`, per
the reproducibility rule). **10/10 windows resolved** (latest epoch ≤ `T`),
staleness 1.57–10.22 h. Cross-tagging between the two closely-flying twins is
a known catalog failure mode, so every pull is checked: propagated into
`[T, T + 1 d]`, residual against C must beat residual against D by ≥ 5×;
measured **195–301×, 10/10 PASS** — every window clears the bar by ~40×.

## 11. The window table and how it was drawn

Ten windows, 14 days each, drawn once and frozen (`random.Random`, seed
**20260814**) against band rules fixed before the draw: both NRLMSISE-00
solar inputs in range (window-mean F10.7 and Ctr81) — low ≤ 85, moderate
110–150, intense ≥ 185 — non-storm bands additionally capped at daily
Ap ≤ 30 and 3-hourly ap ≤ 50 every day, ≥ 30 days' separation from every other
window and from the three frozen v0.7.2 windows, ≤ 2 per band per calendar
year. Storm windows are a **census selection**, not a draw — only 8 events in
the drawable span (2018-06 → 2026-05-09, bounded by orekit-data's CSSI
OBSERVED block) reach daily Ap ≥ 80 — chosen for placement and F10.7 spread.

| # | window | band | t0 | F10.7 | Ap max |
|---|---|---|---|---|---|
| 1 | `low_2019_12` | low | 2019-12-23 | 71.9 | 8 |
| 2 | `low_2021_04` | low | 2021-04-15 | 77.3 | 28 |
| 3 | `low_2021_06` | low | 2021-06-17 | 83.1 | 13 |
| 4 | `moderate_2022_04` | moderate | 2022-04-29 | 120.2 | 15 |
| 5 | `intense_2024_06` | intense | 2024-06-14 | 187.4 | 17 |
| 6 | `storm_2024_08` | storm | 2024-08-11 | 242.5 | **127** |
| 7 | `intense_2024_11` | intense | 2024-11-23 | 198.6 | 11 |
| 8 | `storm_2025_05` | storm | 2025-05-26 | 137.4 | **98** |
| 9 | `moderate_2025_07` | moderate | 2025-07-23 | 147.8 | 27 |
| 10 | `storm_2026_01` | storm | 2026-01-13 | 166.0 | **144** |

Full table (Ctr81, ap3, Kp) in the build plan and
`experiments/extended-validation/README.md`.

**Storm placement is deliberate.** With every TLE fit arc ending at day 6,
the three storms sit at day 1 (`storm_2024_08` — a storm-contaminated arc,
calm forecast), days 3–8 (`storm_2025_05` — nonstationarity, the gate's `s`
half), and day 6 (`storm_2026_01` — the contract's mandated
fit-right-before-onset case, satisfied with no extra downloads: the model's
Ap-driven onset sits exactly at the day-6 UTC boundary).

**Two caveats recorded rather than engineered away.** "Intense" exists only
in 2024 (17 eligible starts, all 2024-06-13 to 2024-11-28), so that band is
confounded with mission epoch and altitude. And the stated 2,887-candidate
count implies a t0 span starting 2018-06-01, not the 2018-09-01 the same
sentence gives — left as drawn, since re-deriving it would mean re-drawing.

**The 13→14 day extension (2026-08-15).** Windows were lengthened after the
draw because the TLE part's last forecast sample needs a fourteenth truth
file. The draw was not re-run; instead every window was re-verified against
the same band rules on 14 days. Nine passed unchanged; window 4
(`moderate_2022_04`) failed on its added day and slid **−1 day**
(2022-04-30 → 2022-04-29) under the plan's own failure rule — the smallest
move that restores the band.

## 12. Part 1 — table noise (GRACE-FO C/D twin, Chunk 2)

Same design as the §2 twin question, scaled to the three frozen v0.7.2
windows and this study's rewritten geometry (`A_ref` = 1.0013468 m², box
0.7588835 × 3.6100207 × 1.3195 m — the study's *third* `A_ref`, never
compared to §4's 1.027 m² without converting). Per window, per twin: a 1-day
scalar-Cd fit, then three 1-day propagations (fitted Cd, sphere table, box
table). Four C/D ratios on 3D RMS:

| window | `Cd_fit` | `RMS_Cd_fit` | `RMS_sphere` | `RMS_box` |
|---|---|---|---|---|
| `quiet_2019` | +1.15% | +0.79% | −2.09% | −0.91% |
| `active_2023` | −0.53% | −6.55% | −2.38% | +2.52% |
| `storm_2024` | −0.56% | −0.92% | −1.36% | +0.77% |

**12/12 HIT.** Every ratio clears its bar with margin — worst departure
6.55% against a 20% bar (`RMS_Cd_fit`, active); the twin Cd ratio worst
1.15% against a 10% bar. Both maneuver screens CLEAN on all six
satellite-windows. Full breakdown (radial/along/cross) in
`gracefo/results_table_noise.txt`.

The ratios can leave 1.0 at all because the twins fly a 180° relative yaw
that puts opposite ends of the same tapered bus into the wind, while the
model's box carries equal-area ±Y faces — that asymmetry is present in the
truth and **absent from the model**. The claim is deliberately modest: two
near-identical bodies in the same atmosphere give consistent drag results.
No error bar on a fitted Cd is claimed, and Cd levels are not compared
across `A_ref` conventions (§15).

## 13. Part 2 — drag propagations (GRACE-FO C + Swarm A/B, Chunks 3–13)

Five configurations (drag off, `Cd = 2.3`, in-arc 7-day scalar-Cd fit, sphere
table, box table) × one 7-day propagation each × ten windows × GRACE-FO C and
Swarm A/B — thirty 7-day arcs, each read at day 1/3/7 as **per-day** RMS
(`[N−1 d, N d]`, never accumulated from t0). **This part carries no
benchmark**; the contract states an expectation, not a requirement, and the
bug-hunt trigger is an *inversion* — a table run losing badly where drag is
strong. That trigger **did not fire.**

**The pattern.** In the low-activity windows (1–3) the naive `Cd = 2.3`
performs best and the sphere table trails it; window 3, the most active of
the three, already favors the tables. From moderate activity on (4–10) the
sphere table generally leads and beats `Cd = 2.3`. The **box table is the
worst performer nearly everywhere** — negative removed fraction (worse than
drag off) in windows 1–2 on all three satellites, and rarely close to the
sphere table when drag is strong; where it does edge the sphere table the
win is small, with window 4 the one standout. Day-1 removed fraction of the
drag-off signal, GRACE-FO C (`Cd=2.3` / sphere / box):

| # | window | band | removed fraction | fitted Cd (B = Cd·A/m) |
|---|---|---|---|---|
| 1 | `low_2019_12` | low | 82 / 49 / −36% | 1.797 (3.00e−3) |
| 2 | `low_2021_04` | low | 87 / 56 / −25% | 2.500 (4.17e−3) |
| 3 | `low_2021_06` | low | 74 / 94 / 50% | 2.661 (4.44e−3) |
| 4 | `moderate_2022_04` | moderate | 57 / 69 / 92% | 3.610 (6.03e−3) |
| 5 | `intense_2024_06` | intense | 90 / 96 / 36% | 2.460 (4.13e−3) |
| 6 | `storm_2024_08` | storm | 83 / 92 / 52% | 2.991 (5.02e−3) |
| 7 | `intense_2024_11` | intense | 78 / 88 / 59% | 2.865 (4.81e−3) |
| 8 | `storm_2025_05` | storm | 78 / 91 / 57% | 2.992 (5.03e−3) |
| 9 | `moderate_2025_07` | moderate | 65 / 77 / 80% | 3.289 (5.53e−3) |
| 10 | `storm_2026_01` | storm | 88 / 94 / 35% | 2.308 (3.88e−3) |

Full per-day, per-satellite tables (including Swarm A/B) in
`gracefo/results_drag/`, `swarm/results_drag/`, and the cross-window parse
`results_drag_summary.txt`. **Band label is not drag magnitude**: the day-1
drag-off signal on C tracks F10.7, not Ap, so `storm_2025_05` (704 m) and
`storm_2026_01` (545 m) sit *below* both intense windows (872 m, 1643 m) —
only `storm_2024_08`, the set's highest-F10.7 window, is the largest.

**Swarm carries much larger absolute errors, but the removed-fraction shape
tracks GRACE-FO's** for `Cd = 2.3` and the sphere table — evidence that the
drag stack's *relative* behavior survives a body whose mass and geometry are
estimates, even though the absolute numbers do not (§10). Swarm A and B are
never read as a twin ratio.

**The window-4 Swarm A burn, and what caught it.** Swarm A took a real
**+2,218 m** orbit-raise at t0 + 4.217 d (implied ΔV +1.25 m/s) inside
`moderate_2022_04` — undetected until after every window had run. It railed
Swarm A's 7-day fitted Cd at the 1.5 floor (an artifact, not a body
property); the degree-5 screen called it **CLEAN** (the burn inflated its
own denominator) and separately false-flagged Swarm B in windows 3 and 10 as
REVIEW. The catch was a purpose-built vis-viva energy probe
(`swarm/probes/probe_energy_step.py`, one-revolution-mean semi-major axis
from truth, robust |z| > 20, pre-registered): clean windows top out at
4.3σ, the detection sits at **261.7σ**. The polynomial screen's known-real-burn
record is now **0-for-3** (two GRACE-FO D burns, this Swarm A burn) — every
CLEAN verdict from it is weak evidence, not a quiet window (§16).

## 14. Part 3 — TLE fitting tests (Chunks 14–18)

Thirteen scored configurations per window, all fitted to **truth** except two
state-path rows, GRACE-FO C only. Every arc ends at the common instant
`T = t0 + 6 d`; every forecast runs `[T, T + 7 d]`, read per-day at day 1/3/7
past T. The r/s gate's thresholds are **carried verbatim from
`tle-fitting-playbook.md`** (r < 0.05, s < 0.1) and never re-fitted — a
misclassification is the finding, not something to recalibrate away. Gate
mapping:

| r < 0.05 | s < 0.1 | arm |
|---|---|---|
| yes | yes | `arm_transplant` |
| no | – | `arm_zero` |
| yes | no | `arm_fresh` |

Every fit converged in every window (`run_tle_window.py` hard-exits on
`TLEFitError`); in-arc RMS sat in the ~500–700 m SGP4 lossiness class for
every non-fading-memory row. All ten catalog cross-tags passed (§10).

**The three pre-registered benchmarks (Chunk 18,
`results_tle_adjudication.txt`):**

| benchmark | bar | result | verdict |
|---|---|---|---|
| `[bench-1]` gate vs `naive_2d`, 30 cells | ≥ 70% (21/30) tie-rule | 27/30 = 90.0% (strict: 16/30 = 53.3%) | **HIT** — hinges on the contract's 1.5× tie rule |
| `[bench-2]` gate vs every fixed arm | gate strictly highest hit rate | gate 26/30 = 86.7%; always-`arm_transplant` 30/30 = 100% | **MISS** — the gate is **redundant**, not wrong: one arm does the job everywhere |
| `[bench-3]` fading-memory promotion | ≥ 1.5× median day-3 gain in ≥ 2 bands, no band < 0.8× | `fade_tau_1p5`: intense 1.652×, moderate 3.332×, min band 0.851× | **PROMOTE** — clears the bar, with a caveat below |

Per the contract's rule (a miss on `[bench-2]` revises the playbook *toward*
the arm that redundantly won, not against the gate), the practical read is:
**always-`arm_transplant` is the new default recipe** (Chunk 22 does the
actual playbook rewrite) — regime-validated across ten windows and four
bands, but still body-validated on GRACE-FO alone.

**`[misclass]` — 4 of 30 cells, across 2 of 10 windows.** `low_2019_12` day 7
(gate `arm_zero`, lost to `arm_transplant` by 1.94×) and `moderate_2022_04`
all three days (gate `arm_zero`, lost by up to 4.02×) — the same window
whose t0 slid for the 14-day extension (§11). **`[bench-3]`'s moderate-band
median is carried by this window**, so the PROMOTE verdict is recorded as a
live candidate, not a settled win (§16).

**`[post-hoc]` (labelled, not a re-fit).** The best reachable r/s partition
over this data's own grid scores 30/30 = 100% on the `[bench-2]` metric,
against the frozen gate's 86.7% — an observation about this dataset, not a
claim that the pre-registered thresholds were secretly right.

**Two structural caveats.** The gate mapping is horizon-independent, but the
playbook's own rows carry horizon qualifiers the r/s table drops (`B*=0`
scoped to ~3 d, held B* to ≥4 d, fresh fit to ≤1 d) — so a poor day-3/7
score can be the playbook working as documented past its stated horizon, not
the gate mispredicting; Chunk 18 isolates this with `arm_transplant`, run in
every window regardless of the gate's pick. And the fading-memory result
characterizes **uniform 300-measurement sampling only** — the log-spaced,
recency-weighted axis that naturally pairs with short τ was not measured
(`docs/tle-fit-strategy-findings.md` §3, still open).

**A promotion's cost, if elected:** the fading-memory rows alone needed
`max_iterations = 800` (worst observed demand 471 evaluations,
`intense_2024_06` τ = 0.5) against the shipped default of 100 — a §1.2
amendment would have to raise that ceiling to clear it.

**State-path rows** (2-day arc, sphere/box table references, matching
`naive_2d`'s span): forecast degradation tracks the reference's own drift
from truth roughly linearly, as §5's single-window result predicted — the
a-priori tables cannot meet §1.2's single-digit-percent calibration bar.
Full drift-vs-degradation table in `results_tle_adjudication.txt`
`[also-recorded]`.

## 15. What this study does not claim

Carried from the contract, and applying equally to §4's original GRACE-FO
reading: an orbit residual constrains only the product `ρ·Cd·A/m`. Scaling a
table's error and the density model's error by the same factor changes
nothing observable, so the absolute level of a Cd table's error is not
recoverable from orbit data — adding satellites does not change this.

- **No claim of the form "the tables are off by X%"**, anywhere in this
  study.
- **A fitted Cd next to a table Cd is direction and rough size, never a
  level** — this is why §4's "sphere at the DSMC band's low edge" reading was
  withdrawn (§4, 2026-08-24) independent of this study, and why this study
  never attempts the comparison at all.
- **The tables are judged only by what they do to position error** — §13's
  removed-fraction reading, which is what a user actually experiences.

## 16. Honest caveats

- **"Intense" is a 2024-only band** (§11) — confounded with mission epoch and
  altitude; not separable with this window set.
- **The maneuver screen is weak evidence.** The degree-5 polynomial missed
  all three known-real burns it was ever tested against (two GRACE-FO D
  burns, the Swarm A window-4 burn) — a CLEAN verdict anywhere in this study
  means "no reason to suspect a burn," not "confirmed quiet." No Swarm
  window was ever substituted for a detected maneuver, because none was
  detected in time to substitute one (§10, §13).
- **`[bench-1]`'s HIT depends on the tie rule** — the strict comparison
  (53.3%) would miss the 70% bar. Both numbers are printed; the tie rule is
  the contract's own scoring convention, not a rescue.
- **`[bench-3]`'s PROMOTE is carried by one window.** `moderate_2022_04` is
  both the moderate band's larger contributor (band size 2) and the window
  `[misclass]` flags as the study's worst gate failure (up to 4.02×) — the
  playbook revision (Chunk 22) records this as a live candidate, not a
  closed question.
- **The fading-memory result is uniform-sampling only** — the log-spaced
  axis that pairs naturally with short τ remains untested
  (`docs/tle-fit-strategy-findings.md` §3).
- **Swarm's table rows conflate geometry error with model error** — its
  mass and box are ESA-sourced estimates, not measurements, so a Swarm
  table-vs-truth gap cannot be attributed to the drag model alone the way
  GRACE-FO's Handbook-traceable geometry allows (§10).
- **The daily-Ap storm-smearing mechanism (§4) is unchanged and still
  governs** where every storm window's model onset actually sits — it is
  why `storm_2026_01`'s arc end lines up with the model's onset at all
  (§11).
- **Part 3 tested regime generalization, not body generalization** — all
  thirteen TLE configurations ran on GRACE-FO C only; Swarm was never
  fitted. The r/s gate and the fading-memory result are now validated
  across ten windows and four solar-activity bands on **one** body, not
  across bodies.

## 17. Named follow-ons

Unchanged from §8, still out of scope, still their own future branches: the
NRLMSISE-00 ap-history mode, the `box_and_panels` geometry upgrade, and the
`earth_radiation` resume (upstream-unblocked since 2026-08-03, but forbidden
on this branch's frozen environment either way).

New from this study:

- **A general maneuver-screen upgrade.** The vis-viva energy probe that
  caught the Swarm A burn (§13) is a candidate replacement or supplement for
  the degree-5 polynomial screen generally — its one calibration point is a
  clean sweep (3-for-3 known burns caught) against the polynomial's 0-for-3.
  Not built here; the polynomial stays because building a new detector
  mid-study would be exactly the kind of API-adjacent expansion this
  branch's firewall exists to prevent.
- **The fading-memory promotion decision** (§14, §16) — Chunk 22 writes the
  actual playbook language; this doc records the measured PROMOTE verdict
  and its moderate-band caveat for that chunk to weigh.
- **The log-spaced-sampling axis** for fading memory
  (`docs/tle-fit-strategy-findings.md` §3) — corroborated further here
  (§14's `max_iterations` cost), still unresolved.
- **A second body for Part 3.** This study closes the "single window per
  regime" gap (§16) but not the "single body" one for TLE fitting
  specifically — Swarm ran the drag leg only. Fitting Swarm TLEs against its
  SP3 truth, now that a reader exists (§10), is the cheapest next step.
