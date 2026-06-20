# propygator — Feature sub-designs

Companion document to `architecture.md`. Where `architecture.md` locks in the cross-cutting decisions (data model, module structure, conventions), this document fleshes out the per-feature design for the five v1 features.

---

## 1.1 Numerical propagator

> **Status: DRAFTED.** Force-model, spacecraft, attitude, integrator, output, and metadata sections are settled. `VariableCd` (a precomputed Cd table keyed on geocentric radius and live total density) is the v1 variable-drag path for **both** sphere and box geometry (a density-varying scalar Cd); a faithful incidence-keyed box table (`IncidenceVariableCd`) is designed as the documented extension. Full per-facet Sentman remains deferred (architecture §13). SRP uses a conical shadow. Attitude is a first-class input with seven modes, all but one backed by native Orekit providers. Remaining open items are cosmetic plot details. The **drag-validity & altitude-guards addendum** (drag-model validity domain + the altitude/regime guard system) has been built and folded into the subsections below — the signature (`limits=`), the metadata block (termination keys), "Escape and re-entry" (rewritten to the as-built guards), "Drag-coefficient modeling" (the §5 invariant, two-tier regime warnings, Knudsen floor), and the limitations note.

### Public signature

```python
def propagate_numerical(
    initial: State,
    duration: float,                          # seconds, positive
    *,
    output_step: float,                       # seconds; required, keyword-only
    force_models: ForceModelConfig | None = None,   # None -> leo_default()
    spacecraft: SpacecraftConfig | None = None,     # None -> SpacecraftConfig()
    attitude: AttitudeConfig | None = None,         # None -> LofAligned() (TNW)
    integrator: IntegratorConfig | None = None,     # None -> DOP853 default
    limits: AltitudeLimits | None = None,           # None -> system backstops only
    name: str | None = None,                  # optional, recorded in metadata
) -> Trajectory:
```

Inputs after `duration` are keyword-only so callers can't transpose `output_step` and `force_models`. Backward propagation is not supported in v1.

`limits` (an optional `AltitudeLimits`) adds user terminal altitude bounds that **nest inside** the always-on system backstops (impact at `R⊕`, lunar-parity escape); see "Escape and re-entry" and "Drag-coefficient modeling" below. `None` means the system backstops only. (Added by the drag-validity & altitude-guards addendum, which superseded/extended several subsections below — folded back in here.)

**Default-argument convention.** Configurable inputs use a `None` sentinel and are substituted with their default instances inside the body (consistent with `fit_tle`, architecture §8), so no config object is constructed in the signature.

`attitude` controls orientation over the propagation and is meaningful only for non-spherical geometry — a sphere is orientation-independent (see "Attitude configuration").

### `ForceModelConfig`

A frozen dataclass; each field is independently togglable, with presets as classmethods.

```python
@dataclass(frozen=True)
class ForceModelConfig:
    gravity_degree: int = 70
    gravity_order: int = 70
    gravity_field: str = "EIGEN-6S"
    sun_third_body: bool = True
    moon_third_body: bool = True
    drag: bool = True
    atmosphere_model: str = "NRLMSISE-00"   # "NRLMSISE-00" | "Harris-Priester" | "DTM-2000"
    srp: bool = True
    solid_tides: bool = False
    ocean_tides: bool = False
    relativity: bool = False

    @classmethod
    def leo_default(cls) -> "ForceModelConfig": ...
    @classmethod
    def geo_default(cls) -> "ForceModelConfig": ...
    @classmethod
    def keplerian(cls) -> "ForceModelConfig": ...
```

`ForceModelConfig` carries *which* perturbations act and *which model* each uses, but not the spacecraft's mass, area, or coefficients — those need a spacecraft description and live in `SpacecraftConfig`. The split keeps the two concerns orthogonal.

**Presets:**

| Setting | `leo_default` | `geo_default` | `keplerian` |
|---|---|---|---|
| `gravity_degree, gravity_order` | 70, 70 | 12, 12 | 0, 0 (point mass) |
| `sun_third_body` / `moon_third_body` | True / True | True / True | False / False |
| `drag` | True (`NRLMSISE-00`) | False | False |
| `srp` | True | True | False |
| `solid_tides` / `ocean_tides` / `relativity` | False | False | False |

LEO is gravity- and drag-dominated; GEO is gravity-degree-limited with negligible drag and SRP as a leading perturbation; Keplerian is the bit-exact analytical comparison case for tests (§11). Tides and relativity are off in all presets (rarely needed for v1 orbits, and they cost wall-clock time); users flip the boolean. Defaults are "good general-purpose starting points," not "best possible physics."

**Gravity field source.** `gravity_field` names a file Orekit loads via `GravityFieldFactory` (e.g. `EIGEN-6S`, `EGM2008`, `EGM96`), shipped in the orekit-data zip. Because config construction is on the safe-before-init surface (architecture §10), `gravity_field` and `atmosphere_model` are stored as plain strings and validated at the top of `propagate_numerical` (before integration), raising `ValueError` with a known-name list if a string doesn't resolve.

**SRP shadow.** When `srp` is enabled, SRP uses a **conical** Earth shadow — a continuous lighting ratio in [0, 1] across the penumbra from the apparent angular radii of Sun and occulting body, with Earth as the WGS84 ellipsoid. Matches Orekit's `SolarRadiationPressure` default; the right choice for LEO, where fast umbra/penumbra crossings make a hard cylindrical cutoff misrepresent eclipse transitions.

### `SpacecraftConfig`

A frozen dataclass for physical properties. Mass is the only shape-independent property and stays here; the surface-interaction coefficients live **on the geometry**, because the geometry fixes which Orekit surface model is used and how its coefficients are parameterized.

```python
@dataclass(frozen=True)
class SpacecraftConfig:
    mass_kg: float = 1000.0
    geometry: SpacecraftGeometry = SpacecraftGeometry.sphere(area_m2=1.0)
```

The default is a generic 1000 kg, 1 m² sphere with conventional coefficients. The docstring is explicit these are placeholders: *"For accurate drag and SRP modeling, override the mass, geometry, and coefficients to match your spacecraft."* (The factory default is a frozen, Orekit-free constant, so the import-time construction is safe.)

**Why coefficients moved onto the geometry.** Orekit parameterizes *drag* with a single Cd for both supported geometries, but parameterizes *radiation* differently per surface model: the sphere model takes one reflectivity coefficient Cr; the box model (`BoxAndSolarArraySpacecraft`) takes an **absorption** and a **specular-reflection** coefficient, each in [0, 1] (the remainder, `1 − absorption − specular`, is diffuse). A single `Cr` field could not faithfully drive the box model, so each geometry's coefficients live on its own factory.

### `SpacecraftGeometry`

The external shape plus its surface-interaction coefficients. v1 supports two idioms.

**`sphere` — simplest case.**

```python
SpacecraftGeometry.sphere(
    area_m2: float,
    *,
    drag_coefficient: float | VariableCd = 2.2,       # Cd, unitless
    reflectivity_coefficient: float = 1.5,            # Cr, unitless
) -> SpacecraftGeometry
```

One shape number: cross-sectional area (π·r²). Same area faces velocity and Sun regardless of orientation, so attitude is irrelevant. Maps to Orekit's `IsotropicDrag` / `IsotropicRadiationSingleCoefficient`. Cd = 2.2 is the free-molecular convention (above ~200 km). Cr uses Orekit's single-coefficient convention — **1.0 = fully absorbing, 2.0 = perfectly specular** — pinned in the docstring so users coming from tools where Cr ∈ [0, 1] is a reflectivity *fraction* don't mistranslate.

