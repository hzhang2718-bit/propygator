# propygator — Architecture & Design Reference

A Python library for orbital simulation and satellite tracking, built on Orekit.

**Status:** Phase 1 design, revised. Package name: `propygator`. Documented import alias: `pgr`.

---

## 1. Scope

### Core features (v1)

| # | Feature | Description |
|---|---------|-------------|
| 1.1 | Numerical propagator | High-fidelity orbit propagation from an initial state vector, with configurable force models. Outputs trajectories and plots. |
| 1.2 | TLE fitter | Given an observed state (or trajectory), fit a TLE via least-squares against a reference trajectory produced by 1.1. |
| 1.3 | TLE propagator | SGP4 propagation of TLEs with plotting output. |
| 1.4 | Real-time tracker | Current position / ground position for a TLE, plus a **live dashboard** — a buffered, self-refreshing matplotlib view (ground track, altitude, speed, sky view) that tracks the satellite in real time. |
| 1.5 | Ground passes + brightness | Find future visible passes from a ground station, including estimated visual magnitude. Outputs a pass table plus sky charts. Combines tracking, lighting, and eclipse logic. |

### Notes on TLE fitting (1.2)

- Fitting a TLE to a single state via short numerical propagation works, but TLEs inherently degrade because **SGP4 is a simplified model**. For the SGP4 branch used on near-Earth orbits (period < 225 minutes), the force model is limited to J2/J3/J4 zonal harmonics and a single-parameter (B*) drag term, with no SRP, no third-body perturbations, and no tides. The deep-space (SDP4) branch adds simplified lunar/solar perturbations and resonance terms, but it does not approach the fidelity of a numerical propagator with a full force model. Either way, fitting is lossy.
- Practical implication: expose `fitting_span` as a parameter (default 1–3 days), document the inherent lossiness, support both "single state" and "trajectory/observations" inputs.
- TLE propagation (1.3) is the must-have; TLE fitting (1.2) is a plus, and is the hardest to get right.

---

## 2. User-facing surface

### Phase 1 hosting plan

Static only. Three audiences served from one codebase:

1. **Developers** — `pip install` (after conda env setup), `import propygator`, use in scripts / VS Code.
2. **Learners** — Jupyter notebooks shipped in the repo, doubling as tutorials and demos.
3. **Casual visitors** — notebooks rendered to static HTML and posted on the projects page of the personal website.

Interactive web hosting (Streamlit, Gradio, custom backend) is deferred to Phase 2. The architecture supports it without changes.

### Why the layers don't conflict

The core library has no UI dependencies. Notebooks and (future) web apps are thin layers that import the same core. Same logic, different presentations.

---

## 3. Environment & dependencies

### Confirmed working setup (May 2026)

| Component | Version | Notes |
|-----------|---------|-------|
| Python | 3.11 | pinned for binary compatibility |
| OpenJDK | 17 | bundled by conda |
| orekit_jpype | 13.1.x | JPype-based wrapper (modern path) |
| jpype1 | 1.5.x | Java/Python bridge |
| NumPy | 2.x | computation at the boundary |
| jupyterlab | 4.5.7 | for user interfaces |

All from `conda-forge`. **Do not** use the legacy `orekit` (JCC-based) wrapper — it pulls OpenJDK 8 and is harder to maintain on modern systems.

NumPy 2.x compatibility with orekit_jpype 13.1.x has been verified via `test_numpy_compat.py`. The exact `conda list` output of the verified environment is checked in at `docs/verified_environments/2026-05.txt`.

### Important wrapper note

The `orekit_jpype` wrapper has different import boilerplate from the older `orekit` (JCC) wrapper. Most online tutorials and Stack Overflow answers reference the older one. Document this in the README so contributors don't waste hours.

### Installation pattern

Conda handles Orekit + Java; pip handles everything else. A single `environment.yml` is the source of truth — its `pip:` block contains `- -e .` so the project installs in development mode as part of env creation:

```bash
conda env create -f environment.yml
conda activate propygator
```

**Always activate the env before running Python.** The conda env's library directory must be on the search path so NumPy's BLAS/LAPACK backend (this build links Intel MKL) loads; an interpreter launched without activation hard-crashes on the first linear-algebra call (`a @ b`, `np.linalg.*`) with a DLL delay-load error rather than a Python exception. This is primarily a Windows-local-dev hazard — WSL2 and CI run in an activated env. (Detailed troubleshooting lives in the README.)

For dependency updates after the initial install, use `conda env update -f environment.yml --prune` so conda re-evaluates the pip block and removes anything no longer specified. Note that `--prune` has historical quirks with pip-managed entries in the lockfile; if pip dependencies get out of sync, the reliable recovery is to recreate the env rather than to update it. Document this in the README. The verified-environment snapshot (`docs/verified_environments/2026-05.txt`) records the `conda` / `mamba` versions this guidance was tested against; `--prune` behaviour has shifted across versions in the past, so re-verify if the snapshot is more than a few minor versions behind the current tooling.

### Orekit data

**Not shipped with the package.** Treated as an external dependency analogous to a database the application connects to:

- Users download `orekit-data` from https://gitlab.orekit.org/orekit/orekit-data
- A convenience helper at `scripts/download_orekit_data.py` automates the download + extract step for users and CI. By default it populates `~/.propygator/orekit-data/`.
- The library uses a search path on first Orekit-touching call:
    1. `OREKIT_DATA_PATH` env var, if set
    2. `~/.propygator/orekit-data/`, if it exists
    3. `./orekit-data/` in the current working directory, if it exists. *Intended for one-off experimentation; this entry is sensitive to `os.chdir` and to where the process was launched from. Production code and notebooks intended to be re-runnable should rely on the env var or `~/.propygator/`.*
    4. Otherwise, raise `OrekitDataMissingError` with the download URL, the search order, and a copy-paste-ready command for either running the download script or setting the env var.
- When multiple paths resolve, the env var wins. This matches standard config-resolution conventions and lets power users override the default without deleting it.
- Code never surfaces a raw Java stack trace for this case — the missing-data condition is detected before any Orekit class touches the filesystem.

### TLE data sources

- **CelesTrak** — the v1 source. No auth required, covers popular satellites.
- **Direct user input** — always available, takes priority.
- **Space-Track** — **deferred (not wired in v1).** A broader-coverage source requiring an account (env vars `SPACETRACK_USERNAME` / `SPACETRACK_PASSWORD`); the `fetch_tle(source=...)` parameter and a future `source='auto'` are designed to admit it, but v1 fetches CelesTrak only.

A remote fetch that fails in transport — no network / DNS failure / connection refused / timeout, or an HTTP error status — raises `TLEFetchError` (a `PropygatorError` subclass), carrying a clean, actionable message that names the NORAD id and the offline `TLE.from_strings` escape hatch rather than letting `requests`' raw urllib3 traceback surface (the no-raw-trace rule, the same principle as `OrekitDataMissingError`). A *successful* fetch that simply finds no object for the requested id, a malformed response body, or an unknown `source` raises `ValueError` instead — those are not-found / input conditions, not transport failures.

A built-in registry of "popular" satellites (ISS, Hubble, GPS, NOAA, etc.) maps friendly names to NORAD IDs. The same registry carries a curated standard-magnitude table (intrinsic brightness at 1000 km range, 50% phase angle) used by feature 1.5. For satellites outside the registry, users supply magnitude explicitly or pass requests are returned without magnitude estimates.

