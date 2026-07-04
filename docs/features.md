# propygator — Feature sub-designs

Companion document to `architecture.md`. Where `architecture.md` locks in the cross-cutting decisions (data model, module structure, conventions), this document fleshes out the per-feature design for the five v1 features.

---

## 1.1 Numerical propagator

> **Status: DRAFTED.** Force-model, spacecraft, attitude, integrator, output, and metadata sections are settled. `VariableCd` (a precomputed Cd table keyed on geocentric radius and live total density) is the v1 variable-drag path for **both** sphere and box geometry (a density-varying scalar Cd); a per-face incidence-resolved box table (`BoxFaceCd`, Tier B) is shipped for the convex box (binding design `docs/general-upgrades-1.md` "Tier B Drag"). Full per-facet Sentman remains deferred (architecture §13). SRP uses a conical shadow. Attitude is a first-class input with seven modes, all but one backed by native Orekit providers. Remaining open items are cosmetic plot details. The **drag-validity & altitude-guards addendum** (drag-model validity domain + the altitude/regime guard system) has been built and folded into the subsections below — the signature (`limits=`), the metadata block (termination keys), "Escape and re-entry" (rewritten to the as-built guards), "Drag-coefficient modeling" (the §5 invariant, two-tier regime warnings, Knudsen floor), and the limitations note.

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
    drag_coefficient: float | VariableCd | BoxFaceCd = 2.2,
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
| `sphere` given a `BoxFaceCd` | `ValueError` (a sphere has no flow incidence; use a fixed Cd or `VariableCd`) |
| `box_and_panels` given a `BoxFaceCd` with `solar_array_area_m2 > 0` | `ValueError` (`BoxFaceCd` is a convex box only and cannot represent solar-array shadowing; set `solar_array_area_m2=0`, or use a fixed Cd / `VariableCd`) |

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
- `min_step_s` / `max_step_s` bound the adaptive controller; the wide defaults (1 ms–1000 s) mean a healthy propagation never bumps either bound. If the adaptive step is driven below `min_step_s` (usually an ill-posed problem), Hipparchus cannot meet tolerance and **stops** rather than silently continuing at an oversized step — the propagation raises `NumericalPropagationError` (see the failure table below). (Earlier drafts described this as an end-of-run *warning*; that assumed the integrator clamps at `min_step_s` and continues, which it does not — it raises.)
- **`high_precision` caveat:** `rel_tolerance = 1e-12` is demanding; on a stiff or ill-posed case it can drive the step below `min_step_s` and raise `NumericalPropagationError`. Verify against the §11 round-trip tests at implementation; if it raises on representative LEO/GEO cases, loosen to `1e-11` rather than shipping a preset that fails.

### `propagate_numerical` behavior

**Output step.** `output_step` controls the sampling rate of the returned `Trajectory`, not the integrator step. The integrator runs adaptively; Orekit's generated ephemeris (or a step handler) produces samples at exactly `output_step` intervals, decoupling integration accuracy from trajectory density.

**Sample count.** `floor(duration / output_step + tol) + 1` samples (with a small relative `tol ≈ 1e-9` to absorb float round-off so divisible cases are deterministic), first sample at `initial.epoch`, last at `initial.epoch + floor(...) * output_step`. If `duration` isn't an integer multiple of `output_step`, the trajectory ends just shy of `initial.epoch + duration`; no synthesized final partial-step sample.

A pre-flight cap rejects pathological grids: if the computed sample count exceeds `_MAX_OUTPUT_SAMPLES` (10,000,000 — e.g. a tiny `output_step` over a long `duration`), `propagate_numerical` raises `ValueError` before integrating rather than attempting a multi-gigabyte allocation. This cap is the shared facility 1.3's `propagate_tle` reuses for its identical sample-grid contract (features §1.3).

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

**`spacecraft` string.** Deterministic; numbers are coerced to `float` and rendered with `repr()` (so an int- and a float-valued coefficient serialize identically — `Cd=2` and `Cd=2.0` both yield `2.0`); semicolon separates geometry from mass/coefficients. A `VariableCd` / `BoxFaceCd` records `Cd=table:<name-or-hash>` (the hash folds in a kind tag and the table's axis set, so a 2-D `VariableCd` and a per-face `BoxFaceCd` can't collide; `BoxFaceCd.default()` records `Cd=table:box_face_default`).

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
| output sample count `floor(duration/output_step + tol) + 1` over the shared cap (`_MAX_OUTPUT_SAMPLES` = 10,000,000) | `ValueError` (propygator-side, before integration; reused by 1.3) |
| `gravity_field` / `atmosphere_model` / `integrator.type` doesn't resolve | `ValueError` (with known-name list) |
| `Inertial.reference_frame` non-inertial | `ValueError` |
| `SunPointing.pointing_axis` parallel to `phasing_axis` | `ValueError` |
| `attitude.law` not callable (`CustomAttitude`) | `ValueError` |
| `AltitudeLimits(...)` unreasonable — `min_altitude_km < 0`, `max_altitude_km` above the escape-parity altitude (≈ 320,621 km), or `min >= max` — raised at **construction**, not at a crossing | `ValueError` |
| `NadirPointing(velocity_reference='ecef')` on an orbit whose ground-relative velocity is ~0 (e.g. geostationary / instantaneously ground-stationary) — the yaw target `v_rel = v − ω⊕×r` is undefined, so its direction can't be formed | `NumericalPropagationError` (carrying the underlying message; LEO yaw-steering is the validated domain — ECEF-nadir addendum §2) |
| Integrator fails (usually `min_step_s` saturation) **and** the failure is a drag-driven re-entry (drag on, descending, osculating perigee already below the ~150 km drag-table floor) | *stop & report* — partial `Trajectory`, `termination_reason="reentry"` (**not** an error; addendum §6.6) |
| Integrator fails for any **other** reason (over-tight tolerance, bad setup, non-low-altitude stiffness) | `NumericalPropagationError` (may carry a recovered `err.partial_trajectory`, or `None`) |
| Unrecognized underlying Orekit failure | `NumericalPropagationError` wrapping the original |

`propagate_numerical` raises **`NumericalPropagationError`** — a subclass of the base `PropagationError` (both in `propygator.exceptions`; catch the base to catch any propagator's failure, including 1.3's `TLEPropagationError`) — carrying the Java exception's message as a string, no raw Java stack trace (same principle as `OrekitDataMissingError`, architecture §3). String-valued config fields are validated at the top of `propagate_numerical`, before integration. A drag-driven decay is **caught and classified** rather than always re-raised (addendum §6.6): a genuine re-entry stops and reports a partial `Trajectory` (`termination_reason="reentry"`), while any non-re-entry failure re-raises `NumericalPropagationError` — carrying a recoverable partial trajectory as `err.partial_trajectory` when usable steps were generated, else `None`. The invariant is **prefer a false re-raise over a false `reentry`**: when in doubt, raise.

**Escape and re-entry (drag-validity & altitude-guards addendum).** The propagator carries a geocentric-radius guard family that bounds both ends of the validity domain. All guards operate on `r = |position|` in the EME2000 propagation frame (one `sqrt`, no per-substep geodetic conversion).