> **Implementation note (Orekit 13.1.x, verified at build).** Earlier drafts named the sphere's SRP model `IsotropicRadiationClassicalConvention`; that wording is misleading. `IsotropicRadiationClassicalConvention` takes **two** coefficients `(area, ca, cs)` (absorption + specular) and cannot represent a single `Cr`. The single-`Cr` sphere is `IsotropicRadiationSingleCoefficient(area, cr)` (its parameter driver is literally "reflection coefficient", default 1.5), which is the model that realizes the 1.0-absorbing / 2.0-specular convention above.

**`box_and_panels` — a sketched satellite.**

```python
SpacecraftGeometry.box_and_panels(
    *,
    x_length_m: float,
    y_length_m: float,
    z_length_m: float,
    solar_array_area_m2: float = 0.0,
    solar_array_axis: tuple[float, float, float] = (0.0, 1.0, 0.0),
    drag_coefficient: float | VariableCd | IncidenceVariableCd = 2.2,
    absorption_coefficient: float = 0.3,            # in [0, 1]
    specular_reflection_coefficient: float = 0.6,   # in [0, 1]
) -> SpacecraftGeometry
```

A rectangular bus with optional solar arrays — the standard "sketch a satellite without a CAD model" abstraction. Matches Orekit's `BoxAndSolarArraySpacecraft`.

- **`x/y/z_length_m`** — box centered on the body origin, faces normal to body X/Y/Z. Orekit sums visible-face contributions to project cross-section toward any direction (velocity for drag, Sun for SRP).
- **`solar_array_area_m2`** — *total* panel area, treated as one equivalent panel that **auto-rotates to track the Sun** independent of bus attitude. `0.0` (default) models a body-only spacecraft. **Note:** because the array always Sun-tracks, do *not* use it to model a surface whose orientation you want to control (e.g. a solar sail) — model that as the box and steer it with the attitude config.
- **`solar_array_axis`** — body-frame unit vector the arrays rotate about. Default `(0, 1, 0)` is the common single-axis, body-Y convention. Non-unit vectors normalized silently; zero/non-finite raise `ValueError`. Unused when array area is 0.
- **`drag_coefficient`** — Cd along the atmosphere-relative velocity (fixed, or a table; see "Drag-coefficient modeling").
- **`absorption_coefficient`, `specular_reflection_coefficient`** — box SRP optics, each in [0, 1], diffuse making up the remainder, applied uniformly across all faces (per-face optics out of scope for v1).

Drag uses projected area along velocity-relative-to-atmosphere × `drag_coefficient` (no aerodynamic torque or lift in v1). SRP uses projected area along the Sun direction with the absorption/specular coefficients. A non-trivial geometry changes drag/SRP only as attitude varies the cross-section relative to velocity and Sun; with `LofAligned` (TNW), the cross-section varies naturally over the orbit.

**Modeling a solar sail.** Represent it generically as a thin, highly specular box — no sail-specific type in v1: use `box_and_panels` with `solar_array_area_m2=0.0`, a small nonzero thin dimension (a millimeter; the validator requires every dimension `> 0`), `specular_reflection_coefficient` high and `absorption_coefficient` low (a real aluminized membrane is ≈ `specular 0.85`, `absorption 0.10`), and steer it with the attitude config. This captures the cosine-law area change and the dominant normal-directed SRP force; it does not model billowing, wrinkles, or optics beyond a single specular/absorbing split.

**Validation** (at construction — safe-before-init, no Orekit calls):

| Condition | Result |
|---|---|
| `mass_kg <= 0` | `ValueError` |
| `sphere(area_m2 <= 0)` | `ValueError` |
| `sphere` / `box_and_panels` with `drag_coefficient < 0` (fixed value) | `ValueError` |
| `sphere` with `reflectivity_coefficient < 0` | `ValueError` |
| `box_and_panels` with any dimension `<= 0` | `ValueError` |
| `box_and_panels(solar_array_area_m2 < 0)` | `ValueError` |
| `box_and_panels` with non-finite or zero `solar_array_axis` | `ValueError` |
| `box_and_panels` with non-unit `solar_array_axis` | normalized silently |
| `box_and_panels` `absorption`/`specular` outside `[0, 1]` | `ValueError` |
| `box_and_panels` `absorption + specular > 1` | `ValueError` (negative diffuse) |
| `sphere` given an `IncidenceVariableCd` | `ValueError` (no incidence dependence) |

A fixed Cd > 5 or sphere Cr > 3 emits a warning but doesn't raise — improbable, but used for sensitivity studies.

### Attitude configuration

`AttitudeConfig` lives in `propagation/attitude.py`. v1 provides seven modes; all but `CustomAttitude` lower to **native Orekit attitude providers**, so they add no per-substep Python and require no user-constructed rotation.

```python
AttitudeConfig = (
    LofAligned | LofOffset | Inertial | SunPointing
    | NadirPointing | InPlaneTracking | CustomAttitude
)

@dataclass(frozen=True)
class LofAligned:
    """Body axes follow the TNW local orbital frame: body-X along velocity,
    body-Z along orbital momentum, body-Y completing the right-handed set.
    The v1 default. TNW is fixed in v1; no parameters."""

@dataclass(frozen=True)
class LofOffset:
    """LofAligned (TNW) rotated by fixed body-frame angles. Use for an
    arbitrary fixed offset from the velocity-aligned frame — e.g. a flat plate
    rolled about the velocity axis (roll_deg). Non-finite angles raise ValueError."""
    roll_deg: float = 0.0     # about body-X (the velocity axis in TNW)
    pitch_deg: float = 0.0
    yaw_deg: float = 0.0

@dataclass(frozen=True)
class Inertial:
    """Fixed orientation in inertial space — the spacecraft does not rotate
    relative to `reference_frame`. Optional fixed offset via the angles.
    `reference_frame` must be inertial (EME2000 / J2000); else ValueError."""
    reference_frame: Frame = Frame.EME2000
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    yaw_deg: float = 0.0

@dataclass(frozen=True)
class SunPointing:
    """`pointing_axis` (body) is held exactly on the Sun; `phasing_axis` (body)
    fixes the remaining roll about the Sun line by tracking `phasing_reference`.
    Axes normalized silently; pointing_axis parallel to phasing_axis -> ValueError."""
    pointing_axis: tuple[float, float, float] = (0.0, 0.0, 1.0)   # body axis aimed at Sun
    phasing_axis:  tuple[float, float, float] = (1.0, 0.0, 0.0)   # body axis for the 2nd DOF
    phasing_reference: str = "orbit_normal"   # "orbit_normal" | "velocity" | "inertial_z"

@dataclass(frozen=True)
class NadirPointing:
    """Body -Z held on (geodetic) nadir; body +Y steered toward the velocity
    vector. Earth-pointing with velocity yaw. Exact when the flight-path angle
    is zero (circular orbits, apsides); off-apsis on eccentric orbits, nadir is
    held exactly and velocity is best-effort."""
    velocity_reference: str = "inertial"      # "inertial" (ECI velocity);
    # "ecef" = Earth-relative (ground-track) velocity yaw, v_rel = v - ω⊕×r,
    # implemented via a custom TargetProvider (architecture §13)

@dataclass(frozen=True)
class InPlaneTracking:
    """Body +Z on the orbit normal; body +Y on the velocity vector. Exact for
    all orbits, since the orbit normal is always perpendicular to velocity.
    No parameters."""

@dataclass(frozen=True)
class CustomAttitude:
    """Fully user-defined law mapping a State to a body orientation. `law`
    returns a propygator Orientation (a boundary value type — NOT an Orekit /
    Hipparchus Rotation), converted internally. Escape hatch for laws not
    expressible above. `law` must be callable, else ValueError."""
    law: Callable[[State], "Orientation"]
```

