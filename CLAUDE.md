# CLAUDE.md

Durable context for Claude Code sessions on this repo. Read this before starting work.

## What this project is

`propygator` is a Python library for orbital simulation and satellite tracking, built on Orekit. Personal-portfolio project, public repo, single maintainer. Documented import alias: `pgr`.

Authoritative design documents live in `docs/`:

- `docs/architecture.md` — types, modules, conventions, decisions. **Read before designing anything new.** Section 13 is the canonical decisions log.
- `docs/project_meta.md` — licensing, versioning, CI, distribution. Tier-(a) project; bias toward minimalism.

If a session produces a decision worth keeping, update §13 of `architecture.md` before merging.

## Environment

Conda + JPype. The legacy JCC-based `orekit` package is NOT used here.

```bash
conda env create -f environment.yml
conda activate propygator
```

**Always work inside the `propygator` conda env.** If a command fails with `ModuleNotFoundError: orekit_jpype` or a Java DLL error, the env isn't active — stop and activate it; don't `pip install` anything to "fix" it.

Verified-environment snapshots live in `docs/verified_environments/`. If you change `environment.yml`, run the three-layer stack-compat test (see Testing below) and commit a fresh snapshot.

### Orekit data

External dependency, not shipped with the package. Resolved at runtime via this search order (see architecture §3):

1. `OREKIT_DATA_PATH` env var
2. `~/.propygator/orekit-data/`
3. `./orekit-data/` (one-off experimentation only — sensitive to cwd)
4. Otherwise raise `OrekitDataMissingError`

**Never hardcode an orekit-data path in code, tests, notebooks, or examples.** The only file that resolves the path is `src/propygator/_orekit_init.py`. Everything else goes through it.

## Non-negotiable conventions

These are enforced at module boundaries. Violating them is a bug, not a style preference. Full text in architecture §4 and §10.

### Wrapper

**Use `orekit_jpype` (JPype-based).** Do NOT use the legacy `orekit` package (JCC-based). Most online Orekit tutorials and Stack Overflow answers use the legacy wrapper — its idioms (`orekit.initVM()`, `JArray_double`, `Orbit.cast_`, the `from orekit.pyhelpers import setup_orekit_curdir` pattern) do not apply here. The canonical idiom for this repo lives in `src/propygator/_orekit_init.py`; copy from there.

### Units

- **Internal: SI.** Meters, seconds, radians, kilograms.
- **I/O: human-friendly.** Kilometers, degrees, days at the user-facing boundary.
- Conversions happen at the boundary, not scattered through the code.

### Time

- All time values inside `propygator` are `propygator.Epoch` instances. Never raw `datetime`, never raw Orekit `AbsoluteDate` in public APIs.
- User input: UTC ISO strings or **tz-aware** `datetime`. Naive `datetime` rejected at parse time.
- Internal: UTC for user-facing values, TT for dynamics. Conversions are explicit (`epoch.in_scale(TimeScale.TT)`), never implicit.

### Frames

- All frame values inside `propygator` are `propygator.Frame` enum members.
- Every `State` and `Trajectory` carries an explicit `frame`. **No defaults.** A function returning "position" without a frame is a bug.
- No automatic frame conversions on `State`/`Trajectory`-returning paths. Users call `.to_frame(...)` explicitly. (Functions returning derived non-`State` types — `GeodeticPosition`, `Pass`, scalars — may convert internally because no frame ambiguity escapes.)

### Paths

- `pathlib.Path` everywhere. No `os.path.join`, no string concatenation for paths.

### Types at the public boundary

- Orekit's Java-backed objects (`AbsoluteDate`, `SpacecraftState`, `Frame`, `TLE`, etc.) never appear in public type annotations.
- Where a public method exposes an Orekit object (e.g. `Epoch.to_orekit()`), the annotation is gated behind `if TYPE_CHECKING:` so importing `propygator` doesn't import any `org.orekit.*` symbol.

## The JVM rule

JPype constraint: **one JVM per process, started once, cannot be reinitialized.** All three of these matter for how code is written.