- **Terminal backstops (always on).** Two custom radius event detectors stop the run cleanly and **report**: **impact** at `r < R⊕` (WGS84 equatorial, 6,378,137 m) and **escape** at `r > r_lunar_parity` (≈ 327,000 km — the Earth-Moon gravity-parity radius at lunar perigee; a fixed hard-coded policy fence, not Orekit-derived). The escape backstop makes an already-supported unbound (hyperbolic) `State` *safe*: runaway integration terminates instead of running to absurd distances. The parabolic `e == 1` rejection in `KeplerianElements` stays (a representability limit, orthogonal to these guards).
- **Re-entry (reactive).** A decaying orbit with drag on stiffens until the integrator saturates `min_step_s` (or the atmosphere model rejects the sub-surface query) and fails. That failure is **caught and classified**: drag on + descending + osculating perigee already below the ~150 km drag-table floor (the shipped Cd table's lower data edge — distinct from the body-size-dependent ~110–220 km Knudsen free-molecular floor used for the drag-regime *warning* below) → a physical re-entry that **stops & reports** (`termination_reason="reentry"`, partial `Trajectory`); anything else re-raises `NumericalPropagationError` (invariant: prefer a false re-raise over a false `reentry`). See the Failure modes table.
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

# Convex box (Tier B): a per-face (geocentric radius, density, face-flow angle) table.
BoxFaceCd.default()                          # shipped per-face box/plate table
BoxFaceCd.from_table(                        # grid shape (n_radius, n_density, n_incidence)
    grid, *, radius_axis, density_axis, incidence_axis, name=None,
)
BoxFaceCd.from_callable(fn, *, name=None)    # fn(radius_m, density_kgm3, theta_rad) -> Cd
```

`drag_coefficient` widens to `float | VariableCd | BoxFaceCd` (`sphere` accepts `float | VariableCd`; `box_and_panels` accepts all three). The `VariableCd` / `BoxFaceCd` objects are pure-Python tables, safe to construct before init.

**Tier A — density-varying scalar Cd (sphere and box).** A sphere has no incidence dependence, so `(radius, density)` fully determines its Cd. The box keeps Orekit's attitude-driven projected-area bookkeeping; only the scalar Cd it would apply is replaced by the table value. This captures the solar-cycle / diurnal / altitude trend that a flat 2.2 misses, but applies one scalar uniformly across faces — it does **not** capture per-face incidence (that is Tier B).

**Tier B — per-face incidence table (`BoxFaceCd`, convex box).** A box's true Cd also depends on how each *face* meets the flow. `BoxFaceCd` resolves this per face: a single universal `(geocentric radius, total density, face-flow angle θ ∈ [0, π])` table whose value is **one face's** Cd, referenced to that face's **full** area, as a function of the angle θ between the face normal and the incoming flow (θ = 0 head-on, π⁄2 edge-on, π fully leeward). The incidence projection is already baked in — the normal-pressure part falls off as `cos θ`, but the tangential-shear part does **not** vanish edge-on (it floors at ~0.07 at θ = π⁄2 and tapers smoothly to ~0 by θ ≈ 110°) — so the table spans the leeward half and every face is a direct lookup. In free-molecular flow a **convex** body never self-shadows, so total drag is the exact **independent sum of the six per-face contributions**: at runtime the attitude rotates the flow direction into the body frame, each face's θ is formed, and `CdA = Σ_i Cd_i · A_i` is assembled over the full face areas (no re-projection) and applied as the sphere-style `a = ½ (CdA/m) ρ |v_rel| v_rel`. Because the coefficient is per-unit-area and geometry-independent, **one shipped default serves every convex box and plate** — `BoxFaceCd.default()` (asset `data/box_face_cd_default.npz`), carrying the same gas-surface assumptions as the Tier A sphere default (SESAM accommodation anchored α = 0.90 / 400 km solar-max, diffuse re-emission, 300 K wall); a spacecraft with markedly different surface physics supplies its own via `from_table` / `from_callable`. The axis is θ (not `cos θ`): the shear's `sin θ` factor is smooth in θ but becomes `√(1−cos²θ)` — an infinite-derivative cusp at the poles — in `cos θ`, so a θ axis interpolates linearly with clean ~2nd-order convergence and no special node placement. All six faces are evaluated (windward *and* leeward) — dropping the leeward/edge shear would understate a near-cubic bus's drag by ~5–11 % at a face-on attitude and inject a non-physical discontinuity there. `BoxFaceCd` is **convex-box-only**: valid on `box_and_panels` with `solar_array_area_m2 == 0` (a protruding, articulating array makes the body non-convex, and its sweeping bus-array shadowing needs a panel method / DSMC — out of scope). Binding design: `docs/general-upgrades-1.md` "Tier B Drag".

**When `BoxFaceCd` matters (honest, scenario-dependent).** The per-face correction is *attitude-correlated*, so its orbit-level benefit depends entirely on how the body flies. For a bus flown **face-on / nadir-held / tumbling / Sun-pointing** — where the ram meets faces near head-on — a best-fit *physical* constant Cd (or `VariableCd`) absorbs almost all of the difference: the along-track divergence over a multi-day LEO propagation is **< 1 %**, and `BoxFaceCd` is not worth its per-substep cost there. Its load-bearing case is **grazing / edge-on flight of a high-area-to-mass flat plate (a solar / drag sail)**: there the tangential shear dominates, a physical constant Cd (2.2, or `VariableCd`) *under*-predicts along-track by ~1400–1640 km over 5 days at 400 km / solar max, and the constant needed to patch it (best-fit Cd ≈ 4.7) is unphysically large and *still* leaves a ~100 km residual — a **~2× effect a recalibrated scalar cannot absorb**. That non-absorbable regime is why `BoxFaceCd` ships. **Caveat on the ~2× figure:** it was measured with `InPlaneTracking`, which tracks **inertial** velocity only (it has no `velocity_reference` option — only `NadirPointing` offers `ecef`), so a body held "edge-on" that way sits a few degrees off the true Earth-relative flow; the idealized perfectly-edge-on benefit is larger (~9×), but the shipped, honestly-measured figure is ~2×. (Giving `InPlaneTracking` the same `ecef` option is a possible future upgrade — it would change a shipped "no parameters" contract, so it is *not* part of Tier B.)

**Runtime.** Each variable Cd maps to a thin custom `DragSensitive` whose `dragAcceleration` reads geocentric radius from the state, takes the passed-in total density (and, for `BoxFaceCd`, the attitude the state carries), interpolates Cd, and assembles `a = −½ (Cd·A/m) ρ |v_rel| v_rel` exactly as `IsotropicDrag` / the box model would. A `BoxFaceCd` instead sums the effective `CdA = Σ_i Cd_i · A_i` over the box's six faces inside its accel closure — it does **not** route through the Orekit box model (whose single uniform Cd cannot consume a per-face table; the box object is still built, but only to drive SRP). The inertial→body rotation is `state.getAttitude().getRotation().applyTo(...)`, verified to machine precision against Orekit's own box drag. **The custom `DragSensitive` is instantiated inside `propagate_numerical`, never at geometry construction** — that keeps the geometry factory on the safe-before-init surface (architecture §10).

As built (addendum Chunk 9), **every** drag path — sphere or box, *fixed Cd or a table* — routes through this one custom `DragSensitive`, so the free-molecular-floor warn-once hook (below) and the table-edge warnings share a single code path. The trade: a fixed-Cd sphere, which Orekit could otherwise drive natively via `IsotropicDrag`, now crosses the Java↔Python boundary for the drag formula on every substep — marginal next to the default `NRLMSISE-00` density query, a larger share under a cheaper atmosphere (`Harris-Priester`); the uniformity was judged worth it for v1. The shared proxy also exposes no drag `ParameterDriver`, which is invisible to forward/backward propagation and TLE fitting and matters only for numerical OD (out of scope for v1). See architecture §13.

> **Implementation note (Orekit sign convention, verified at build).** The textbook `a = −½ … |v_rel| v_rel` above assumes `v_rel = v_spacecraft − v_atmosphere`. Orekit hands `DragSensitive.dragAcceleration` the **opposite-signed** relative velocity, `relativeVelocity = v_atmosphere − v_spacecraft`, and `IsotropicDrag` therefore applies a **positive** scalar: `a = +½ (Cd·A/m) ρ |relativeVelocity| relativeVelocity`. The custom `DragSensitive` must use the `+½` form with Orekit's argument to match `IsotropicDrag` (verified to ~1e-21 m/s²); the two expressions denote the same physical deceleration. A faithfulness test pins this against `IsotropicDrag` at constant Cd. The per-substep work is a low-dimensional interpolation plus a `|position|`; far cheaper than per-facet Sentman, but measurably slower than stock fixed-Cd drag — benchmark at implementation.

**Where the table comes from.** `sphere_default()` is generated once by maintainers and committed to `data/`; end users load a small array and compute nothing. Generation sweeps a high-fidelity Cd model (closed-form Sentman for the sphere) over a grid of thermospheric conditions and regrids onto the `(radius, density)` mesh — order 10⁴–10⁵ vectorized evaluations, sub-minute. The convex-box `BoxFaceCd.default()` table is generated the same way by `scripts/generate_box_face_cd_table.py` — the per-face free-molecular closed form (normal pressure **and** tangential shear, Sentman/Schaaf-Chambre) swept over `(radius, density, θ)`, sharing the sphere default's accommodation model, cross-validated ≪ 1 % on `CdA` against the experiment kernel — and committed as `data/box_face_cd_default.npz`. Users needing a different surface material/temperature or a non-convex body supply their own via `from_table` / `from_callable`.

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
    table value (VariableCd, sphere or box), or — for a convex box with no
    solar arrays — a per-face free-molecular incidence table (BoxFaceCd,
    Sentman/Schaaf-Chambre) that resolves how each face meets the flow.
    Solar-array shadowing (non-convex bodies), aerodynamic lift, and
    higher-fidelity gas-surface physics (multiple reflection, per-facet
    material/temperature, transitional/continuum flow) are not modeled.
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

- Keplerian elements (a, e, i, Ω, ω, ν) — token `keplerian` — computed **in EME2000** (the trajectory frame). Near-circular / near-equatorial orbits make ω, Ω, ν individually ill-conditioned (argument of latitude is the stable combination); see architecture §6.
- Mean anomaly `mean_anomaly_deg` — token `mean_anomaly` — a single column computed per row via `KeplerianElements.mean_anomaly()`. Kept **separate** from the `keplerian` token so that group's pinned six-column set (and 1.1's CSV snapshots) stay byte-stable. Frame-invariant (M depends only on e and ν), though computed in EME2000 like the other element columns for consistency.
- Sun position / direction columns — token `sun` (Sun lives in `core/bodies.py`, reachable without violating the dependency rule).

Opt-in groups are appended in the fixed canonical order `keplerian, mean_anomaly, sun`, regardless of the order tokens are passed in `columns`, so the schema stays deterministic. An eclipse flag is intentionally excluded — it would force `io/` to import `tracking/visibility.py` (architecture §7). Metadata goes in the CSV header as `# key: value` comment lines.

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
- **Variable drag coefficient** — `VariableCd`, a `(geocentric radius, total density)` table, for **sphere and box** (Tier A: density-varying scalar Cd); `BoxFaceCd` (Tier B: a per-face `(radius, density, face-flow angle)` table for a convex box, with a shipped `default()`) resolves how each face meets the flow; clamp-to-edge out-of-grid; the custom `DragSensitive` is built inside `propagate_numerical`. Full per-facet Sentman deferred.
- **IntegratorConfig** — three presets locked; `high_precision` rel-tolerance flagged for verification.
- **SRP shadow** — conical (umbra + penumbra), ellipsoidal Earth; matches Orekit's default.
- **Output layout** — composite `plot_summary`; 3D and CSV separate; `_draw_*(ax, ...)` primitives; `plot_speed` plots speed magnitude; ground track / 3D colored by time, time-series dark blue, outlines black, bundled coastline (no `cartopy`).
- **CSV** — 16 default columns; Keplerian opt-in columns computed in EME2000; eclipse flag excluded for dependency reasons.
- **`export_all`** — booleans `summary` / `plot_3d` / `csv`; `show_map_overlay` aligned with the `plot_*` functions; `Sequence[Frame]` options with tuple defaults.
- **Sample count** — `floor(duration/output_step + tol) + 1` with a small round-off tolerance.
- **Default-argument convention** — `None` sentinels, consistent with `fit_tle`.

### Still open / deferred for 1.1

- Cosmetic plot details (dark-blue hex, colormap endpoints, axis labels, figure sizes, legend placement) — deferred; structural layout is fixed. Endpoint glyphs are the current cosmetic baseline: a blue start circle in both spatial plots, and direction-indicating end glyphs — a heading-oriented triangle on the ground track and a velocity-oriented cone in the 3-D view (ECEF-nadir & direction-markers addendum §3).
- Full per-facet Sentman drag coefficient — deferred (architecture §13); `BoxFaceCd` (Tier B, shipped) is the per-face convex-box path, and full per-facet material/temperature + non-convex shadowing remain the deferred extension.
- Time-varying / programmed attitude and local-orbital frames beyond TNW — deferred; `CustomAttitude` is the v1 escape hatch.

---

## 1.2 TLE fitter

> **Status: NOT STARTED (design sketch).** The binding `fit_tle` signature, the three reference-input paths, and the data-flow diagrams already live in `architecture.md` §8; the blurb below is a placeholder to be expanded into a full sub-design when 1.2 is scheduled. It is built **last** (architecture §12) and treated as a plus, not a blocker.

Fit a TLE to an observed orbit by least-squares, so a high-fidelity numerical result — or user-supplied observations — can be re-expressed as a shareable TLE under SGP4. `fit_tle(reference, *, fitting_span, force_models, initial_guess, max_iterations)` accepts either a `State` (propagated internally over `fitting_span` to build the reference trajectory) or a `Trajectory` (used directly), and returns a bare `TLE` (a richer `FitResult` is a deferred extension). It leans on Orekit's built-in TLE-generation/fitting machinery for the iterative osculating→mean fit.

The defining caveat, stated loudly in the docstring: the fit is **inherently lossy** because SGP4 is a simplified model (J2/J3/J4 zonal + single B\* drag for the near-Earth branch; simplified luni-solar + resonance for deep-space). A full-force numerical orbit can never be reproduced exactly. This is the faithful sibling of 1.3's deliberately-unfaithful `TLE.from_state_unfitted`.

**To flesh out when scheduled:** convergence/quality reporting (the deferred `FitResult`), B\* handling (fit vs. fixed), the initial-guess strategy, and failure modes (non-convergence).

## 1.3 TLE propagator

> **Status: DRAFTED.** Signature, frame handling, outputs, the osculating-element CSV columns, the row→TLE utility, and metadata are settled. 1.3 reuses 1.1's `Trajectory`, plotting stack, and exporters wholesale; only the propagation core and the native output frame differ. **The observer-centric sky view (the `look_angles` primitive + sky-track plot) has moved out of 1.3 to Feature 1.4** — the live tracker now needs a live sky-view panel, so the primitive is first built there and still pulls Feature 1.5's foundation forward (architecture §12). 1.3 is therefore now purely SGP4 propagation reusing 1.1's outputs; see §1.4.

SGP4/SDP4 propagation of a TLE, producing the same `Trajectory` output and the same visual/CSV products as 1.1. The propagation core is Orekit's `TLEPropagator.selectExtrapolator(tle)`, which automatically picks the near-Earth (SGP4, period < 225 min) or deep-space (SDP4) branch — no user-facing knob.

### Public signature

```python
def propagate_tle(
    tle: TLE,
    duration: float,              # seconds; positional-or-keyword, aligned with 1.1
    *,
    output_step: float,           # seconds; required, keyword-only (matches 1.1 exactly)
    start: Epoch | None = None,   # None → tle.epoch
    name: str | None = None,      # optional; falls back to tle.name, recorded in metadata
) -> Trajectory:
```

The TLE comes from `TLE.from_strings(...)`, `TLE.from_norad_id(...)`, or `fetch_tle("ISS")` — friendly names resolve through the popular-satellite registry in `core/catalogs.py`, and the 6h/24h cache TTLs apply on the fetch path (architecture §10). On the fetch path a network/HTTP **transport** failure (no network, DNS failure, connection refused, timeout, or an HTTP error status) raises `TLEFetchError` — a `PropygatorError` subclass carrying a clean message that names the NORAD id and the offline `TLE.from_strings` escape hatch, never `requests`' raw traceback (architecture §3). An id that resolves but returns no object, a malformed response block, or an unknown `source` raises `ValueError` (not-found / input conditions, not transport failures); `TLE.from_norad_id` shares this behavior since it delegates to `fetch_tle`.

Notice what is absent relative to `propagate_numerical`: no `force_models`, `spacecraft`, `attitude`, or `integrator`. SGP4 is self-contained — its drag rides in the TLE's B\* term and the theory is fixed — which is what makes 1.3 the simple feature.

**`duration` calling convention.** `duration` sits before the `*`, so — exactly like 1.1's `propagate_numerical(initial, duration, *, ...)` — it is positional-or-keyword: `propagate_tle(tle, 86400)` and `propagate_tle(tle, duration=86400)` both work. An earlier draft made it keyword-only; that is dropped, so the two propagators share one calling convention for `duration`. With `output_step` now *also* required and keyword-only (below), the calling conventions are identical — the only signature differences are 1.3's **absent** `force_models` / `spacecraft` / `attitude` / `integrator` inputs and its added `start`.

**`output_step` required (no default).** `output_step` is required and keyword-only, **exactly as in 1.1** — there is no 60 s default. An earlier draft defaulted it for quick-look convenience; that is dropped in favour of full cross-feature consistency. The decisive reason is that a *defaulted* step turns the `output_step > duration` guard into a foot-gun: a short quick-look like `propagate_tle(tle, 30)` would raise `ValueError` for a step the user never chose. Requiring the step makes that guard unambiguous (the user always picked it) and lets 1.3 reuse 1.1's propagator-agnostic pre-flight via the promoted shared `core/sampling.py` helper — the positive/ordered-step checks *and* the output-sample cap (below) — rather than a bespoke relaxed copy. (1.1's `_validate_inputs` interleaves these with numerical-only checks, so the shared subset is extracted to `core/` rather than reused in place; see `docs/build-plan-feature-1.3-notes.md` #7.) The cost is one extra keyword at the call site (`propagate_tle(tle, 3600, output_step=60)`); the README / §9 examples already pass it explicitly.

**`start` default.** Defaults to the TLE's own epoch (`tle.epoch`), because SGP4 is most accurate at epoch and degrades away from it. The common alternative is `start=Epoch.now()` for a "where is it now and next" view; both are documented, with the accuracy caveat below.

**`name` default.** When `name` is omitted it falls back to the TLE's own name (`tle.name`), so a fetched or 3-line TLE (`fetch_tle("ISS")` → `"ISS (ZARYA)"`) carries its identity into the trajectory's metadata `name` with no extra typing. An explicit `name=` always wins; a bare 2-line TLE whose `tle.name` is `None` leaves the metadata `name` unset (unchanged from supplying nothing). This reuses the existing optional `name` metadata field — no new key — so 1.1's metadata grammar and its CSV-header snapshots are untouched. (For the fallback to carry anything, the fetch path / `TLE.from_strings`' 3-line form must populate `tle.name`; see `docs/build-plan-feature-1.3-notes.md` Note 3.)

