# General Upgrades 1

This document provides specific details regarding a set of general upgrades to propygator. It temporarily supercedes architecture.md and features.md, but minimally and only in specifically noted spots. It will function as a source of truth for propygator v0.5.0 build.

## Tier B Drag

> Adds **`BoxFaceCd`** — a per-face, incidence-resolved drag-coefficient table for a
> **convex box** — the realized form of the Tier B box-drag extension that `features.md`
> §1.1 sketched as the deferred `IncidenceVariableCd`. This section is the **binding
> contract** for the v0.5.0 `BoxFaceCd` surface: signature, table semantics, runtime,
> validation, metadata, and the evidence pipeline. It supersedes only the enumerated
> `features.md` §1.1 / `architecture.md` §13 spots below; everything else there stands.

### Supercessions

- **`features.md` §1.1, `box_and_panels` signature** — `drag_coefficient: float | VariableCd | IncidenceVariableCd` becomes `float | VariableCd | BoxFaceCd`. (`sphere` is unchanged: `float | VariableCd`.)
- **`features.md` §1.1, "Tier B — incidence-keyed box table" paragraph** — the whole-body `(radius, density, azimuth, elevation[, array])` grid is replaced by the per-face `BoxFaceCd` design in **Details**.
- **`features.md` §1.1, "API at a glance"** — the `IncidenceVariableCd.from_table(...)` example is replaced by the `BoxFaceCd` constructors below.
- **`features.md` §1.1, validation table** — the row "`sphere` given an `IncidenceVariableCd` → `ValueError`" now reads `BoxFaceCd`, and a new row rejects a `BoxFaceCd` on a paneled box (see **Details → Validation**).
- **`features.md` §1.1, failure-modes table** — the row "`box_and_panels` `IncidenceVariableCd` under drag → `NotImplementedError`" is **removed**: the path is implemented, and misuse now fails at *construction* (`ValueError`), not at propagation.
- **`features.md` §1.1, metadata grammar** — the `Cd=table:<name-or-hash>` note also covers `BoxFaceCd` (its hash includes the incidence axis, so it can't collide with a 2-D `VariableCd`).
- **`features.md` §1.1, model-limitations docstring** — the drag bullet is updated (see **Details → Docstring**).
- **`architecture.md` §13, "Coefficient of drag modeling" deferred sub-design** — the Tier B description (deferred `IncidenceVariableCd`, whole-body table, ADBSat/DSMC-generated) is replaced by `BoxFaceCd` (shipped, per-face, convex-only). The two §13 cross-mentions of "deferred Tier-B `IncidenceVariableCd`" (the module-tree comment and the exception-types note) refer to `BoxFaceCd`, no longer deferred.
- **Code** — the unreleased `IncidenceVariableCd` skeleton (`propagation/spacecraft.py`; never top-level-exported; its `__call__` only ever raised) is **renamed and redesigned** to `BoxFaceCd` and re-exported at the top level beside `VariableCd`. No deprecation cycle: no released, working path depended on it. The in-package migration touches, at minimum: the `DragCoefficient` type alias; the `_format_cd` serializer and a **new `_content_hash` kind tag** (`"cd_boxface"`, so a per-face table can never collide with a 2-D `"cd2d"` one); the `spacecraft.py` module-header docstring (today it describes the deferred skeleton); the sphere-rejection check in `_validate_sphere` and the **new** convex-box check in `_validate_box`; a **new incidence-axis range check** (`_validate_axis` enforces only 1-D / finite / strictly-ascending — not the `[0, π]` bound); the `NotImplementedError` drag-wiring branch in `numerical.py`; the top-level export; and the consuming tests, `README.md`, and `CLAUDE.md`. (Detailed sequencing is the build plan's job; this lists the surface so none is missed.)

### Context

The decision record (condensed from the analysis that produced this doc):

- **Why Tier A is not enough for a box.** Tier A (`VariableCd`) gives a box a density/altitude-varying *scalar* Cd, but Orekit still applies one coefficient uniformly across all faces. A box's true per-face Cd depends on how each face meets the flow: from the committed collapse evidence (`cd_box_results.txt`, whose per-**face**-area `mean C_D` column reads 3.60→4.64 for the cube head-on→corner-on and 3.13→0.43 for the plate face-on→80° grazing), the per-**projected**-area coefficient — the quantity Orekit's single Cd must absorb, recovered by dividing those values by the attitude's projected-area factor (cube corner-on √3 ≈ 1.73; plate 80° cos 80° ≈ 0.17) — varies ~20–25 % across attitude (cube 3.60→2.68; plate 3.13→2.49). That residual is a **coherent, attitude-correlated systematic** — not zero-mean noise — that a single scalar cannot absorb and that accumulates secularly in along-track. It is also 1–4 orders of magnitude larger than the finest perturbations the propagator already models (relativity, tides), so leaving it unmodeled is inconsistent with the project's accuracy bar. It is largest, and most relevant, for high area-to-mass flat plates — **solar / drag sails**, which `features.md` §1.1 already steers onto the box (not the Sun-tracking array).
- **Convex-only, because shadowing is the enemy.** In free-molecular flow a **convex** body never self-shadows (no overhangs → no face occludes the inflow to another), so its total drag is the exact **independent sum of per-face contributions**, each a smooth function of that face's incidence — exactly what the experiment's `cd_box.py` kernel computes, so the committed collapse evidence is already *per-face* evidence. **Panels** (a protruding, articulating solar array) make the body non-convex; the resulting sweeping array-bus shadowing produces near-discontinuities that defeat smooth interpolation and need a panel method (ADBSat) or DSMC. Tier B is therefore scoped to the convex box; the panel case stays out (use a dedicated aero tool, or a fixed Cd / `VariableCd`).
- **Per-face beats a whole-body grid on every axis.** A universal `Cd(radius, density, incidence)` table summed over the box's faces is: *exact* for any convex box (all six faces summed over the full `[0, π]` incidence range — the independent free-molecular sum, leeward back-pressure included); *universal* in geometry (the per-area coefficient is size/aspect-ratio-independent, so one shipped table serves every convex box and plate — a real default, which a geometry-specific whole-body grid could never be); *trivially interpolation-safe* (a single 1-D incidence axis on which the per-face coefficient is smooth (C∞) across `[0, π]`, so linear interpolation converges cleanly with no special node placement — dissolving the 2-D azimuth-periodicity worry); and *the design the existing evidence already backs*. The cost — redesigning the unreleased skeleton — is free.
- **Mirrors the Tier A pipeline.** Offline experiment (collapse — done; + an incidence-interpolation convergence study) → an independent, Orekit-free shipped generator → a cross-validation gate proving the two agree ≪ 1 % — the same structure as `generate_sphere_cd_table.py` + `cross_validate_models.py`.
- **Evidence gate.** Shipping is contingent on an orbit-level study showing the Tier-A → `BoxFaceCd` trajectory divergence is **material and non-absorbable** (survives best-fit constant-Cd recalibration) for a representative sail. If it is not, `BoxFaceCd` is dropped rather than shipped. The contract below specifies the feature to build; the benefit study is the go/no-go.

### Details

**Type.** `BoxFaceCd` is a frozen, pure-Python table (safe before init, like `VariableCd`), re-exported at the top level as a first-class shipped Cd option (`propygator.BoxFaceCd`). It is accepted only by `box_and_panels`; `sphere` rejects it.

**API at a glance.**

```python
# Shipped default (the headline path): the in-house free-molecular per-face table.
# One table serves every convex box and plate *geometry* — the coefficient is
# per-unit-area and geometry-independent — under the shipped gas-surface assumptions
# (SESAM accommodation anchored at alpha=0.90 / 400 km solar-max, diffuse re-emission,
# wall temperature 300 K), exactly as the Tier A sphere default. A spacecraft with a
# markedly different surface material or temperature should supply its own table via
# from_table / from_callable. Asset: data/box_face_cd_default.npz.
BoxFaceCd.default() -> BoxFaceCd

# User-supplied per-face table.
BoxFaceCd.from_table(
    grid,                       # shape (n_radius, n_density, n_incidence)
    *,
    radius_axis,                # geocentric radius [m], ascending
    density_axis,               # total mass density [kg/m^3], ascending
    incidence_axis,             # face-flow angle [rad] in [0, pi], ascending
    name=None,
) -> BoxFaceCd

# User callable: fn(radius_m, density_kgm3, theta_rad) -> Cd (ref full face area;
# theta in [0, pi]).
BoxFaceCd.from_callable(fn, *, name=None) -> BoxFaceCd
```

**Table semantics.** The value `Cd(radius, density, θ)` is one **face's** drag coefficient, referenced to that face's **full** area, as a function of the face-flow angle θ — the angle between the face's outward normal and the incoming-flow direction, over the full `θ ∈ [0, π]` (θ = 0 head-on, π⁄2 edge-on, π fully leeward). It already includes the incidence projection: the normal-pressure part falls off as `cos θ` (→ 0 at edge-on), but the **tangential-shear part does not vanish edge-on** — it floors at ~0.07 (referenced to the full face area) at θ = π⁄2 and tapers smoothly across the windward↔leeward boundary to ~0 by θ ≈ 110°, so the table spans the leeward half too and every face is a direct lookup. The `(radius, density)` keying carries the same thermosphere-collapse Tier A validated, now at each incidence. Because the coefficient is per-unit-area and geometry-independent, a single table is universal across convex-box and plate *geometry* — under the fixed gas-surface assumptions noted on `default()` above (surface material and temperature are baked in, exactly as in the Tier A sphere default; users needing different surface physics supply their own table).

**Runtime (per-face sum).** Built inside `propagate_numerical` reusing the **same** custom `DragSensitive` *interface implementation* as Tier A — and its shared Knudsen-floor warn-once hook — so the Java-interface class is untouched. The per-face path does **not**, however, fit `_build_drag_sensitive`'s current 2-arg contract (`cd_lookup(radius, density)` → `accel(scalar)`): the six `table(radius, density, θ_i)` lookups, the `CdA` assembly, and the table-edge warn-once all move *into* the acceleration callable — which already receives the `(SpacecraftState, density, relativeVelocity)` Orekit hands it, so it has the attitude it needs. That is a small, contained closure change (a sibling proxy builder, or a branch in `_build_drag_force`), and the only genuinely new ingredient — the inertial→body rotation — is de-risked in the convention note below:

- Each substep the proxy receives the `SpacecraftState` (attitude) and Orekit's `relativeVelocity = v_atmosphere − v_spacecraft`. The incoming-flow direction the body sees is `flow_hat = −relativeVelocity / |relativeVelocity|`, rotated into the body frame via `state.getAttitude().getRotation().applyTo(...)`.
- For each of the 6 box faces (outward normals ±X/±Y/±Z; full areas `y·z`, `x·z`, `x·y`), it forms `c_i = n_i · flow_hat` and the face-flow angle `θ_i = arccos(clip(c_i, −1, +1)) ∈ [0, π]` (θ = 0 head-on, π⁄2 edge-on, π fully leeward). The `clip` is mandatory, not cosmetic: at exact head-on/leeward a finite-precision `c_i` can land just past `±1`, and an unclamped `arccos` returns NaN that silently poisons the drag acceleration — the same class of hazard `VariableCd.__call__` already guards by rejecting non-finite inputs. (The `cd_box.py` kernel sidesteps it entirely by staying in `cos θ` space; a θ-keyed table cannot.) **All six faces are evaluated** — windward and leeward alike.
- It looks up `Cd_i = table(radius, density, θ_i)` and assembles the total drag coefficient-area `CdA = Σ_i Cd_i · A_i`, where `A_i` is the **full** face area (the incidence projection — both the `cos θ` pressure falloff and the tangential-shear floor — is already in `Cd_i`; do **not** re-project). The leeward faces contribute the small free-molecular back-pressure/shear tail the closed form carries (tapering smoothly to ~0 by θ ≈ 110°), so the runtime is the exact convex free-molecular drag and matches the committed all-faces collapse evidence — no term is dropped.
- The acceleration is the **sphere-style** form with that effective `CdA`: `a = ½ (CdA / m) ρ |relativeVelocity| · relativeVelocity` (Orekit's `+½` convention; the same formula verified against `IsotropicDrag` to ~1e-21 m/s² for the sphere). No lift — the per-face value is already projected onto the ram direction and the total is applied along `relativeVelocity`, consistent with the v1 no-lift design.
- **It does not route through `BoxAndSolarArraySpacecraft.dragAcceleration`** (whose single uniform Cd on `max(0, n·flux)` projected area cannot consume a per-face incidence table). The Orekit box object is still built — but only to drive **SRP**.

**Why all faces, not windward-only.** The per-face coefficient does **not** vanish edge-on: the pressure term `∝ cos θ` does, but the tangential-shear term floors at ~0.07 (full-face-area reference) and tapers smoothly across the windward↔leeward boundary. Summing windward faces only — dropping that shear at and past θ = π⁄2 — is sub-percent for a thin high-area-to-mass plate (the headline sail, whose grazing side faces have negligible area) but **understates total drag by ~5–11 % for a near-cubic bus at an axis-aligned (face-on / nadir) attitude**, where the four grazing side faces carry real shear of comparable area; it also injects a non-physical attitude discontinuity at face-on (the dropped shear reappears the instant the body rotates off-axis). Evaluating all six faces over the full `[0, π]` incidence axis removes both at negligible cost: it is the exact convex free-molecular drag, it reproduces the committed `cd_box.py` collapse evidence (already an all-faces sum) without re-derivation, and it is *simpler* at runtime (no windward/leeward branch). The per-face Cd is smooth (C∞) in θ across `[0, π]` — **and this is precisely why the axis is θ and not `cos θ`**: the shear's `sin θ` factor is smooth in θ, but written in `cos θ` it becomes `√(1 − cos²θ)`, which has an infinite-derivative cusp at the poles (`cos θ = ±1`, i.e. head-on and fully-leeward), so a `cos θ` axis would smear those endpoints under linear interpolation. On the θ axis there are no value jumps and no slope kinks, so linear interpolation converges cleanly with no special node placement. (The implementer must therefore key and interpolate the table in θ even though the `cd_box.py` kernel evaluates natively in `cos θ`.)

**Convention (de-risked).** The inertial→body rotation is `state.getAttitude().getRotation().applyTo(flow_inertial)` — verified to machine precision (~1e-16) against Orekit's own `BoxAndSolarArraySpacecraft.dragAcceleration`: a windward projected-area reconstruction reproduces Orekit's box drag exactly, confirming the rotation sense and the face normal/area set (`applyInverseTo` is wrong by ~9 %). Per-substep cost is one rotation + six dot products + six (shared-`(radius, density)`) incidence interpolations — below the atmosphere-density query, comparable to the existing box path.

**Geometry coupling — convex box only.** `BoxFaceCd` is valid only on `box_and_panels` with **`solar_array_area_m2 == 0`** (a convex bus, no arrays), enforced at *construction* of the geometry with an actionable message — never a late propagation failure. (Verified empirically: `solar_array_area_m2 = 0` runs clean through the real drag+SRP path and is bit-identical to a vanishing array, so "no arrays" is a faithful convex-box representation.)

**Validation** (at construction — safe before init, no Orekit calls):

| Condition | Result |
|---|---|
| `sphere(...)` given a `BoxFaceCd` | `ValueError` — "a sphere has no flow incidence; use a fixed Cd or VariableCd" |
| `box_and_panels(...)` given a `BoxFaceCd` with `solar_array_area_m2 > 0` | `ValueError` — "BoxFaceCd models a convex box only and cannot represent solar-array shadowing; set solar_array_area_m2=0, or use a fixed Cd / VariableCd" |
| `from_table` grid shape ≠ `(radius, density, incidence)` axis sizes | `ValueError` |
| `from_table` an axis is non-1-D / non-ascending / non-finite, or grid non-finite | `ValueError` |
| `from_table` `incidence_axis` outside `[0, π]` | `ValueError` |
| `from_callable` returns a non-finite or negative Cd (checked at runtime) | `ValueError` |

The type annotations also encode the scope statically: `sphere`'s `drag_coefficient: float | VariableCd` excludes `BoxFaceCd`, so mypy flags the sphere misuse at edit time; the paneled-box case is the runtime check above (the array area is not visible to the type system).

**Out-of-grid & drag-regime warnings.** Same clamp-to-edge-don't-extrapolate policy and edge-aware two-tier warnings as Tier A (low radius edge → loud invalid-floor; high radius edge → soft negligible-drag; density edge → neutral data-range). The incidence axis spans the full `[0, π]`, so a real face-flow angle never falls outside it — there is no incidence clamp, wrap, or seam (θ is a bounded angle, not a periodic azimuth). The body-size Knudsen free-molecular floor (`guards.py`, from the box's max edge length) applies unchanged — a large sail's higher floor (~180–220 km) is already handled.

**Metadata.** `Cd=table:<name-or-hash>`, exactly as Tier A. `BoxFaceCd.default()` records `Cd=table:box_face_default`; a `from_table`/`from_callable` table without a name records its content hash (which includes the incidence axis, so it cannot collide with a 2-D `VariableCd`). A `from_callable` table carries the same "not byte-reproducible" gap noted for `CustomAttitude`. Example `spacecraft` string:

```
"box:x=2.0,y=1.5,z=1.0,arrays=0.0,axis=(0,1,0);m=420.0,Cd=table:box_face_default,abs=0.3,spec=0.6"
```

**Docstring** (the updated drag bullet of the `propagate_numerical` model-limitations note):

```
* The drag coefficient is a fixed value, a (geocentric radius, density)
  table value (VariableCd, sphere or box), or — for a convex box with no
  solar arrays — a per-face free-molecular incidence table (BoxFaceCd,
  Sentman/Schaaf-Chambre) that resolves how each face meets the flow.
  Solar-array shadowing (non-convex bodies), aerodynamic lift, and
  higher-fidelity gas-surface physics (multiple reflection, per-facet
  material/temperature, transitional/continuum flow) are not modeled.
```

**Evidence pipeline** (required build deliverables, mirroring Tier A):

1. **Offline experiment** (`experiments/drag-coefficient-verification/`, throwaway venv, not shipped, not in CI): (a) fixed-attitude collapse — **already committed** (`cd_box_experiment.py` / `cd_box_results.txt`), and already an **all-faces** per-face sum, so it validates the runtime basis directly (no re-derivation; the crucial Tier A sphere evidence stays untouched — add any new box logic alongside it, e.g. a separate driver, rather than editing the sphere files); (b) a **new 1-D incidence-interpolation convergence study** on the `cd_box.py` per-face kernel over the full `[0, π]` axis — Cd on a fine incidence grid as truth, subsampled to candidate coarse grids, linearly interpolated back, max/RMS error reported vs spacing. The per-face Cd is smooth (C∞) in θ across `[0, π]` (no value jumps, no slope kinks — smooth in θ on the chosen axis; see the axis-choice note above on why θ and not `cos θ`), so a uniform grid is expected to show clean ≈ 2nd-order convergence with no special node placement.
2. **Shipped generator** `scripts/generate_box_face_cd_table.py` → `data/box_face_cd_default.npz`: an **independent**, pure-numpy (**Orekit-free**, so the cross-validator can import it in the experiment venv) reconstruction of the per-face free-molecular physics, sharing the Tier A accommodation model (SESAM α anchor) for cross-table coherence.
3. **Cross-validation**: extend `cross_validate_models.py` to drive the experiment kernel and the shipped generator off one identical set of `(radius, density, incidence)` rows. Assert agreement on the **force-relevant quantity — the assembled `CdA = Σ_i Cd_i · A_i`** for a representative box swept over attitude × radius × density (an O(1 m²) total that is never near zero), with `max rel diff ≪ 1 %` — mirroring how the Tier A check asserts on *total* sphere Cd, not per-species terms. Keep a **secondary** max-*absolute* per-face check (`|Cd_gen − Cd_exp| < ε_abs`, with ε_abs set well under the smallest force-relevant Cd) to catch local divergence: a bare *relative* per-face gate is ill-posed near grazing/leeward, where `Cd_i → ~0.07 → 0` (a tiny denominator carrying negligible force). The generator must reconstruct the **full** per-face physics — normal pressure **and** tangential shear — or it cannot match the kernel at large θ. This is the §5-equivalence invariant: a validity limit transfers to the shipped table only because the two independent reconstructions agree.
4. **Benefit / go-no-go study** (hybrid — generate the table in the experiment venv, propagate in the conda env): Tier A (best-fit constant Cd) vs `BoxFaceCd` for a representative Sun-pointing LEO sail over a multi-day window; ship only if the along-track divergence is material and **survives constant-Cd recalibration**.
