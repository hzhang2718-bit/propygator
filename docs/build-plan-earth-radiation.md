# Build plan: Earth radiation pressure resume (+ frozen-study `--verify` repair)

> **Status: Part A CLOSED at its A0 STOP gate (2026-09-06) — the feature stays
> parked. Part B is the live half, unstarted.** The gate did not flip: Orekit's
> 13.1.6 `acos` horizon fix is real, but `KnockeRediffusedForceModel` carries a
> **second** defect — the Lambertian emission cosine computed as the geocentric
> central angle — inflating ERP **1.98× at LEO** and 1.21× at GEO. A1–A5 stand
> as the recipe for whenever upstream fixes it; the evidence, the measured
> factors, and the stricter two-probe resume bar are in
> `experiments/earth-radiation/README.md`. **Part B** repairs the
> real-world-validation `run_all.py --verify`, red since v0.7.3 and deferred to
> "its own process" by the extended-validation plan's Chunk 26.
> Part A's **binding contract is the ERP half of
> `docs/history/general-upgrades-1.md` "Planetary Third-Body & Earth Radiation
> Pressure"**; where this plan and that section disagree, the **contract wins**.
> Chunks 2–3 of `docs/history/build-plan-additional-perturbations.md` are the
> archived sequencing this plan absorbs and supersedes. Status headers are the
> maintainer's — trust the git log.

## Facts verified 2026-09-06 (nothing here is remembered)

| Claim | How checked |
|---|---|
| `erp-runtime-chunk2.patch` still applies to `main` | `git apply --check` exit 0, 15 commits past its `a9259dc` base |
| conda-forge offers `orekit_jpype` **13.1.7.0 and 13.1.7.1** | `conda search -c conda-forge orekit_jpype` |
| the working env is still **13.1.4.0** | `importlib.metadata` in the env |
| ~~`environment.yml`'s `orekit_jpype=13.1.*` already permits both~~ — **corrected 2026-09-06: the `jpype1=1.5.*` pin blocks the upgrade**, since `orekit_jpype 13.1.7.x` requires `jpype1 1.7.1.*`; adoption is a two-pin change | `conda env create` solver failure, then `conda search --info` |
| CI builds from `environment.yml` with `cache-environment: true` | `.github/workflows/ci.yml:32-39` |
| the ERP Supercessions were never folded back | `features.md` contains no `earth_radiation`; `architecture.md:1185` still says "blocked" |
| the LAGEOS truth file is on disk | `data/lageos/esa.orb.lageos2.230422.v70.sp3.gz` |
| `--verify` exits 1 on any diff | `run_all.py:216-217` |
| the two recorded magnitudes for the frozen diff contradict | `experiments/real-world-validation/README.md:120-126` vs `docs/history/build-plan-extended-validation-updated.md:1149-1155` |

**Recorded but unmeasured:** the ~0.2 % Run-5 shift. Chunk B1 measures it before
anything is decided.

## Source-of-truth docs (do not silently diverge)

- `docs/history/general-upgrades-1.md` "Planetary Third-Body & Earth Radiation
  Pressure" — the binding contract, including its 2026-07-05 Outcome note.
- `docs/history/build-plan-additional-perturbations.md` Chunks 2–3 — the
  archived sequencing, still authoritative on wiring detail.
- `experiments/earth-radiation/README.md` — the bug evidence, the parked patch,
  the 5-step resume recipe.
- `docs/history/build-plan-extended-validation-updated.md` Chunk 19 (checklist
  line 947) + Chunk 26 "Known red, by design" — the documentation of the
  `--verify` failure and the decision to give it its own branch.
- `docs/validation-findings.md` §8 — the LAGEOS ERP acceptance test, named as a
  follow-on and built here as Chunk A4.

## Decisions already locked (contract; do not relitigate)

- `earth_radiation: bool = False` **inserted after `srp`**, not appended; a
  **bare** `earth_radiation` token in the slot after `srp`.
- The resolution knob is a **module constant**, never a config field; its value
  is the benchmark's to choose.
- **SRP optics reused**: sphere → its own `IsotropicRadiationSingleCoefficient`;
  box → the shared `BoxAndSolarArraySpacecraft`, now driving three forces.
- 4-arg Knocke constructor; **independent of `srp`**; **no shadow wiring**.
- `spacecraft` / `attitude` metadata gates widen to drag-or-SRP-or-ERP.
- Off in every preset — a both-off run stays byte-identical.

## Open decisions (maintainer's, flagged at their chunk)

1. **Env adoption** — whether the working `propygator` env moves to 13.1.7.x, and
   whether `environment.yml` gains an exact pin (A1). The frozen studies were
   measured on 13.1.4.0.
2. **Version** — a new public config field is a minor bump (v0.9.0); the archived
   plan's "no tag, fold into v0.5.0" is dead (A5).
