# Build plan: Extended Validation — the GRACE lineage, the density-bias lever, and the fitting playbook under transfer

> **Status: BUILD PLAN (started).** Derived from the binding contract
> `docs/extended-validation.md` — **the contract wins on every conflict**; this is a working
> blueprint, not a contract. It is a **validation study, not a feature**: nothing here
> touches `src/`, and the binding outputs are evidence (committed results, a findings doc, a
> revised playbook, pinned tests). Status headers are the maintainer's — trust the git log
> for true status.
>
> **Supersedes the Swarm-based build plan of 2026-08-03**, retired 2026-08-08 with its
> contract.

## Context

Every external claim propygator makes rests on **one satellite**. The v0.7.2 study measured
GRACE-FO 1 (~490 km, ram-dominated conventional bus); the v0.8.0 fit-strategy experiment
fitted TLEs to the same truth. The r/s gate thresholds, the regime arms, the fitted-Cd
density lever, and the Checkpoint-B "the box adds only absorbable scale" deferral are all
**bets on transfer**, taken with wide margins and never tested off their own data
(`docs/tle-fit-strategy-findings.md` §1 says so).

This study takes those bets across the **GRACE lineage** — GRACE-FO 2 (a formation twin
already inside the tarballs on disk) and original GRACE A/B (the same bus lineage,
2002–2017, spanning a full solar cycle and a wider drag-level range).

**The methodological correction, and the reason this plan differs from its predecessor:** an
orbit residual constrains only ρ·Cd·A, so writing `T = Cd_table/Cd_fitted = E(s)/D(w)`, the
*level* of E is unidentifiable — scale every E *and* every D by the same *c* and every
observable is unchanged. **No second satellite fixes that**, which is why the old plan's
headline B2 (`T(SwarmB)/T(GRACE-FO)`) could never have yielded the "X % table error" claim
it was written to license, and why Swarm — whose own geometry and mass bookkeeping error
swamped the quantity in question — was retired. What replaces it is four measurements the
GRACE lineage can actually deliver: a **noise floor** from the twin, a **density-bias curve
reported beside the tables' own modelled response with the attribution declined**, a **shape
anchor** at the 2008–09 minimum, and an honest **geometry limit** (contract §2.3, §2.5).
Leg B claims a measurement and a bounded structural limit, not a decomposition — the
identifiability argument bites on the variance exactly as it bites on the level.

> **Note the 2026-08-08 correction inside that replacement claim (contract §2.5).** The
> structural finding is **the measured size of the tables' dimensional collapse**
> (`metadata_json`: **0.490 % RMS overall, 0.672 % storm**), not an absence of composition
> response. The generator samples 80 conditions explicitly varying local solar time, latitude,
> F10.7 and Ap into a 4480-point cloud before regridding, and it recorded what the regrid
> costs. **Do not write "the tables have no composition axis and cannot represent an LST-driven
> response at all"** — the shipped asset contradicts it. The residual bounds
> table-vs-its-own-generator-physics; table-vs-truth stays out of reach.

**End state:** propygator can claim validation against precise orbits from two independent
missions and four spacecraft across 2002–2024; the fitted-Cd method has a measured error bar
for the first time; the playbook's thresholds are transfer-tested under freeze across a wide
drag-level range; the s-gate has a stated domain of validity; and the fading-memory question
is closed against its pre-registered bar.

**Risk profile: front-loaded, and cheaper than the predecessor's.** Chunk 0 costs zero
downloads and resolves Checkpoint A against a *known* answer. Chunk 1 carries the study's
one real technical unknown (the GRACE record format), gated with both branches costed and a
declared fallback.

### Source-of-truth docs (do not silently diverge)

- **`docs/extended-validation.md`** — the binding contract. Every §-reference below is to it
  unless stated otherwise.
- `docs/architecture.md` §4 / §10 / §11 — boundary + frame/time invariants; the
  pinned-reference-data precedent the new tests extend.
- `docs/features.md` §1.1 / §1.2 — the shipped contracts **under test**. This plan reads
  them; it never edits them.
- `docs/tle-fitting-playbook.md` — the recipe under transfer test. Its thresholds are
  **frozen inputs** here (contract §6), revised only at wrap-up.
- `docs/real-world-validation-findings.md`, `experiments/real-world-validation/README.md` —
  the baseline evidence and the **frozen-evidence rule**.
- `docs/experiments_venv.md` — hygiene rules, with the study's locked departure: this runs in
  the **conda env** (propygator is the system under test), **with no carve-out** — the
  table-range figure is a `.npz` lookup, so nothing here needs the `pymsis`/`scipy`
  generation venv.
- `CLAUDE.md` "Java↔Python boundary notes" + the ASCII-stdout experiments rule.

### Decisions already locked (do not relitigate)

**The contract's §12 decisions log is the authority and is not restated here.** Read it once
before Chunk 0. Duplicating its reasoning into this plan is how the two documents drift apart
— the plan carries *what to do*, the contract carries *why*. The index below is pointers only;
where a chunk needs the reasoning, it cites the §.

| Decision | Contract § |
|---|---|
| Body set = GRACE-FO 1 + 2, GRACE A + B; Swarm retired | §12, §2.1 |
| "X % table error" withdrawn as unearnable; T is a normalization convention bracketed over **A/m** | §2.1, §2.2 |
| DSMC retracted in full; the study has no external level anchor | §2.3 M4 |
| Leg B downscoped from decomposition to reporting; B2/B5 reported, A4 a diagnostic | §2.5 |
| The table-range figure is a `.npz` lookup, not a generator run — **computed in Chunk 2** | §2.5 |
| The collapse finding is its **measured 0.490 % RMS**, never an absence claim | §2.5 |
| Two error floors routed by cancellation structure (twin / sub-arc); curvature is **not** a third | §5 |
| Checkpoint A is the twin test, not a ballistic-coefficient prediction | §4 |
| GRACE lands as a new module in the new tree | §9 |
| `D(w)` sweep runs Run 3 only — **scientific reason, not compute** | §9 |
| LST curve windows run **GRACE-FO 1 only**; both twins at inherited windows and in Leg C | §9, §3 |
| **Leg C draws only on the four 10-day window classes** — not the 3-day curve/GRACE anchors | §3, §6 |
| Windows stratified on LST as well as activity, from a fixed recorded list | §3 |
| r/s thresholds frozen; C1 stated behaviorally | §6 |
| Matched-staleness rule (latest epoch ≤ T) | §3 |
| Storm anchors pre-onset / mid / post; ≥ 1 moderate event; capped search | §7 |
| GRACE-FO 2 does not satisfy E1; E1 resolved in quiet + active only | §8 |
| Fading memory: verbatim bar, default DEFER, promotion exits to its own branch | §8 |
| No `src/` change on this branch, with the symmetric re-run rule | §9 |
| Env frozen at the installed `orekit_jpype` 13.1.4.0 for the study's duration | §3 |

### Data access (read once)

- **GRACE-FO GNV1B:** PO.DAAC daily tarballs, Earthdata login. **The quiet, active and
  Gannon windows are already on disk** (`experiments/real-world-validation/data/gracefo/`:
  10 / 10 / 4 days), and each tarball already contains the `_D_` product — verified
  2026-08-08 that `gracefo_1B_2019-11-14_RL04.ascii.noLRI.tgz` carries
  `GNV1B_2019-11-14_D_04.txt`. Chunk 0 needs **zero downloads**.
- **Volume is the binding constraint — but size it per leg, not per download convention.**
  A daily tarball is **148 MB**, and it carries *both* C and D. The "10-day window" is an
  inherited download habit, not a driver requirement: `run_gracefo.py:127` sets
  `LOAD_DAYS = 3` and `run_fit_vs_catalog.py:98,102` set 4 and 6, so **no driver has ever
  consumed more than 6 days**. Days needed per window: **3** for the `D(w)` curve (Chunk 2,
  Run 3 only — the largest window *count*) and for the GRACE drag anchors (Chunk 3); **10**
  only for the anchor and storm legs (Chunks 5, 6, 8). Ten LST curve windows is therefore
  **~4.4 GB**, not 10–15.
  > **The two columns are not independent, and Leg C is scoped accordingly** (contract §3,
  > §6). A 3-day window cannot host even one 3 d arc + 3 d forecast anchor, so **Chunks 5/6/7
  > never draw on the curve or GRACE-anchor windows** — their sources are the four window
  > classes already provisioned at 10 days (inherited quiet/active, the E1 drag-timescale
  > window, the storm library), at **zero additional download**. That set spans the drag-level
  > range C1 requires; the LST windows hold F10.7 fixed by construction and would add
  > near-duplicate anchors for ~10 GB.

  **Chunk 0 resolves whether PO.DAAC serves `GNV1B` standalone**; the
  GNV1B member is ~23 MB/day/satellite uncompressed inside the tarball, so standalone service
  removes the constraint entirely. If it does not, the cap is recorded — and given the per-leg
  counts above it is likely non-binding for the curve leg.
