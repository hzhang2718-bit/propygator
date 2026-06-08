# Groundwork plan: scaffolding propygator before Feature 1

## Context

`propygator` is fully designed but unimplemented — only `docs/`, one standalone
`test_numpy_compat.py`, and housekeeping files (`README.md`, `LICENSE`,
`CHANGELOG.md`, `.gitignore`) exist on disk. The goal of this plan is to lay all
the groundwork — folders, packaging, environment spec, lazy-JVM machinery, the
pure-Python core data model, the test harness, tooling, and CI — so that work on
**Feature 1.1 (numerical propagator)** can start against a real, importable,
tested package.

Scope decisions locked with the user:
- **Core types:** implement the JVM-free "safe before init" surface fully and
  tested (`Epoch`, `TimeScale`, `Frame`, exceptions); add **validated skeletons**
  for `State` / `Trajectory` / `KeplerianElements` / `Orientation` /
  observation types (construction + shape/dtype/finiteness validation). Defer
  `to_orekit()` / `to_frame()` / Orekit conversions to Feature 1.
- **Tooling:** pre-commit **and** a minimal GitHub Actions CI.
- **Environment:** an env named `propygator` already exists and runs
  `test_numpy_compat.py` today; it is incomplete and has no `environment.yml`.
  We write `environment.yml` to match the verified pins
  (`docs/verified_environments/2026-05.txt`) and top off the missing packages.

Binding design docs (do not silently diverge): `docs/architecture.md` (§3 env,
§4 conventions, §5 tree/packaging, §7 dep rule, §10 JVM/logging/cache, §11
testing, §12 build order), `docs/features.md` (1.1 / 1.3 drafted),
`docs/project_meta.md` (MIT, GitHub-only, tier-a, minimal CI),
`docs/orekit_setup_reference.md` (JVM boilerplate, Java↔Python boundary).

### One-time dependency top-off (you run this) - Completed

The env is missing these (verified absent in the 2026-05 snapshot). All on
conda-forge — single command:

```powershell
conda install -n propygator -c conda-forge matplotlib plotly pandas pytest pre-commit ruff mypy nbstripout python-dotenv
```

The editable install (`pip install -e .`) happens in **Chunk 1** after
`pyproject.toml` exists. `matplotlib`/`plotly`/`pandas` are pulled now (Feature
1.1 plotting needs them) but not exercised until then. `python-dotenv` is for
Feature 1.3+ credentials; harmless to have early.

---

## Chunk 1 — Packaging foundation: `src/` tree + `pyproject.toml` + `environment.yml` - Completed and verified

**Goal:** make `propygator` a real, importable, editable-installed package whose
import does **not** start the JVM.

**Create:**
- `src/propygator/__init__.py` — `__version__ = importlib.metadata.version("propygator")`;
  attach `logging.getLogger("propygator").addHandler(logging.NullHandler())`.
  Re-export nothing yet beyond `__version__` (the verb/type surface grows as
  later chunks land — keep accidental Orekit imports out).
- `src/propygator/core/__init__.py`, `propagation/__init__.py`, `tle/__init__.py`,
  `tracking/__init__.py`, `plotting/__init__.py`, `io/__init__.py` — empty stubs
  (the full module tree from architecture §5 is created incrementally).
- `pyproject.toml` — `[build-system]` setuptools + src layout
  (`[tool.setuptools.packages.find] where = ["src"]`); `[project]` name
  `propygator`, `version = "0.1.0"` (single source of truth, SemVer 0.x),
  `requires-python = ">=3.11"`, author Henry Zhang / hzhang2718@gmail.com,
  MIT license; `[project.dependencies]`: `numpy`, `pandas`, `matplotlib`,
  `plotly`, `requests`, `python-dotenv` (**not** orekit — conda owns it);
  `[project.optional-dependencies] dev`: `pytest`, `ruff`, `mypy`, `pre-commit`,
  `nbstripout`; `[project.urls]` with the GitHub repo URL.
- `environment.yml` — channel conda-forge; conda deps pinned to verified majors:
  `python=3.11`, `openjdk=17`, `orekit_jpype=13.1.*`, `jpype1=1.5.*`,
  `numpy=2.*`, `pandas=3`, `matplotlib`, `plotly`, `jupyterlab=4.5.*`, `pip`,
  then `pip: ["-e .[dev]"]`. (Orekit deliberately conda-only; never the legacy
  JCC `orekit`.)

