# General Upgrades 1

This document provides specific details regarding a set of general upgrades to propygator. It temporarily supercedes architecture.md and features.md, but minimally and only in specifically noted spots. It will function as a source of truth for propygator v0.5.0 build.

> **Archived to `docs/history/` (2026-07-07), one exception to its historical status:**
> all five sections shipped/resolved as `v0.5.0` and every shipped section's
> Supercessions are folded back — but the **ERP half of "Planetary Third-Body & Earth
> Radiation Pressure" remains the binding contract** for the parked, upstream-blocked
> `earth_radiation` resume (`experiments/earth-radiation/` carries the patch + probe +
> recipe). Archived location notwithstanding, that section still wins on conflict when
> the resume happens.

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


## Live Dashboard Blitting

> Converts the live dashboard's per-frame redraw from **clear-and-redraw** to
> **in-place artist updates, then blitting on top** — the "later optimization"
> `features.md` §1.4 repeatedly names. The headline win is **interactive zoom/pan that
> survives the redraw** (today `ax.clear()` wipes it every tick, so zooming into a pass
> or an altitude feature is impossible) — delivered by the mutate-in-place rewrite; the
> secondary win, from the blit layer on top, is a cheaper, flicker-free per-frame redraw
> (the coastline basemap is rendered once and cached instead of re-rasterized every
> second). This section is the **binding contract** for the change:
> the artist split, the background-invalidation policy, the four blit-specific wrinkles,
> and the build sequence. It supersedes only the enumerated `features.md` §1.4 spots
> below; the buffer engine, panel content, and `live_track` signature are unchanged.
>
> **Outcome (Checkpoint A, 2026-07-03): shipped as the mutate-in-place layer only.**
> Build-sequence step 1 landed — build-once / mutate-in-place at `blit=False`, which is
> the entire interactivity headline (zoom/pan survives every redraw and buffer rebuild).
> The blit layer proper (steps 2–3: `blit=True`, the three-step background invalidation,
> the axes-anchored readout, the band-change re-cache) was **declined at the build
> plan's Checkpoint A go/no-go**: at `refresh_s=1 s` the flicker-free/CPU win did not
> justify the four wrinkles' full handling plus the private-`_blit_cache` matplotlib
> coupling. Blitting stays the named later optimization; the section below remains its
> design record. The Supercessions were **folded back into `features.md` §1.4 in that
> partial form** (mutate-in-place at `blit=False`; blitting still deferred — the
> "blitting shipped in v0.5.0" wording below did *not* happen), so they no longer
> override §1.4.

### Supercessions