- **GRACE GNV1B:** PO.DAAC. **Record format resolved by inspection before any GRACE code is
  written** — first from the file listing (GRACE-FO products carry an explicit `.ascii.`
  token, so the listing may answer it with no download), then from one delivered file.
  **The GRACE-era daily volume is a separate unknown** — the 148 MB figure is a GRACE-FO
  tarball whose bulk is modern high-rate instrument data. Chunk 1 measures and records the
  GRACE per-day cost from the first delivered day; the storm library is not sized until then.
- **Catalog TLEs:** per-anchor Space-Track `gp_history` pulls (maintainer's credentials,
  `.env` convention). Not fetchable via `fetch_tle` (CelesTrak-only, current epoch).
  Close-formation pairs are a cross-tagging hazard — check object identity on every pull.
- **orekit-data coverage — verified on disk 2026-08-08:** EOP `finals2000A.all` 1973-01-02 →
  2027-07-04 (final through the span); CSSI `BEGIN OBSERVED` 1957-10-01 → 2026-05-09; leap
  seconds through 2017-01-01; DE-440 `lnxp1990.440`; `eigen-6s.gfc` at max_degree 240. Note
  `itrf-versions.conf` switches `finals2000A.` from ITRF-2005 to ITRF-2008 at 2011-02-01 and
  to ITRF-2014 at 2017-03-01 — Orekit handles it automatically; record the realization
  beside every window.
- **The env is frozen for the study's duration** (contract §3). Installed `orekit_jpype` is
  **13.1.4.0**; conda-forge offers 13.1.7.0 under the same `13.1.*` pin, so a recreation
  silently changes the Orekit build under the evidence. Do not recreate or update mid-study,
  and **print both the resolved `orekit_jpype` version and the propygator version into every
  results header**.
- **Raw truth files are never committed** (`data/` gitignored). Committed evidence is the
  README + results files per leg, plus small extracted fixtures as in-file test literals.

### Architecture invariants to honor

Experiment scripts: **ASCII-only stdout** (captured under cp1252), progress to stderr,
`pathlib.Path`, cwd-independent, lazy `org.orekit.*` imports, reference-only (outside
`testpaths`, excluded from CI/lint via the `pyproject.toml` ruff `extend-exclude` — already
`["experiments"]`, so the new tree is covered with no config change).
**Bit-determinism is a requirement** (contract §9): no RNG anywhere — Leg E's
log-spaced-toward-recency subsampling is a closed-form index rule, and the window list is
fixed and recorded, not drawn — no `Epoch.now()`, no wall-clock-dependent anchor placement.
Chunk 10's shipped tests only: JVM via the **`orekit` fixture** (so the collection-ordering
hook schedules them after the pure-Python guards); no new public exports; `import propygator`
stays JVM-free; fixtures small enough to live as in-file literals.

---

## How to use this plan

- **11 chunks (0–10)**, each sized for roughly one Claude Code session.
  - **Chunk 0 is the diagnostic gate** (GRACE-FO 2 stand-up → Checkpoint A). Zero downloads.
  - **Chunk 1 is the study's one technical unknown**, gated with a declared fallback.
  - **Chunks 2–9 are the evidence body**; **Chunk 10 is wrap-up** (the only chunk touching
    `tests/`, docs, README, notebooks).
- Each chunk lists **Goal / Create-Edit / Reuse / You provide / You run / Verify**.
- **Checkpoints:** A after Chunk 0 (GO / INVESTIGATE) and D after Chunk 9 (DEFER / PROMOTE)
  — the study's only two decision gates.
- **The orchestrator is built incrementally, from Chunk 0.** The last study added
  `run_all.py` late and paid for it in a reorganization; here every chunk registers its group
  as it lands.
- **Every chunk that produces a number resolves its pre-registered predictions explicitly as
  hit or miss** (contract §4–§8). "Interesting" is not a verdict. A **withheld** claim is
  also written down as withheld.
- **Commits, CHANGELOG entries, chunk-header "done" marks, downloads, Space-Track pulls, and
  any release are the maintainer's.** Claude writes scripts/tests/docs and runs read-only and
  test commands.