### Frame handling

SGP4 outputs natively in **TEME**, so `propagate_tle` returns a `Trajectory` in `Frame.TEME` — no silent conversion, consistent with the explicit-frame rule (architecture §10). Users wanting another frame call `.to_frame(...)` on the result. The returned `Trajectory`'s `epoch_scale` follows 1.1's convention: it inherits the scale of `start` (which defaults to `tle.epoch`), with no forced re-scaling — just as 1.1 inherits `initial.epoch`'s scale.

For the *display* outputs, the inertial views default to **EME2000** — the same inertial frame 1.1 uses — so a ground track or 3D plot from a TLE is directly comparable to one from the numerical propagator, which is a common reason to run 1.3. The TEME→EME2000 conversion is cheap and needs only EOP, which the ITRF (ground-relative) outputs already require, so it adds no dependency; and it is visually inconsequential, because TEME and EME2000 differ by a slow frame rotation, so inertial *speed* is identical between them far below mm/s — only the axis label changes. TEME remains selectable **in the plot verbs** (`plot_3d(frame=Frame.TEME)`, `plot_speed(frames=...)`) for anyone who wants the raw SGP4 frame; `export_csv` has no frame switch — it always writes the EME2000 + ITRF columns (architecture §6), so a TEME view of the tabular data means converting the trajectory yourself or reading the EME2000 columns.

### Failure modes and terminal behavior

Unlike `propagate_numerical`, 1.3 carries **no altitude-guard family** and no `limits=` parameter — and that is deliberate, not an omission. 1.1's impact/escape radius detectors and min-step re-entry catch exist to tame *numerical integration* (adaptive-step stiffness, runaway integration of unbound states, sub-surface atmosphere queries); SGP4/SDP4 is a closed-form analytic evaluation with none of those failure modes. The escape backstop is also structurally moot: a TLE encodes a bound orbit (mean motion > 0 ⟹ finite `a`), so SGP4 cannot represent a hyperbolic escape. The contract is therefore to **let Orekit's `TLEPropagator` enforce its own validity envelope, and translate — never second-guess — its outcome.** Two error classes:

| Condition | Exception |
|---|---|
| `duration <= 0` / `output_step <= 0` / `output_step > duration` | `ValueError` (propygator-side, before any Orekit call) |
| output sample count `floor(duration/output_step + tol) + 1` over the shared cap (`_MAX_OUTPUT_SAMPLES` = 10,000,000; a tiny `output_step` over a long `duration`) | `ValueError` (propygator-side; reuses 1.1's cap via the promoted `core` helper — see `docs/build-plan-feature-1.3-notes.md` #7) |
| Malformed TLE (bad checksum / field) | `ValueError` at `TLE.from_strings` construction (architecture §10), so `propagate_tle` receives a valid TLE |
| SGP4/SDP4 internal failure during the span — orbit has **decayed**, sub-surface semi-major axis, eccentricity out of range | caught `OrekitException`, re-raised as `TLEPropagationError` (carrying the Orekit message string, no Java trace, per architecture §3) |
| Unrecognized underlying Orekit failure | `TLEPropagationError` wrapping the original |

**No stop-and-report on decay.** 1.1 catches a drag-driven re-entry and returns a *partial* `Trajectory` with `termination_*` metadata; 1.3 deliberately does **not**. The reason is fidelity-honesty, not effort: SGP4 is least reliable precisely as it approaches decay, so handing back a partial trajectory would imply accuracy that isn't there. A decay therefore raises **`TLEPropagationError`** cleanly — a subclass of the base `PropagationError` (so `except PropagationError` catches it and 1.1's `NumericalPropagationError` alike), but **without** a `partial_trajectory` attribute at all (1.1's `NumericalPropagationError` carries one; SGP4 never does). Consequently the `terminated` / `termination_reason` / `termination_epoch` `TrajectoryMetadata` keys (added by the drag-validity & altitude-guards addendum) are **never written by 1.3** — a completed SGP4 run's metadata is exactly the block in "Metadata" below, and a failed one raises rather than returning a partial. A user who needs a hard altitude cutoff on an SGP4 trajectory post-filters the returned `Trajectory` themselves.

**Stale-TLE warning (warn-once, not an error).** SGP4 accuracy degrades with time from the TLE epoch, so when a propagation *reaches* far from epoch the run emits a one-time `warnings.warn` — it does **not** raise. SGP4 can evaluate at any time; it is merely inaccurate there, and blocking long spans would break legitimate qualitative / decay-visualisation and teaching uses. The trigger is the worst-case age over the whole span, `max(|start − tle.epoch|, |(start + duration) − tle.epoch|)` (both ends, because `start` may legally precede `tle.epoch`), exceeding a fixed **30-day** threshold. It is pure-`Epoch` arithmetic (no JVM), lives in the same propygator-side pre-flight as the `ValueError` checks, and is **1.3-specific** — 1.1 has no epoch-staleness analogue. It operationalises the accuracy caveat at the point the user sees it, mirroring 1.1's warn-once idiom (drag-regime / attitude-geometry warnings).

### Outputs

The visual and CSV products are 1.1's, reused unchanged: the stacked `plot_summary` (ground track on top, altitude, then one speed panel per requested frame), `plot_3d` (inertial and/or ITRF, with the black-coastline map overlay on the ITRF view), `plot_speed`, and `export_all` (summary + 3D + CSV). Ground track and 3D are colored by time (blue→red); time-series are dark blue. The only 1.3-specific output choices:

**Keplerian elements stay opt-in (1.1's convention).** An earlier draft turned the six classical elements (a, e, i, Ω, ω, ν) on by default for 1.3 because SGP4 is element-based. That is dropped: 1.3 respects 1.1's opt-in `columns=["keplerian"]` convention, so `export_csv(traj, path)` yields the identical 16 default columns for both propagators and `io/` needs no propagator-type branch. A 1.3 user who wants elements passes the token explicitly; they are **osculating** elements computed from each row's state **in EME2000** — `export_csv` converts to EME2000 for every column regardless of the trajectory's frame (architecture §6), so the elements are reported there, not in TEME. (Only i, Ω, ω are frame-sensitive; a, e, ν — and the `mean_anomaly` token below — are rotation-invariant between inertial frames, so the choice is immaterial for them.)

**Mean anomaly M — a new opt-in token.** For the row→TLE path below it is convenient to have mean anomaly M alongside the true anomaly ν. M is exposed as its own additive CSV token (`columns=["mean_anomaly"]`), kept **separate** from the `keplerian` token so that token's pinned six-column set — and 1.1's CSV snapshot tests — stay byte-stable. M is cheap and already computed: `KeplerianElements.mean_anomaly()` exists (architecture §6) and the forward Kepler chain ν→E→M is closed-form (no iteration). The token is built and documented as a first-class CSV token in features §1.1 "CSV columns".

**Row → TLE (`TLE.from_state_unfitted`).** Any row's state can be turned into a syntactically valid TLE:

```python
TLE.from_state_unfitted(
    state: State,
    *,
    norad_id: int | None = None,    # None → placeholder 00000
    bstar: float | None = None,     # None → 0.0 (no drag info — see reason 2)
    name: str | None = None,
) -> TLE
```

This is a **format-valid, not round-trip-faithful** utility, by explicit design ("accuracy aside") — the `unfitted` in the name carries the warning. The mechanics: it computes the state's osculating elements **in TEME** (a TLE lives in TEME; building from EME2000 elements would stack a frame error on top of the mean/osculating error), converts true anomaly ν → mean anomaly M for the TLE's anomaly field, derives the mean-motion field from the semi-major axis, and formats the NORAD id and B\* the caller supplied — or placeholders (`00000` / `0.0`) when omitted. A bare `State` carries **neither** a catalog number nor a drag term, so there is nothing to "carry from a source TLE": those two fields are passed explicitly or defaulted. It produces correct field formatting and checksums.

Three independent reasons it will **not** reproduce the trajectory under SGP4 — all stated loudly in the docstring:

1. **Mean vs osculating.** TLE elements are *mean* elements (Kozai-Brouwer, with periodic variations averaged out); the osculating elements computed from a state are not. The J2 short-period term alone moves the osculating semi-major axis by tens of kilometers relative to the mean value.
2. **B\* is not recoverable from a state.** B\* is a drag *fit residual*, not a physical ballistic coefficient (architecture §1.2), so it cannot be derived from a position/velocity — only passed in or defaulted. A default `bstar=0.0` gives the rebuilt TLE *no drag*, so it diverges immediately from any decaying orbit.
3. **The anomaly and element fields are osculating values placed in mean-element slots**, as in (1). (The mean-motion field in particular is derived as `n = sqrt(µ/a³)` from the library's WGS84 GM, not SGP4's WGS72 constants — a further small offset, folded under "format-valid, not faithful.")

So a TLE built this way is for format-level interop and inspection, not fidelity. For a TLE that actually round-trips, use `fit_tle` (feature 1.2), which performs the proper iterative osculating→mean fit on Orekit's TLE-generation machinery.

One expected artifact: because osculating elements wobble over an orbit, emitting one TLE per row yields a *family* of slightly different TLEs for the same orbit, each epoch-stamped to its row. That is correct behavior — and is itself a visualization of the osculating-vs-mean gap — but it surprises anyone expecting identical element sets.

`TLE.from_state_unfitted` lives on the `TLE` type in `core/` (architecture §6); building a TLE from a `State` (both core types) respects the dependency rule. The `unfitted` qualifier is deliberate: `fit_tle` is the faithful sibling, and the asymmetry should be visible at the call site.

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
    "name": <str>,                 # optional; the name arg, else tle.name if set
}
```

The source TLE lines make an SGP4 trajectory exactly reproducible. `propagator` is always `"sgp4"` — that single token also covers the auto-selected deep-space (SDP4) branch (`selectExtrapolator` switches internally past the ~225-min period cutoff), and because the TLE lines are recorded the branch is reproducible with no separate token, so no `"sdp4"` value is introduced (it stays within the architecture §6 `"numerical" | "sgp4" | "user"` set — `"user"` tags a hand-assembled trajectory and is emitted by `_default_metadata`). The `tle_line1` / `tle_line2` / `norad_id` / `tle_epoch` / `start` keys are new optional `TrajectoryMetadata` fields (architecture §6), analogous to the `spacecraft` / `attitude` / `name` keys added for 1.1. `norad_id` is stored as an `int` (mirroring `TLE.norad_id`, architecture §6); the export writer stringifies it in the CSV header like every other metadata value, so storing it as a number costs nothing at the boundary. No `force_models` / `integrator` keys — they don't apply.

### Accuracy caveat (docstring)

SGP4 is accurate to roughly 1 km near the TLE epoch, degrading to many kilometers over days to weeks as drag and unmodeled perturbations dominate. It is not portable to a numerical propagator — B\* is a fit residual, not a physical ballistic coefficient (architecture §1.2). Propagating far from epoch, or from `Epoch.now()` against an old TLE, degrades accuracy accordingly.

### Testing / reference cases

Per architecture §11:

- **SGP4 implementation-agreement.** Verify `propagate_tle` output against **published Vallado SGP4 test vectors** (the canonical *Revisiting Spacetrack Report #3* / AIAA 2006-6753 cases) to centimetre agreement at sampled times, **compared in the native TEME frame** — comparing after a TEME→EME2000 conversion injects EOP-dependent differences that would blow the centimetre budget, so the test reads the raw SGP4 output frame. Cover **both branches**: at least one near-Earth (SGP4, period < 225 min) *and* one deep-space (SDP4) vector from the same suite (e.g. a Molniya-type case such as 08195 / 04632 — verify the catalog number against the published case list), so `selectExtrapolator`'s automatic branch pick is exercised. This is *implementation-agreement* with the reference SGP4/SDP4, **not** absolute accuracy against truth (which degrades with time from epoch; see the accuracy caveat above).
- **ISS end-to-end.** Exercise a fixed ISS TLE through `propagate_tle` → `plot_summary` / `export_all`, confirming the 1.1 output stack consumes a TEME-framed trajectory unchanged.
- **Sample-count contract.** Assert `propagate_tle` honours the §1.1 sample-count formula exactly (`floor(duration/output_step + tol) + 1`, first sample at `start`), so the two propagators produce identically-gridded trajectories — this is the test that would catch the dependency-rule duplication/promotion decision drifting (see `docs/build-plan-feature-1.3-notes.md`).
- **CSV snapshot.** A CSV snapshot for a fixed ISS TLE + `columns=["keplerian", "mean_anomaly"]` pins the EME2000 element frame and the `keplerian, mean_anomaly, sun` column order.

### Resolved decisions for 1.3

- **Signature** — `duration` required, **positional-or-keyword** (aligned with 1.1); `output_step` required and keyword-only, **no default** (the former 60 s default is dropped for full 1.1 consistency and to keep the `output_step > duration` guard unambiguous); `start` defaults to `tle.epoch`. No force/spacecraft/attitude/integrator inputs.
- **Output frame** — native TEME from the propagator; EME2000 as the default display inertial frame (TEME selectable **in the plot verbs**, not in `export_csv`); ITRF for ground-relative views. Opt-in Keplerian / `mean_anomaly` CSV columns are always computed in EME2000 (architecture §6), since only i/Ω/ω are frame-sensitive.
- **Outputs** — 1.1's `plot_summary` / `plot_3d` / `plot_speed` / `export_all` reused unchanged; **Keplerian elements stay opt-in** (1.1's convention), with mean anomaly **M** as a separate `mean_anomaly` token (features §1.1 "CSV columns").
- **Terminal behavior** — no altitude-guard family and no `limits=` (SGP4 has none of numerical integration's failure modes; escape is structurally moot for a bound TLE); argument errors raise `ValueError`, and SGP4/SDP4 decay / internal failures are caught and re-raised as `TLEPropagationError` (no stop-and-report, no `termination_*` metadata). Pre-flight reuses 1.1's propagator-agnostic checks via the promoted shared `core/sampling.py` helper (positive/ordered-step checks + the shared `_MAX_OUTPUT_SAMPLES` cap), not the monolithic `_validate_inputs` in place; a far-from-epoch span emits a warn-once stale-TLE warning, never an error.
- **Row → TLE** — `TLE.from_state_unfitted`, a format-valid (not round-trip-faithful) utility using TEME osculating elements and ν→M; `norad_id` / `bstar` are optional with placeholder defaults (a `State` carries neither); faithful TLEs are 1.2's `fit_tle`.
- **Metadata** — `propagator: "sgp4"` plus source-TLE keys (`norad_id` typed `int`); requires the §6 `TrajectoryMetadata` additions.

### Still open / deferred for 1.3

- A *convenience default* for `output_step` — dropped from v1: `output_step` is now required, matching 1.1. If a default is ever reintroduced, a period-relative one (a fixed number of points per revolution) would suit GEO better than a flat number; deferred as a refinement.
- Tuning the 30-day stale-TLE warning threshold (or making it configurable) — fixed at 30 days for v1; deferred.
- Backward propagation before the TLE epoch (SGP4 supports it natively) — deferred; no v1 feature needs it.

## 1.4 Real-time tracker

> **Status: BUILT (on `feature/tle-tracker`; squash-merge as `v0.4.0` pending — trust the git log). Buffer magnitudes finalized.** Two layers: (a) the cheap **real-time primitives** (`current_state` / `current_ground_position`) sketched in architecture §7, and (b) a **live, buffered dashboard** — the substance of this feature. The signature, panel set, and behaviour below are settled and binding; the **buffer magnitudes** (`output_step` / `half_window_s` / `refresh_s`) were dialled in against look/feel and compute cost during the build and finalized at `output_step=10 s`, `half_window_s=2700 s`, `refresh_s=1 s` (still tunable parameters, not contract). 1.4 also first builds the sky-view infrastructure (the `look_angles` primitive + sky-track plot) — before 1.5, so 1.5's topocentric foundation is pulled forward (architecture §12).

1.4 answers "where is this satellite *now*, and show me." It has a cheap query layer and a richer live-visualization layer; both ride on 1.3's `propagate_tle` and 1.1's output primitives, so 1.4 adds little new physics — it is composition.

### Real-time primitives

```python
def current_state(tle: TLE) -> State: ...              # TEME (SGP4-native); .to_frame(...) to convert
def current_ground_position(tle: TLE) -> GeodeticPosition: ...  # TEME→ITRF→geodetic, lat/lon/alt directly
```

`current_state` returns the satellite state at `Epoch.now()` in **TEME** (the natural SGP4 frame; no silent conversion, architecture §10). `current_ground_position` returns a `GeodeticPosition` (lat/lon/alt) directly — it carries no `Frame`, so it is allowed to convert internally (TEME→ITRF→geodetic). Both live in `tracking/realtime.py`. They are **not** literally `propagate_tle` evaluated at one instant — `propagate_tle` requires `duration > 0` and returns a *`Trajectory`*, not a single `State`. Instead they reuse a shared single-shot TEME-`State` helper, `_tle_state_at(tle, epoch) -> State` (`selectExtrapolator(tle)` → `propagate(epoch)` → PV in TEME), in `tle/propagator.py`, so no throwaway trajectory/ephemeris is built for one point. (`selectExtrapolator` is one-time *setup* — `propagate_tle` builds the propagator once and hoists it **above** its sample loop — so `_tle_state_at` is its own single-shot helper, **not** literally `propagate_tle`'s per-sample loop body; `propagate_tle`'s loop is deliberately *not* re-routed through it, which would rebuild the propagator on every grid epoch.) The **6-hour realtime cache TTL** (architecture §10) only applies on a *fetch* that selects it — these primitives take a `TLE` directly and never fetch, so the TTL governs whatever fetch produced that TLE (see the TTL note under *Live dashboard*; `fetch_tle` now exposes a keyword-only `ttl_s` selector that the live/realtime path uses to reach the 6 h realtime TTL).

### Live dashboard

A live, self-updating matplotlib view that tracks the satellite in real time across **three or four panels** — **ground track, altitude, speed**, plus a **sky view** when a `GroundStation` is supplied. It is a *display item only* — ephemeral, not saved.

**Buffer engine (pure, headless-testable).** The engine maintains a rolling `Trajectory` buffer **centred on `now`**, covering `[now − half_window_s, now + half_window_s]`, produced by `propagate_tle`. The buffer is **symmetric on purpose**: the trailing half is the path the satellite has already flown and the leading half is where it is going, so the ground track reads as motion — a fixed past-and-future path with the live marker sliding along it. Each frame the engine reads the current state by interpolation — `buffer.at(Epoch.now())`, the already-built cached-`Ephemeris` Hermite lookup (architecture §6) — so rendering is smooth and decoupled from the buffer's `output_step`. Re-propagation is **drain-triggered**: the engine rebuilds the buffer by re-propagating when `now` reaches the displayed leading edge (never on the `refresh_s` redraw tick); the path on the panels is otherwise **static between re-propagations**. Two safeguards keep the per-frame `buffer.at(now)` strictly in-bounds — `Trajectory.at` does a Python bounds check and raises `ValueError` on an out-of-span query (no extrapolation, architecture §13): (a) the buffer is propagated with a small **leading guard margin past the displayed edge**, so the realized last sample sits beyond `now + half_window_s` even across a blocking rebuild; and (b) the query is **clamped to the realized last sample**, `buffer.at(min(now, buffer.end_epoch))`, reading the trajectory's realized span endpoint through a small additive public `Trajectory.start_epoch` / `end_epoch` accessor — the single source of truth, the very endpoint `Trajectory.at` already bounds-checks against (`core/states.py`) — **rather than re-deriving** the sample grid's `floor`-with-tolerance last-sample formula inside `live.py`, which would couple the engine to `core/sampling.py`'s exact rounding and, on any drift, clamp to a still-out-of-span epoch and re-introduce the very crash this guard exists to prevent; so even a pathological stall degrades to a momentarily frozen marker rather than a crash. (The public span accessor — `Trajectory.start_epoch` / `end_epoch`, thin read-only wrappers over the private `_epoch_at` — was added as a 1.4 prerequisite, replacing the earlier plan of recomputing the grid in the engine; see the 1.3/1.4 pre-build notes.) (A very fresh TLE — epoch less than `half_window_s` ago — makes the trailing start precede the TLE epoch; this is deliberately **left unclamped**. `propagate_tle` legally accepts a `start` before `tle.epoch` (SGP4 evaluates backward, and the buffer is still a *forward* propagation from `start` — not the deferred backward-propagation case), the offset is far inside the 30-day stale-TLE threshold, and clamping would break the centred-buffer symmetry by pushing the live marker off-centre.) **Auto-refresh:** if the satellite was obtained via the fetch path (a name / NORAD id resolved through `fetch_tle`), the rebuild also re-fetches the TLE — so a long-running view stays accurate; a directly-supplied `TLE` is only re-propagated. **Stale-TLE warning (directly-supplied case):** because each rebuild re-invokes `propagate_tle`, a directly-supplied TLE already older than the 30-day stale threshold would re-emit `propagate_tle`'s stale warning on *every* rebuild — its message embeds the age in days, so Python's warning dedup does not collapse the repeats — a long-run nag. The engine instead checks staleness **once at startup**, emits a single notice, and then suppresses the per-rebuild repeat *surgically*: `propagate_tle`'s stale warning is given a dedicated `StaleTLEWarning(UserWarning)` category (an additive, backward-compatible 1.3 change) that the engine filters for the session — not a blanket warning-swallow, so a genuine decay (`TLEPropagationError`) still surfaces. (Fetched targets re-fetch a fresh TLE each rebuild, so they never reach this path.) The re-fetch **rides on the re-propagation** (once per rebuild, ~every `half_window_s`), never on the `refresh_s` redraw — and the realtime-TTL cache then collapses repeated re-fetches to at most one CelesTrak round-trip per cache window, so the engine reuses the existing cache rather than tracking fetch times itself. **(TTL plumbing — built: `fetch_tle` now takes a keyword-only `ttl_s: float | None = None` (forwarded to `fetch_celestrak`; default `None` keeps the 24 h general TTL), so the live/realtime path selects `_TTL_REALTIME_S` (6 h) and auto-refresh collapses repeated re-fetches to ≤1 CelesTrak round-trip per ~6 h.)** Each rebuild (and a cache-miss re-fetch) is a synchronous, blocking step on the draw thread — a brief stall every ~`half_window_s` (and at most ~every 6 h for the network); v1 accepts this, with an off-thread rebuild-and-swap as a named later option (the headless engine is the seam). The buffer/refresh state machine is plain Python over existing verbs and is tested directly, without a display.

**The view (the only "live" part).** A single `matplotlib.animation.FuncAnimation` drives a 3- or 4-axes figure (the sky axis is added only when a `station` is given; the layout is a `GridSpec` assembled conditionally), building each panel **once** from the **1.1 `_draw_*(ax, ...)` primitives** (`_draw_ground_track`, `_draw_altitude`, `_draw_speed`) plus the new **`_draw_sky_track`** (below) — for the two primitives that derive a JVM-crossing array *internally*, **handed the engine's precomputed arrays** so the redraw stays pure (see *Per-frame work*) — and thereafter **mutating the persistent artists in place** (the v0.5.0 mutate-in-place upgrade, `general-upgrades-1.md` "Live Dashboard Blitting"): each tick mutates only the dynamic now-indicators, a buffer rebuild refreshes the static curves' data in place, nothing ever calls `ax.clear()` or re-autoscales, and every axis limit is pinned once (ground/sky by their primitives, altitude/speed from the first buffer) — so a user's **toolbar zoom/pan survives every redraw and every rebuild**. One refinement to the pinned limits: if a later buffer's altitude/speed curve would exceed the first-buffer envelope (a buffer shorter than one orbit, an eccentric orbit, drag decay), the rebuild **widens the dashboard's own y-limits — never shrinks them, and never once the user has zoomed or panned that panel** — so the curve can't clip out of an untouched view. The animation runs at `blit=False`: the blit layer proper was declined at that upgrade's Checkpoint-A gate (at 1 Hz the flicker-free/CPU win did not justify coupling to matplotlib's private blit internals) and stays the named later optimization. The function returns the native `FuncAnimation` object (consistent with "every `plot_*` returns its native figure", architecture §10) — and the caller **must keep a reference to it** (`anim = live_track(...)`), or matplotlib garbage-collects the animation and it silently stops (documented alongside the inline-backend caveat below).

**Dashboard layout.** The panels are placed with a `GridSpec` sized to each panel's natural aspect — the ground track is the wide hero strip on top, the time-series stack beneath it sharing a time axis, and the square sky polar (when present) sits to their right:

- **3-panel (no `station`)** — `GridSpec(3, 1, height_ratios=[2, 1, 1])`: ground track (row 0, full width), altitude (row 1), speed (row 2). The two time-series share the x (elapsed-time) axis.
- **4-panel (with `station`)** — `GridSpec(3, 2, height_ratios=[2, 1, 1], width_ratios=[1.4, 1])`: ground track spans row 0 across both columns; altitude (row 1, col 0) and speed (row 2, col 0) stack on the left sharing the time axis; the sky polar spans rows 1–2 in col 1.

The ratios are tunable placeholders (like the buffer magnitudes), dialled in against look/feel during the build.

**Per-frame work (cheap *only with the compute/draw split*).** The expensive, JVM-crossing quantities are derived **once per re-propagation**, not per frame — but this is a property the panels must be *built* to, not a given, because two of the 1.1 `_draw_*` primitives derive their array **internally on every call**. The split mirrors `geodetic_track`, which already *is* a compute-once (memoized on the `Trajectory`) / draw-many helper:

- **Ground track & altitude — free.** `_draw_ground_track` / `_draw_altitude` both ride `geodetic_track`, memoized on the buffer `Trajectory`, so the first frame of a buffer pays the O(N) projection and every later frame hits the cache. No change needed.
- **Speed & sky — need a precomputed-array seam.** `_draw_speed` calls `traj.to_frame(frame)` internally and `_draw_sky_track` calls `look_angles_track(station, traj)` internally, and **neither result is trajectory-memoized** (`to_frame` returns a fresh `Trajectory`; `look_angles_track` is station-keyed by design). Redrawn naively per frame they would re-cross the JVM O(N) *every tick* — the trap. So each grows an **optional precomputed-data parameter** (`_draw_speed(..., speeds_kms=None, color=None, label=None)`, `_draw_sky_track(..., azel=None)`): the engine computes the two speed-magnitude arrays and the az/el track **once per re-propagation**, holds them, and hands them in each frame, so the draw step is pure numpy/matplotlib with no JVM. **Only the ITRF (ground-relative) speed array actually costs a `to_frame`**: the buffer is already in an inertial frame (TEME, from `propagate_tle`), and the inertial speed *magnitude* is invariant under the TEME→EME2000 rotation (a pure rotation preserves `|v|`; the two frames differ only by the ~1e-8-relative nutation-rate frame-rotation term, far below plot resolution), so the engine reads the inertial curve straight off `buffer.velocities` — `|v|` with no conversion — paying one O(N) `to_frame(ITRF)` per re-propagation instead of two. Both parameters **default to today's compute-it-yourself behaviour**, so the standalone `plot_speed` / `plot_sky_track` verbs and the 1.1 snapshot tests stay byte-stable (a build checkpoint to hold). For the two-frame speed overlay the seam does double duty: the same additive change carries the per-curve `color`/`label` and swaps `_draw_speed`'s single-frame *title* for the caller's *legend* — so the speed-panel tweak is **not** merely "colour/label", it is "precomputed array + colour/label + title→legend". (And because a supplied `speeds_kms` array makes `_draw_speed`'s `frame` argument drive neither the conversion nor the title, `frame` becomes optional — `frame=None` — rather than a required-but-dead parameter the caller must still pass.)

Per frame, then, only the **now-indicators** are recomputed, all O(1): the two time-series cursors are a bare `axvline` at the current elapsed-time **scalar** (no value, no JVM); `buffer.at(now)` (the cached-`Ephemeris` Hermite eval, built once per buffer) yields the current `State`, from which `itrf_now = state_now.to_frame(ITRF)` is computed **once** and reused for the sub-satellite marker *and* its title (`to_geodetic(itrf_now)` → lat/lon/alt) — note **no** inertial conversion is needed per frame, since the speed cursor is positional, not a numeric readout; and the sky marker plus the Sun/Moon tint and markers come from a **single combined core primitive**, `observer_snapshot(station, now, state_now)` (`core/observation.py`), that builds the station `TopocentricFrame` **once** and projects the satellite, Sun, and Moon together — three `AzElRange`s from one frame build. (Calling `look_angles` / `sun_look_angles` / `moon_look_angles` separately would rebuild that *identical* station frame three times per frame; batching them is the same reasoning that gave `look_angles_track` its existence, and keeping the builder in `core/` preserves the "no Orekit code in `live.py`" rule. The one remaining per-frame Orekit touch, `state_now.to_frame(ITRF)` above, is left in place — a negligible 1 Hz cost.) So a tick never re-runs an O(N) JVM loop. This is what lets `update()` finish within `refresh_s` and keeps the real-time feel (and because `now` is read from the wall clock each frame, even a slow tick stays *time-correct*, just less smooth). The **artist-data-update half of the named later optimization shipped** in the v0.5.0 mutate-in-place upgrade — the scene is built once and thereafter only mutated, cheap *because* it re-uses the cached arrays via the seam above; **blitting** proper stays deferred (it would remove the residual per-frame matplotlib cost — chiefly the basemap coastline re-render — by restoring a cached background instead of re-rasterizing).

**Dashboard panel specifics.** The live panels add display touches over the bare 1.1 primitives — all of them owned by `tracking/live.py`, so the reusable `plotting/` verbs are untouched. Because the underlying buffer path/curve is **static between re-propagations**, every panel carries a live **now-indicator** — the one thing that moves frame to frame — so all three or four panels read as live, not just the ground track: a sliding current-position marker on the two spatial panels (ground track, sky) and a moving vertical *now*-cursor on the two time-series panels (altitude, speed). In each panel below, that indicator is the live element; the rest of the panel is redrawn from the static buffer. The additive changes the panels need to the shipped 1.1 `_draw_*` primitives (the ground-track end-triangle relabel/suppress, the two-frame speed overlay) all **default to the current behaviour**, so 1.1's `plot_*` snapshot tests (architecture §11) stay byte-stable — a build checkpoint to hold.

- **Ground track.** Draws the whole symmetric buffer via `_draw_ground_track` (which already handles dateline wrap and the blue→red elapsed-time gradient, so the trailing→leading path is colour-coded past→future for free). The live **current-position marker** — this panel's now-indicator — is drawn at `buffer.at(now)`'s sub-satellite point and **carries the heading/direction glyph** (the satellite's actual direction of travel, per the ECEF-nadir & direction-markers addendum). This needs a small additive change to `_draw_ground_track`, which today unconditionally stamps a heading-oriented red *end* triangle at the **last** sample plus a `start`/`end` legend: in a centred buffer that "end" is the *future* leading edge, **not** where the satellite is, so the direction glyph belongs on the live marker instead. The dashboard therefore (a) owns the direction glyph on the current marker — its heading taken from the segment of the **cached buffer lat/lon arrays that brackets `now`**, *not* the end-of-track value `_track_heading_deg` returns today (`plotting/trajectories.py`); that helper grows an optional segment selector (`_track_heading_deg(lon, lat, *, at_index=None)`, default `None` → last valid segment, unchanged), so the live marker reuses the exact dateline/degenerate-fallback convention with no extra JVM work — and (b) relabels the buffer endpoints **past edge / future edge** (or suppresses the end triangle) through a new optional `_draw_ground_track` parameter — the standalone `plot_ground_track` keeps its current start/end behaviour unchanged. The panel **title carries the live sub-satellite coordinates**, e.g. `Ground track — 12.34°N, 56.78°W · alt 412 km` (the lat/lon/alt are already in hand from placing the marker — one geodetic conversion, TEME→ITRF→geodetic — so the live title is effectively free), a **UTC clock** (panel title or figure suptitle) — see *Clock & time-zone seam* below, and live **speeds** (both ground and inertial).
- **Altitude.** `_draw_altitude` unchanged, with a moving vertical *now*-cursor (an `axvline` at the current elapsed-time) over the otherwise-static altitude curve — this panel's now-indicator.
- **Speed.** Both **inertial (EME2000)** and **ground-relative (ITRF)** speed are drawn on the **same axis with a legend** — the gap between them *is* the Earth-rotation contribution, the most instructive thing a speed panel can show a learner. Their units match (km/s) so they co-plot cleanly. This drops the earlier single-`speed_frame` knob; it needs an additive change to `_draw_speed` — a **precomputed `speeds_kms=` array** (so the per-frame redraw never re-runs `to_frame` — and since the inertial curve is read directly off the already-inertial TEME buffer, only the ITRF curve costs a conversion; see *Per-frame work*) plus a `color`/`label` parameter and a legend in place of the single-frame title — so two frames share one axis cheaply. All three parts default to the current behaviour, so `plot_speed` stays byte-stable. Like altitude, it carries the moving *now*-cursor.
- **Sky view.** The shared geometry-only `_draw_sky_track` — handed the engine's **precomputed az/el track** (`azel=`, computed once per re-propagation via `look_angles_track`, not recomputed per frame; see *Per-frame work*) — plus a sliding **current-satellite glyph** at the live (az, el) — the sky panel's now-indicator — plus dashboard-only ambiance (sun-tinted background, Sun & Moon markers, a halo-stroked track), detailed under *Sky view* below.

**Backend-agnostic rendering.** The same `FuncAnimation` renders in either context — *where* it draws is decided by the active matplotlib backend, not by the code:

- **Desktop window** under a GUI backend (`%matplotlib qt` / `tk`, or run as a script) — a pop-out live dashboard window.
- **In-notebook** under `%matplotlib widget` (ipympl) — a live interactive canvas embedded in the output cell (fits the Phase-1 "Learners / notebooks" audience, architecture §2).
- **Caveat (documented):** the notebook *default* backend (`%matplotlib inline`) does **not** animate — it draws a static snapshot. Live animation requires `%matplotlib widget` or a GUI backend.

**Display only, not saved.** A live `FuncAnimation` off the buffer is ephemeral by design — v1 never calls `anim.save()`, so there is no ffmpeg/Pillow writer dependency and no saved artifact. (Export to mp4/gif is explicitly out of scope; it could be added later.) The live view is therefore **not snapshot-tested** (architecture §11) — the buffer engine is tested headlessly; the new core topocentric primitives (`look_angles` / `look_angles_track` / `sun_look_angles` / `moon_look_angles`) are numerically unit-tested; only the animation loop — the colour-mapping and glyph drawing — is left untested.

**Clock & time-zone seam (cheap insurance).** The dashboard's UTC clock is formatted through a **single internal helper that already takes an optional time zone, defaulting to UTC** — not by formatting `Epoch.to_datetime()` inline at the call site. v1 displays **UTC only**; the seam exists purely so that a *planned future* "UTC → US time-zone conversion" upgrade drops in **additively** (expose a `tz=` parameter on `live_track`, pass it through to the seam) with **zero core changes**. The reason it is free to leave in place: a time zone is a *civil display offset* (an IANA zone + DST rule via the stdlib `zoneinfo`), a completely different axis from a `TimeScale` (UTC/TT/TAI/UT1), so it never touches the `Epoch`/leap-second/deferred-UT1 machinery — `Epoch.to_datetime()` already returns a **timezone-aware UTC `datetime`** (`core/time.py`), and `.astimezone(ZoneInfo(...))` on that result is correct local civil time, DST included. The seam's natural eventual home is an additive `tz` parameter on `Epoch.to_datetime` itself. (When that upgrade lands it adds a `tzdata` dependency, since Windows ships no system IANA database; out of scope for 1.4.)

**Signature** (buffer magnitudes finalized at the values below; still tunable, not contract — see status above):

```python
def live_track(
    target: TLE | str | int,                # a TLE (re-propagate only) or a name / NORAD id (fetched → auto-refresh)
    station: GroundStation | None = None,   # supplies the sky-view panel; omitted → 3-panel view
    *,
    output_step: float = 10.0,              # buffer sampling cadence, seconds (finalized)
    half_window_s: float = 2700.0,          # buffer half-span: covers [now − half_window_s, now + half_window_s] (finalized)
    refresh_s: float = 1.0,                 # wall-clock redraw interval, seconds (finalized)
) -> "matplotlib.animation.FuncAnimation":
```

`target` accepts a `TLE` (re-propagate only), a friendly **name**, or a **NORAD id** (`str` or bare `int`) — the `int` admitted for parity with `fetch_tle(name_or_id: str | int)`, which resolves all three; a fetched target auto-refreshes, a raw `TLE` is only re-propagated.

The three time parameters are three distinct clocks: `output_step` and `half_window_s` are **simulation-time** (sample spacing inside the buffer, and the buffer's per-side span), while `refresh_s` is **wall-clock** (the `FuncAnimation` redraw cadence) — and because the view is real-time (no time-acceleration), one wall-clock second advances `now` by one simulation second. `speed_frame` is **gone** (both frames are now drawn); a time-acceleration multiplier is **not** offered (a live dashboard is real-time by definition).

### Sky view

The geometry-only sky view is first built in 1.4 — the live dashboard needs a live sky panel — and is **reused verbatim by Feature 1.5**, so it pulls 1.5's topocentric foundation forward. The reusable pieces (`look_angles`, `_draw_sky_track`, `plot_sky_track`) stay **geometry-only**; the dashboard's richer sky panel adds its ambiance on top in `tracking/live.py` without touching them (see *Dashboard sky panel* below).

**The look-angle primitive** (`core/observation.py`):

```python
@dataclass(frozen=True)
class AzElRange:
    azimuth_deg: float       # 0 = North, increasing clockwise toward East
    elevation_deg: float     # 0 = horizon, +90 = zenith (negative = below horizon)
    range_m: float           # straight-line station → satellite distance


def look_angles(station: GroundStation, state: State) -> AzElRange: ...


def look_angles_track(  # batched analogue of geodetic_track; one TopocentricFrame
    station: GroundStation, trajectory: Trajectory
) -> tuple[np.ndarray, np.ndarray, np.ndarray]: ...  # azimuth_deg, elevation_deg, range_m


def sun_look_angles(station: GroundStation, epoch: Epoch) -> AzElRange: ...   # Sun az/el at station
def moon_look_angles(station: GroundStation, epoch: Epoch) -> AzElRange: ...  # Moon az/el at station


def observer_snapshot(  # one station TopocentricFrame, projected to all three bodies
    station: GroundStation, epoch: Epoch, state: State
) -> tuple[AzElRange, AzElRange, AzElRange]: ...  # (satellite, sun, moon) az/el/range
```

`look_angles` is the exact analogue of `to_geodetic` (architecture §6): `AzElRange` carries **no `Frame`**, so by the explicit-frame rule (architecture §10) it may convert its input internally — callers need not pre-convert TEME states. Internally it builds an Orekit `TopocentricFrame` on the canonical WGS84 ellipsoid (`core/bodies.py`) at the station's geodetic point, so it **touches the JVM** (lazy-imports jpype in the body; *not* safe-before-init). It lives in `core/observation.py` beside `GroundStation` / `AzElRange`, reachable from both `plotting/` (the sky track) and `tracking/` (1.5's `find_passes`) without crossing the inward dependency rule (architecture §7).

**Batched path (from the 1.3/1.4 pre-build notes).** A `TopocentricFrame` depends only on the `station`, not the sample, so calling per-state `look_angles` across a dense trajectory rebuilds it and re-crosses the JPype boundary N times. `look_angles_track(station, trajectory)` builds the station frame **once** and returns parallel `float64` az/el/range arrays — the analogue of `geodetic_track` (`core/frames.py`) — but, being **station-keyed**, it is **not** memoized on the `Trajectory` the way `geodetic_track` memoizes its `(ITRF trajectory, lat/lon/alt)`; the dashboard engine holds the returned arrays itself for the buffer's lifetime. `_draw_sky_track`, the live sky panel (redrawn every frame), and 1.5's dense-trajectory walks all consume the **batched** form; per-state `look_angles` stays the ergonomic single-shot primitive. Both are JVM-touching and added to the architecture §10 JVM-startup list (the value type `AzElRange` stays safe-before-init).

**Body sky-positions (Sun/Moon) — same kernel.** The identical topocentric kernel projects a celestial body instead of a satellite: `sun_look_angles` / `moon_look_angles` take a `station` + an `Epoch`, build the station `TopocentricFrame` **once**, and project the `core/bodies._sun()` / `_moon()` position to an `AzElRange`. They share the private station-frame builder + projection helper with `look_angles` / `look_angles_track` — **one topocentric kernel in `core/observation.py`, five public shapes** (the four above plus `observer_snapshot(station, epoch, state)`, which builds the station frame **once** and projects the satellite + Sun + Moon together for the live dashboard's per-frame redraw) — so *all* the JVM/topocentric geometry stays in `core/`. This is the cleaner home for the dashboard's sky ambiance: `tracking/live.py` becomes pure composition (read `sun_look_angles(...).elevation_deg` → a twilight colour; plot the Sun/Moon `(az, el)`), with no Orekit code in `live.py` and no reach into `core/bodies` internals across the dependency boundary. And it pulls Feature 1.5 forward exactly as `look_angles` does: **Sun elevation at the observer *is* 1.5's "observer in darkness" gate**, so 1.5 reuses `sun_look_angles` verbatim. Because these are numerically checkable, they are **unit-tested** (Sun/Moon az-el at a known station + epoch vs. an almanac), which shrinks the untested live-only surface to just the colour-mapping and glyph drawing.

**The plot verb + primitive** (`plotting/trajectories.py`):

```python
def plot_sky_track(
    trajectory: Trajectory,
    station: GroundStation,
    *,
    min_elevation_deg: float = 0.0,   # horizon clip; samples below are lifted from the line
) -> "matplotlib.figure.Figure": ...
```

A thin wrapper over a `_draw_sky_track(ax, trajectory, station, ...)` primitive (the 1.1 pattern), so the live dashboard's sky panel and the standalone verb share one drawing path. It maps the trajectory through `look_angles_track` (one station `TopocentricFrame`, not one rebuilt per sample) and draws on a **matplotlib polar projection** (architecture §10): North at top, azimuth clockwise (`set_theta_zero_location('N')`, `set_theta_direction(-1)`); radius is the zenith angle, so **zenith at the centre, horizon at the rim** (elevation 90°→0° → radius 0°→90°). The sky disk is a fixed light blue; the track is a single dark-blue line (not the blue→red time gradient — an observer reads a sky track as one continuous path). Returns the native matplotlib `Figure`.

**Geometry only — the 1.4 ↔ 1.5 line.** `plot_sky_track` draws *only the geometry*: no discrete passes, no eclipse/lit shading, no brightness. Those belong to 1.5's richer `plot_sky_chart` (`plotting/passes.py`), which consumes `Pass` objects and layers them on the **same** `look_angles` primitive. 1.4 ships the reusable primitive plus a thin geometry plot; 1.5 adds passes and brightness on top.

**Two build-time points** (neither signature-level):

- **Disjoint arcs.** Over a multi-hour span the satellite rises and sets several times. Drawn as one polyline, matplotlib would join each set to the next rise with a chord across the disk. Mask samples below `min_elevation_deg` to `NaN` (lift the pen) so each visible arc draws on its own.
- **Never-visible span.** If no sample clears `min_elevation_deg`, draw the empty sky disk and emit a one-time `warnings.warn` rather than returning a blank figure silently. (In the **live dashboard** this warning is suppressed — a transient blank sky is the normal state there; see *Dashboard sky panel*.)

**Dashboard sky panel (ambiance, live-only).** The live dashboard's sky panel layers extra context **on top of** the geometry-only `_draw_sky_track`. The *drawing* is owned by `tracking/live.py` (so the shared primitive and the standalone `plot_sky_track` verb keep their fixed-disk / single-line contract, reusable verbatim by 1.5), but every JVM/topocentric quantity it needs comes from the **core** `sun_look_angles` / `moon_look_angles` primitives above — `live.py` itself stays pure composition (no Orekit code). Three additions:

- **Sun-tinted background.** The disk background colour tracks the **Sun's elevation at the observer** — `sun_look_angles(station, now).elevation_deg`, one cheap scalar per frame: day → light blue, civil/nautical/astronomical twilight → a dusk gradient, night → navy. This is *ambient context*, not pass-visibility shading — the satellite-track illumination/eclipse colouring stays a Feature 1.5 concern (the 1.4 ↔ 1.5 line above).
- **Sun & Moon markers.** Plotted as glyphs at the `(az, el)` returned by `sun_look_angles` / `moon_look_angles` (radial position = zenith angle = 90° − el), same path as the tint. (Planet markers would need `CelestialBodyFactory` + the bundled DE ephemeris and are **deferred**; bright-star markers are **out of scope** — no catalog.)
- **Contrasting track (halo).** Because the background now sweeps light-blue → navy, a fixed dark-blue track would vanish at night, so the dashboard draws the track with a **halo / stroke path-effect** (`matplotlib.patheffects.withStroke`) that reads on any background — no background-colour-matching logic. `_draw_sky_track` exposes a small optional track-styling seam (default = the contract dark-blue line) that the dashboard overrides; the standalone verb's output is unchanged.
- **No never-visible warning.** `plot_sky_track`'s one-time *never-visible* `warnings.warn` (above) was tailored to a **static** multi-hour sky view; in the live dashboard the satellite is below the station horizon most of the time, so a transient empty sky disk is the normal, expected state — not a condition to warn about (and under the original clear-and-redraw rendering, a per-frame warn would have spammed). The dashboard therefore **suppresses** that warning through the same `_draw_sky_track` styling/behaviour seam; the blank disk stands on its own. The standalone `plot_sky_track` verb keeps the warn-once unchanged (a static view genuinely wants it).

### Module placement & dependency rule

- `tracking/realtime.py` — `current_state`, `current_ground_position` (the cheap primitives), calling the single-shot `_tle_state_at` helper in `tle/propagator.py` (`tracking/` → `tle/` is within the dependency rule).
- `tracking/live.py` — the symmetric-buffer engine + the `FuncAnimation` driver, and the owner of all dashboard-only display touches (live ground-track title, two-frame speed overlay, sky-panel ambiance, the UTC clock seam). It **lazily imports `plotting/` *and* `matplotlib` (including `matplotlib.animation`) inside the function body** (the `io/exports.py::export_all` precedent, architecture §7), so `tracking/`'s static module graph stays clean and the headless suites never pull `plotting/` / matplotlib *through `tracking/`* (the package as a whole still loads matplotlib at import via the top-level `plot_*` re-exports — a separate, deliberate choice); the one `tracking → plotting` edge exists only at call time, when the user has asked for a live view. **`live_track` is re-exported at the top level** alongside `current_state` / `current_ground_position` (architecture §7's `__init__` list) — parity with every other headline verb (`propagate_numerical` / `propagate_tle` / `fetch_tle`), at **zero invariant cost**: the re-export binds the function object, and because `live_track`'s matplotlib / `plotting` imports are in-body, the re-export starts no JVM and adds **no new matplotlib import** — so `import propygator` stays **JVM-free**. (Note it is *not* matplotlib-free: matplotlib is already loaded at import by the top-level `plot_*` verbs — a deliberate public-namespace choice, architecture §7/§10 — so the `live_track` re-export merely behaves exactly as those already-top-level `plot_*` verbs do, widening the import surface by nothing.)
- `core/observation.py` — `look_angles` / `look_angles_track` (batched) / `sun_look_angles` / `moon_look_angles` / `observer_snapshot` (the live per-frame sat+Sun+Moon batch, one station-frame build) / `AzElRange`; one shared topocentric kernel, all reused by 1.5 (`sun_look_angles` is 1.5's observer-darkness gate).
- `core/bodies.py` — the internal Sun/Moon accessors that `sun_look_angles` / `moon_look_angles` project (already built for SRP / third-body / geodetic); reached only from within `core/`, never from `tracking/`.
- `core/time.py` — `Epoch.to_datetime()`, the tz-ready clock seam (UTC for 1.4; additive `tz=` later).
- `plotting/trajectories.py` — `plot_sky_track` + `_draw_sky_track` (geometry-only; the dashboard restyles the track via the primitive's optional styling seam).

### Resolved decisions for 1.4

- **Scope** — cheap real-time primitives **plus** a live buffered dashboard (the richest tracking feature), not just "where is it now."
- **Live rendering** — one backend-agnostic `matplotlib` `FuncAnimation` over a rolling `Trajectory` buffer; desktop window or in-notebook (`%matplotlib widget`); **display only, not saved**; returns the native animation object. **No time-acceleration** — a live dashboard is real-time by definition (wall-clock = sim-time). Per-frame work is **O(1)** (static per-buffer data cached at re-propagation **and handed to the `_draw_*` primitives via an optional precomputed-array seam**, so the per-frame redraw never re-crosses the JVM; only the now-indicators recompute), so the redraw stays within `refresh_s`; the display layer **builds the scene once and mutates artists in place at `blit=False`** (the v0.5.0 mutate-in-place upgrade — pinned limits, never `ax.clear()`, so zoom/pan survives every redraw and rebuild), with **blitting itself still deferred** (declined at that upgrade's Checkpoint-A gate).
- **Symmetric buffer** — the buffer is **centred on `now`**, `[now − half_window_s, now + half_window_s]`, so the ground track shows a trailing (flown) and leading (predicted) path with the live marker between them; static between re-propagations. Sample `buffer.at(now)` per frame (Hermite lookup); refresh by re-propagation as the buffer drains; **auto-refresh the TLE when the target was fetched** (realtime cache TTL), re-propagate only when a raw `TLE` is supplied. Re-propagation is **drain-triggered** (not on the redraw tick), and the re-fetch rides on it — the fetch cache holds it to ≤1 CelesTrak round-trip per cache window: 1.4 wired the `fetch_tle` plumbing (the keyword-only `ttl_s` selector) so the live/realtime path reaches the realtime **6 h** TTL (`_TTL_REALTIME_S`), collapsing auto-refresh to ≤1 round-trip per ~6 h (see *Live dashboard* and architecture §10). The *magnitudes* (`half_window_s` / `output_step` / `refresh_s`) were finalized during the build at 2700 s / 10 s / 1 s (still tunable).
- **Panels (3 or 4, adaptive)** — ground track / altitude / speed always; **sky view only when a `station` is supplied** (omitted otherwise — more flexible than a required station). Reuses the 1.1 `_draw_*` primitives + the new `_draw_sky_track`. **Every panel carries a live now-indicator** (sliding marker on ground-track/sky, vertical *now*-cursor on altitude/speed) — the element that moves between re-propagations, so no panel looks frozen.
- **Ground-track panel** — live sub-satellite **lat/lon (+ alt) in the title**, a distinct current-position marker, a **UTC clock** (formatted through a tz-ready seam — UTC now, additive `tz=` later, no core changes), and **speeds**.
- **Speed panel** — **both** inertial (EME2000) and ground-relative (ITRF) speeds overlaid with a legend (the gap is the Earth-rotation story); drops the `speed_frame` knob; needs an additive `_draw_speed` change — precomputed `speeds_kms=` array + `color`/`label` + title→legend, all defaulting to current behaviour. The inertial magnitude is read straight off the already-inertial TEME buffer (rotation-invariant), so only the ITRF curve needs a `to_frame`; and `frame` becomes optional once `speeds_kms` is supplied.
- **Sky view (built here, reused verbatim by 1.5)** — `look_angles` (+ the batched `look_angles_track`, + `sun_look_angles` / `moon_look_angles`, + the per-frame `observer_snapshot` that projects satellite + Sun + Moon from one station-frame build) + `AzElRange` (`core/observation.py`, one shared topocentric kernel) and `plot_sky_track` / `_draw_sky_track` (`plotting/trajectories.py`); the shared pieces stay **geometry-only**, and the sky drawers consume the batched `look_angles_track` (one `TopocentricFrame`, not one per sample). The **dashboard sky panel** adds, live-only in `tracking/live.py`: a **sun-tinted background** and **Sun & Moon markers** — both computed by the core `sun_look_angles` / `moon_look_angles` primitives (all JVM geometry stays in `core/`; `live.py` is pure composition) — plus a **halo-stroked track** for contrast against the day→night sweep. `sun_look_angles` doubles as 1.5's observer-darkness gate, so the forward-pull extends beyond `look_angles`.
- **Dependency rule** — `tracking/live.py` lazily imports `plotting/` *and* matplotlib in-body (the `export_all` precedent); the buffer/refresh engine is headless-testable; the animation loop is not snapshot-tested. **`live_track` is re-exported at the top level** (zero invariant cost — the in-body imports keep the re-export JVM-free and add no new matplotlib import; `import propygator` stays JVM-free, though it already loads matplotlib at import via the top-level `plot_*` verbs, by design — architecture §7/§10).

### Still open / deferred for 1.4

- **Buffer magnitudes** — finalized at `half_window_s=2700 s` / `output_step=10 s` / `refresh_s=1 s` (dialled in against look/feel + measured compute during the build); whether to surface the buffer re-propagation trigger as a separate knob stays deferred.
- **Halo vs. colour** for the sky-track contrast — settle the exact path-effect when it can be seen.
- **Planet markers** in the sky panel (`CelestialBodyFactory` + DE ephemeris) — deferred; **bright-star markers** — out of scope (no catalog).
- **Time-zone exposure** — a `tz=` parameter on `live_track` (and the eventual general UTC → US-zone tools) — deferred to a future upgrade; the clock seam is built tz-ready so it lands additively with no core changes (adds a `tzdata` dependency then).
- **A time-acceleration multiplier** (fast-forward / scrub) — closed: not offered (real-time only).
- **Saving the animation** to mp4/gif — out of scope for v1 (display only).
- **Performance** — v1 already derives the static per-buffer data once (so per-frame work is O(1)), and the **artist-data-update half** landed in the v0.5.0 mutate-in-place upgrade (build-once / mutate-in-place, no `ax.clear()`); **blitting** remains a later optimization (removing the residual matplotlib redraw, chiefly the basemap), as does running the buffer rebuild **off-thread** so a re-propagation / cache-miss re-fetch never stalls the draw.

## 1.5 Ground passes + brightness

> **Status: NOT STARTED (design sketch).** The `find_passes` signature, the `Pass` type, and the data-flow live in architecture §6/§7/§8; the blurb below is a placeholder to be expanded into a full sub-design when 1.5 is scheduled. 1.5 reuses the `look_angles` primitive built in 1.4.

The synthesis feature: given a TLE, a `GroundStation`, and a time window, find future **visible passes** — when the satellite is above the horizon, sunlit, and the observer is in darkness — with an estimated **visual magnitude**. It combines tracking, lighting geometry, and eclipse logic.

```python
def find_passes(tle, station, start, duration, min_elevation_deg) -> list[Pass]: ...
```

A `Pass` carries `rise` / `culmination` / `set` epochs, `max_elevation_deg`, `peak_magnitude` (None if not computed), and `sunlit_at_culmination` (architecture §6). The internal pipeline (architecture §8): propagate the TLE → find horizon crossings → check elevation → check lighting (satellite lit, observer dark, not in Earth's shadow) → compute magnitude.

**Outputs — two forms, cheap and rich.**

- **Pass table (cheap).** A tabular view of `list[Pass]` for quick reading — a `passes_to_dataframe(passes) -> pd.DataFrame` (pandas already a dep, mirroring `Trajectory.to_dataframe`) and/or a formatted-text table. Plus the already-anticipated `io/exports` **Pass list → ICS/CSV** export (architecture §7). Cheap formatting of an existing core type — no new dependency.
- **Sky charts (rich).** `plot_sky_chart` (`plotting/passes.py`, matplotlib polar) layers `Pass` objects — rise/culmination/set, brightness, lit/eclipse shading — onto the **same** `look_angles` primitive built in 1.4, plus `plot_pass_timeline`.

**Brightness.** Visual magnitude uses the citation-backed standard-magnitude table in `core/catalogs.py` (intrinsic brightness at 1000 km, 50% phase angle), corrected for range and phase angle in `tracking/visibility.py` (`compute_magnitude`). Satellites outside the registry need a user-supplied magnitude, or passes are returned without a magnitude estimate (architecture §3).

**To flesh out when scheduled:** the horizon-crossing / culmination search algorithm, the eclipse + lighting model, the magnitude/phase-angle math and its references, and the exact sky-chart / timeline layouts.