**Native-provider mapping:**

| Config | Orekit provider |
|---|---|
| `LofAligned` / `LofOffset` | `LofOffset` with `LOFType.TNW` |
| `Inertial` | `FrameAlignedProvider` (aligned to EME2000, optional fixed offset) |
| `SunPointing` | `CelestialBodyPointed` (fixed inertial phasing) or `AlignedAndConstrained` (orbit-relative phasing: primary `PredefinedTarget.SUN`, secondary `PredefinedTarget.VELOCITY` / `.MOMENTUM`) |
| `NadirPointing` | `AlignedAndConstrained` (primary −Z → nadir, secondary +Y → `PredefinedTarget.VELOCITY`) |
| `InPlaneTracking` | `LofOffset(TNW, fixed axis permutation)` or `AlignedAndConstrained` (+Y → `VELOCITY`, +Z → `MOMENTUM`) |
| `CustomAttitude` | user-backed attitude provider |

`SunPointing` uses `CelestialBodyPointed` only when `phasing_reference` is a fixed inertial direction (its phasing vector is constant in inertial space); orbit-relative references (`orbit_normal`, `velocity`) lower to `AlignedAndConstrained`, whose targets vary with the state. (`PredefinedTarget.EARTH` is confirmed against the 13.1.x API; verify the `SUN` / `VELOCITY` / `MOMENTUM` literal spellings against the same javadoc at implementation — a wrong constant is a compile-time error.)

**Why TNW.** TNW is the exactly-defined velocity-aligned local orbital frame (body-X along velocity, body-Z along orbital momentum). The informal "body-X along velocity, body-Z toward nadir" does not map to any single Orekit `LOFType` and isn't even orthogonal for eccentric orbits, so v1 standardizes on TNW.

**Geometry interaction.** `InPlaneTracking`, `NadirPointing`, and `SunPointing` specify body axes directly, so they need no geometry inspection — the box dimensions affect the drag/SRP cross-sections (handled by Orekit) but not the attitude definition. With a velocity-tracking mode, the +Y face is the ram face, so the drag cross-section (x × z face) stays roughly constant over the orbit. For a symmetric box with uniform optical coefficients, which of two opposite faces is sunlit is immaterial (mirror-symmetric), but which *pair* (x vs y vs z) the Sun and flow see is not — it sets the projected area and reflection direction — and is determined automatically by the attitude plus Sun geometry.

**Performance caveat.** A `CustomAttitude` `law` is invoked from inside Orekit's integration loop via JPype on every substep and now also constructs/converts a propygator `Orientation` each call. Prefer the declarative modes; reserve `CustomAttitude` for laws that genuinely cannot be expressed as one of them.

**Deferred (post-v1).** Time-varying / programmed attitude (mid-propagation maneuvers) and additional local-orbital-frame choices beyond TNW. Adding them later is backward-compatible (new attitude types, or a `lof` parameter defaulting to TNW). See architecture §13.

### `IntegratorConfig`

```python
@dataclass(frozen=True)
class IntegratorConfig:
    type: str = "DOP853"             # "DOP853" | "DormandPrince54" | "ClassicalRK4"
    min_step_s: float = 1e-3
    max_step_s: float = 1000.0
    abs_tolerance_m: float = 1e-3
    rel_tolerance: float = 1e-10
    fixed_step_s: float | None = None  # required for ClassicalRK4

    @classmethod
    def default(cls) -> "IntegratorConfig": ...
    @classmethod
    def fast(cls) -> "IntegratorConfig": ...
    @classmethod
    def high_precision(cls) -> "IntegratorConfig": ...
```

| Preset | `type` | `abs_tolerance_m` | `rel_tolerance` | Use |
|---|---|---|---|---|
| `default` | DOP853 | 1e-3 | 1e-10 | high-fidelity general-purpose |
| `fast` | DormandPrince54 | 10.0 | 1e-7 | quick-look, interactive iteration |
| `high_precision` | DOP853 | 1e-5 | 1e-12 | `fit_tle` reference trajectories, precision work |

- **DOP853** (eighth-order adaptive) is the default, matching Orekit's reference examples. **DormandPrince54** is the lower-order adaptive alternative for short propagations. **ClassicalRK4** is fixed-step (requires `fixed_step_s`), mainly for exercising `keplerian` at a known step in tests.
- Tolerances are interpreted as meters of position via Orekit's `OrbitType.CARTESIAN` tolerance computation; the propagator builds the `[abs[7], rel[7]]` array from these two scalars.
- `min_step_s` / `max_step_s` bound the adaptive controller; the wide defaults (1 ms–1000 s) mean a healthy propagation never bumps either bound. If the adaptive step is driven below `min_step_s` (usually an ill-posed problem), Hipparchus cannot meet tolerance and **stops** rather than silently continuing at an oversized step — the propagation raises `PropagationError` (see the failure table below). (Earlier drafts described this as an end-of-run *warning*; that assumed the integrator clamps at `min_step_s` and continues, which it does not — it raises.)
- **`high_precision` caveat:** `rel_tolerance = 1e-12` is demanding; on a stiff or ill-posed case it can drive the step below `min_step_s` and raise `PropagationError`. Verify against the §11 round-trip tests at implementation; if it raises on representative LEO/GEO cases, loosen to `1e-11` rather than shipping a preset that fails.

### `propagate_numerical` behavior

**Output step.** `output_step` controls the sampling rate of the returned `Trajectory`, not the integrator step. The integrator runs adaptively; Orekit's generated ephemeris (or a step handler) produces samples at exactly `output_step` intervals, decoupling integration accuracy from trajectory density.

**Sample count.** `floor(duration / output_step + tol) + 1` samples (with a small relative `tol ≈ 1e-9` to absorb float round-off so divisible cases are deterministic), first sample at `initial.epoch`, last at `initial.epoch + floor(...) * output_step`. If `duration` isn't an integer multiple of `output_step`, the trajectory ends just shy of `initial.epoch + duration`; no synthesized final partial-step sample.

**Input frame.** `initial.frame` must be inertial — `Frame.EME2000` (alias `J2000`) for v1. Newtonian integration is only well-posed in an inertial frame, so `Frame.ITRF` / `Frame.TEME` raise `ValueError` at the top of the function, pointing to `state.to_frame(Frame.EME2000)`. Because input is inertial-only, the output `Trajectory` is always EME2000 (no automatic conversion; architecture §10).

**Attitude/geometry consistency.** If a non-default attitude is supplied with sphere geometry, the propagator emits a one-time warning ("attitude has no effect on orientation-independent geometry; ignoring") and proceeds — a sphere's cross-section is attitude-invariant.

**Metadata populated** on success:

```python
{
    "propygator_version": <str>,        # required, auto
    "orekit_version": <str>,            # required, auto
    "propagator": "numerical",          # required, auto
    "force_models": [<str>, ...],       # optional
    "spacecraft": <str>,                # optional
    "attitude": <str>,                  # optional
    "integrator": <str>,                # optional; e.g. "DOP853"
    "integrator_tolerances": {"abs_m": <float>, "rel": <float>,
                              "min_step_s": <float>, "max_step_s": <float>},
    # ClassicalRK4 is fixed-step: integrator_tolerances is {"fixed_step_s": <float>}
    # instead (the adaptive tolerances above never act on a fixed-step integrator).
    "output_step_s": <float>,
    "created_at": <iso utc str>,
    "name": <str>,                      # only if supplied
    "terminated": True,                 # only if a guard stopped the run early
    "termination_reason": <str>,        # only if terminated; see below
    "termination_epoch": <iso utc str>, # only if terminated; crossing instant
}
```

(The `spacecraft`, `attitude`, and `name` keys are optional fields on the `TrajectoryMetadata` TypedDict, architecture §6.)

**Termination keys (drag-validity & altitude-guards addendum).** When a guard stops the run early (see "Escape and re-entry"), three additive optional keys are written: `terminated: True`, `termination_reason` (one of `"reentry" | "impact" | "escape" | "user_min" | "user_max"`), and `termination_epoch` (ISO-8601 UTC of the crossing). They are written **only when terminated**, so a normal completed run's metadata — and its `export_csv` header — is byte-identical to a pre-guard run (no churn on the common path). These are optional `TrajectoryMetadata` fields (architecture §6), not in the required set.

The optional physics keys are emitted only when they actually shaped the trajectory ("reflect what's acting", not the config booleans): `spacecraft` appears when **drag or SRP** was wired (the only forces that consume mass/geometry/coefficients), so a `keplerian` run omits it; `attitude` appears only when geometry is a **box and** drag or SRP was wired (orientation affects the result solely through a non-spherical cross-section under a surface force) — a sphere, or a force-free box, omits it. `name` appears only when supplied.

**`force_models` grammar.** Deterministic, greppable strings in fixed token order — gravity, `third_body:sun`, `third_body:moon`, drag, srp, tides (`tides:solid` / `tides:ocean` emitted independently), relativity — so the same config yields byte-identical metadata. Example (LEO + solid tides):

```python
["gravity:EIGEN-6S:70x70", "third_body:sun", "third_body:moon",
 "drag:NRLMSISE-00", "srp", "tides:solid"]
```

**`spacecraft` string.** Deterministic; numbers are coerced to `float` and rendered with `repr()` (so an int- and a float-valued coefficient serialize identically — `Cd=2` and `Cd=2.0` both yield `2.0`); semicolon separates geometry from mass/coefficients. A `VariableCd` / `IncidenceVariableCd` records `Cd=table:<name-or-hash>` (the hash includes the table's axis set, so a 2-D and an incidence table for the same geometry don't collide).

```
"sphere:A=1.0;m=1000.0,Cd=2.2,Cr=1.5"
"sphere:A=1.0;m=1000.0,Cd=table:sphere_default,Cr=1.5"
"box:x=2.0,y=1.5,z=1.0,arrays=10.0,axis=(0,1,0);m=420.0,Cd=2.2,abs=0.3,spec=0.6"
```

**`attitude` string.**

```
"lof_aligned:TNW"
"lof_offset:TNW;roll=90.0,pitch=0.0,yaw=0.0"
"inertial:EME2000;roll=0.0,pitch=0.0,yaw=0.0"
"sun_pointing:point=(0,0,1),phase=(1,0,0):orbit_normal"
"nadir_pointing:vel=inertial"
"in_plane_tracking"
"custom:<law name or repr>"
```

`CustomAttitude` cannot be fully serialized (the law is arbitrary Python), so its metadata records the callable's name where available and is a documented reproducibility gap.

**Failure modes.**

| Condition | Exception |
|---|---|
| `initial.frame` non-inertial | `ValueError` |
| `initial` position/velocity non-finite | `ValueError` (at `State` construction, architecture §6) |
| `duration <= 0` / `output_step <= 0` / `output_step > duration` | `ValueError` |
| `gravity_field` / `atmosphere_model` / `integrator.type` doesn't resolve | `ValueError` (with known-name list) |
| `Inertial.reference_frame` non-inertial | `ValueError` |
| `SunPointing.pointing_axis` parallel to `phasing_axis` | `ValueError` |
| `attitude.law` not callable (`CustomAttitude`) | `ValueError` |
| `AltitudeLimits(...)` unreasonable — `min_altitude_km < 0`, `max_altitude_km` above the escape-parity altitude (≈ 320,621 km), or `min >= max` — raised at **construction**, not at a crossing | `ValueError` |
| `box_and_panels` `IncidenceVariableCd` under drag — Tier B deferred (architecture §13) | `NotImplementedError` |
| `NadirPointing(velocity_reference='ecef')` on an orbit whose ground-relative velocity is ~0 (e.g. geostationary / instantaneously ground-stationary) — the yaw target `v_rel = v − ω⊕×r` is undefined, so its direction can't be formed | `PropagationError` (carrying the underlying message; LEO yaw-steering is the validated domain — ECEF-nadir addendum §2) |
| Integrator fails (usually `min_step_s` saturation) **and** the failure is a drag-driven re-entry (drag on, descending, osculating perigee already below the ~150 km drag-table floor) | *stop & report* — partial `Trajectory`, `termination_reason="reentry"` (**not** an error; addendum §6.6) |
| Integrator fails for any **other** reason (over-tight tolerance, bad setup, non-low-altitude stiffness) | `PropagationError` (may carry a recovered `err.partial_trajectory`, or `None`) |
| Unrecognized underlying Orekit failure | `PropagationError` wrapping the original |

`PropagationError` lives in `propygator.exceptions` and carries the Java exception's message as a string — no raw Java stack trace surfaces (same principle as `OrekitDataMissingError`, architecture §3). String-valued config fields are validated at the top of `propagate_numerical`, before integration. A drag-driven decay is **caught and classified** rather than always re-raised (addendum §6.6): a genuine re-entry stops and reports a partial `Trajectory` (`termination_reason="reentry"`), while any non-re-entry failure re-raises `PropagationError` — carrying a recoverable partial trajectory as `err.partial_trajectory` when usable steps were generated, else `None`. The invariant is **prefer a false re-raise over a false `reentry`**: when in doubt, raise.

**Escape and re-entry (drag-validity & altitude-guards addendum).** The propagator carries a geocentric-radius guard family that bounds both ends of the validity domain. All guards operate on `r = |position|` in the EME2000 propagation frame (one `sqrt`, no per-substep geodetic conversion).