3. **Part B's repair shape** — Option A / B / C at Checkpoint B.

## Architecture invariants to honor

Orekit types stay internal; `jpype`/`org.orekit.*` imported **lazily inside
functions**; config construction + serialization stay pure-Python and safe
before init; SI internally; `logging`, never `print`; JVM-touching tests acquire
the **`orekit` fixture**; experiment stdout **ASCII-only**.

## How to use this plan

- **Part A: chunks A0–A5**, each one session. **Part B: chunks B1–B2**, its own
  branch off `main`.
- **A0 is a STOP gate** — if the probe verdict does not flip, the feature stays
  parked. **Checkpoint A** (after A3) and **Checkpoint B** (after B1) are soft.
- **Sequencing rule: Part B runs on the untouched 13.1.4.0 env.** Diagnosing a
  box-table diff under a bumped Orekit conflates two causes, so Part B either
  goes first or runs in `propygator` while Part A lives in its clone.
- **Commits, CHANGELOG, chunk "done" marks, and merges are the maintainer's.**
- `/code-review` + `/simplify` after A2 and in the A5 sweep.

---

# Part A — the `earth_radiation` resume - PARKED

Branch `feature/earth-radiation` off `main`. Not the extended-validation branch,
which forbade this work explicitly.

## Chunk A0 — clone-and-test env + probe verdict (STOP gate)

**Goal:** prove the upstream fix is in before touching `src/`.

**Create / edit:** an uncommitted copy of `environment.yml` in the scratchpad
with **both** pins bumped — `orekit_jpype` and `jpype1`, which 13.1.7.x forces
to `1.7.1.*`; `environment.yml` itself is only edited at A5, if adopted.

**Reuse:** `experiments/earth-radiation/knocke_bug_probe.py` and
`knocke_cosine_probe.py` unchanged — together they are the resume check, and
neither needs the ERP runtime.

**You run:** `conda env create -n propygator-erp -f <the copy>`, then both
probes under `conda run -n propygator-erp`. **Never mutate the working env.**

**Verify — two gates, both required** (2026-09-06 found a second defect that the
first gate alone cannot see):

1. `knocke_bug_probe.py` reads **~0.85**, not 1.00 — the anchor assumes a uniform
   e = 0.68 and a 1 AU Sun where the model uses e ≈ 0.55 at 51.6° latitude and a
   January Sun; the SRP control still matches theory. (13.1.4.0 read 2.42;
   13.1.7.1 reads 1.69.)
2. `knocke_cosine_probe.py` reads an as-coded inflation of **1.000×** — i.e. the
   Lambertian emission cosine is finally the emission cosine.

> ### 🛑 STOP gate
> Either gate failing means the wrapper does not carry both fixes: stop, record
> the tag row in the experiment README, and leave the feature parked. Gate 2
> failed on 13.1.7.1 at 1.98× — that is where Part A closed.

## Chunk A1 — measure what the Orekit bump moves

**Goal:** know the blast radius of the upgrade *before* any ERP code lands.

**You run:** the full suite in the clone env, plus the stack-compat test;
compare failures against a same-day baseline run in `propygator`.

**Record** (a short delta note in the experiment README): every test whose number
moved, with the measured shift — attention on the three real-world pinned modules
(`test_real_world_lageos.py`, `test_real_world_gracefo.py`,
`test_fitter_real_world.py`), the fitter pins, and the plot snapshots.

**Decide (maintainer):** whether `propygator` adopts 13.1.7.x and whether
`environment.yml` gets an exact pin. There is **no standing CI exposure** — the
`jpype1=1.5.*` pin blocks 13.1.7 outright, so a cache miss still rebuilds on
13.1.4.0. (The 13.1.7.1 suite run is already banked: 1105 passed, no pinned
number moved — see the experiment README.)

**Verify:** the suite is green in the clone env, or every failure is explained
and sized — an unexplained failure blocks A2.

## Chunk A2 — re-apply the parked runtime (archived Chunk 2)

**Goal:** land the reverted runtime where it still fits, at a provisional constant.

**Create / edit:**
- `git apply experiments/earth-radiation/erp-runtime-chunk2.patch` — the config
  field, the serializer's required keyword + token, `_build_earth_radiation_force`,
  the widened box-build condition, the force added after SRP, the `_WiredForces`
  field, both widened metadata gates + their comments, the docstrings, and four
  tests. Verified to apply clean; both `_serialize_force_models` call sites, the
  one `_WiredForces(...)` site, and the pinned
  `sphere:A=1.0;m=1000.0,Cd=2.2,Cr=1.5` string are all still current.
- **Recalibrate `test_earth_radiation_effect_is_real_and_below_srp`** — its
  bounds were computed against physics that ran 2.4× hot.
