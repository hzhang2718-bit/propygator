# Build plan: Real-world validation — measured orbits vs. the numerical propagator & TLE fitter

> **Status: BUILD PLAN (not started).** This is a **validation study, not a feature**
> — there is no `features.md` contract because no public API is added or changed.
> The binding outputs are *evidence*: committed experiment results, a findings doc
> (`docs/real-world-validation-findings.md`), and pinned regression tests. Where the
> study contradicts a shipped behavior, that is a **bug report against the shipped
> contract**, handled on the normal fix path — this plan never silently amends
> `features.md`. Status headers are the maintainer's — trust the git log for true
> status.

## Context

Every propygator surface is extensively tested, but the numerical propagator and
the TLE fitter have **never been compared against a measured orbit** — their
external anchors so far are internal consistency (round-trips, pinned self-fit
numbers) plus SGP4's Vallado vectors and the passes' Skyfield cross-check. The
physics engine itself is Orekit (flight-proven, independently validated), so the
realistic risk class is **self-consistent wiring bugs** — a factor-of-2 in area, a
frame-convention flip, a config toggle that never reaches Orekit — which pass every
propygator-vs-propygator test *because they are consistent*. Measured orbits are
the only oracle that can't share the misconception. (A hand-rolled raw-`orekit_jpype`
diff harness was considered and **rejected** for exactly that reason: it re-derives
the configuration from the same understanding that built propygator.)

Three legs, ordered so each builds on the last:

1. **LAGEOS-2 vs. ILRS precise orbits** — the conservative-force + wiring
   diagnostic. A passive laser-ranged sphere (the one satellite
   `SpacecraftGeometry.sphere` models *exactly*) at ~5,800 km: no meaningful drag,
   cm-level truth. Validates gravity + tides + third body + relativity + cannonball
   SRP end-to-end, then an **ablation matrix** proves each `ForceModelConfig`
   toggle individually reaches Orekit.
2. **GRACE-FO vs. GNV1B reduced-dynamic orbits** — the drag stack. Real LEO
   (~500 km), cm-level GPS-determined truth, run in a solar-quiet and a
   solar-active window. The drag-off / drag-on / fitted-Cd trio separates "the
   pipeline is wrong" from "thermospheric density is inherently 10–30% uncertain"
   — and calibrates expectations for the maintainer's solar-sail use case.
3. **TLE fitter vs. reality** — fit a TLE to a day of GNV1B truth, then measure
   how it *predicts* later GNV1B truth, side-by-side with the operational catalog
   TLE of the same epoch doing the same job.

**End state:** propygator can honestly claim "validated against ILRS and GRACE-FO
precise orbits", with the numbers recorded in a findings doc, the stable ones
pinned as regression tests, and a one-line README note.

**Risk profile: front-loaded, and a bad number is a *success mode*.** Chunk 0 is
the whole LAGEOS diagnostic; Checkpoint A is **GO / INVESTIGATE**, not GO/STOP —
a kilometer-scale residual doesn't kill the study, it *is* the study (the plan
switches into bug-hunt mode, which is precisely what this work exists to catch
before real use does).

**Separate correctness from predictability.** Even with perfect wiring, LEO drag
prediction is density-limited: NRLMSISE-00 is typically 10–30% off (worse in
storms), which maps directly into along-track growth. Part of this study's value
is writing down what "normal" looks like so future real-world error isn't misread
as a propygator defect.

### Source-of-truth docs (do not silently diverge)

- `docs/architecture.md` §4/§10 (boundary + frame/time invariants), §11 (testing —
  the pinned-reference-data precedent this study extends).
- `docs/features.md` §1.1 / §1.2 — the shipped contracts *under test*. This plan
  reads them; it never edits them.
- `docs/experiments_venv.md` — the experiments hygiene rules. **One deliberate
  departure, locked below:** this study runs in the **conda env**, not the
  throwaway venv (propygator itself is the system under test; the parsers are pure
  text + NumPy).
- `docs/release-process.md` — only if the maintainer opts to tag at wrap-up.
- `CLAUDE.md` "Java↔Python boundary notes" + the ASCII-stdout experiments rule.

### Decisions already locked (2026-07-11 discussion; do not relitigate)

- **Runs in the conda env** (`conda run -n propygator …`). No new dependencies:
  SP3 and GNV1B are plain-text formats parsed with the stdlib + NumPy.
- **Raw truth files are never committed** (GNV1B is ~10 MB/day). Committed
  evidence is `results.txt` + README per experiment folder (the experiments
  pattern) plus **small extracted fixtures** — initial PV + a few dozen sparse
  truth samples as literals in the test files (the Skyfield 10-pass-table
  precedent), tens of KB total.
- **No public-API change, no `features.md` edit, no minor version bump.** SemVer
  minor means new public surface; this is experiments + tests + docs. A **patch
  tag (`v0.7.2`) at wrap-up is the maintainer's call**; a wiring bug, if found,
  drives its own fix + release on the normal path.
- **LAGEOS-2 first** — it isolates conservative forces and frame/time handling
  with the cleanest public truth that exists; GRACE-FO only after the
  conservative-force floor is established (otherwise drag residuals are
  uninterpretable).
- **GRACE-FO geometry starts as a sphere-equivalent frontal area.** The
  `box_and_panels` geometry-fidelity upgrade is a **named deferral**, taken only
  if Checkpoint B shows residuals that a constant cross-section can't explain.
  (Chunk 2b already *probes* that geometry no-fit with `InPlaneTracking` — which
  for this near-circular, ram-dominated body is drag-equivalent to the physically
  faithful `NadirPointing`, flight-path angle ≲ 0.1°; the deferral is the *fitted*
  box run, not the probe.)
- **The ablation matrix is the wiring proof** — each force toggle flipped
  individually must move the LAGEOS residual by roughly its literature-predicted
  order (and `planets_third_body` must move ~nothing, testing the completeness
  claim against reality).
- **Time route:** truth-product GPS time converts leap-second-free as
  GPS + 19 s = TAI → `Epoch.from_iso(..., TimeScale.TAI)` /
  `Epoch.from_datetime(..., TimeScale.TAI)`; UTC-tagged products go in directly.
  Never a hand-rolled leap-second table.
- **Frames:** truth products are ITRF realizations (SLRF/ITRF2014-class); the
  cm-level realization differences vs. Orekit's ITRF are far below every
  threshold in this plan — noted in the findings doc, not modeled.

### Decisions to confirm (defaults chosen; "You provide" flags them)

- **Branch name.** Default `study/real-world-validation` (maintainer creates off
  `main`; the `feature/` prefix would misdescribe it, but the name is yours).
- **LAGEOS-2 span.** Default: one 7-day arc in 2023 (well inside the local
  orekit-data EOP coverage; exact week picked at chunk time by product
  availability).
- **GRACE-FO satellite + windows.** Default: GRACE-FO 1 (NORAD 43476); one quiet
  week (2019, deep solar minimum, F10.7 ≈ 70) + one active week (2023–24,
  F10.7 ≳ 150, screened storm-free). Exact weeks screened maneuver-free at chunk
  time. **Amended 2026-07-13:** a third, storm window added by the elected
  Chunk 2c (Gannon storm, May 2024).
- **The GO/INVESTIGATE call at Checkpoint A** and the **pinnable-bounds call at
  Checkpoint B** are the maintainer's.
- **Tag `v0.7.2` at wrap-up?** Maintainer's call (current version 0.7.1).

### Data access (read once)

Both truth sources sit behind a **free NASA Earthdata account** — registering and
downloading are the maintainer's steps; scripts consume local files from a
gitignored `experiments/real-world-validation/data/` directory.

- **ILRS precise orbits (LAGEOS-2):** SP3 files from the CDDIS archive
  (`slr/products/orbits/…` — per-analysis-center weeklies + the ILRSA
  combination). Fallback mirror: EDC (DGFI-TUM). A week is a few hundred KB.
- **GRACE-FO GNV1B:** Level-1B daily tarballs from PO.DAAC (expected dataset
  `GRACEFO_L1B_ASCII_GRAV_JPL_RL04`); fallback: GFZ ISDC. ~10 MB/day.
- **Exact product paths/URLs are verified by web search at chunk time**, not
  trusted from this plan.
- **orekit-data coverage:** 2019–2024 EOP and CSSI space-weather history are
  final and safely inside the repo's snapshot; nothing in this plan uses dates
  near the snapshot's download edge.
