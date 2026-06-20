# propygator — Feature 1.1 Addendum: ECEF Nadir Yaw-Steering & Direction-Indicating Plot Markers

> **Status: RETIRED — binding reference for the next build plan.** This is an add-on
> design for the already-feature-complete-and-released numerical propagator (Feature
> 1.1, shipped in `v0.1.0`). The chunked build plan will be derived from this, the way
> `docs/history/build-plan-feature-1.1.md` was derived from `features.md` §1.1. It is
> **not** itself a build plan.
>
> **It supersedes specific, enumerated sections of `architecture.md` and
> `features.md`** (see §1, the supersession map). Where this document and those two
> conflict, *this* document wins until a future reconciliation folds it back.
> It supersedes **only** what it must; everything not listed in §1 is untouched and
> those docs remain authoritative. **THE RECONCILIATION IS ALREADY COMPLETE, AND THE
  SUPERCESSIONS NO LONGER HOLD.**

> **Naming convention.** This is one of several planned add-ons to Feature 1.1. Each
> lives in its own file named `feature-1.1-addendum-<topic>.md` so they can be written,
> reviewed, and reconciled independently. This file's topics are (A) completing the
> deferred **ECEF velocity-reference for `NadirPointing`** (Earth-relative yaw-steering)
> and (B) changing the spatial plots' **endpoint markers to direction-indicating
> glyphs** (an oriented triangle on the ground track, a cone in the 3-D view).

---

## 0. Purpose & scope

Two small, **independent** workstreams, bundled into one addendum because they are both
narrow finishing touches on the existing Feature 1.1 surface, neither blocks the other,
and neither adds a new public name:

- **A — ECEF nadir yaw-steering.** Complete the `NadirPointing(velocity_reference="ecef")`
  path, which ships today as a *validated skeleton*: it constructs, validates, and
  serializes, but lowering it to an Orekit provider raises `NotImplementedError`
  (`attitude.py:405-407`). This closes the deferral recorded in architecture §13 and
  the `features.md` §1.1 failure-modes table. **No signature, dataclass, or metadata
  change** — only the lowering step gains a real provider.

- **B — Direction-indicating endpoint glyphs.** Replace the two end-of-track markers
  that flag only *position* with glyphs that also flag *direction of travel*: the 2-D
  ground track's red **star** → a heading-oriented **triangle**; the 3-D view's red
  **diamond** → a velocity-oriented **cone**. The start marker (a direction-less blue
  circle) is unchanged. This is a cosmetic-baseline change (no binding contract;
  `features.md` line 573 explicitly defers cosmetic plot details), so it re-records
  the §11 snapshot/structural assertions rather than changing a contract.

**In scope:** the ECEF velocity-target provider + its verification; the heading
computation and rotated/oriented end glyphs for both spatial plots; the snapshot/test
and docstring reconciliation; the version-bump recommendation (§6).

**Out of scope (explicitly deferred, unchanged):** backward-in-time propagation (a
contract change with its own correctness/physics risks — deferred to a later addendum);
the Tier B `IncidenceVariableCd` runtime path; UT1; per-facet Sentman drag; local-orbital
frames beyond TNW; `RTN`/`LVLH` frames (architecture §13).

---

## 1. Supersession map (read this first; it is the reconciliation key)