- **Terminal backstops (always on).** Two custom radius event detectors stop the run cleanly and **report**: **impact** at `r < R⊕` (WGS84 equatorial, 6,378,137 m) and **escape** at `r > r_lunar_parity` (≈ 327,000 km — the Earth-Moon gravity-parity radius at lunar perigee; a fixed hard-coded policy fence, not Orekit-derived). The escape backstop makes an already-supported unbound (hyperbolic) `State` *safe*: runaway integration terminates instead of running to absurd distances. The parabolic `e == 1` rejection in `KeplerianElements` stays (a representability limit, orthogonal to these guards).
- **Re-entry (reactive).** A decaying orbit with drag on stiffens until the integrator saturates `min_step_s` (or the atmosphere model rejects the sub-surface query) and fails. That failure is **caught and classified**: drag on + descending + osculating perigee already below the ~150 km drag-table floor → a physical re-entry that **stops & reports** (`termination_reason="reentry"`, partial `Trajectory`); anything else re-raises `PropagationError` (invariant: prefer a false re-raise over a false `reentry`). See the Failure modes table.
- **Drag-regime warnings (run continues).** Two-tier, edge-aware, warn-once — the free-molecular Knudsen floor and the table edges; see "Drag-coefficient modeling".
- **User limits (optional).** An `AltitudeLimits` passed as `limits=` adds terminal altitude bounds that **nest inside** the system backstops (they can only *tighten* termination). A reasonable crossing stops & reports (`termination_reason="user_min"`/`"user_max"`); an unreasonable limit (outside the backstops) is rejected at `AltitudeLimits` construction with `ValueError` (it could never bind — the system backstop fires first).
- **Reporting contract.** Every runtime termination — impact, escape, re-entry, reasonable user-limit — *stops and reports*: it returns the partial `Trajectory` (samples up to the crossing) with `terminated` / `termination_reason` / `termination_epoch` metadata, written only when terminated. The sole `raise` on the guard path is the construction-time `ValueError` for an unreasonable `AltitudeLimits`.
- **Non-goal (unchanged).** propygator *guards* these boundaries; it does not *model* atmospheric entry (aerothermodynamics, breakup, footprint) or deep-space / cislunar dynamics. The escape backstop intentionally terminates Earth-bound trajectories whose apogee exceeds lunar-perigee parity (e.g. cislunar transfers, weak-stability-boundary orbits) — both out of the modeled regime (Moon-as-perturbation fails there) and out of scope.

*(This subsection was **superseded** by the addendum: the old ~120 km hardcoded re-entry floor and ~1,000,000 km SOI ceiling are replaced by the guard family above, reconciled here. Full contract: `docs/history/feature-1.1-addendum-drag-validity-and-altitude-guards.md` §6; architecture §13.)*

**Logging.** INFO: once at start (config summary), once at end (sample count, wall time). DEBUG: integrator step statistics if Orekit exposes them. No printing (architecture §10).

### Drag-coefficient modeling

v1 supports a fixed user Cd (default) and an optional variable Cd that captures the dominant solar-cycle and diurnal variation without the plumbing cost of a physical free-molecular model.

**Fixed Cd (default).** A scalar `drag_coefficient` (default 2.2) mapping onto Orekit's `IsotropicDrag` (sphere) or the box drag model. Right for most v1 use.

**Variable Cd — the plumbing constraint.** Orekit's `DragSensitive.dragAcceleration` is handed only *total density* and the relative velocity — no composition or temperature. So any model needing those at runtime must re-query the atmosphere per substep. Keying instead on quantities already in hand sidesteps this: **geocentric radius** (`|position|` in the propagation frame — no frame transform, no EOP) and the passed-in total density. Total density is a tight proxy for thermospheric state at a given radius — at fixed altitude it swings 5–10× over the solar cycle, driven by the same temperature/composition changes that move Cd — so a `(radius, density)` table collapses the higher-dimensional input space while retaining the dominant variation a fixed 2.2 ignores. Radius alone would miss the solar-cycle effect; density carries it. (Geocentric radius rather than geodetic altitude: the altitude axis is the weak secondary index, the up-to-~21 km geodetic/geocentric spread lands within a bin or two where Cd varies slowly at fixed density, and it avoids a per-substep frame transform. The shipped table must be *generated by a Cd model proven equal to the validity experiment's, over the same axis, conditions, and altitude band* — the §5 model-equivalence invariant of the drag-validity addendum, which strengthens the bare same-convention requirement: a validity limit derived from the experiment transfers to the shipped table only if the two independent Sentman/DRIA reconstructions agree at the boundary (cross-validated to 0.0191 % across 130–1450 km before the table was regenerated).)

```python
# Sphere or box (Tier A): a 2-D (geocentric radius, total density) table.
VariableCd.from_table(grid, *, radius_axis, density_axis)
VariableCd.sphere_default()                 # shipped sphere table
VariableCd.from_callable(fn)                # fn(radius_m, density_kgm3) -> Cd

# Faithful box (Tier B): adds body-frame flow-incidence axes.
IncidenceVariableCd.from_table(
    grid, *, radius_axis, density_axis,
    azimuth_axis, elevation_axis, array_axis=None,
)
```

`drag_coefficient` widens to `float | VariableCd | IncidenceVariableCd` (`sphere` accepts `float | VariableCd`; `box_and_panels` accepts all three). The `VariableCd` / `IncidenceVariableCd` objects are pure-Python tables, safe to construct before init.

**Tier A — density-varying scalar Cd (sphere and box).** A sphere has no incidence dependence, so `(radius, density)` fully determines its Cd. The box keeps Orekit's attitude-driven projected-area bookkeeping; only the scalar Cd it would apply is replaced by the table value. This captures the solar-cycle / diurnal / altitude trend that a flat 2.2 misses, but applies one scalar uniformly across faces — it does **not** capture per-face incidence (that is Tier B).

**Tier B — incidence-keyed box table.** A box's true Cd also depends on how each face meets the flow, so a faithful table adds body-frame incidence axes (azimuth, elevation; optional array-articulation axis), generated offline by a panel method (ADBSat) or DSMC. No shipped default — a box table is geometry/material-specific. At runtime the model computes the relative-velocity direction in the body frame from the attitude and looks up Cd on the multi-D grid.

**Runtime.** Each variable Cd maps to a thin custom `DragSensitive` whose `dragAcceleration` reads geocentric radius from the state, takes the passed-in total density (plus body-frame incidence for Tier B), interpolates Cd, and assembles `a = −½ (Cd·A/m) ρ |v_rel| v_rel` exactly as `IsotropicDrag` / the box model would. **The custom `DragSensitive` is instantiated inside `propagate_numerical`, never at geometry construction** — that keeps the geometry factory on the safe-before-init surface (architecture §10).

As built (addendum Chunk 9), **every** drag path — sphere or box, *fixed Cd or a table* — routes through this one custom `DragSensitive`, so the free-molecular-floor warn-once hook (below) and the table-edge warnings share a single code path. The trade: a fixed-Cd sphere, which Orekit could otherwise drive natively via `IsotropicDrag`, now crosses the Java↔Python boundary for the drag formula on every substep — marginal next to the default `NRLMSISE-00` density query, a larger share under a cheaper atmosphere (`Harris-Priester`); the uniformity was judged worth it for v1. The shared proxy also exposes no drag `ParameterDriver`, which is invisible to forward/backward propagation and TLE fitting and matters only for numerical OD (out of scope for v1). See architecture §13.

> **Implementation note (Orekit sign convention, verified at build).** The textbook `a = −½ … |v_rel| v_rel` above assumes `v_rel = v_spacecraft − v_atmosphere`. Orekit hands `DragSensitive.dragAcceleration` the **opposite-signed** relative velocity, `relativeVelocity = v_atmosphere − v_spacecraft`, and `IsotropicDrag` therefore applies a **positive** scalar: `a = +½ (Cd·A/m) ρ |relativeVelocity| relativeVelocity`. The custom `DragSensitive` must use the `+½` form with Orekit's argument to match `IsotropicDrag` (verified to ~1e-21 m/s²); the two expressions denote the same physical deceleration. A faithfulness test pins this against `IsotropicDrag` at constant Cd. The per-substep work is a low-dimensional interpolation plus a `|position|`; far cheaper than per-facet Sentman, but measurably slower than stock fixed-Cd drag — benchmark at implementation.