The registry and magnitude table live in `core/catalogs.py` (see §7) because they are reference data, not I/O. Each magnitude entry must carry an in-source citation for its origin (e.g. Mike McCants's `mcnames.zip` / `qsmag` standard-magnitude file, Heavens-Above, or per-satellite optical-observation references) so the table is auditable and extensible. Untraceable "looks about right" values are not acceptable.

---

## 4. Conventions

These are enforced at module boundaries. Violating them is a bug.

### Units

- **Internal: SI everywhere.** Meters, seconds, radians, kilograms.
- **I/O: human-friendly.** Kilometers, degrees, days at the user-facing boundary.
- Orekit is SI internally, which helps.

### Time

- All time values inside `propygator` are `propygator.Epoch` instances — a Python wrapper that carries an explicit time scale (UTC, TAI, TT, UT1) and lazily constructs the Orekit `AbsoluteDate` when an Orekit call needs it.
- User input: UTC ISO strings or timezone-aware `datetime` objects, parsed at the boundary via `Epoch.from_iso(...)` / `Epoch.from_datetime(...)`. Naive `datetime` objects are rejected at parse time.
- Internal convention: UTC for user-facing values, TT for dynamics. Conversions are explicit (`epoch.in_scale(TimeScale.TT)`), not implicit.

### Frames

- All frame values inside `propygator` are `propygator.Frame` enum members. Each member knows how to produce its Orekit counterpart on demand.
- v1 supported set: `Frame.EME2000` (with `Frame.J2000` as an alias of the same enum member), `Frame.ITRF`, `Frame.TEME` (for SGP4 output).
- Explicit on every `State` object. No defaults. A function returning "position" without a frame is a bug.

### State representation

- Canonical internal form: **Cartesian (position + velocity) in EME2000** (also accessible as `Frame.J2000`).
- Conversions to Keplerian, equinoctial, TLE mean elements provided as needed.
- Don't let multiple representations float around with different conventions.

### Paths

- All filesystem paths use `pathlib.Path` throughout the codebase. No string concatenation for path construction, no `os.path.join`.

---

## 5. Repository structure

Modern Python `src/` layout. Forces proper installation, catches path-import bugs.

```
propygator/
├── src/
│   └── propygator/              # importable package
│       ├── __init__.py
│       ├── _orekit_init.py
│       ├── core/
│       ├── propagation/
│       ├── tle/
│       ├── tracking/
│       ├── plotting/
│       └── io/
├── tests/                       # mirrors src/propygator/ structure
├── notebooks/                   # numbered demos: 01_intro.ipynb, etc.
├── docs/                        # MkDocs source
│   └── verified_environments/   # conda list snapshots for sanity checks
├── data/                        # small reference data (NOT orekit-data),
|                                # the bundled low-resolution Natural Earth
|                                # coastline lives here
├── scripts/
│   └── download_orekit_data.py  # downloads & extracts orekit-data
├── pyproject.toml               # project metadata, pip dependencies
├── environment.yml              # conda env spec (Orekit + Java + dev install)
├── .pre-commit-config.yaml      # pre-commit hooks
├── README.md
├── LICENSE                      # MIT
└── .gitignore
```

### Key files

**`pyproject.toml`** — modern project metadata. Lists pip-installable deps (numpy, matplotlib, plotly, requests). Does **not** list Orekit (conda handles it).

**`environment.yml`** — conda spec. Pins Python 3.11, OpenJDK 17, orekit_jpype. Its `pip:` block contains `- -e .`, installing the project in development mode as part of env creation. Single source of truth for the environment.

**`.gitignore`** — excludes `__pycache__/`, `*.pyc`, `.pytest_cache/`, `dist/`, `build/`, `*.egg-info/`, `.ipynb_checkpoints/`, `.env`, and `orekit-data/` if kept in tree.

### Notebooks

- Live at `notebooks/`, **not** inside the package
- Numbered for ordering: `01_intro.ipynb`, `02_numerical_propagation.ipynb`, etc.
- Notebook output stripping handled by the pre-commit setup below
- Rendered to HTML via `jupyter nbconvert` for the projects page

### Pre-commit hooks

A `.pre-commit-config.yaml` enforces repo hygiene automatically. Each contributor runs `pre-commit install` once per clone; from then on, hooks fire on every commit.

**Essential hook:**
- `nbstripout` — strips notebook outputs so notebook diffs stay readable and the repo doesn't bloat with cell outputs (binary images, JSON output blobs). Without this, notebook PRs become unreviewable. This hook alone justifies the pre-commit setup for this project.

**Recommended hooks:**
- `ruff` (lint + format) — replaces flake8/black/isort, fast
- `mypy` — type checking on changed files; configured with `--ignore-missing-imports` for the JPype-generated `org.orekit.*` namespace
- File hygiene: `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-toml`

CI runs the same hooks via `pre-commit run --all-files` so contributors who don't install locally are still caught.

### Documentation

- MkDocs + Material theme for Phase 1 (lightweight, pretty, Markdown-based)
- `mkdocstrings` for auto-generated API docs from docstrings
- Sphinx if PDF output or scientific-Python conventions become important later

### CI

- GitHub Actions, free for public repos.
- Tier 1 matrix: Ubuntu latest, Python 3.11 (matches the development environment). Multi-OS and multi-Python expansion deferred until a concrete bug motivates it; Windows users are directed to WSL2 in the README.
- Tests run on push to main and on PRs.
- Conda environment is cached between runs via `mamba-org/setup-micromamba` so re-runs take seconds rather than minutes.
- CI step downloads orekit-data via `scripts/download_orekit_data.py` so the dataset doesn't need to be checked in.
- Even minimal CI signals "maintained project".

### Versioning

Semantic versioning. Pre-1.0 is the unstable phase: breaking changes are allowed in minor releases (0.x → 0.(x+1)) and will be called out in the changelog. From 1.0 onward, breaking changes are reserved for major releases.

---

## 6. Core data model

These types are the lingua franca. Every module produces or consumes these. `Epoch` and `Frame` are the boundary types that keep Orekit's Java-backed objects from leaking into public APIs.

### `Epoch`

Python wrapper for a time value. Carries an explicit time scale and lazily constructs the Orekit `AbsoluteDate` when an Orekit call needs it. Internal storage is a two-double form `(int_seconds: int64, frac_seconds: float64)` that matches Orekit's internal precision (femtoseconds over decades) — a plain `float64` would lose roughly nine orders of magnitude of precision relative to Orekit's `AbsoluteDate`.

**Storage invariants** (enforced by every constructor and mutating method):

- The integer part is always **TAI seconds since the J2000 epoch**, regardless of the user-visible `scale`. The reference instant is Orekit's `AbsoluteDate.J2000_EPOCH`: 2000-01-01T12:00:00 TT, which is 2000-01-01T11:59:27.816 TAI (the TT−TAI offset is a fixed 32.184 s). The same physical instant is named differently in different scales; the count of seconds we store is measured in TAI, which is the only continuous, leap-second-free linear scale. The `scale` field tags the *presentation* scale for output (`to_iso`, `to_datetime`) but never changes what the integer means.
- `_frac_seconds ∈ [0.0, 1.0)`. Operations that produce out-of-range fractions (e.g. `shifted_by` with a non-integer offset, or scale conversions that introduce sub-second offsets) must renormalize back into the canonical form.
- Leap-second source. UTC↔TAI at construction needs a leap-second table.
Because Epoch construction must work before JVM start (§10), propygator
bundles a small static table (core/_leap_seconds.py, refreshed per release)
rather than reading orekit-data. This keeps the TAI integer eager and all
Epoch methods pure-Python; at first JVM touch the bundled table is
cross-checked against orekit-data's UTC-TAI.history (mismatch → warning).
UT1 is the exception: UT1↔TAI needs continuously-varying EOP, which cannot
be bundled, so UT1-scale construction defers normalization to first JVM
touch and is NOT part of the safe-before-init surface.

```python
@dataclass(frozen=True)
class Epoch:
    _int_seconds: int            # TAI seconds since J2000 TAI (integer part)
    _frac_seconds: float         # sub-second fraction in [0.0, 1.0)
    scale: TimeScale             # presentation scale: UTC, TAI, TT, UT1

    @classmethod
    def from_iso(cls, iso: str, scale: TimeScale = TimeScale.UTC) -> "Epoch": ...
    @classmethod
    def from_datetime(cls, dt: datetime, scale: TimeScale = TimeScale.UTC) -> "Epoch":
        # Rejects naive datetimes (tzinfo is None) at the boundary.
        ...
    @classmethod
    def now(cls, scale: TimeScale = TimeScale.UTC) -> "Epoch": ...

    def in_scale(self, scale: TimeScale) -> "Epoch": ...
    def shifted_by(self, seconds: float) -> "Epoch": ...
    def to_iso(self) -> str: ...
    def to_datetime(self) -> datetime: ...   # always tz-aware

    if TYPE_CHECKING:
        # Annotation-only; no runtime Orekit import for the type.
        def to_orekit(self) -> "org.orekit.time.AbsoluteDate": ...
    else:
        def to_orekit(self): ...
```

**Pure-Python rule.** All `Epoch` methods listed above are pure-Python and do not touch the JVM. Only `to_orekit()` crosses into Orekit. This is part of the lazy-JVM contract (see §10) — constructing `Epoch`s before `propygator.init(vmargs=...)` must be safe, or the explicit-init path is unusable.

The two-double form is shared with `Trajectory`'s array storage so single-epoch and array-of-epochs use the same representation.

### `Frame`

An enum-style sentinel. Each member knows how to produce its Orekit counterpart on demand.

```python
class Frame(Enum):
    EME2000 = "EME2000"   # canonical; Orekit's preferred name for the frame
    J2000   = "EME2000"   # same value → automatic alias of EME2000
    ITRF    = "ITRF"      # IERS 2010 conventions
    TEME    = "TEME"      # SGP4 output frame

    def to_orekit(self): ...   # returns org.orekit.frames.Frame
```

`Frame.J2000` and `Frame.EME2000` resolve to the same enum member via Python's standard enum-alias mechanism (members declared with an already-used value become aliases of the canonical member). `EME2000` is canonical because Orekit prefers that name (`FramesFactory.getEME2000()`); `J2000` is the alias for user-facing readability since the two names refer to the same frame — mean equator and equinox of J2000.0. `Frame.J2000 is Frame.EME2000` is `True`, `Frame("EME2000")` returns the canonical member, and `list(Frame)` skips the alias.

(There is a small frame-bias of tens of milliarcseconds between EME2000 and GCRF, the ICRF realization — but that is a separate frame and is not part of the v1 supported set. It is not a J2000-vs-EME2000 difference.)

The supported set is intentionally small in v1. Relative-motion frames (RTN/LVLH) are deferred — see §13.

### `State`

The canonical "where is this object, when, in what frame."

```python
@dataclass(frozen=True)
class State:
    epoch: Epoch                 # propygator type, explicit scale
    position: np.ndarray         # meters, shape (3,), float64
    velocity: np.ndarray         # m/s, shape (3,), float64
    frame: Frame                 # explicit, no defaults

    def __post_init__(self):
        # Runtime shape/dtype validation. Type annotations don't enforce these,
        # and a buggy code path that produces shape (1,3) or float32 propagates
        # far from the construction site.
        if self.position.shape != (3,) or self.velocity.shape != (3,):
            raise ValueError(
                f"position and velocity must have shape (3,), "
                f"got {self.position.shape} and {self.velocity.shape}"
            )
        if self.position.dtype != np.float64 or self.velocity.dtype != np.float64:
            raise ValueError("position and velocity must be float64")

        # Finiteness: reject NaN/inf at the construction site so a bad state
        # can't reach the propagator and surface later as an opaque Orekit
        # failure. np.isfinite is False for both NaN and inf.
        if not (np.all(np.isfinite(self.position))
                and np.all(np.isfinite(self.velocity))):
            raise ValueError("position and velocity must be finite (no NaN or inf)")

    def to_frame(self, target_frame: Frame) -> "State": ...
    def to_keplerian(self) -> "KeplerianElements": ...

    if TYPE_CHECKING:
        def to_orekit(self) -> "org.orekit.propagation.SpacecraftState": ...
    else:
        def to_orekit(self): ...
```

Immutable. Frame mandatory. No Orekit types appear in the public field annotations.

### `KeplerianElements`

The classical-element representation returned by `State.to_keplerian()` and accepted by `KeplerianElements.to_state(epoch, frame)`. Full spec deferred to implementation, but two conventions are pinned now to avoid silent bugs:

- **Angle convention:** the stored angular anomaly is the **true anomaly** ν. Mean and eccentric anomaly are available via methods (`.mean_anomaly()`, `.eccentric_anomaly()`), not as alternate fields. A single canonical anomaly avoids the "which one is this?" class of bugs.
- **Units:** SI throughout (semi-major axis in meters, angles in radians, time-derivatives where applicable in SI). Conversion to degrees happens at the user-facing boundary, not in the dataclass.
- Frame. Classical elements are frame-dependent (i and Ω are measured against
  the frame's equator/reference direction). to_keplerian() computes in the
  State's own frame; no implicit conversion. CSV element columns, however, are
  always computed in EME2000: export_csv converts the trajectory to EME2000 for
  every column (matching the default x/y/z_eme2000 columns) regardless of the
  input trajectory's frame, and has no per-frame element switch. So a 1.3 TEME
  trajectory's opt-in Keplerian columns are reported in EME2000, not TEME. Note
  a, e, ν (and the mean-anomaly token M) are rotation-invariant between inertial
  frames, so only i, Ω, ω would ever differ by frame — the EME2000-vs-TEME
  distinction is confined to those three angles. This is distinct from
  TLE.from_state_unfitted, which uses TEME osculating elements by design
  (features §1.3).
- Singularities. ω and ν are individually ill-conditioned as e→0 (only their
  sum, the argument of latitude, is well-defined); Ω is ill-conditioned as
  i→0. Orekit returns finite values but they go erratic for the near-circular
  LEO orbits this library targets. Documented in the docstring; equinoctial
  elements are a future opt-in.

### `Orientation`
A propygator-native rotation: the body→inertial orientation returned by
CustomAttitude laws, so user code never imports Hipparchus. Built from a
quaternion, axis-angle, or 3×3 matrix; lazily constructs the Orekit/Hipparchus
Rotation in to_orekit() (same lazy-JVM pattern as Epoch). Orientation only —
attitude rates are out of scope for v1 and default to zero.

### `Trajectory`

The output of any propagation. Backed by NumPy arrays for efficiency at the scale of routine multi-day propagations (10³–10⁵ samples); the column-oriented layout gives ~4–5× memory savings over a `list[State]` plus much better locality for vectorized frame transforms and exports. The list-of-`State` view is preserved via iteration and indexing.

```python
@dataclass
class Trajectory:
    # Backing arrays — column-oriented for memory locality
    _epochs_int: np.ndarray       # int64, shape (N,), TAI seconds since J2000
    _epochs_frac: np.ndarray      # float64, shape (N,), sub-second fraction
    epoch_scale: TimeScale        # scale tag for all epochs
    positions: np.ndarray         # float64, shape (N, 3), meters
    velocities: np.ndarray        # float64, shape (N, 3), m/s
    frame: Frame
    metadata: "TrajectoryMetadata"

    def __post_init__(self):
        # Validate first, then freeze. If any validation raises, the object
        # never reaches the caller (the exception propagates out of __init__),
        # so freezing-before-validating wouldn't leak a partially-built object —
        # the ordering is about error-message quality and conceptual cleanliness:
        # freeze is the last step after the object is known valid.

        # 1. Metadata: required keys present.
        required = {"propygator_version", "orekit_version", "propagator"}
        missing = required - self.metadata.keys()
        if missing:
            raise ValueError(
                f"Trajectory metadata missing required keys: {missing}"
            )

        # 2. Shapes and dtypes of the backing arrays.
        #    (Detailed checks deferred to implementation: int64 for _epochs_int,
        #    float64 for _epochs_frac/positions/velocities, shape (N,) for
        #    epoch arrays and (N, 3) for positions/velocities, consistent N.)
        ...

        # 2b. Epochs strictly increasing in time. at() uses the first/last
        #     samples as the span endpoints and the Ephemeris that backs it
        #     assumes chronologically ordered, distinct samples, so an unsorted
        #     or duplicate-epoch trajectory is rejected at construction.

        # 3. Freeze backing arrays. Users who need to mutate can call .copy()
        #    on the returned arrays.
        for arr in (self._epochs_int, self._epochs_frac,
                    self.positions, self.velocities):
            arr.setflags(write=False)

    def __len__(self) -> int: ...
    def __getitem__(self, i: int) -> State: ...   # materializes one State
    def __iter__(self) -> Iterator[State]: ...

    @classmethod
    def from_states(cls, states: list[State]) -> "Trajectory":
        """Construct from a list of State objects. All states must share the
        same frame and epoch scale. Convenient for small trajectories; for
        large N, prefer from_arrays."""
        ...

    @classmethod
    def from_arrays(
        cls,
        epochs: list[Epoch] | np.ndarray,       # see Epoch-input contract below
        positions: np.ndarray,                  # shape (N, 3), float64, meters
        velocities: np.ndarray,                 # shape (N, 3), float64, m/s
        frame: Frame,
        epoch_scale: TimeScale = TimeScale.UTC, # used only when epochs is ndarray
        metadata: "TrajectoryMetadata | None" = None,
    ) -> "Trajectory":
        """Construct from raw arrays. Validates shapes, dtypes, strictly
        increasing epochs, and (for the list-of-Epoch form) that all epochs
        share a single TimeScale.

        Epoch-input contract:
          * list[Epoch]   — preserves full femtosecond-class precision; the
                            per-epoch `scale` must be uniform across the list.
                            `epoch_scale` is ignored. Best for moderate N where
                            constructing Epochs in Python is acceptable.
          * np.ndarray    — must be dtype `datetime64[ns]`, 1-D, shape (N,).
                            Interpreted as wall-clock time in the scale given
                            by the `epoch_scale` keyword. Nanosecond precision
                            is sufficient for observational data (1 ns at LEO
                            velocity is well under a millimeter of position
                            error). Best for the large-N observational path.
                            NOT intended for round-tripping internal high-
                            precision epochs; internal propagator paths use the
                            two-double form directly via a private constructor.
                            Precision-mismatch note: Epochs constructed via
                            this path carry nanosecond precision, but Epoch's
                            two-double storage and Orekit's AbsoluteDate are
                            femtosecond-class. A user who builds a Trajectory
                            via from_arrays(datetime64[ns]) and then exports
                            an Epoch via .to_orekit() gets an AbsoluteDate
                            whose effective precision is ns, not fs. This is
                            fine for any v1 use case but worth being aware of
                            if sub-nanosecond timing ever matters.

        Metadata, if None, is populated with a minimal required-key dict."""
        ...

    def at(self, epoch: Epoch) -> State:
        """Interpolated state lookup. Uses Orekit's Ephemeris with Hermite
        interpolation on the underlying samples, which keeps (p, v) consistent
        by construction. The Ephemeris is built on first call and cached on
        the Trajectory instance.

        Raises ValueError if `epoch` is outside the trajectory's span — no
        extrapolation. Users who want denser sampling should re-propagate
        with a smaller output_step.

        The returned State is in the same frame as the Trajectory; call
        .to_frame(...) on the result to convert."""
        ...

    def to_dataframe(self) -> pd.DataFrame: ...
    def to_frame(self, frame: Frame) -> "Trajectory": ...
```

`metadata` is the reproducibility hook (see below). Backing-store details are leading-underscore — users get `State` objects via iteration; downstream code that needs raw arrays can read the public-named arrays directly. The arrays are read-only by default; the read-only flags are documented in the `Trajectory` docstring.

**Immutability contract.** `Trajectory` is intentionally *not* a frozen dataclass — the `Ephemeris` for `at()` is cached as a private attribute on first call, which requires attribute writes. The read-only flags on `_epochs_int`, `_epochs_frac`, `positions`, and `velocities` protect the *array contents*; the attribute *bindings* are not enforced-immutable, but mutating them (e.g. `traj.frame = Frame.ITRF`) is unsupported and will corrupt invariants. This matches the looser immutability discipline of NumPy and pandas, where the data is the protected surface and rebinding attributes on a returned object is "don't do that" rather than mechanically prevented.

**Supported construction path.** Users construct `Trajectory` via `from_states` or `from_arrays`. Direct invocation of the dataclass `__init__` (e.g. `Trajectory(_epochs_int=..., _epochs_frac=..., ...)`) is not part of the supported API; it exists only so the propagator internals can build trajectories efficiently. Direct construction will hit the `__post_init__` validator and is responsible for supplying the full required metadata dict — `from_arrays` and `from_states` handle that for you.

**`to_frame()` allocation contract.** Returns a new `Trajectory` with freshly allocated, read-only `positions` and `velocities` arrays (not views into the source). Epoch arrays and `metadata` may be shared with the source since they aren't frame-dependent.

### `TrajectoryMetadata`

A `TypedDict` (not a dataclass) so the type checker enforces required reproducibility fields without forcing users into a constructor or rejecting user-added keys at runtime. Runtime presence of the required keys is additionally enforced by `Trajectory.__post_init__` so the reproducibility export pipeline can rely on them.

```python
class TrajectoryMetadata(TypedDict, total=False):
    # Required for reproducibility; checker-enforced AND runtime-validated
    # in Trajectory.__post_init__.
    propygator_version: Required[str]
    orekit_version: Required[str]
    propagator: Required[str]             # "numerical" | "sgp4" | "user"

    # Optional — populated when applicable.
    force_models: list[str]
    integrator: str
    integrator_tolerances: dict
    output_step_s: float
    created_at: str                        # ISO UTC
    spacecraft: str
    attitude: str
    name: str
    tle_line1: str
    tle_line2: str
    norad_id: int                          # catalog number; mirrors TLE.norad_id (int)
    tle_epoch: str                         # ISO 8601 UTC
    start: str                             # ISO 8601 UTC
    # Termination reporting (drag-validity & altitude-guards addendum §6.6) —
    # written ONLY when a guard stops the run early (impact, escape, re-entry, or
    # a reasonable user-limit crossing); additive/optional, NOT in the required set,
    # so a normal completed run's metadata is byte-identical to before the guards.
    terminated: bool
    termination_reason: str                # reentry|impact|escape|user_min|user_max
    termination_epoch: str                 # ISO 8601 UTC of the crossing
    # Extensible: user code may add arbitrary keys (e.g. "experiment_id").
```

`total=False` plus `Required[...]` on the reproducibility keys means: the listed required fields *must* be present and type-checked, every other listed field is optional, and arbitrary user-added keys pass through at runtime (TypedDict doesn't reject extras at runtime; the checker flags unknown keys only when strict mode is on). The `Trajectory.__post_init__` validator closes the gap between the static guarantee and the runtime guarantee. Relies on `typing.Required`, which is Python 3.11+ — consistent with the existing 3.11 pin.

### `TLE`

Wraps Orekit's TLE class with friendlier construction and validation.

```python
@dataclass(frozen=True)
class TLE:
    line1: str
    line2: str
    name: str | None = None

    @classmethod
    def from_strings(cls, line1: str, line2: str, name=None) -> "TLE": ...
    @classmethod
    def from_norad_id(cls, norad_id: int, source: str = "celestrak") -> "TLE": ...
    @classmethod
    def from_state_unfitted(cls, state: State, *, norad_id: int | None = None,
                            bstar: float | None = None, name: str | None = None) -> "TLE": ...

    @property
    def epoch(self) -> Epoch: ...
    @property
    def norad_id(self) -> int: ...

    if TYPE_CHECKING:
        def to_orekit(self) -> "org.orekit.propagation.analytical.tle.TLE": ...
    else:
        def to_orekit(self): ...
```

`from_state_unfitted` builds a *format-valid* TLE from a state's osculating elements (converted to TEME internally, with true anomaly mapped to mean anomaly); `norad_id` and `bstar` are optional and default to placeholders (`00000` / `0.0`) when not supplied — a bare `State` carries neither, so there is nothing to recover from it. It is not round-trip-faithful: osculating elements placed in mean-element fields do not reproduce the state under SGP4, and a placeholder `bstar=0.0` strips drag entirely. The `unfitted` in the name flags this; for a faithful fit use `fit_tle` (§8 / feature 1.2). See `features.md` §1.3 for the full rationale.

### `GroundStation`

```python
@dataclass(frozen=True)
class GroundStation:
    name: str
    latitude_deg: float
    longitude_deg: float
    altitude_m: float = 0.0
```

### `GeodeticPosition`

The output type of `to_geodetic(state)`, which converts a `State` in an Earth-fixed frame (ITRF) to lat/lon/altitude. Used by the real-time tracking surface and by anyone who needs "where on Earth is this satellite right now."

```python
@dataclass(frozen=True)
class GeodeticPosition:
    latitude_deg: float
    longitude_deg: float
    altitude_m: float          # geodetic altitude above the WGS84 ellipsoid
```

`to_geodetic` lives in `core/frames.py` (not in `tracking/`) because it's a pure coordinate transformation operating on `State` + `Frame` — both `core/` types — and because the `tracking/` → `core/` dependency direction (§7) means anything `tracking/` might want to reuse must be reachable from `core/`. The function requires an Earth-fixed input frame; passing a `State` in J2000/TEME raises `ValueError` rather than silently auto-converting (consistent with the explicit-frame-conversion rule, §10).

### `AzElRange` and `look_angles`

The topocentric look angles of a satellite from a ground station — the observer-centric counterpart to `to_geodetic`. `look_angles(station, state)` returns the azimuth, elevation, and slant range of `state` as seen from `station`:

```python
@dataclass(frozen=True)
class AzElRange:
    azimuth_deg: float       # 0 = North, increasing clockwise toward East
    elevation_deg: float     # 0 = horizon, +90 = zenith (negative = below horizon)
    range_m: float           # straight-line station → satellite distance


def look_angles(station: GroundStation, state: State) -> AzElRange: ...
```

`look_angles` and `AzElRange` live in `core/observation.py` (with `GroundStation`), co-located so the observe-primitive and its output type sit beside the observer type they key on. Like `to_geodetic` the *function* is placed in `core/` so both `tracking/` (Feature 1.5's `find_passes`) and `plotting/` (Feature 1.4's `plot_sky_track`) can reach it without inverting the inward dependency rule (§7); building it on the canonical WGS84 Earth ellipsoid (`core/bodies.py`), it internally constructs an Orekit `TopocentricFrame` at the station's geodetic point, so it **touches the JVM** and lazy-imports jpype inside the function body. `core/observation.py` therefore stays JVM-free on *import* — the value types (`GroundStation`, `GeodeticPosition`, `Pass`, `AzElRange`) remain safe-before-init — while this one *call* does not. Its result carries no `Frame`, so unlike `to_geodetic` it need not demand a particular input frame: per the explicit-frame rule (§10, which governs only frame-carrying `State`/`Trajectory` returns) it may convert its input internally.

Introduced for Feature 1.4's live sky view (features §1.4) but shared verbatim with Feature 1.5's pass finder, so building it in 1.4 brings 1.5's topocentric foundation forward.

Feature 1.4 adds four siblings in the same module, sharing one topocentric kernel: `look_angles_track(station, trajectory)` — the batched analogue of `geodetic_track`, returning parallel az/el/range arrays (but **not** memoized on the `Trajectory`, since it is station-keyed); `sun_look_angles(station, epoch)` / `moon_look_angles(station, epoch)`, the same kernel projecting the Sun/Moon for the live sky panel's tint/markers and for 1.5's observer-darkness gate; and `observer_snapshot(station, epoch, state)`, which builds the station frame once and projects the satellite + Sun + Moon together (the live dashboard's per-frame batch). All are JVM-touching like `look_angles` (on the §10 JVM-startup list); only the `AzElRange` value type is safe-before-init (features §1.4).

### `Pass`

Output of pass prediction.

```python
@dataclass(frozen=True)
class Pass:
    rise: Epoch
    culmination: Epoch
    set: Epoch
    max_elevation_deg: float
    peak_magnitude: float | None     # None if not computed
    sunlit_at_culmination: bool
```

---

## 7. Module structure

```
src/propygator/
├── __init__.py
│       Exposes most-used names: State, Trajectory, TLE, Epoch, Frame,
|       TimeScale, KeplerianElements, Orientation, GroundStation, Pass,
|       GeodeticPosition, AzElRange, ForceModelConfig, SpacecraftConfig,
|       SpacecraftGeometry, VariableCd, BoxFaceCd, IntegratorConfig,
|       AltitudeLimits, the attitude family, propagate_numerical,
|       propagate_tle, fit_tle, fetch_tle, current_state,
|       current_ground_position, find_passes, look_angles, sun_look_angles,
|       moon_look_angles (look_angles_track, the batched array form, stays
|       in propygator.core.observation), the plot_*/export* functions, init,
|       clear_cache, and the exception types. (BoxFaceCd, the shipped Tier-B
|       per-face convex-box drag table, is top-level beside VariableCd.)
|       Verbs beyond Feature 1.1 are added to this list as their features
|       land.
│       Also exposes init() for explicit JVM configuration.
│       Attaches logging.NullHandler() to the "propygator" logger so the
│       library is silent unless the application configures handlers.
│       Importing does NOT start the JVM — see _orekit_init.py.
│
├── _orekit_init.py
│       JVM startup (lazy), orekit-data loading.
│       Resolves orekit-data path via the search order in §3
│       (OREKIT_DATA_PATH → ~/.propygator/orekit-data/ → ./orekit-data/);
│       raises OrekitDataMissingError if none resolve.
│       Reads PROPYGATOR_VM_ARGS for default JVM args.
│       Exposes init(vmargs=...) for explicit pre-use configuration.
│       Lazy: JVM starts on first Orekit-touching call, not on import.
│
├── core/
│   ├── time.py          Epoch class, TimeScale enum, parse helpers
│   ├── frames.py        Frame enum + Orekit-counterpart lookup
│   │                    + to_geodetic(state) -> GeodeticPosition
│   ├── states.py        The State class, conversions to/from Orekit types
│   ├── elements.py      KeplerianElements, conversions to/from State
│   ├── tle.py           The TLE type (two-line element set): pure-Python parse,
│   │                    mod-10 checksum, and .epoch / .norad_id accessors (all
│   │                    safe before init), plus the JVM-touching to_orekit() and
│   │                    the JVM/network-touching from_state_unfitted /
│   │                    from_norad_id constructors. Holds the TLE parse/checksum
│   │                    directly (no separate tle/parsing.py — features §1.3
│   │                    Decision a). See §6.
│   ├── sampling.py      Propagator-agnostic output-sample grid: _sample_count,
│   │                    the epoch-grid generator, the _MAX_OUTPUT_SAMPLES cap,
│   │                    and the shared pre-flight checks (duration/output_step
│   │                    positive + ordered). Promoted out of propagation/
│   │                    numerical.py so both propagate_numerical and
│   │                    propagate_tle (tle/ may import only from core/, §7 dep
│   │                    rule) share one contract-bearing helper and produce
│   │                    identically-gridded trajectories (features §1.3;
│   │                    build-plan notes #7).
│   ├── bodies.py        Earth model (canonical instance), Sun, Moon
│   ├── observation.py   GroundStation, Pass, GeodeticPosition, AzElRange,
│   │                    look_angles(station, state) -> AzElRange (topocentric
│   │                    az/el/range; JVM-touching, shared with find_passes; Feature 1.4 also adds
│   │                    look_angles_track / sun_look_angles / moon_look_angles /
│   │                    observer_snapshot to this one shared kernel).
│   │                    In core/ so io/ can import them without violating
│   │                    the "io depends only on core" rule (§7 dep rule).
│   └── catalogs.py      Popular satellite registry (friendly name → NORAD ID)
│                        + standard-magnitude table for visibility calcs.
│                        Reference data, not I/O — lives in core/ so the
│                        dependency direction stays clean.
│
├── propagation/
│   ├── numerical.py     propagate_numerical(initial, duration, *,
│   │                                        output_step, force_models=None,
│   │                                        spacecraft=None, attitude=None,
│   │                                        integrator=None, limits=None,
│   │                                        name=None)
│   │                    All inputs after duration are keyword-only;
│   │                    output_step is required (user-controlled).
│   │                    integrator is an optional IntegratorConfig;
│   │                    defaults to DOP853 with sensible tolerances.
│   │                    limits is an optional AltitudeLimits (guards.py).
│   │                    Imports the output-sample grid + cap from
│   │                    core/sampling.py (shared with propagate_tle) rather
│   │                    than defining them locally.
│   │                    Full binding signature: features §1.1.
│   ├── force_models.py  ForceModelConfig + presets (leo_default,
│   │                    geo_default, keplerian)
│   ├── spacecraft.py    SpacecraftConfig, SpacecraftGeometry (sphere /
│   │                    box_and_panels factories), VariableCd, and the
│   │                    shipped Tier-B BoxFaceCd per-face convex-box table
│   ├── attitude.py      holds the AttitudeConfig family
│   ├── integrators.py   IntegratorConfig (tolerances, min/max step)
│   └── guards.py        AltitudeLimits + the altitude/regime guard system:
│                        impact/escape radius detectors, the min-step
│                        re-entry catch, and the Knudsen-floor + table-edge
│                        drag-regime warnings (drag-validity & altitude-
│                        guards addendum; architecture §6/§13).
│
├── tle/
│   ├── propagator.py    propagate_tle(tle, duration, *, output_step,
│   │                    start=None, name=None)
│   │                    duration required, positional-or-keyword (aligned
│   │                    with 1.1, features §1.3); output_step required and kw-only,
│   │                    with no default (dropped for 1.1 consistency, features §1.3); start
│   │                    defaults to tle.epoch.
│   │                    Default output frame: TEME. Reuses the shared
│   │                    output-sample grid + cap from core/sampling.py.
│   ├── fitter.py        fit_tle(reference, fitting_span, ...)
│   │                    Accepts State (then propagates internally) or
│   │                    Trajectory (used directly). See §8.
│   └── sources.py       fetch_tle, fetch_celestrak (fetch_spacetrack deferred)
│                        Caches to ~/.propygator/cache/
│                        fetch_tle(name_or_id, source='celestrak')
│                        (v1: CelesTrak only; 'auto'/Space-Track deferred)
│                        Two TTLs: 6h (realtime workflows), 24h (general).
│                        Transport failures (no network / DNS / timeout / HTTP
│                        error) raise TLEFetchError (architecture §3).
│                        (No tle/parsing.py — the TLE parse/checksum lives on the
│                        TLE type in core/tle.py; features §1.3 Decision a.)
│
├── tracking/
│   ├── realtime.py      current_state(tle) -> State
│   │                    Returns the satellite state in TEME (the natural
│   │                    SGP4 output frame). Users wanting J2000 or ITRF
│   │                    call .to_frame(...) on the result.
│   │                    current_ground_position(tle) -> GeodeticPosition
│   │                    Internally TEME→ITRF→geodetic; the user receives
│   │                    lat/lon/alt directly, no frame to convert.
│   ├── live.py          live_track(...) — the live dashboard (features §1.4).
│   │                    A rolling Trajectory buffer centred on now (propagate_tle;
│   │                    auto-refreshes the TLE when fetched) drives a matplotlib
│   │                    FuncAnimation over the 1.1 _draw_* primitives +
│   │                    _draw_sky_track (sky panel only with a GroundStation).
│   │                    Lazily imports plotting/ (the export_all precedent,
│   │                    dep rule below). Live display only; not saved.
│   ├── passes.py        find_passes(tle, station, start, duration,
│   │                                min_elevation_deg)
│   └── visibility.py    Eclipse check, sun angle, phase angle
│                        compute_magnitude(state, sun, observer, std_mag)
│                        Pulls the standard-magnitude table from core/catalogs.py.
│
├── plotting/
│   ├── trajectories.py  plot_3d (Plotly), plot_ground_track + _draw_ground_track
│   │                    (matplotlib), plot_sky_track + _draw_sky_track
│   │                    (matplotlib polar; takes a GroundStation, geometry-only
│   │                    observer view; built in 1.4, reused by 1.5 — features §1.4)
│   ├── timeseries.py    plot_altitude + _draw_altitude, plot_speed + _draw_speed
│   │                    (matplotlib — 2D timeseries; plot_speed is speed
│   │                    magnitude, not velocity components — features §1.1)
│   ├── composite.py     plot_summary — the default stacked GridSpec figure
│   │                    (ground track + altitude + one speed panel per frame),
│   │                    assembled from the _draw_* primitives (features §1.1)
│   ├── style.py         per-figure mplstyle context manager + Plotly template
│   ├── basemap.py       bundled low-res Natural Earth coastline overlay
│   │                    (_render_earth_basemap; no cartopy)
│   └── passes.py        plot_sky_chart (matplotlib polar; Feature 1.5,
│                        shares core look_angles with plot_sky_track, adds
│                        passes + brightness),
│                        plot_pass_timeline (matplotlib)
│
└── io/
    └── exports.py       Trajectory → CSV/JSON; Pass list → ICS/CSV
                         Writes TrajectoryMetadata to format-appropriate
                         locations (CSV header comments, JSON top-level key,
                         image file metadata via savefig metadata=).
```

### Dependency rule

Dependencies flow inward. `tracking/` can import from `propagation/` and `core/`; `propagation/` can import from `core/`; `tle/` can import from `core/`. `io/` is a pure I/O leaf — it depends on `core/` types and on nothing in `tracking/` or `propagation/`. **Nothing imports from `plotting/`** — it's a leaf. This keeps the core testable without a display.

**Sanctioned exception — `io/exports.py::export_all`.** `export_all` bundles the plots with the CSV, so it calls `plotting.plot_summary` / `plot_3d`. It imports them **lazily, inside the function body**, so `io/`'s static module graph stays `core`-only and the headless suites never pull `plotting/` through `io/`; the sole `io → plotting` edge exists only at call time, when the user has explicitly asked `export_all` to render figures. This honors features.md's placement of `export_all` beside `export_csv` and this section's own "`savefig`-at-`exports.py`" framing (the `io/exports.py` entry above already anticipates writing image-file metadata via `savefig`), while preserving the rule's intent (core testable without a display). The lazy import is the same idiom the package uses for the JVM and for the Sun body inside `export_csv`. Note the top-level `__init__` *separately* re-exports `plot_*`, so `import propygator` does load matplotlib (≈0.6 s) — a public-namespace choice, independent of this rule.

`core/catalogs.py` is reference data and may be imported by `tracking/`, `tle/sources.py`, and elsewhere. It does not import from any sibling subpackage.

---

## 8. Data flow per feature

### 1.1 Numerical propagation

```
User → State + ForceModelConfig + duration
     → propagation.numerical.propagate_numerical()
     → Trajectory
     → plotting.* / io.exports.*
```

### 1.2 TLE fitting

`fit_tle` accepts either a `State` or a `Trajectory` as its reference input:

```python
def fit_tle(
    reference: State | Trajectory,
    *,
    fitting_span: float = 86400.0 * 2,   # seconds; default 2 days
    force_models: ForceModelConfig | None = None,  # used only if reference is State
    initial_guess: TLE | None = None,
    max_iterations: int = 100,
) -> TLE:
    """Fit a TLE against a reference trajectory.

    If `reference` is a State, a numerical trajectory is generated over
    `fitting_span` using `force_models` (defaults to leo_default) and the
    fit is performed against that trajectory.

    If `reference` is a Trajectory, it is used directly and `force_models`
    is ignored (warning emitted if supplied). `fitting_span` is clipped to
    the trajectory's actual span.
    """
```

The two reference-input shapes correspond to three realistic user paths:

**(a) From a prior numerical propagation** — most common; refit a high-fidelity propagation result so the TLE can be shared with downstream tools.

```python
initial = pgr.State(epoch=..., position=..., velocity=..., frame=pgr.Frame.J2000)
ref_traj = pgr.propagate_numerical(initial, duration=86400 * 2,
                                  force_models=pgr.ForceModelConfig.leo_default(),
                                  output_step=60)
fitted = pgr.fit_tle(ref_traj)
```

**(b) From observational data assembled by the user** — radar or optical reductions expressed as positions and velocities at known times. The user constructs a `Trajectory` via `Trajectory.from_arrays` (or `from_states` for small N) and passes it in.

```python
traj = pgr.Trajectory.from_arrays(
    epochs=epoch_list,
    positions=positions_array,    # shape (N, 3), float64, meters
    velocities=velocities_array,  # shape (N, 3), float64, m/s
    frame=pgr.Frame.J2000,
)
fitted = pgr.fit_tle(traj)
```

**(c) From an existing TLE-propagated trajectory** — legal and useful for cross-checking SGP4 against itself; works without any new API since `propagate_tle()` returns a `Trajectory`.

```python
old_tle = pgr.fetch_tle("ISS")
old_traj = pgr.propagate_tle(old_tle, duration=86400)
refit = pgr.fit_tle(old_traj)
```

Single-state diagram:
```
User → State (observed)
     → propagation.numerical.propagate_numerical()  # reference trajectory
     → tle.fitter.fit_tle()                          # least-squares
     → TLE
```

Trajectory diagram:
```
User → Trajectory  (via from_arrays / from_states / earlier propagation)
     → tle.fitter.fit_tle()
     → TLE
```

A `FitResult` return type (carrying RMS residual, iteration count, convergence flag) is a future extension; v1 returns a bare `TLE`.

### 1.3 TLE propagation

```
User → TLE  (via fetch_tle / fetch_celestrak / direct input)
     → tle.propagator.propagate_tle()
     → Trajectory  (TEME, optionally converted)
     → plotting.* / io.exports.*
```

### 1.4 Real-time tracking

```
User → TLE
     → tracking.realtime.current_state()
     → State  (+ derived lat/lon/alt)
```

Live dashboard:

```
User → TLE or fetched name (+ optional GroundStation)
     → tracking.live.live_track()
            maintains a rolling Trajectory buffer centred on now (propagate_tle;
            trailing + leading path), samples buffer.at(now) per frame, redraws
            ground-track / altitude / speed — plus a sky panel only when a
            GroundStation is given — via the 1.1 _draw_* primitives +
            _draw_sky_track, and refreshes (re-propagate; re-fetch if fetched)
            as the buffer drains
     → matplotlib FuncAnimation  (desktop window or %matplotlib widget; live only)
```

### 1.5 Ground passes with brightness

```
User → TLE + GroundStation + time window
     → tracking.passes.find_passes()
            internally: propagate TLE → find horizon crossings →
            check elevation → check lighting → compute magnitude
     → list[Pass]
     → plotting.passes.* for sky charts
```

All paths converge on `Trajectory` or `State`, so plotting and export modules don't care where data came from.

---

## 9. Example user code

A typical notebook session:

```python
import propygator as pgr

# Pull ISS TLE
iss = pgr.fetch_tle("ISS")

# See where it is right now (returns a GeodeticPosition directly)
print(f"Lat/lon: {pgr.current_ground_position(iss)}")

# Propagate forward 1 day with SGP4 at 60-second output cadence
traj = pgr.propagate_tle(iss, duration=86400, output_step=60)

# Plot the ground track
pgr.plot_ground_track(traj).show()

# Find tonight's visible passes from Durham
durham = pgr.GroundStation("Durham", 35.99, -78.90, altitude_m=130)
passes = pgr.find_passes(
    iss, durham,
    start=pgr.Epoch.now(),
    duration=86400,
    min_elevation_deg=20,
)

for p in passes:
    print(f"Pass at {p.culmination.to_iso()}, max el {p.max_elevation_deg:.1f}°, "
          f"mag {p.peak_magnitude:.1f}")
```

Top-level `propygator` namespace exposes common verbs. Power users reach into submodules for fine control (e.g., `propygator.propagation.numerical.propagate_numerical` with custom `ForceModelConfig`). Same pattern as NumPy or pandas: convenient at the top, detailed underneath.

The function-based API is the contract. A `Satellite` convenience class is deliberately not provided in v1 (see §13).

---

## 10. Key architectural decisions

### Lazy JVM init, one JVM per process

The JVM is started **on first Orekit-touching call**, not on `import propygator`. This keeps imports cheap and — critically — gives users a window between `import` and first use during which they can configure JVM args via an explicit `propygator.init(vmargs=...)` call.

Three init paths:

1. **Implicit (typical case)** — `propagate_numerical(...)` or any other Orekit-touching function triggers JVM startup with default args on first call.
2. **Explicit (power case)** — `propygator.init(vmargs="-Xmx8g")` called after `import propygator` but before any Orekit-touching function. Used when defaults aren't right (large simulations, custom system properties).
3. **Env var** — `PROPYGATOR_VM_ARGS` is read by the implicit path, allowing customization without code changes.

**Late-init handling:** if `init()` is called after the JVM is already running, it raises `JVMAlreadyStartedError` if the requested args differ from what's running, no-ops if they match. The error message explains the JPype constraint and points to the env-var workaround. This is enforced because **JPype cannot re-initialize the JVM** — one shot per process.

**What does NOT touch the JVM.** For the explicit-init path to be usable, the user must be able to do work between `import propygator` and `propygator.init(...)` without inadvertently starting the JVM. The supported "safe before init" surface is:

- All `Epoch` constructors and methods *except* `to_orekit()`, and except construction in the UT1 scale (defers leap/EOP resolution to first JVM touch — see §6).
- All `Frame` enum access *except* `to_orekit()`.
- `State.__init__` and its validation (no Orekit calls in `__post_init__`).
- `Trajectory.from_states` / `from_arrays` shape and dtype validation.
- `TLE.from_strings` parsing and checksum validation, bare `TLE(...)` construction, and the `.epoch` / `.norad_id` accessors (all pure-Python).
- `GroundStation`, `Pass`, and `AzElRange` construction (the value types are pure-Python; only the `look_angles` / `look_angles_track` *calls* start the JVM — see below).
- VariableCd table construction and validation (the Orekit DragSensitive it lowers to is built inside propagate_numerical, not at config time).

JVM startup is reserved for: any `to_orekit()` call, `propagate_numerical`, `propagate_tle`, `fit_tle`, `TLE.from_state_unfitted` (it lowers the state to Orekit's TLE formatter), `current_state`, `current_ground_position`, `look_angles` / `look_angles_track` / `sun_look_angles` / `moon_look_angles` / `observer_snapshot` (they build an Orekit `TopocentricFrame`), `find_passes`, and `Trajectory.at()` (which builds the cached `Ephemeris`). `TLE.from_norad_id` / `fetch_tle` are **network-touching** (not JVM-touching) but likewise sit outside the safe-before-init surface. Code review and CI tests guard against accidental Orekit imports leaking into the "safe before init" surface.

### Orekit types stay internal

Public APIs accept and return `propygator` types (`Epoch`, `Frame`, `State`, `Trajectory`, `TLE`, `Orientation`). Custom attitude laws return propygator.Orientation, not a Hipparchus Rotation, so the rule holds with no exception. Orekit's Java-backed objects appear only inside module implementations. Where a public method exists to convert to an Orekit type (e.g. `State.to_orekit()`), the annotation uses `TYPE_CHECKING` so no runtime Orekit import is needed at the public type level. Benefits:

- Users don't need to know Orekit to use `propygator`
- Swapping backends affects only implementation
- IDE autocomplete works (real Python types, not JPype proxies)
- Pickling / serialization works (Orekit Java objects don't pickle)

Private cached references to Orekit objects (e.g. the `Ephemeris` cached on a `Trajectory` to back `at()`) are acceptable as implementation details — the rule is about public APIs, not internal caches.

### Frame conversions are explicit

No automatic conversions on `State`-returning paths. TLE propagation returns TEME; numerical propagation returns whatever frame the initial state was in (always EME2000); `current_state(tle)` returns TEME. Users explicitly call `.to_frame(...)` to convert. Verbose, but it prevents silent frame-mismatch bugs.

The rule applies specifically to functions that return `State` or `Trajectory` — types that carry a `Frame`. Functions returning derived non-`State` types (`GeodeticPosition`, `Pass`, scalar magnitudes) may convert internally because the result does not carry a frame and so no frame ambiguity escapes the function. For example:

- `current_ground_position(tle) -> GeodeticPosition` is allowed to internally do TEME→ITRF→geodetic.
- `find_passes(...) -> list[Pass]` is allowed to internally convert to topocentric.
- `compute_magnitude(state, ...) -> float` follows the same explicit-frame rule as `to_geodetic`: it requires its input `State` to be in a specific frame (raises `ValueError` otherwise), since it does carry a frame.

### Plotting: Plotly for interactive 3D, matplotlib for everything else

The split is along the axis of "does the user benefit from rotating/zooming this," not strictly along dimensionality:

- **Plotly** for 3D trajectories and any case where interactivity adds value. Renders well in notebooks and to standalone HTML (the §2 hosting plan needs this).
- **matplotlib** for everything else: altitude vs. time, orbital elements, sky charts (polar projection), pass timelines. matplotlib's defaults match scientific-paper aesthetics, polar projection is excellent for sky charts, and PNG output keeps the projects-page payload small (a single Plotly HTML embeds ~3 MB of plotly.js).
- Each `plot_*` function returns the native figure object (Plotly `Figure` or matplotlib `Figure`). No abstraction layer over the backends — users can post-process with the native API.

Per-feature plot specifications and CSV/JSON export shapes are a separate sub-design exercise, deferred to a follow-up doc.

### Caching: two TTLs

TLE fetches and force model loading cache to `~/.propygator/cache/`. Per-call `use_cache=False` skips the cache for that call; `propygator.clear_cache()` clears it explicitly.

`clear_cache()` v1 contract: a top-level, no-argument function that recursively removes the contents of `~/.propygator/cache/` (the directory itself is preserved). Selective clearing (by source, by satellite, by age) is out of scope for v1; if needed later, add it as keyword arguments on the same function for backward compatibility.

Two TTLs serve different workflows:

- **Realtime workflows** (`current_state`, `current_ground_position`): **6-hour TTL**. CelesTrak typically refreshes popular satellites several times per day, so a 6-hour TTL catches updates within roughly half a refresh cycle while avoiding pointless refetches of identical TLEs. **(Feature 1.4 plumbing — resolved.)** `current_state` / `current_ground_position` take a `TLE` directly and do **not** fetch, so this 6-hour TTL is realized only on the *fetch* that produced the TLE. Feature 1.4 surfaced the realtime TTL through `fetch_tle`: it now takes a keyword-only `ttl_s: float | None = None` (forwarded to `fetch_celestrak`; default `None` keeps the 24-hour general TTL), so the live/realtime path selects `_TTL_REALTIME_S` (6 h) while ordinary fetches stay at 24 h.
- **General fetches** (`fetch_celestrak`): **24-hour TTL**. Notebook re-runs within a day hit the cache; daily re-issues are picked up automatically. (Space-Track's `fetch_spacetrack` is deferred — §3.)

Note that the cache lives on the *fetch* path, not on `propagate_tle` (which takes a `TLE` directly). The TTL governs how often we re-hit the network, not the freshness of the underlying TLE epoch.

### Configuration via dataclass + presets

`ForceModelConfig` with named presets:

```python
ForceModelConfig.leo_default()      # 70x70 gravity, drag, SRP, Sun/Moon
ForceModelConfig.geo_default()      # higher gravity, no drag, SRP critical
ForceModelConfig.keplerian()        # point mass only, for tests
```

More discoverable than a long keyword-argument list. Integrator settings are factored out into a separate `IntegratorConfig` so propagation and integration concerns don't compete for parameter space.

### Logging

Use Python's `logging` module — never bare prints. One logger per module:

```python
logger = logging.getLogger(__name__)
```

The package's `__init__.py` attaches a `NullHandler` to the `propygator` root logger so the library is silent unless the application explicitly configures handlers:

```python
logging.getLogger(__name__).addHandler(logging.NullHandler())
```

Applications opt in to seeing logs via `logging.basicConfig(level=...)` or by setting the level on the `propygator` logger directly. Users control verbosity.

### Reproducibility

`Trajectory.metadata` (a `TrajectoryMetadata` TypedDict — see §6) is the in-memory source of truth for reproducibility info. The required fields (`propygator_version`, `orekit_version`, `propagator`) are populated automatically at construction; optional fields are populated when applicable. The required keys are enforced at runtime by `Trajectory.__post_init__`, so the export pipeline can rely on them.

On export, `io.exports` writes metadata to format-appropriate locations:

- **CSV** — header comment lines (`# propygator_version: 0.1.0`, etc.) before the data rows
- **JSON** — top-level `"metadata"` key alongside the trajectory data
- **PNG/SVG** — file metadata block via `matplotlib.savefig(..., metadata={...})` or Plotly's layout-metadata equivalent. Recoverable with `exiftool` or equivalent; doesn't clutter the figure.

Plot titles do **not** carry metadata. They stay visually clean; metadata lives in the file's metadata block.

### Credentials

Never commit. Use environment variables (`SPACETRACK_USERNAME`, `SPACETRACK_PASSWORD`) or a gitignored `.env` file via python-dotenv.

---

## 11. Testing strategy

- **Reference cases:** ISS TLEs (widely available, well-characterized), Vallado textbook examples (gold standard).
- **Cross-checks:** Numerical propagation of a Keplerian orbit (no perturbations) matches analytical Kepler within machine precision; SGP4 propagation matches published Vallado test-vector outputs to centimeters (this is *implementation-agreement* with the reference algorithm, **not** absolute accuracy against truth — accuracy of a TLE against reality is governed by the SGP4 model limitations described in §1.2 and degrades over time as drag and unmodeled perturbations dominate).
- **Snapshot tests for plots:** save reference figures, diff against them in CI.
- **Fixtures:** `tests/conftest.py` initializes JVM + orekit-data once per session.
- **Orekit-data discovery:** tests follow the same rule as user code — the search path in §3 is used, otherwise the test session aborts with the same `OrekitDataMissingError` and instructions. No test-only fallback path. CI provisions the data via `scripts/download_orekit_data.py`; local developers do the same once.

### Stack-compatibility tests

A small dedicated test set guards against silent breakage when conda dependencies update (especially around the NumPy ↔ JPype ↔ Orekit boundary):

- **(a) Smoke import** — `import propygator`, fetch a known TLE, materialize a `State` from `current_state`. Catches "imports but the JPype/NumPy boundary is broken" failures.
- **(b) Numerical round-trip** — propagate a known *point-mass* (Keplerian) orbit over exactly one Keplerian period and assert it returns to the initial state at machine-precision levels (10⁻⁸ relative or better). A closed two-body orbit is exactly periodic, so this **one-period closure** is a genuine there-and-back round-trip that stays inside the v1 forward-only contract — backward propagation is unsupported (`duration > 0`; features §1.1), so the literal "forward then backward" of the original design is realized this way. Catches "imports work but math is wrong" failures (e.g. silent dtype promotion changes in NumPy).
- **(c) Bulk-array round-trip** — construct a `Trajectory` with ~10⁵ samples, run `to_frame()`, run `to_dataframe()`, export to CSV, reload, compare. Catches dtype/promotion bugs in the vectorized paths. Explicitly assert `float64` for `positions`/`velocities` and `int64` for `_epochs_int` on the reloaded trajectory — NumPy 2.x changed some default-integer behaviour across point releases (e.g. earlier 2.x had platform-dependent int defaults on Windows; resolved by 2.1), and the test should be sensitive to dtype regressions even though Windows is not a supported platform.

These three tests are also the basis for the verified-environment snapshot in `docs/verified_environments/`.

---

## 12. Build order

Suggested implementation sequence:

1. **1.1 Numerical propagator** — core types, force model config, basic plotting
2. **1.3 TLE propagator** — shares plotting infrastructure with 1.1
3. **1.4 Real-time tracker** — the realtime primitives (`current_state` / `current_ground_position`) are cheap once 1.3 works, but 1.4 now also carries the **live buffered dashboard** (ground track / altitude / speed / sky view), making it the richest tracking feature. It first builds the `look_angles` primitive + `_draw_sky_track` (moved out of 1.3), so it still pulls Feature 1.5's topocentric foundation forward.
4. **1.5 Ground passes + brightness** — builds on 1.4 and visibility; reuses 1.4's `look_angles`. Adds a pass table plus the richer sky/timeline charts.
5. **1.2 TLE fitter** — hardest; lean on Orekit's built-in fitting machinery. Treated as a plus rather than a blocker.

**1.1 Numerical propagator** is built and released, together with its
drag-validity/altitude-guards and ECEF-nadir/direction-markers addenda.
**1.3 TLE propagator** is the next feature.

---

## 13. Open questions / decisions log

### Resolved

- **Numerical interpolation in `Trajectory.at()`** — delegated to Orekit's `Ephemeris` with Hermite interpolation. Cached on the `Trajectory` on first call. Raises `ValueError` on out-of-bounds queries (no extrapolation).
- **`Frame.EME2000` vs `Frame.J2000`** — `EME2000` is the canonical enum member (matching Orekit's preferred name); `J2000` is an alias of the same member. The two names refer to the same frame and coexist for readability. The ~tens-of-milliarcseconds bias commonly mentioned in this context is between EME2000 and GCRF, not between EME2000 and J2000.
- **Orekit-data resolution** — search path: env var → `~/.propygator/orekit-data/` → `./orekit-data/` → error.
- **Realtime cache TTL** — 6 hours (was 2). Better matches CelesTrak's update cadence.
- **Plot backend rule** — Plotly for interactive 3D, matplotlib for everything else (including sky charts and 2D timeseries). The split is along the interactivity axis, not strictly along dimensionality.
- **`TrajectoryMetadata` runtime guarantee** — TypedDict + runtime validator on required keys in `Trajectory.__post_init__`. Closes the gap between static and runtime guarantees while preserving user extensibility.
- **`State` runtime validation** — shape and dtype validation in `__post_init__`.
- **`Trajectory` backing arrays read-only** — `setflags(write=False)` in `__post_init__` so frozen-elsewhere semantics extend to array contents.
- **`Epoch.now()` default scale** — UTC, explicit in the signature.
- **`Trajectory` user-construction API** — `from_states` (ergonomic, small N) and `from_arrays` (vectorized, large N).
- **`fit_tle` contract** — accepts `State | Trajectory`; `force_models` used only in the State case; emits warning if supplied with a Trajectory.
- **`NullHandler` on the package logger** — yes, in `__init__.py`.
- **CI** — Tier 1 (Ubuntu, Python 3.11), cached conda env, no Windows.
- **NumPy 2.x + orekit_jpype compatibility** — verified May 2026 via the three-layer test in §11; environment snapshot in `docs/verified_environments/2026-05.txt`.
- **`core/catalogs.py`** — reference data lives in `core/`, not `io/`.
- **`Satellite` convenience class** — deliberately not provided in v1. Function-based API is the contract; if a `Satellite` class is added later, it will be sugar over the same functions and won't change the underlying contract.
- **Versioning policy** — semver, pre-1.0 may break in minor releases.
- **Package name** — renamed from `orbitkit` to `propygator` before build to avoid acoustic/visual collision with `orekit`. Documented import alias is `pgr` (`import propygator as pgr`); shown throughout the §9 examples.
- **Attitude family** — Native-provider-backed modes: `Inertial` (`FrameAlignedProvider`), `SunPointing` (`CelestialBodyPointed` or `AlignedAndConstrained`), `NadirPointing` and `InPlaneTracking` (`AlignedAndConstrained`), plus `LofAligned`/`LofOffset` (`LofOffset`). `CustomAttitude` (user law returning `propygator.Orientation`) is the only non-native escape hatch. `NadirPointing` is exact only for circular orbits (nadir primary, velocity secondary, for eccentric). `NadirPointing` **and `InPlaneTracking`** wire **both** `velocity_reference` options: `inertial` via Orekit's `PredefinedTarget.VELOCITY`, and `ecef` (Earth-relative velocity `v − ω⊕×r`) via one shared custom `@JImplements TargetProvider` — in the `AlignedAndConstrained` **secondary** slot for `NadirPointing` (ground-track velocity yaw; nadir stays the exact primary — ECEF-nadir & direction-markers addendum) and in the **primary** slot for `InPlaneTracking` (+Y exact on the wind, +Z best-effort on the orbit normal — feathers a flat body to the true flow; general-upgrades-1.md "ECEF InPlaneTracking"; see the §13 deferral note below).
- **Sky view relocated 1.3 → 1.4.** The geometry-only sky-track plot and the `look_angles(station, state) -> AzElRange` primitive (`core/observation.py`) it rides on were originally scheduled in Feature 1.3 to pull Feature 1.5's foundation forward. They moved to Feature 1.4: the live tracker needs a live sky-view panel, so the primitive is first built there — still before 1.5 in the build order, so the forward-pull is preserved. 1.3 reverts to pure SGP4 propagation reusing 1.1's outputs. (features §1.3 / §1.4.)
- **1.4 expanded to a live dashboard.** Beyond the `current_state` / `current_ground_position` primitives, 1.4 now ships a live, buffered matplotlib view (ground track, altitude, speed, sky view) driven by `FuncAnimation` over a rolling `Trajectory` buffer that re-propagates and **auto-refreshes a fetched TLE** (6-hour cache TTL). Backend-agnostic (desktop window or in-notebook `%matplotlib widget`), **live display only — not saved** (no animation-writer dependency; not snapshot-tested). The driver (`tracking/live.py`) lazily imports `plotting/` (the `export_all` precedent), keeping the static dependency graph clean. (features §1.4.)
- **1.5 pass table.** Alongside the polar sky charts, 1.5 offers a tabular view of `list[Pass]` (a `passes_to_dataframe` DataFrame and/or formatted text), plus the already-anticipated `io/exports` Pass-list → ICS/CSV export. Cheap formatting of an existing core type; no new dependency. (features §1.5.)
- **Force inventory: lumped planetary third body (v0.5.0); Earth radiation designed but blocked.** `ForceModelConfig.planets_third_body` wires third-body gravity from the pinned seven-planet set (Mercury–Neptune, heliocentric order; accessors in `core/bodies.py` off the DE ephemeris already bundled in orekit-data — no new data), one `third_body:planets` metadata token, off in every preset. Deliberately **one lumped toggle**, not per-planet booleans — at ~1e-10–1e-13 of central gravity, per-planet selection is false granularity. The companion `earth_radiation` (Knocke albedo + thermal IR through the SRP optics) is fully designed and was fully built, but **every installable Orekit (≤ 13.1.5) carries a horizon-angle defect in `KnockeRediffusedForceModel`** (visible-cap bound `asin(R/r)` instead of `acos(R/r)`; ~2.4–3× hot at LEO, ~10–20× cold at GEO — fixed upstream in Orekit 13.1.6, 2026-06-03), so the runtime was reverted and parked (`experiments/earth-radiation/`, patch + probe + resume recipe; general-upgrades-1.md "Planetary Third-Body & Earth Radiation Pressure" → Outcome).
- **`tracking/` is its own top-level package** (not folded into `tle/`) — the former §13 "Still open" question, resolved by the Feature 1.4 design now that the import shapes are on the page (as the deferral anticipated). `tracking/` holds `realtime.py` (`current_state` / `current_ground_position`), `live.py` (the live dashboard, which lazily imports `plotting/`), and — with 1.5 — `passes.py` (`find_passes`) and `visibility.py` (`compute_magnitude`). These are observer / real-time / visibility concerns that *consume* `tle/`'s `propagate_tle` + the `TLE` type but don't belong inside it: `tracking/` legitimately depends on `propagation/`, `tle/`, and `core/` (and, lazily, `plotting/`), so folding it into `tle/` would mix SGP4 propagation with observer geometry and drag a plotting edge into `tle/`. Kept separate. (features §1.4 / §1.5; §7 dependency rule.)

### Still open

- Whether `core/` should be split finer (e.g., separate `time/` and `frames/` packages) or kept compact. Same deferral logic — premature to decide.

### Deferred sub-designs (not blockers)

- **Per-feature plot specifications and CSV/JSON output shapes.** Backend decisions are locked (Plotly for interactive 3D, matplotlib for everything else) but the exact figures and tabular outputs each feature produces will be designed in a separate doc.
- **RTN/LVLH frames.** Dropped from v1's supported frame set because none of features 1.1–1.5 need satellite-local frames. Returns to the supported set when formation flying, rendezvous, or relative-motion features are added. Note: re-adding these is *not* a drop-in extension of the `Frame` enum — they are relative-motion frames parameterized by a reference state (and possibly a reference epoch), so they'll require a new type (e.g. `RelativeFrame(reference: State)`) rather than a new enum value. Plan for this when the feature lands; don't expect the deferral to be trivial to undo.
- **`FitResult` return type for `fit_tle`** — backward-compatible to add later (introduce `fit_tle_detailed()` or extend the return). v1 returns a bare `TLE`.
- **Coefficient of drag modeling.** The numerical integrator interpolates a variable Cd from a table keyed on geocentric radius and total density. v1 ships this for the sphere (VariableCd) and a box density-varying scalar Cd (Tier A): Orekit's box computes projected area from attitude, the table supplies the scalar Cd. A per-face incidence-resolved box table (Tier B, `BoxFaceCd`) is **shipped** for the convex box: one universal `(radius, density, face-flow angle θ ∈ [0, π])` table whose value is a single face's Cd (full-area reference, `cos θ` normal pressure **and** the tangential-shear floor), summed as `CdA = Σ_i Cd_i · A_i` over the six faces inside `propagate_numerical` — the exact convex free-molecular sum (no self-shadowing). It does **not** route through Orekit's box `dragAcceleration` (a single uniform Cd cannot consume a per-face table); the shipped `BoxFaceCd.default()` table is generated Orekit-free by `scripts/generate_box_face_cd_table.py` and cross-validated ≪ 1 % on `CdA` against the experiment kernel. Non-convex bodies (solar-array shadowing) stay out of scope. Binding design: `general-upgrades-1.md` "Tier B Drag". Full per-facet free-molecular Sentman (per-facet material/temperature, multiple reflection) remains deferred for plumbing reasons (Orekit's DragSensitive is passed only total density). The table is keyed on geocentric radius, not geodetic altitude, to avoid a per-substep frame transform; the geodetic reconciliation is done once during offline table generation. As built (Feature 1.1 + the Chunk-9 addendum), **every** drag path — sphere or box, fixed Cd or VariableCd — routes through a single custom `DragSensitive` proxy so the §6.2 free-molecular-floor warn-once hook is shared; consequently it exposes no drag `ParameterDriver`. That is invisible to forward/backward-in-time propagation and to TLE fitting (which reads only the propagated *states* and estimates the TLE's own elements + B*), and would matter only for numerical orbit determination — estimating the propagator's own Cd — which is out of scope for v1. The per-substep proxy cost for the fixed-Cd path (which Orekit could otherwise drive natively) is marginal next to the default NRLMSISE-00 density query; uniformity was judged worth it for v1 (features.md §1.1). **Validity domain (drag-validity & altitude-guards addendum).** The table is empirically valid only within an altitude band: a body-size-dependent free-molecular **Knudsen floor** (`Kn = λ/L = 10`; ~110 km for a CubeSat rising to ~220 km for a station) below which the Sentman/DRIA closed form over-predicts, up to a Cd-table ceiling (~1400 km, where drag is negligible so the high limit is non-binding). The runtime computes the floor once at setup from a conservative high-activity composition captured offline and embedded in `propagation/guards.py` (Orekit exposes only total density, and pymsis is not a runtime dependency). The shipped table is generated by a Cd model **proven equal** to the validity experiment's over the same axis/conditions/band — the §5 model-equivalence invariant (cross-validated to 0.0191 %) — so it claims only the band that was validated. See features.md §1.1 and the addendum §5/§6.
- **`NadirPointing` ECEF-relative velocity yaw (`velocity_reference="ecef"`) — RESOLVED (ECEF-nadir & direction-markers addendum).** Both `velocity_reference` options are now wired. `inertial` (ECI velocity) uses Orekit's `PredefinedTarget.VELOCITY`; `ecef` — yaw-steering to the Earth-relative (ground) velocity, which differs from inertial by the Earth-rotation term ω⊕×r (up to a few degrees of yaw in LEO) — is lowered via a custom `@JImplements TargetProvider` (`attitude._build_ecef_velocity_target_provider`) swapped into the same `AlignedAndConstrained` secondary slot (primary −Z→NADIR unchanged). The provider returns the normalized `v_rel = v_inertial − ω⊕×r` direction, derived from the inertial↔ITRF `Transform` at the sample date (exact, not a hardcoded ω). The former validated-skeleton `NotImplementedError` is removed; the config still constructs, validates, and serializes the unchanged `nadir_pointing:vel=ecef` token — no signature or metadata change. Full contract: the addendum §2. (The Tier-B per-face box drag path is now shipped as `BoxFaceCd` — see the drag note above.)
- **Escape / re-entry guards — RESOLVED (drag-validity & altitude-guards addendum).** `propagate_numerical` now carries a geocentric-radius guard family, closing the old "no purpose-built guard" gap. **Terminal backstops (always on):** impact at `r < R⊕` and **escape** at the lunar-gravity-parity radius (~327,000 km, perigee parity — a fixed hard-coded policy fence, replacing the previously-planned ~1,000,000 km SOI ceiling). A drag-driven decay is **caught and classified**: a genuine re-entry (drag on, descending, osculating perigee below the ~150 km drag-table floor) stops & reports (`termination_reason="reentry"`), while a non-re-entry min-step failure still raises `NumericalPropagationError` — a subclass of the base `PropagationError` (1.3's SGP4 failures raise the sibling `TLEPropagationError`; catch the base for any propagator) — replacing the previously-planned ~120 km hardcoded floor. Optional user `AltitudeLimits` (`limits=`) nest inside the backstops and may only tighten termination; an unreasonable limit raises `ValueError` at construction. Every runtime termination stops and reports a partial `Trajectory` with `terminated`/`termination_reason`/`termination_epoch` metadata (written only when terminated). The eccentricity gates are **retained** — a hyperbolic `State` already propagated; only the escape backstop is added. propygator *guards* these boundaries but does not *model* atmospheric entry or deep-space/cislunar regimes (the escape backstop is the clean boundary marker for the latter). Full contract: features.md §1.1 + the addendum §6.

None of these block starting the build.
