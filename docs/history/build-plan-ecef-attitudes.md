# Build plan: ECEF InPlaneTracking (`velocity_reference="ecef"`)

> **Status: BUILD PLAN (not started).** Derived from the **"ECEF InPlaneTracking"**
> section of `docs/general-upgrades-1.md`, which is the **binding contract** for this
> work (the way the "Tier B Drag" section was for its plan). Every axis rule,
> validation row, metadata token, and gate below traces to that section — cited inline
> as "(contract: <heading>)". Where this plan and the contract disagree, the
> **contract wins**; fix the plan. Status headers are the maintainer's — trust the git
> log for true status.

## Context

`InPlaneTracking` gains `velocity_reference: str = "inertial"`; `"ecef"` re-aims the
mode's *primary* alignment from the inertial velocity to the Earth-relative
(atmosphere-relative) velocity `v_rel = v − ω⊕×r`, reusing the custom ECEF
`TargetProvider` shipped with `NadirPointing(velocity_reference="ecef")` **verbatim**
(one new call site, zero provider changes). The headline user is a feathered drag/solar
sail flown with `BoxFaceCd` — today no declarative mode can zero a flat body's angle of
attack to the true co-rotating flow.

**This upgrade was born in Tier B's wrap-up.** The Tier B pre-Chunk-7 note
(`docs/history/build-plan-tier-b-drag.md`) measured the edge-on sail benefit at **~2×
instead of the idealized ~9× precisely because `InPlaneTracking` sat a few degrees off
the true flow**, and flagged this `velocity_reference` option as the follow-on. That
committed evidence is a strong *prior* that the attitude reference is material for the
headline sail — but the Chunk-1 study, not the prior, makes the GO/NO-GO call.

**This is one of several independent general upgrades** headed for **v0.5.0** (third,
after Tier B drag and the live-dashboard mutate-in-place layer). Its branch —
`feature/ecef-attitudes`, already created by the maintainer — merges to `main` with
**no version bump and no tag** (v0.5.0 is tagged once, after all upgrades land).
`general-upgrades-1.md` stays alive for any remaining upgrades.

**End state:** `pgr.InPlaneTracking(velocity_reference="ecef")` propagates end-to-end;
the default `InPlaneTracking()` is **bit-identical to today** (same native provider
path); the `attitude` metadata token becomes `in_plane_tracking:vel=<ref>`; the Tier
B-era "inertial velocity only" caveat in `features.md` §1.1 and the `BoxFaceCd`
docstring is retired. `propagate_numerical`'s signature, the provider, and every other
attitude mode are unchanged.

### Source-of-truth docs (do not silently diverge)

- `docs/general-upgrades-1.md` **"ECEF InPlaneTracking"** — the binding contract. Key
  sub-headings: *Supercessions*, *Context*, *Details* (API at a glance, Axis
  construction, Provider lowering, Attitude rates, Validation, Failure mode, Metadata,
  Sphere interaction, Performance, Out of scope, Evidence gate).
- `docs/features.md` §1.1 and `docs/architecture.md` §13 — authoritative **except**
  the spots the contract's *Supercessions* list replaces; reconciled in Chunk 4.
- `docs/history/feature-1.1-addendum-ecef-nadir-and-direction-markers.md` §2 — the
  design record of the shipped `TargetProvider` (the overload-collapse and
  default-method traps it already handles). Reference; do not re-derive.
- `docs/history/build-plan-tier-b-drag.md` — the pre-Chunk-7 note (origin story, the
  committed edge-on study scenario + numbers) and the edge-on benefit driver this
  plan's study reuses as a template.

### Decisions already locked (do not relitigate)

- **The ECEF target takes the *primary* slot** (+Y exact on the wind; +Z demoted to
  best-effort on the orbit normal) — the inverse of `NadirPointing`'s secondary-slot
  swap. Momentum-primary would keep the plate in the orbit plane and buy nothing
  (contract: *Context*, third bullet).
- **`_build_ecef_velocity_target_provider` is reused unchanged.** No edits to the
  provider, its overload dispatch, or its zero-derivative trick.
- **`inertial` stays bit-identical**: `PredefinedTarget.VELOCITY` primary, fully
  native, zero behavioral change.