**Where the table comes from.** `sphere_default()` is generated once by maintainers and committed to `data/`; end users load a small array and compute nothing. Generation sweeps a high-fidelity Cd model (closed-form Sentman for the sphere) over a grid of thermospheric conditions and regrids onto the `(radius, density)` mesh — order 10⁴–10⁵ vectorized evaluations, sub-minute. A box (Tier B) table is a deliberate user setup step (a generation script or an external tool such as ADBSat / DSMC); the output is the same kind of array.

**Freshness.** The table encodes a *physics relationship* (given this density at this radius, what is Cd?), not the atmospheric *state*; the time-varying density is supplied live by the atmosphere model from orekit-data space-weather files. So the table tracks current conditions and never goes stale with time — it needs regenerating only when the geometry/material changes or a revised physics model ships. (Keying on a solar index instead of density would bake space-weather assumptions into the table and make it drift; this is why density is the key.)

**Out-of-grid & drag-regime warnings (drag-validity addendum).** Out-of-grid inputs still clamp to the nearest edge per-axis (raising mid-run would crash a long propagation; extrapolating would fabricate Cd) — but the one-time warning is now **edge-aware and two-tier**, because the two altitude edges are physically asymmetric:

- **Low edge** — below the table's lower altitude edge, or below the body-size-dependent free-molecular **Knudsen floor**: drag is large and the model is invalid → a **loud** warning.
- **High edge** — above the table's upper altitude edge: Cd is uncertain but multiplies a near-zero force → a **soft** note.

A density-axis clamp is a neutral data-range edge. Each boundary warns once per propagation; with drag **off**, no drag-regime warning fires (there is no drag model to be invalid — the only low guard is then the impact backstop). The **Knudsen floor** is computed once at setup from the body's characteristic length L (sphere → diameter `2√(A/π)`; box → max edge length, conservative) by re-implementing the validity experiment's `Kn = λ/L = 10` free-molecular scan. Because Orekit's atmosphere API exposes only *total* density — not the per-species number densities λ needs — and pymsis is deliberately not a runtime dependency, the conservative high-activity composition is captured **offline** (`scripts/generate_kn_floor_composition.py`) and embedded as a constant in `propagation/guards.py`; the runtime scan runs against that fixed composition (a deterministic worst-case fence, not the run's live space weather). This is the *third* reconstruction of the experiment's method, held to the §5 equivalence check (cross-checked against the committed experiment floor curve).

**Metadata / reproducibility.** Fixed: `Cd=2.2`. Variable: `Cd=table:<name-or-hash>`. A `from_callable` table carries the "not byte-reproducible" gap noted for `CustomAttitude`.

**Accuracy framing (docstring).** Variable Cd removes a known systematic bias in the *coefficient* — most valuable at higher LEO near the oxygen-to-helium transition (~500 km) and for long decay studies that sweep through altitudes — but thermospheric density-model uncertainty (15–30%) still dominates total drag error. An honest improvement, not a path to truth.

**Full per-facet Sentman — still deferred.** A free-molecular model computing Cd per facet/species/substep (composition, ambient and surface temperature, incidence, accommodation) needs inputs Orekit withholds from `dragAcceleration`, so it requires re-querying the atmosphere or replacing the drag force, with per-substep JPype cost — research-grade beyond v1. Recorded in architecture §13.

### Model limitations (user-facing docstring note)

```
Spacecraft-model limitations (v1):
  * Solar radiation pressure uses uniform optical coefficients across the
    whole spacecraft. Per-face optical properties are not modeled.
  * Drag acts on the projected cross-section but produces no torque, and
    aerodynamic lift is not modeled; attitude is not perturbed by drag.
  * The drag coefficient is a fixed value, a (geocentric radius, density)
    table value (VariableCd, sphere or box), or — for a faithful box — an
    incidence-keyed table (IncidenceVariableCd). Per-facet gas-surface
    physics (full Sentman) is not modeled.
  * Drag modeling is valid only within an altitude band — free-molecular flow
    above a body-size-dependent floor (~110 km for a small CubeSat rising to
    ~220 km for a large bus/station) up to the Cd-table ceiling (~1400 km).
    Below the floor the run continues with a warning but drag is unreliable;
    a decaying orbit ends gracefully at re-entry, while impact and escape
    terminate the run, and user altitude limits may tighten these bounds.
```

### Outputs

`propagate_numerical` returns a `Trajectory` and nothing else; outputs are produced by separate, composable functions, with `export_all` bundling the common case.

```python
# plotting/trajectories.py
def plot_ground_track(traj, *, show_map_overlay=True, color_by_time=True) -> matplotlib.Figure: ...
def plot_3d(traj, *, frame=Frame.EME2000, show_earth=True,
            show_map_overlay=False, color_by_time=True) -> plotly.graph_objects.Figure: ...
# plotting/timeseries.py
def plot_altitude(traj) -> matplotlib.Figure: ...
def plot_speed(traj, *, frames=(Frame.EME2000,)) -> matplotlib.Figure: ...
# plotting/composite.py
def plot_summary(traj, *, speed_frames=(Frame.EME2000,), show_map_overlay=True) -> matplotlib.Figure: ...
# io/exports.py
def export_csv(traj, path, *, columns=None) -> None: ...
```

**`plot_summary` is the default visual** — a single `GridSpec` figure: ground track spanning the top row at a larger height weight, altitude beneath, then one speed panel per frame in `speed_frames`, time-series rows sharing the x-axis.

**`_draw_*(ax, traj, ...)` primitives.** Each plot's drawing logic lives in a private primitive (`_draw_ground_track`, `_draw_altitude`, `_draw_speed`) that draws onto a *supplied* `Axes`; public `plot_*` functions are thin wrappers, and `plot_summary` calls the same primitives. This is required, not stylistic: matplotlib can't move axes between figures, so a composite can't be assembled from standalone figures. Designing the primitives up front is cheap; retrofitting is not.

**`plot_speed` is a single series** — speed *magnitude* (one dark-blue line), not velocity components. `frames` selects inertial speed and/or ITRF (ground-relative) speed; requesting both yields two stacked dark-blue panels, each frame-labeled. ITRF speed is relative to the rotating Earth (most uses want inertial; ITRF is for ground-relative motion, e.g. near-GEO stationkeeping); the docstring spells this out.

**Map machinery.** Ground track and the 3D ITRF overlay share a `_render_earth_basemap()` helper that draws a bundled low-resolution Natural Earth coastline (shipped in `data/`) as a **black** `LineCollection` — no `cartopy`, keeping GEOS/PROJ out of the install and the static-hosting payload small. The same coastline drapes the 3D ITRF sphere. The 3D ITRF view shows a static Earth with the ground-track shadow under the inertial trace; the inertial view shows the orbit holding still as Earth rotates underneath.

**Styling.** A single shipped `plotting/propygator.mplstyle`, applied per-figure via a context manager *inside* each `plot_*` function (never by mutating global `rcParams` on import). Plotly figures get an analogous shared layout template. Ground track and 3D are colored *by time* (blue→red, via a `LineCollection` / color-mapped Plotly trace reading the same named colormap); all time-series use a fixed dark blue; continent outlines are black. Pinning the baseline early is a prerequisite for the §11 snapshot tests. Deferred to implementation: exact dark-blue hex, colormap endpoints, axis labels, figure sizes, legend placement.

**CSV columns.** Default set (`columns=None`), 16 columns: `epoch_utc` (ISO), `epoch_mjd_utc`, `x/y/z_eme2000_m`, `vx/vy/vz_eme2000_mps`, `x/y/z_itrf_m`, `latitude_deg`/`longitude_deg`/`altitude_m` (geodetic, WGS84), `speed_inertial_mps` (EME2000-relative magnitude), `speed_itrf_mps` (ground-relative magnitude). `columns` is additive — a list of opt-in group tokens appended to the defaults:

- Keplerian elements (a, e, i, Ω, ω, ν), computed **in EME2000** (the trajectory frame). Near-circular / near-equatorial orbits make ω, Ω, ν individually ill-conditioned (argument of latitude is the stable combination); see architecture §6.
- Sun position / direction columns (Sun lives in `core/bodies.py`, reachable without violating the dependency rule).

An eclipse flag is intentionally excluded — it would force `io/` to import `tracking/visibility.py` (architecture §7). Metadata goes in the CSV header as `# key: value` comment lines.

### `export_all` convenience function

```python
from collections.abc import Sequence

def export_all(
    traj: Trajectory,
    output_dir: Path,
    *,
    summary: bool = True,
    plot_3d: bool = True,
    csv: bool = True,
    show_map_overlay: bool = True,                     # ground track + ITRF 3D + ITRF speed
    speed_frames: Sequence[Frame] = (Frame.EME2000,),
    frames_3d: Sequence[Frame] = (Frame.EME2000,),
    csv_columns: list[str] | None = None,
    filename_prefix: str = "trajectory",
) -> dict[str, Path]:
    """Generate the standard outputs; return a dict mapping output name to
    written path. Files are `{filename_prefix}_{output}.{ext}` (e.g.
    `trajectory_summary.png`, `trajectory.csv`). The summary is one stacked
    matplotlib figure (ground track, altitude, one speed panel per
    speed_frames); 3D plot(s) and CSV are separate. When frames_3d has both an
    inertial frame and ITRF, two frame-suffixed 3D files are written."""
    ...
```

Booleans (not an `outputs=[...]` string list) preserve IDE autocomplete and static checking — a typo'd string would be a silent no-op. `frames_3d` / `speed_frames` are `Sequence[Frame]` with immutable tuple defaults. The `show_map_overlay` name matches `plot_ground_track` / `plot_3d` / `plot_summary` (it was `map_overlay` in an earlier draft). If the option set grows, the escape hatch is an `ExportConfig` dataclass, not a string list. Defaults give "I just want to see what happened": summary + an inertial 3D plot + CSV, map overlay on.

### Typical user code

```python
import propygator as pgr

# Simple
initial = pgr.State(...)
traj = pgr.propagate_numerical(initial, duration=86400, output_step=60)
pgr.export_all(traj, output_dir=Path("./run_01"))

# Box bus, in-plane tracking (+Z on orbit normal, +Y on velocity)
traj = pgr.propagate_numerical(
    initial, duration=86400, output_step=60,
    spacecraft=pgr.SpacecraftConfig(
        mass_kg=420,
        geometry=pgr.SpacecraftGeometry.box_and_panels(
            x_length_m=2.0, y_length_m=1.0, z_length_m=1.0,
            solar_array_area_m2=10.0,
            drag_coefficient=pgr.VariableCd.sphere_default(),  # Tier A scalar Cd
        ),
    ),
    attitude=pgr.InPlaneTracking(),
)
pgr.export_all(traj, output_dir=Path("./run_02"),
               speed_frames=[pgr.Frame.EME2000, pgr.Frame.ITRF],
               frames_3d=[pgr.Frame.EME2000, pgr.Frame.ITRF])

# Solar sail rolled 30 deg about the velocity axis
sail = pgr.SpacecraftConfig(
    mass_kg=50,
    geometry=pgr.SpacecraftGeometry.box_and_panels(
        x_length_m=10.0, y_length_m=10.0, z_length_m=0.001,
        solar_array_area_m2=0.0,
        specular_reflection_coefficient=0.85, absorption_coefficient=0.10,
    ),
)
traj = pgr.propagate_numerical(initial, duration=86400 * 7, output_step=60,
                               spacecraft=sail, attitude=pgr.LofOffset(roll_deg=30.0))
```

### Resolved decisions for 1.1

- **Attitude API** — seven-mode `AttitudeConfig` family (`LofAligned` / `LofOffset` / `Inertial` / `SunPointing` / `NadirPointing` / `InPlaneTracking` / `CustomAttitude`), TNW as the local orbital frame; all but `CustomAttitude` lower to native Orekit providers (`FrameAlignedProvider`, `CelestialBodyPointed` / `AlignedAndConstrained`, `LofOffset(TNW)`). `CustomAttitude.law` returns a propygator `Orientation`, not an Orekit/Hipparchus `Rotation`.
- **Spacecraft optical coefficients** — on the geometry factories; sphere uses one Cr, box uses absorption + specular (each in [0, 1]).
- **Variable drag coefficient** — `VariableCd`, a `(geocentric radius, total density)` table, for **sphere and box** (Tier A: density-varying scalar Cd); `IncidenceVariableCd` (Tier B: + body-frame incidence) is the faithful box extension, no shipped default; clamp-to-edge out-of-grid; the custom `DragSensitive` is built inside `propagate_numerical`. Full per-facet Sentman deferred.
- **IntegratorConfig** — three presets locked; `high_precision` rel-tolerance flagged for verification.
- **SRP shadow** — conical (umbra + penumbra), ellipsoidal Earth; matches Orekit's default.
- **Output layout** — composite `plot_summary`; 3D and CSV separate; `_draw_*(ax, ...)` primitives; `plot_speed` plots speed magnitude; ground track / 3D colored by time, time-series dark blue, outlines black, bundled coastline (no `cartopy`).
- **CSV** — 16 default columns; Keplerian opt-in columns computed in EME2000; eclipse flag excluded for dependency reasons.
- **`export_all`** — booleans `summary` / `plot_3d` / `csv`; `show_map_overlay` aligned with the `plot_*` functions; `Sequence[Frame]` options with tuple defaults.
- **Sample count** — `floor(duration/output_step + tol) + 1` with a small round-off tolerance.
- **Default-argument convention** — `None` sentinels, consistent with `fit_tle`.

### Still open / deferred for 1.1

- Cosmetic plot details (dark-blue hex, colormap endpoints, axis labels, figure sizes, legend placement) — deferred; structural layout is fixed. Endpoint glyphs are the current cosmetic baseline: a blue start circle in both spatial plots, and direction-indicating end glyphs — a heading-oriented triangle on the ground track and a velocity-oriented cone in the 3-D view (ECEF-nadir & direction-markers addendum §3).
- Full per-facet Sentman drag coefficient — deferred (architecture §13); `IncidenceVariableCd` is the faithful v1-extension path for the box.
- Time-varying / programmed attitude and local-orbital frames beyond TNW — deferred; `CustomAttitude` is the v1 escape hatch.

---

## 1.2 TLE fitter

> **Status: NOT STARTED.**

## 1.3 TLE propagator

> **Status: DRAFTED.** Signature, frame handling, outputs, the osculating-element CSV columns, the row→TLE utility, and metadata are settled. 1.3 reuses 1.1's `Trajectory`, plotting stack, and exporters wholesale; only the propagation core and the native output frame differ.

SGP4/SDP4 propagation of a TLE, producing the same `Trajectory` output and the same visual/CSV products as 1.1. The propagation core is Orekit's `TLEPropagator.selectExtrapolator(tle)`, which automatically picks the near-Earth (SGP4, period < 225 min) or deep-space (SDP4) branch — no user-facing knob.

### Public signature