- **Historical catalog TLEs (Chunk 3)** are not fetchable via `fetch_tle`
  (CelesTrak-only, current epoch): the maintainer pulls the two reference TLEs
  from the Space-Track web UI (credentials per the repo's `.env` convention) and
  pastes them into the experiment folder.

### Architecture invariants to honor (CLAUDE.md / architecture §4, §10, §11)

Experiment scripts: **ASCII-only stdout** (captured under cp1252), `pathlib.Path`,
lazy `org.orekit.*` imports, reference-only (outside `testpaths`, excluded from
CI/lint). Shipped additions (Chunk 4 tests only): JVM access via the **`orekit`
fixture**; no new public exports; `import propygator` stays JVM-free; pinned
fixtures small enough to live as literals.

---

## How to use this plan

- **10 chunks (0–7, with 2b and 2c inserted after 2)**, each sized for one
  Claude Code session:
  - **Chunk 0 is the diagnostic gate** (LAGEOS end-to-end → Checkpoint A).
  - **Chunks 1–3 (2b and 2c included) are the evidence body**; **Chunk 4 is wrap-up**
    (the only *study* chunk that touches `src/`-adjacent surfaces: `tests/`,
    docs, README).
  - **Chunk 5 is order-independent maintenance** (the `box_face_default`
    negative-leeward grid fix discovered by Chunk 2b) — its own branch off
    `main`, addressable in isolation at any time; no study chunk depends on it.
  - **Chunk 6 is order-independent feature work** (the `FitResult` covariance
    exposure elected from Chunk 3's B\* finding) — like Chunk 5 its own branch
    off `main`, but on the normal *feature* path (it adds public surface);
    no study chunk depends on it.
  - **Chunk 7 is order-independent feature work** (the `FitResult` residual
    diagnostics elected 2026-07-17 from the Chunk 6 scoping discussion) —
    same shape as Chunk 6: own branch off `main`, the normal feature path,
    no study chunk depends on it; may share Chunk 6's branch/release
    (maintainer's call).
- Each chunk lists **Goal / Create-Edit / Reuse / You provide / You run / Verify**.
- **Checkpoint A (after Chunk 0) is GO / INVESTIGATE** — never a silent shrug: a
  bad diff reroutes the plan into localized bug-hunting (the t₀ diff, then the
  ablations, are the localization tools) and any confirmed defect exits to the
  normal fix path before the study resumes.
- **Checkpoint B (after the GRACE-FO leg — Chunk 2 + 2b)** decides what is
  pinnable and whether the GRACE-FO geometry upgrade is warranted (Runs 4 & 5 are
  the geometry evidence).
- **Commits, CHANGELOG entries, chunk-header "done" marks, downloads, and any
  release are the maintainer's.** Claude writes scripts/tests/docs and runs
  read-only/test commands.
- **Mergeable chunks:** 2, 2b, 2c, and 3 share the GNV1B data pipeline; adjacent
  ones can run in one session (with 2 + 2b done, 2c + 3 is the natural remaining
  pairing).
- **2026-07-15 reorganization (pre-Chunk-4 cleanup, maintainer-requested):**
  shared analysis math centralized in `experiments/real-world-validation/common.py`
  (RIC/rms, formerly hosted by the Chunk 0 driver), the GRACE-FO leg constants /
  factories / measured anchors in `gracefo/gracefo_common.py` (formerly split
  across drivers), the diagnostic probes moved to `gracefo/probes/`, a top-level
  study README added, and `run_all.py` added as the one-command
  regenerate/verify orchestrator. All five results files were regenerated from
  the reorganized drivers and verified to reproduce the committed numbers
  (wall-clock timing lines aside). Chunk texts below keep their original file
  references except where a path moved.

---

## Git (read once)

The maintainer creates **`study/real-world-validation`** off `main`. Per-chunk
rhythm: maintainer commits + pushes after each verified chunk (committed evidence
= scripts + README + `results.txt`; never raw truth files — extend
`.gitignore` for `experiments/real-world-validation/data/` in Chunk 0). At
wrap-up: squash-merge; the optional `v0.7.2` tag follows
`docs/release-process.md` if taken.

---

## Chunk 0 — LAGEOS-2: truth data, SP3 parser, the first 7-day diff → Checkpoint A - Done

**Goal:** the complete conservative-force diagnostic running end-to-end — truth
in, `propagate_numerical` out, residuals decomposed — so Checkpoint A reads one
table and makes one call.

**Create / edit** (all in `experiments/real-world-validation/lageos/`;
reference-only; ASCII-only prints):
- `sp3.py` — a minimal generic SP3 parser: reads the header **time-system field**
  (GPS → TAI via the locked +19 s route; UTC direct), epochs → `Epoch`, positions
  km → m (SI at the boundary), ITRF; velocity from `V`-records when present, else
  central Lagrange differentiation of neighboring positions (cm-level noise over
  minutes-spaced samples → sub-mm/s error; both routes printed and compared when
  V-records exist).
- `run_lageos.py` — the driver:
  1. Initial `State` at t₀ in `Frame.ITRF` → `.to_frame(Frame.EME2000)` (the
     inertial-frame rule).
  2. Config: `ForceModelConfig(drag=False, solid_tides=True, ocean_tides=True,
     relativity=True)` at 70×70; `SpacecraftGeometry.sphere` with A = 0.2827 m²
     (0.30 m radius), `reflectivity_coefficient` ≈ 1.13, mass 405.38 kg —
     literature values re-confirmed at chunk time and cited in the README.
  3. `propagate_numerical` over the 7-day arc, `IntegratorConfig.high_precision()`,
     then `Trajectory.at()` sampled on the truth epochs (converted back to ITRF
     for the diff).
  4. A pure-NumPy RIC (radial / along-track / cross-track) decomposition helper
     built from the truth PV.
  5. Prints: the **t₀+ε sanity diff** (isolates frame/time conversion from all
     dynamics — must be ~0 before anything else is interpretable), then RMS + max
     residuals per component at 1 d / 3 d / 7 d.
- `README.md` (provenance: product, analysis center, span, parameter citations) +
  committed `results.txt`.
- `.gitignore` entry for `experiments/real-world-validation/data/`.

**Reuse:** `Epoch.from_iso` / `TimeScale.TAI`, `State.to_frame`, `Trajectory.at`,
`ForceModelConfig`, `SpacecraftGeometry.sphere`; `experiments/tle-fitting/` as the
folder/README/results template.

**You provide:** the Earthdata account + the downloaded SP3 week; span
confirmation; **the Checkpoint A call.**

**You run:** the download;
`conda run -n propygator python experiments/real-world-validation/lageos/run_lageos.py`;
commit the evidence.

**Verify:** parser round-trips a truth epoch bit-cleanly; the t₀+ε diff is
~0 (≪ 1 m); the 1/3/7-day residual table prints and is committed.

> ### ⛔ Checkpoint A — GO / INVESTIGATE (maintainer's call) - GO
> Read the day-1 residual against three tiers:
> 1. **≲ 20 m/day → GO.** The conservative-force wiring is proven at the level
>    this study needs (literature floor for this force set is meters/day —
>    unmodeled Earth-radiation + thermal thrust). Proceed to Chunk 1; note the
>    number the Chunk 4 pin will be derived from.
> 2. **~20–500 m/day → INVESTIGATE inputs first.** Most likely Cr/mass/area or a
>    truth-product misread, not wiring — sweep Cr, re-check the parser against a
>    second analysis center's SP3 before suspecting the stack.
> 3. **> ~500 m/day → INVESTIGATE wiring.** The t₀+ε diff localizes: nonzero →
>    frame/time conversion; zero-then-secular-growth → a force is wrong/missing —
>    run the Chunk 1 ablations early as the localization tool. A confirmed defect
>    exits to the normal fix path (its own branch/test/release); the study resumes
>    after.
> 4. Commit + push the evidence **whatever the outcome** — a bad number recorded
>    is the study working as designed.

---

## Chunk 1 — LAGEOS-2 ablation matrix: the per-toggle wiring proof - Done

**Goal:** direct evidence that every `ForceModelConfig` boolean actually reaches
Orekit — the class of bug internal tests structurally cannot see.

**Create / edit** (`experiments/real-world-validation/lageos/`):
- Extend `run_lageos.py` (or add `run_ablations.py`) to rerun the Chunk 0 arc
  with one change at a time: `srp=False`; `relativity=False`;
  `solid_tides=False, ocean_tides=False`; `sun_third_body=False,
  moon_third_body=False`; gravity truncated to 20×20 and 8×8;
  `planets_third_body=True`.
- Each row reports day-1 and day-7 RMS deltas vs. the full-config baseline. The
  script also prints the expected order of magnitude per force (computed
  acceleration ratios sampled along the orbit — no literature table hardcoded),
  so the matrix is self-interpreting: **every ablation must degrade agreement by
  roughly its predicted order; `planets_third_body` must change ~nothing.**
- Results + a short interpretation appended to `results.txt` / README.

**Reuse:** everything from Chunk 0; the run is embarrassingly parallel in
wall-clock (a handful of 7-day propagations — minutes each).

**You provide:** nothing new.

**You run:** the ablation script; commit.

**Verify:** the matrix is monotone-sensible (no ablation *improves* agreement
materially; each moves it in the predicted order; the planets row is null).
Any row that misbehaves = a located wiring bug → the Checkpoint A item-3 exit.

---

## Chunk 2 — GRACE-FO GNV1B: the drag stack, quiet + active - Done

**Goal:** the full drag pipeline (NRLMSISE-00 + real CSSI space weather + the
shared `DragSensitive` proxy) measured against a real drag-perturbed orbit, with
the residual decomposed into "pipeline" vs. "density model" by construction.

**Create / edit** (`experiments/real-world-validation/gracefo/`):
- `gnv1b.py` — parser for the GNV1B ASCII product: YAML-ish header skipped,
  GPS-seconds-since-the-GRACE-epoch → TAI (the locked +19 s route), Earth-fixed
  PV records (frame flag checked), quality flags honored, subsampled to 30–60 s
  (1 Hz truth is far denser than needed — confirm native sampling against the
  L1B handbook at chunk time).
- `run_gracefo.py` — per window (quiet 2019 / active 2023–24):
  - **Maneuver screening:** a drag-off residual scan over the candidate weeks; a
    jump discontinuity = maneuver → slide the window (SDS monthly reports as the
    cross-check if ambiguous).
  - Spacecraft: sphere-equivalent — defaults mass 600 kg, frontal area 1.0 m²,
    Cd 2.3, **replaced by GRACE-FO handbook/macro-model values at chunk time**
    (cited in the README).
  - **Run 1 — drag off:** the residual growth *is* the drag signal; must clear
    the Leg-1 conservative floor by an order of magnitude (expect
    ~0.5–1 km/day along-track at ~500 km, activity-dependent).
  - **Run 2 — drag on** (`leo_default`-style + tides/relativity on): the residual
    is now density × Cd error; the healthy band is ~10–30% of Run 1's signal.
  - **Run 3 — scalar Cd fit:** coarse scan + golden-section refine on Cd
    minimizing day-arc along-track RMS (a handful of propagations, pure Python
    around `propagate_numerical`). If one scalar collapses Run 2's residual, the
    pipeline is proven and the remainder is genuine density bias — the number
    that calibrates solar-sail expectations.
  - Prints: per-window table — RIC RMS/day for runs 1/2/3, the Run 2 / Run 1
    ratio, the fitted Cd (vs. the literature value), F10.7/Ap context for the
    window.
- `README.md` + committed `results.txt`.

**Reuse:** the Chunk 0 RIC helper + driver skeleton; `Epoch`/`State`/`to_frame`
as before.

**You provide:** the GNV1B downloads (both windows); window confirmation.

**You run:** the downloads; the driver per window; commit.

**Verify:** screening found maneuver-free weeks; Run 1 ≫ conservative floor;
Run 2 materially beats Run 1; Run 3 ≤ Run 2; the quiet-vs-active contrast is
visible in the fitted Cd / residual ratio.

---

## Chunk 2b — Runs 4 & 5: the a-priori Cd-table probe (Checkpoint B geometry evidence) - Done

**Goal:** measure what propygator's *generated* drag tables predict for a real
orbit with **no reference Cd supplied** — the isotropic `VariableCd.sphere_default`
and the per-face `BoxFaceCd.default`. This is the direct evidence for Checkpoint B's
geometry decision, and it answers the pre-flight-Cd question behind the maintainer's
solar-sail use case: before flight data comes back, these tables are the only Cd
estimate available, so it matters what they predict against a real orbit. A scratch
probe (retained as `gracefo/probes/probe_tables.py`; **superseded geometry** — its
docstring and the ISSUE notes below say how) already queried the tables at
GRACE-FO conditions; Runs 4 & 5 turn that table lookup into committed *orbit*
residuals.

**Physics framing (resolved 2026-07-12 discussion; do not relitigate):**
- An orbit residual constrains only the **ρ·Cd·A product**, so a no-fit table run is
  **density-limited** — it exposes NRLMSISE-00's density bias, it does not test the
  Cd in isolation. Expect *both* tables to **over-predict** drag in the quiet window
  (NRLMSISE over-models solar-min density). That is the finding, not a defect.
- On a **common frontal reference** (`A_ram = 1.027 m²`) the tables are physically
  credible and DSMC-consistent (Mehta 2013; arXiv 2503.21651 give Cd ≈ 2.65–4.5):
  sphere ≈ 2.9, box ≈ 4.3, vs. the density-depressed fitted ≈ 2.0. The box is the
  **more complete** model (it adds edge-on skin-friction the sphere structurally
  cannot see); it is *not* over-estimating. The alarming sphere-vs-box gap in the
  scratch probe was a reference-area artifact (sphere referenced to A = 1.0, box to
  its real face areas) plus the density confound — not a box bug, Sentman fault, or
  table-setup error (verified by reading both generators + the per-face closed form).
- GRACE is a **bluff, ram-dominated body**, not the edge-on feathered plate BoxFaceCd
  exists for — so the box's extra fidelity here is nearly all **absorbable by a
  scalar** (the `BoxFaceCd` docstring's "face-on / nadir-held → < 1% along-track"
  regime). Its non-absorbable payoff belongs to the sail's own study.

**Geometry — base-averaged rectangle at real dimensions (method resolved 2026-07-12):**
GRACE-FO is a trapezoidal prism; propygator models a rectangular box. Averaging the
two parallel widths gives a rectangle that **preserves the ram (frontal) area
exactly** and under-counts the wetted side area by ~9.5% (→ ~2% of Cd·A, far below
the density confound this run measures). **Do not** length-correct the baseline box:
that swaps a traceable dimension for a fictitious one and buys false precision
against larger dropped effects (the trapezoid's nadir/zenith asymmetry at a few
degrees of angle-of-attack). The +0.33 m length-corrected box is a one-off
sensitivity check only (Verify 5).

Citable dimensions (JPL GRACE-FO Launch Press Kit; cross-checked vs. eoPortal
FLEXBUS/Astrium):

| Quantity | Value | Note |
|---|---|---|
| length L (along-track) | 3.123 m | long axis; rides the wind |
| height h (radial) | 0.780 m | |
| bottom width (nadir) | 1.943 m | |
| top width (zenith) | 0.690 m | |
| **base-averaged width w** | **1.3165 m** | (1.943 + 0.690)/2 |
| **ram area A_ram** | **1.027 m²** | ½(1.943 + 0.690)·0.780 = w·h (exact) |

Box mapping (matches `InPlaneTracking`'s axes — body **+Y on the wind**, +Z
best-effort on the orbit normal): `x_length_m = 0.780` (radial/height),
`y_length_m = 3.123` (along-track/ram, the long axis), `z_length_m = 1.3165`
(cross-track/width). Then the ram + leeward faces are the ±Y faces (area
`x·z = 1.027 m²` = A_ram ✓), nadir/zenith are the ±X faces (4.111 m² each), and the
slant sides are the ±Z faces (2.436 m² each) — total wetted side 13.09 m² (the ~9.5%
under-count of the true 14.47 m²).

**Create / edit** (`experiments/real-world-validation/gracefo/run_gracefo.py`;
ASCII-only prints; `progress=False`):
- Two new **no-fit** runs appended per window, sharing the Run 2/3 force set
  (conservative + NRLMSISE-00) and the same 1-day arc:
  - **Run 4 — sphere table:** `SpacecraftGeometry.sphere(area_m2=1.027,
    drag_coefficient=VariableCd.sphere_default(), reflectivity_coefficient=1.3)`;
    the driver's default attitude (a sphere's Cd is isotropic — attitude-independent).
  - **Run 5 — box table:** `SpacecraftGeometry.box_and_panels(x_length_m=0.780,
    y_length_m=3.123, z_length_m=1.3165, solar_array_area_m2=0.0,
    drag_coefficient=BoxFaceCd.default())` (SRP optics default; negligible at 500 km)
    with attitude `InPlaneTracking(velocity_reference="ecef")`.
- A **Cd-table diagnostic block**: the arc-mean effective Cd on the common `A_ram`
  reference for each table, printed beside the Run 3 fitted Cd and the DSMC band —
  the findings-doc mini-table. For Run 5 assemble `Σ Cd_i·A_i` over the realized
  attitude (the probe's hand-sum). Simplification (noted 2026-07-12): because
  `InPlaneTracking(ecef)` holds body +Y *exactly* on the wind, the face-flow
  angles are constant by construction (ram θ = 0, leeward θ = π, all four sides
  θ = π/2) — the "arc-mean" varies only through the table's (radius, density)
  inputs along the orbit; no per-substep attitude reconstruction is needed.
  > **⚠ ISSUE (flagged 2026-07-12):** Runs 1–3 reference Cd to `A = 1.0 m²`; Runs
  > 4–5 reference to `A_ram = 1.027 m²` (a 2.7% area difference). The Run-3 fitted
  > Cd (2.03 / 3.40, on A = 1.0) and the table Cd (on 1.027) are therefore on
  > *different* references — restate the fitted Cd on the common `A_ram` reference
  > (× 1.0/1.027) in the diagnostic block and findings mini-table so the DSMC
  > comparison is apples-to-apples.
- Two new rows (Run 4, Run 5) in the RIC RMS table + the growth-profile rows, and a
  one-line reading.

**Reuse:** the Run 1–3 machinery in `run_gracefo.py` (parse, config, propagate, RIC,
growth); `VariableCd.sphere_default` / `BoxFaceCd.default` / `InPlaneTracking` (all
shipped); `probes/probe_tables.py` (retained under `gracefo/probes/`) as the diagnostic template
— mechanism only, its geometry is superseded (its docstring says how).

**You provide:** nothing new (both windows' GNV1B already on disk).

**You run:** the extended driver per window; commit.

**Verify:**
1. **Axis-convention live check (load-bearing):** Run 5's arc-mean effective Cd·A ≈
   **6 m² absolute** (≈ 4.3 referenced to A_ram). If it prints ~13 m², a large face
   is accidentally the ram face → the box↔attitude axis mapping is wrong; fix that
   before reading anything else.
   > **⚠ ISSUE (flagged 2026-07-12 — recompute at build time):** these two figures
   > do **not** reconcile against the refined geometry — 6 m² / `A_ram` 1.027 m² =
   > **5.8**, not 4.3. The "4.3" traces to the scratch probe's *superseded*
   > reference area (`A_ram` = 1.9·0.8 = 1.52 → 6/1.52 ≈ 4), and the probe's side
   > areas (16.74 m²) are ~22% larger than the refined 13.09 m², so the ≈6 m² gate
   > itself will shift. Recompute **both** numbers against `A_ram = 1.027` /
   > 13.09 m² when Run 5 runs, and make the diagnostic block state *which* quantity
   > each printed number is (raw `Σ Cd_i·A_i` face-sum vs. along-wind effective
   > Cd·A vs. Cd referenced to `A_ram`) — the parenthetical currently conflates two.
2. Both no-fit residuals exceed Run 3 (fitted); Run 5 (box, larger Cd·A) ≥ Run 4
   (sphere) in the quiet window — the density confound amplified by the
   physically-larger, more-correct box.
3. Common-reference effective Cd (a reading, not a gate): sphere near the DSMC
   band's (2.65–4.5) low edge; the **quiet-window** fitted Cd below the band (the
   density bias) — window-scoped, because the active-window fitted (3.40 → ~3.31
   on `A_ram`) sits *inside* the band, consistent with roughly unbiased solar-max
   density. The box is expected near the band but may land at or above its 4.5
   top once recomputed per Verify 1's ISSUE (a sharp-edged box with full-length
   flat sides plausibly out-drags the real trapezoid's DSMC) — coherent either
   way; record what it prints.
4. *(Optional)* a single scale factor re-fit on the box Cd·A collapses Run 5 to
   ≈ Run 3 — direct proof the box adds no non-absorbable structure for ram-dominated
   GRACE.
5. *(Optional)* the +0.33 m length-corrected box moves the residual by ≪ the density
   confound — geometry-insensitivity, i.e. the residual is density-limited.

---

> ### ✅ Checkpoint B — pinnable bounds + geometry decision (maintainer's call)
> 1. From the measured numbers, set the Chunk 4 pin bounds (generous margins —
>    see Chunk 4's tolerance policy).
> 2. Decide the named deferral with **Runs 4 & 5 as direct evidence**: the
>    sphere-equivalent + scalar fit (Runs 1–3) already drives the residual to
>    single-metre-class; the expectation — to be read off the measured Run 5, not
>    assumed — is that the `box_and_panels` + `InPlaneTracking` upgrade adds only
>    *absorbable* scale for ram-dominated GRACE (its non-absorbable payoff is the
>    edge-on sail regime GRACE doesn't exercise). Default: **defer** — the box
>    validated as physically sound (DSMC-consistent) but not warranted for this
>    bluff body; record either way.
> 3. Optional stretch case noted at the call and **elected 2026-07-13**: a storm
>    window as a density stress test → **Chunk 2c** (does not reopen items 1–2).

---

## Chunk 2c — Gannon-storm window: the density stress case + the box-table sign test - Done

> **Elected 2026-07-13 (maintainer's call), promoting Checkpoint B's item-3
> stretch case to a built chunk.** Checkpoint B's resolved decisions (pin
> bounds, geometry deferral) stand — this chunk adds density-stress evidence to
> the findings doc; it reopens nothing.

**Goal:** the identical Run 1–5 battery over the strongest geomagnetic storm of
the GRACE-FO era, breaking the two-window degeneracy in the Cd-table reading
and exercising the one NRLMSISE-00 input path no committed window touches.

**Physics framing (resolved 2026-07-13 discussion):**
- **What quiet + active cannot separate.** An orbit residual constrains only
  ρ·Cd·A, and the physical Cd is near-constant across windows (the tables
  themselves move only ~8–10% quiet→active) — so the fitted-Cd *swing* across
  windows is a density-bias measurement. The committed windows already flip the
  **sphere** table's sign (1.47× over → 0.80× under the fitted product) but not
  the **box**'s (2.23× → 1.21×, over both times). Two readings stay open:
  **(H1)** the box's residual over-prediction is more density bias — storm
  densities flip its sign too; **(H2)** the box genuinely over-drags this bluff
  body by ~20% (Chunk 2b Verify 3's sharp-edge expectation) — the
  over-prediction persists. The storm discriminates, and **either outcome is a
  recordable finding** (H1 clears the table; H2 is a real characterization of
  `box_face_default` on bluff bodies, worth documenting).
- **Expected sign, not pre-committed:** the storm-time literature has
  NRLMSISE-00 typically *under*-predicting peak storm density and lagging
  recovery, so the expectation is the fitted Cd rising past the box table's
  ~4.1 — but the model can also over-respond in phases; record what prints.
- **Wiring coverage:** both committed windows are geomagnetically dead (daily
  Ap 2 / 4), so NRLMSISE-00's ap-driven storm terms and the
  `CssiSpaceWeatherData` 3-hourly-ap plumbing are *unexercised* — squarely this
  study's risk class. The storm drives 3-hourly ap to 400. **Data verified
  present (2026-07-13):** the local orekit-data CSSI file carries the window
  deep inside its OBSERVED block — 2024-05-10 daily Ap 105 / 2024-05-11 daily
  Ap 271, 3-hourly ap to 400, Kp 9, F10.7 ≈ 227.
- **Truth stays valid in a storm:** GNV1B reduced-dynamic orbits are
  GPS-determined (cm-class through storms) — the storm stresses the model, not
  the truth.
- **The scalar-Cd fit will not collapse the residual** to the quiet/active
  Run-3 class: the density bias varies hour-to-hour inside the arc, so one
  scalar absorbs an arc-mean only. A large Run-3 residual is the expected
  reading — the findings doc's "what a storm does to a scalar-Cd fit" caveat
  (the solar-sail operational takeaway), not a pipeline defect.

**Window (Gannon storm, May 2024):** primary arc **t₀ = 2024-05-11 00:00**, the
full-storm day (uniformly disturbed → the cleanest arc-mean fitted-Cd
interpretation), loaded span 05-11 → 05-13. Optional secondary: the **onset
arc** t₀ = 2024-05-10 (≈17 h pre-storm, main phase from ~17:00 UT — the
model-lag probe) via `--start-date=2024-05-10`.

**Create / edit** (`experiments/real-world-validation/gracefo/`; driver changes
prepared 2026-07-13 alongside this section):
- `run_gracefo.py`:
  - `storm_2024` registered in `WINDOWS` (now a dict carrying an optional
    first-loaded-day filter; the on-disk 05-10 onset day is skipped by default
    so t₀ opens the full-storm arc); `--start-date=YYYY-MM-DD` override.
  - Cd-fit coarse bracket parameterized: storm windows scan to **Cd 8.0** (the
    shipped `_SOFT_CD_LIMIT` = 5 only *warns*, and a storm fitted Cd is a
    density-bias absorber, not a physical Cd); a fit railing at the edge prints
    a NOTE and is recorded as "> 8" — itself a density-bias bound.
  - Storm-aware maneuver-screen note: a real storm onset is itself a slope
    kink, so the deg-5 departure documents the storm signature rather than a
    burn — actual-burn detection falls back to the GRACE-FO SDS monthly
    reports (check May 2024; operators do maneuver around big storms).
  - Space-weather block enriched for all windows: per-loaded-day F10.7/Ap/Kp +
    the max 3-hourly ap over the primary arc — the live proof the storm
    reaches the model.
  - **As-built addition (2026-07-13, onset-arc discussion):** `--fixed-cd=X` —
    one extra no-fit propagation at a Cd calibrated elsewhere, printing RIC RMS
    + a 3-hourly signed along-track profile. Run on the onset arc at the
    active_2023 fitted **3.405** as the **"storm-surprise" case** (how fast a
    pre-storm-calibrated prediction diverges when the storm arrives — the
    operationally realistic scenario, and the solar-sail takeaway). Framing
    rule: the onset arc's *fitted* Cd and s-factors blend ~17 quiet + ~7 storm
    hours and are reported flagged, never as a fourth column in the
    three-window fitted-Cd story.
- Storm results appended to `results.txt`; README storm-window provenance +
  result reading.

**Reuse:** the entire Run 1–5 battery, Cd-table diagnostic block, and s-factor
consistency check, unchanged — the sign test reads directly off the
already-printed s-factors.

**You provide:** four PO.DAAC daily tarballs into `data/gracefo/storm_2024/` —
`gracefo_1B_2024-05-10_RL04.ascii.noLRI.tgz` through `…2024-05-13…` (same
dataset as the committed windows; verify the RL04 path covers May 2024 at
download time per the data-access rule).

**You run:**
`conda run -n propygator python run_gracefo.py storm_2024 >> results.txt`
(the onset arc — elected at run time — appended the same way with
`--start-date=2024-05-10 --fixed-cd=3.405`); commit.

**Verify:**
1. The space-weather block shows the storm reaching the model (2024-05-11 daily
   Ap 271; arc max 3-hourly ap 400) — if not, the CSSI wiring is the finding.
2. Run 1 (drag-off) clears the active window's ~1.06 km/day by a wide margin
   (multi-km/day class at storm densities).
3. **The sign test (the point):** extend the s-factor sequence quiet → active →
   storm — sphere 1.47 → 0.80 → s₄; box 2.23 → 1.21 → s₅. Box s₅ < 1 ⇒ **H1**
   (the over-prediction was density bias; the storm flips it). Box s₅ still > 1
   at daily Ap 271 ⇒ evidence for **H2** (a genuine ~20% geometric over-drag).
   Record either way, beside the fitted Cd on A_ram vs. the DSMC band.
4. The fitted Cd is off the scan rails (or recorded as "> 8"); Run 3's residual
   is expected well above the quiet/active Run-3 numbers — record it as the
   storm caveat number, not a defect.
5. Findings-doc handoff: the Chunk 4 mini-table gains the storm column; the
   pinned tests are **unchanged by default** (if any storm number is pinned,
   only relationships, under the same generous-margin tolerance policy).

> **As-run note (2026-07-13):** all gates passed; both arcs run (peak + onset).
> **Sign test → H1** — box s: 2.23 → 1.21 → **0.97** (fitted Cd on A_ram
> 1.98 → 3.32 → 3.97 vs box table 4.42 → 4.06 → 3.88; the curves cross at the
> storm). Fitted Cd 4.08, off the rails; peak Run 3 residual 119 m (the storm
> scalar-fit caveat). The onset arc exposed an **unplanned finding**: Orekit's
> `NRLMSISE00` at default switches (propygator's construction) is
> **daily-Ap-driven**, smearing the evening storm across May 10's quiet
> morning — the onset fitted Cd 1.78 is that smearing artifact, and the
> storm-surprise run was +614 m *before onset* (+2.24 km/day total). Mechanism
> proven by the committed `probes/probe_ap_driving.py` (1.92× density at constant
> real-time ap = the fitted-Cd ratio). Named follow-on, not built: the
> ap-history mode (`withSwitch(9, -1)`). Evidence: two `results.txt` blocks +
> the README "Storm window" section.

---

## Chunk 3 — TLE fitter vs. reality - Done

**Goal:** the question that motivated this study, answered with one table: *is a
propygator-fitted TLE as good as an operational catalog TLE at predicting a real
orbit?*

**Create / edit** (`experiments/real-world-validation/gracefo/` — same data):
- `run_fit_vs_catalog.py`:
  1. Build a `Trajectory.from_arrays` reference from **one day** of GNV1B truth
     at ~60 s cadence (ITRF in — the §1.2 Trajectory path converts to TEME
     internally), `fit_tle_detailed(..., norad_id=43476, name="GRACE-FO 1")`.
  2. Report the `FitResult` diagnostics (iterations, `rms_m`, residual profile)
     — the post-fit agreement over the fit day.
  3. **Prediction test:** propagate the fitted TLE forward 3 days past the fit
     span (`propagate_tle`), diff against GNV1B truth per day.
  4. **The catalog benchmark:** the maintainer-provided same-epoch Space-Track
     TLE, propagated over the *same* fit-day + 3 forward days, diffed the same
     way. Side-by-side table: fitted vs. catalog, per-day RMS.
  5. Element-level sanity: fitted vs. catalog mean elements close;
     B\* expected to differ (a fit residual, not a physical value — §1.2's
     documented behavior, now shown against reality).
- Results + README as before. Both windows if cheap; the active window is the
  interesting one (drag stresses the B\* fit).

**Reuse:** `fit_tle_detailed` / `FitResult` / `propagate_tle` (all shipped);
`TLE.from_strings` for the catalog lines; Chunk 2's parser + RIC helper.

**You provide:** the two historical catalog TLEs from Space-Track (epoch nearest
the fit-day start), pasted as strings into the experiment folder.

**You run:** the driver; commit.

**Verify:** the fit converges on real (non-propygator-generated) data; post-fit
RMS is sub-km-class; the fitted TLE's forward-prediction growth is the same
order as the catalog TLE's (parity, not victory, is the claim).

> **As-run note (2026-07-14):** both windows run (quiet + active — the locked
> scope; a storm case was offered and declined at election). All three Verify
> gates pass. The fit converged on real GNV1B data in 16–18 iterations at
> ~630 m post-fit RMS (the §1.2 lossiness class, now measured against a real
> orbit); on the fit day the fitted TLE *beat* the catalog in both windows
> (0.83× / 0.79×). Forward prediction exposed a **B\*-regime finding**: with
> B\* fitted, the quiet window ran away (+3 d ratio 17× — over a 1-day
> solar-minimum arc the drag signature (~44 m/day, Chunk 2 Run 1) sits far
> below the ~600 m SGP4 representation noise, so the fitted B\* 2.07e-4 is
> pure fit residual extrapolating quadratically, with the mean motion skewed
> to compensate it in-arc); the elected `--fit-bstar=off` variant collapses it
> to 0.83–2.00× (beating the catalog at +1 d, mean motion restored to within
> 8.3e-7 rev/day of the catalog's) while making the *active* window worse
> (drag signature ~1 km/day → B\* genuinely observable there) — §1.2's own
> `fit_bstar` guidance validated against reality. Parity holds with the
> regime-appropriate setting: +1..+3 d fitted/catalog 3D ratios 0.83–2.00
> (quiet, B\* off) / 1.08–2.10 (active, B\* on). Catalog TLEs: Space-Track
> `gp_history`, nearest-epoch selection (−6.1 h / −4.2 h from fit start; both
> predate the fit day). Evidence: `run_fit_vs_catalog.py` +
> `results_fit_vs_catalog.txt` (four blocks) + the README "Fitter vs. catalog"
> section. Chunk 4 handoff: the fitter-vs-catalog table + the B\* regime rule
> (over a 1-day arc, fit B\* when drag is observable, hold it when quiet).

> **Sweep extension (2026-07-14, maintainer-elected):** does a longer fitting
> span close the forward gap — and should the §1.2 `fitting_span` default move
> 2 d → 3 d? `--sweep`: 1/2/3-day fit arcs **end-anchored** at the day-4
> start, forecast over the common days 4–6 window (density realization held
> fixed across spans), configs B\* fitted and B\* held-at-catalog
> (`initial_guess=catalog` + `fit_bstar=False`), both windows
> (`results_fit_span_sweep.txt`; sweep table + readings in the README).
> Results: a 1-day arc under-conditions B\* in every regime (12–18.5 km at
> +3 d); **2 days is the fitted-B\* sweet spot in both windows** (4.5 /
> 2.1 km); **3 days beats 2 nowhere in the default configuration** (in-arc
> RMS grows with span — SGP4 representation error accumulating — and older
> data imports stale density). **The conditional default change was declined:
> the shipped 2-day default is empirically vindicated.** The regime rule
> sharpened: weak drag → hold a calibrated B\* and fit elements on the
> longest clean arc (quiet 3-d held: 1.41 km, edging the 3.25-d-stale
> catalog's 1.46 km); strong drag → fit B\* on ~2 days (holding a long-arc B\*
> over longer arcs degrades active forecasts 1.9 → 7.0 km — the wrong held
> decay pushes compensation into the fitted mean motion, which extrapolates).
> Plus the operational note: at solar max every well-configured fitted TLE
> beat the 3-day-stale catalog at +3 d by 2–8× — freshness beats catalog
> pedigree in high drag. Chunk 4 handoff: the sweep table + the sharpened
> rule; **Chunk 6** (elected the same day) carries the `FitResult` covariance
> follow-on.

> **State-path extension (2026-07-14, maintainer-elected):** the §1.2 `State`
> reference path — the fitter's own internal `propagate_numerical` reference,
> the path a pre-flight user with no truth trajectory actually exercises —
> measured against reality for the first time (`--state-path`;
> `results_fit_state_path.txt`; README table + readings). Twin design: the
> day-2-start truth state, the shipped 2-day `fitting_span` default, the
> sweep's common days-4–6 forecast, B\* fitted; only the reference source
> differs from the live-recomputed trajectory-path twin. Results: quiet —
> **free** (+4–10% at +3 d; 7–28 m reference drift under ~600 m SGP4 noise);
> active with the uncalibrated Cd 2.3 — **7.4× the twin** (15.3 vs 2.1 km at
> +3 d), far beyond the displacement-sum estimate, because the fit inherits
> the reference's wrong *secular decay* (fitted B\* 1.32e-4 vs the twin's
> 2.05e-4) — a derivative error that compounds through the forecast; active
> with the calibrated Cd 3.405 — parity, here better than the truth fit
> itself (1.15 vs 2.07 km). The composition needed measuring, not arithmetic
> — the study's thesis, again. Findings-doc rule: **the State path is free
> iff the ballistic coefficient is calibrated**, and the fit's own
> diagnostics cannot see an uncalibrated reference (in-arc RMS 635 m against
> its own wrong reference — the self-consistency trap live); Chunk 6's
> covariance does not catch it either (it flags conditioning, not reference
> bias) — the guard is a calibrated Cd or a truth reference.

> **A-priori-table extension (2026-07-15, maintainer-elected):** the
> state-path check's "calibrated Cd" row needs truth to calibrate — circular
> for the no-truth persona — so this extension runs the calibration source
> that persona actually has: the shipped Cd tables (Chunk 2b's Run 4/5
> configs, constructors imported from `run_gracefo.py`), three rows appended
> to the same twin design (`results_fit_state_path.txt` regenerated — the
> original rows recompute deterministically in the same run; README table +
> readings). Design: the sphere table (`VariableCd.sphere_default` on A_ram)
> through the **native State path** *and* the **external
> propagate-then-fit-Trajectory route** — the pair's delta measures the
> construction-time "identical result" equivalence on real data — then the
> box table (`BoxFaceCd.default`, `InPlaneTracking(ecef)`) via the external
> route only, because **§1.2's State path cannot express attitude** (no
> parameter; internal reference pinned to default `LofAligned`) — a shipped
> limitation this extension surfaced, material for the sail regime, whose
> documented remedy is now validated: equivalence deltas ≤ 1.9 m / ≤ 0.5 m
> (quiet/active) across every column, B\* to 2e-8, against a ~600 m SGP4
> floor. Results: active — sphere/box 9,484 / 9,284 m at +3 d, ~4.5× the
> twin, between calibrated (1,147) and nominal (15,285) exactly as their
> ±20% product errors predict; the box row is the first *over*-decay point
> and proves the compounding is sign-symmetric (fitted B\* 2.34e-4 above vs
> sphere 1.57e-4 below the twin's 2.05e-4). Quiet — +25% / +60% over the
> twin, second-order under the quiet fitted-B\* runaway. The transfer is
> ~linear: ~0.4–0.5 km per % of ρ·Cd·A error at +3 d (active), ~20–25 m/%
> (quiet). Findings-doc rule sharpened: **"calibrated" means a
> single-digit-% ballistic coefficient — the a-priori tables' density
> confound (±20% at solar max, ×1.5–2.2 in deep minimum) structurally cannot
> meet it**; the tables buy physical plausibility, not State-path
> calibration. Attitude-dependent spacecraft take the external route, at
> zero cost.

---

## Chunk 4 — Wrap-up: pinned tests, findings doc, README - Done

**Goal:** persist what the study proved — regression tests that would catch a
future wiring regression, the findings doc, the README claim.

**Create / edit:**
- **Pinned tests** (the Skyfield-table precedent; `orekit` fixture; fixtures as
  in-file literals, tens of KB total):
  - `tests/propagation/test_real_world_lageos.py` — initial PV + sparse truth
    samples over the **shortest arc that still proves the point** (target: one
    day or less; total test runtime budget ≲ 60 s — measured, not guessed);
    asserts RMS below the Checkpoint-A number × a generous margin.
  - `tests/propagation/test_real_world_gracefo.py` — the drag-off signal present
    within a wide band + drag-on materially better (ratio bound, not absolute
    meters), from the Checkpoint-B numbers. **Optional (strong, cheap) wiring
    pin:** the Run-5 box `Σ Cd_i·A_i` at the `InPlaneTracking` ram orientation —
    a pure table × face-sum × attitude-mapping quantity that guards the axis
    convention (Chunk 2b Verify 1) independently of the density pipeline the
    ratio bound covers. Evaluate the table at **fixed** `(radius, density, θ)`
    inputs (as the scratch probe does at ρ = 1e-12), not "arc-mean over real
    conditions", so the pin stays independent of orekit-data CSSI refreshes.
  - `tests/tle/test_fitter_real_world.py` — the fit converges on the pinned real
    subsample; post-fit RMS bounded.
  - **Tolerance policy (binding):** every threshold = measured × margin
    generous enough to absorb orekit-data refreshes (EOP/CSSI updates for
    2019–2024 are final-history and stable, but the margin costs nothing).
    Thresholds prove "the wiring didn't regress", not "the number is exact".
- **`docs/real-world-validation-findings.md`** — methodology, provenance
  (products, spans, parameter citations), the residual tables, the ablation
  matrix, the fitted-Cd story (all three windows — quiet / active / the Chunk 2c
  storm — the density-bias lever, plus the storm-window scalar-Cd caveat), the
  **a-priori-Cd-table mini-table** (Runs 4 & 5:
  the sphere/box effective Cd on the common `A_ram` reference vs. the DSMC
  2.65–4.5 band vs. the Run-3 fitted Cd — the direct Checkpoint-B geometry
  evidence), the fitter-vs-catalog table, and the honest caveats (density
  10–30%; Cr sensitivity; sphere-equivalent geometry; the box is DSMC-consistent
  but adds only *absorbable* scale for ram-dominated GRACE; **the
  error-cancellation caveat on the Runs 4/5 ranking** — the sphere's smaller
  no-fit residual is the NRLMSISE density bias partially cancelling its too-low
  Cd, not higher fidelity, so Run 4 < Run 5 must not be read as a table ranking
  (2026-07-12 discussion); the `box_face_default` negative-leeward grid noise →
  Chunk 5; the parked `earth_radiation` toggle as the named next step for the
  LAGEOS floor).
  Non-binding findings doc, `prospective-forces-…` style; archived to
  `docs/history/` when superseded.
- **`README.md`** — a short "Validation" note: SGP4 (Vallado), passes (Skyfield),
  numerical propagator (ILRS/LAGEOS-2), drag (GRACE-FO GNV1B), TLE fitter
  (fit-vs-catalog parity), each with its headline number.
- **CLAUDE.md** "Project state" — the study recorded (delegated to Claude).
- **You** update `CHANGELOG.md` (tests/docs entry) and decide the `v0.7.2` tag.
- Full local CI parity: `conda run -n propygator pytest` and
  `conda run -n propygator pre-commit run --all-files` green.

**Reuse:** the experiment drivers are the fixture generators (a `--emit-fixture`
flag printing the literal arrays beats hand-copying).

**You provide:** CHANGELOG; the tag decision; the merge.

**You run:** the release steps if tagging (per `docs/release-process.md`).

**Verify:** full suite green including the three new test files; the README
numbers match `results.txt`; `import propygator` still JVM-free; this plan
retires to `docs/history/`.

---

## Chunk 5 — `box_face_default` negative-leeward grid fix (order-independent maintenance) - Done

> **Normal-fix-path item, folded in as its own chunk (maintainer's 2026-07-12
> request) so it can be addressed in isolation.** It touches `scripts/` +
> `data/` + `src/` + `tests/` (plus, per the 2026-07-16 amendments, cosmetic
> `experiments/` + `docs/` touch-ups) on its **own branch off `main`** (not the
> study branch), at any time — no study chunk depends on it, and it needs
> nothing from the study's data. Discovered by Chunk 2b's Verify-4 probe.

> **Amended 2026-07-16 (pre-build blast-radius analysis, on branch
> `fix/box-face-cd-leeward-floor`):** the Create/edit, Scope-decisions, and
> Verify items below fold in that analysis — the floor-placement constraint,
> the npz metadata handling, the old-vs-new grid diff (the venv-drift guard),
> the committed-evidence decision (frozen — maintainer chose option (b)), and
> the `run_gracefo.py::_scaled_box_cd` cleanup. Evidence figures re-verified
> against the shipped npz the same day.

**Evidence (measured 2026-07-12; recorded so no session re-derives it):** the
shipped `data/box_face_cd_default.npz` grid (shape 26 × 25 × 65) carries
noise-level **negative** entries over the leeward half — 11,325 of 42,250 values
(27%) are < 0, most-negative −5.77e-4, and the entire θ = π slice is ≤ 0 (max
−3.4e-11). Physically Cd_leeward → 0⁺; the negatives are numerical noise
(hypothesis to confirm at chunk time: erfc/exp cancellation in the generator's
leeward Sentman closed form, committed with no physical floor).
**Re-verified 2026-07-16 with three additions:** the negatives are confined to
incidence nodes 46–64 (θ ≥ 129.4°); the npz `metadata_json.cd_range` min is
**−0.00175** — the pre-regrid *cloud* range, more negative than the grid min,
so flooring only the grid leaves a stale negative range claim in the metadata;
the sphere table's grid min is 2.106 (zero negatives), so its half of the fix
is validation-only, no regeneration.
**Hypothesis resolved at fix time (2026-07-17), with a mechanism refinement:**
the negatives are the closed form's *analytic* residue, not floating-point
noise — a cancellation-free `erfc(−a)` re-evaluation of the same formula
reproduces them to ~1e-17. The erfc/exp terms nearly cancel *analytically*,
and for low speed-ratio (light, hot) species the DRIA re-emission recoil
projected on the drag axis exceeds the tiny incident drag: H reaches −1.6e-3
near θ ≈ 150–180°, He −3.2e-11 at θ = π (the measured slice value), and the
grid argmin sits at 1350 km / lowest densities / θ = 143.4° — the
He/H-dominated corner. Still physically spurious (the model has no
self-shadowing; a convex body's leeward faces are shielded, Cd_leeward → 0⁺),
so the floor stands unchanged; the mechanism is recorded in the generator's
module docstring ("Leeward floor").

**Symptom that bit:** table lookups tolerate the negatives (no per-lookup
validation on the `from_table` path), but `BoxFaceCd.from_callable` **rejects**
any returned Cd < 0 — so wrapping the shipped table in a callable (e.g. scaling
it, as Chunk 2b's Verify 4 does) raises `ValueError` **mid-propagation**. The
experiment clamps at zero (`run_gracefo.py::_scaled_box_cd`). Orbit-level impact
of the noise itself: ≤ ~1e-3 m² of Cd·A (≤ 0.01% of the GRACE face-sum) —
cosmetic in effect, but a real factory asymmetry: `from_table` accepts a grid
that `from_callable` would refuse to serve.

**Create / edit:**
- `scripts/generate_box_face_cd_table.py` — floor the assembled grid at 0.0 (the
  physical bound) before writing; document the floor in the script docstring.
  **Floor placement is constrained (2026-07-16):** it goes in `generate()` at
  grid assembly — after the nearest-neighbour edge fill, *before* the anchor
  prints so the logged θ=180 anchor reflects shipped values — and **never**
  inside `_face_cd_species` / `_face_cd_total`: the cross-validator drives
  those closed forms against the *unfloored* experiment kernel
  (`cd_box.cd_panel_species`) and asserts machine-precision agreement (1e-9
  gate), which an in-form floor breaks at ~5.8e-4. Corollary: **the experiment
  kernel needs no matching floor** — the experiment side is untouched by
  design.
- Same script, metadata: rescope `cd_range` (post-floor grid range, or keep the
  cloud range under a cloud-named key — its current min −0.00175 is the
  *cloud*, not the grid) and add explicit floor provenance (e.g.
  `leeward_floor: {applied, n_floored, min_before_floor}`).
- Regenerate `data/box_face_cd_default.npz` and rerun the generator's
  cross-validation gate (the change is ≤ 5.8e-4 absolute — far inside the Tier B
  "≪ 1% on CdA" acceptance). Because the floor never touches the closed form,
  `CROSS_VALIDATION_MAX_REL_PCT` (0.1193) is **expected to reproduce
  unchanged** — the rerun is confirmation, not refresh; update the constant
  (and the results file) only if the print actually moves.
- **Old-vs-new npz array diff (new verify artifact, 2026-07-16):** assert only
  previously-negative grid entries changed (all to exactly 0.0) and every
  other entry + all three axes are bit-identical. This doubles as the
  venv-drift guard: if *non-leeward* entries moved, the throwaway venv's
  pymsis/scipy have drifted since the 2026-06 snapshot and the whole grid
  silently shifted — **stop and decide** (re-pin the venv per
  `docs/experiments_venv.md` vs. accept a full regeneration); never ship the
  diff blind.
- `src/propygator/propagation/spacecraft.py` — validate grid ≥ 0 in
  `BoxFaceCd.from_table` (and `VariableCd.from_table`, same rule, cheap) so the
  asymmetry closes at construction; leave `from_callable`'s strict runtime check
  as is. (This tightens a previously-accepted input beyond the archived
  general-upgrades-1.md Tier B validation table — the archived doc stays
  untouched; the factory docstrings carry the new rule and this plan is the
  sanctioned instruction.)
- Tests (`tests/propagation/test_spacecraft.py`, pure-Python, no JVM): the
  shipped grid min ≥ 0 (both tables — the sphere's is trivially true, its Cd
  never approaches 0); `from_table` rejects a grid containing a negative entry;
  an identity `from_callable` wrap of the default table returns ≥ 0 at θ = π.
  While there, extend `test_box_face_default_loads_committed_asset` with a
  leeward-≥-0 assert.
- `experiments/real-world-validation/gracefo/run_gracefo.py` (2026-07-16) —
  remove the now-dead `_scaled_box_cd` `max(0.0, …)` clamp and replace its
  bug-explanation comment with a one-line breadcrumb ("grid floored at
  generation since v0.7.3"). Clamping non-negative values is an identity, so
  the committed evidence stays reproducible — **no re-run**.
- Docs (2026-07-16): `docs/real-world-validation-findings.md` §7 caveat + §8
  follow-on gain a "shipped in v0.7.3" pointer; `data/README.md`'s box-table
  entry gains a one-line floor note; `experiments/real-world-validation/README.md`
  gains the evidence-freeze note (see Scope decisions).

**Scope decisions (resolved 2026-07-16, maintainer's; do not relitigate):**
- **Committed study evidence stays frozen at its v0.7.2 numbers** (option (b)
  of the blast-radius analysis). `gracefo/results.txt` prints
  `leeward -0.000` in 4 places (the sign of −3.4e-11); after regeneration a
  `run_all.py --verify` diffs on exactly those strings — the numeric effect on
  Run 5 is ~1e-11 m² of Cd·A, below printed precision. Do **not** regenerate
  the `drag` / `state-path` groups; instead the study README notes that a
  post-Chunk-5 `--verify` differs by exactly `leeward -0.000` → `0.000` and
  why that is expected (the evidence is the historical record of what was
  measured against the table that shipped then).
- **No other experiment re-runs.** Surveyed 2026-07-16: the Tier B benefit
  studies (`cd_box_benefit_study*.py`), `experiments/ecef-attitude-benefit/`
  (its committed results print no leeward Cd values), and
  `gracefo/probes/probe_tables.py` (superseded probe, outside `run_all`) are
  archived evidence with the effect below printed precision; notebook 02 has
  no leeward narrative and strips outputs. Note-only, no action.

**Reuse:** the existing generator + its cross-validation harness. The committed
default-table tests assert *ranges*, not exact values (verified 2026-07-12), and
run metadata is name-based (`Cd=table:box_face_default`), not content-based — so
nothing pinned moves.

**You provide / run:** the branch (`fix/box-face-cd-leeward-floor`, created
2026-07-16); the generator + cross-validator reruns (throwaway venv, not
conda); CHANGELOG + the patch release per `docs/release-process.md` — the
release is **`v0.7.3`** (the study's optional `v0.7.2` tag was taken).

**Verify:** regenerated npz min ≥ 0 **and** the old-vs-new array diff is
leeward-only (the venv-drift gate above); the cross-validation rerun
reproduces `CROSS_VALIDATION_MAX_REL_PCT` (or constant + npz metadata are
refreshed together); full suite + pre-commit green. Interaction with Chunk 4's
face-sum pin (landed *before* this fix): its generous-margin band already
absorbs the shift (~1e-7 m² on the 4.18 m² face-sum; its docstring says so) —
nothing pinned moves.

---

## Chunk 6 — `FitResult` covariance exposure (order-independent feature work)

> **Elected 2026-07-14 (maintainer's request), from Chunk 3's B\* finding.**
> Like Chunk 5 this is not study work — but where Chunk 5 is a fix, this adds
> **public surface**, so it runs on its **own branch off `main`** on the
> normal feature path: a `features.md` §1.2 amendment drafted at chunk time
> (this plan never silently amends contracts), a **minor** version bump (the
> exact number depends on what has shipped by then), CHANGELOG + release the
> maintainer's. No study chunk depends on it, and it needs nothing from the
> study's data beyond the Chunk 4 fixtures.

**Motivation (the Chunk 3 evidence):** the quiet-window 1-day fits converged
at in-band RMS while their fitted B\* (1.8–2.1e-4 vs the catalog's 0.99e-5)
was pure fit residual that ruined forward prediction 17× — and nothing on
`FitResult` could show the user that B\* was unconstrained. The estimator
computes the parameter covariance anyway (the same "diagnostics are free from
the estimator" argument that pulled `FitResult` in-contract at the 1.2
Checkpoint A); a formal sigma(B\*) ≫ the estimate reads "hold B\*" directly —
the clean primitive a "weak-drag warning" heuristic would only approximate.

**Create / edit:**
- `src/propygator/tle/fitter.py` — capture the physical covariance from the
  `BatchLSEstimator` at convergence (exact Orekit 13.1.x accessor probed at
  chunk time, the Chunk-0 rhythm — reflection first, then the real call path)
  and carry it on `FitResult`: the covariance matrix plus named per-parameter
  sigmas in a documented parameter order (the 6 mean elements + B\* iff
  `fit_bstar`), following the `residuals_m` array-backed value-type invariants
  (defensive copy, read-only contents, value-based `__eq__`/`__hash__`,
  validating `__post_init__`, constructible pre-JVM). Alongside it, capture
  the **a-posteriori variance factor** σ₀² = cost² / (m − n) — the weighted
  residual sum of squares over the degrees of freedom, available from the
  observer's `ls_evaluation` (`getCost()`; exact accessor confirmed by the
  same chunk-time probe) — and carry σ₀ as a scalar `FitResult` field: the
  covariance and sigmas ship **raw**, and σ₀ is the documented bridge to
  residual-scaled sigmas (× σ₀), applied by the user knowingly, never
  silently. The **correlation matrix** (elected 2026-07-17) is exposed as a
  **derived, JVM-free property** computed on demand from the stored
  covariance — not a second stored array (no redundant state; equality/hash
  stay covariance-based, and it works unchanged for any parameter set, 6 or
  7 with B\*) — in the same documented parameter order; the docstring names
  corr(B\*, n) → ±1 as the direct collinearity read behind the Chunk-3
  pathology.
- `docs/features.md` §1.2 — the amendment (additive fields only; document the
  interpretation caveat: under the fixed 1 m / 1 mm/s measurement sigmas
  against a *systematic* SGP4 representation error, formal sigmas are
  **conditioning indicators** — relative, not absolute, uncertainty; the σ₀
  field documents the standard rescaling, with the honest second caveat that
  even scaled sigmas understate uncertainty here — the residuals are a
  smooth, autocorrelated once-per-rev signal, so the effective
  independent-measurement count sits far below N).
- Tests (`tests/tle/test_fitter.py` + `tests/tle/test_fitter_real_world.py`;
  `orekit` fixture): shape / parameter order / read-only pins; sigma(B\*)
  **dominant** on a short weak-drag fit vs small on a drag-observable fit,
  and |corr(B\*, n)| **higher** on the weak-drag fit (relationships, not
  absolutes — the study's tolerance policy); σ₀ relationship pins — O(1) on
  the SGP4 self-fit (residuals at the assumed sigma) vs ≫ 1 on the real-data
  fixture (~630 m residuals under a 1 m sigma); the `fit_bstar=False` path
  (no B\* row) — exercised via the held-catalog-B\* carrier configuration on
  the real-data fixture, doubling as a carrier-route pin; equality/hash with
  the new fields.
- `notebooks/07_tle_fitting.ipynb` — a covariance + correlation read added
  to the walkthrough, flagging the Chunk-3-style unconstrained B\*.
- **Resolved at election (the Chunk 3 sweep):** the conditional
  `fitting_span` default change (2 d → 3 d) is **declined** — the sweep showed
  2 days is the fitted-B\* sweet spot in both windows and 3 days beats it
  nowhere in the default configuration; the shipped default stands, and the
  sweep table goes to the findings doc instead.
- **Also resolved at election (2026-07-14):** a `bstar=` convenience kwarg on
  `fit_tle` (direct pre-computed-B\* input) was considered and **declined** —
  the contract-sanctioned carrier route
  (`initial_guess=TLE.from_state_unfitted(..., bstar=...)` +
  `fit_bstar=False`) works and is not burdensome; the §1.2 signatures stay
  frozen.

**Reuse:** the `FitResult` validation idioms; the Chunk-0 probe rhythm for the
covariance accessor; the Chunk 3/4 pinned GNV1B subsamples as the
weak-drag / strong-drag test pair.

**You provide / run:** the branch (suggest `feature/fitresult-covariance`);
CHANGELOG; the version bump + release per `docs/release-process.md`.

**Verify:** full suite + pre-commit green; `import propygator` stays JVM-free
(`FitResult` remains constructible + validating pre-init); the fitter's public
signatures unchanged (additive fields only); sigma(B\*) on the quiet
short-arc real-data fixture reads unconstrained while a drag-observable fit
reads constrained.

---

## Chunk 7 — `FitResult` residual diagnostics (order-independent feature work)

> **Elected 2026-07-17 (maintainer's request), from the Chunk 6 scoping
> discussion.** Like Chunk 6 this adds **public surface**: its own branch off
> `main` on the normal feature path, a `features.md` §1.2 amendment drafted at
> chunk time (additive fields only), a minor version bump, CHANGELOG + release
> the maintainer's. Order-independent of Chunk 6 — but it amends the same
> §1.2 surface and the same `FitResult`, so running both chunks on one branch
> with a single combined amendment and one release is the economical
> packaging (maintainer's call).

**Motivation:** `residuals_m` keeps only norms, which destroys the most
diagnostic information in the residual set — *structure*. A once-per-rev
sinusoid reads "SGP4 short-period representation error, irreducible"; a
secular along-track ramp reads "drag/B\* mismatch" — exactly the analysis
the study's Leg 3 did by hand. The signed position **and** velocity
components are already computed and discarded in the observer loop
(`_build_fit_observer`), and the observed PV provides the radial /
along-track / cross-track axes: the data is free, only the carrying surface
is new.

**Create / edit:**
- `src/propygator/tle/fitter.py` — the observer captures the signed residual
  components at the accepted final evaluation; `FitResult` gains velocity
  residual norms (`(N,)`) and signed position residuals decomposed
  radial / along-track / cross-track (`(N, 3)`, axes built from the observed
  PV; exact field names — and whether raw TEME components also ship — settled
  at chunk time, the lean being RIC-only), following the `residuals_m`
  array-backed value-type invariants (defensive copy, read-only contents,
  value-based `__eq__`/`__hash__`, validating `__post_init__`, constructible
  pre-JVM).
- `docs/features.md` §1.2 — the amendment (additive fields only; document the
  axis convention and the read: periodic structure = representation error,
  secular structure = dynamics mismatch).
- Tests (`tests/tle/test_fitter.py` + `tests/tle/test_fitter_real_world.py`):
  shape / alignment with `measurement_epochs` / read-only / equality-hash
  pins; a structure pin on the pinned measured day (along-track dominates the
  decomposition — relationships, not absolutes); `import propygator` stays
  JVM-free.
- `notebooks/07_tle_fitting.ipynb` — a residual-structure read (the RIC
  components over the arc; flag secular vs periodic by eye).

**Reuse:** the `FitResult` validation idioms; the existing observer loop; the
Chunk 3/4 pinned GNV1B subsamples.

**You provide / run:** the branch (suggest
`feature/fitresult-residual-diagnostics`, or fold onto Chunk 6's branch);
CHANGELOG; the version bump + release per `docs/release-process.md`.

**Verify:** full suite + pre-commit green; the fitter's public signatures
unchanged (additive fields only); the along-track-dominant structure pin
holds on the real-world fixture; `FitResult` remains constructible +
validating pre-init.

---

## End-state verification

1. **Evidence committed:** LAGEOS 7-day diff + ablation matrix, GRACE-FO
   two-window drag trio, fitter-vs-catalog table — scripts, READMEs,
   `results.txt` all in `experiments/real-world-validation/`; no raw truth files
   in git.
2. **Checkpoints resolved and recorded:** A (GO or the investigation trail),
   B (pin bounds + geometry decision).
3. **The wiring is proven externally:** t₀ conversion ~0; conservative forces at
   the meters-to-tens-of-meters/day level vs. ILRS; every toggle's ablation
   signature correct; drag signal resolved and materially reduced by the model;
   the fitter converges on non-synthetic data at catalog-TLE parity.
4. **Regressions guarded:** three pinned test files green under the tolerance
   policy.
5. **Docs:** findings doc in `docs/`; README Validation note; CLAUDE.md updated;
   CHANGELOG (maintainer); plan retired to `docs/history/`; optional `v0.7.2`.

## Notes / deferred (not this plan)

- **GNSS/IGS SP3 leg** — cm-level drag-free truth; deferred (LAGEOS covers the
  conservative diagnostic; a GNSS bus needs box-wing SRP to be interesting).
- **ISS OEM leg** — NASA publishes ephemerides *with* ballistic inputs; a nice
  third drag case, deferred.
- **GRACE-FO `box_and_panels` geometry** (fitted box run) — the Checkpoint B
  named deferral. Chunk 2b probes the geometry no-fit with `InPlaneTracking`
  (drag-equivalent to the faithful `NadirPointing` for this ram-dominated body);
  the deferred step is the *fitted* box, taken only if the sphere-equivalent
  leaves residuals a constant cross-section can't explain.
- **Storm-window density stress case** — noted at Checkpoint B, **elected
  2026-07-13 → Chunk 2c** (no longer deferred).
- **`earth_radiation`** — upstream-blocked (the Knocke horizon bug); when the
  fixed Orekit wrapper lands, the LAGEOS arc from this study is the ready-made
  acceptance test (ties into `experiments/earth-radiation/`'s resume kit).
  **Recipe:** one new ablation row — the same committed arc with
  `earth_radiation=True` vs. the committed baseline `results.txt`. Expected
  signature: the residual *tightens* by the ERP order (~1.5e-10 m/s² on LAGEOS
  ≈ meters over a day, tens of meters over the week — the Checkpoint-A floor);
  it does not vanish (thermal thrust stays unmodeled). Since the unblock rides
  an Orekit version bump (fresh conda env per CLAUDE.md), the re-run doubles as
  the whole-stack regression check on the upgraded env. Optionally tighten the
  Chunk 4 LAGEOS pin afterward.
- **Watching a predicted ISS pass** — the zero-code end-to-end check; no chunk
  needed, just a clear evening.