### Lazy startup

JVM starts on **first Orekit-touching call**, not on `import propygator`. This gives users a window between `import` and first use to configure JVM args via `propygator.init(vmargs=...)`. Architecture §10 lists the full safe-before-init surface; the short version:

**Safe before JVM starts** (do not touch the JVM): all `Epoch` constructors and methods except `to_orekit()`, all `Frame` enum access except `to_orekit()`, `State.__init__` and its validation, `Trajectory.from_states`/`from_arrays` shape/dtype validation, `TLE.from_strings` parsing, `GroundStation`/`Pass` construction.

**Starts the JVM**: any `to_orekit()` call, `propagate_*`, `fit_tle`, `current_position`, `current_ground_position`, `find_passes`, `Trajectory.at()`.

### What this means for new code

- **Never put `from org.orekit... import ...` at module top level.** Do it inside the function (or method) that needs it. A top-level Orekit import kicks off the JVM on `import propygator`, breaking the explicit-init contract.
- **Same for `import jpype`** in any module other than `_orekit_init.py`.
- Late `init(vmargs=...)` calls raise `JVMAlreadyStartedError` if args differ from running, no-op if they match.

There is (or will be) a CI test that does `import propygator` and asserts the JVM is not running. If you change anything in `src/propygator/__init__.py` or in the import chain, that test must still pass.

## Testing

Run via `pytest` from the activated conda env. Test fixtures (`tests/conftest.py`) initialize JVM + orekit-data once per session.

Reference cases come from Vallado's *Fundamentals of Astrodynamics and Applications*; the verified vectors live in `tests/data/`. **Do not "fix" a failing Vallado test by adjusting the tolerance.** The tolerance is the test; if cross-check fails, the propagator is wrong.

### Stack-compatibility tests (architecture §11)

Three tests guard against silent breakage at the NumPy ↔ JPype ↔ Orekit boundary:

- **(a) Smoke import** — `import propygator`, fetch a known TLE, materialize a `State`.
- **(b) Numerical round-trip** — propagate a Keplerian orbit forward then backward; assert agreement at machine precision.
- **(c) Bulk-array round-trip** — build a large `Trajectory`, run frame conversion, export to CSV, reload, compare arrays and dtypes.

Run these any time you touch `environment.yml`, `_orekit_init.py`, or anything in `core/` that handles array boundaries.

## Workflow expectations

### Plan before writing files

For any non-trivial change, produce a written plan first (plan mode is fine). Read the relevant architecture section, list the files you'll create or modify, list the tests you'll add. Wait for confirmation before editing.

### Commits

- One narrative breakpoint per commit. "Types for 1.1 done" is a commit; "everything for feature 1.1" is not.
- Don't commit notebook outputs — `nbstripout` pre-commit hook handles this; make sure it ran.
- Conventional commit subject lines welcome but not required (the project meta says no auto-changelog).

### When in doubt

- Architectural question → check `docs/architecture.md` §13 (decisions log) before proposing something new.
- Wrapper / Orekit-API question → check `_orekit_init.py` and existing module code for the local idiom before consulting external docs (most of which describe the legacy wrapper).
- "Should I add a Satellite class / RTN frame / FitResult type?" → no. §13 explicitly defers these.

## Things this project deliberately does NOT do

These come up regularly and are settled — don't re-propose them:

- No PyPI / conda-forge publishing (GitHub-only distribution, project meta §4).
- No Windows CI (Linux + Python 3.11 only, project meta §7).
- No `Satellite` convenience class in v1 (architecture §13).
- No RTN/LVLH frames in v1 (architecture §13 — these are relative-motion frames and need a separate type, not an enum extension).
- No `FitResult` return type in v1 — `fit_tle` returns a bare `TLE` (architecture §13).
- No issue templates, no `CONTRIBUTING.md`, no `CODE_OF_CONDUCT.md` (project meta §11).
- No Read the Docs; docs live in `docs/` and render directly on GitHub (project meta §8).
