# propygator — Architecture & Design Reference

A Python library for orbital simulation and satellite tracking, built on Orekit.

**Status:** Phase 1 design, revised. Package name: `propygator` (renamed from `orbitkit` to avoid acoustic/visual collision with `orekit`). Documented import alias: `pgr`.

---

## 1. Scope

### Core features (v1)

| # | Feature | Description |
|---|---------|-------------|
| 1.1 | Numerical propagator | High-fidelity orbit propagation from an initial state vector, with configurable force models. Outputs trajectories and plots. |
| 1.2 | TLE fitter | Given an observed state (or trajectory), fit a TLE via least-squares against a reference trajectory produced by 1.1. |
| 1.3 | TLE propagator | SGP4 propagation of TLEs with plotting output. |
| 1.4 | Real-time tracker | Current ground position, altitude, etc. for a given TLE. |
| 1.5 | Ground passes + brightness | Find future visible passes from a ground station, including estimated visual magnitude. Combines tracking, lighting, and eclipse logic. |

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
| jupyterlab | 4.5.7 | for user interfaces

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

- **CelesTrak** — default, no auth required, covers popular satellites
- **Space-Track** — optional, requires account (env vars: `SPACETRACK_USERNAME`, `SPACETRACK_PASSWORD`), broader coverage
- **Direct user input** — always available, takes priority

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
│   └── propygator/                # importable package
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
├── data/                        # small reference data (NOT orekit-data)
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
        """Construct from raw arrays. Validates shapes, dtypes, and (for the
        list-of-Epoch form) that all epochs share a single TimeScale.

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
    propagator: Required[str]             # "numerical" | "sgp4"

    # Optional — populated when applicable.
    force_models: list[str]
    integrator: str
    integrator_tolerances: dict
    output_step_s: float
    created_at: str                        # ISO UTC
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

    @property
    def epoch(self) -> Epoch: ...
    @property
    def norad_id(self) -> int: ...

    if TYPE_CHECKING:
        def to_orekit(self) -> "org.orekit.propagation.analytical.tle.TLE": ...
    else:
        def to_orekit(self): ...
```

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
│       propagate_numerical, fetch_tle, propagate_tle, etc.
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
│   ├── bodies.py        Earth model (canonical instance), Sun, Moon
│   ├── observation.py   GroundStation, Pass, GeodeticPosition.
│   │                    In core/ so io/ can import them without violating
│   │                    the "io depends only on core" rule (§7 dep rule).
│   └── catalogs.py      Popular satellite registry (friendly name → NORAD ID)
│                        + standard-magnitude table for visibility calcs.
│                        Reference data, not I/O — lives in core/ so the
│                        dependency direction stays clean.
│
├── propagation/
│   ├── numerical.py     propagate_numerical(initial, duration,
│   │                                        force_models, output_step,
│   │                                        integrator=None)
│   │                    output_step is required (user-controlled).
│   │                    integrator is an optional IntegratorConfig;
│   │                    defaults to DOP853 with sensible tolerances.
│   ├── force_models.py  ForceModelConfig + presets (leo_default,
│   │                    geo_default, keplerian)
│   └── integrators.py   IntegratorConfig (tolerances, min/max step)
│
├── tle/
│   ├── propagator.py    propagate_tle(tle, start, duration, output_step)
│   │                    Default output frame: TEME.
│   ├── fitter.py        fit_tle(reference, fitting_span, ...)
│   │                    Accepts State (then propagates internally) or
│   │                    Trajectory (used directly). See §8.
│   ├── sources.py       fetch_tle, fetch_celestrak, fetch_spacetrack
│   │                    Caches to ~/.propygator/cache/
|   |                    fetch_tle(name_or_id, source='auto)
│   │                    Two TTLs: 6h (realtime workflows), 24h (general).
│   └── parsing.py       Validation, checksum, formatting
│
├── tracking/
│   ├── realtime.py      current_position(tle) -> State
│   │                    Returns the satellite state in TEME (the natural
│   │                    SGP4 output frame). Users wanting J2000 or ITRF
│   │                    call .to_frame(...) on the result.
│   │                    current_ground_position(tle) -> GeodeticPosition
│   │                    Internally TEME→ITRF→geodetic; the user receives
│   │                    lat/lon/alt directly, no frame to convert.
│   ├── passes.py        find_passes(tle, station, start, duration,
│   │                                min_elevation_deg)
│   └── visibility.py    Eclipse check, sun angle, phase angle
│                        compute_magnitude(state, sun, observer, std_mag)
│                        Pulls the standard-magnitude table from core/catalogs.py.
│
├── plotting/
│   ├── trajectories.py  plot_3d (Plotly), plot_ground_track (matplotlib)
│   ├── timeseries.py    plot_altitude, plot_elements, plot_velocity
│   │                    (matplotlib — 2D timeseries)
│   └── passes.py        plot_sky_chart (matplotlib polar),
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
User → TLE  (via fetch_celestrak / fetch_spacetrack / direct input)
     → tle.propagator.propagate_tle()
     → Trajectory  (TEME, optionally converted)
     → plotting.* / io.exports.*
```

### 1.4 Real-time tracking

```
User → TLE
     → tracking.realtime.current_position()
     → State  (+ derived lat/lon/alt)
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

- All `Epoch` constructors and methods *except* `to_orekit()` (see §6).
- All `Frame` enum access *except* `to_orekit()`.
- `State.__init__` and its validation (no Orekit calls in `__post_init__`).
- `Trajectory.from_states` / `from_arrays` shape and dtype validation.
- `TLE.from_strings` parsing and checksum validation.
- `GroundStation` and `Pass` construction.

JVM startup is reserved for: any `to_orekit()` call, `propagate_numerical`, `propagate_tle`, `fit_tle`, `current_position`, `current_ground_position`, `find_passes`, and `Trajectory.at()` (which builds the cached `Ephemeris`). Code review and CI tests guard against accidental Orekit imports leaking into the "safe before init" surface.

### Orekit types stay internal

Public APIs accept and return `propygator` types (`Epoch`, `Frame`, `State`, `Trajectory`, `TLE`). Orekit's Java-backed objects appear only inside module implementations. Where a public method exists to convert to an Orekit type (e.g. `State.to_orekit()`), the annotation uses `TYPE_CHECKING` so no runtime Orekit import is needed at the public type level. Benefits:

- Users don't need to know Orekit to use `propygator`
- Swapping backends affects only implementation
- IDE autocomplete works (real Python types, not JPype proxies)
- Pickling / serialization works (Orekit Java objects don't pickle)

Private cached references to Orekit objects (e.g. the `Ephemeris` cached on a `Trajectory` to back `at()`) are acceptable as implementation details — the rule is about public APIs, not internal caches.

### Frame conversions are explicit

No automatic conversions on `State`-returning paths. TLE propagation returns TEME; numerical propagation returns whatever frame the initial state was in (typically EME2000); `current_position(tle)` returns TEME. Users explicitly call `.to_frame(...)` to convert. Verbose, but it prevents silent frame-mismatch bugs.

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

- **Realtime workflows** (`current_position`, `current_ground_position`): **6-hour TTL**. CelesTrak typically refreshes popular satellites several times per day, so a 6-hour TTL catches updates within roughly half a refresh cycle while avoiding pointless refetches of identical TLEs.
- **General fetches** (`fetch_celestrak`, `fetch_spacetrack`): **24-hour TTL**. Notebook re-runs within a day hit the cache; daily re-issues are picked up automatically.

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

- **(a) Smoke import** — `import propygator`, fetch a known TLE, materialize a `State` from `current_position`. Catches "imports but the JPype/NumPy boundary is broken" failures.
- **(b) Numerical round-trip** — propagate a known Keplerian orbit forward, then backward; assert agreement with the initial state at machine-precision levels (10⁻⁸ relative or better). Catches "imports work but math is wrong" failures (e.g. silent dtype promotion changes in NumPy).
- **(c) Bulk-array round-trip** — construct a `Trajectory` with ~10⁵ samples, run `to_frame()`, run `to_dataframe()`, export to CSV, reload, compare. Catches dtype/promotion bugs in the vectorized paths. Explicitly assert `float64` for `positions`/`velocities` and `int64` for `_epochs_int` on the reloaded trajectory — NumPy 2.x changed some default-integer behaviour across point releases (e.g. earlier 2.x had platform-dependent int defaults on Windows; resolved by 2.1), and the test should be sensitive to dtype regressions even though Windows is not a supported platform.

These three tests are also the basis for the verified-environment snapshot in `docs/verified_environments/`.

---

## 12. Build order

Suggested implementation sequence:

1. **1.1 Numerical propagator** — core types, force model config, basic plotting
2. **1.3 TLE propagator** — shares plotting infrastructure with 1.1
3. **1.4 Real-time tracker** — cheap once 1.3 works
4. **1.5 Ground passes + brightness** — builds on 1.4 and visibility
5. **1.2 TLE fitter** — hardest; lean on Orekit's built-in fitting machinery. Treated as a plus rather than a blocker.

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

### Still open

- Whether `tracking/` should be a separate top-level package or fold into `tle/`. Defer until code is on the page; the right answer will be obvious from import shapes.
- Whether `core/` should be split finer (e.g., separate `time/` and `frames/` packages) or kept compact. Same deferral logic — premature to decide.

### Deferred sub-designs (not blockers)

- **Per-feature plot specifications and CSV/JSON output shapes.** Backend decisions are locked (Plotly for interactive 3D, matplotlib for everything else) but the exact figures and tabular outputs each feature produces will be designed in a separate doc.
- **RTN/LVLH frames.** Dropped from v1's supported frame set because none of features 1.1–1.5 need satellite-local frames. Returns to the supported set when formation flying, rendezvous, or relative-motion features are added. Note: re-adding these is *not* a drop-in extension of the `Frame` enum — they are relative-motion frames parameterized by a reference state (and possibly a reference epoch), so they'll require a new type (e.g. `RelativeFrame(reference: State)`) rather than a new enum value. Plan for this when the feature lands; don't expect the deferral to be trivial to undo.
- **`FitResult` return type for `fit_tle`** — backward-compatible to add later (introduce `fit_tle_detailed()` or extend the return). v1 returns a bare `TLE`.

None of these block starting the build.