- **Metadata is always emitted**: `in_plane_tracking:vel=inertial` |
  `in_plane_tracking:vel=ecef` (the default's serialized token changes — a deliberate
  contract supercession).
- **Scope = `InPlaneTracking` only.** `LofOffset`-ecef is the named follow-on;
  `LofAligned`-ecef is permanently redundant; `SunPointing` phasing is skipped
  (contract: *Out of scope*).
- **Bundle into v0.5.0** — no tag/version bump in this plan.

### Decisions to confirm (defaults chosen; "You provide" flags them)

- **Study scenario (Chunk 1).** Default: the contract's thin-plate sail with
  `BoxFaceCd.default()` on a **~500 km SSO** (i ≈ 97.4° — near-max out-of-plane wind)
  over a multi-day window, plate dims patterned on Tier B's edge-on sail (1 m² face,
  0.01 m edge, 2 kg). *Recommended add-on:* also re-run at Tier B's exact edge-on
  scenario (400 km circular / i 51.6° / 5 d / solar max) for direct comparability with
  the committed `cd_box_benefit_study_edgeon` evidence. Confirm before Chunk 1.
- **The GO/NO-GO call at Checkpoint A** is the maintainer's.

### Architecture invariants to honor (CLAUDE.md / architecture §4, §10)

Orekit/Java types stay internal; `jpype`/`org.orekit.*` imports **lazily inside
functions**; the dataclass + validation + metadata stay **pure-Python, safe before
init** (the `tests/core`-style no-JVM property of config construction); SI internally;
`logging`, never `print`; JVM-touching tests acquire the **`orekit` fixture** (that is
how the conftest hook orders them after the pure-Python guards).

---

## How to use this plan

- **4 numbered chunks**, each sized for one Claude Code session and independently
  verifiable:
  - **Chunk 1 is the evidence gate** — runs wholly in the **conda env** (every piece
    is shipped; no experiment venv, no pymsis/scipy). Its output is committed
    *evidence* (figure + ASCII-only captured stdout), not pytest tests.
  - **Chunks 2–3 are the shipped code** (2 pure-Python, 3 JVM-touching); **Chunk 4 is
    wrap-up.**
- Each chunk lists **Goal / Create-Edit / Reuse / You provide / You run / Verify**.
- **One STOP gate:** Checkpoint A (after Chunk 1). If the `inertial` → `ecef`
  difference is immaterial for the headline sail, **drop the parameter** rather than
  ship (contract: *Evidence gate*).
- **`/code-review` + `/simplify` checkpoints:** after Chunk 3 (the provider branch +
  live tests) and in the Chunk 4 sweep.
- **Commits, CHANGELOG entries, chunk-header "done" marks, and the merge are the
  maintainer's.** Claude writes code and runs read-only/test commands; the maintainer
  runs the study, commits, and pushes.
- **Mergeable chunks:** 2 + 3 can merge into one session (the diff is small); split
  them if the JVM session runs long.

---

## Git (read once)

The branch **`feature/ecef-attitudes`** already exists (created by the maintainer off
`main`); the contract section and this plan ride on it. Per-chunk rhythm:
`git status` → `git add -A` → `git commit -m "ecef-attitudes chunk N: <summary>"` →
`git push` (CI runs on the branch). **Do NOT** bump `pyproject.toml` version or tag —
v0.5.0 is cut after all the general upgrades land.

---

## Chunk 1 — Feathered-sail benefit study → GO/NO-GO Checkpoint A - Done

**Goal:** quantify `inertial` vs `ecef` `InPlaneTracking` for the headline sail with
the **real propagation stack**, *before* the runtime exists — so the parameter can be
dropped cheaply (contract: *Evidence gate*).

**The stand-in trick (what makes this front-loadable):** the `ecef` leg runs *today*
via `CustomAttitude` with a feathered law — per state, compute
`v_rel = v − ω⊕×r` with a hardcoded `ω⊕ = 7.292115e-5 rad/s` about EME2000 +Z (the
~0.3° pole offset is negligible for a benefit study), then build the contract's frame:
`Y = unit(v_rel)`, `Z = unit(ĥ − (ĥ·Y)Y)`, `X = Y×Z` → `Orientation` (contract: *Axis
construction*). This exercises `propagate_numerical` + `BoxFaceCd.default()` end-to-end
with no new runtime, and later doubles as an **independent cross-check** of the shipped
provider (Chunk 4). The `CustomAttitude` per-substep Python cost makes the run slower —
fine for an experiment.

