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
  `box_and_panels` + `NadirPointing` fidelity upgrade is a **named deferral**,
  taken only if Checkpoint B shows residuals that a constant cross-section can't
  explain.
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
  time.
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

- **5 chunks (0–4)**, each sized for one Claude Code session:
  - **Chunk 0 is the diagnostic gate** (LAGEOS end-to-end → Checkpoint A).
  - **Chunks 1–3 are the evidence body**; **Chunk 4 is wrap-up** (the only chunk
    that touches `src/`-adjacent surfaces: `tests/`, docs, README).
- Each chunk lists **Goal / Create-Edit / Reuse / You provide / You run / Verify**.
- **Checkpoint A (after Chunk 0) is GO / INVESTIGATE** — never a silent shrug: a
  bad diff reroutes the plan into localized bug-hunting (the t₀ diff, then the
  ablations, are the localization tools) and any confirmed defect exits to the
  normal fix path before the study resumes.
- **Checkpoint B (after Chunk 2)** decides what is pinnable and whether the
  GRACE-FO geometry upgrade is warranted.
- **Commits, CHANGELOG entries, chunk-header "done" marks, downloads, and any
  release are the maintainer's.** Claude writes scripts/tests/docs and runs
  read-only/test commands.
- **Mergeable chunks:** 2 + 3 share the GNV1B data and can run in one session.

---

## Git (read once)

The maintainer creates **`study/real-world-validation`** off `main`. Per-chunk
rhythm: maintainer commits + pushes after each verified chunk (committed evidence
= scripts + README + `results.txt`; never raw truth files — extend
`.gitignore` for `experiments/real-world-validation/data/` in Chunk 0). At
wrap-up: squash-merge; the optional `v0.7.2` tag follows
`docs/release-process.md` if taken.

---

## Chunk 0 — LAGEOS-2: truth data, SP3 parser, the first 7-day diff → Checkpoint A

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

> ### ⛔ Checkpoint A — GO / INVESTIGATE (maintainer's call)
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

## Chunk 1 — LAGEOS-2 ablation matrix: the per-toggle wiring proof

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

## Chunk 2 — GRACE-FO GNV1B: the drag stack, quiet + active

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

> ### ✅ Checkpoint B — pinnable bounds + geometry decision (maintainer's call)
> 1. From the measured numbers, set the Chunk 4 pin bounds (generous margins —
>    see Chunk 4's tolerance policy).
> 2. Decide the named deferral: does the sphere-equivalent explain the residuals,
>    or is the `box_and_panels` + `NadirPointing` upgrade warranted? (Default:
>    defer — record the evidence either way.)
> 3. Optional stretch case noted, not built: a storm window as a density stress
>    test.

---

## Chunk 3 — TLE fitter vs. reality

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

---

## Chunk 4 — Wrap-up: pinned tests, findings doc, README

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
    meters), from the Checkpoint-B numbers.
  - `tests/tle/test_fitter_real_world.py` — the fit converges on the pinned real
    subsample; post-fit RMS bounded.
  - **Tolerance policy (binding):** every threshold = measured × margin
    generous enough to absorb orekit-data refreshes (EOP/CSSI updates for
    2019–2024 are final-history and stable, but the margin costs nothing).
    Thresholds prove "the wiring didn't regress", not "the number is exact".
- **`docs/real-world-validation-findings.md`** — methodology, provenance
  (products, spans, parameter citations), the residual tables, the ablation
  matrix, the fitted-Cd story, the fitter-vs-catalog table, and the honest
  caveats (density 10–30%; Cr sensitivity; sphere-equivalent geometry; the
  parked `earth_radiation` toggle as the named next step for the LAGEOS floor).
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
- **GRACE-FO `box_and_panels` + `NadirPointing` geometry** — the Checkpoint B
  named deferral.
- **Storm-window density stress case** — noted at Checkpoint B, not built.
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
