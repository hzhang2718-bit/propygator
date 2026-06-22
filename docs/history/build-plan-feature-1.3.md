# Build plan: Feature 1.3 — TLE propagator

> **Status: BUILD PLAN (not started).** Sequenced, session-sized chunks for the SGP4/SDP4
> TLE propagator, modeled on `docs/history/build-plan-feature-1.1.md`. The binding contract
> is `docs/features.md` §1.3; the prerequisite/scoping notes are
> `docs/build-plan-feature-1.3,4-notes.md`. Chunk-completion headers and the CHANGELOG are
> the maintainer's to author (trust the git log for true status).

## Context

Feature 1.1 (numerical propagator) plus both addenda are shipped; `main`/HEAD is
`v0.2.0`, 615 tests pass, and the whole 1.1 output surface (`Trajectory`, the `plot_*`
verbs, `export_csv`/`export_all`) is built and re-exported. **Feature 1.3, the SGP4/SDP4
TLE propagator, is the next feature** (architecture §12 order: 1.3 → 1.4 → 1.5 → 1.2).
It is "the simple feature": it reuses 1.1's `Trajectory`, plotting stack, and exporters
wholesale — only the propagation core (Orekit's `TLEPropagator`) and the native output
frame (TEME) differ.

The end state is a *usable* feature: a user can build a `TLE` (from pasted strings, a
NORAD id, or `fetch_tle("ISS")`), call `propagate_tle(...)`, get a `Trajectory` in TEME,
and run the full 1.1 plot + CSV output surface on it — exactly as shown in
`docs/features.md` §1.3 and `README.md`.

**Why this needs a plan (not just "implement §1.3").** §1.3 reads as "reuse 1.1
wholesale," but three prerequisites must exist before `propagate_tle` can be called at
all, plus two genuine edits to "reused" code. The plan sequences them:
- the **`TLE` core type** does not exist (`tle/` is a bare `__init__.py`);
- the shared **output-sample grid** lives inside 1.1's monolithic `_validate_inputs` and
  must be **promoted to `core/sampling.py`** (the dependency rule forbids `tle/` importing
  `propagation/`);
- the **fetch infrastructure** (`fetch_tle`, `from_norad_id`, the name→NORAD registry,
  the cache) is new and shared with Feature 1.4;
- an **`Epoch`−`Epoch` difference** helper is missing (the stale-TLE warning needs it);
- the **`mean_anomaly` CSV token** is a real, small addition to `io/exports.py`.

## Source-of-truth documents (do not silently diverge)

- **`docs/features.md` §1.3** — the binding contract: the `propagate_tle` signature,
  frame handling, failure modes, metadata grammar, the `from_state_unfitted` row→TLE
  utility, the `mean_anomaly` token, and the testing/reference cases. Most important file.
- **`docs/build-plan-feature-1.3,4-notes.md`** — the pre-build-plan notes (Notes 1–5 +
  "Also fold in"). Every prerequisite and DECIDED item below traces to it. Not a contract;
  it changes no signature.
- **`docs/architecture.md`** — §6 (`TLE`, `TrajectoryMetadata`, `KeplerianElements`),
  §7 (module tree + dependency rule + the sanctioned lazy-import exception), §8 (1.3 data
  flow), §10 (caching TTLs, explicit frames, safe-before-init, Orekit-types-internal),
  §11 (testing), §12 (build order).
- `docs/history/build-plan-feature-1.1.md` — the model for this plan's **style** (git
  walkthrough, per-chunk template, inline checkpoints). Also the reference for how the
  reused output surface is shaped.
- `docs/orekit_setup_reference.md` — JVM boundary patterns. **Self-flagged stale; verify
  against the installed 13.1.x API** before trusting any snippet.

## Decisions locked with the maintainer for this build

- **Git:** one feature branch `feature/tle-propagator`, single squash-PR into `main` at
  the end (GitHub Flow, project_meta §3). Abbreviated walkthrough below; the full
  end-to-end tutorial is in `docs/history/build-plan-feature-1.1.md`.
- **TLE parsing home — Option (a).** The `TLE` dataclass and its **pure-Python**
  parse/checksum live in a new **`core/tle.py`**; `from_state_unfitted` leans on **Orekit's**
  `TLE(...)` formatting + checksum (it is already JVM-touching); **no separate
  `tle/parsing.py`** is built. Rationale: keeps the inward dependency rule pure (no
  `core→tle` edge), `from_strings`' checksum must be pure-Python/safe-before-init anyway, and
  Orekit's formatter avoids reimplementing the TLE fixed-column foot-guns. The §7 tree's
  `tle/parsing.py` line is the only thing pointing the other way; the wrap-up (Chunk 9)
  reconciles the tree (`core/tle.py` in, `tle/parsing.py` out).
- **Fetch infrastructure — in scope for 1.3.** Build `core/catalogs.py` (name→NORAD
  registry), `tle/sources.py` (CelesTrak fetch + `~/.propygator/cache/` TTLs), `fetch_tle`,
  and `TLE.from_norad_id` here, so 1.3 is usable straight from the README. **CelesTrak
  only** (Note 3 DECIDED); `"auto"`/Space-Track stay deferred, the `source` param stays for
  forward-compat with `"celestrak"` its only valid value.