**Create / edit** (all in a new `experiments/ecef-attitude-benefit/`; reference-only,
outside `testpaths`, excluded from CI/lint; **ASCII-only prints** — stdout is captured
under cp1252):
- A driver (e.g. `ecef_feather_benefit.py`) propagating the sail **twice** —
  `attitude=InPlaneTracking()` vs the feathered `CustomAttitude` — over the multi-day
  window, then reporting:
  - **(a) big-face AoA history** vs the true flow for both legs (pure geometry off the
    sampled states + the same hardcoded-ω⊕ wind). Expected: identically ~0 for the
    feathered leg; oscillating 0 → ~3.8° → 0 per half-orbit for `inertial`. **The ~0
    assertion doubles as the DCM-sense check** — a transposed rotation in the law
    shows up immediately as a non-zero AoA.
  - **(b) assembled `CdA` history** for both legs (`BoxFaceCd` is a pure-Python
    callable — direct `table(radius, density, θ_i)` lookups over the six faces at a
    representative density).
  - **(c) the along-track divergence** between the two trajectories (the headline
    number; same diff style as the Tier B edge-on study).
- A figure (AoA + CdA + divergence panels) + captured `results.txt`, committed as
  evidence with a short folder `README.md` (the experiments provenance pattern).

**Reuse:** `experiments/drag-coefficient-verification/cd_box_benefit_study_edgeon.py`
as the template (the propagate-twice-and-diff shape, the sail geometry, the along-track
metric); `propagate_numerical` + `BoxFaceCd.default()` + `CustomAttitude` (all
shipped); `Frame`/`State` conversions for the geometry math.

**You provide:** the scenario confirmation (SSO default ± the Tier B comparability
leg); **the GO/NO-GO call at Checkpoint A.**

**You run:** `conda run -n propygator python experiments/ecef-attitude-benefit/...`;
eyeball the figure; commit the evidence.

**Verify:** the feathered leg's AoA is ~0 and the `inertial` leg's matches the
predicted out-of-plane wind oscillation (validates the axis math before it becomes
runtime); the along-track divergence is quantified; bare `pytest` unaffected.

> ### ⛔ GO/NO-GO Checkpoint A
> 1. If the `inertial` → `ecef` difference is **immaterial** for the headline sail
>    (drag/along-track change lost in the constant-Cd noise floor) → **STOP: drop the
>    parameter**, record the evidence, add an Outcome note to the contract section
>    (the blitting precedent), do not build Chunks 2–3.
> 2. If **material** (the Tier B ~2×-vs-~9× prior says expect this) → **GO**.
> 3. Commit + push the evidence either way.

---

## Chunk 2 — The `velocity_reference` field: validation + metadata (pure-Python, safe before init) - Done

**Goal:** the config surface — constructible and validating with **no JVM** (contract:
*API at a glance*, *Validation*, *Metadata*).

**Create / edit:**
- `src/propygator/propagation/attitude.py`:
  - `InPlaneTracking` gains `velocity_reference: str = "inertial"` + `__post_init__`
    sharing `_VALID_VELOCITY_REFERENCES` and mirroring `NadirPointing`'s message shape
    (`attitude.py:239-244`); class docstring per the contract's API block.
  - `_metadata_string` → `f"in_plane_tracking:vel={self.velocity_reference}"`
    (**always emitted**).
- **Tests** (`tests/propagation/test_attitude.py` — config tests, fixture-free):
  - default is `"inertial"` (mirror `:62`); accepts `"ecef"` (mirror `:142-145`);
    rejects a bad value with `ValueError` (mirror `:148-150`).
  - metadata pairs: update the `(InPlaneTracking(), "in_plane_tracking")` row (`:174`)
    to `"in_plane_tracking:vel=inertial"` and add the `ecef` pair (mirror `:173`).
  - **rename/rewrite `test_in_plane_tracking_has_no_params` (`:65-66`)** — the mode
    now has a parameter.