```python
def propagate_tle(
    tle: TLE,
    *,
    duration: float,              # seconds; required, keyword-only
    output_step: float = 60.0,    # seconds; optional, unlike 1.1's required step
    start: Epoch | None = None,   # None → tle.epoch
    name: str | None = None,      # optional, recorded in metadata
) -> Trajectory:
```

The TLE comes from `TLE.from_strings(...)`, `TLE.from_norad_id(...)`, or `fetch_tle("ISS")` — friendly names resolve through the popular-satellite registry in `core/catalogs.py`, and the 6h/24h cache TTLs apply on the fetch path (architecture §10).

Notice what is absent relative to `propagate_numerical`: no `force_models`, `spacecraft`, `attitude`, or `integrator`. SGP4 is self-contained — its drag rides in the TLE's B\* term and the theory is fixed — which is what makes 1.3 the simple feature.

**`output_step` default.** Unlike 1.1, where `output_step` is required (keyword-only) to prevent argument-order mistakes, 1.3 defaults it to 60 s. This is a deliberate, documented divergence: SGP4 is a quick-look tool with no force model to reason about, so the convenience outweighs the cross-feature inconsistency. It stays keyword-only.

**`start` default.** Defaults to the TLE's own epoch (`tle.epoch`), because SGP4 is most accurate at epoch and degrades away from it. The common alternative is `start=Epoch.now()` for a "where is it now and next" view; both are documented, with the accuracy caveat below.

### Frame handling

SGP4 outputs natively in **TEME**, so `propagate_tle` returns a `Trajectory` in `Frame.TEME` — no silent conversion, consistent with the explicit-frame rule (architecture §10). Users wanting another frame call `.to_frame(...)` on the result.

For the *display* outputs, the inertial views default to **EME2000** — the same inertial frame 1.1 uses — so a ground track or 3D plot from a TLE is directly comparable to one from the numerical propagator, which is a common reason to run 1.3. The TEME→EME2000 conversion is cheap and needs only EOP, which the ITRF (ground-relative) outputs already require, so it adds no dependency; and it is visually inconsequential, because TEME and EME2000 differ by a slow frame rotation, so inertial *speed* is identical between them far below mm/s — only the axis label changes. TEME remains selectable for anyone who wants the raw SGP4 frame.

### Outputs

The visual and CSV products are 1.1's, reused unchanged: the stacked `plot_summary` (ground track on top, altitude, then one speed panel per requested frame), `plot_3d` (inertial and/or ITRF, with the black-coastline map overlay on the ITRF view), `plot_speed`, and `export_all` (summary + 3D + CSV). Ground track and 3D are colored by time (blue→red); time-series are dark blue. The only 1.3-specific output choices:

**Keplerian elements on by default in the CSV.** Because SGP4 is element-based, the six classical elements (a, e, i, Ω, ω, ν) — opt-in for 1.1 — are included by default in the 1.3 CSV. They are **osculating** elements computed from each row's state. Mean anomaly M is available alongside the true anomaly ν for the row→TLE path below.

**Row → TLE (`TLE.from_state`).** Any row's state can be turned into a syntactically valid TLE:

```python
TLE.from_state(
    state: State,
    *,
    norad_id: int | None = None,    # None → carried from source TLE, else placeholder
    bstar: float | None = None,     # None → carried from source TLE, else 0.0
    ...
) -> TLE
```

This is a **format-valid, not round-trip-faithful** utility, by explicit design ("accuracy aside"). The mechanics: it computes the state's osculating elements **in TEME** (a TLE lives in TEME; building from EME2000 elements would stack a frame error on top of the mean/osculating error), converts true anomaly ν → mean anomaly M for the TLE's anomaly field, derives the mean-motion field from the semi-major axis, and carries B\* and the NORAD id from the source TLE (or 0 / placeholders for a hand-built state). It produces correct field formatting and checksums.

The critical caveat, stated loudly in the docstring: **TLE elements are *mean* elements (Kozai-Brouwer, with periodic variations averaged out); the osculating elements computed from a state are not.** The J2 short-period term alone moves the osculating semi-major axis by tens of kilometers relative to the mean value. So a TLE built this way will **not** reproduce the trajectory when re-propagated with SGP4 — it is for format-level interop and inspection, not fidelity. For a TLE that actually round-trips, use `fit_tle` (feature 1.2), which performs the proper iterative osculating→mean fit on Orekit's TLE-generation machinery.

One expected artifact: because osculating elements wobble over an orbit, emitting one TLE per row yields a *family* of slightly different TLEs for the same orbit, each epoch-stamped to its row. That is correct behavior — and is itself a visualization of the osculating-vs-mean gap — but it surprises anyone expecting identical element sets.

`TLE.from_state` lives on the `TLE` type in `core/` (architecture §6); building a TLE from a `State` (both core types) respects the dependency rule.

### Metadata

```python
{
    "propygator_version": <str>,   # required, auto
    "orekit_version": <str>,       # required, auto
    "propagator": "sgp4",          # required, auto
    "tle_line1": <str>,            # optional, populated — source TLE line 1
    "tle_line2": <str>,            # optional, populated — source TLE line 2
    "norad_id": <int>,             # optional, populated
    "tle_epoch": <iso utc str>,    # optional, populated
    "start": <iso utc str>,        # optional, populated
    "output_step_s": <float>,      # optional, populated
    "created_at": <iso utc str>,   # optional, populated
    "name": <str>,                 # optional, only if name supplied
}
```

The source TLE lines make an SGP4 trajectory exactly reproducible. The `tle_line1` / `tle_line2` / `norad_id` / `tle_epoch` / `start` keys are new optional `TrajectoryMetadata` fields (architecture §6), analogous to the `spacecraft` / `attitude` / `name` keys added for 1.1. No `force_models` / `integrator` keys — they don't apply.

### Accuracy caveat (docstring)

SGP4 is accurate to roughly 1 km near the TLE epoch, degrading to many kilometers over days to weeks as drag and unmodeled perturbations dominate. It is not portable to a numerical propagator — B\* is a fit residual, not a physical ballistic coefficient (architecture §1.2). Propagating far from epoch, or from `Epoch.now()` against an old TLE, degrades accuracy accordingly.

### Resolved decisions for 1.3

- **Signature** — `duration` required keyword-only; `output_step` defaults to 60 s (deliberate divergence from 1.1); `start` defaults to `tle.epoch`. No force/spacecraft/attitude/integrator inputs.
- **Output frame** — native TEME from the propagator; EME2000 as the default display inertial frame (TEME selectable); ITRF for ground-relative views.
- **Outputs** — 1.1's `plot_summary` / `plot_3d` / `plot_speed` / `export_all` reused unchanged; Keplerian (osculating) elements on by default in the CSV.
- **Row → TLE** — `TLE.from_state`, a format-valid (not round-trip-faithful) utility using TEME osculating elements and ν→M; faithful TLEs are 1.2's `fit_tle`.
- **Metadata** — `propagator: "sgp4"` plus source-TLE keys; requires the §6 `TrajectoryMetadata` additions.

### Still open / deferred for 1.3

- Period-relative default `output_step` (a fixed number of points per revolution) instead of a flat 60 s — would suit GEO better; deferred as a refinement.
- Backward propagation before the TLE epoch (SGP4 supports it natively) — deferred; no v1 feature needs it.

## 1.4 Real-time tracker

> **Status: NOT STARTED.**

## 1.5 Ground passes + brightness

> **Status: NOT STARTED.**