- Leave the constant **provisional at 15°**; A3 owns the value.

**Reuse:** `_build_srp_force`'s sphere/box split and asserts; the shared-box
machinery; the Chunk-1 planets seams.

**Verify:** `pytest tests/propagation` green in the clone env; a both-fields-off
run's metadata byte-identical; `import propygator` still JVM-free.

> ### ✅ Checkpoint — shipped surface rebuilt
> `/code-review` + `/simplify` on the diff; commit + push.

## Chunk A3 — resolution benchmark + magnitude characterization

**Goal:** contract deliverables 1–2 — pick the constant and measure the honest
numbers, **through the shipped stack**.

**Create / edit** (in `experiments/earth-radiation/`, ASCII-only, conda env):
- `erp_resolution_benchmark.py` — the reference sail (the ECEF study's 1 m² /
  0.5 kg thin-plate box at 500 km SSO, `InPlaneTracking(velocity_reference="ecef")`)
  over the ladder **90° → 45° → 30° → 15° → 10° → 5° → 2.5°**, finest as truth;
  per rung the along-track error vs truth **and** wall clock; pick the coarsest
  converged rung. **The pre-fix ladder is not reusable** — the fix shrinks the LEO
  cap, and the old GEO rungs were already non-monotonic between 2° and 1°.
- The rung override is
  `propygator.propagation.numerical._EARTH_RADIATION_ANGULAR_RESOLUTION = <value>`
  before each run, stated in the script header as a deliberate private-constant
  override confined to this script.
- `erp_magnitude_study.py` (or the same driver) — ERP on vs off at the chosen
  resolution, drag + SRP on, multi-day, for **(a)** the sail and **(b)** the
  conventional bus (1000 kg / 1 m² sphere): the ERP-vs-SRP acceleration fraction,
  the along-track divergence, and the direction sanity check (mostly radially
  outward).
- A figure + captured `results.txt` + the README's provenance section.
- **Finalize the constant:** set it, drop "provisional", cite this study.

**You provide:** confirmation of the sweep defaults (the ladder, a 1–2 d sweep arc
vs a multi-day characterization arc, drag off during the sweep); then the
Checkpoint-A confirmation.

**Verify:** a clean convergence plateau; the chosen rung's error ≪ the effect; the
full suite green at the final constant; `results.txt` ASCII-only.

> ### 🔎 Checkpoint A — constant + numbers confirmed (soft)
> The maintainer confirms the constant and the sail/bus numbers before any doc
> quotes them. No plateau, or pathological cost → pause and reconcile with the
> contract.

## Chunk A4 — LAGEOS ERP acceptance (new; not in the archived plan)

**Goal:** an external-truth check that the wired force has the right sign and
order — `docs/validation-findings.md` §8's named next step.

**Create / edit:** `experiments/earth-radiation/erp_lageos_acceptance.py` —
imports the frozen leg's `run_lageos` / `sp3` / `common` modules, propagates the
committed 7-day arc with `earth_radiation` on and off at the A3 constant, and
reports 3D + RIC RMS and the signed along-track at 7 d. Output to
`experiments/earth-radiation/results_lageos_acceptance.txt`.

**It does not touch `lageos/results.txt`.** The frozen study stays frozen; the
new row lives in the ERP folder next to a transcribed baseline. The ablation
matrix's `("planets third body ON", ...)` row is the shape to copy, not a file
to edit.

**The wiring check comes first:** the `earth_radiation=False` arm must reproduce
the committed baseline (day-1 3.6 m RMS, 7-day 23.6 m, almost purely
along-track). Only then is the delta meaningful.

**Expected signature** (recorded, not a gate): the along-track floor **tightens by
the ERP order — metres per day — without vanishing**, since thermal thrust stays
unmodeled. A larger or sign-flipped residual is the failure signal; the probe and
A3's direction check are where to look first.

**Reuse:** the truth file already on disk; `ric_components` / `rms` from
`common.py`, read-only.

**Verify:** the off-arm reproduces the baseline; the on-arm delta is reported with
its sign; LAGEOS's Cr 1.13 is **not** tuned here (the §7 untested-Cr caveat stands).

## Chunk A5 — docs fold-back, env adoption, release

**Goal:** land the contract's pending Supercessions and ship.

**Create / edit:**
- `features.md` §1.1 — the dataclass field in grammar position; the preset-table
  row + extended off-in-all-presets sentence; the optional-physics-keys gates
  (drag/SRP/ERP); the grammar paragraph + example; the model-limitations bullet
  **verbatim** from the contract.
- `architecture.md` §13 — the bullet flips from "designed but blocked" to shipped.
- `general-upgrades-1.md` — the Outcome note gains the resume: the chosen
  constant, the headline numbers, Supercessions folded back.