- **Consuming metadata assertions:** `tests/propagation/test_numerical.py:805`
  (serializer pair) and `:1189` (end-to-end metadata) update to the new token.
  `tests/test_public_surface.py:130` uses the default and needs no change.

**Reuse:** `_VALID_VELOCITY_REFERENCES`; the `NadirPointing` validation/metadata
pattern wholesale.

**You provide:** nothing.

**You run:** the per-chunk git rhythm.

**Verify:** `conda run -n propygator pytest tests/propagation/test_attitude.py tests/core -v`
green with **no JVM** (config construction stays on the safe-before-init surface);
`conda run -n propygator python -c "import propygator, jpype; print(jpype.isJVMStarted())"`
→ `False`.

---

## Chunk 3 — Provider lowering + live tests (JVM-touching; the de-risk item)

**Goal:** the `ecef` branch inside `_to_provider`, proven **inside a real
`propagate()`** — the primary slot has never hosted the custom provider (contract:
*Provider lowering*, *Failure mode*, *Sphere interaction*).

**Create / edit:**
- `src/propygator/propagation/attitude.py`, the `_to_provider` `InPlaneTracking`
  branch: primary target = `PredefinedTarget.VELOCITY` (`inertial`) or
  `_build_ecef_velocity_target_provider()` (`ecef`); secondary stays
  `PredefinedTarget.MOMENTUM`. **Rewrite the branch comment** ("velocity ⊥ momentum so
  both hold" is now `inertial`-only; `ecef` is exact-primary / best-effort-secondary)
  and extend the module docstring's native-providers note.
- **Tests** (`tests/propagation/test_attitude_providers.py`, `orekit` fixture —
  scheduled last by the conftest hook):
  - `ecef` lowers to a working provider (mirror `:153-157`); add
    `InPlaneTracking(velocity_reference="ecef")` to the all-modes lowering list
    (`:116`).
  - **The physical axis test** (mirror `test_nadir_ecef_yaws_off_inertial_by_earth_rotation`,
    `:167-191`): on a polar-ish circular LEO at several epochs, independently compute
    `v̂_rel` off the EME2000→ITRF transform and assert **body +Y (`ecef`) lands on
    `v̂_rel` to < 1e-6°** (primary exact); **+Z sits off `ĥ` by exactly
    `asin(|ĥ·v̂_rel|)`** (the contract's residual formula); the `ecef`-vs-`inertial`
    +Y split equals `angle(v, v_rel)` (~3–4° at an equator crossing, ~0 over the
    poles).
- **Tests** (`tests/propagation/test_numerical.py`, `orekit` fixture):
  - **The de-risk propagation test (contract requirement):** a box +
    `InPlaneTracking(velocity_reference="ecef")` runs end-to-end through a real
    `propagate_numerical` — the `@JImplements` default-method traps only surface in
    the real call path — and records `metadata["attitude"] == "in_plane_tracking:vel=ecef"`
    (mirror `:1168-1189`'s shape).
  - **The failure-mode test (new — no nadir twin exists to mirror):** a
    ground-relative-stationary orbit (GEO-ish radius) + `ecef` raises
    `NumericalPropagationError` (the contract's *Failure mode*; features.md row).
    Keep it one tight case.
  - **Regression:** the existing default-`InPlaneTracking` tests (`:718-730`,
    `:1168-1189`) stay green with no behavioral change beyond the metadata token.
  - *(Cheap, optional)* parametrize the sphere warn-and-fall-back test (`:876-894`)
    with `InPlaneTracking(velocity_reference="ecef")` — the contract says unchanged.

**Reuse:** `_build_ecef_velocity_target_provider` **verbatim**; the nadir-ecef test
scaffolding (`_body_axis_in_inertial`, the ITRF-transform reference computation).

**You provide:** nothing.

**You run:** the per-chunk git rhythm.

**Verify:** `conda run -n propygator pytest tests/propagation -v` green; the physical
assertions hold; the default path is regression-clean.

> ### ✅ Checkpoint B — runtime built
> 1. `ecef` `InPlaneTracking` constructs, lowers, and propagates per the contract.
> 2. `/code-review` + `/simplify` on the Chunks 2–3 diff.
> 3. Commit + push.

---

## Chunk 4 — Wrap-up: evidence refresh, docs reconciliation, sweep, merge (no tag)

**Goal:** land the upgrade — the shipped mode confirmed against the Chunk-1 stand-in,
the contract's *Supercessions* folded back, clean sweep, merge to `main`. **No version
bump, no tag.**

**Create / edit / run:**
- **Evidence refresh (the cross-check):** re-run the Chunk-1 study's feathered leg
  with the real `InPlaneTracking(velocity_reference="ecef")` in place of the
  `CustomAttitude` stand-in; confirm the two agree (up to the stand-in's hardcoded-ω⊕
  pole offset) and refresh the committed figure/results — **the number the docs quote
  must come from the shipped mode.**
- Full local CI parity: `conda run -n propygator pytest` and
  `conda run -n propygator pre-commit run --all-files` green from repo root.
- `/code-review` + `/simplify` final pass across the whole diff.
- **Reconcile the docs** (the contract's *Supercessions* list — exactly those spots):
  - `features.md` §1.1 — the `InPlaneTracking` dataclass + docstring scoping; the
    native-provider mapping row; the failure-modes row (extend the nadir-ecef
    `v_rel ≈ 0` row); the metadata grammar; **the "When `BoxFaceCd` matters" caveat
    paragraph** (`features.md:415` — retire "possible future upgrade", re-frame the
    ~2× as the `inertial`-reference figure, cite the study's `ecef` result).
  - `src/propygator/propagation/spacecraft.py` — the same caveat in the `BoxFaceCd`
    docstring (`:492-500`), updated identically.
  - `architecture.md` §13 — the "Attitude family" resolved note.
  - `README.md` — check the one attitude mention (`:174`); likely a no-op.
  - **Leave `general-upgrades-1.md` in place** (alive for any remaining upgrades);
    its section is now "built".
  - **You** update `CHANGELOG.md` `[Unreleased]` and refresh `CLAUDE.md` "Project
    state" (the narrative artifacts are yours).
- **Merge:** `gh pr create` against `main`, CI green, `gh pr merge --squash
  --delete-branch` — **your call**. This plan then retires to `docs/history/`.

**You provide:** the study re-run; CHANGELOG + CLAUDE.md edits; the merge go-ahead.

**Verify:** full `pytest` + `pre-commit run --all-files` green; `pyproject.toml`
version **unchanged**; the *Supercessions* spots all carried; `import propygator`
stays JVM-free.

---

## End-state verification (shipped → on `main`, untagged)

1. **Evidence:** the feathered-sail study (AoA / CdA / along-track divergence, both
   scenarios if run) is committed, final figures produced by the **shipped** mode; the
   GO decision recorded at Checkpoint A.
2. **Config:** `InPlaneTracking(velocity_reference=…)` constructs/validates JVM-free;
   a bad value raises `ValueError`; the default is bit-identical (native provider).
3. **Runtime:** `ecef` propagates end-to-end (the primary-slot custom provider proven
   in the real call path); +Y on `v̂_rel` to < 1e-6°; +Z residual matches
   `asin(|ĥ·v̂_rel|)`; ground-stationary + `ecef` → `NumericalPropagationError`.
4. **Metadata:** `in_plane_tracking:vel=<ref>` everywhere, tests updated.
5. **Docs:** the *Supercessions* map carried into `features.md` / `architecture.md` /
   the `BoxFaceCd` docstring; both Tier B-era caveat spots retired; CHANGELOG +
   CLAUDE.md updated; **version unchanged / untagged**.
6. `conda run -n propygator python -c "import propygator, jpype; print(jpype.isJVMStarted())"` → `False`.

## Notes / deferred (not this plan)

- **`LofOffset`-ecef** (a plate at controlled incidence to the true flow) — the named
  follow-on; the contract's *Out of scope* carries its implementation note (the
  rotated-axes trick, no wrapper provider needed).
- **`SunPointing` `phasing_reference="velocity_ecef"`** — API symmetry only, no
  physics case.
- **Attitude-rate fidelity** under the zero-derivative trick — out of scope; v1
  zeroes attitude rates by design (contract: *Attitude rates*).
- **v0.5.0 tag** — the separate cross-upgrade step once all general upgrades land.