| Source section | Relationship | What changes |
|---|---|---|
| `architecture.md` §13 → **"`NadirPointing` ECEF-relative velocity yaw"** (line 1050) | **SUPERSEDED (resolved)** | The validated-skeleton deferral is closed. ECEF is implemented via a custom `@JImplements TargetProvider` that subtracts Earth rotation (§2) — exactly the completion route the deferral itself anticipated. |
| `architecture.md` §13 → **"Attitude family"** resolved note (line 1037) | **EXTENDED** | `NadirPointing` now wires **both** `velocity_reference` options; the note gains the ECEF target provider alongside the inertial `PredefinedTarget.VELOCITY`. |
| `features.md` §1.1 → **`NadirPointing` docstring + `velocity_reference` comment** (lines 206–213) | **EXTENDED** | The "`ecef` is a deferred / validated-skeleton" wording is replaced by "`ecef` = Earth-relative (ground-track) velocity yaw, implemented." Signature and metadata token (`nadir_pointing:vel=ecef`) are unchanged. |
| `features.md` §1.1 → **Failure-modes table** row `NadirPointing(velocity_reference='ecef')` → `NotImplementedError` (line 363) | **SUPERSEDED (removed)** | That row is deleted — the path no longer raises. |
| `features.md` §1.1 → **"Styling" / "Cosmetic plot details … deferred"** (line 573) + the endpoint-marker baseline in `plotting/style.py` | **EXTENDED (cosmetic)** | The locked endpoint glyphs change (§3): ground-track end **star → heading-oriented triangle**; 3-D end **diamond → velocity-oriented cone**. The structural layout is unchanged; this is within the deferred-cosmetic latitude, so it re-records snapshots rather than altering a contract. |
| `docs/history/build-plan-feature-1.1.md` → **"Notes / deferred"** ECEF bullet (lines 847–851) | **SUPERSEDED (resolved)** | History doc; the ECEF deferral it records is closed by this addendum. (Left in place as a record; not edited.) |

Anything not in this table is **not** superseded.

**New additions (not supersessions): none.** Unlike the drag-validity & altitude-guards
addendum (which added the public `AltitudeLimits` type), this addendum adds **no new
public name, config dataclass, exception type, metadata key, or signature parameter**.
Workstream A completes an existing config option's runtime; workstream B changes the
appearance of existing output. Consequently the `__init__.py` re-export list
(architecture §7) and the public type inventory (architecture §6) are untouched. The
only build-time reconciliation artifacts are the doc edits in this map, the re-recorded
snapshots, and a `CHANGELOG.md` `[Unreleased]` entry + version bump (§6, authored by the
maintainer).

---

## 2. Workstream A — `NadirPointing(velocity_reference="ecef")`

### 2.1 What it models (the real-world situation)

`NadirPointing` holds body −Z on nadir (an instrument looking straight down) and steers
body +Y toward "the velocity vector." The `velocity_reference` chooses *which* velocity:

- **`inertial`** (wired today): +Y tracks velocity in the non-rotating EME2000 frame — the
  true orbital velocity vector.
- **`ecef`** (this workstream): +Y tracks velocity **relative to the rotating Earth** —
  the ground-track direction, `v_rel = v_inertial − ω⊕ × r`.

The two differ by the Earth-rotation term `ω⊕ × r`, which in LEO is ~0.5 km/s against an
orbital speed of ~7.5 km/s — a yaw offset of **up to ~3–4°**, varying sinusoidally over an
orbit (largest near the equator, vanishing at the orbit's highest-latitude turning points,
scaled by inclination).

**The use case is yaw steering for Earth observation.** A push-broom imager (or SAR, or
any ground-footprint instrument — Landsat, the Sentinels, SPOT) builds an image by
sweeping a cross-track detector line across the ground. For the image to be un-skewed, the
detector line must be perpendicular to the **ground-track** velocity, not the inertial
velocity; because the Earth rotates underneath, the two differ by that few-degree yaw, and
across a swath hundreds of km wide that is a large ground displacement. Real spacecraft
continuously rotate about the nadir axis to null it — the maneuver is literally called
*yaw steering* / *yaw compensation*. So `ecef` is the more physically realistic mode for
imaging missions; it is "special" only because Orekit ships the inertial velocity as a
primitive (`PredefinedTarget.VELOCITY`) but has **no** built-in ground-relative-velocity
target.

### 2.2 Current state (the validated skeleton — do not rebuild it)

These already exist and **do not change**:

- `_VALID_VELOCITY_REFERENCES = ("inertial", "ecef")` (`attitude.py:107`); `NadirPointing.__post_init__`
  accepts both.
- `_metadata_string()` → `"nadir_pointing:vel=ecef"` (`attitude.py:246`). No metadata grammar change.
- `NadirPointing` is already re-exported at top level.