- `docs/validation-findings.md` §8 — the `earth_radiation` follow-on closes with
  A4's result.
- `README.md` force inventory; `CLAUDE.md` "Project state" + its Forces line.
- `environment.yml` (if adopted) + a `docs/verified_environments/2026-09.txt`
  snapshot.
- `experiments/earth-radiation/README.md` — bug evidence becomes the resume
  record; the tag table gains the fixed row.

**You provide:** the CHANGELOG entry, the version bump + editable reinstall, the
PR, the squash-merge, the tag.

**Verify:** full `pytest` + `pre-commit run --all-files` green; `import propygator`
JVM-free; every Supercessions spot carried; if A1 moved a number the notebooks
hand-transcribe, `00_showcase.ipynb` and notebook 07 §9 are updated and re-exported.

---

# Part B — the frozen study's `--verify` repair

Its own branch off `main`, per Chunk 26's deferral. **Runs on the untouched
13.1.4.0 `propygator` env** — this is a v0.7.3 table question, not an Orekit one.

## Chunk B1 — measure the actual diff, and nothing else

**Goal:** replace two contradictory recorded magnitudes with one measured number.

**You run:**
`conda run -n propygator python run_all.py --verify --only drag,state-path --out-dir <scratch>`
— ~1 h, dominated by the golden-section Cd fits.

**Record:** every differing line; the Run-5 along-track RMS delta; the face-sum
Cd·A delta.

**Adjudicate the contradiction:**
- `experiments/real-world-validation/README.md:120-126` — "exactly four
  `leeward -0.000` → `0.000` prints … the numeric effect on Run 5 is ~1e-11 m² of
  Cd·A, below printed precision."
- `docs/history/build-plan-extended-validation-updated.md:1149-1155` — "~0.2 %
  box-table (Run 5) shift … its README note undersold the effect by ~5 orders of
  magnitude."

At most one is right. Neither carries a committed measurement.

**Verify:** the diff is fully explained by the v0.7.3 table — spot-check by
loading the pre- and post-fix grids at the realized face-flow angles — and no
*other* divergence is present. Confirm the other three groups are still clean.

> ### 🔎 Checkpoint B — the repair shape (maintainer's)
> B1's number decides whether this is a prose correction or a tooling change.

## Chunk B2 — the repair

**Option A (recommended, minimal).** Keep the numbers frozen; give `run_all.py` a
committed **known-diff baseline** — a small ASCII file of sanctioned diff lines
per group. `--verify` reports them separately and exits 0 only when the diff is a
subset of them, non-zero on anything new. Restores the tool's signal without
recomputing frozen evidence; ~30 lines in the orchestrator.

**Option B (full).** Regenerate the `drag` + `state-path` groups against the
current table with a dated provenance note. This **recomputes frozen evidence** —
it needs explicit authorization, and every quoted Run-4 / Run-5 number in
`gracefo/README.md` and `validation-findings.md` §3–4 must then be swept.

**Option C (prose only).** Correct the README with B1's number; `--verify` stays
red.

**In all three:** the README Conventions bullet is corrected to B1's measured
number — that sentence is wrong today under either reading — and Chunk 19's
`[*] NOT green` checklist line is closed by a pointer to this branch.

**You provide:** the option choice; explicit authorization if B.

**Verify:** `--verify --only drag,state-path` exits 0 (A or B) or the README states
the measured diff (C); the other three groups still reproduce; no shipped `src/`
file is touched by this branch.

---

## End-state verification

1. **Probe:** LOOKS FIXED on the adopted stack, its result committed.
2. **Runtime:** `earth_radiation` wires Knocke through the shipped SRP optics
   (sphere and box; the box drives three forces off one object), the token sits
   in its fixed slot, the widened gates are test-pinned, a both-off run is
   byte-identical.
3. **Constant:** the benchmark-chosen value with a comment citing the study.
4. **Evidence:** `experiments/earth-radiation/` holds the convergence plateau,
   the wall-clock ladder, the sail + bus magnitudes, the direction check, and the
   LAGEOS acceptance result.
5. **Docs:** every Supercessions spot carried; the Outcome note updated;
   `validation-findings.md` §8's ERP item closed.
6. **Part B:** `--verify` is green-or-honest, and the frozen numbers are untouched
   unless Option B was authorized.
7. `conda run -n propygator python -c "import propygator, jpype; print(jpype.isJVMStarted())"` → `False`.

## Out of scope

- The **NRLMSISE-00 ap-history** follow-on (`withSwitch(9, -1)`) — its own study.
- The extended-validation study's **per-group `--verify` sweep** and the
  **fading-memory** branch authorization.
- **`LofOffset`-ecef**, per-face optical properties, albedo-only / IR-only
  switches, and any `angular_resolution` config field — all contract-level
  exclusions.