- **`features.md` §1.4, "The view" paragraph** — "v1 uses clear-and-redraw per frame; blitting / artist-update is a later optimization" now reads: the driver builds the scene once and mutates artists in place under `FuncAnimation(blit=True)`.
- **`features.md` §1.4, "Per-frame work" paragraph** — its closing "v1 keeps the simple clear-and-redraw rendering ... blitting / artist-data updates stay the named later optimization" is realized here. The O(1)-per-frame compute seam that paragraph describes (the engine's precomputed speed/az-el arrays + memoized `geodetic_track`) is the *precondition* this upgrade builds on, unchanged — not something it revisits.
- **`features.md` §1.4, "Resolved decisions → Live rendering" bullet** — "v1 uses clear-and-redraw, blitting deferred" becomes "blitting shipped in v0.5.0".
- **`features.md` §1.4, "Still open / deferred → Performance" bullet** — the **blitting** half is realized here; the **off-thread rebuild** half stays deferred (explicitly out of scope — see *Out of scope* below).
- (No signature, panel-content, or buffer-engine change: the `_TrackerEngine` state machine and `live_track`'s §1.4 signature are untouched. The §1.4 sky-view radial-label refinement — labelling the rings in elevation — is a *separate* small upgrade, not part of this section.)

### Context

The decision record:

- **The defect is `ax.clear()`, not throughput.** `update()` calls `ax.clear()` on every axis each tick (`live.py` `ax_ground/ax_alt/ax_speed/ax_sky.clear()`) and lets the panels re-autoscale, so any zoom/pan the user sets through the matplotlib toolbar is destroyed on the next redraw (~1 Hz). At `refresh_s=1 s` the redraw is not a throughput bottleneck; the felt problem is that the dashboard is **non-interactive** — you cannot zoom into a sky-panel pass or an altitude feature without it clearing a second later.
- **Two separable wins: mutate-in-place buys interactivity; blit buys efficiency.** Dropping `ax.clear()` for **mutate-persistent-artists-in-place** is what makes zoom/pan survive — nothing clears or re-autoscales the axes, so user limits persist. That holds *independently of blitting*, even at `blit=False`. Layering `FuncAnimation(blit=True)` on top then caches the static background and, per tick, restores it and redraws only the returned *animated* artists — buying the per-tick efficiency (the basemap is rasterized once, not every second) and a flicker-free redraw. Under blit, zoom survives because FuncAnimation keys its cached background on each axes' *view* (`ax._get_view()` — the limits) and re-captures whenever the view changes; the toolbar's zoom/pan changes the view, so the next frame re-grabs the background at the zoomed limits. **There is no permanent handler that re-caches after an arbitrary full canvas draw** — the re-capture is driven solely by the view-change check, which is exactly why background invalidation (below) has to be explicit. This split — interactivity from the mutate-in-place rewrite, efficiency from the blit layer — drives the build sequence.
- **What it buys, and what it costs.** Per tick, only a handful of small artists render over a cached bitmap instead of re-rasterizing the whole figure — the coastline basemap (the expensive draw) is cached once, so per-tick CPU drops and the redraw is flicker-free. At 1 Hz the *speed* gain is modest, so the blit layer's payoff is mostly the flicker-free redraw plus headroom for a lower `refresh_s`; the headline **interactivity** win is delivered one layer down by the mutate-in-place rewrite (which is why the build sequence lands that first, at `blit=False`, then flips blit on — see *Build sequence*). The cost is engineering: the draw loop is rewritten and four blit-specific wrinkles (below) must each be handled. The buffer rebuild still pays a full redraw, but it is drain-triggered (~every `half_window_s`), not per tick.
- **Alternatives rejected.** *Capture-and-restore axis limits around `ax.clear()`* (or autoscale only on rebuild) would preserve zoom without a rewrite, but it fights autoscale, is ambiguous about "did the user zoom or did the buffer move?", still flickers, and yields no efficiency win. *Off-thread rebuild* is orthogonal (it removes the rebuild stall, not the per-tick clear) and stays deferred.

### Details

The refactor is confined to `tracking/live.py`'s display layer (`live_track` + its `update` closure); the pure `_TrackerEngine` is untouched. The move is *clear-and-redraw* → *build-once / mutate-in-place*, driven by `FuncAnimation(blit=True)` with an `init_func`.

**Artist split.** Every artist is classified **static** (drawn once per buffer, part of the cached background) or **dynamic** (mutated and returned every frame):

- *Static (per buffer):* the ground-track gradient path + coastline basemap + start marker + station marker + legend; the altitude curve; both speed curves + legend; the sky disk, grids, track line, and legend. Created **once** during the scene build (`_init_scene` in the *Driver shape* sketch), then refreshed on rebuild by a `_draw_static(buffer)` helper that **mutates those persistent artists in place** (`set_segments` / `set_data` / `set_offsets` / `set_facecolor`). **Clear-then-redraw (`ax.clear()`) is not an option** for the static refresh, for three compounding reasons: (i) `ax.cla()` re-enables autoscale and `_draw_ground_track` re-pins `xlim(-180,180)` / `ylim(-90,90)`, so a rebuild would wipe the very zoom this upgrade exists to protect; (ii) the persistent *dynamic* artists share these axes, so clearing orphans them (`a.axes` becomes `None`, and `_blit_draw`'s `copy_from_bbox(a.axes.bbox)` then raises); (iii) it re-rasterizes the expensive basemap every rebuild, defeating the cache. Mutating in place is also what makes `_draw_static` **idempotent** — FuncAnimation's `init_func` re-runs it on every window *resize* (`_on_resize → _init_draw → init_func`), so re-setting existing artists' data is a safe no-op, whereas a version that appends fresh `plot(...)` artists each call leaks a full artist set per resize. **Because the shipped `_draw_*` primitives create fresh artists per call and return only the ground-track mappable, `_draw_static` cannot re-invoke them on rebuild** (that would re-pin limits, re-draw the basemap, and duplicate artists); it must hold stable handles to the individual static artists and mutate them — see *Blast radius* for the additive primitive seams this needs.
- *Dynamic (per frame):* the live heading-marked sub-satellite marker (ground track); the two now-cursors (altitude, speed); the sky Sun/Moon/satellite glyphs; and the live readout text. Created **once** and thereafter **only mutated, never recreated** — `update()` mutates these and returns them; `init_func` creates them and returns them so blit knows the animated set. (Recreating a dynamic artist inside `update()` breaks the re-cache: a fresh artist is not yet `set_animated` when the rebuild's synchronous `draw()` runs, so it is baked into the captured background *and* redrawn on top — a ghost. See *Background invalidation*.)

The §1.4 precomputed-array seam (`engine.inertial_speed_kms` / `ground_speed_kms` / `azel`, memoized `geodetic_track`) is unchanged — it already makes the static content cheap to (re)draw on rebuild and keeps the dynamic updates JVM-free.

**Background invalidation (the central design point).** Blit assumes a *fixed* background; this dashboard has two events that change it, and getting the re-cache right is the crux of this upgrade. The trap: **FuncAnimation only re-captures the blit background when an axes' view (`ax._get_view()`) changes** — and we deliberately *fix* the axis limits (below) so a rebuild can't blow away zoom, which means the view never changes on its own. So a bare `fig.canvas.draw_idle()` after mutating the static artists does **not** refresh the cache: the next frame's `_blit_clear` restores the *stale* cached bitmap over the freshly-drawn static content and the update is silently lost (verified against matplotlib 3.10 — `draw_idle` defers past the frame's `_post_draw`, and even a synchronous draw leaves the view-keyed cache entry in place). Both background-changing events are therefore handled by one **explicit three-step** mechanism inside `update()` — mutate the static artists, force a **synchronous** full draw, then **invalidate FuncAnimation's blit cache** so `_post_draw` re-captures the new background on this same tick:

```python
_draw_static(engine.buffer)      # (or just ax_sky.set_facecolor(...) for a band change) — mutate static
fig.canvas.draw()                # SYNCHRONOUS full draw -> new static into the buffer, animated artists
                                 #   excluded; draw_idle would defer past the re-capture, so use draw()
anim._blit_cache.clear()         # drop the stale view-keyed background so _post_draw re-grabs it this tick
```

This works **only because the dynamic artists are `set_animated(True)`** — FuncAnimation sets that flag on both the `init_func` return and every `update()` return, and `fig.canvas.draw()` skips animated artists. So the synchronous draw renders the *new static content only*, `copy_from_bbox` captures a clean background, and `_blit_draw` then draws the dynamic artists back on top. The corollary is the persistent-artist rule above: the dynamic set must be created once and only mutated — recreate one inside `update()` and it ghosts.

1. **Buffer rebuild** (drain-triggered, ~every `half_window_s`). `update()` calls `engine.maybe_rebuild(now)`; when it returns `True`, run the three-step re-cache with `_draw_static(engine.buffer)`. That frame costs a full redraw (today's per-tick cost), but rebuilds are rare.
2. **Twilight band change** (sky panel). The disk tint (`ax_sky.set_facecolor`) is part of the axes *background*, so it cannot be blitted as an over-the-top artist without covering the track. It is a **discrete 5-value band** (`_twilight_facecolor`), so recompute the band each frame (a cheap scalar, off the per-frame Sun elevation the glyph snapshot already yields) and run the same three-step re-cache **only when the band changes** (a few times per day) — not every tick. Between band changes the tint is constant, so nothing is lost. (Update the *stored* band unconditionally each tick: the *Driver shape* sketch's short-circuiting `maybe_rebuild(now) or _band_changed(now)` skips the band check on a rebuild frame, so let the rebuild's own three-step re-cache stand and refresh the stored band there too — otherwise the stored band goes stale and the next tick fires one harmless extra re-cache.)

`anim._blit_cache` is a private attribute; the sanctioned alternative is to hand-roll blitting (`copy_from_bbox` / `restore_region`) so the driver owns the re-capture outright. Either way the invalidation must be *explicit* — the "`draw_idle()` re-caches automatically" mental model is wrong, and a build that relies on it will look correct for exactly one frame, then revert to the stale background. Note that `_blit_cache` (and `_step` / `_post_draw`, exercised by the test below) are matplotlib internals: this couples the driver to a matplotlib version (pinned; verified against 3.10), and the background-invalidation pixel test is the canary that catches a breaking bump.

> **De-risked (matplotlib 3.10.9, the pinned env).** A standalone reproduction of this exact structure — fixed limits, a static artist mutated on a forced rebuild, an animated artist returned each frame, `FuncAnimation(blit=True)` stepped over an `Agg` canvas — confirmed every load-bearing claim *in pixels*: (i) *without* `_blit_cache.clear()` the mutated static content is silently lost on the tick **after** the rebuild (the stale-background defect); (ii) *with* the three-step it persists on subsequent ticks; (iii) a synchronous `fig.canvas.draw()` skips `set_animated(True)` artists (no ghost baked into the captured background); (iv) `_blit_draw` re-captures **only** when `ax._get_view()` differs (source lines ~1208–1212), so with the limits pinned the invalidation must be explicit; (v) both test bootstraps (`fig.canvas.draw()` **or** `anim._init_draw()`) leave `_step()` clean — `_blit_cache` exists from construction; and (vi) wrinkle 1 renders correctly via **both** `Line2D.set_marker(MarkerStyle)` (the rotation transform is preserved on the internal `_marker`, even though `get_marker()` returns the base `"^"`) and `PathCollection.set_paths`.

**Fixed axis limits (so a rebuild doesn't blow away zoom).** Autoscaling on rebuild would reset a user's zoom. Set **stable limits once** and never autoscale: the ground track is already fixed (−180..180 / −90..90) and the sky is fixed (`rlim(0, 90)`); give altitude and speed stable y-ranges (taken from the first buffer, held across rebuilds — for near-circular LEO, the primary target, the altitude/speed envelope is effectively constant over a session). A user zoom then survives even a rebuild. (This pinned view is also *why* background invalidation above must be explicit: with the limits fixed, FuncAnimation's automatic view-change re-cache never fires.) **Caveat:** the first-buffer envelope bounds later windows only when the orbit is near-circular **and the buffer spans at least one orbit**; a highly eccentric orbit (GTO / Molniya), a session long enough to show drag decay, or a buffer shorter than one orbit (which sees only a slice of the per-orbit altitude oscillation — the demo script's `--fast` smoke mode surfaced exactly this clipping in LEO) can carry altitude/speed outside it and clip. The named remedy **shipped with the mutate-in-place layer**: on rebuild, `_draw_static` *widens* the dashboard-set altitude/speed y-limits to enclose the new buffer's envelope — never shrinking (shrinking mid-session would fight a user's zoom), and only while the panel still sits at the dashboard's own last-applied limits, so a user-zoomed/panned viewport is never touched.

**The four blit wrinkles** (each a build checkpoint):

1. **Rotated heading marker.** The live sub-satellite triangle rotates to the track heading each frame — its marker *shape* changes, not just its position, which a bare `set_offsets` cannot express. Resolve with a single persistent `Line2D` (one point) whose marker is updated via `set_marker(_heading_marker(heading))` + `set_data([lon], [lat])` (translating the `_LIVE_MARKER` scatter kwargs to the Line2D `markerfacecolor`/`markeredgecolor`/`markersize` equivalents), or an equivalent single-`PathCollection` `set_paths` that keeps the scatter styling — one artist, mutated in place, returned each frame. (A fresh scatter per frame also works but re-creates an artist needlessly.)
2. **Twilight facecolor** — handled by the band-change re-cache above (it is a background element, not an animated artist).
3. **Live readout** — today a `fig.suptitle`, a *figure-level* `Text` outside every `Axes.bbox`, which FuncAnimation's per-axes blit never redraws (blit only re-blits the `ax.bbox` of the animated artists' axes). Move the readout to an **axes-anchored `Text`** on the ground-track axes, updated each frame via `set_text(...)`. It must sit **inside** that axes' bbox (e.g. axes-fraction `y≈0.95`, `va="top"`, `transform=ax.transAxes`) — a title-style anchor *above* the axes (`y>1.0`) lands back in the margin outside `ax.bbox` and, exactly like the suptitle, would never blit. The readout is now bounded by the ground panel's width rather than the full figure, and the string is long (coords · altitude · both speeds · UTC clock), so keep it compact (left-anchored, a modest fontsize) to avoid clipping at the panel edge. (This repoints the two structural tests that read `fig._suptitle` — see *Blast radius*.)
4. **Sky glyphs** — Sun/Moon/satellite are `set_offsets`-friendly `PathCollection`s (position-only updates); keep one per body and mutate offsets. The sky *track* line is static between rebuilds (it depends on the buffer's `azel`), so it stays in the background.

**Driver shape** (sketch, not literal):

```python
dynamic = _init_scene(...)                 # build static + dynamic artists; static kept in the closure, dynamic returned for blit
def init():                                # FuncAnimation init_func
    _draw_static(engine.buffer)
    return dynamic
def update(_frame):
    now = Epoch.now()
    if engine.maybe_rebuild(now) or _band_changed(now):
        _draw_static(engine.buffer)        # idempotent: mutate static artists in place
        fig.canvas.draw()                  # SYNCHRONOUS full draw (NOT draw_idle), then...
        anim._blit_cache.clear()           # ...invalidate so _post_draw re-captures this tick
    # mutate marker / cursors / readout from the O(1) precomputed seam; the sky glyphs
    #   from the per-frame observer_snapshot (JVM-crossing but O(1): one TopocentricFrame)
    return dynamic
anim = FuncAnimation(fig, update, init_func=init, blit=True,
                     interval=int(refresh_s * 1000.0), cache_frame_data=False)
```

**Efficiency (the honest accounting).** Per tick: was a full figure re-rasterization (basemap included); becomes a background restore + a few small artist draws — materially cheaper CPU, flicker-free. At `refresh_s=1 s` the wall-clock gain is small (1 Hz was never slow); the **interactivity** headline is already banked by the mutate-in-place step, so the *blit layer specifically* is judged on the flicker-free redraw plus headroom to lower `refresh_s` later — not fps. Rebuild frames and band-change frames still cost a full redraw, but are rare. Net: a modest CPU win on top of an already-interactive dashboard. **Because step 1 delivers the entire interactivity headline on its own, the blit layer (steps 2–3) is a separable efficiency increment** — a legitimate place to stop if the flicker-free redraw and lower-`refresh_s` headroom aren't wanted, weighed against the four wrinkles and the private-`_blit_cache` coupling it adds.

**Out of scope (still deferred).** The **off-thread rebuild** (features.md §1.4 Performance bullet): a rebuild / cache-miss re-fetch is still a synchronous stall on the draw thread; blitting does not change that (the headless engine remains the seam for it). No change to buffer magnitudes or panel content.

**Blast radius.**

- `tracking/live.py` — `live_track` setup + the `update` closure rewritten; a one-time scene build holding persistent static- **and** dynamic-artist handles; a mutate-in-place (never `ax.clear()`) idempotent `_draw_static`; `fig.suptitle` → axes-anchored `Text`; the explicit three-step background re-cache (synchronous `draw()` + `anim._blit_cache.clear()`); `FuncAnimation(..., init_func=init, blit=True)`.
- **Tests** (`tests/tracking/test_live_dashboard.py`) — only the **3-panel** build test reads the live readout via `fig._suptitle` (`test_live_dashboard.py:110`); it must repoint to the new axes-anchored `Text`. The 4-panel build test asserts only legends/titles (no `_suptitle` read), so it needs no *readout* repoint — but both build tests still tick, so keep them green under the new persistent-artist set. Add:
  - a **zoom-survival** test — set axis limits, drive a non-rebuild frame under the frozen-now fixture, assert limits unchanged. Guards the mutate-in-place / no-autoscale property; passes even at `blit=False`, so it lands with build step 1.
  - an **artist-mutation** test — cursor `get_xdata` / marker offsets / readout `get_text` change across frames.
  - a **background-invalidation** test — the real regression guard for the re-cache, and the one case that **must step the actual blit loop**, not call the `update` closure directly. Today's smoke tests tick via `anim._func(0)` (`test_live_dashboard.py:88`), which runs only the `update` body and **bypasses** `_blit_clear` / `_blit_draw` — so it can assert a rebuild ran `_draw_static` + one full draw, but it *cannot* catch the stale-background defect (the blit cache is never exercised). This test drives `anim._step()` (or `_draw_next_frame(..., blit=True)`) over an `Agg` canvas across a forced rebuild **and** a band change, and asserts on `fig.canvas.buffer_rgba()` that the **new** static content / facecolor is present *after subsequent ticks* (not just the rebuild tick) — the pixel check is the only thing that proves the invalidation. It must **initialize the blit machinery first**: under `Agg` with no event loop, FuncAnimation's `_init_draw` (which flags the animated set and seeds the cache) normally fires on the first `draw_event`, so the test has to force it — an initial `fig.canvas.draw()`, or a direct `anim._init_draw()` — before stepping, or `_step` runs with no animated set / empty cache. Keep it one tight case; the animation loop is otherwise still display-only / not snapshot-tested (§1.4).
- No change to `_TrackerEngine`, the §1.4 signature, or any public `plotting/` **verb** (`plot_*`). The private `_draw_*` **primitives**, however, likely need small **additive, output-preserving seams** so the rebuild can mutate their artists in place: today only `_draw_ground_track` returns its artist (the `LineCollection` mappable), so `_draw_altitude` / `_draw_speed` / `_draw_sky_track` should mirror it and return the `Line2D`(s) they create (or `live.py` must capture those handles off the axes at build time). **The ground track needs *two* mutable static handles, not one:** besides the returned `LineCollection` (`set_segments` / `set_array` / `set_clim` on rebuild — note the kept-segment count varies as the track crosses the dateline differently, so recompute segments and colour array together via `_dateline_segments`), its **start marker** — the "past edge" scatter created *inside* `_draw_ground_track` (`trajectories.py:273`) and **not** currently returned — also moves each rebuild as the centred buffer re-centres, so `_draw_ground_track` must additionally surface that handle (or `live.py` grabs it off `ax.collections` at build, before it adds the live-marker scatter). Either way the standalone `plot_*` outputs and their snapshot tests are unchanged.

**Build sequence** (each step ends green; the repo's Goal/Edit/Verify rhythm):

1. **Mutate-in-place at `blit=False` (interactivity first), 3-panel.** Drop `ax.clear()`; build the scene once (persistent static **and** dynamic artist handles), refresh it on rebuild via a mutate-in-place, idempotent `_draw_static(buffer)`, and add an `init_func`; `update()` *mutates* the dynamic artists — the rotated heading marker (wrinkle 1) and the two now-cursors — instead of redrawing. Fix altitude/speed y-limits. Stay at `blit=False`; keep the `fig.suptitle` readout for now. *Verify:* 3-panel builds; a tick mutates (not re-creates) the dynamic artists; the zoom-survival test passes; a forced rebuild refreshes the static curves without resetting a user zoom. **Interactivity ships here**, before any blit risk.
2. **Flip on `blit=True` + explicit background invalidation, 3-panel.** Set `blit=True`; `init_func` returns the animated set; move the readout to the axes-anchored `Text` inside `ax.bbox` (wrinkle 3); add the three-step re-cache (mutate → synchronous `draw()` → `anim._blit_cache.clear()`) on buffer rebuild. *Verify:* the background-invalidation **pixel** test passes (a forced rebuild's new static content survives *subsequent* ticks, not just the rebuild tick); zoom still survives; `update()` returns the dynamic artists.
3. **4-panel sky under blit.** Sky glyphs via `set_offsets` (wrinkle 4); the twilight band-change re-cache via the same three-step (wrinkle 2); static sky track/disk/legend. *Verify:* 4-panel builds; a band change triggers exactly one re-cache and the new facecolor survives later ticks; glyph offsets update per frame.
4. **Docs + wrap-up.** Fold these Supercessions back into `features.md` §1.4 (clear-and-redraw → mutate-in-place + blit), add the CHANGELOG `[Unreleased]` entry, and update the `live_track` docstring's rendering note; squash-merge to `main` (no tag — v0.5.0 is tagged only after all general upgrades land).


## ECEF InPlaneTracking

> Adds **`velocity_reference: str = "inertial"`** to `InPlaneTracking` — the third
> general upgrade feeding v0.5.0 (branch `feature/ecef-attitudes`). `"ecef"` re-aims the
> mode's velocity alignment from the inertial velocity to the Earth-relative
> (atmosphere-relative) velocity `v_rel = v − ω⊕×r`, reusing the custom ECEF
> `TargetProvider` shipped with `NadirPointing(velocity_reference="ecef")` **unchanged**.
> The headline user is a feathered drag/solar sail flown with `BoxFaceCd`: today no
> declarative mode can zero a flat body's angle of attack to the true co-rotating flow —
> the Tier B GO-caveat regime is reachable only via `CustomAttitude`. This section is the
> **binding contract** for the change: axis construction, signature, validation, metadata,
> failure modes, and the evidence gate. It supersedes only the enumerated `features.md`
> §1.1 / `architecture.md` §13 spots below; everything else stands.
>
> **Outcome (2026-07-04): shipped in full.** Checkpoint A resolved **GO** on the Chunk-1
> stand-in study (2 kg sail: −63.3 km / 5 d, 1.12×); the Chunk-4 refresh re-measured with
> the **shipped mode** at the 0.5 kg sail mass (−273 km / 5 d, 1.12×; shipped vs stand-in
> agree to 0.02 km max along-track — evidence: `experiments/ecef-attitude-benefit/`). The
> Supercessions below are **folded back** into `features.md` §1.1 / `architecture.md` §13 /
> the `BoxFaceCd` docstring and no longer override — note the failure-modes fold-back uses
> the build-verified wording (near-zero `v_rel` completes with a meaningless attitude;
> raises only at exact zero), per **Details → Failure mode / degenerate domain**.

### Supercessions

- **`features.md` §1.1, `InPlaneTracking` dataclass** — gains `velocity_reference: str = "inertial"` (`"inertial"` | `"ecef"`, validated at construction like `NadirPointing`'s). The docstring's unconditional "Exact for all orbits, since the orbit normal is always perpendicular to velocity" is scoped to the `inertial` reference; the `ecef` reference is exact-primary (+Y on the wind) / best-effort-secondary (+Z within the out-of-plane wind angle of the orbit normal — ≤ ~3.8° in LEO, identically 0 for equatorial orbits). See **Details → Axis construction**.
- **`features.md` §1.1, native-provider mapping table** — the `InPlaneTracking` row (today "`LofOffset(TNW, fixed axis permutation)` or `AlignedAndConstrained` (+Y → `VELOCITY`, +Z → `MOMENTUM`)") becomes: `AlignedAndConstrained`, primary +Y → `PredefinedTarget.VELOCITY` (`inertial`) or the custom ECEF-velocity `TargetProvider` (`ecef`), secondary +Z → `PredefinedTarget.MOMENTUM`.
- **`features.md` §1.1, failure-modes table** — the `NadirPointing(velocity_reference='ecef')` ground-relative-stationary row now also covers `InPlaneTracking(velocity_reference='ecef')` (there the undefined direction is the *primary* target) **and is reworded to the build-verified behavior**: near-zero `v_rel` does **not** raise — the run completes with a physically meaningless attitude; `NumericalPropagationError` fires only at exactly zero `|v_rel|` (see **Details → Failure mode / degenerate domain**). LEO is the validated domain.
- **`features.md` §1.1, metadata grammar** — the `attitude` token `in_plane_tracking` becomes `in_plane_tracking:vel=inertial` | `in_plane_tracking:vel=ecef` (the `nadir_pointing:vel=…` grammar; **always emitted**, so the default's serialized form changes from the bare `in_plane_tracking`).
- **`features.md` §1.1, "When `BoxFaceCd` matters" caveat paragraph** — its Tier B-era caveat ("measured with `InPlaneTracking`, which tracks **inertial** velocity only … (Giving `InPlaneTracking` the same `ecef` option is a possible future upgrade — … *not* part of Tier B.)") is **retired: the option now ships**. The paragraph keeps the honestly-measured ~2× figure, re-framed as the `inertial`-reference figure, and cites the `ecef`-referenced result from this upgrade's benefit study. The **same caveat text in the `BoxFaceCd` docstring** (`propagation/spacecraft.py`, its "when it matters" note) is updated identically.
- **`architecture.md` §13, "Attitude family" resolved note** — extended: `InPlaneTracking` now wires both `velocity_reference` options through the same custom ECEF `TargetProvider` as `NadirPointing`, swapped into the *primary* slot.
- **Code** — the migration touches, at minimum: `propagation/attitude.py` (the field + `__post_init__` validation sharing `_VALID_VELOCITY_REFERENCES` and mirroring `NadirPointing`'s message shape; `_metadata_string`; the `_to_provider` `InPlaneTracking` branch — swap the primary target when `ecef` and rewrite its "velocity ⊥ momentum so both hold" comment; the class docstring); the consuming tests (`tests/propagation/test_attitude.py`, `test_attitude_providers.py`, `test_numerical.py` metadata assertions that read the bare `in_plane_tracking` token); and any `README.md` / `CLAUDE.md` attitude-family mentions. No `numerical.py` change (the attitude lowering is generic) and no new exports (`InPlaneTracking` is already top-level). (Detailed sequencing is the build plan's job; this lists the surface so none is missed.)

### Context

The decision record:

- **This is an attitude-fidelity fix, not a force fix.** Orekit's `DragForce` already uses the true co-rotating-atmosphere relative velocity for the *force*; only the *attitude* is misaligned when a mode tracks inertial velocity. The wind offset `angle(v, v_rel)` reaches ~3.8° at 500 km (|ω⊕×r| ≈ 500 m/s vs v ≈ 7.6 km/s) and is strongly inclination-dependent: identically 0 for equatorial prograde orbits (the wind is along-track), maximal for polar/SSO orbits, where at the equator crossings the entire wind is **out of the orbit plane**. Drag sails fly SSO — the maximum-benefit regime.
- **For a feathered sail the residual angle of attack dominates the edge area.** At 3.8° AoA the big faces present `sin 3.8° ≈ 6.6 %` of their area to the flow — for a thin sail (~1 % edge-to-face area ratio) that is ~20× the edge area, so the misalignment, not the edge, sets the feathered drag. Whether *net* drag drops when feathering to the true wind is a genuine ram-vs-shear trade (the grazing shear floor ~0.07 full-face-referenced is the same order as the 3.8° projected ram term) — precisely the question `BoxFaceCd` exists to answer, and why the benefit study is front-loaded (see **Evidence gate**).
- **The ECEF target must take the *primary* slot** — the inverse of `NadirPointing`'s swap (which kept nadir primary and swapped the *secondary*). If momentum stayed primary, the sail plane would stay exactly in the orbit plane and the big-face AoA would equal the full out-of-plane wind angle — the same worst case as the `inertial` reference, i.e. zero benefit. Holding +Y exactly on `v_rel` zeroes the big-face AoA identically; the +Z axis then carries the (physically unavoidable) best-effort residual instead.
- **Why only `InPlaneTracking`.** The family assessment: `LofAligned`-ecef is physically redundant (this mode up to a fixed body-axis permutation — X↔Y roles, same Z); `LofOffset`-ecef (controlled incidence to the true flow) is the named follow-on, deferred (see **Out of scope**); `SunPointing`'s phasing reference is a best-effort roll about the Sun line where ≤ ~4° is second-order on projected areas; `Inertial` has no velocity concept; `NadirPointing` already shipped; `CustomAttitude` is already the escape hatch.
- **Evidence gate.** Shipping is contingent on the front-loaded feathered-sail study (below) showing the `inertial` → `ecef` difference is material for the headline sail. If it is negligible even there, the parameter is dropped rather than shipped (the Tier B bar: a coherent, attitude-correlated effect, not noise).

### Details

**API at a glance.**

```python
@dataclass(frozen=True)
class InPlaneTracking:
    """Body +Z on the orbit normal; body +Y on the velocity vector.

    velocity_reference selects the velocity: "inertial" (ECI velocity; exact
    for all orbits, since the orbit normal is always perpendicular to the
    inertial velocity) | "ecef" (Earth-relative velocity v − ω⊕×r, the
    atmosphere-relative flow — feathers a flat body to the true wind; +Y is
    held exactly on the wind, +Z is best-effort on the orbit normal, off by
    at most the out-of-plane wind angle, ≤ ~4° in LEO)."""
    velocity_reference: str = "inertial"   # "inertial" (ECI) | "ecef"
```

**Axis construction (`ecef`).** At each attitude evaluation, in the propagation frame (EME2000), with `v̂_rel = unit(v − ω⊕×r)` (read exactly off the EME2000→ITRF transform by the shipped `TargetProvider` — not a hardcoded ω⊕, so the ~0.3° pole offset is captured for free) and `ĥ = unit(r×v)` (the inertial orbit normal — `PredefinedTarget.MOMENTUM`, unchanged; the orbit normal has no meaningful "ECEF variant"):

1. **+Y ↦ v̂_rel, exact** (primary). The +Y face is the ram face — the flow arrives along `−v̂_rel` onto it — the same ram-face convention as the `inertial` reference.
2. **+Z ↦ unit(ĥ − (ĥ·v̂_rel) v̂_rel), best-effort** (secondary). With +Y pinned, the only remaining freedom is roll about the wind axis; `AlignedAndConstrained` places +Z at the direction closest to `ĥ` in the plane ⊥ `v̂_rel` — the orbit normal with its along-wind component removed.
3. **+X = Y × Z** completes the right-handed triad; for near-circular orbits it sits ≈ on the outward radial (zenith), as in the `inertial` reference.

The ±Z faces (a sail's big faces) therefore contain the wind exactly in their plane — **zero angle of attack, by construction**. The secondary residual is exact and small: `angle(+Z, ĥ) = asin(|ĥ·v̂_rel|) = asin(|ĥ·(ω⊕×r)| / |v_rel|)` — the out-of-plane angle of the co-rotation wind (`ĥ·v = 0` identically, so only the wind term survives). It is 0 for equatorial orbits and oscillates 0 → ~3.8° → 0 per half-orbit on a polar/SSO orbit (max at the equator crossings, zero over the poles). Relative to the `inertial` attitude, the whole frame is re-aimed by `angle(v, v_rel)` ≤ ~3.8°: the wind's in-plane component pitches +Y within the orbit plane (+Z unmoved); its out-of-plane component tilts +Y out of the plane and drags +Z off `ĥ` by the same angle.

**Provider lowering.** The `_to_provider` `InPlaneTracking` branch keeps its `AlignedAndConstrained(Vector3D(0,1,0), <primary>, Vector3D(0,0,1), PredefinedTarget.MOMENTUM, sun, earth)` shape; `<primary>` is `PredefinedTarget.VELOCITY` (`inertial`, bit-identical to today) or `_build_ecef_velocity_target_provider()` (`ecef`, reused verbatim — one new call site, zero changes to the provider). **De-risk item:** the addendum exercised the custom provider only in the *secondary* slot; the primary slot is typed the same (`TargetProvider` — the code already passes `PredefinedTarget.VELOCITY` there), but per the `@JImplements` rule it must be proven inside a real `propagate()` — the primary path may invoke different default-method overloads than the secondary did.

**Attitude rates.** The zero-derivative trick now sits under the *primary* alignment, so the `ecef` branch's attitude *rates* are not faithful — the same accepted consequence class as `NadirPointing`-ecef, and immaterial here: attitude feeds only force cross-sections, never rates, and v1 zeroes attitude rates by design.

**Validation** (at construction — pure-Python, safe before init):

| Condition | Result |
|---|---|
| `InPlaneTracking(velocity_reference=…)` not in `("inertial", "ecef")` | `ValueError` (the `NadirPointing` message shape, sharing `_VALID_VELOCITY_REFERENCES`) |

**Failure mode / degenerate domain (verified at build, 2026-07-04).** On an orbit whose ground-relative velocity is ~0 (geostationary-ish) the *primary* target `v_rel = v − ω⊕×r` is physically meaningless. The hard failure the `NadirPointing`-ecef row promised (`NumericalPropagationError`) fires only when `|v_rel|` is **exactly** zero — Hipparchus `normalize()` throws on exact zero only — which floating point never reaches: the EME2000-equator vs true-spin-axis offset alone keeps an EME2000-equatorial GEO orbit at `|v_rel|` ≈ 15 m/s, so a near-GEO propagation **completes without error, carrying a noise-driven attitude** (pinned by `test_in_plane_tracking_ecef_near_geostationary_completes`). Note the primary-slot consequence is *worse* than `NadirPointing`'s: there a degenerate `v_rel` only wobbles the best-effort yaw about a still-pinned nadir, while here the corrupted target is the exact primary, so the **whole body frame** (all drag/SRP cross-sections) becomes noise. LEO is the validated domain; the wrap-up rewording of the features.md failure-modes row must describe this for **both** ecef modes rather than promising an error.

**Metadata.** `in_plane_tracking:vel=inertial` | `in_plane_tracking:vel=ecef` — the `nadir_pointing:vel=…` grammar, **always emitted** (grammar consistency wins; metadata is descriptive output, not parsed input — the default's token changes from the bare `in_plane_tracking`). The recording gate is unchanged (the `attitude` key appears only for a box with a wired surface force).

**Sphere interaction (unchanged).** `InPlaneTracking` with either reference on a sphere has no dynamical effect: the existing one-time attitude/geometry consistency warning + `LofAligned` fallback applies.

**Performance.** `ecef` pays one Python `TargetProvider` crossing per attitude evaluation (value + derivative-2 calls) — the same accepted cost as `NadirPointing`-ecef. `inertial` stays fully native, zero change.

**Out of scope (the rest of the family).**

- **`LofAligned`-ecef** — permanently redundant: `InPlaneTracking`-ecef up to a fixed body-axis permutation.
- **`LofOffset`-ecef** — the named follow-on (a plate at *controlled incidence to the true flow*, the natural `BoxFaceCd` companion for incidence sweeps). Implementation note for when it's scoped: no wrapper provider is needed — `AlignedAndConstrained` accepts arbitrary body vectors, so a fixed Euler offset is equivalent to aligning the offset-rotated body axes (`R_offset·X̂` → wind target, `R_offset·Ẑ` → momentum); the care points are rotation-sense consistency (the `FRAME_TRANSFORM` vs `VECTOR_OPERATOR` trap documented on the `Inertial` branch) and the exactness structure (native TNW holds both axes exactly; the flow frame is exact-primary/best-effort-secondary). Meanwhile `CustomAttitude` covers the case.
- **`SunPointing` `phasing_reference="velocity_ecef"`** — mechanically the `NadirPointing` swap (secondary slot), physically second-order; add only for API symmetry if ever wanted.

**Evidence gate** (front-loaded, the build plan's first chunk — STOP/GO). A feathered-sail study, wholly in the conda env (every piece is shipped — no experiment venv): a representative thin-plate box with `BoxFaceCd.default()` on a ~500 km SSO over a multi-day window, `InPlaneTracking(velocity_reference="inertial")` vs `"ecef"`. Report (a) the big-face AoA history (expected: identically ~0 for `ecef`; oscillating 0–~3.8° for `inertial`), (b) the assembled `CdA` history, (c) the along-track divergence. **GO** iff the difference is material by the Tier B bar (coherent, attitude-correlated, not absorbable); otherwise the parameter is dropped.


## Planetary Third-Body & Earth Radiation Pressure

> Adds two opt-in perturbations to `propagate_numerical` — **`planets_third_body`**
> (lumped third-body gravity from the seven planets other than Earth) and
> **`earth_radiation`** (Knocke's rediffused Earth albedo + thermal-infrared radiation
> pressure) — the fourth general upgrade feeding v0.5.0 (one branch,
> `feature/additional-perturbations`, both chunks; realizing items 1–2 of
> `docs/history/prospective-forces-and-progress-findings.md` — item 3, progress reporting, stays
> unscoped and that doc remains its reference). Both ride inside `ForceModelConfig` — the
> designed extension point — so the frozen `propagate_numerical` signature is untouched;
> both are **off in every preset** (default runs stay bit-identical); and both wire
> **stock Orekit force models** (no `@JImplements` proxies, so the JPype default-method
> trap does not apply). The headline user for `earth_radiation` is the solar-sail regime
> the last two upgrades built toward: ERP scales with area-to-mass and, for a box, acts
> through the attitude-dependent `BoxAndSolarArraySpacecraft` cross-section, so it
> composes with `BoxFaceCd` + ECEF `InPlaneTracking` for free. This section is the
> **binding contract**: config fields and placement, the pinned planet set, wiring,
> metadata grammar, the resolution constant, validation, docstrings, and the evidence
> deliverables. It supersedes only the enumerated `features.md` §1.1 /
> `architecture.md` spots below; everything else stands.
>
> **Outcome (2026-07-05): planets shipped in full; `earth_radiation` blocked on
> upstream.** `planets_third_body` landed per this contract (build-plan Chunk 1; GEO
> effect pin ~0.15 m / 3 d at the fixed test epoch, LEO ~5e-4 m / 1 d) and its
> Supercessions are **folded back** into `features.md` §1.1 / `architecture.md` §13.
> The ERP runtime was **fully built and then reverted, unshipped**: its
> effect-envelope test exposed a defect in Orekit's `KnockeRediffusedForceModel` —
> every released Orekit through 13.1.5 bounds the visible-cap integration with
> `asin(R/r)` instead of `acos(R/r)`, making ERP ~2.4–3× hot at LEO (even in
> eclipse) and ~10–20× cold at GEO; the fix shipped in **Orekit 13.1.6 (2026-06-03)**
> but no installable orekit_jpype wrapper ≥ 13.1.6 exists yet (conda-forge: 13.1.4.0;
> PyPI: 13.1.5.0). Evidence, the parked Chunk-2 patch, and the resume recipe live in
> `experiments/earth-radiation/`. A second finding recorded there: the model
> converges only for `angularResolution` ≲ 2°, and the fix changes the LEO cap, so
> the resolution benchmark must run fresh after the upgrade. The ERP parts of the
> Supercessions below (the `earth_radiation` field, its token, the widened
> `spacecraft`/`attitude` gates, the model-limitations bullet) are **pending, not
> folded back** — this section remains their binding design for the resumed build.

### Supercessions

- **`features.md` §1.1, `ForceModelConfig` dataclass** — gains `planets_third_body: bool = False` (inserted after `moon_third_body`) and `earth_radiation: bool = False` (inserted after `srp`). Fields are **inserted in metadata-grammar order, not appended**: the dataclass reads in the same fixed order as the grammar. This shifts the positional index of every later field — accepted deliberately (0.x semver; every §1.1/§9 example constructs by keyword, and an 11-field config constructed positionally was already unreadable).
- **`features.md` §1.1, preset table + prose** — the table gains a `planets_third_body` / `earth_radiation` row (False / False / False across all three presets); the "Tides and relativity are off in all presets" sentence extends to cover both new fields, plus the two honesty caveats in **Details → Docstrings** (planetary magnitudes; ERP cost/regime).
- **`features.md` §1.1, `force_models` grammar paragraph + example** — the fixed token order becomes: gravity, `third_body:sun`, `third_body:moon`, **`third_body:planets`**, drag, srp, **`earth_radiation`**, `tides:solid`, `tides:ocean`, relativity (see **Details → Metadata**).
- **`features.md` §1.1, optional-physics-keys paragraph** — the `spacecraft` gate "appears when **drag or SRP** was wired" becomes "drag, SRP, or Earth radiation" (all three consume mass/area/coefficients); the `attitude` gate "box **and** drag or SRP" becomes "box **and** drag, SRP, or Earth radiation".
- **`features.md` §1.1, model-limitations docstring** — gains the Earth-radiation bullet in **Details → Docstrings**.
- **`architecture.md` §13, decisions log** — gains a resolved "Force inventory extended (v0.5.0)" bullet at fold-back: lumped seven-planet third body + Knocke Earth radiation, both opt-in, both stock Orekit.
- **Code** — the migration touches, at minimum: `core/bodies.py` (seven planet accessors, verbatim `_moon()` clones); `propagation/force_models.py` (the two fields in grammar position; `_serialize_force_models` gains two **required** keyword params + token emission; `_metadata_tokens` passes them; the module-docstring token-order sentence); `propagation/numerical.py` (`_WiredForces` two fields; `_add_perturbation_forces` — the planets loop after the Moon block, the ERP force after SRP, the box-build condition gains `or fm.earth_radiation`; a new `_build_earth_radiation_force` beside `_build_srp_force`; a new `_EARTH_RADIATION_ANGULAR_RESOLUTION` constant beside `_OCEAN_TIDE_DEGREE`; the `_serialize_force_models` call site; the `spacecraft`/`attitude` metadata gates and their "only drag/SRP consume mass/geometry" comments; the `propagate_numerical` docstring); the consuming tests (`tests/propagation/test_force_models.py` grammar/preset pins, `test_numerical.py` wiring/metadata); and `README.md` / `CLAUDE.md` force-inventory mentions. (Detailed sequencing is the build plan's job; this lists the surface so none is missed.)

### Context

The decision record (condensed from `docs/history/prospective-forces-and-progress-findings.md` §2–§3; Orekit-API claims there were confirmed against the installed orekit_jpype 13.1.x by direct introspection on 2026-06-20):

- **Planetary gravity ships as completeness, honestly scoped.** Planetary accelerations on an Earth orbiter are ~1e-10–1e-13 of central gravity (Venus and Jupiter dominate) — this will never visibly move a LEO trajectory, and the contract says so out loud. It ships anyway because the cost is trivial: the Sun/Moon third-body path is cloned verbatim, `CelestialBodyFactory` already exposes every planet, and the JPL DE ephemeris **already bundled in orekit-data answers for all of them** (probed: `getJupiter()` resolves and returns a µ) — no new data dependency, no resolver work. At that price, "full third-body completeness" is worth having for high-precision GEO / long-arc work.
- **One lumped toggle, not per-planet booleans.** At these magnitudes, per-planet selection is false granularity — no one has a physical reason to want "just Saturn", and seven booleans (or a names-tuple) would bloat the config and the metadata grammar for zero information. A single `planets_third_body` boolean with a **pinned** planet set keeps the config readable, the grammar token deterministic, and the intent honest ("completeness on/off"). (The findings doc leaned toward a couple of explicit booleans; this contract supersedes that lean.)
- **Earth radiation pressure ships on domain fit, not completeness.** ERP is a recognized term in precise LEO orbit determination, largest for low, high-area-to-mass craft — exactly the solar/drag-sail regime propygator's maintainer targets and the last two upgrades (`BoxFaceCd`, ECEF `InPlaneTracking`) built toward. For a representative sail it is roughly 10–25 % of direct SRP (albedo ~0.3 of the solar constant plus Earth IR, geometry-dependent) — a real force-budget term where radiation pressure is the point. For a box it rides the attitude-dependent `BoxAndSolarArraySpacecraft`, so a feathered or Sun-pointing sail sees it on the correct projected area with zero extra wiring.
- **Named `earth_radiation`, not `earth_albedo`.** Knocke's "rediffused" model bundles reflected sunlight (visible albedo) *with* Earth's own thermal-infrared re-emission, and Orekit ships only the combined model. The name and docs must say albedo + IR — a contract decision, not a code one.
- **The resolution knob is a hardcoded constant, not a config field.** `KnockeRediffusedForceModel`'s `angularResolution` is a continuous tuning knob; a field for it on `ForceModelConfig` would reopen the models-vs-coefficients split the config deliberately keeps clean. It lands as a module constant (`_EARTH_RADIATION_ANGULAR_RESOLUTION`, the `_OCEAN_TIDE_DEGREE` precedent), with its value chosen by a small front-loaded benchmark (see **Evidence deliverables**) rather than guessed in this contract.
- **No go/no-go gate this time.** Tier B and ECEF `InPlaneTracking` carried STOP/GO evidence gates because shipping hinged on an unmeasured effect being material. Here the magnitudes are already understood (the findings-doc probe + the published ERP literature): planets ship *despite* being tiny (completeness at trivial cost — the tiny magnitude is the documented caveat, not a ship-blocker), and ERP ships on domain grounds. The evidence work below is **selection and characterization** (pick the resolution constant; measure and record the honest magnitudes), not a ship gate.

### Details

**API at a glance** (the full post-upgrade `ForceModelConfig`; both new fields marked):

```python
@dataclass(frozen=True)
class ForceModelConfig:
    gravity_degree: int = 70
    gravity_order: int = 70
    gravity_field: str = "EIGEN-6S"
    sun_third_body: bool = True
    moon_third_body: bool = True
    planets_third_body: bool = False   # NEW — the seven other planets, lumped
    drag: bool = True
    atmosphere_model: str = "NRLMSISE-00"
    srp: bool = True
    earth_radiation: bool = False      # NEW — Knocke Earth albedo + thermal IR
    solid_tides: bool = False
    ocean_tides: bool = False
    relativity: bool = False
```

**The planet set (pinned).** `planets_third_body=True` wires third-body point-mass attraction from exactly the **seven planets other than Earth** — Mercury, Venus, Mars, Jupiter, Saturn, Uranus, Neptune — added in that (heliocentric) order immediately after the Moon block in `_add_perturbation_forces` (the force sum is order-independent; a pinned order keeps the wiring deterministic and reviewable). Pluto is excluded (not a planet; effect beyond negligible); the barycenter accessors (`getSolarSystemBarycenter` / `getEarthMoonBarycenter`) are not third bodies for this purpose. Pinning the set is what makes the single `third_body:planets` metadata token deterministic forever.

**Planets wiring.** Seven accessors in `core/bodies.py` (`_mercury()` … `_neptune()`), each a verbatim clone of `_moon()` over the matching `CelestialBodyFactory` getter (module-internal, lazy-JVM, same docstring shape). `_add_perturbation_forces` adds seven `ThirdBodyAttraction`s. The bundled DE ephemeris covers all seven — **no new data dependency**; a nonstandard, trimmed orekit-data missing planetary ephemerides fails inside the factory exactly as a missing Sun/Moon would (same failure class; no new handling).

**Earth-radiation wiring.** A new `_build_earth_radiation_force(geometry, sun, box)` parallel to `_build_srp_force`, added immediately after SRP (force-addition order = token order):

```python
KnockeRediffusedForceModel(_sun(), radiation_sensitive,
                           Constants.WGS84_EARTH_EQUATORIAL_RADIUS,
                           _EARTH_RADIATION_ANGULAR_RESOLUTION)
```

- **Optics are the SRP optics, reused.** Sphere → an `IsotropicRadiationSingleCoefficient(area_m2, reflectivity_coefficient)` with the same coefficients as SRP (the object is stateless, so building a second instance is fine; the build may hoist to share one). Box → the **shared `BoxAndSolarArraySpacecraft`**, which then drives up to **three** forces (drag + SRP + Earth radiation): the box-build condition in `_add_perturbation_forces` gains `or fm.earth_radiation`. No new coefficients, no new spacecraft-config surface.
- **The 4-arg constructor** (default time scale for the model's periodic albedo terms); the 5-arg `TimeScale` overload exists if the build finds a concrete need — using it is an implementation detail, not a contract change.
- **Independent of `srp`.** Knocke needs the Sun position and the optics, not the SRP force: `earth_radiation=True, srp=False` is valid (physically odd, but no coupling validation — consistent with every other independent toggle).
- **No shadow wiring.** Earth IR acts in eclipse too, and the model computes the lit cap itself — there is no eclipse/shadow configuration to add or record.
- **Sphere + attitude interaction unchanged.** ERP on a sphere is attitude-invariant; the existing one-time "attitude has no effect on orientation-independent geometry" warning path is untouched.

**`_EARTH_RADIATION_ANGULAR_RESOLUTION`.** A module constant in `numerical.py` beside `_OCEAN_TIDE_DEGREE`, radians, controlling how finely Knocke discretizes Earth's visible cap. Its **value is not pinned by this contract** — it is chosen by the front-loaded resolution benchmark (Evidence deliverable 1) as the coarsest resolution whose orbit-level ERP effect is converged for the reference cases, and lands with a comment citing that study. Changing it later is a behavior change pinned by `propygator_version` (see Metadata).

**Metadata.**

- **Grammar** (fixed token order, extended): gravity, `third_body:sun`, `third_body:moon`, **`third_body:planets`**, drag (`drag:<model>`), `srp`, **`earth_radiation`**, `tides:solid`, `tides:ocean`, `relativity`. `third_body:planets` is **one token** — the lumped config produces a lumped token whose meaning (the pinned seven-planet set) lives in features.md; per-planet tokens would bloat every metadata block for zero information. `earth_radiation` is a **bare token**: the resolution constant is *not* encoded, on the ocean-tides precedent (the 4×4 truncation isn't in `tides:ocean` either) — the recorded `propygator_version` pins both constants. Example (everything the LEO preset has, plus both new forces):

```python
["gravity:EIGEN-6S:70x70", "third_body:sun", "third_body:moon", "third_body:planets",
 "drag:NRLMSISE-00", "srp", "earth_radiation"]
```

- **Serializer.** `_serialize_force_models` gains two **required** keyword params (`planets_third_body`, `earth_radiation`) — required, not defaulted, so no call site can silently omit them; `_WiredForces` gains the matching fields; `propagate_numerical` serializes from the wired facts, never the config booleans, exactly as today. A run with both fields off emits byte-identical metadata to a pre-upgrade run.
- **Optional-key gates.** `spacecraft` records when **drag, SRP, or Earth radiation** was wired; `attitude` when geometry is a box **and** any of those three was wired. (Both code comments saying "only drag/SRP consume mass/geometry/coefficients" are updated — ERP is now the third such force.)

**Validation.** None new at construction: both fields are plain booleans with no invalid states and no coupling constraints; `__post_init__` is untouched. All three presets are **unchanged** (both fields False everywhere), so preset construction and serialization stay bit-identical.

**Failure modes.** None new. Both forces are stock Orekit classes wired through existing seams: no Python-implemented Java interfaces (no default-method trap), no new data resolution, no new degenerate domains. The only genuinely new failure surface is a broken/trimmed orekit-data install (planets), which fails in the same class as a missing Sun/Moon.

**Performance (honest accounting).** Planets: seven extra point-mass evaluations + DE-ephemeris lookups per integrator substep, all Java-side — negligible next to a single NRLMSISE-00 density query; no measurable wall-clock change expected on a drag-on run. Earth radiation: Knocke integrates over the discretized visible cap **every substep** — a real, resolution-dependent cost (quantified by the benchmark), but entirely Java-side (no per-substep JPype crossing, unlike the drag proxy). Both default off, so the default-path cost is exactly zero.

**Docstrings.** Two honesty caveats are part of the contract:

- *Planetary magnitudes* (features.md preset prose + the `planets_third_body` field doc): "Planetary third-body accelerations on an Earth orbiter are ~1e-10–1e-13 of central gravity (Venus and Jupiter dominate); `planets_third_body` is a completeness option for high-precision or long-arc work — it will not visibly move a LEO trajectory."
- *Earth radiation* (a new bullet in the `propagate_numerical` model-limitations note, after the SRP bullet):

```
* Earth radiation pressure (earth_radiation) uses Knocke's low-order zonal
  Earth albedo + thermal-infrared model, applied through the same uniform
  optical coefficients as SRP, on a lit-cap discretization fixed at a
  version-pinned angular resolution. Per-face optical properties and
  higher-fidelity Earth radiation models are not included.
```

**Evidence deliverables** (front-loaded where they inform the build; characterization, **not** a ship gate):

1. **ERP resolution benchmark** (`experiments/earth-radiation/`, wholly in the conda env — every piece is shipped, no experiment venv): sweep `angularResolution` over a coarse-to-fine ladder (e.g. 90° → 45° → 30° → 15° → 10° → 5° → 2.5°) for the reference sail (the ECEF study's 1 m² / 0.5 kg at 500 km SSO) over a multi-day arc, with the finest grid as truth. Pick the **coarsest** resolution whose along-track ERP effect agrees with truth to well within the model's own uncertainty (a few % of the effect), and report wall-clock overhead per rung. The chosen value lands as `_EARTH_RADIATION_ANGULAR_RESOLUTION` with a comment citing this study.
2. **ERP magnitude characterization** (same experiment): with/without `earth_radiation` for (a) the reference sail and (b) a conventional bus (the 1000 kg / 1 m² default sphere) in LEO; report the ERP-vs-SRP acceleration fraction and the along-track divergence, plus a direction sanity check (mostly radially outward). These are the honest numbers that feed the docstring/CHANGELOG framing.
3. **Planets effect pin**: with/without `planets_third_body` on a multi-day GEO arc (drag off, so it runs fast), asserting a small nonzero divergence in the expected envelope, and a LEO arc showing the effect is negligible there. Small enough to live as a test rather than an experiment (build plan decides the home).
4. **Tests** (beyond the pins above): grammar token order/presence for both tokens; preset bit-identity (all three presets carry both fields False; default-config serialization unchanged); the metadata-gate changes (an ERP-only run — drag and SRP off — records `spacecraft`; a box + ERP run records `attitude`); and a box + ERP smoke through a real `propagate()` (three forces driven off one shared box object).

**Out of scope.**

- **Per-planet toggles / an `extra_third_bodies` names-tuple** — false granularity at these magnitudes; the lumped boolean is the API. If a genuine per-body need ever materializes, an additive tuple field can coexist with the lumped toggle.
- **Pluto and the barycenter accessors** — excluded from the pinned set (see above).
- **An `angular_resolution` field on `ForceModelConfig`** — would reopen the models-vs-coefficients split; the constant is the v1 shape (ocean-tides precedent).
- **Separate albedo-only / IR-only switches** — Orekit ships only the combined Knocke model; the honest combined name is the feature.
- **Per-face optical properties** (a radiation analog of `BoxFaceCd`) — not modeled; stays in the model-limitations note.
- **Progress reporting** (findings doc §4) — deferred, unscoped; the findings doc stays in `docs/` as its reference.

**Build shape** (one branch, `feature/additional-perturbations`; detailed sequencing is the build plan's job): planets chunk first (afternoon-scale; exercises the config/grammar/`_WiredForces` seams end-to-end), then the ERP runtime + tests (with a **provisional** resolution constant), then the ERP experiment (deliverables 1–2 — run *through the shipped path* by overriding the module constant per rung, which is why the runtime lands first; it finalizes `_EARTH_RADIATION_ANGULAR_RESOLUTION` before any doc quotes a number), then docs fold-back + wrap-up — Supercessions folded into `features.md` §1.1 / `architecture.md` §13 / `README.md` / `CLAUDE.md`; a status note added to `docs/history/prospective-forces-and-progress-findings.md` marking items 1–2 realized (the doc stays put for item 3); CHANGELOG `[Unreleased]` entry per `docs/changelog-guidelines.md` (maintainer-authored); squash-merge to `main`, **no tag** (v0.5.0 is tagged once, after all general upgrades land).


## Civil Time Zones & Progress Reporting

> Two user-experience upgrades feeding v0.5.0 (the fifth general upgrade, its own
> branch): **(A)** an optional `tz=` on `live_track` that re-expresses the dashboard's
> readout clock in a **US civil time zone** (default unchanged — UTC), and **(B)**
> **default-on progress reporting** for the long-running verbs — plain, throttled stderr
> status lines so a user never stares at a seemingly frozen terminal. (B) realizes item 3
> of `docs/history/prospective-forces-and-progress-findings.md` (§4), which that doc left
> unscoped; §4 stays its mechanism reference until this ships. Part A rides the tz-ready
> `_format_clock` seam already built into `tracking/live.py` (features.md §1.4 named it),
> so the core time model is untouched; Part B adds one keyword-with-default to the frozen
> `propagate_numerical` signature — the **one deliberate §1.1 signature edit** among the
> general upgrades — plus a narrow, documented exception to the "logging, never prints"
> convention. Neither changes any existing default *output* except that a bare
> `propagate_numerical(...)` now prints progress. This section is the **binding
> contract**: the `tz=` surface and resolution, the `USTimeZone` set, the `progress`
> surface and reporter behavior, the sanctioned-exception carve-out, and the blast radius
> for both. It supersedes only the enumerated `features.md` §1.1 / §1.4,
> `architecture.md`, and `CLAUDE.md` spots below; everything else stands.
>
> **Outcome (2026-07-06): shipped in full — both parts** (branch
> `feature/ux-improvements`; build plan archived at
> `docs/history/build-plan-ux-improvements.md`). Supercessions folded back into
> `features.md` §1.1 (the `progress` signature edit + a "Progress reporting"
> section) / §1.4 (the `tz=` signature line, the readout-clock paragraph, the
> realized time-zone bullet), `architecture.md` §Logging + `CLAUDE.md` (the
> sanctioned-exception carve-out), and the findings doc's item-3 status. Two
> mechanism facts learned at build (both pinned in code + tests): the step
> normalizer does **not** guarantee a `handleStep` tick at the exact endpoint, so
> the proxy's `finish(final_state)` forwards the true final fraction (1.0 on
> completion, the stop fraction on a guard stop); and the `try/finally` was
> widened to start immediately after `reporter.start()`, so even a *setup*
> failure (e.g. missing orekit-data) ends with the honest `failed at NN%` line.
> The final line quotes the reporter's own elapsed clock (JVM startup included)
> for consistency with the tick lines.

### Supercessions

**Part A — time zones:**

- **`features.md` §1.4, ground-track-panel paragraph** — "a **UTC clock** (formatted through a tz-ready seam — UTC now, additive `tz=` later, no core changes)" becomes: the readout clock is UTC by default and re-expressed in a US civil zone when `live_track(..., tz=)` is supplied (a pure display offset, DST-correct; not a `TimeScale` change).
- **`features.md` §1.4, "Still open / deferred → Time-zone exposure" bullet** — the `live_track` `tz=` half is **realized here**; the "eventual general UTC → US-zone tools" half maps onto Feature 1.5 `find_passes` (its `Pass` rise/culmination/set epochs), which inherits the same `USTimeZone` / `_resolve_tz` surface and stays future.
- **`features.md` §1.4, `live_track` signature** — gains a trailing keyword-only `tz: USTimeZone | tzinfo | None = None` (additive, backward-compatible; `None` → UTC, bit-identical to today). The three buffer magnitudes are unchanged.
- **`tracking/live.py`, `_format_clock` docstring** — the "v1 always renders UTC; a future `tz=` … out of scope for 1.4 (adds a `tzdata` dependency on Windows)" note is rewritten to describe the shipped `tz=` path; `tzdata` is now a declared dependency (see **Code**).
- **Code** — a new `USTimeZone` enum + `_resolve_tz(...)` helper in `core/time.py`, `USTimeZone` re-exported at the top level; the `tz` parameter on `live_track` resolved **once** at entry and threaded into the existing `_format_clock(now, tz=...)` call (no change to `_format_clock`'s body); `tzdata` **declared** in `environment.yml` (conda-forge name **`python-tzdata`** — the conda package named plain `tzdata` is the raw IANA database and does *not* provide the importable Python module `zoneinfo` needs on Windows) + `pyproject` runtime deps (PyPI name `tzdata`; today it is only a transitive pandas dep); tests; `README.md` / `CLAUDE.md` / `features.md` §1.4.

**Part B — progress reporting:**

- **`features.md` §1.1, `propagate_numerical` signature** — gains a trailing `progress: bool | ProgressCallback = True` (keyword-with-default; `ProgressCallback = Callable[[float], None]`). This is the single deliberate edit to the frozen §1.1 signature; it is additive and backward-compatible (existing calls are unaffected), but the **default changes observable behavior** — a bare `propagate_numerical(...)` now emits progress to stderr.
- **`features.md` §1.1, a new "Progress reporting" paragraph** — documents the default-on plain-line reporter, the `progress=False` opt-out, and the `progress=<callable>` seam.
- **`architecture.md` §Logging ("never bare prints") + `CLAUDE.md` "Architecture invariants" ("Logging, never prints")** — gain a **sanctioned-exception** clause: transient progress output may go to **stderr** provided it is TTY-gated, opt-out (`progress=False`), never written to stdout, and never attached to the root logger. (`logger.info` progress milestones are still emitted for handler-configured users.)
- **`docs/history/prospective-forces-and-progress-findings.md`, status header** — item 3 (progress reporting) moves from "remains unscoped — §4 is still the live reference" to "scoped by general-upgrades-1 §Civil Time Zones & Progress Reporting"; §4 stays the mechanism reference.
- **Features 1.5 `find_passes` / 1.2 `fit_tle` (NOT STARTED)** — their eventual signatures carry the same `progress` parameter from birth (a forward commitment, not an edit to existing text, so the reporter has three consumers).
- **Code** — a new `core/progress.py` (`_ProgressReporter`: determinate + indeterminate modes, the TTY gate, the 10-percent/heartbeat throttle, ASCII-only rendering, the callable pass-through; plus the public `ProgressCallback` alias — it names a public parameter type, so it is defined here and re-exported at the top level); `propagation/numerical.py` — an `OrekitFixedStepHandler` `@JImplements` proxy (all three of `init`/`handleStep`/`finish`), registered via `propagator.getMultiplexer().add(step, handler)`, the reporter finalized in a `finally`; the `progress` parameter and its wiring; tests; `README.md` / `CLAUDE.md`.

### Context

The decision record:

- **Time zones are display-only; the core time model must not learn civil zones.** `Epoch`/`TimeScale` carry *physics* scales (UTC/TAI/TT, leap seconds, deferred UT1) — a civil US zone with DST is a `datetime.astimezone(ZoneInfo(...))` applied to `Epoch.to_datetime()` (already tz-aware UTC), at the *formatting* boundary. So `tz=` lives on the display verb and threads into `_format_clock`; `Epoch` gains nothing. Only the suptitle readout localizes — the altitude/speed panels are elapsed-hours and the ground/sky panels are spatial, so there is no other wall-clock to touch.
- **Default UTC, not system-local.** Keeping UTC the default is backward-compatible (matches the §1.4 "UTC clock" description and every snapshot) and keeps output machine-independent. Local time is one keyword away; auto-detecting the host zone was considered and rejected (surprising, non-reproducible).
- **US-only via a curated enum + a `tzinfo` escape hatch.** `USTimeZone` (Eastern/Central/Mountain/Pacific/Alaska/Hawaii, plus Arizona — Mountain-clock/no-DST) keeps the US scope discoverable and off the full IANA surface; power users / non-US callers pass a raw `tzinfo` (`ZoneInfo(...)`). DST correctness *requires* `zoneinfo` (a fixed UTC offset is wrong half the year), which on Windows needs the `tzdata` package — hence declaring it.
- **`tzdata` is present, but only incidentally.** Probed in the `propygator` env: `python-tzdata` 2026.2 is installed (pandas pulls it) and `ZoneInfo("America/New_York")` resolves DST-correctly (→ EDT). The feature works today, but the plan **declares** `tzdata` so a future pandas change can't silently break tz on the maintainer's own (Windows) platform.
- **Progress must be default-on and visible — which forces stderr.** The requirement is that a user never wonders whether a long propagation has frozen. The repo's top-level `NullHandler` makes `logger.info` silent by default, so log-only (findings §4 option a) shows nothing out of the box and fails the requirement. Default-on visibility therefore requires writing to the console — reconciled with "logging, never prints" by treating a progress indicator as the **standard narrow carve-out** that `pip`/`git`/`tqdm` all take: stderr only, TTY-gated, opt-out, transient, never the root logger, never stdout. The TTY gate is load-bearing — pytest, CI, `conda run`, and the redirected `experiments/` scripts are all non-TTY, so they drop to the coarse milestone cadence (coarse, **not silent** — see Reporter behavior; that same choice keeps notebook runs informative, since Jupyter's captured stderr is non-TTY too). Interactive batch loops (a propagate-and-`export_all` script run at a terminal) *are* TTYs — they opt out with `progress=False` (see Default-on implications).
- **Plain milestone lines — no dependency, no hand-rolled bar.** Options weighed: a hard `tqdm` dep (best bar, but a genuinely new dependency — probed: tqdm is **not** installed and nothing pulls it in); a hand-rolled `\r` bar (no dep but ~40–60 lines re-implementing tqdm and its edge cases); and plain milestone stderr lines (no dep, ~15 lines). The stated goal ("know it's not frozen") is fully met by plain lines, so that ships. Because the reporter is an internal detail behind the `progress` param, promoting to tqdm later is a zero-API-change swap — the decision is low-stakes and reversible.
- **This is the one upgrade that edits the frozen §1.1 signature — deliberately.** The earlier general upgrades rode `ForceModelConfig` to stay signature-free; progress is not a force and has no such extension point, so it adds one keyword-with-default. The findings doc (§5.2) already flagged this as a conscious doc edit, not a silent add. It is the reusable seam Features 1.5 and 1.2 consume.

### Part A — time zones (details)

**`USTimeZone` (the pinned set).** A frozen enum in `core/time.py`, re-exported top-level, mapping a friendly US-zone name to its IANA key (DST handled by `zoneinfo`):

```python
class USTimeZone(Enum):
    EASTERN  = "America/New_York"
    CENTRAL  = "America/Chicago"
    MOUNTAIN = "America/Denver"
    PACIFIC  = "America/Los_Angeles"
    ALASKA   = "America/Anchorage"
    HAWAII   = "Pacific/Honolulu"   # no DST
    ARIZONA  = "America/Phoenix"    # Mountain clock, no DST
```

**Resolution.** `_resolve_tz(tz: USTimeZone | tzinfo | None) -> tzinfo`: `None → timezone.utc` (the unchanged default); a `tzinfo` is returned as-is (escape hatch); a `USTimeZone` is lowered to `ZoneInfo(member.value)`. A `ZoneInfoNotFoundError` (a stripped tz database) is re-raised as an actionable message naming `tzdata` — never a raw traceback (the repo's error-surface rule). Resolved **once** at `live_track` entry, not per frame.

**Threading.** `live_track` gains `tz: USTimeZone | tzinfo | None = None`; the resolved `tzinfo` is passed to the existing `_format_clock(now, tz=...)` call in `update()`. `_format_clock` already does `.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")`, so the `%Z` token self-documents the offset ("EDT" / "EST" / "UTC") and DST is automatic — **no change to `_format_clock`'s body**, only its docstring.

**User-visible change.** `tz=None` (default) → readout `… · 2026-07-05 18:42:03 UTC`, byte-identical to today. `live_track("ISS", tz=USTimeZone.PACIFIC)` → `… · 2026-07-05 11:42:03 PDT` (and "PST" in winter, automatically). Only the readout clock changes; every panel is unchanged.

**Dependency.** Declare it in `environment.yml` as conda-forge's **`python-tzdata`** (the conda package named plain `tzdata` is the raw IANA database — it does *not* provide the importable Python module `zoneinfo` falls back to on Windows) and in `pyproject` runtime deps under its PyPI name **`tzdata`**. It is a tiny pure-data package, already present transitively; declaring it makes the tz path deterministic across platforms rather than reliant on pandas' transitive pull.

**Feature 1.5 inheritance (forward note, not built here).** `find_passes` will accept the same `tz=` and apply `_resolve_tz` when it formats the `Pass` rise/culmination/set epochs — the "eventual UTC → US-zone tools" the §1.4 deferred bullet named. No 1.5 code lands in this section. *(Resolution at 1.5 contract drafting, 2026-07-07: the `tz=` surface lands on the pass **formatters** — `passes_to_dataframe` / `plot_sky_chart` / `plot_pass_timeline` — not on `find_passes` itself, which returns tz-less `Epoch`-carrying `Pass` objects and formats nothing. A maintainer-approved deviation from this note's literal wording; features §1.5 is binding.)*

**Out of scope (Part A).** Non-US zones as first-class enum members (use a raw `tzinfo`); localizing the CSV `epoch_utc` column (a §1.1-named archival UTC column — if ever wanted, an additive `local` column *group* on the `io/exports.py` registry, never a conversion of the canonical column); any change to `Epoch` / `TimeScale` / `to_iso` (civil zones stay out of the physics-scale model).

### Part B — progress reporting (details)

**Surface.** `propagate_numerical(..., progress: bool | ProgressCallback = True)` where `ProgressCallback = Callable[[float], None]` (fraction 0.0 → 1.0):

| `progress` | Behavior |
|---|---|
| `True` (default) | The built-in plain-line reporter (below) |
| `False` | Silent |
| a callable | Called with the 0→1 fraction each throttled tick; the library prints **nothing** (the seam for tqdm / a GUI / a log line) |

**Reporter behavior (`_ProgressReporter`, `core/progress.py`).** Plain, ASCII-only status lines to **stderr** (never stdout), one per throttled tick — no `\r` redraw:

- A `start` line prints **immediately** (before the first slow substep — the real "it began" signal).
- A progress line on each new **10%** *or* every **~5 wall-clock seconds**, whichever first (short runs aren't spammy; long runs get a heartbeat so they never look frozen).
- A `done` line with the final wall-clock and sample count.
- **TTY gate:** the fine cadence applies only when `sys.stderr.isatty()`; a non-TTY (piped, CI, redirected — the `experiments/` scripts, pytest) coarsens to `start` + 25/50/75 + `done` so log files stay clean. (Probed: under `conda run`, `stderr.isatty()` is `False`, confirming batch runs take the coarse cadence.)
- **ASCII-only** glyphs / separators (`|`, `-`, `#`) — dodges the Windows cp1252 stderr `UnicodeEncodeError` class the `experiments/` scripts already hit.
- **Determinate + indeterminate modes.** `propagate_numerical` and `find_passes` (1.5) drive a determinate 0→1 fraction; `fit_tle` (1.2), whose differential correction early-exits on convergence, drives the indeterminate mode (per-iteration `iter N | rms …` lines, no fake percentage).
- `logger.info` milestones are still emitted regardless (free for users who configure logging).

Format (illustrative, not literal):

```
propagate_numerical: start | 168.0 h | DOP853 | 60481 samples
propagate_numerical:  10% | t+16.8/168.0 h | 3.1 s
...
propagate_numerical: done | 168.0 h | 29.4 s | 60481 samples
```

On early termination the final line is honest, e.g. `propagate_numerical: stopped at 61% | reentry at t+102.4 h | 18.3 s | 6148 samples (partial)`.

**Mechanism (1.1).** An `OrekitFixedStepHandler` `@JImplements` proxy registered via `propagator.getMultiplexer().add(step_s, handler)` before `propagate()` (findings §4, probed). `handleStep(state)` computes `fraction = state.getDate().durationFrom(start_date) / span`, where `span = end_date.durationFrom(start_date)` — the **realized** propagation span `(n_samples − 1) · output_step`, which the sample grid floors to ≤ the requested `duration` (dividing by `duration` would top out below 1.0 whenever `duration` isn't a step multiple) — monotonic 0 → 1 — and calls `reporter.update(fraction)`. (The degenerate single-sample run has `span == 0`; the reporter guards it — `start`/`done` lines only, no fraction ticks.) The proxy must implement **all three** interface methods (`init` / `handleStep` / `finish`) — the JPype default-method trap (`guards.py`'s detectors dodge it via `FunctionalDetector`; here the three-method implement is simplest, per findings §5.3).

**Composition with the guard system.** The handler is read-only; on early termination (impact / escape / reentry) or the failure / partial-recovery path (`numerical.py` try/except) it simply stops firing. The reporter is finalized in a `finally` that spans propagation **through termination classification** (the reason in the `stopped at NN% | reentry …` line is known only after the guard system classifies, well past `propagate()` itself), so every exit path ends with an honest final line rather than a tick dangling at the achieved fraction — `done` on a clean run, the reason-bearing `stopped` line on a guard stop, and a reasonless `failed at NN%` on the re-raise path. The post-propagation sampling loop is not covered (rarely the bottleneck).

**Sanctioned exception (the convention-level decision).** Progress output narrowly bends "logging, never prints": it is stderr-only, TTY-gated, opt-out via `progress=False`, transient (no persistent state, no root-logger handler), and never touches stdout. `architecture.md` and `CLAUDE.md` gain this carve-out so the rule and its one exception are both explicit.

**Default-on implications.** A bare `propagate_numerical(...)` now prints — a deliberate, visible behavior change (CHANGELOG-noted). Loop callers (`export_all` batch, benefit studies) should pass `progress=False`; the TTY gate already silences the redirected `experiments/` scripts and CI / pytest.

**Features 1.5 / 1.2 (forward commitment, not built here).** Both take the same `progress` parameter from their first implementation — 1.5 a determinate window-scan fraction (`scanned / total`), 1.2 the indeterminate iteration mode (what the *callable* form receives in the indeterminate mode — `Callable[[float], None]` has no natural iteration semantics — is pinned by 1.2's own contract, not here). Designing the reporter for both now means the seam has three consumers and never needs reshaping.

**Out of scope (Part B).** A hard `tqdm` / `rich` dependency (the reporter is swappable behind `progress`, so tqdm can be promoted later with no API change); a `\r` animated bar (plain lines are the shape); covering the post-propagation sampling loop or `propagate_tle` (fast, analytic — no bar); a progress signal on any non-long-running verb.

### Build shape

(one branch feeding v0.5.0; detailed sequencing is the build plan's job.) Two independent parts, either orderable first. **Part A** — `USTimeZone` + `_resolve_tz` in `core/time.py`, top-level export, `tz=` on `live_track` threaded to `_format_clock`, declare `tzdata`, tests, then a manual GUI smoke of the localized readout via `run/live_dashboard_demo.py`. **Part B** — the `core/progress.py` reporter (with headless unit tests over both modes and the TTY gate), then the `OrekitFixedStepHandler` proxy + `progress` param in `propagate_numerical` (tested inside a real `propagate()`), the `finally` finalize, and the guard-path partial line, then the `architecture.md` / `CLAUDE.md` convention carve-out. **Wrap-up** — fold both Supercessions back into `features.md` §1.1 / §1.4, `architecture.md`, `CLAUDE.md`, `README.md`; flip the findings-doc item-3 status; CHANGELOG `[Unreleased]` (maintainer-authored); squash-merge to `main`, **no tag** (v0.5.0 is tagged once, after all general upgrades land).