The single deferral is in `_to_provider`: `if config.velocity_reference == "ecef": raise
NotImplementedError(_ECEF_DEFERRED_MESSAGE)` (`attitude.py:405-407`, message at 312–318).

### 2.3 Implementation contract

Replace that raise with a provider that yaw-steers to the **Earth-relative** velocity.
The inertial branch lowers to
`AlignedAndConstrained(primary −Z → PredefinedTarget.NADIR, secondary +Y → PredefinedTarget.VELOCITY, sun, earth)`
(`attitude.py:409-416`). The ECEF branch keeps the **same primary** (−Z on nadir, exact)
and swaps **only the secondary target** for a custom `TargetProvider` that yields the
ground-relative velocity direction — so the two `velocity_reference` options stay on one
code path, differing only by the `ω⊕ × r` term, which is the whole point.

**Route (the contract): a custom `@JImplements(TargetProvider)` proxy.** This is the route
architecture §13 commits to ("a custom `@JImplements TargetProvider` that subtracts Earth
rotation"). It returns the normalized `v_rel = v_inertial − ω⊕ × r` direction in the
propagation (EME2000) frame, computed from Orekit's inertial↔ITRF `Transform` at the
sample date (which carries Earth's rotation rate) — i.e. take the Earth-relative velocity
and express its direction back in the inertial frame. `AlignedAndConstrained`'s constructor
accepts any `TargetProvider` in the secondary slot (`PredefinedTarget` is itself a
`TargetProvider`), so the custom proxy drops in with no other change.

**This route is empirically de-risked (live JVM test, 2026-06-18).** The custom proxy was
built and driven through a real `NumericalPropagator.propagate()` on a 500 km / 51.6° box:
it lands on propygator's exact convention (`+Y → v_rel` < 0.01°, `−Z → nadir` < 0.02°) and
produces the expected yaw (3.08° at the equator → ~0 near the max-latitude turning point).
The interface shape and the two JPype traps below are confirmed, not assumed; see the
memory note `ecef-nadir-targetprovider-route`.

**Interface shape (verified, installed 13.1.x).** `TargetProvider` has **one abstract
method** — `getTargetDirection(ExtendedPositionProvider sun, OneAxisEllipsoid earth,
TimeStampedFieldPVCoordinates<T> pv, Frame frame) -> FieldVector3D<T>` — plus default
overloads (a plain-PV `getTargetDirection -> Vector3D` and two `getDerivative2TargetDirection`).
The `AlignedAndConstrained` secondary slot does accept this non-`PredefinedTarget` provider.

**Build notes (the two real traps — both confirmed, both surface only inside a real
`propagate()`, never in a bare `getAttitude`):**

1. **Default-method trap (the recorded lesson, again).** `AlignedAndConstrained` actually
   invokes the **default** `getDerivative2TargetDirection`, not only the abstract method, so
   the proxy must implement it too — mirroring how `_build_law_backed_provider`
   (`attitude.py:436-524`) had to implement the `AttitudeProvider` defaults. A proxy that
   implements only the abstract method fails with `UndeclaredThrowableException`.
2. **JPype overload collapse.** A single Python `getTargetDirection` serves **both** Java
   overloads, so it is called with a **field PV** (return `FieldVector3D`) *and* a **plain
   PV** (return `Vector3D`). Hand-dispatch on the argument type
   (`hasattr(pv, "toTimeStampedPVCoordinates")`) and return the matching type.
3. **Zero-derivative trick (defuses the Field math).** v1 zeroes attitude rates, so the
   Field overloads return a **constant** `FieldVector3D` built from the value direction
   (`field.getZero().add(...)`, or `UnivariateDerivative2(x, 0, 0)`) — no derivative
   calculus. The `FieldUnivariateDerivative2<T>` field-state overload is never hit by a
   double-precision `NumericalPropagator`, so skip it (mirrors `_build_law_backed_provider`
   skipping the Field `getAttitude`).

For `ω⊕ × r`, derive the Earth angular velocity from the inertial→ITRF `Transform` (transform
the PV to ITRF and re-express that velocity's direction back in EME2000) rather than a
hardcoded `ω = (0, 0, 7.292e-5)`; the hardcoded vector ignores the ~0.3° EME2000-pole-vs-
spin-axis offset (~0.02° of yaw — negligible, but the transform route is exact and barely
more code).

**Fallback (confirmed the *heavier* option, not lighter):** Orekit's native `NadirPointing`
wrapped in `YawCompensation` also runs, but it uses Orekit's own body convention (measured:
`+Z = nadir`, `+X = ground-relative velocity`, `+Y ≈ −momentum`) — a swap-and-flip from
propygator's `−Z`/`+Y`. Matching the contract needs a fixed body-frame rotation offset, and
Orekit has no native "rotate the body frame of a provider," so it would be wrapped in an
`AttitudeProvider` proxy *anyway*, on a **separate** code path from the inertial branch — i.e.
it trades the `TargetProvider` proxy for an `AttitudeProvider` proxy plus a convention
reconciliation. Keep the custom `TargetProvider` as primary; record `YawCompensation` as the
contingency only.

### 2.4 Verification

- **Yaw differs from inertial by the rotation term.** On a circular LEO box, propagate with
  `NadirPointing(velocity_reference="ecef")` and `="inertial"` and compare the body +Y
  direction (or the attitude rotation): the difference is the expected `ω⊕ × r` yaw —
  **a few degrees near the equator, →0 at the orbit's max-latitude turning point**. Pin the
  hand-checked equatorial value (≈ 3.08° for a 500 km / 51.6° circular orbit, measured
  2026-06-18; see §2.3).
- **Metadata unchanged:** `nadir_pointing:vel=ecef` still serializes; the `attitude` key is
  recorded only for a box with a wired surface force (unchanged gate).
- **Sphere path unaffected:** a non-default attitude on a sphere still emits the one-time
  consistency warning and falls back to `LofAligned` (`numerical._resolve_attitude`).
- **No regression:** the `inertial` branch and the other six modes are byte-identical.
- JVM-touching tests acquire the `orekit` fixture (architecture §11; the
  `pytest_collection_modifyitems` ordering hook).

---

## 3. Workstream B — direction-indicating endpoint glyphs

Today both spatial plots mark the trajectory **end** with a static glyph that conveys only
*where* the track ends (ground track: red star, `style.py` `MARKER_END`, marker `"*"`; 3-D:
red diamond, `trajectories.py:359-362`, `symbol="diamond"`). Neither conveys *which way the
satellite is going* there. Replacing the end glyph with a direction-indicating one lets a
reader pick prograde/retrograde and ascending/descending directly off the figure. The
**start** glyph (blue circle) stays a direction-less circle — a clean "this is t=0" anchor —
in both plots.

### 3.1 Ground track — heading-oriented triangle (matplotlib)

- Replace `MARKER_END`'s star with a **triangle rotated to the local heading** of the
  sub-satellite track. Apply via a rotated `matplotlib.markers.MarkerStyle`
  (`MarkerStyle("^").transformed(Affine2D().rotate_deg(heading_deg − 90))` — `"^"` points
  to +y = north = 90°, so the offset orients it along the heading; **verify the base-marker
  orientation at build** and pin the exact offset). `ax.scatter(..., marker=<MarkerStyle>)`
  accepts the rotated style; it remains a single scatter collection, so the existing
  `_scatter_collections(ax)` count of 2 and the offset-vs-geodetic-endpoint assertion
  (`test_trajectories.py:137-151`) stay green.
- **Heading.** Bearing of the **last non-dateline-wrapping** segment of the (lon, lat)
  track: `heading = atan2(Δlat, Δlon)` in degrees. This is exact on the plot because the
  map is equirectangular (plate carrée) with `aspect="equal"`, so one degree of longitude
  and latitude are isotropic on screen — no projection correction.
- **Dateline edge.** If the final segment wraps ±180°, fall back to the previous valid
  segment (reuse the keep-mask logic in `_dateline_segments`, `trajectories.py:101-116`).
  Degenerate short tracks (coincident last points): fall back to pointing north (no
  rotation).
- **`MARKER_END` restructuring (the rotation is data-dependent).** The triangle's rotation
  depends on each trajectory's end heading, so the glyph *shape* cannot live in the static
  module-level `MARKER_END` dict. Keep colour / size / edge / `zorder` / `label` in
  `MARKER_END`, **drop its `marker` key**, and build the rotated `MarkerStyle` inside
  `_draw_ground_track` (`ax.scatter(..., marker=<MarkerStyle>, **MARKER_END)` — dropping the
  key avoids a double-`marker` kwarg). Document the split: the glyph shape now lives in the
  draw function, the rest of the cosmetics stay in `style.py`.
- Keep the red colour and the existing visual weight; keep the `"end"` legend label.

### 3.2 3-D view — velocity-oriented cone (Plotly)

- Replace the diamond `_endpoint_marker(..., symbol="diamond")` (the `end` trace) with a
  `go.Cone` placed at the final sample and oriented along the **final velocity vector in the
  plot `frame`**, tip forward (`anchor` to be pinned so the cone *points* in the direction
  of motion).
- **Velocity source.** `plot_3d` currently converts only positions
  (`pos_km = traj.to_frame(frame).positions / 1000.0`, `trajectories.py:309`). Capture the
  converted trajectory **once** and read both `positions` and `velocities[-1]` from it
  (`to_frame` is JVM-crossing — do not convert twice). Use the velocity *direction* (the
  cone's length is controlled by sizing, not magnitude).
- **Single colour.** `go.Cone` colours by vector magnitude via a colorscale; force a
  constant red with a single-value colorscale + `showscale=False` — the same trick
  `_sphere_surface` already uses for the Earth globe (`trajectories.py:229`).
- **Scene-relative visual size (the Plotly constraint, empirically pinned 2026-06-18).**
  `go.Cone` has **no pixel sizemode** — under `sizemode="absolute"` its size is in *data
  units*, so a single hardcoded `sizeref` holds constant *data* size but *shrinking* visual
  weight as the orbit grows, and effectively vanishes on a GEO (~6×) or escape-guard partial
  (up to ~50×) scene. (A pixel-fixed *marker* is not an alternative: 3-D `Scatter3d` markers
  have no rotation and no triangle symbol — confirmed — which is *why* the end glyph must be a
  data-space cone.) So size it **relative to the scene**: `sizeref = k × (max position span)` —
  one scalar from the `pos_km` already computed, no per-sample work — so the cone holds
  constant *visual* weight on every orbit. Tune `k` (~4–6 % of the scene extent) at build to
  match the old diamond's weight and record it next to the other 3-D cosmetic constants.
- Keep the `"end"` legend entry. The start circle marker is unchanged.

### 3.3 Shared reconciliation

- **`plot_summary` inherits the triangle for free** — it draws the ground track through the
  shared `_draw_ground_track` primitive (`composite.py`), so the change has a single source.
- **Cosmetic-baseline edits:** update `MARKER_END` (and the `_MARKER_SIZE` comment about the
  star) in `style.py`; update the three docstrings that say "star"/"diamond"
  (`trajectories.py:131`, `:262`, `:302`).
- **Snapshot/structural tests to update:** `test_plot_3d.py:115-122` currently asserts
  `end.marker.symbol == "diamond"` — replace with "a `go.Cone` trace exists, positioned at
  the final sample and oriented along the final velocity, single red colour." `test_style.py`
  `test_endpoint_markers` (≈`:89-96`) asserts `MARKER_END["marker"] == "*"` — update it for the
  restructured `MARKER_END` (the `marker` key is gone; assert the retained colour / size / edge
  keys). Add a ground-track heading assertion (the triangle's rotation matches
  `atan2(Δlat, Δlon)` of the last valid segment). Re-record the image-bytes smokes — the ground
  track (`test_trajectories.py:243`) **and** the `plot_summary` composite (`test_composite.py`
  `test_summary_render_to_buffer_smoke`, which inherits the triangle via `_draw_ground_track`).
- **Backend rule respected:** matplotlib for the 2-D ground track, Plotly for the 3-D view
  (architecture §10) — no backend change.

---

## 4. What the end product looks like

**ECEF nadir yaw-steering (box, Earth-observation attitude):**

```python
import propygator as pgr
traj = pgr.propagate_numerical(
    leo_state, duration=86400.0, output_step=60.0,
    spacecraft=box_bus,                                  # non-spherical: attitude matters
    attitude=pgr.NadirPointing(velocity_reference="ecef"),
)
traj.metadata["attitude"]   # "nadir_pointing:vel=ecef"  (unchanged token)
# +Y now tracks the ground-relative velocity — a few degrees of yaw off the inertial mode.
```

**Direction glyphs (no API change — the figures just read better):**

```python
fig2d = pgr.plot_ground_track(traj)   # end marker: a triangle pointing along the track heading
fig3d = pgr.plot_3d(traj)             # end marker: a cone pointing along the velocity vector
```

---

## 5. Git: branch strategy (read once, before Chunk 1)

You've now done two feature branches (`feature/numerical-propagator`,
`feature/drag-validity-and-altitude-guards`); the full end-to-end walkthrough is in
`docs/history/build-plan-feature-1.1.md` ("Git: the feature-branch walkthrough") if you
want to re-read the rhythm.

**The wrinkle from last time is gone.** The previous addendum had to branch *off the
1.1 feature branch* because 1.1 wasn't merged. This time `main` is **clean and released**
(Feature 1.1 + the drag-validity addendum are merged and tagged `v0.1.0`), so you branch
straight from `main`:

```powershell
conda activate propygator
git switch main
git pull
git switch -c feature/ecef-nadir-and-direction-markers
git push -u origin feature/ecef-nadir-and-direction-markers
```

(Branch name is a suggestion — rename to taste; keep the `feature/` prefix to match the
prior two.) Because the two workstreams are independent and small, **one branch and one PR
covering both** is the natural choice; there's no need to split them.

**Per-chunk rhythm** is unchanged: `git status` → `git add -A` →
`git commit -m "addendum chunk N: <summary>"` → `git push` (CI runs on the branch).
**Commit/push, the CHANGELOG entry, the version bump, and PR/merge are yours** — Claude
won't push, write CHANGELOG narrative, bump the version, or open/merge a PR without you
asking.

At the wrap-up: `gh pr create` against `main`, confirm CI green, then
`gh pr merge --squash --delete-branch` — your call on timing.

**You provide (git):** confirm the branch name before Chunk 1; `gh` authenticated before the
wrap-up chunk.

---

## 6. Versioning — recommend a MINOR bump to `v0.2.0`

The repo single-sources the version in `pyproject.toml` (currently `0.1.0`) and adheres to
SemVer with a Keep-a-Changelog `CHANGELOG.md`. Weighing this addendum against the
Added/Changed/Fixed discipline:

- **Workstream A is net-new functionality, not a bug fix.** A configuration that previously
  raised `NotImplementedError` now produces a valid propagation — the textbook definition of
  a backward-compatible **feature addition** (an "Added" entry → **MINOR** under SemVer).
- **Workstream B is an intentional output change, not a fix.** The endpoint glyphs change on
  purpose (a "Changed" entry), reinforcing the minor-level signal.
- **Neither is a "Fixed."** A **PATCH** (`0.1.1`) is reserved for backward-compatible bug
  fixes; shipping new capability under a patch would mis-signal the release.

The fact that **no public signature or symbol changes** (workstream A completes an existing
option; no new top-level name in either) does *not* pull this down to a patch — a
behaviour-level feature addition is still a MINOR bump. And the project is on `0.x`, where
even larger changes are permitted in a minor release, so `0.2.0` is comfortably within
policy.

**Recommendation: bump to `v0.2.0`** with an `## [0.2.0]` CHANGELOG section carrying an
**Added** line (ECEF nadir yaw-steering) and a **Changed** line (direction-indicating plot
markers). The version bump and CHANGELOG wording are the maintainer's to author (per the
project's commit/CHANGELOG convention); this section only records the recommendation and
its rationale.

---

## 7. Decisions log

### Resolved by this add-on

- **ECEF nadir** = implemented via a custom `@JImplements(TargetProvider)` returning the
  Earth-relative velocity direction (`v_inertial − ω⊕ × r`) in the propagation frame, swapped
  into the existing `AlignedAndConstrained` secondary slot (primary −Z→NADIR unchanged).
  **Empirically confirmed working in a real `propagate()` (2026-06-18)**; the two JPype traps
  (default-method + overload collapse) and the zero-derivative trick are documented in §2.3.
  The native `NadirPointing`+`YawCompensation` route is the recorded fallback only, and was
  measured to be the heavier option. No signature, dataclass, or metadata change; the
  `nadir_pointing:vel=ecef` token is unchanged.
- **Ground-track end marker** = a triangle rotated to the local track heading
  (`atan2(Δlat, Δlon)` of the last non-wrapping segment; exact under plate carrée +
  `aspect="equal"`). Start marker stays a circle.
- **3-D end marker** = a `go.Cone` at the final sample oriented along the final velocity in
  the plot frame, **scene-relative** size (`sizemode="absolute"`, `sizeref = k × scene span`,
  §3.2), single red colour via a constant colorscale. Start marker stays a circle.
- **Bundling rationale** = the two workstreams are independent and small, share no code, and
  add no new public name; one branch / one PR.
- **Version** = recommend MINOR → `v0.2.0` (feature addition + intentional output change;
  not a patch). §6.

### Still open (build-time tuning only — the approaches are settled)

- **Cone `k` (scene-relative size factor) + `anchor`** — the sizing *policy* is resolved
  (scene-relative `sizeref = k × scene span`, §3.2); tune `k` (~4–6 %) and pin `anchor` so the
  cone points tip-forward, at build. Record next to the other 3-D constants.
- **Triangle base-marker rotation offset** — confirm `"^"` points north and pin the exact
  `rotate_deg` offset at build.

(The `TargetProvider` interface shape and the custom-proxy viability — previously open — are
now resolved empirically; see §2.3 and the `ecef-nadir-targetprovider-route` memory note.)

---

## 8. Definition of done

1. **ECEF nadir wired (§2):** `_to_provider` lowers `NadirPointing(velocity_reference="ecef")`
   to a working provider (custom `TargetProvider`, every propagator-invoked method incl. the
   Field overload implemented), verified inside a real box `propagate()`; the
   `_ECEF_DEFERRED_MESSAGE` raise is removed.
2. **ECEF verified (§2.4):** the ECEF-vs-inertial yaw equals the `ω⊕ × r` term (hand-checked
   equatorial value; →0 at max latitude); metadata token and the sphere consistency-warning
   path unchanged; the other six attitude modes regression-free.
3. **Ground-track triangle (§3.1):** end marker is a heading-oriented triangle; dateline and
   degenerate-track edges handled; `plot_summary` inherits it via `_draw_ground_track`.
4. **3-D cone (§3.2):** end marker is a velocity-oriented, **scene-relative-sized**,
   single-colour cone; the converted trajectory is reused (one `to_frame`); start circle
   unchanged.
5. **Cosmetic + test reconciliation (§3.3):** `style.py` (`MARKER_END` restructured) / docstring
   edits done; `test_plot_3d` cone assertion + `test_style` `MARKER_END` update + ground-track
   heading assertion added; the ground-track and `plot_summary` image smokes re-recorded;
   `pre-commit run --all-files` clean.
6. **Tests** JVM-touching paths acquire the `orekit` fixture (architecture §11).
7. **Supersession map (§1)** carried into the `features.md`/`architecture.md` reconciliation;
   `CHANGELOG.md` `[Unreleased]`/`[0.2.0]` entry + version bump authored by the maintainer (§6).
8. No new `NotImplementedError` introduced; the intended deferrals (Tier B `IncidenceVariableCd`,
   UT1, backward propagation) remain untouched.
