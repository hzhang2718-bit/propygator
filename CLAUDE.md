# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

**propygator** is a Python library for orbital simulation and satellite tracking, built on [Orekit](https://www.orekit.org/) via the `orekit_jpype` wrapper.

**Build stage 1 (groundwork, `docs/history/build-plan-stage-1.md` Chunks 1–8) is complete, and Feature 1.1 (numerical propagator) is feature-complete** on branch `feature/numerical-propagator` (build plan, now archived: `docs/history/build-plan-feature-1.1.md`, 13 chunks; **Chunks 1–12 complete + verified, and Chunk 13's `/code-review` + `/simplify` polish is done too — only the PR + squash-merge into `main` is left, and it is intentionally deferred in favor of additional feature builds first**). The package is scaffolded, installable, and 549 tests pass. The whole Feature 1.1 surface (`propagate_numerical`, the config dataclasses, the `plot_*` verbs, `export_csv`/`export_all`) is implemented and re-exported at the top level; the merge is the user's call. What is built:

- **Lazy-JVM init** (`_orekit_init.py`) — `init()`, `clear_cache()`, orekit-data resolution, `_ensure_started()`.
- **The pure-Python core data model** (`core/`) — `Epoch`/`TimeScale`, `Frame`, `State`, `Trajectory`, `KeplerianElements`, `Orientation`, `GroundStation`/`GeodeticPosition`/`Pass`, exceptions. All construction + validation works with **no JVM** (the "safe before init" surface).
- **The entire Orekit-crossing conversion layer** (Feature 1.1 Chunks 1–3) — `Frame.to_orekit`, `State.to_orekit`/`to_frame`/`to_keplerian`, `KeplerianElements.from_state`/`to_state`/`mean_anomaly`/`eccentric_anomaly`, `Trajectory.to_frame`/`at` (cached `Ephemeris` + Hermite interpolation), `to_geodetic` (in `frames.py`), and `Orientation.to_orekit` are all implemented. The deferred-stub constants (`_FEATURE1_NOTE`/`_DEFERRED_NOTE`/`_TO_OREKIT_DEFERRED`) are **retired**. `Epoch.to_orekit()` was the original reference pattern for the lazy bootstrap (`_ensure_started()` then `from org.orekit.time import AbsoluteDate`); the rest of the conversion layer now follows it.
- **`core/bodies.py`** (Chunk 1) — internal accessors for the canonical WGS84 Earth ellipsoid (ITRF) plus Sun/Moon, all behind `_ensure_started()`. Used by SRP, third-body, drag, and geodetic conversion; Orekit types never leak onto a public signature.
- **The full numerical-propagator core** (`propagation/`, Feature 1.1 Chunks 4–9) — the frozen config dataclasses `ForceModelConfig` (`force_models.py`), `IntegratorConfig` (`integrators.py`), `SpacecraftConfig`/`SpacecraftGeometry`/`VariableCd`/`IncidenceVariableCd` (`spacecraft.py`), and the seven-mode attitude family `LofAligned`/`LofOffset`/`Inertial`/`SunPointing`/`NadirPointing`/`InPlaneTracking`/`CustomAttitude` (`attitude.py`); plus **`propagate_numerical`** itself (`numerical.py`) — integrator + gravity + perturbations (third-body, drag with Tier-A `VariableCd`, SRP, solid/ocean tides, relativity), sphere and `box_and_panels` geometry, full attitude wiring, and `Trajectory` metadata assembly. `propagate_numerical` is re-exported at the top level (`import propygator as pgr; pgr.propagate_numerical(...)`).
- **The full output surface** (Feature 1.1 Chunks 10–12) — `io/exports.py` (`export_csv` with its 16 default columns + additive `keplerian`/`sun` group tokens + metadata header; `export_all` bundling summary PNG + 3D HTML + CSV) and `plotting/` (`plot_summary`/`plot_ground_track`/`plot_3d`/`plot_altitude`/`plot_speed`, plus the shared `style.py` per-figure context manager and the bundled Natural Earth coastline `basemap.py`). Plotly for `plot_3d`, matplotlib for the rest. **The entire Feature 1.1 public surface is re-exported from the top-level `__init__.py`** (types, `propagate_numerical`, all config dataclasses, the attitude family, the `plot_*` verbs, `export_csv`/`export_all`); `import propygator` stays JVM-free.

What is **not** built yet — this is the next work:

- **Feature 1.1 is code-complete and its Chunk 13 review/polish is done; the PR + squash-merge into `main` is intentionally deferred** (Chunk 13 header: "merge deferred in favor of additional builds"). The merge is an outward action the user drives. The next *build* work is Feature 1.3 (TLE propagator), then 1.4 → 1.5 → 1.2 (architecture §12 order) — these proceed *before* the deferred merge.
- The submodules `tle/` and `tracking/` are still **empty `__init__.py` stubs** (`propagation/`, `io/`, and `plotting/` are now built). Their public verbs (`propagate_tle`, `fetch_tle`, `find_passes`) are the *target* surface shown in `README.md` and are not implemented or re-exported yet.
- **Remaining `NotImplementedError`s are intended deferrals, not stubs to fill**: UT1 everywhere (`core/time.py`; the `Trajectory` UT1-epoch guard) needs EOP data; the Tier B `IncidenceVariableCd` runtime path (built as a validated skeleton — construction works, but `propagate_numerical` raises when drag is wired on a box with it; `numerical.py:447–452`); and `NadirPointing(velocity_reference='ecef')` (also a validated skeleton — the dataclass accepts `'ecef'`, but lowering it to an Orekit provider raises in `attitude._to_provider`; architecture §13). The `NotImplementedError` in `Frame.to_orekit` is a defensive fallback for an unmapped enum member, not a deferral.

## Source-of-truth documents

Read these before implementing anything. They are detailed and decisions in them are deliberate — don't silently diverge.

- `docs/architecture.md` — cross-cutting design: data model, module structure, conventions, key architectural decisions, testing strategy. The single most important file. Section numbers (§3, §6, §10, §11…) are cited throughout the code.
- `docs/features.md` — per-feature sub-designs (1.1 numerical propagator and 1.3 TLE propagator are DRAFTED with full signatures; 1.2/1.4/1.5 are NOT STARTED). **§1.1 is the binding contract for the current work** — every signature, preset, validation rule, metadata grammar, and output. Do not change a signature being implemented; it's the contract.
- `docs/feature-1.1-addendum-drag-validity-and-altitude-guards.md` — **a DRAFT source-of-truth add-on to Feature 1.1** (drag-model validity domain + altitude/regime guard system). Per its own §1 supersession map it **supersedes enumerated parts** of `architecture.md` (§13 escape/re-entry guards; §6 `TrajectoryMetadata`) and `features.md` (§1.1 escape-and-re-entry, drag-coefficient modeling, signature, failure-modes/metadata, docstring) and **wins on conflict** until a future reconciliation folds it back in — so read it before trusting those passages. Not yet built; the next build plan derives from it.
- `docs/history/build-plan-feature-1.1.md` — **the Feature 1.1 build plan, now archived** (moved into `docs/history/` once the code landed). 13 sequenced, session-sized chunks for the numerical propagator, each with Goal/Create-Edit/Reuse/You-provide/Verify and inline checkpoints (CLAUDE.md refresh + `/code-review` + `/simplify`). All chunks' build + review work is done; only Chunk 13's PR + squash-merge into `main` is outstanding (intentionally deferred, user-driven). Still the binding reference for that final merge — it carries the full git feature-branch → PR → merge walkthrough.
- `docs/history/build-plan-stage-1.md` — the sequenced groundwork plan (Chunks 1–8). **Complete**; kept as the historical record of *why* the scaffolding is shaped the way it is.
- `docs/project_meta.md` — governance/distribution decisions (MIT, GitHub-only, tier-(a) personal portfolio, minimal CI). This doc *supersedes* the tier-(b) framing that leaks into a few spots of `architecture.md`.
- `docs/orekit_setup_reference.md` — the working Orekit/JPype environment and the Java↔Python boundary patterns. **It self-flags as possibly out of date and is NOT a source of truth.** `architecture.md`/`features.md` win in any conflict; verify before relying on it.

## Environment & running

The conda env named `propygator` already exists and runs. `environment.yml` is on disk and is the single source of truth for the env (it installs propygator editable via `pip: -e .[dev]`).

- conda env named `propygator`, Python **3.11** (pinned), OpenJDK **17** (bundled by conda)
- `orekit_jpype` 13.1.x, `jpype1` 1.5.x, NumPy 2.x, pandas 3.x — all from `conda-forge`
- Dev toolchain (pytest, ruff, mypy, pre-commit, nbstripout) comes from the `[dev]` extra. Latest verified snapshot: `docs/verified_environments/2026-06.txt`.
- **Never** use the legacy JCC-based `orekit` package (pulls OpenJDK 8).

Activate before running anything Python: `conda activate propygator`. On this Windows machine, PowerShell needs a one-time `conda init powershell`; the conda interpreter is at `C:\Users\hzhan\miniconda3\envs\propygator\python.exe`. **Activation is mandatory, not cosmetic** — NumPy here links Intel MKL whose runtime DLLs only resolve in the activated env, so calling that interpreter path directly hard-crashes on the first NumPy linear-algebra call (`@`, `np.linalg.*`) with `Windows fatal exception 0xC06D007F` instead of a Python error. For non-interactive runs prefer `conda run -n propygator <cmd>` (note: `conda run` rejects newlines in `python -c`; use a script file).

Commands:
- Tests: `conda run -n propygator pytest`; single test: `pytest tests/core/test_time.py::test_name`. `testpaths=["tests"]` keeps a bare `pytest` from recursing into the vendored `./orekit-data/` tree.
- The stack-compatibility test (guards NumPy↔JPype↔Orekit, starts the JVM): `pytest tests/test_stack_compat.py`. Requires orekit-data resolvable (see below).
- Lint/format/typecheck/hooks: `pre-commit run --all-files` (ruff-check + ruff-format + mypy + nbstripout + file hygiene). Same hooks run in CI.
- Lint or type-check alone: `ruff check src tests scripts` / `mypy` (mypy scope is `src` + `scripts` only — tests are not type-gated; `py.typed` is a promise about `src/`).
- Create/update env: `conda env create -f environment.yml` / `conda env update -f environment.yml --prune` (if pip deps desync, recreate rather than update).

**faulthandler is disabled** (`addopts = ["-p", "no:faulthandler"]` in `pyproject.toml`). Once the JVM is up, HotSpot deliberately raises/handles access violations internally; faulthandler misreads the benign JVM-teardown signal as a fatal crash and prints a spurious access-violation traceback at shutdown (exit code stays 0). Do not re-enable it.

### orekit-data

~500 MB, **not** committed, treated as an external dependency. Resolution order (implemented in `_orekit_init._resolve_data_path`): `OREKIT_DATA_PATH` env var (authoritative — set-but-missing **raises**, never falls back) → `~/.propygator/orekit-data/` → `./orekit-data/` → raise `OrekitDataMissingError` (the message carries the URL + remedies; never a raw Java trace). A copy currently lives at the repo root `./orekit-data/`; the canonical install location is `~/.propygator/orekit-data/`. Fetch it with `python scripts/download_orekit_data.py` (also used by CI on a cache miss). Download source: https://gitlab.orekit.org/orekit/orekit-data (branch `main`, not `master`). The test session aborts cleanly via an autouse, no-JVM data gate in `tests/conftest.py` if data is unresolvable.

## Architecture invariants

These are enforced at module boundaries; violating them is a bug (architecture §4, §10).

- **Orekit types stay internal.** Public APIs accept/return only propygator types (`Epoch`, `Frame`, `State`, `Trajectory`, `TLE`, `Orientation`, …). JPype/Java objects appear only inside implementations. `to_orekit()` methods annotate the Orekit return type under `if TYPE_CHECKING:` (with a runtime `else:` branch) so no runtime Orekit import leaks into the public type surface — see `Epoch.to_orekit` / `State.to_orekit` for the pattern.
- **Lazy JVM, one JVM per process.** Importing `propygator` must NOT start the JVM. It starts on the first Orekit-touching call (via `_ensure_started()`), or via explicit `propygator.init(vmargs=...)`. JPype cannot re-init the JVM, so `init()` with conflicting `vmargs` raises `JVMAlreadyStartedError`. The "safe before init" surface (all `Epoch`/`Frame`/`State`/config construction + validation; everything except `to_orekit()` and the propagate/fetch/track verbs) is asserted by the pure-Python `tests/core/*` suite — keep accidental Orekit imports out of it (import `jpype`/`orekit_jpype`/`pyhelpers` lazily *inside* functions, never at module top).
- **Units:** SI everywhere internally (m, s, rad, kg); human-friendly (km, deg, days) only at the user-facing boundary.
- **Frames are explicit.** Every `State`/`Trajectory` carries a `Frame`; no defaults, no automatic conversion on `State`-returning paths (users call `.to_frame(...)`). Functions returning non-frame-carrying types (`GeodeticPosition`, `Pass`, scalars) may convert internally. v1 frame set: EME2000 (`J2000` is an enum *alias* of the same member), ITRF, TEME.
- **Time:** all internal time is `Epoch` (carries an explicit `TimeScale`; UTC user-facing, TT for dynamics; conversions explicit). Stored as a two-part `(_int_seconds, _frac_seconds)` count of TAI-seconds-since-J2000 (computed via the TT route for exactness; see `core/time.py` module docstring). Naive `datetime`s rejected at the boundary. **UT1 is deferred** (needs EOP data from a running JVM) — it raises `NotImplementedError` everywhere.
- **Paths:** `pathlib.Path` throughout — no string concat, no `os.path.join`.
- **Logging, never prints:** `logger = logging.getLogger(__name__)` per module; top-level `__init__.py` attaches a `NullHandler`.
- **Frozen dataclasses** for the data model, with shape/dtype/finiteness validation in `__post_init__` (`State`, `Epoch`, `KeplerianElements`, `Orientation`, `GroundStation`, …). Array-backed value types (`State`, `Orientation`) defensively copy inputs, set them read-only, and define value-based `__eq__`/`__hash__` (the dataclass-generated `__eq__` raises on ndarray fields). `Trajectory` is intentionally **not** frozen (`eq=False`, caches an `Ephemeris`) but its backing arrays are set read-only and equality is by identity.

## Module structure & dependency rule

Modern `src/` layout: `src/propygator/{core,propagation,tle,tracking,plotting,io}/` (see architecture §5, §7 for the full tree). Top-level `__init__.py` re-exports the common verbs as features land; today it re-exports `init`/`clear_cache`, the types, the exceptions, and the **full Feature 1.1 surface** (`propagate_numerical`, the config dataclasses, the attitude family, the `plot_*` verbs, `export_csv`/`export_all`). Still to come as later features land: `propagate_tle`, `fit_tle`, `fetch_tle`, `current_position`, `find_passes`. Documented import alias is `pgr` (`import propygator as pgr`).

Dependencies flow inward: `tracking/` → `propagation/`/`tle/` → `core/`. `io/` depends only on `core/` (this is why `GroundStation`/`Pass`/`GeodeticPosition` live in `core/observation.py`, not in `io/` or `tracking/`). Exceptions live in `core/exceptions.py` (the innermost layer) so any subpackage can raise/catch them. **Nothing imports `plotting/`** — it's a leaf, so the core stays testable headless.

## Conventions for this repo

- Build order: groundwork (done), *then* features in architecture §12 order: 1.1 numerical propagator → 1.3 TLE propagator → 1.4 tracker → 1.5 passes → 1.2 TLE fitter (hardest, treated as a plus).
- **Signatures are the binding contract.** The conversion-layer deferred stubs (`_FEATURE1_NOTE`/`_DEFERRED_NOTE`) are retired, and the entire Feature 1.1 surface (`propagate_numerical`, all config dataclasses, the `plot_*`/`export_csv`/`export_all` verbs) is implemented to its `features.md` §1.1 signatures. This rule now governs the **next** features (1.3 onward): implement each verb to the **exact signature in `features.md`** — don't change it. Genuine remaining deferrals raise `NotImplementedError` with a clear message: UT1 (needs EOP data) and the Tier B `IncidenceVariableCd` runtime path.
- **Notebooks** live in `notebooks/` (NOT inside the package), numbered (`01_intro.ipynb`); the `nbstripout` pre-commit hook strips outputs — keep it.
- **Plotting backends:** Plotly for interactive 3D, matplotlib for everything else (2D timeseries, polar sky charts). Each `plot_*` returns the native figure. A bundled low-res Natural Earth coastline in `data/` (NOT cartopy) draws map overlays.
- **Testing** (architecture §11): JVM + orekit-data started once per session via the opt-in `orekit` fixture in `tests/conftest.py` (requested only by tests that touch Orekit; the autouse fixture is a *no-JVM* data gate so the pure-Python `tests/core/*` suite can assert "safe before init"). Reference cases are ISS TLEs and Vallado vectors; Keplerian round-trips checked to machine precision; plot snapshot tests. The 3-part stack-compatibility test guards the NumPy↔JPype↔Orekit boundary.
  - **One-JVM-per-process ordering:** `jpype.isJVMStarted()` is a monotonic global flag, so the `tests/core` `test_no_jvm_started` guards only hold while no JVM test has run yet in the process. A `pytest_collection_modifyitems` hook in `conftest.py` schedules every `orekit`-fixture test *last*, so any path order (e.g. `pytest tests/test_conversions.py tests/core`) stays green. **New JVM-touching tests must acquire the JVM via the `orekit` fixture** — that's how the hook knows to order them after the pure-Python guards.
- **Versioning:** SemVer from 0.1.0, staying on 0.x; version single-sourced in `pyproject.toml`, read back via `importlib.metadata` (`core.states._propygator_version`, returns `"unknown"` from a non-installed source tree). CHANGELOG is hand-maintained Keep-a-Changelog.
- **Credentials** (Space-Track) come from env vars (`SPACETRACK_USERNAME`/`PASSWORD`) or a gitignored `.env` (`.env.example` is committed); never committed.

## Java↔Python boundary notes (orekit_jpype)

- Import `jpype`/`orekit_jpype`/`orekit_jpype.pyhelpers` **lazily inside functions**, never at module top — `pyhelpers` does `from java.io import File` at import time and cannot even be imported before `initVM()`.
- `Vector3D` etc. are Java objects: extract with getters into NumPy (`np.array([v.getX(), v.getY(), v.getZ()])`).
- Cannot subclass Java classes from Python; implement Java interfaces (custom force models, event detectors, the variable-Cd `DragSensitive`) via `@JImplements`/`@JOverride`.
- IDE autocomplete on `org.orekit.*` is limited (runtime stubs); red underlines that run fine are normal. mypy treats the `org.orekit.*`/`java.*`/`jpype`/`pandas`/`requests` namespaces as untyped (`ignore_missing_imports` in `pyproject.toml`).
- Don't `conda update` blindly — the pinned trio (Python 3.11 / OpenJDK 17 / orekit_jpype 13.1.x) is a tested combination; upgrade Orekit by creating a fresh env.