**Explicitly OUT of scope for 1.3** (do not build here):
- The **sky view** — `look_angles` / `AzElRange` (`core/observation.py`) and
  `plot_sky_track` / `_draw_sky_track` (`plotting/trajectories.py`) — **relocated to
  Feature 1.4** (Note 4 / features §1.3, §1.4). `propagate_tle`'s signature is unaffected.
- `fit_tle` (Feature 1.2, the faithful sibling of `from_state_unfitted`).
- The standard-magnitude table in `core/catalogs.py` (Feature 1.5) — 1.3 adds only the
  name→NORAD registry to that file.
- Space-Track / `"auto"` source; backward propagation before epoch; a configurable or
  period-relative stale-threshold / `output_step` default (all §1.3 "still open / deferred").

## Architecture invariants to honor in every chunk (CLAUDE.md / architecture §4, §10)

Orekit types stay internal (public APIs accept/return only propygator types; `to_orekit()`
annotates the Orekit return only under `if TYPE_CHECKING:`); import
`jpype`/`orekit_jpype`/`pyhelpers` **lazily inside functions**, never at module top; SI
internally; **frames explicit** (TEME out of `propagate_tle`, no silent conversion);
`pathlib.Path` everywhere; `logging`, never `print`; frozen dataclasses with
`__post_init__` validation. **One-JVM-per-process test ordering:** every JVM-touching test
acquires the JVM via the `orekit` fixture so `conftest.py`'s hook schedules it after the
pure-Python `tests/core/*` "no JVM started" guards.

## How to use this plan

- **9 numbered chunks (Chunk 0 = branch setup)**, each sized for one Claude Code session
  and independently verifiable. Run in order — later chunks depend on earlier ones.
- Each chunk lists **Goal / Create-edit / Reuse / You provide / Verify**. **You provide**
  is called out every chunk (often "nothing") so you know whether a session needs input.
- **Checkpoints** (CLAUDE.md refresh + `/code-review` + `/simplify`) are marked inline
  after the chunks where they pay off — the moments to consolidate before the next layer.
- Adjacent small chunks (e.g. 6+7, or 3+4 if a session has capacity) can be merged —
  they're split for safety, not because they must be separate.
- **Per-chunk git rhythm** (the "You run" for every chunk): `git add -A` →
  `git commit -m "Feature 1.3 chunk N: <summary>"` → `git push` (CI runs on the branch).
  Commit at the end of each chunk or more often.
- **New test subpackage:** Chunk 3 is the first to touch `tle/`, so it must create
  `tests/tle/__init__.py` or `pytest tests/tle` collects nothing (the existing
  `tests/{core,io,plotting,propagation}/__init__.py` are the precedent).

---

## Git: the feature-branch walkthrough (read once, before Chunk 1)

You've run this flow for 1.1 and both addenda, so this is the short form (the full
tutorial is in `docs/history/build-plan-feature-1.1.md`).

**One-time, before Chunk 1:**
```powershell
conda activate propygator
git switch main
git pull
git switch -c feature/tle-propagator
git push -u origin feature/tle-propagator
```

**At the very end (Chunk 9):**
```powershell
gh pr create --base main --head feature/tle-propagator `
  --title "Feature 1.3: TLE propagator" --body "..."