**You provide:** the GitHub repo URL/username for `[project.urls]`
(`docs/history/github_status_2026_06_03.md` may already have it — I'll check
there first and only ask if it's absent).

**You run:** `conda activate propygator; pip install -e .` (after files exist).

**Verify:**
```powershell
conda activate propygator
python -c "import propygator, jpype; print(propygator.__version__); print('JVM started:', jpype.isJVMStarted())"
```
Expect `0.1.0` and `JVM started: False`. Also `pip show propygator` shows an
editable (`Location` pointing at `src`) install.

---

## Chunk 2 — Lazy JVM init + exceptions + orekit-data resolution - Completed and Claude verified

**Goal:** the one-JVM-per-process lazy-init machinery and clean, typed errors.

**Create:**
- `src/propygator/core/exceptions.py` — `OrekitDataMissingError`,
  `JVMAlreadyStartedError` (and a base `PropygatorError`).
- `src/propygator/_orekit_init.py`:
  - `init(vmargs=None)` — starts the JVM exactly once (`orekit_jpype.initVM`),
    then `setup_orekit_curdir(<resolved data path>)`. Resolution order
    (architecture §3): `OREKIT_DATA_PATH` env → `~/.propygator/orekit-data/` →
    `./orekit-data/` → raise `OrekitDataMissingError` with the gitlab download
    URL, the search order, and a copy-paste command (never a raw Java trace).
    Honor `PROPYGATOR_VM_ARGS`. If already started: no-op when args match, raise
    `JVMAlreadyStartedError` when they differ (JPype can't re-init).
  - an internal `_ensure_started()` that Orekit-touching code calls.
  - `clear_cache()` — recursively empties `~/.propygator/cache/` (dir preserved).
  - Use `pathlib.Path` throughout; `logger = logging.getLogger(__name__)`.
- Re-export `init`, `clear_cache`, and the exception types (`PropygatorError`,
  `OrekitDataMissingError`, `JVMAlreadyStartedError`) from top-level
  `__init__.py`. The exceptions are now defined and `init()` raises them, so
  they belong on the top-level surface (architecture §7 lists "the exception
  types" there); all three are pure-Python and carry no Orekit-import risk.

**Reuse:** the exact boilerplate ordering from
`docs/orekit_setup_reference.md` (`initVM()` before any `from org.orekit...`;
`setup_orekit_curdir(path)` once) and `test_numpy_compat.py`.

**You provide:** nothing (your repo-root `orekit-data/` satisfies the 3rd
resolution rule when run from the repo).

**Verify** (manual script, run from repo root so `./orekit-data` resolves):
```powershell
conda activate propygator
python -c "import propygator as pgr, jpype; pgr.init(); print('started:', jpype.isJVMStarted()); pgr.init()"  # 2nd init no-ops
python -c "import propygator as pgr; pgr.init(); pgr.init(vmargs='-Xmx9g')"  # expect JVMAlreadyStartedError
$env:OREKIT_DATA_PATH='C:\does\not\exist'; python -c "import propygator as pgr; pgr.init()"  # expect OrekitDataMissingError, clean msg
Remove-Item Env:\OREKIT_DATA_PATH
```

---

## Chunk 3 — `core/time.py`: `Epoch` + `TimeScale` (full, pure-Python) - Completed and verified

**Goal:** the most-used "safe before init" type, fully implemented and tested
without touching the JVM.

**Create:**
- `src/propygator/core/_leap_seconds.py` — bundled static leap-second table
  (enables pure-Python UTC↔TAI).
- `src/propygator/core/time.py`:
  - `class TimeScale(Enum)`: UTC, TAI, TT, UT1.
  - `@dataclass(frozen=True) Epoch` with `_int_seconds` (TAI s since J2000),
    `_frac_seconds` ∈ [0,1), `scale`. Methods: `from_iso`, `from_datetime`
    (**reject naive datetimes**), `now`, `in_scale`, `shifted_by` (renormalize
    frac), `to_iso`, `to_datetime` (tz-aware). `to_orekit()` annotated under
    `if TYPE_CHECKING` → `org.orekit.time.AbsoluteDate`; runtime body calls
    `_ensure_started()` then builds the `AbsoluteDate` (only JVM-touching method;
    UT1 construction also defers to the JVM).
- Re-export `Epoch`, `TimeScale` from `__init__.py`.
- `tests/__init__.py`, `tests/core/__init__.py`,
  `tests/core/test_time.py` — pure-Python, **no JVM**: iso round-trip,
  datetime round-trip, naive-datetime rejection, `shifted_by` frac
  renormalization, scale conversions vs known offsets (e.g. TAI−UTC, TT−TAI=32.184s).

**Verify:** `conda activate propygator; pytest tests/core/test_time.py -v` green;
confirm none of these tests start the JVM (assert `not jpype.isJVMStarted()` in a
test).

---

## Chunk 4 — `core/frames.py` + `core/states.py::State` + `core/observation.py` - Complete and Claude verified

**Goal:** the frame enum and the simple frozen dataclasses with validation.

**Create:**
- `src/propygator/core/frames.py` — `class Frame(Enum)` with `EME2000="EME2000"`,
  `J2000="EME2000"` (auto-alias → `Frame.J2000 is Frame.EME2000`),
  `ITRF="ITRF"`, `TEME="TEME"`. `to_orekit()` deferred (JVM-touching;
  `raise NotImplementedError` stub with a "Feature 1" note, or minimal lookup
  behind `_ensure_started()` — keep it stubbed for now).
- `src/propygator/core/states.py::State` — `@dataclass(frozen=True)`:
  `epoch: Epoch`, `position`/`velocity: np.ndarray`, `frame: Frame`.
  `__post_init__` validates shape `(3,)`, dtype `float64`, finiteness
  (architecture §4 spec — copy the error messages). `to_frame`,
  `to_keplerian`, `to_orekit` → `NotImplementedError` (Feature 1).
- `src/propygator/core/observation.py` — frozen dataclasses `GroundStation`,
  `GeodeticPosition`, `Pass` (lives in `core/` so `io/` can import without
  breaking the dep rule, architecture §7).
- Re-export `Frame`, `State`, `GroundStation`, `GeodeticPosition`, `Pass`.
- `tests/core/test_frames.py`, `test_states.py`, `test_observation.py` —
  alias identity; valid State; rejection of wrong shape / float32 / NaN / inf.

**Verify:** `pytest tests/core/ -v` green (incl. Chunk 3). Confirm pure-Python
(no JVM) for construction/validation.

---

## Chunk 5 — `Trajectory` + `TrajectoryMetadata` + `KeplerianElements` + `Orientation` - Complete and Claude verified

**Goal:** the complex data-model types as validated skeletons (no Orekit math).

**Create:**
- In `core/states.py`:
  - `TrajectoryMetadata(TypedDict, total=False)` with `Required[...]`
    `propygator_version`, `orekit_version`, `propagator`; optional keys per
    architecture §10.
  - `class Trajectory` (intentionally **not** frozen): column arrays
    (`_epochs_int int64`, `_epochs_frac float64`, `positions`/`velocities`
    `float64 (N,3)`), `epoch_scale`, `frame`, `metadata`. `__post_init__`
    validates required metadata keys + array shapes/dtypes, then
    `setflags(write=False)` on all backing arrays. Implement the JVM-free parts:
    `__len__`, `__getitem__`→materialize `State`, `__iter__`, `from_states`,
    `from_arrays`, `to_dataframe` (pandas, pure-Python). Defer `at()` /
    `to_frame()` (JVM) → `NotImplementedError` (Feature 1).
  - `Orientation` — construct from quaternion / axis-angle / 3×3 matrix;
    validation only; `to_orekit()` deferred.
- `src/propygator/core/elements.py::KeplerianElements` — frozen dataclass, SI,
  true-anomaly convention; field validation only; `from_state`/`to_state`
  conversions deferred (Feature 1).
- Re-export `Trajectory`, `KeplerianElements`, `Orientation`.
- `tests/core/test_trajectory.py`, `test_elements.py` — `from_arrays`/`from_states`
  round-trip; read-only enforcement (write raises); missing-metadata-key
  rejection; `to_dataframe` shape/columns; `len`/index/iter materialize States.

**Verify:** `pytest tests/core/ -v` green.

---

## Chunk 6 — Test harness: `conftest.py` + stack-compatibility boundary test

**Goal:** session-scoped JVM/data init for tests, and the boundary guard ported
from `test_numpy_compat.py`.

**Create:**
- `tests/conftest.py` — session-scoped autouse fixture calling `propygator.init()`
  once (same resolution path as user code); abort the session with the clean
  `OrekitDataMissingError` if data is unresolvable (architecture §11).
- `tests/test_stack_compat.py` — port the boundary checks from
  `test_numpy_compat.py`: (a) smoke import + JVM start + `Epoch.to_orekit()` /
  raw Orekit object construction; the `Vector3D`↔NumPy extraction, NumPy→`JArray`,
  and dtype-edge-case (`float32/float64/int32/int64`) assertions; a manual raw-Orekit
  Keplerian propagation asserting `(N,3) float64`. **Note:** parts (b) numerical
  round-trip via `propagate_numerical` and (c) bulk-`Trajectory` CSV round-trip
  depend on Feature 1.1 — add them when 1.1 lands; leave `# TODO(1.1)` markers.

**Reuse:** `test_numpy_compat.py` is the source material — move its logic into
the test, then delete the standalone script (or keep it until the port is
verified green, then remove).

**Verify:** `conda activate propygator; pytest -v` (full suite) green from repo
root.

---

## Chunk 7 — Tooling: pre-commit + lint/type config + orekit-data download script

**Goal:** enforce hygiene locally; make orekit-data reproducible for CI/fresh setups.

**Create:**
- `.pre-commit-config.yaml` — hooks: `ruff` (lint) + `ruff-format`, `mypy`,
  `nbstripout`, and file hygiene (`trailing-whitespace`, `end-of-file-fixer`,
  `check-yaml`, `check-toml`).
- Add `[tool.ruff]` and `[tool.mypy]` to `pyproject.toml`; mypy gets
  `ignore_missing_imports` for the `org.orekit.*` runtime-stub namespace
  (architecture §6 / JPype note).
- `scripts/download_orekit_data.py` — downloads + extracts orekit-data from
  `https://gitlab.orekit.org/orekit/orekit-data` into a target dir
  (default `~/.propygator/orekit-data/`); `pathlib`, `logging`, no prints.

**You run:** `conda activate propygator; pre-commit install` (one time, optional
but recommended so hooks run on commit).

**Verify:** `pre-commit run --all-files` passes (after it auto-fixes formatting;
re-run until clean). Optionally smoke the script with `--help` /a temp dir.

---

## Chunk 8 — CI + docs polish + housekeeping

**Goal:** wire up CI and bring the repo docs/structure to a clean baseline.

**Create / edit:**
- `.github/workflows/ci.yml` — on push (any branch) + PR; Ubuntu + Python 3.11;
  `mamba-org/setup-micromamba@v1` to build from `environment.yml`; cache
  orekit-data (`actions/cache`) and fetch via `scripts/download_orekit_data.py`
  on miss; run `pytest` then `pre-commit run --all-files` (project_meta CI spec).
- `README.md` — expand to the 9-section structure (project_meta §9): one-liner,
  CI + license badges only, install (`conda env create -f environment.yml`),
  quick example (the §9 snippet), features, notebooks link, architecture link,
  acknowledgments (Orekit Apache-2.0 + orekit_jpype), license.
- `CHANGELOG.md` — populate `[Unreleased]` with the groundwork additions
  (Keep-a-Changelog).
- `notebooks/01_intro.ipynb` — minimal placeholder (nbstripout keeps it clean).
- `data/` — create with a short `README.md` placeholder (Natural Earth coastline
  is sourced during Feature 1.1 plotting, not now).
- `.env.example` — `SPACETRACK_USERNAME=` / `SPACETRACK_PASSWORD=` template
  (real `.env` stays gitignored; credentials only needed at Feature 1.3+).

**You provide:** GitHub repo URL (for README badges/clone) if not already
captured in Chunk 1; decide whether to push to trigger the first CI run.

**Verify:** locally run exactly what CI runs — `pytest` and
`pre-commit run --all-files` both green. Validate the workflow YAML
(`check-yaml` hook). If you push, confirm the Actions run goes green.

---

## End-state verification (groundwork complete → ready for Feature 1)

From repo root, `conda activate propygator`:
1. `python -c "import propygator, jpype; print(propygator.__version__, jpype.isJVMStarted())"`
   → `0.1.0 False` (import is JVM-free).
2. `python -c "import propygator as pgr, jpype; pgr.init(); print(jpype.isJVMStarted())"`
   → `True`; second `pgr.init()` no-ops; mismatched vmargs raises
   `JVMAlreadyStartedError`; missing data raises `OrekitDataMissingError`.
3. `pytest -v` → all core + stack-compat tests green.
4. `pre-commit run --all-files` → clean.
5. Tree matches architecture §5: `src/propygator/{core,propagation,tle,tracking,plotting,io}/`,
   `tests/`, `notebooks/`, `data/`, `scripts/`, plus `pyproject.toml`,
   `environment.yml`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`.

At that point Feature 1.1 starts by implementing `propagation/numerical.py` (and
the deferred `to_orekit()`/`to_frame()` conversions + the force/spacecraft/
attitude/integrator configs), then completing stack-compat parts (b) and (c).

## Notes / deferred (not groundwork)
- `to_orekit()` / `to_frame()` / Keplerian↔Cartesian math → Feature 1.1.
- TLE type + `tle/` modules, tracking, passes, plotting impls → Features 1.3–1.5.
- MkDocs/mkdocstrings site → deferred (README + architecture.md suffice now,
  project_meta).
- Natural Earth coastline asset → arrives with Feature 1.1 plotting.
- Space-Track credentials → Feature 1.3+ (`.env.example` template only for now).