- **Mergeable chunks:** 2+3 share the drag-run harness; 5+6 share the anchor harness.
- **Real dependencies (not all of 7/8/9 are independent):** 6 → 5 (`probes/anchors.py`);
  7 → 5 **and** 7 → 2 (`MEASURED_ANCHORS` supplies the calibrated-Cd reference class);
  8 → 5 and 8 → 1; **9 → 8** (Leg E's storm regime is a storm-library window) and 9 → 5.
  Only **7 and 8 are independent of each other**; 9 is not independent of 8.
  **Also: 4 → 2** — Chunk 2 computes the `.npz` `range_table` lookup and the collapse
  residual, and Chunk 4 consumes them (the lookup moved into Chunk 2 so **B2 resolves in one
  chunk** rather than straddling two). And **5 → 3, 5 → 8 for its non-GRACE-FO rows**: Leg C's
  GRACE and storm anchors live in windows those chunks provision, so Chunk 5 lands its
  GRACE-FO rows first and appends the rest on a re-run.
- **Droppable under budget pressure, in this order — with what each drop costs beyond its own
  chunk, because none of these are self-contained:**
  1. **Chunk 3's 2002–03 solar-max window.** B3 degrades from a two-point shape test to a
     one-point comparison against GRACE-FO — *and* it removes GRACE's high-activity point,
     which is one side of **A3**'s quiet→active→storm direction test, one side of **A4**'s
     activity match, and a candidate for **Leg E's E1** active-regime GRACE row. Do not drop
     it without checking whether a storm-library window or the E1 mid-cycle window can stand
     in as GRACE's high-activity point.
  2. **Storm-library events beyond the third.** Cheap to drop *except* for the event Leg E
     consumes as its storm regime — that one is load-bearing for Chunk 9 and is dropped last.
  3. **LST windows beyond the third.** Weakens B5's LST term and widens M2's bound.

---

## Chunk 0 — GRACE-FO 2, the noise floor, and Checkpoint A - Done

**Goal.** Activate the formation twin on truth already on disk, measure the noise floor the
study has never had, and resolve **Checkpoint A**. Zero downloads.

**Create / edit.**

- `experiments/extended-validation/` skeleton: `README.md` (study index), `run_all.py`
  (orchestrator skeleton, one group registered), `data/` (gitignored), `gracefo/`, `grace/`,
  `probes/`. **The `.gitignore` entry is already in place**
  (`experiments/extended-validation/data/`) — verify with `git status` after the first
  download, before the first commit.
- `gracefo/gracefo_ext_common.py` — the leg config: NORAD IDs (43476 C, 43477 D), the
  inherited geometry constants **imported or transcribed with provenance** from
  `gracefo_common.py` (never redefined silently), the per-window mass band with its citation,
  `sphere_spacecraft()` / `box_spacecraft()` / `force_config(drag)` factories on the v0.7.2
  conservative baseline, and a `MEASURED_ANCHORS` block later chunks consume (empty at
  first).
- `gracefo/run_twin_checkout.py` — the Chunk 0 driver, over the three inherited windows for
  **both** C and D: parse report with per-satellite `qualflg` drop rates, t₀
  ITRF→EME2000→ITRF round-trip and first-sample diff, a drag-off / drag-on pair, and the
  **Run-3 scalar-Cd fit per satellite** so `T(C,w)/T(D,w)` can be formed. Prints the
  Checkpoint A criterion and the realized value side by side. Results →
  `gracefo/results_twin.txt`.

**A `--data-root` argument is a Chunk 0 deliverable, not a later convenience.** It defaults
to the new tree's `data/` and can point at `experiments/real-world-validation/data/gracefo/`.
`find_window_files` and `parse_gnv1b` both take arbitrary `Path`s, so this is a **read** of
the frozen tree, never an edit (contract §9).

**Reuse.** `real-world-validation/gracefo/gnv1b.py` (`parse_gnv1b`, `find_window_files`,
`Gnv1bEphemeris`) and `real-world-validation/common.py` (`ric_components`, `rms`) —
**imported, never edited**.

**You provide.** The **Checkpoint A** call. The **PO.DAAC standalone-`GNV1B` answer** (a
browser check; it sets every later chunk's download budget). Confirmation of the GRACE-FO 1/2
relative-yaw attitude convention, or a note that it is still open.

**You run.** `conda run -n propygator python gracefo/run_twin_checkout.py <window>`.

**Verify.**

- D parses cleanly from every tarball already on disk; the `_D_` member is found by the
  existing filter; **D's `qualflg` drop rate is comparable to C's** (the parser already
  returns `n_dropped_qc` — a one-line read, and a large asymmetry is a finding).
- Epoch round-trips bit-clean; header epoch count matches parsed length; subsampling to the
  60 s grid exact.
- **t₀ diff at float-noise level** (the v0.7.2 study measured ≤ 5e-9 m for GRACE-FO).
- **Checkpoint A — GO / INVESTIGATE.** GO requires D's parse clean, t₀ clean, drag-on
  materially below drag-off, and **`T(C,w)/T(D,w)` within 10 % of 1 in every inherited
  window**. Generous on purpose: this gate hunts wiring bugs, and **the measured deviation
  itself is the deliverable**.
- **A1 recorded** — the deviation and its window-to-window spread, carrying the **mandatory
  three-term label**: *"noise floor + fore/aft asymmetry + any true A/m difference between the
  twins"* (contract §2.3 M1). Not "noise floor", and **not the two-term form** — the third term
  is a systematic that reproduces identically on every re-run, so folding it into "noise"
  inflates the band every cross-body claim is later judged against.
- A bad number reroutes into bug-hunting; a confirmed defect exits to the normal fix path,
  and contract §9's symmetric rule then applies before the study resumes.

---

## Chunk 1 — GRACE stand-up: format resolution and the reader

**Goal.** Original GRACE truth on disk, parsed, screened, and sanity-checked, with the
reader landed as a new module. This chunk carries the study's one real technical unknown.

**Step 1 — resolve the format before writing code.** Check the PO.DAAC listing for a format
token in the filenames (GRACE-FO carries `.ascii.`). If that is inconclusive, one delivered
day settles it. **Record what was found**, whichever branch it takes.

**Create / edit.** `grace/grace_l1b.py` — the reader, in the **new tree**, in one of two
shapes:

- **ASCII branch** (~1 hour): the GRACE-FO column layout with its own `_SAT_NAMES` for
  `"A"`/`"B"`, its own member filter, and delegation to the shared parsing shape. The GPS
  epoch route is identical (GPS + 19 s = TAI, `gnv1b.py:46`) and carries across.
- **Binary branch** (~half a session): a `struct`-based reader against the documented L1B
  record layout, with the ASCII header parsed for provenance. Not difficult — the risk is
  silent field misalignment, which the self-checks below catch.

Plus `grace/grace_common.py` — the leg config mirroring Chunk 0's: NORAD IDs (27391 A,
27392 B), the equivalent-box geometry with citation and the documented difference from
GRACE-FO (height ~0.72 m vs 0.780 m at `gracefo_common.py:59`; launch mass ~487 vs ~600 kg),
the per-window mass band, and the spacecraft/force factories.

And `grace/run_grace_checkout.py` — parse report, maneuver screen, late-mission-degradation
screen, t₀ round-trip, and a drag-off / drag-on pair.

**Neither branch edits frozen code.** The ASCII branch is the one that *tempts* an additive
change to `gnv1b.py`'s `_SAT_NAMES` (`:49`, validated `:208`) — do not take it; a new module
keeps the frozen tree untouched by construction (contract §9).

**Reuse.** `common.py`; `gnv1b.py` read as a structural reference, not imported, if the
binary branch applies.

**You provide.** GRACE downloads for the Chunk 2/3 window candidates; the format-branch
confirmation.

**You run.** `conda run -n propygator python grace/run_grace_checkout.py <window>`.

**Verify.**

- **The A–B separation self-check** — GRACE A and B fly in trailing formation on the same
  ground track. Recovering that separation, alongside |r| ≈ 6870 km and |v| ≈ 7.6 km/s, is the
  decisive proof that field offsets are right. This is the binary branch's safety net and it
  runs on the ASCII branch too. **Assert the separation as a band (roughly 150–300 km), never
  a point value** — the gap is actively maintained and drifts (GRACE A/B ranged ~170–270 km
  across the mission, and the GRACE-FO pair measures **181.0 km** in `quiet_2019`, not the
  ~220 km nominal). A field misalignment throws the separation by orders of magnitude, not
  percent, so the band catches it; |r| and |v| carry the sharp part of the check
  (contract §3).
- Epoch round-trips bit-clean; grid uniform; decimation to the 60 s grid exact; inter-file
  continuity verified at the seams.
- Maneuver screen **CLEAN** by a **named, automatable test** — "an unexplained along-track
  step" is circular in a drag study, since drag produces along-track drift too. Use the
  v0.7.2 GRACE-FO screen as the template (`gracefo/results.txt`: *"along-track signal
  (max |.|): 186.6 m; departure from a smooth deg-5 fit: 6.7 m → CLEAN"*), i.e. **residual
  departure from a smooth low-order fit**, threshold stated up front, cross-checked against
  the mission's published maneuver record. GRACE maneuvered far more than GRACE-FO — expect
  casualties and retire those windows.
- **Late-mission degradation screen** — battery limits, attitude-mode changes and reduced
  operation on GRACE B make the lowest-altitude years unsuitable. Record the altitude and
  attitude-mode status per window; **the study does not chase the ~300 km end**. **Screen on
  the two things that actually break a window, not on mission health generally:** `GNV1B` is
  a **GPS-derived orbit product**, so the instrument and power failures that ended GRACE's
  *science* return do not by themselves disqualify it — an **attitude-mode change** (breaks
  the box run's assumed convention) or a **data gap / degraded tracking** (breaks the parse
  and the fit) do. The mid-cycle E1 window (~2014–2015) is expected to pass; screen it rather
  than assuming either way.
- **t₀ diff at float-noise level**, and the ITRF realization for the window recorded
  (`itrf-versions.conf` puts pre-2011 windows on ITRF-2005).
- **The GRACE-era per-day download volume measured and recorded** from the first delivered
  day — it is independent of GRACE-FO's 148 MB and it is what sizes Chunk 8's storm library.
- **Fallback if both branches fail, in order:** (a) the **GFZ ISDC** archive as a second
  source for the same L1B product — check it before rewriting anything, since a second
  distribution of the product costs a reader nothing; then (b) GRACE reduced-dynamic orbits in
  **SP3**, which `lageos/sp3.py` already parses. Record the decision either way (contract §3).

---

## Chunk 2 — Leg B: the density-bias curve, GRACE-FO era

**Goal.** The `D(w)` curve across an LST-stratified window set on **GRACE-FO 1**. This is the
study's largest compute block (~2.5 h) — larger than Leg E.

**Create / edit.** `gracefo/run_density_curve.py` → `gracefo/results_density_curve.txt`.
**Run 3 only** — the scalar-Cd golden-section fit — per window. Register the `curve` group in
`run_all.py`. Record each window's fitted Cd into `MEASURED_ANCHORS` with provenance,
alongside the window's F10.7, Ap, both node local times and mean altitude.

**Run 3 only is a *scientific* scope decision, not a compute one** (contract §9). Runs 1/2/4/5
exist to put the tables under test, and the tables are not under test at a curve window — they
would produce rows no prediction consumes. **Do not repeat the old compute justification:**
measured from v0.7.2's evidence a whole Run 1–5 window is **≈ 390 s** (run 4 at 12 s, run 5 at
23 s, verify-4 at 21 s) while the **fit alone is 210–239 s**, so dropping the other runs saves
~10 %, and with the sub-arc floor a Run-3-only window costs *more* than a full one.

**GRACE-FO 1 only at the curve windows** (contract §9, §3). The twin floor governs
**cross-body** claims; this leg makes only **cross-window** claims (B2, B5), judged against
the sub-arc floor. M1 is already measured in full in Chunk 0. Running D here would double the
study's largest block for extra M1 samples no prediction consumes. Both twins still run at the
inherited windows (Chunk 0) and throughout Leg C (Chunk 5), where they are two genuine catalog
objects.

**The window list is fixed and recorded, never drawn.** At ≈ 1.12 °/day of LST drift
(i = 89°, ~490 km, non-sun-synchronous by mission design), windows ~80 days apart differ by
~6 h of node local time and ~90 days apart by ~100°. **The full diurnal axis is covered in
~160 days of calendar span, not ~320** — a near-polar orbit samples its ascending and
descending nodes ~12 h apart in local time simultaneously, so each window contributes two LST
points (contract §2.4). Size the leg around ~160 days and **record both node local times per
window**, not a single mean LST. The 2019–2020 deep minimum holds F10.7 nearly constant
across that span, which is what makes the axis usable — the inherited 2019-11 quiet window is
the first point. **Each curve window is 3 days** (contract §3's per-leg day counts), not 10.
Screen each candidate for maneuvers and data availability before committing the list.

**σ(T) is computed here, not deferred — and the sub-arc floor is a Chunk 2 deliverable.**
**Two** sources, not three: Chunk 0's twin floor, which governs **cross-body** claims; and a
**within-window sub-arc floor** for **cross-window** claims (B2, B5). Measure the latter by
**fitting each of the 3 loaded days separately** and taking the spread of the three `Cd` —
zero new downloads, **~2 extra fits per window at ~210–240 s each** (day 1's separate fit *is*
the main fit). **Do not use A1's twin floor for cross-window claims:** at fixed window
`T(C,w)/T(D,w) = κ_D/κ_C` cancels `D(w)`, the truth product, the index error and the fit's
conditioning — precisely the terms that vary *between* windows — so A1 is anti-conservative
there and would let measurement scatter read as `D`. The sub-arc spread contains real
day-to-day density variation, so it **over**-estimates the floor, the same conservative
direction M1 already argues for itself. Every T cell also carries its **A/m bracket**
(contract §2.2).

**The golden-section minimum's curvature is a fit-quality diagnostic, not a σ source**
(contract §5). Print the bracket if it is useful — a flat minimum is a weak-drag warning worth
seeing — but it never enters an error bar: the Cd fit is a deterministic optimization against a
residual dominated by unmodelled systematics, so its minimum's width measures optimizer
resolution, not uncertainty in T, and quoting it would publish a σ an order of magnitude
tighter than the honest one.

**The `.npz` table lookup lands here, not in Chunk 4 — so B2 resolves in the chunk that
produces its other two numbers.** `range_table` is an evaluation of the committed
`data/sphere_cd_default.npz` and `data/box_face_cd_default.npz` at each window's mean
(radius, density), reachable through the public **JVM-free** `VariableCd.__call__(radius_m,
density_kgm3)` and `BoxFaceCd.__call__(radius_m, density_kgm3, theta_rad)`
(`propagation/spacecraft.py:378`, `:675`). It needs no truth data and no propagation — ~10
lines against values this driver already computes for its fits — so leaving it in Chunk 4
would strand B2 across two chunks for nothing. **Chunk 4 consumes these values; it does not
recompute them.**

**Read `metadata_json` while the `.npz` is open, and record the collapse residual.** Both
assets carry `metadata_json.confidence` with the generator's measured regrid cost —
**"overall 0.490 %, storm 0.672 %"** — plus `condition_coverage` (80 conditions; F10.7
65–320; Ap 2–400) and `n_samples` (4480). That number is the study's dimensional-collapse
finding (contract §2.5) and it is **read, not asserted**. Print it into the results file
beside `spread_T`.

**This group is checkpointed per window and resumable** (contract §9). It is one of the study's
two multi-hour groups; write each window's row as it completes and skip completed windows on a
re-run.

**Reuse.** Chunk 0's config and `--data-root`; the v0.7.2 `run_gracefo.py` as the structural
template (read, not imported — it is a chunk driver, and the frozen rule forbids editing it).

**You provide.** GRACE-FO downloads for the LST-stratified windows (3 days each; budget set by
Chunk 0's standalone-`GNV1B` answer); the committed window list after screening. **The
GRACE-FO-1-only decision changes compute, not downloads** — each tarball carries both C and D
regardless, so the storage figure (~4.4 GB for ten windows) is unchanged and D remains
available on disk if a later chunk wants it.

**You run.** `run_all.py --only curve`.

**Verify.**

- **B2 — reported, not predicted, and it resolves *here*.** Print three numbers, all as
  **ratios of extremes**: `spread_T = max_w T/min_w T − 1`, the **sub-arc** window-to-window
  floor, and `range_table = max_w Cd_table/min_w Cd_table − 1` (the `.npz` lookup, computed in
  this chunk). **No 3×/2× pass criterion** — it sat on quantities whose own floors are
  estimated, and the inference it licensed is the one contract §2.3 M2 withdraws. Ratios,
  never absolute differences: §2.2 defines T only up to the assumed A/m, so a claim on T must
  be invariant under `T → cT`.
- **The dimensional-collapse residual recorded from `metadata_json`** — 0.490 % overall /
  0.672 % storm — printed beside `spread_T`, with its scope on the same line:
  **table-vs-its-own-generator-physics, not table-vs-truth.**
- **B5 — reported, not predicted.** Measure and plot the LST dependence of T at fixed
  activity **against the 0.49 % collapse band**. The like-for-like comparison *is* available:
  the tables' LST response is mediated entirely through (radius, density), and the collapse
  residual is exactly how much LST-driven composition response that mediation discards. **Do
  not state it as a prediction** — §2.4 concedes the two terms are not separately identified
  without assuming the density bias is smooth and low-order in LST. **And do not write that
  the tables have no composition response at all** (contract §2.5): the generator sampled LST
  explicitly and measured what the regrid costs. What stays unresolved is the **true** Cd's
  LST response, which no orbit-only design reaches.
- Every T cell carries its A/m bracket and its σ; every absolute Cd carries its mass
  assumption; every claim names which floor it was judged against.

---

## Chunk 3 — Leg B: the GRACE-era anchors and the shape test

**Goal.** The 2008–09 deep-minimum known-answer test and a 2002–03 solar-max point on GRACE.
Resolve **B3** and **A3/A4**.

**Create / edit.** `grace/run_grace_drag.py` → `grace/results_drag.txt`. The **full Run 1–5
structure** here (this is where the tables are under test), plus Run 3 at any additional
GRACE windows feeding the curve. Register the `grace-drag` group.

**Like-for-like arc starts are load-bearing** — the cross-mission ratios divide GRACE's
fitted Cd into GRACE-FO's, so a mismatched arc silently corrupts the comparison. Print the
arc start beside every fitted Cd so the pairing is auditable from the results file alone.

**Reuse.** Chunk 1's reader and config; Chunk 2's fit harness; `gracefo/results.txt` from the
v0.7.2 study, **transcribed read-only with a provenance line** for the GRACE-FO 1 column
(2.23 / 1.21 / 0.97 box T on `A_ram = 1.027`; fitted Cd 1.98 / 3.32 / 3.97) — never
recomputed.

**You provide.** The GRACE window downloads — the 2008–09 and 2002–03 anchors (3 days each,
contract §3's per-leg day counts) **and the 10-day E1 drag-timescale window** (~2014–2015,
~420–440 km, F10.7 matched to `active_2023`, after the attitude-mode and data-gap screen).
The E1 window is provisioned here because it is a GRACE drag row, but **Chunks 5 and 9 both
consume it** — Chunk 9 cannot satisfy E1 without it, since both GRACE anchor windows sit
inside GRACE-FO's own altitude envelope and so supply no timescale contrast. Also the
published 2008–09 anomaly magnitude with citations (papers in hand, not recalled).

**You run.** `run_all.py --only grace-drag`.

**Verify.**

- **B3 — the shape anchor.** GRACE's 2008–09 fitted Cd sits low *relative to that same
  body's own high-activity window*, in the same direction and rough proportion as GRACE-FO
  1's 1.98 → 3.32. **Never stated as an absolute comparison** — the 1.98 carries
  `GRACEFO_MASS_KG = 600.0`, a round launch mass (`:38`), so an absolute reading re-imports
  the level problem the contract withdraws (contract §2.3 M3) — **and with DSMC retracted
  there is no band left to state one against anyway.**
- **The circularity is stated in the results file**, not just the findings doc: the published
  anomaly was itself established from orbital-drag-derived densities under assumed Cd models,
  so this is a cross-check between two drag-based paths, not a comparison against ground
  truth.
- **A3** — fitted Cd rises quiet → active → storm on GRACE as on GRACE-FO 1: a direction and
  rough-magnitude test, not a level test.
- **A4 — reported, not predicted.** Print `T(GRACE,w₁)/T(GRACE-FO,w₂)` with its confounds
  enumerated on the row: the documented dimension and mass differences, and — dominant — the
  unmatched density bias `D(w₂)/D(w₁)`. **There is no "≈ 1" pass criterion.** The ratio is
  `[E_G/E_F]·[D(w₂)/D(w₁)]`, and Chunk 2 measures the D-swing at O(2) across the driver range
  against an A1 floor of a few percent, so an "≈ 1" test would fire on the confound and be
  misread as a reader bug. **Pipeline validation across the 17-year gap is Chunk 1's job** —
  the A–B separation self-check, |r|, |v|, the t₀ round-trip and seam continuity are direct
  and unconfounded, and do it better.
- **A2** — the scalar-Cd fit collapses the residual to the v0.7.2 class at the new epochs.

---

## Chunk 4 — Leg B: the table analysis and its limits

**Goal.** Everything the tables can honestly be put through, and an explicit written record
of what they cannot. Resolve **B1** and **B4**.

**Create / edit.** `gracefo/run_tables.py` → `results_tables.txt`:

1. **The T matrix** for both tables, all four bodies, all windows — each cell a **bracket
   over the assumed A/m** with its σ. GRACE-FO 1's column transcribed with provenance.
2. **The tables' modelled response — consumed from Chunk 2, not recomputed.** Chunk 2 already
   evaluates the committed `.npz` grids at each window's mean (radius, density) and records
   `range_table` (contract §2.5). Import those values and report as a ratio of extremes. **No
   generator run, no `pymsis`/`scipy`, no second environment, no α sweep** — the earlier plan
   to re-derive this through `scripts/generate_*_cd_table.py` is withdrawn as unnecessary.
   Extend the lookup only to the GRACE and box-table cells Chunk 2 did not cover.

   **And carry the dimensional-collapse finding with its measured size.** Verified on disk
   2026-08-08: the shipped grids reduce to **(radius, density)** — sphere `grid (26, 25)` over
   `radius_axis` / `density_axis`, box `grid (26, 25, 65)` adding `incidence_axis`. **The
   finding is what that reduction costs, and the generator already measured it:**
   `metadata_json.confidence` reports **0.490 % RMS overall / 0.672 % storm** against a
   4480-point cloud sampled over 80 conditions with local solar time, latitude, F10.7 and Ap
   all varied (`scripts/generate_sphere_cd_table.py`, `lon` uniform 0–360 commented *"varies
   local solar time"*). Quote that beside the measured T spread.

   > **Do not write "the tables cannot represent an LST-driven composition response at all."**
   > An earlier draft of the contract did; the shipped `metadata_json` contradicts it, and this
   > chunk is opening that file anyway. **What the residual bounds is
   > table-vs-its-own-generator-physics, not table-vs-truth** — whether the *true* free-molecular
   > Cd's LST response exceeds the Sentman/DRIA model's is §2.1's identifiability problem on the
   > composition axis and stays unmeasured. State both halves or neither.
3. **The absorbable-scale retest** — scale the box table's Cd·A onto the fitted product and
   check whether the box run collapses onto the fitted run, as it did for GRACE-FO 1
   (1.85 vs 1.86 m; 6.45 vs 6.36 m; 118.6 vs 119.0 m).
4. **Attitude sensitivity** — the box run under `InPlaneTracking` ecef vs inertial vs default
   `LofAligned`, bounding how much of the box answer is attitude convention.
5. **Regime-guard exercise** at GRACE's lower-altitude windows — the two-tier drag-regime
   warn-once (Kn floor + table edges) behaves as documented and does not fire spuriously.

> **Items 4 and 5 are capped, deliberately.** Neither resolves a pre-registered prediction and
> neither has a gate; both are cheap (a box run is ~20 s wall, per `results.txt`) and both are
> worth having, but they are the two places this chunk can sprawl. Item 4 runs **three
> attitudes at two windows** (one quiet, one active) — not the full window set; v0.7.2 already
> bounds the mapping through its axis check and the s = 2.23 predicted-vs-realized agreement,
> so this is a confirmation, not a survey. Item 5 is a **smoke test**: it asserts the warn-once
> fires where documented and stays silent elsewhere, and records the outcome in one line. If
> either wants to grow, it becomes a follow-on instead.

**No DSMC desk comparison — the leg is retracted** (contract §2.3 M4). Quote no band, run no
comparison, recall no DSMC value. The results file states plainly that the study has **no
external level anchor**.

**This chunk has no decision gate.** Its output changes which claims §10 licenses; it does
not branch the plan.

**Reuse.** Chunks 2 and 3's results; the v0.7.2 `probes/probe_tables.py` as a pattern
reference.

**You provide.** Nothing new.

**You run.** `run_all.py --only tables`.

**Verify.**

- **B1** — the box table's T crosses ~1 at storm peak on the new bodies as it did on
  GRACE-FO 1 (the sign test that resolved H1: over-prediction is density bias, not geometric
  over-drag).
- **B4** — the absorbable-scale result holds, leaving the Checkpoint-B `box_and_panels`
  deferral intact. A miss **elects a follow-on**; it does not authorize the geometry upgrade
  inside this study.
- **The withheld claims are written into the results file, not only the findings doc**: no
  "X % table error" (unearnable — contract §2.1); no *"at least X % of the variation is
  density bias"* (the variance decomposition needs an unmeasurable assumption about the true
  Cd's response — contract §2.3 M2); no geometry claim from flight data (§2.3 M4b —
  convex-box and high-A/m are anti-correlated by construction); **no absolute Cd level**,
  since the DSMC retraction leaves no external anchor; and **no claim about the *true* Cd's
  LST response** — the 0.490 % collapse residual bounds the table against its own generating
  model and says nothing about that model's fidelity to truth (contract §2.5).

---

## Chunk 5 — Leg C: playbook transfer and the r/s gate under freeze

**Goal.** Replicate the playbook decision rule across the achieved anchor set on all four
bodies with thresholds frozen. Resolve **C1–C3**.

**Create / edit.**

- **`probes/anchors.py` — created here, not later.** The shared anchor/forecast harness
  (anchor placement, the staging-fit pair, the arm runners, the ITRF-on-truth-grid diff).
  Chunks 6, 7, 8 **and** 9 all consume it, so it is a Chunk 5 deliverable rather than a later
  extraction; writing it as a module from the start costs nothing and avoids a mid-study
  refactor of four callers.
- `probes/probe_playbook_transfer.py` → `probes/results_playbook_transfer.txt`. Per anchor:
  the 2 d free staging fit (→ r), the 3 d fit (→ s), then the gate's chosen arm and its
  rivals (fitted-2d, selfcal 2d→1d, held-cat 1d, held-zero 1d) on a common 3-day forecast
  window, diffed in ITRF on the truth grid. **≥ 4 anchors per window per satellite.**

**Define the gate's behavior on a singular covariance — before the run, not after.**
`FitResult.sigmas` returns `None` whenever `covariance` is `None` (a converged fit whose
`(JᵀJ)⁻¹` extraction was singular, per §1.2), and the v0.8.0 template computes
`f2.sigma0 * f2.sigmas[i]` with no guard — never reached on GRACE-FO 1, but this chunk runs a
much larger anchor set on three new bodies and two new decades. **A singular covariance means
r is not computable, which is "does not certify", not a crash and not a pass.** Print it as
an explicit `r = n/a -> no certification` row and count it in C1's tally.

**Freeze discipline (binding).** `RATIO_THRESHOLD = 0.05` and `S_THRESHOLD = 0.1` are module
constants carried verbatim from the playbook with a comment saying so. **Re-fitting them to
this data and then reporting that they classify is circular and forbidden.** Any
recalibration is a separate, clearly labelled post-hoc section.

**Reuse.** `tle-fit-strategy/probe3_rule_replication.py` as the structural template (read,
not imported); Chunks 0–1's readers; `common.rms`; public `fit_tle_detailed` /
`propagate_tle` only — no fitter internals in this chunk.

**This group is checkpointed per window and resumable** (contract §9) — it is the study's
second multi-hour group. Write each window's anchor rows as they complete; skip completed
windows on a re-run.

**Window sources are enumerated, and this chunk needs no new downloads** (contract §3, §6).
Leg C's 3 d arc + 3 d forecast geometry needs a 10-day window, so it draws **only** on the
window classes already provisioned at that length:

| Window | Bodies | Drag level | Provisioned in |
|---|---|---|---|
| `quiet_2019` (10 d, on disk) | GRACE-FO 1 **and 2** | weakest — ~495 km, deep minimum | already there |
| `active_2023` (10 d, on disk) | GRACE-FO 1 **and 2** | ~495 km, solar max | already there |
| **E1 drag-timescale** (10 d) | GRACE A (B if clean) | ~430 km, F10.7 matched — **~2.5–3× denser** | Chunk 3 |
| Storm library (10 d each) | GRACE A/B, GRACE-FO | storm peaks | Chunk 8 |

**The 3-day curve windows (Chunk 2) and GRACE 2008–09 / 2002–03 anchors (Chunk 3) are not Leg
C sources** — they cannot host even one anchor. That is a scoping decision, not a gap: C1's
requirement is **drag-level range**, and the four classes above run from solar-minimum
GRACE-FO to ~430 km GRACE at solar max to storm peaks — wider than the LST windows could add,
since those hold F10.7 fixed by construction. Re-provisioning them at 10 days would cost
~10 GB for near-duplicate anchors.

**Ordering note:** the storm rows depend on Chunk 8 and the GRACE row on Chunk 3, so this
chunk lands its GRACE-FO rows first and the group is re-run to append the rest — which the
per-window resumability above already supports.

**You provide.** Catalog TLEs for the held-cat arm — the **matched-staleness** pulls land in
Chunk 6, so this chunk uses a single per-window catalog TLE (the v0.8.0 pattern) and labels
it as such.

**You run.** `run_all.py --only playbook`.

**Verify.**

- **C1 — stated behaviorally**: the arm the gate selects is the best-forecasting arm at that
  anchor, tallied over all anchors, with r/s reported alongside. **Not** "quiet ⇒ r ≥ 0.05" —
  that conflates the calendar window with the drag regime, and GRACE at a low-altitude window
  has far more drag signal than GRACE-FO at solar minimum, so a low r there is the gate
  *working*.
- **C2** — quiet's B\* = 0 catalog-free default beats a held catalog B\* out to ~3 d, with
  the crossover appearing by ~4 d.
- **C3** — the two-stage self-calibrated transplant is the best catalog-free active-regime
  config on a **majority** of anchors (the honest bar under a 2–3× anchor-noise floor).
- **The correlation caveat is printed in the results header**: adjacent anchors share 2 of 3
  arc days and 2 of 3 forecast days; effective independent count ~3–4 per window. The
  **achieved** anchor count is reported, not a promised one.

---

## Chunk 6 — Leg C: matched-staleness catalog parity

**Goal.** The fair fight. Replace "crushes a 6-day-stale catalog" with a same-footing claim.
Resolve **C4**.

**Create / edit.** `probes/probe_catalog_parity.py` → `probes/results_catalog_parity.txt`.
Three rows per anchor: **playbook arm**, **matched-staleness catalog**, **stale catalog**
(continuity with the prior evidence). Per-anchor staleness Δ = T − epoch printed on every
catalog row.

**The selection rule is binding and asserted in code:** the matched catalog TLE is the one
with the **latest epoch ≤ T**. A TLE with epoch > T is future information; the script
**raises** rather than silently selecting it.

**Close-formation cross-tagging is checked, not assumed.** GRACE-FO 1/2 and GRACE A/B each
fly close together (GRACE-FO ~181 km measured, GRACE A/B ~170–270 km), and cross-tagged
catalog entries are a real historical failure mode. Assert object-identity consistency on
every pull — a TLE whose implied orbit does not match the truth ephemeris to catalog tolerance
is rejected with a printed reason.

**Reuse.** `probes/anchors.py` (built in Chunk 5) — imported, not copied.

**You provide.** Space-Track `gp_history` pulls for NORAD 43476, 43477, 27391 and 27392
covering the committed windows, pasted into a committed literal table (the v0.8.0 pattern:
credentials never committed, TLE text committed).

**You run.** `run_all.py --only parity`.

**Verify.**

- **C4** — the playbook still wins on the fit day, but the forward margin **shrinks
  substantially** from the 2×–30× measured against a 6-day-stale catalog. Report the measured
  shrink explicitly, including any anchor where the matched catalog *wins*.
- Every catalog row carries its staleness; no row uses a post-T epoch (assert, don't trust);
  every pull passed the identity check.
- **A note on the 2002–2017 catalog**: TLE quality and observation cadence differ from the
  modern era. Report it as a caveat on the GRACE rows rather than averaging over it.

---

## Chunk 7 — Leg C′: State-path composition through the playbook arms

**Goal.** Measure how much reference-model error erodes the r/s margins when the reference is
propygator's own output calibrated only by the shipped tables — the weld between goals 1 and
2. Resolve **C5**.

**Create / edit.** `probes/probe_state_path.py` → `probes/results_state_path.txt`. At a
subset of Chunk 5's anchors (≥ 3 per window per satellite), run the playbook arms on
`propagate_numerical` references built from (a) the sphere table, (b) the box table, (c) the
window's calibrated scalar Cd from `MEASURED_ANCHORS`, against the truth-path twin as
baseline. Report r and s **for each reference class**, not just forecast RMS.

**Two routes, and every row is labelled with the one that produced it.** The §1.2 State path
propagates its reference internally under **the default `LofAligned` attitude and exposes no
attitude parameter**, so the box table's `InPlaneTracking(ecef)` convention is inexpressible
there. The v0.7.2 template already solved this and says so in its own docstring: sphere table
through **both** the native State path and the external propagate-then-fit route (the
measured equivalence), box table through the **external route only**. Inherit that split.
Rows on the external route measure reference-model error in general; only native-State rows
license a statement about the §1.2 State path.

**Reuse.** `probes/anchors.py`; the Chunk 0/1 spacecraft factories; the v0.7.2
`run_fit_vs_catalog.py --state-path` as the structural template.

**You provide.** Nothing new.

**You run.** `run_all.py --only state-path`.

**Verify.**

- **C5** — table-based references degrade the arms measurably but leave the gate's *decisions*
  intact; r/s margins narrow without inverting. A margin **inversion** is the important
  negative result: it would mean the gate is unsafe for users whose reference is propygator's
  own output, and the playbook must say so. **Resolve it per route** — an inversion seen only
  on external-route box rows is a statement about table-calibrated references, not about the
  §1.2 State path.
- The §1.2 prediction that reference-model error "simply adds" is checked against the
  measured displacement-sum arithmetic, as the v0.7.2 study did when it found the
  uncalibrated-Cd case costing 7.4× (a *derivative* error, not an additive one).

---

## Chunk 8 — Leg D: the storm library and the s-gate's domain of validity

**Goal.** Attack the gate's dangerous failure mode with a real library, and state what s can
and cannot certify. Resolve **D1**.

**Step 1 — the screen (do this before committing the anchor set).** For each candidate event,
load the window and measure the cross-span B\* drift and the raw forecast degradation. If
**both** are null, the window teaches nothing and is replaced. **The library must contain at
least one moderate, gradual event** — a G4 is an easy catch, and the false negative the gate
exists to hunt lives in the excursion big enough to wreck a forecast but small enough that
cross-span drift stays under 10 %.

**The candidate pool is named up front and the search is capped** (contract §7). The moderate
event is a *search*, not a pick, and each screening round costs a 10-day GRACE download at a
per-day volume unknown until Chunk 1 — this is the one place the leg can overrun. Screen in
this order, **moderate candidates flagged**:

| # | Event | Class |
|---|---|---|
| 1 | 2003-10/11 Halloween | G5 |
| 2 | 2015-03 St Patrick's | G4 |
| 3 | **2006-12** | **moderate** |
| 4 | **2015-06** | **moderate** |
| 5 | 2004-11 / 2005-05 | G5 |
| — | 2017-09 | G4, late-mission — screen hard against Chunk 1's attitude-mode / data-gap rules |

Stop at **≥ 3 events including ≥ 1 moderate**, and **cap the search at five screened
windows**. If no moderate event is found by then, the library ships with what it has and the
findings doc records the moderate mode as **untested** — an honest result and a named
follow-on, not a reason to keep downloading.

**Create / edit.** `probes/probe_storm_library.py` → `probes/results_storm_library.txt`.
**≥ 3 events** beyond Gannon, drawn from 2002–2017 (a far richer source than the GRACE-FO era
— one of the clearest gains from the body set change), **plus the extended Gannon window**.
Anchors placed **pre-onset / mid-storm / post-onset by construction**: with the onset at **the
start of day 4 of a 10 d window**, the three classes fall out of fixed day-4 / day-6 / day-8
placement on the study-wide 3 d arc + 3 d forecast geometry. 10 days is exact, not tight.

**Day-labelling convention (contract §3), so the table is unambiguous:** truth days are
numbered 1…10, **each label is an inclusive whole-day count** (`days 1–3` = 3 days), and **an
anchor sits at the *start* of its named day**. Every arc and every forecast below is exactly
3 days; the last forecast ends with the last truth day.

| Anchor | Arc | Forecast | Class |
|---|---|---|---|
| day 4 | days 1–3, entirely pre-onset | days 4–6, spans onset | **pre-onset** |
| day 6 | days 3–5, contains onset | days 6–8 | **mid-storm** |
| day 8 | days 5–7, entirely post-onset | days 8–10 | **post-onset** |

**Gannon is extended to 2024-05-07 → 05-16 and joins the library.** The committed 4-day
window cannot host one 3 d + 3 d anchor — `probe4` was forced to a **1-day** forecast for
exactly this reason (`results_probe4_storm.txt:3`). With the model's onset at the 05-10 UTC
day boundary, day 1 = 05-07 and day 10 = 05-16: six more days, ~0.9 GB. **The committed 4-day
rows stay untouched** as the continuity baseline.

**The classification each row must carry — this is the chunk's principal output:**

- **Gate failure** — nonstationarity *visible inside the arc*, s < 0.1, transplant certified,
  forecast fails. The dangerous mode; never observed in the single storm tested.
- **Unforecastable onset** — nonstationarity *begins after the arc ends*. s small, transplant
  certified, forecast fails anyway — and **no gate computed from past measurements can do
  better.** Not a defect. The pre-onset anchors are expected to land here by construction.

**Reuse.** `tle-fit-strategy/probe4_storm.py` as the template; `probes/anchors.py`; Chunk 1's
GRACE reader.

**You provide.** Downloads for the library windows — **10 days each, positioned so the onset
lands at the start of day 4**; the **Gannon extension (2024-05-07 → 05-09 and 05-14 → 05-16,
six days)**; the event list after Step 1's screen. **Chunk 9 consumes one 2002–2017 library
window as Leg E's GRACE storm regime.**

> **Do not try to acquire a storm window "for both bodies of the E1 pairing" — it does not
> exist.** GRACE re-entered before GRACE-FO launched, so no storm event was flown by both.
> The storm regime carries **one satellite per event** and states the satellite/event
> confound; **E1 is resolved in the quiet and active regimes** (contract §8).

**You run.** `run_all.py --only storm`.

**Verify.**

- **D1** — s detects in-arc nonstationarity and cannot detect post-arc onset. Every row
  classified as gate failure / unforecastable onset / correct rejection; **any true gate
  failure is escalated to the findings doc as a threshold finding**, not buried.
- **The daily-Ap caveat is attached to every storm row** — Orekit's `NRLMSISE00` at default
  switches is daily-Ap-driven, so the prediction-error boundary around a storm is the UTC day
  boundary of the index, not the physical onset. These are results for the model **as
  shipped**, and the caveat bites *harder* on the large fast events 2002–2017 supplies more
  of — say so rather than letting it pass as a constant.

---

## Chunk 9 — Leg E: the fading-memory decision & Checkpoint D

**Goal.** Execute the pre-registered decision experiment and resolve **Checkpoint D**.
**Default outcome is DEFER.**

**Create / edit.** `probes/probe_fading_memory.py` → `probes/results_fading_memory.txt`. The
design, carried from `tle-fit-strategy-findings.md` §3:

- τ ∈ {0.5, 0.75, 1, 1.5, 2, 3} d × {quiet, active, **storm**} × ≥ 3 anchors, in **both**
  B\*-free and B\*-held modes.
- **Sampling-skew axis** — uniform vs log-spaced-toward-recency subsampling, as a declared
  second axis. Under uniform 300-sample subsampling a short τ spends most of the measurement
  budget on near-zero-weight samples; folding that in silently would confound the result. The
  index rule is closed-form, not a draw (bit-determinism).
- **Conservative r-gate protocol** — compute r/s on *unweighted* staging fits, forecast with
  the weighted fit. Preserves the calibrated thresholds at the cost of two cheap fits.
- **E1 — the two-satellite condition is satisfied by GRACE against GRACE-FO, in the quiet and
  active regimes only.** **GRACE-FO 2 does not count** — same altitude, same windows, same
  timescale as GRACE-FO 1, so it is one dynamical case and counting it would be
  self-deception. The pairings: **quiet** = GRACE 2008–09 minimum vs `quiet_2019`; **active**
  = the §3 **E1 drag-timescale window** (GRACE ~430 km, F10.7 matched) vs `active_2023` —
  same activity, ~2.5–3× density contrast, no event confound. **The storm regime cannot
  satisfy E1**: the missions do not overlap, so no storm event was flown by both bodies and
  satellite is confounded with event by construction. Storm rows carry one satellite per
  event and print the confound; the E1 verdict is read off quiet + active. State which
  pairing carried each regime.
- **E2** — report the **τ sensitivity curve**, not the optimum. τ 0.75 → 1.0 d moved a +3 d
  RMS by 1.75× in the teaser; a sharp optimum is a foot-gun even at a good RMS.
- **E3** — if the bar is cleared, state explicitly what weighting does to σ₀, the covariance,
  and therefore the r-gate. A knob that silently invalidates the gate is not shippable.

**Internals note.** The weighted fit is expressible only through `propygator.tle.fitter`
internals (`_run_estimation`, `_MEASUREMENT_CAP`, `_SIGMA_*`), exactly as `probe2` did. The
module docstring must carry the **unsupported-usage** notice. This is sanctioned in an
experiment probe and nowhere else.

**Reuse.** `tle-fit-strategy/probe2_epoch_and_weights.py` (the mechanism, verbatim where
possible); Chunk 5's anchor harness.

**You provide.** The **Checkpoint D** call. No new downloads: quiet = GRACE 2008–09 vs
`quiet_2019`, active = the Chunk 3 **E1 drag-timescale window** vs `active_2023`, storm = one
Chunk 8 library window (GRACE) and the extended Gannon window (GRACE-FO), each contributing a
single satellite with the event confound printed.

**You run.** `run_all.py --only fading` — the heaviest group, though lighter than the headline
count suggests. The declared axes multiply to τ (6) × regimes (3) × anchors (3) × B\*-modes
(2) × skew (2) × satellites (2) ≈ **430 weighted fits**, before the unweighted staging pairs
and the playbook-arm baselines each row is scored against. `probe3` measured **4 anchors in
~80 s wall** (`results_probe3_rule_replication.txt:24`) and each anchor runs 2 staging fits +
4 arms, so the unit cost is **~3.4 s per fit-and-forecast** — the ~20 s figure is per *anchor*,
not per fit. 430 weighted fits is therefore ~25 min, roughly tripling to **~1.5 h** with the
staging pairs and baselines. **Budget ~1.5 h, cap at 3 h.** Size the anchor count against that
before launching, and make the group resumable per regime.

**Verify — the bar, quoted verbatim and applied without softening:**

> Amend §1.2 only if the weighted fit's median +3 d improvement over the corresponding
> playbook arm is **≥ 1.5× in at least two regimes**, **with no regime made > 1.25× worse**,
> under a **single** recommended τ (or a τ rule computable from the fit itself).

- **DEFER** → record the measured verdict, close `tle-fit-strategy-findings.md` §3, keep the
  sweep committed as an experiments recipe. A near-miss is a defer **with the numbers written
  down**.
- **PROMOTE** → the study still ships **without** the API change; a `measurement_decay_tau`
  parameter is a §1.2 amendment on `feature/fading-memory-weights` off `main`, after this
  study merges, with its own minor release.

---

## Chunk 10 — Wrap-up: findings, playbook, pins, reconciliation

**Goal.** Convert evidence into the repo's permanent record. The only chunk touching
`tests/`, docs, README, and notebooks.

**Create / edit.**

- **`docs/extended-validation-findings.md`** — in the style of
  `real-world-validation-findings.md`: why the study exists, truth provenance, per-leg
  results, **every pre-registered prediction (A1–A3, B1, B3, B4, C1–C5, D1, the Leg E bar)
  resolved as hit or miss** and **every reported-only quantity (A4, B2, B5) printed with its
  confounds rather than a verdict**, **every withheld claim stated as withheld** (the "X % table
  error" level and the flight-data geometry claim, each with its reason), honest caveats (the
  contract §2.4 list: LST, the GRACE↔GRACE-FO bus difference, mass, maneuvers, late-mission
  degradation, ITRF realization changes, anchor correlation), and named follow-ons.
- **`docs/tle-fitting-playbook.md` — revised.** Evidence base restated (two missions, four
  spacecraft, the achieved anchor count); thresholds validated **or corrected**; the **s-gate
  domain-of-validity statement** added (s certifies in-arc stationarity and provably cannot
  certify forward validity); the catalog claim restated on matched-staleness footing.
- **New pinned tests** mirroring the v0.7.2 study's three, tolerance policy inherited
  (**measured × a margin generous enough to absorb orekit-data refreshes; relationships over
  absolutes**): a GRACE-FO twin-agreement pin and a GRACE t₀ + day-1 drag-relationship pin
  (`tests/propagation/test_real_world_grace.py`), and an r-gate classification pin extending
  `tests/tle/test_fitter_real_world.py`. Fixtures as in-file literals emitted by driver
  `--emit-fixture` flags; JVM via the `orekit` fixture.
- **Reconciliation:** README "Validation" (the evidence base is no longer single-satellite);
  `notebooks/07_tle_fitting.ipynb` §9 and `notebooks/00_showcase.ipynb` (hand-transcribed
  numbers per CLAUDE.md — **and a fresh static HTML export if the showcase changes**);
  `docs/tle-fit-strategy-findings.md` closed or archived (routes 1, 2, 3, 4, 6 executed;
  route 5 survives; §3 resolved by Checkpoint D); `docs/real-world-validation-findings.md`
  cross-referenced, **numbers not edited**; `experiments/extended-validation/README.md`
  finalized with the findings-at-a-glance table.
- **`run_all.py`** finalized: `--list`, `--only <group>`, `--verify` (scratch run + diff with
  wall-clock lines masked), CRLF output to match committed evidence.

### The DSMC correction — the saved edits, applied HERE and nowhere earlier

**The edit list and the full blast-radius table live in contract §9 ("The DSMC correction")
and are not duplicated here** — they carry file paths, line numbers and per-file dispositions
that must have exactly one authoritative copy. Work this chunk with that section open. What
this plan adds is only the sequencing:

1. Apply the contract §9 table's **three prose edits** (findings doc ×2, `gracefo/README.md`
   correction block). **Additive only** — no constant edited, no results file regenerated.
2. Confirm the table's **"do not touch"** rows are untouched: `gracefo_common.py:65`,
   `results.txt` (all eight band lines), `run_gracefo.py`, `probes/probe_tables.py`, and the
   archived `docs/history/build-plan-real-world-validation.md`.
3. Run `run_all.py --verify` on the **v0.7.2 tree** and confirm it is still green. That is the
   proof the correction stayed additive.

**Wording discipline: withdrawn, not refuted.** Mehta, McLaughlin & Sutton (2013,
*Adv. Space Res.* 52(12) 2035–2051) is a genuine DSMC study of the GRACE bus, but its values
were not checked against the paper — so the correction may **not** assert the box table falls
outside a correctly-sourced band. Record: *the credibility claim rested on a mis-sourced upper
edge and is withdrawn; absent a verified reference this project makes no statement about
absolute Cd level, consistent with contract §2.1.*

**No user-facing correction and no test churn** — the retraction never reached `src/`,
`tests/`, `README.md`, the notebooks or the playbook (contract §9 verifies the counts).

**Reuse.** Every results file from Chunks 0–9.

**You provide.** CHANGELOG entry + version bump (**patch `v0.8.1`** per contract §11); the PR
and squash-merge; the tag.

**You run.** `pre-commit run --all-files`; `conda run -n propygator pytest`; `run_all.py
--verify` per group.

**Per-group `--verify` is the documented default.** A whole-study verify runs the drag
window-runs *plus* Leg E (~1.5 h, capped at 3) — a multi-hour act, not a pre-commit check. `--only
<group>` is what a normal wrap-up session runs; the full sweep is scheduled once,
deliberately, and its result recorded. Say so in the study README so a later reader does not
launch it casually.

**Verify (the contract's Definition of Done, §13).**

1. GRACE-FO 2 stands up; Checkpoint A resolved GO against the twin criterion.
2. GRACE stands up; format resolved by inspection, reader in the new tree, self-checks and
   both screens clean.
3. Leg A complete; **A1–A3 resolved, A4 reported as a diagnostic**; the M1 noise floor
   measured and labelled with **all three** terms.
4. Leg B complete; the `D(w)` curve bracketed over A/m with σ; the tables' modelled response
   obtained **by `.npz` lookup** and quoted beside it **with the attribution declined**; the
   **dimensional-collapse finding recorded with its measured 0.490 % RMS** and its
   table-vs-own-physics scope stated (never as an absence claim); **B1/B3/B4 resolved, B2/B5
   reported**;
   σ(T) with the two floors routed by cancellation structure; **no DSMC comparison.**
5. Leg C complete; frozen thresholds; matched staleness at every anchor; C1–C5 resolved, C5
   per route.
6. Leg D complete; ≥ 3 events including one moderate, plus the extended Gannon window;
   gate-failure vs unforecastable-onset resolved; the domain-of-validity statement in the
   playbook; the daily-Ap caveat on every storm row.
7. Leg E resolved; **E1 satisfied by GRACE vs GRACE-FO in quiet + active**, not the twin and
   not in the storm regime; **Checkpoint D recorded** against the verbatim bar with the
   sensitivity curve in evidence.
8. Evidence regenerable by one orchestrator command, every header carrying both versions;
   findings doc complete with withheld claims stated; playbook revised; new pins green.
9. **Frozen-evidence rule honored** — no code, constant or results file in
   `experiments/real-world-validation/` changed; the DSMC correction landed as additive prose
   only and that tree's `--verify` is still green.
10. Reconciliation done (README, both notebooks, the two findings docs) **and the DSMC
    correction edits 1–3 applied.**
11. **No `src/` change on this branch**; `pre-commit` clean; CHANGELOG + version bump authored
    by the maintainer.

---

## Notes / deferred

- **A genuine bus contrast** — the one thing the GRACE lineage cannot supply. **TerraSAR-X /
  TanDEM-X** is the candidate worth checking (~515 km, hexagonal prism, body-mounted panels,
  close-formation twins, so a bus contrast *and* a second noise-floor pair); public POD terms
  unconfirmed, which is why it is a follow-on and not a leg. **Swarm is not the candidate** —
  contract §12 records why.
- **The 70×70 gravity truncation self-ablation** — never ablated at LEO, only at LAGEOS
  altitude where degree 70 is suppressed by ~1e-20 against ~5e-3 here, and `eigen-6s.gfc`
  carries 240 degrees. Needs no truth data (70 vs 120 vs 200 against itself) and sits
  underneath every along-track residual this study measures. Cheap; deliberately out of scope
  so this study does not sprawl.
- **Route 5 (refit-cadence sweep)** — does selfcal 2d→12h beat 2d→1d? Is there a horizon past
  which re-staging beats holding yesterday's transplant? Cheap rows on this harness; left open
  deliberately.
- **The NRLMSISE-00 ap-history mode** (`withSwitch(9, -1)`) — a shipped-code change that would
  move every storm-time number in the repo. Its own study; the storm windows this study
  commits are ready-made test cases for it.
- **A drag-free high-LEO point** (Sentinel-3 / Jason-3) — the r-gate's "no" arm at genuinely
  negligible drag. Deferred: a fourth product format for one arm of one gate.
- **`earth_radiation`** — parked, upstream blocker lifted (orekit_jpype 13.1.7.0 on
  conda-forge), but its resume is a `feature/` branch off `main` and requires an env upgrade
  this study's freeze forbids.
- **The fitted-box geometry upgrade** — still deferred; Chunk 4's B4 re-tests the premise but
  cannot lift the deferral.
