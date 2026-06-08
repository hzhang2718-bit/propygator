# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

**propygator** is a Python library for orbital simulation and satellite tracking, built on [Orekit](https://www.orekit.org/) via the `orekit_jpype` wrapper.

The project is in **design phase**. The architecture is fully specified but the package is **not yet implemented**: there is no `src/`, `tests/`, `pyproject.toml`, or `environment.yml` on disk yet — only design docs and one standalone compatibility script. When implementing, you are creating these from the design, not modifying existing code. Treat the design docs as the binding contract.

## Source-of-truth documents

Read these before implementing anything. They are detailed and decisions in them are deliberate — don't silently diverge.

- `docs/architecture.md` — cross-cutting design: data model, module structure, conventions, key architectural decisions, testing strategy. The single most important file.
- `docs/features.md` — per-feature sub-designs (1.1 numerical propagator and 1.3 TLE propagator are DRAFTED with full signatures; 1.2/1.4/1.5 are NOT STARTED).
- `docs/build-plan-stage-1.md` — the sequenced groundwork plan (Chunks 1–8) for scaffolding the package *before* Feature 1.1: `src/` tree + packaging, lazy-JVM init, the pure-Python core data model, the test harness, tooling, and CI. This is the concrete next-steps roadmap; follow it unless the user redirects. The one-time conda dependency top-off it calls for is already done (see env section below).
- `docs/project_meta.md` — governance/distribution decisions (MIT, GitHub-only, tier-(a) personal portfolio, minimal CI). This doc *supersedes* the tier-(b) framing that leaks into a few spots of `architecture.md`.
- `docs/orekit_setup_reference.md` — the working Orekit/JPype environment and the Java↔Python boundary patterns. **It self-flags as possibly out of date and is NOT a source of truth** (its example paths `orekit-project`, legacy `setup_orekit_curdir` boilerplate predate the rename and the lazy-init design). `architecture.md`/`features.md` win in any conflict; verify before relying on it.

## Environment & running

There is no `environment.yml` on disk yet (it's specified in `architecture.md` §3 / `build-plan-stage-1.md` Chunk 1 but not written). However, the conda env named `propygator` **already exists and runs Python today** — the build plan's one-time dependency top-off is done, so the full dev toolchain (pytest, ruff, mypy, pre-commit, nbstripout, matplotlib, plotly, pandas, python-dotenv, jupyterlab) is installed alongside the Orekit stack. Latest verified snapshot: `docs/verified_environments/2026-06.txt` (2026-05 is the prior one).

- conda env named `propygator`, Python **3.11** (pinned), OpenJDK **17** (bundled by conda)
- `orekit_jpype` 13.1.x, `jpype1` 1.5.x, NumPy 2.x, pandas 3.x — all from `conda-forge`
- **Never** use the legacy JCC-based `orekit` package (pulls OpenJDK 8).

Activate before running anything Python: `conda activate propygator`. On this Windows machine, PowerShell needs a one-time `conda init powershell`; the conda interpreter is at `C:\Users\hzhan\miniconda3\envs\propygator\python.exe`.

Commands (most don't work until the corresponding files are created):
- Run the JPype/NumPy/Orekit boundary smoke test (works today): `python test_numpy_compat.py` (requires `orekit-data/` resolvable from CWD)
- Create env (once `environment.yml` exists): `conda env create -f environment.yml`
- Update env: `conda env update -f environment.yml --prune` (if pip deps desync, recreate rather than update)
- Tests (once `tests/` exists): `pytest`; single test: `pytest tests/path/test_x.py::test_name`
- Lint/format/hooks: `pre-commit run --all-files` (ruff + mypy + nbstripout + file hygiene)

### orekit-data

~500 MB, **not** committed, treated as an external dependency. Currently a copy lives at the repo root `orekit-data/`. The designed resolution order (implement in `_orekit_init.py`): `OREKIT_DATA_PATH` env var → `~/.propygator/orekit-data/` → `./orekit-data/` → raise `OrekitDataMissingError` (never a raw Java stack trace). Download source: https://gitlab.orekit.org/orekit/orekit-data.

## Architecture invariants

These are enforced at module boundaries; violating them is a bug (architecture §4, §10).

- **Orekit types stay internal.** Public APIs accept/return only propygator types (`Epoch`, `Frame`, `State`, `Trajectory`, `TLE`, `Orientation`, …). JPype/Java objects appear only inside implementations. `to_orekit()` methods annotate the Orekit return type under `if TYPE_CHECKING:` so no runtime Orekit import leaks into the public type surface.
- **Lazy JVM, one JVM per process.** Importing `propygator` must NOT start the JVM. It starts on the first Orekit-touching call, or via explicit `propygator.init(vmargs=...)`. JPype cannot re-init the JVM. There is a defined "safe before init" surface (all `Epoch`/`Frame`/`State`/config construction and validation, everything except `to_orekit()` and the propagate/fetch/track verbs) — keep accidental Orekit imports out of it.
- **Units:** SI everywhere internally (m, s, rad, kg); human-friendly (km, deg, days) only at the user-facing boundary.
- **Frames are explicit.** Every `State`/`Trajectory` carries a `Frame`; no defaults, no automatic conversion on `State`-returning paths (users call `.to_frame(...)`). Functions returning non-frame-carrying types (`GeodeticPosition`, `Pass`, scalars) may convert internally. v1 frame set: EME2000 (alias J2000), ITRF, TEME.
- **Time:** all internal time is `Epoch` (carries an explicit `TimeScale`; UTC for user-facing, TT for dynamics; conversions explicit). Naive `datetime`s rejected at the boundary.
- **Paths:** `pathlib.Path` throughout — no string concat, no `os.path.join`.
- **Logging, never prints:** `logger = logging.getLogger(__name__)` per module; `__init__.py` attaches a `NullHandler`.
- **Frozen dataclasses** for the data model, with shape/dtype/finiteness validation in `__post_init__` (`State`, `Trajectory`, configs). `Trajectory` is intentionally not frozen (caches an `Ephemeris`) but its backing arrays are set read-only.

## Module structure & dependency rule

Modern `src/` layout: `src/propygator/{core,propagation,tle,tracking,plotting,io}/` (see architecture §5, §7 for the full tree). Top-level `__init__.py` re-exports the common verbs (`propagate_numerical`, `propagate_tle`, `fit_tle`, `fetch_tle`, `current_position`, `find_passes`, the `plot_*`/`export_*` functions, `init`, types). Documented import alias is `pgr` (`import propygator as pgr`).

Dependencies flow inward: `tracking/` → `propagation/`/`tle/` → `core/`. `io/` depends only on `core/` (this is why `GroundStation`/`Pass`/`GeodeticPosition` live in `core/observation.py` and the satellite/magnitude catalogs in `core/catalogs.py`, not in `io/` or `tracking/`). **Nothing imports `plotting/`** — it's a leaf, so the core stays testable headless.

## Conventions for this repo

- Build order: first the groundwork (`build-plan-stage-1.md` Chunks 1–8: scaffolding, lazy-JVM init, core data model, test harness, tooling, CI), *then* the features in the architecture §12 order: 1.1 numerical propagator → 1.3 TLE propagator → 1.4 tracker → 1.5 passes → 1.2 TLE fitter (hardest, treated as a plus).
- **Notebooks** live in `notebooks/` (NOT inside the package), numbered (`01_intro.ipynb`); `nbstripout` pre-commit hook strips outputs — keep it.
- **Plotting backends:** Plotly for interactive 3D, matplotlib for everything else (2D timeseries, polar sky charts). Each `plot_*` returns the native figure. A bundled low-res Natural Earth coastline in `data/` (NOT cartopy) draws map overlays.
- **Testing** (architecture §11): JVM + orekit-data initialized once per session in `tests/conftest.py`; reference cases are ISS TLEs and Vallado vectors; Keplerian round-trips checked to machine precision; plot snapshot tests. A 3-part stack-compatibility test guards the NumPy↔JPype↔Orekit boundary.
- **Versioning:** SemVer from 0.1.0, staying on 0.x; version single-sourced in `pyproject.toml`, read back via `importlib.metadata`. CHANGELOG is hand-maintained Keep-a-Changelog.
- **Credentials** (Space-Track) come from env vars (`SPACETRACK_USERNAME`/`PASSWORD`) or a gitignored `.env`; never committed.

## Java↔Python boundary notes (orekit_jpype)

- `Vector3D` etc. are Java objects: extract with getters into NumPy (`np.array([v.getX(), v.getY(), v.getZ()])`).
- Cannot subclass Java classes from Python; implement Java interfaces (custom force models, event detectors, the variable-Cd `DragSensitive`) via `@JImplements`/`@JOverride`.
- IDE autocomplete on `org.orekit.*` is limited (runtime stubs); red underlines that run fine are normal.
- Don't `conda update` blindly — the pinned trio (Python 3.11 / OpenJDK 17 / orekit_jpype 13.1.x) is a tested combination; upgrade Orekit by creating a fresh env.