# CI green on the PR, then:
gh pr merge --squash --delete-branch
git switch main; git pull
git tag v0.3.0      # you author the release + CHANGELOG (your standing convention)
git push --tags
```

**You provide (git):** `gh` installed + authenticated before Chunk 9 (only needed at the
end). Per the maintainer's standing preference, **Claude will not commit, push, open the PR,
write the CHANGELOG, or tag the release without being asked** — those narrative/outward
actions are the maintainer's; on request Claude will run the add/commit/push for a chunk.

---

## Chunk 0 — Branch setup - Done

**Goal:** start the feature line and commit this plan as its first commit.

**Create-edit:** do the one-time git branch setup above; commit this
`docs/build-plan-feature-1.3.md` on `feature/tle-propagator` as the first commit.

**You provide:** confirmation to start (and that Claude may drive git, if desired).

**Verify:** `git branch` shows `* feature/tle-propagator`; the plan is committed; CI runs.

---

## Chunk 1 — Promote the shared output-sample grid to `core/sampling.py` - Done

**Goal:** extract the propagator-agnostic sampling contract out of 1.1's monolithic
`_validate_inputs` so both `propagate_numerical` and (Chunk 3) `propagate_tle` share **one**
grid + cap and produce identically-gridded trajectories — the dependency rule forbids
`tle/` importing `propagation/` (Note "Sample-count reuse — DECIDED #7"; architecture §7).

**Create-edit:**
- New `src/propygator/core/sampling.py`. Move **verbatim** from
  `propagation/numerical.py`: `_MAX_OUTPUT_SAMPLES` (10,000,000) and its generalized
  comment, `_SAMPLE_COUNT_TOL` (1e-9), and `_sample_count(duration, output_step)`
  (`numerical.py:113,120,135`). Add two small helpers:
  - `_validate_sampling(duration, output_step) -> int` — the **shared pre-flight**: the
    finite/positive `duration`, finite/positive `output_step`, and `output_step <= duration`
    checks (lifted from `numerical.py:228–238`), then the sample-count **cap** check raising
    the already-pre-generalized canonical message (`numerical.py:271–278`, the
    `"...{n} output samples...one propagator evaluation..."` text — preserve the
    `"output samples"` substring). Returns `n_samples`.
  - `_output_offsets(n_samples, output_step) -> list[float]` — the on-grid offsets
    `[k * output_step for k in range(n_samples)]` (the grid 1.1 builds at
    `numerical.py:1063`), so both propagators generate the grid in one place. (Epochs are
    built per-propagator via `start.shifted_by(offset)`, already pure-Python.)
- Refactor `propagation/numerical.py`: delete the moved constants/`_sample_count`, import
  them from `..core.sampling`, and rewrite `_validate_inputs` to call `_validate_sampling`
  for the positive/ordered/cap subset while **keeping the numerical-only checks in place**
  (inertial-frame rule, integrator type + `ClassicalRK4` fixed-step coupling, gravity-field
  name, atmosphere-model name). Keep `_realized_sample_count` in `numerical.py` (1.3 has no
  stop-and-report, so it does not move).
- New `tests/core/test_sampling.py` (pure-Python, safe-before-init): the
  `floor(d/step + tol) + 1` formula incl. the divisible-case determinism; the three
  pre-flight `ValueError`s; the cap `ValueError` (`match="output samples"`); `_output_offsets`
  shape/values.

**Reuse:** the exact code already exists in `numerical.py`; this is a move + re-import, not
new logic.

**You provide:** nothing.

**Verify:** `pytest tests/core/test_sampling.py` green; **the full numerical suite stays
green** — `pytest tests/propagation/test_numerical.py` (the `match="output samples"` pin at
`:174` must still pass). **Watch the cross-error ordering:** bundling positive/ordered+cap
into `_validate_sampling` and calling it right after the inertial-frame check moves the cap
ahead of the integrator/gravity/atmosphere name checks; the pinned messages are
independent, but run the suite and confirm no test asserts which error wins when two inputs
are simultaneously wrong. `import propygator` must still not start the JVM.

---

## Chunk 2 — The `TLE` core type (`core/tle.py`) - Done

**Goal:** the type everything in §1.3 takes. Pure-Python construction + parse + checksum
(safe-before-init), with a JVM-only `to_orekit()` (Note 1; architecture §6).

**Create-edit:**
- New `src/propygator/core/tle.py` — `@dataclass(frozen=True) class TLE` with `line1`,
  `line2`, `name=None`:
  - `__post_init__` — cheap structural validation only (two 69-char lines; line-number
    digits 1/2). Pure-Python.
  - `from_strings(cls, line1, line2, name=None)` — parse + **mod-10 checksum validation**
    (each line's column-69 digit vs the summed digits, `-`=1); raise `ValueError` with an
    actionable message on a bad checksum/format, so `propagate_tle` always receives a valid
    TLE (architecture §10). Strictly two lines + optional `name`; the fetch path (Chunk 7)
    splits a 3-line CelesTrak block and passes line-0 as `name=`. **Safe-before-init.**
  - `epoch` property — **pure-Python** parse of line-1 cols 19–32 (2-digit year with the
    57–99→19xx / 00–56→20xx pivot + fractional day → UTC `datetime` → `Epoch.from_datetime`,
    `TimeScale.UTC`). Must be JVM-free: Chunk 3's stale-TLE pre-flight and `start=tle.epoch`
    default run *before* `_ensure_started()` (Note "Stale-TLE warn-once"). **Safe-before-init.**
  - `norad_id` property — pure-Python parse (line-1 cols 3–7) → `int`. **Safe-before-init.**
  - `to_orekit()` — lazy bootstrap (`_ensure_started()` then
    `from org.orekit.propagation.analytical.tle import TLE as OrekitTLE`;
    `OrekitTLE(line1, line2)`), `if TYPE_CHECKING:` annotation
    (`-> "org.orekit.propagation.analytical.tle.TLE"`), same pattern as `Epoch.to_orekit`.
    JVM-touching.
  - `from_norad_id` / `from_state_unfitted` are **not** added here — they land in Chunks 7
    and 8 (both edits to this file).
- Re-export `TLE` from the top-level `src/propygator/__init__.py` (`__all__` + import).
- `tests/core/test_tle.py` (pure-Python, safe-before-init, **no `orekit` fixture**):
  `from_strings` parses a known fixed ISS TLE; a corrupted checksum digit raises
  `ValueError`; malformed lines raise; `.norad_id` correct; `.epoch` matches the known ISS
  epoch to the second; bare `TLE(line1, line2)` construction works without starting the JVM
  (it sits in the `tests/core` "no JVM started" suite). Plus one JVM test **in a
  fixture-gated file** (e.g. `tests/test_conversions.py` or `tests/tle/`, Chunk 3) for
  `to_orekit()` round-trip (`getLine1()/getLine2()` echo the inputs).

**Reuse:** `Epoch.to_orekit` / `State.to_orekit` (the lazy + `TYPE_CHECKING` pattern);
`Epoch.from_datetime` (`time.py:275`) for the pure-Python epoch.

**You provide:** a known-good fixed ISS TLE (line1/line2) for the tests, or confirm Claude
may use a public ISS TLE checked into the test as a fixture.

**Verify:** `pytest tests/core/test_tle.py` green; the `tests/core` suite still asserts no
JVM started; `import propygator; propygator.TLE` resolves with the JVM down.

---

## Chunk 3 — `propagate_tle` + the `Epoch` difference helper (`tle/propagator.py`) - Done

**Goal:** the headline verb — SGP4/SDP4 propagation to a TEME `Trajectory`, with the
propygator-side pre-flight (shared sampling checks + stale-TLE warn-once) and the metadata
block. Get the feature *working* from `TLE.from_strings`.

**Create-edit:**
- `src/propygator/core/time.py` — add `Epoch.seconds_since(self, other: "Epoch") -> float`
  (signed seconds from `other` to `self`, from the two-part TAI count; pure-Python,
  safe-before-init). Recommended name `seconds_since` over `__sub__` (explicit; avoids a
  bare-float subtraction surprise; mirrors Orekit's `durationFrom` direction). Small test in
  `tests/core/test_time.py`: `e.shifted_by(x).seconds_since(e) == x`; antisymmetry.
- New `src/propygator/tle/propagator.py` — `propagate_tle(tle, duration, *, output_step,
  start=None, name=None) -> Trajectory` (the **exact** §1.3 signature: `duration`
  positional-or-keyword, `output_step` required kw-only, no defaults beyond `start`/`name`):
  1. **Pre-flight (pure-Python, before any JVM):** `start = start if start is not None else
     tle.epoch`; `n_samples = _validate_sampling(duration, output_step)` (core/sampling);
     `resolved_name = name if name is not None else tle.name`. **Stale-TLE warn-once:**
     `age = max(abs(start.seconds_since(tle.epoch)), abs(start.shifted_by(duration).seconds_since(tle.epoch)))`;
     if `age > 30 * 86400` emit a single `warnings.warn` (both ends, because `start` may
     precede `tle.epoch`; §1.3 "Stale-TLE warning"). Never raises.
  2. **JVM section:** `_ensure_started()`; lazy `import jpype` +
     `from org.orekit.propagation.analytical.tle import TLEPropagator`;
     `propagator = TLEPropagator.selectExtrapolator(tle.to_orekit())` (auto near-Earth vs
     deep-space, no user knob); `teme = Frame.TEME.to_orekit()`;
     `start_date = start.to_orekit()`. For each `offset` in `_output_offsets(n_samples,
     output_step)`: `pv = propagator.propagate(start_date.shiftedBy(offset)).getPVCoordinates(teme)`
     → fill `positions`/`velocities` via getters; `epochs.append(start.shifted_by(offset))`.
     **Pin the frame explicitly** by requesting PV in `teme` (don't rely on the propagator's
     implicit frame). Wrap the propagate loop in `try/except jpype.JException` → capture
     `getMessage()` and raise `TLEPropagationError(f"TLE propagation failed: {msg}")` from
     `None` (no `partial_trajectory` — SGP4 never stops-and-reports; §1.3 "No stop-and-report").
  3. **Assemble:** `Trajectory.from_arrays(epochs, positions, velocities, Frame.TEME,
     metadata=metadata)`.
  4. **Metadata** — a local `_build_sgp4_metadata(...)` mirroring `numerical._build_metadata`
     but simpler: `propygator_version=_propygator_version()` (core/states),
     `orekit_version=_orekit_version()` (from `..._orekit_init`), `propagator="sgp4"`,
     `tle_line1`/`tle_line2`, `norad_id=tle.norad_id` (int), `output_step_s=float(output_step)`,
     `created_at=datetime.now(timezone.utc).isoformat()`, and `name=resolved_name` **only if
     not None**. **UTC-force the epoch keys** — `tle_epoch=tle.epoch.in_scale(TimeScale.UTC).to_iso()`
     and `start=start.in_scale(TimeScale.UTC).to_iso()` (Note "Metadata timestamps must be
     forced to UTC"; `to_iso()` emits no zone suffix, so never hand it a TT/TAI epoch). No
     `force_models`/`integrator`/`termination_*` keys.
- Re-export `propagate_tle` from the top-level `__init__.py`.
- Create `tests/tle/__init__.py`. `tests/tle/test_propagator.py` (`orekit` fixture):
  argument `ValueError`s (duration ≤ 0, output_step ≤ 0, output_step > duration); the shared
  **cap** raise on this path (`match="output samples"`); **sample-count contract** — the grid
  matches `floor(duration/output_step + tol) + 1`, first sample at `start`, and is identical
  to `propagate_numerical`'s grid for the same `duration`/`output_step`; returned
  `Trajectory.frame is Frame.TEME`; metadata keys present, `propagator == "sgp4"`, epoch
  keys carry the UTC instant; **stale-TLE** `pytest.warns` past 30 days (and *no* warning
  inside 30 days, both ends).

**Reuse:** `core/sampling` (Chunk 1); `numerical.py`'s assembly skeleton
(`_ensure_started` → loop → `Trajectory.from_arrays` → metadata) at `numerical.py:945–1147`,
minus all guards/ephemeris-recovery; `TLEPropagationError` already in `core/exceptions.py`
(just raise it); `_orekit_version`/`_propygator_version` already exist.

**You provide:** confirm `seconds_since` as the `Epoch` API name (vs `__sub__`).

**Verify:** `pytest tests/tle/test_propagator.py` green; a manual `conda run` script —
`propagate_tle(TLE.from_strings(L1, L2), 86400, output_step=60)` returns a ~1441-sample TEME
`Trajectory`. `import propygator` still JVM-free.

> **Checkpoint after Chunk 4** (the verb + its correctness proof land together).

---

## Chunk 4 — SGP4/SDP4 implementation-agreement + decay error path - Done

**Goal:** prove `propagate_tle` reproduces the reference SGP4/SDP4 algorithm on both
branches, and that a decay surfaces cleanly as `TLEPropagationError` (§1.3 "Testing").

**Create-edit:**
- `tests/tle/test_sgp4_agreement.py` (`orekit` fixture): compare `propagate_tle` output to
  **published Vallado SGP4 test vectors** (the *Revisiting Spacetrack Report #3* / AIAA
  2006-6753 cases) at sampled times, **in the native TEME frame** (no TEME→EME2000
  conversion — that injects EOP differences that blow the centimetre budget), to
  centimetre agreement. Cover **both branches**: ≥1 near-Earth (SGP4, period < 225 min) and
  ≥1 deep-space (SDP4, e.g. a Molniya-type case such as 08195 / 04632 — verify the catalog
  number against the published case list), exercising `selectExtrapolator`'s automatic pick.
- `tests/tle/test_propagator.py` (additions): a **decayed** TLE propagated past decay raises
  `TLEPropagationError` (carrying a message string, no Java trace; assert no
  `partial_trajectory` attribute). Best-effort sourcing — see "You provide".

**Reuse:** the `orekit` fixture; the cm-comparison idiom from the existing Vallado-vector
tests for `propagate_numerical` (mirror their tolerance/assertion style).

**You provide:** the reference Vallado vectors for one near-Earth + one deep-space case
(line1/line2 + expected TEME position/velocity at given times), **or** confirm Claude may
extract them from Orekit's bundled SGP4 test data / transcribe the published AIAA report
cases. For the decay test, a known-decayed TLE, or confirm Claude may synthesize/borrow one
(mark `xfail`-tolerant if a clean decay is hard to source).

**Verify:** both-branch agreement tests pass to cm; the decay test raises the right type.

> **Checkpoint — Chunk 4.** Refresh CLAUDE.md "Project state" (propagate_tle + TLE type +
> core/sampling.py landed; tle/ no longer a stub). Run `/code-review` then `/simplify` on
> the branch diff; address findings. This is the consolidation point before the additive
> output/fetch/utility layers.

---

## Chunk 5 — Output reuse + the `mean_anomaly` CSV token - Done

**Goal:** confirm 1.1's output stack consumes a TEME `Trajectory` unchanged, and add the one
genuine "reused" edit §1.3 calls out — the `mean_anomaly` CSV token (§1.3 "CSV export edits
still needed").

**Create-edit:**
- `src/propygator/io/exports.py` — register `"mean_anomaly"` as a new additive group:
  add `_build_mean_anomaly_columns(traj) -> {"mean_anomaly_deg": ...}` (per-row
  `KeplerianElements.mean_anomaly()` in degrees; computed in EME2000 like the `keplerian`
  group, though M depends only on e and ν so the frame is immaterial); add it to
  `_OPTIONAL_GROUPS` (`exports.py:148`); insert `"mean_anomaly"` into `_GROUP_ORDER` between
  `keplerian` and `sun` → `("keplerian", "mean_anomaly", "sun")` (`exports.py:155`). **Keep
  it separate from the `keplerian` token** so that token's pinned six-column set and 1.1's
  CSV snapshots stay byte-stable. No change to the 16-column default; no propagator branch.
- `tests/io/test_exports.py` (additions): a **CSV snapshot** for a fixed ISS TLE +
  `columns=["keplerian", "mean_anomaly"]`, pinning the EME2000 element frame and the
  `keplerian, mean_anomaly, sun` column order; assert the 16-default and `["keplerian"]`-only
  snapshots are **unchanged** (byte-stable).
- `tests/tle/test_outputs.py` (`orekit` fixture): **ISS end-to-end** — a fixed ISS TLE →
  `propagate_tle` → `plot_summary` and `export_all` produce figures + a CSV with the 16
  default columns, confirming the stack consumes a TEME-framed trajectory unchanged.
- **Verify-only (Note 5, expected no code change):** `plot_3d` already gates the coastline on
  `frame is Frame.ITRF` (`plotting/trajectories.py:514`), so `plot_3d(frame=Frame.TEME)` —
  an ECI frame — correctly draws **no** coastline and warns. Add a small assertion that
  `plot_3d` of a TEME trajectory takes the no-coastline branch; touch the gate only if it
  somehow keys on `not EME2000` rather than `is ITRF`.
- **Docs:** fold the temporary §1.3 "CSV export edits still needed" note into features §1.1
  "CSV columns" (document `mean_anomaly` as a first-class token) and delete the temporary
  section (the note instructs this).

**Reuse:** `_OPTIONAL_GROUPS`/`_GROUP_ORDER` machinery + the `keplerian`/`sun` builders as
the template; `KeplerianElements.mean_anomaly()` (`elements.py:106`); the entire 1.1 plot +
export surface (no new plotting code).

**You provide:** nothing (reuses the Chunk 2 ISS fixture).

**Verify:** `pytest tests/io tests/tle/test_outputs.py` green; 1.1's existing CSV snapshots
unchanged; `plot_3d(frame=Frame.TEME)` draws no coastline.

---

## Chunk 6 — Popular-satellite registry (`core/catalogs.py`) - Done

**Goal:** the friendly-name → NORAD-id resolution that `fetch_tle("ISS")` / `from_norad_id`
ride on (architecture §3, §7). Reference data, no I/O, imports no sibling subpackage.

**Create-edit:**
- New `src/propygator/core/catalogs.py` — a pure-Python registry mapping friendly names
  (e.g. `"ISS"`, `"HST"`, `"TIANGONG"`) → NORAD id, **each entry carrying an in-source
  citation** for its catalog number (architecture §3: "untraceable 'looks about right'
  values are not acceptable"). Add `_resolve_norad_id(name_or_id) -> int` (name → id via the
  registry, case-folded; a bare int / numeric string passes through; unknown name → a clear
  `ValueError` listing how to pass a raw id). **Magnitude table is NOT built here** (Feature
  1.5) — only the name→NORAD registry.
- `tests/core/test_catalogs.py` (pure-Python): known names resolve; pass-through ids;
  unknown name raises with an actionable message; case-insensitive lookup.

**Reuse:** nothing structural — this is new reference data; follow the §3 citation rule.

**You provide:** the initial satellite list (which friendly names to ship) + a citation
source for each NORAD id (CelesTrak / Heavens-Above / Space-Track), **or** confirm Claude may
seed a small set (ISS/HST/a few well-known LEO+GEO) with CelesTrak citations for you to edit.

**Verify:** `pytest tests/core/test_catalogs.py` green; `import propygator` still JVM-free;
`core/catalogs.py` imports nothing from `tle/`/`tracking/`/`propagation/`.

---

## Chunk 7 — CelesTrak fetch + cache + `TLE.from_norad_id` (`tle/sources.py`) - Done

**Goal:** the network fetch path that makes `fetch_tle("ISS")` and `TLE.from_norad_id(...)`
work, with the two-TTL on-disk cache (architecture §10; Note 3).

**Create-edit:**
- New `src/propygator/tle/sources.py`:
  - `fetch_celestrak(norad_id, *, use_cache=True, ttl_s=...) -> str` — GET CelesTrak's gp.php
    (`CATNR=<id>&FORMAT=tle`) via `requests`; return the raw 3-line TLE text. Lazy-import
    `requests` inside the function.
  - `fetch_tle(name_or_id, source="celestrak", *, use_cache=True) -> TLE` — `source !=
    "celestrak"` raises `ValueError` (`"auto"`/Space-Track deferred, param kept for
    forward-compat); resolve via `core.catalogs._resolve_norad_id`; fetch; **split the 3-line
    block** into (line0/name, line1, line2); return `TLE.from_strings(line1, line2,
    name=line0.strip())` so `tle.name` is populated for the §1.3 name-fallback. JVM-free
    (network + pure-Python parse only).
  - **Cache:** `~/.propygator/cache/` keyed by NORAD id, two TTLs — **6 h** (realtime
    workflows, consumed by 1.4) and **24 h** (general; the default `fetch_tle` uses). A cache
    helper reads a fresh entry within TTL, else re-fetches and rewrites; `use_cache=False`
    bypasses both read and write. Wire it into the existing top-level `clear_cache()`.
- `src/propygator/core/tle.py` — add `TLE.from_norad_id(cls, norad_id, source="celestrak")`
  delegating to `tle.sources.fetch_tle` (lazy import inside the classmethod — a
  classmethod-time `core→tle` *call* edge; acceptable as the chosen Option (a) keeps no
  *static* `core→tle` import, and `from_norad_id` is the network-touching, not
  safe-before-init, member per Note 1). **Alternatively** site the body in `tle/sources.py`
  and have the classmethod be a thin forwarder — pick whichever keeps the import graph
  cleanest at build time; flag the choice in the chunk's review.
- Re-export `fetch_tle` from the top-level `__init__.py`.
- `tests/tle/test_sources.py` — **mock the HTTP layer** (monkeypatch `requests.get`): fetch
  returns a known TLE → correct `TLE` with `name` set; a second call within TTL is served
  from cache (no second HTTP call); past TTL re-fetches; `use_cache=False` always hits the
  (mocked) network; unknown `source` raises; `clear_cache()` empties the TLE cache. Use
  `tmp_path` / monkeypatch the cache dir so tests never touch the real `~/.propygator/`.

**Reuse:** `core.catalogs._resolve_norad_id` (Chunk 6); `TLE.from_strings` (Chunk 2); the
existing `clear_cache()` plumbing.

**You provide:** confirm tests **mock** CelesTrak (recommended — no live network in CI) vs a
live opt-in test; confirm the cache location (`~/.propygator/cache/`) and that 24 h is the
`fetch_tle` default TTL (6 h is reserved for 1.4's realtime path).

**Verify:** `pytest tests/tle/test_sources.py` green with no network; a manual
`fetch_tle("ISS")` (live, run by you) returns an ISS `TLE` with `name="ISS (ZARYA)"`.

> **Light checkpoint after Chunk 7** — the feature is now usable from the README
> (`fetch_tle` → `propagate_tle` → plots). Optional `/code-review` on the fetch layer.

---

## Chunk 8 — Row → TLE (`TLE.from_state_unfitted`) - Done

**Goal:** the format-valid (not round-trip-faithful) `State` → `TLE` utility (§1.3
"Row → TLE"; Note 2). JVM-touching; leans on Orekit for formatting + checksums (Decision a).

**Create-edit:**
- `src/propygator/core/tle.py` — add `from_state_unfitted(cls, state, *, norad_id=None,
  bstar=None, name=None) -> TLE`:
  - **Mechanics:** `el = state.to_frame(Frame.TEME).to_keplerian()` (osculating elements in
    TEME — a TLE lives in TEME); `M = el.mean_anomaly()` (ν→M, `elements.py:106`); derive the
    mean-motion field from `a` as `n = sqrt(mu / a**3)` using the **library WGS84 GM**
    (`Constants.WGS84_EARTH_MU`, the same Earth GM the rest of the library uses — pin this
    single source; the WGS84-vs-SGP4-WGS72 mismatch is documented non-faithfulness, not
    reconciled). Build via Orekit's `TLE(...)` constructor, read back
    `getLine1()/getLine2()` (correct fixed-column formatting + checksums), and return
    `cls.from_strings(line1, line2, name=name)` so the result is a validated propygator `TLE`.
  - **Pinned non-physical field defaults** (enumerate in the docstring — Note 2): NORAD id
    `norad_id or 0` (placeholder `00000`); `bstar or 0.0`; classification `U`; international
    designator placeholder; element-set number; revolution number at epoch; ephemeris type
    `0`; mean-motion 1st & 2nd derivatives `0.0` (not recoverable from one state, same
    rationale as B*).
  - **Docstring** states the three non-faithfulness reasons loudly (mean vs osculating;
    B* not recoverable from a state; osculating values in mean-element slots + the
    WGS84/WGS72 constant offset) and the "family of slightly different TLEs across rows"
    artifact. JVM-touching — **not** added to the safe-before-init surface.
- `tests/tle/test_from_state_unfitted.py` (`orekit` fixture): the produced lines are
  format-valid (round-trip back through `TLE.from_strings` / `to_orekit()` with no checksum
  error); `norad_id`/`bstar` placeholders vs explicit values land in the right columns; two
  rows of one orbit yield **different** element sets (the osculating-wobble artifact). Need
  not round-trip under SGP4 (optionally assert divergence to document the gap).

**Reuse:** `State.to_frame`/`to_keplerian` (`states.py`), `KeplerianElements.mean_anomaly`,
`Frame.TEME`, Orekit `Constants.WGS84_EARTH_MU`.

**You provide:** confirm the µ source to pin (`Constants.WGS84_EARTH_MU`) and the
international-designator / element-set / rev-number placeholder values (or accept Claude's
sensible defaults).

**Verify:** `pytest tests/tle/test_from_state_unfitted.py` green; the result is a valid
propygator `TLE` whose lines Orekit re-parses without error.

---

## Chunk 9 — Wrap-up: docs reconciliation, CI parity, review, merge - Done

**Goal:** make the docs match the built reality, prove the whole suite + hooks are green,
and land the feature on `main`.

**Create-edit / actions:**
- **Docs reconciliation:**
  - `architecture.md` §7 module tree — add `core/tle.py` (the `TLE` type), update the
    `tle/` block (`propagator.py` built; `sources.py` built CelesTrak-only; **drop
    `parsing.py`**, folded into `core/tle.py` per Decision a), note `core/sampling.py` and
    `core/catalogs.py` (registry) as built.
  - `architecture.md` §10 safe-before-init list — confirm it names `TLE.from_strings` /
    bare construction / `.epoch` / `.norad_id` as safe-before-init and `from_state_unfitted`
    / `from_norad_id` / `to_orekit` as JVM/network-touching.
  - confirm the §1.3 temporary CSV note is folded into §1.1 (Chunk 5).
  - `CLAUDE.md` "Project state" — 1.3 built + re-exported (`propagate_tle`, `fetch_tle`,
    `TLE`); `tle/` and `core/catalogs.py`/`core/sampling.py` no longer stubs; note the
    sky-view/`look_angles`/`fit_tle` deferrals and that **1.4 is now next**.

- **Post-build add-on to reconcile — `TLEFetchError` (network-failure wrapping; added
  after Chunk 7).** A dedicated `TLEFetchError(PropygatorError)` now wraps `requests`
  transport failures (no network / DNS / connection-refused / timeout, and HTTP error
  statuses) raised inside `fetch_celestrak`, so an offline `fetch_tle("ISS")` surfaces one
  clean, actionable line (names the NORAD id + the offline `TLE.from_strings` escape hatch,
  chain suppressed via `from None`) instead of `requests`' ~70-line urllib3 traceback —
  the architecture §3 "no raw trace, message-only" rule, which the original Chunk-7 fetch
  path was the lone violator of (it let `requests` errors propagate). Built: the class in
  `core/exceptions.py` (direct `PropygatorError` subclass, beside `OrekitDataMissingError` /
  `JVMAlreadyStartedError`), re-exported at top level + `__all__`; the `try/except
  requests.exceptions.RequestException` wrap in `tle/sources.py`; tests
  (`tests/tle/test_sources.py`: HTTP-status + connection-error wraps, `__suppress_context__`
  asserted). **Reconcile in the docs:**
  - `architecture.md` §3 (TLE data sources) — note remote-fetch transport failures surface
    as `TLEFetchError` (consistent with the no-raw-trace rule); add it to any
    exception-hierarchy listing the docs carry.
  - `features.md` §1.3 — where `fetch_tle` / `from_norad_id` are described, record the
    fetch-failure behavior: a network/HTTP transport failure raises `TLEFetchError`; an
    id-not-found, malformed block, or unknown `source` raises `ValueError` (unchanged —
    those are not-found / input conditions, not transport failures).
  - `CLAUDE.md` "Project state" — mention `TLEFetchError` alongside the re-exported 1.3
    surface if the exception list there is enumerated.
- **CI parity:** full `conda run -n propygator pytest` green; `pre-commit run --all-files`
  green (ruff-check + ruff-format + mypy over `src`+`scripts` + nbstripout + hygiene).
- **Review:** `/code-review` then `/simplify` over the full branch diff; address findings.
- **Merge (maintainer triggers):** open the squash-PR, CI green, `gh pr merge --squash
  --delete-branch`, then `v0.3.0` tag + CHANGELOG (maintainer authors these).

**Reuse:** the Chunk-11 wrap-up rhythm of the drag-validity addendum (CI parity + review +
docs reconciliation) as the template.

**You provide:** `gh` authenticated; you drive the PR/merge/tag/CHANGELOG.

**Verify:** `pytest` + `pre-commit` both green on a clean tree; `import propygator` exposes
`propagate_tle`, `fetch_tle`, `TLE` and stays JVM-free; the README TLE example runs
end-to-end.

---

## End-to-end verification (the "usable feature" gate)

After Chunk 9, this must work in an activated env (`conda run -n propygator python`):

```python
import propygator as pgr
tle = pgr.fetch_tle("ISS")                       # CelesTrak + 24h cache; name populated
traj = pgr.propagate_tle(tle, 86400, output_step=60)   # TEME Trajectory, ~1441 samples
assert traj.frame is pgr.Frame.TEME
fig = pgr.plot_summary(traj)                     # 1.1 stack consumes TEME unchanged
pgr.export_all(traj, "iss")                      # summary PNG + 3D HTML + CSV
pgr.export_csv(traj, "iss.csv", columns=["keplerian", "mean_anomaly"])
# row -> format-valid TLE  (indexing a Trajectory returns the sample's State)
back = pgr.TLE.from_state_unfitted(traj[0], norad_id=25544)
```

Plus: `import propygator` does not start the JVM; the `tests/core/*` suite still asserts
"no JVM started"; both SGP4 branches agree with the Vallado vectors to cm in TEME; the
stale-TLE warning fires once past 30 days; a decay raises `TLEPropagationError`.

## Chunk dependency map

```
0 branch setup
1 core/sampling.py ───────────────┐
2 core/tle.py (TLE type) ──┐      │
3 propagate_tle + Epoch.seconds_since  (needs 1,2)
4 SGP4 agreement + decay   (needs 3)        ◀ Checkpoint
5 mean_anomaly token + output reuse (needs 3; token indep.)
6 core/catalogs.py ────────┐
7 fetch + cache + from_norad_id (needs 2,6) ◀ light checkpoint
8 from_state_unfitted      (needs 2)
9 wrap-up                  (needs all)      ◀ final review + merge
```
Mergeable if a session has capacity: 3+4, 6+7. Independent after Chunk 3: 5, 6/7, 8.
