# Build plan: Feature 1.1 — Numerical propagator

## Context

Build stage 1 (groundwork) is complete: `propygator` is a scaffolded, installable,
tested package (198 tests passing) with the full pure-Python "safe-before-init"
core data model. Every Orekit-crossing method on that model currently raises
`NotImplementedError` with a "deferred to Feature 1" note, and the
`propagation/`, `plotting/`, `io/` subpackages are empty `__init__.py` stubs.

**This plan builds Feature 1.1, the numerical propagator** — the first and
hardest v1 feature and the foundation every later feature reuses (1.3 TLE
propagation reuses its `Trajectory`, plotting, and exporters wholesale). The end
state is a *usable* feature: a user can call `propagate_numerical(...)`, get a
`Trajectory`, convert/inspect it, and produce the full plot + CSV output surface,
exactly as shown in `docs/features.md` §1.1 "Typical user code."

**Source-of-truth docs (do not silently diverge):**
- `docs/features.md` §1.1 — the binding contract: every signature, preset,
  validation rule, metadata grammar, and output. This is the most important file
  for this build.
- `docs/architecture.md` — §6 (data-model conversions), §7 (module tree +
  dependency rule), §8 (1.1 data flow), §10 (lazy-JVM, explicit-frame, internal
  Orekit types), §11 (testing), §13 (deferred items).
- `docs/orekit_setup_reference.md` — JVM boilerplate + Java↔Python boundary
  patterns. **Self-flagged as possibly stale; verify against the installed
  13.1.x API before relying on any snippet** (constant spellings are compile-time
  errors if wrong).
- `docs/project_meta.md` §3 — the branching strategy this plan follows.

**Decisions locked with the user for this build:**
- **Git:** one feature branch `feature/numerical-propagator`, single PR into
  `main` at the end (GitHub Flow per project_meta §3). Detailed walkthrough below.
- **Output scope:** full — CSV export, all plots (summary, ground track, 3D,
  altitude, speed), `export_all`, and an intro notebook.
- **Variable drag:** Tier A `VariableCd` for **both sphere and box** (a
  density-varying scalar Cd keyed on geocentric radius + total density), with the
  shipped `sphere_default()` asset and a custom `DragSensitive`. Tier B
  `IncidenceVariableCd` ships as a *validated skeleton* (construction works) whose
  runtime path raises `NotImplementedError` — the documented faithful extension.

**Architecture invariants to honor in every chunk** (CLAUDE.md / architecture
§4, §10): Orekit types stay internal (public APIs accept/return only propygator
types; `to_orekit()` annotates the Orekit return only under `if TYPE_CHECKING:`);
import `jpype`/`orekit_jpype`/`pyhelpers` **lazily inside functions**, never at
module top; SI units internally; frames explicit (no auto-conversion on
`State`-returning paths); `pathlib.Path` everywhere; `logging`, never `print`;
frozen dataclasses with `__post_init__` validation for config types.

---

## How to use this plan

- **13 numbered chunks** — Chunk 11 (plotting) is split into five sub-chunks
  11a–11e — each (sub-)chunk sized for one Claude Code session and independently
  verifiable. Run them in order — later chunks depend on earlier ones.
- Each chunk lists **Goal / Create-Edit / Reuse / You provide / You run /
  Verify**. **You provide** is called out every chunk (often "nothing") so you
  always know whether a session needs input from you.
- **Checkpoints** (CLAUDE.md refresh + `/code-review` + `/simplify`) are marked
  inline after the chunks where they pay off. These are the moments to pause and
  consolidate before the next layer.
- Adjacent small chunks (4+5+6 configs; 7+8; or any two adjacent 11x sub-chunks)
  can be merged into one session if it still has capacity — they're split for
  safety, not because they must be separate.
- **New test subpackages:** `tests/` mirrors `src/` as packages (note the existing
  `tests/core/__init__.py`). The first chunk to touch a new area must create the
  matching `tests/<pkg>/__init__.py` — `tests/propagation/` (Chunk 4), `tests/io/`
  (Chunk 10), `tests/plotting/` (Chunk 11a) — or `pytest tests/<pkg>` collects
  nothing.

---

## Git: the feature-branch walkthrough (read once, before Chunk 1)

You've never used branches, so here is the whole workflow end-to-end. A **branch**
is just a movable label on a line of commits; `main` is one such label. Creating
`feature/numerical-propagator` lets you build all of Feature 1.1 on a parallel
line, keep `main` untouched until it's done, and then merge it in one reviewed
step. This matches `docs/project_meta.md` §3 (feature branches for substantive
work; PR for CI feedback + a written record; no branch protection; tag releases
on `main`).

**One-time, at the very start (do this before Chunk 1):**
```powershell
conda activate propygator
git checkout main
git pull                                  # make sure main is current
git switch -c feature/numerical-propagator   # create + switch to the branch
git push -u origin feature/numerical-propagator   # publish it; -u links local<->remote
```
`git switch -c` creates the branch from wherever `main` is now. After `-u`, a
plain `git push` always knows where to go.

**The per-chunk rhythm (repeat for every chunk):**
```powershell
git status                  # see what changed
git add -A                  # stage everything
git commit -m "Feature 1.1 chunk N: <short summary>"
git push                    # CI runs automatically on the branch
```
Commit at the end of each chunk (or more often). Every push triggers the GitHub
Actions run from build stage 1, so you get continuous CI feedback on the branch
without touching `main`. If you want to see where you are: `git log --oneline -10`
and `git branch` (the `*` marks your current branch).

**Sanity checks you'll want:**
- `git switch main` then `git switch feature/numerical-propagator` to hop between
  lines (commit or stash first; git refuses to switch with uncommitted changes
  that would be clobbered).
- `git diff main` shows everything Feature 1.1 has changed vs `main`.

**At the very end (Chunk 13), open and merge the PR:**
```powershell
gh pr create --base main --head feature/numerical-propagator `
  --title "Feature 1.1: numerical propagator" --body "..."
# review the PR on GitHub (CI must be green), then:
gh pr merge --squash --delete-branch
git switch main
git pull
git tag v0.2.0      # optional: tag the release on main (project_meta §3)
git push --tags
```
`--squash` collapses the chunk commits into one tidy commit on `main`;
`--delete-branch` cleans up the now-merged feature branch. If `gh` isn't
authenticated yet, run `gh auth login` once (or type `! gh auth login` in this
session so the output lands here).

**You provide (git):** confirm `gh` is installed + authenticated before Chunk 13
(today it's only needed at the end). Nothing else.

> If at any chunk you'd rather Claude drive git, say so and it will run the
> add/commit/push for that chunk — but it **will not push or open the PR without
> you asking** (per the repo's outward-action rule).

---

## Chunk 1 — Orekit bridge foundation: `Frame.to_orekit()` + `core/bodies.py` + `State.to_orekit()` - complete and Claude verified

**Goal:** the lowest JVM-crossing layer everything else stands on — resolve frames
and celestial bodies to Orekit, and turn a `State` into an Orekit object. This is
the first code that *uses* the lazy-JVM machinery beyond `Epoch.to_orekit()`.

**Create / edit:**
- `src/propygator/core/frames.py` — implement `Frame.to_orekit()` (replace the
  `_TO_OREKIT_DEFERRED` `NotImplementedError`). Pattern: `_ensure_started()`, then
  `from org.orekit.frames import FramesFactory` /
  `from org.orekit.utils import IERSConventions`; map `EME2000 →
  getEME2000()`, `ITRF → getITRF(IERSConventions.IERS_2010, True)`,
  `TEME → getTEME()`. Keep the signature/annotation exactly as the stub
  (`-> "org.orekit.frames.Frame"`).
- `src/propygator/core/bodies.py` (new; architecture §7) — the canonical Earth
  model (a `OneAxisEllipsoid` on WGS84 constants in ITRF) plus `Sun`/`Moon`
  accessors (`CelestialBodyFactory.getSun()/.getMoon()`), all behind
  `_ensure_started()`. These are needed by SRP, third-body, drag, and geodetic
  conversion. Expose module-level accessor functions returning the Orekit objects
  (internal use); do **not** leak Orekit types onto any public signature.
- `src/propygator/core/states.py` — implement `State.to_orekit()` (replace the
  `_FEATURE1_NOTE` body). Build `Vector3D` position/velocity → `PVCoordinates` →
  `AbsolutePVCoordinates`/`CartesianOrbit` at `self.epoch.to_orekit()` in
  `self.frame.to_orekit()`, returning the Orekit `SpacecraftState`. Decide and
  document the µ source (Earth GM from the gravity field / `Constants`). Keep the
  `if TYPE_CHECKING` annotation.
- **Tests** move to the `orekit` fixture (these now start the JVM): new
  `tests/test_conversions.py` (or `tests/core/`-adjacent JVM file) asserting the
  three frames resolve to the right Orekit class, Earth/Sun/Moon construct, and a
  `State.to_orekit()` round-trips position/velocity back via getters to within
  machine precision. **Remove the old pure-Python `tests/core/*` assertions that
  these raise `NotImplementedError`** (they'd now start the JVM and violate the
  safe-before-init invariant).

**Reuse:** `Epoch.to_orekit()` in `core/time.py` is the exact lazy-bootstrap
pattern (`_ensure_started()` then import). The `Vector3D`↔NumPy getter idiom is in
`docs/orekit_setup_reference.md` and the existing `tests/test_stack_compat.py`
part (a).

**You provide:** nothing. (Earth/Sun/Moon come from orekit-data.)

**You run:** the per-chunk git rhythm.

**Verify:** `pytest tests/test_conversions.py -v` green (JVM starts once via the
fixture); `pytest tests/core -v` still green and still JVM-free (assert
`not jpype.isJVMStarted()` survives in the pure-Python suite).

---

## Chunk 2 — State ↔ Keplerian + `State.to_frame()` - complete and Claude verified

**Goal:** the Cartesian↔Keplerian math and single-state frame conversion — the
conversions used by CSV element columns, `to_keplerian` inspection, and
`KeplerianElements.to_state` orbit construction.

**Create / edit:**
- `src/propygator/core/states.py` — implement `State.to_frame(target_frame)`
  (Orekit `Transform` between the two `to_orekit()` frames, applied to the PV;
  returns a new `State` with fresh read-only arrays, no view aliasing) and
  `State.to_keplerian()` (osculating `KeplerianOrbit` in the state's own frame →
  `KeplerianElements`, true-anomaly convention, SI).
- `src/propygator/core/elements.py` — implement `KeplerianElements.from_state()`,
  `to_state(epoch, frame)` (build `KeplerianOrbit` → `CartesianOrbit` → `State`),
  and `mean_anomaly()` / `eccentric_anomaly()` (replace the `_DEFERRED_NOTE`
  bodies; ν→M, ν→E via Orekit or closed form). Keep signatures identical.
- **Tests** in `tests/test_conversions.py` under the `orekit` fixture; retire the
  matching `NotImplementedError` assertions from `tests/core/test_states.py` /
  `test_elements.py`.

**Reuse:** Chunk 1's `Frame.to_orekit()` / `State.to_orekit()`. Architecture §6
pins the conventions (true anomaly stored; angles SI; classical elements computed
in the state's own frame; near-circular/near-equatorial ill-conditioning noted in
the docstring).

**You provide:** *optionally* a specific reference vector to pin against (e.g. a
Vallado COE↔RV example, edition/example number). If you don't, Claude will use a
standard Vallado example (e.g. Example 2-6) and a circular-LEO case — confirm at
review.

**Verify:** machine-precision round-trips `State → to_keplerian → to_state →`
back, and `State → to_frame(ITRF) → to_frame(EME2000)` ≈ identity; absolute check
against the chosen Vallado vector to textbook tolerance. `pytest tests/core -v`
still JVM-free and green.

---

## Chunk 3 — `Trajectory.to_frame()` + `Trajectory.at()` + `to_geodetic()` + `Orientation.to_orekit()` - complete and Claude verified

**Goal:** finish the *entire* deferred-method surface from the groundwork build —
the bulk-trajectory conversions, interpolation, geodetic lat/lon/alt, and the
attitude rotation bridge.

**Create / edit:**
- `src/propygator/core/states.py` — `Trajectory.to_frame(frame)` (vectorized
  per-sample transform; returns a new `Trajectory` with fresh read-only arrays and
  copied metadata) and `Trajectory.at(epoch)` (Orekit `Ephemeris` + Hermite
  interpolation, **cached on first call**, `ValueError` on out-of-bounds — no
  extrapolation; architecture §13). `Orientation.to_orekit()` → Hipparchus
  `Rotation` (lazy pattern; replace the `_FEATURE1_NOTE` body).
- `src/propygator/core/frames.py` — add `to_geodetic(state) -> GeodeticPosition`
  (architecture §7 places this in `frames.py`): **requires an Earth-fixed (ITRF)
  input state** — raise `ValueError` pointing at `state.to_frame(Frame.ITRF)` if
  given EME2000/TEME; **no silent auto-conversion** (architecture §6 carves
  `to_geodetic` out as strict; §10's "GeodeticPosition-returning functions may
  convert internally" latitude is reserved for the Feature 1.4
  `current_ground_position` wrapper, not this low-level function). Use the Earth
  ellipsoid from `core/bodies.py` to get geodetic lat/lon/alt (WGS84) from the ITRF
  state.
- After this chunk, retire the `_FEATURE1_NOTE` / `_DEFERRED_NOTE` /
  `_TO_OREKIT_DEFERRED` constants if nothing references them anymore.
- **Tests:** bulk `to_frame` on a hand-built `Trajectory`; `at()` interpolation
  accuracy at sample points (exact) and between (Hermite) + out-of-bounds raises;
  geodetic against a known lat/lon/alt (ITRF input) **and `to_geodetic` raising
  `ValueError` on an EME2000/TEME state**; `Orientation` round-trip. Move all to the
  `orekit` fixture and retire the corresponding `NotImplementedError` assertions.

**Reuse:** Chunks 1–2; the `Trajectory` already caches an `Ephemeris` slot
(`eq=False`, see its docstring) — wire `at()` into it.

**You provide:** nothing.

**Verify:** `pytest -v` full suite green; the deferred-method surface is gone —
grep the tree for `NotImplementedError` in `core/` and confirm only intended
(Tier B, UT1) remain.

> ### ✅ Checkpoint A — deferred conversions complete - Done
> 1. **Refresh `CLAUDE.md`**: the "Project state" section's list of methods that
>    "currently raise `NotImplementedError`" is now stale — update it to say the
>    Orekit-crossing conversions are implemented (Feature 1.1 in progress), and
>    move `Epoch.to_orekit` out of being "the one exception."
> 2. Run `/code-review` then `/simplify` on the branch diff so far (the
>    conversion layer is the foundation — get it clean before building on it).
> 3. Commit + push.

---

## Chunk 4 — Config: `propagation/force_models.py` + `propagation/integrators.py` - Complete and Claude verified

**Goal:** the two simplest config dataclasses — pure-Python, safe-before-init, no
JVM. Establishes the config+preset+validation pattern for Chunks 5–6.

**Create / edit:**
- `src/propygator/propagation/force_models.py` — `ForceModelConfig` frozen
  dataclass with all fields + defaults exactly per features.md §1.1 (gravity
  degree/order/field, sun/moon third body, drag + atmosphere_model, srp,
  solid/ocean tides, relativity) and the `leo_default()` / `geo_default()` /
  `keplerian()` classmethods matching the preset table. Store `gravity_field` /
  `atmosphere_model` as plain strings (validated later, at propagate time). Add the
  deterministic **`force_models` metadata grammar** serializer (fixed token order:
  `gravity:<field>:<deg>x<order>`, `third_body:sun`, `third_body:moon`,
  `drag:<atm>`, `srp`, `tides:solid`/`tides:ocean`, `relativity`).
- `src/propygator/propagation/integrators.py` — `IntegratorConfig` frozen
  dataclass + `default()` / `fast()` / `high_precision()` presets per the table.
- **Tests** (pure-Python, no JVM): preset values; the `force_models` serializer is
  byte-identical for a given config; field defaults.

**Reuse:** the existing frozen-dataclass + `__post_init__` validation idiom from
`core/` (e.g. `KeplerianElements`).

**You provide:** nothing (presets are fully specified in features.md).

**Verify:** `pytest tests/propagation -v` green; confirm constructing these does
**not** start the JVM.

---

## Chunk 5 — Config: `propagation/spacecraft.py` + `VariableCd` (Tier A) + `sphere_default` asset - Complete and Claude verified

**Goal:** the spacecraft geometry/coefficients config and the variable-Cd table
machinery — all pure-Python and safe-before-init (the custom `DragSensitive` that
*uses* a `VariableCd` is built later, inside `propagate_numerical`).

**Create / edit:**
- `src/propygator/propagation/spacecraft.py` (new) —
  - `SpacecraftConfig(mass_kg=1000.0, geometry=SpacecraftGeometry.sphere(area_m2=1.0))`
    frozen dataclass.
  - `SpacecraftGeometry` with the `sphere(area_m2, *, drag_coefficient=2.2,
    reflectivity_coefficient=1.5)` and `box_and_panels(...)` factories, **the full
    validation table** from features.md (mass>0, area>0, dims>0, Cd≥0,
    absorption/specular each in [0,1] and sum ≤1, solar-array axis finite/nonzero
    normalized silently, sphere given `IncidenceVariableCd` → `ValueError`, Cd>5 /
    Cr>3 warn-not-raise).
  - The deterministic **`spacecraft` metadata string** serializer (`repr()`-based
    numbers; `sphere:A=...;m=...,Cd=...,Cr=...` and `box:...;m=...,Cd=...,abs=...,spec=...`;
    `Cd=table:<name-or-hash>` for a table).
- `VariableCd` (Tier A — **sphere and box**): `from_table(grid, *, radius_axis,
  density_axis)`, `from_callable(fn)`, `sphere_default()`. Pure-Python table with
  per-axis **clamp-to-edge + one-time warning** out-of-grid, and a content hash
  (axis set included) for metadata. `IncidenceVariableCd.from_table(...)` ships as
  a **validated skeleton** (construction + validation work; it's accepted only by
  `box_and_panels`) — its runtime use is deferred (Tier B).
- `scripts/generate_sphere_cd_table.py` + the committed asset in `data/` —
  generate `sphere_default` by sweeping a closed-form Sentman sphere Cd over a
  `(geocentric radius, total density)` grid and regridding (features.md "Where the
  table comes from"). Commit the small array to `data/`; `sphere_default()` loads it.
- **Tests** (pure-Python): every validation branch; `VariableCd` interpolation at
  grid points (exact) and clamping past edges (warns once); the metadata strings
  are deterministic; `IncidenceVariableCd` constructs but is rejected by `sphere`.

**Reuse:** Chunk 4's serializer/validation pattern.

**You provide:** confirm (or adjust) the `sphere_default` grid extents — proposed
radius span ≈ 6,500–7,500 km (≈ 150–1,200 km altitude) and total-density span
covering solar min↔max at those altitudes. Claude will propose concrete bounds in
the PR; you sign off.

**Verify:** `pytest tests/propagation -v` green and JVM-free; `python
scripts/generate_sphere_cd_table.py --help` runs; `VariableCd.sphere_default()`
loads the committed asset.

**Reference (background evidence — *not* a dependency):** the `(radius, density)`
collapse assumption this table rests on was de-risked in
`experiments/drag-coefficient-verification/` (see its `README.md`). Treat it as
supporting evidence only:
- It is a **good reference** for *why* a `(radius, density)` Cd table is sound — its
  Tier A run shows the sphere Cd collapses onto one `(alt, ρ)` surface to ≈ 0.34 %
  RMS across genuinely different epochs (season, local solar time, latitude, F10.7,
  Ap), an order of magnitude under the 15–30 % thermospheric density uncertainty.
- It is **not a source of truth.** The Cd model there is an independent
  reconstruction / stand-in, not propygator's implementation; do not treat its
  formulas or numbers as authoritative for this chunk.
- **Do not import from `experiments/`.** It is reference-only, lives outside the
  package, and is excluded from CI/lint. Reconstruct everything
  `generate_sphere_cd_table.py` needs from scratch against features.md, using
  propygator's own Sentman Cd.
- **Mind two gaps it does not cover:** it keys on *geodetic altitude*, whereas this
  table keys on *geocentric radius*; and it spans only 300–800 km, while the proposed
  grid runs ≈ 150–1,200 km — the fast-changing low end is unverified there, so don't
  read the experiment as validating those extremes.

---

## Chunk 6 — Config: `propagation/attitude.py` (seven modes + provider lowering) - Complete and Claude verified

**Goal:** the `AttitudeConfig` family — the seven frozen dataclasses (pure-Python
construction/validation) plus the internal "lower to a native Orekit attitude
provider" builder (JVM-touching, tested under the fixture).

**Create / edit:**
- `src/propygator/propagation/attitude.py` — `LofAligned`, `LofOffset`,
  `Inertial`, `SunPointing`, `NadirPointing`, `InPlaneTracking`, `CustomAttitude`
  exactly per features.md, with their validation (Inertial frame must be inertial;
  SunPointing pointing∦phasing; CustomAttitude.law callable; angles finite; axes
  normalized). The `AttitudeConfig` union alias.
- The deterministic **`attitude` metadata string** serializer (`lof_aligned:TNW`,
  `lof_offset:TNW;roll=...`, `inertial:EME2000;...`, `sun_pointing:...`,
  `nadir_pointing:vel=...`, `in_plane_tracking`, `custom:<law name>`).
- An internal `_to_provider(config, ...)` that maps each mode to its Orekit
  provider (`LofOffset(TNW)`, `FrameAlignedProvider`, `CelestialBodyPointed` /
  `AlignedAndConstrained`, user-backed provider for `CustomAttitude` via
  `Orientation.to_orekit()`), behind `_ensure_started()`. **Verify the
  `PredefinedTarget.SUN/VELOCITY/MOMENTUM` and `LOFType.TNW` literal spellings
  against the installed 13.1.x javadoc** — a wrong constant is a runtime
  `AttributeError`/Java error (features.md flags this explicitly).

> **⚠️ Rotation-direction caveat (read before wiring `CustomAttitude`).**
> `Orientation` stores the **active** rotation quaternion `(cos θ/2, sin θ/2·k̂)`,
> but Hipparchus builds its `Rotation` from that quaternion in the **FRAME_TRANSFORM
> (passive)** sense, so `Orientation.to_orekit().applyTo(v)` is the **inverse** of
> the active body rotation the quaternion denotes, and `applyInverseTo(v)`
> reproduces it. Concretely (verified, and pinned by
> `test_orientation_to_orekit_rotation_direction_is_pinned` in
> `tests/test_conversions.py`): for `from_axis_angle((0,0,1), +90°)`,
> `applyTo(+X) = −Y` while `applyInverseTo(+X) = +Y`. Orekit's `Attitude` rotation
> is itself defined reference(inertial)→spacecraft(body) in the same frame-transform
> sense, so the two conventions may already line up — **do not assume**: build a
> user-backed provider, assert a known body vector lands where expected in inertial
> space against a hand-checked case, and only then trust it. If this forces a change
> to `Orientation.to_orekit` (e.g. an `applyInverseTo`, a quaternion conjugate, or
> the `RotationConvention` arg), **update the characterization test in the same
> commit** so the pinned direction stays the source of truth.

- **Tests:** pure-Python for construction/validation/metadata strings; a small set
  under the `orekit` fixture asserting each mode builds a non-null provider.
  Include the body→inertial direction check described in the caveat above (the
  first real consumer of `Orientation.to_orekit`, which the Chunk-3 characterization
  test deliberately left to this chunk).

**Reuse:** `Orientation.to_orekit()` (Chunk 3) for `CustomAttitude`; the bodies
accessors (Chunk 1) for Sun-relative modes.

**You provide:** nothing.

**Verify:** `pytest tests/propagation -v` green; pure-Python construction is
JVM-free; provider-building tests pass under the fixture.

---

## Chunk 7 — Propagator core: `propagation/numerical.py` (integrator + gravity → `Trajectory`) - Complete and Claude verified

**Goal:** a working `propagate_numerical` for the gravity-only case — integrator
selection, gravity force, output-step ephemeris sampling, `Trajectory` + metadata
assembly, input validation, and `PropagationError`. This is the heart of the
feature; perturbations and non-spherical geometry layer on in 8–9.

**Create / edit:**
- `src/propygator/core/exceptions.py` — add `PropagationError` (carries the Java
  message as a string; no raw stack trace — same principle as
  `OrekitDataMissingError`).
- `src/propygator/propagation/numerical.py` — `propagate_numerical(initial,
  duration, *, output_step, force_models=None, spacecraft=None, attitude=None,
  integrator=None, name=None) -> Trajectory` with the **exact signature** from
  features.md. This chunk implements:
  - **Input validation at the top** (before integration): inertial-frame check
    (ITRF/TEME → `ValueError` pointing at `to_frame(EME2000)`); `duration>0`,
    `output_step>0`, `output_step≤duration`; resolve `integrator.type` and
    `gravity_field` strings (`ValueError` + known-name list on miss). `None`
    sentinels substituted with default instances inside the body.
    **`ClassicalRK4` requires `IntegratorConfig.fixed_step_s` (else `ValueError`)** —
    this type-dependent coupling is validated *here*, not at `IntegratorConfig`
    construction: Chunk 4 deliberately keeps construction type-agnostic (it only
    checks `fixed_step_s` is finite/positive *when supplied*), leaving every
    `type`-dependent check at this single propagate-time locus alongside the
    `integrator.type` name resolution.
  - Build the integrator (DOP853 / DormandPrince54 / ClassicalRK4) with tolerances
    via `OrbitType.CARTESIAN` tolerance computation; `min/max_step` bounds;
    `min_step` saturation → end-of-run warning.
  - Build a `NumericalPropagator` with the gravity force only this chunk
    (point-mass for `keplerian`; `HolmesFeatherstoneAttractionModel` /
    `GravityFieldFactory.getNormalizedProvider(deg, order)` otherwise), default
    `LofAligned` attitude provider, sphere `SpacecraftState`.
  - **Ephemeris sampling** at exactly `output_step` (generated ephemeris or step
    handler) with sample count `floor(duration/output_step + tol) + 1`, first
    sample at `initial.epoch`. Assemble the `Trajectory` (EME2000 output) with the
    full metadata dict (`propygator_version`, `orekit_version`,
    `propagator:"numerical"`, `integrator`, `integrator_tolerances`,
    `output_step_s`, `created_at`, optional `name`, and a `force_models` list that
    reflects **only the forces actually wired this chunk** — gravity alone (point
    mass for `keplerian`). Emit no drag/SRP/third-body/tides tokens until Chunk 8
    applies them, so the metadata never claims a force that isn't acting; drive the
    serializer from what was added to the propagator, not from the config booleans.
  - Wrap convergence/unknown Orekit failures in `PropagationError`.
  - INFO log at start (config summary) + end (sample count, wall time).
- **Re-export** `propagate_numerical` from `propagation/__init__.py` (top-level
  re-export deferred to Chunk 12).
- **`tests/test_stack_compat.py` part (b)** — the numerical forward/backward
  Keplerian round-trip at machine precision (10⁻⁸ relative) now lands; remove the
  `# TODO(1.1)` marker.
- **Tests:** sample-count correctness (divisible + non-divisible `duration`);
  frame/duration/output_step validation errors; `keplerian` preset vs analytical
  two-body to machine precision; a full-gravity LEO sanity check (bounded energy /
  altitude); integrator presets run; **`force_models` metadata lists only the wired
  forces** — assert a `leo_default` run this chunk still emits just the gravity
  token (no drag/SRP/third-body yet), and `keplerian` emits `["gravity:...:0x0"]`.

**Reuse:** all conversions (Chunks 1–3), `ForceModelConfig`/`IntegratorConfig`
(Chunk 4), `Trajectory.from_arrays` and `TrajectoryMetadata` (groundwork).

**You provide:** *optionally* a reference initial state (Vallado/ISS) to anchor the
LEO sanity test; otherwise Claude uses a standard one — confirm at review.

**Verify:** `pytest tests/test_stack_compat.py -v` green (part b passes); the
gravity-only `propagate_numerical` returns a correctly-shaped EME2000 `Trajectory`;
Keplerian round-trip at machine precision.

---

## Chunk 8 — Perturbations on a sphere: third-body, drag (+`VariableCd`), SRP, tides, relativity - Complete and Claude verified

**Goal:** the full force-model toggles acting on the default sphere spacecraft —
the physics that makes the propagator real.

**Create / edit:**
- `src/propygator/propagation/numerical.py` — extend force-model assembly from the
  `ForceModelConfig` booleans:
  - **Third body** — Sun/Moon via `ThirdBodyAttraction` (bodies from Chunk 1).
  - **Drag** — atmosphere model resolution (`NRLMSISE-00` | `Harris-Priester` |
    `DTM-2000`; `ValueError` + known-name list on miss), `IsotropicDrag` for the
    sphere; **the custom `@JImplements` `DragSensitive`** for a `VariableCd`
    (reads geocentric radius from state + passed-in total density, interpolates Cd,
    assembles the drag deceleration), **instantiated inside `propagate_numerical`**
    (keeps the geometry factory safe-before-init). **Sign convention (verified):**
    Orekit passes `relativeVelocity = v_atm − v_sc`, so the faithful form is
    `a = +½ (Cd·A/m) ρ |relVel| relVel` — the `−½` written in features.md assumes
    the opposite `v_rel = v_sc − v_atm`; both denote the same deceleration. See the
    features.md §1.1 "Drag-coefficient modeling → Runtime" implementation note.
  - **SRP** — `SolarRadiationPressure` with the **conical** shadow on the WGS84
    ellipsoid. The single-`Cr` sphere maps to `IsotropicRadiationSingleCoefficient`
    (area, Cr) — **not** `IsotropicRadiationClassicalConvention`, which takes two
    coefficients (area, ca, cs) and can't represent a single Cr (verified; see the
    features.md §1.1 sphere implementation note).
  - **Solid/ocean tides, relativity** — the corresponding Orekit force models.
  - Emit the full deterministic `force_models` metadata list; update the
    `spacecraft` metadata key.
- **Tests:** LEO-with-drag shows secular altitude decay; `geo_default` preset runs
  and is gravity/SRP-dominated; `force_models` metadata grammar is byte-exact for
  representative configs; a `VariableCd` sphere run differs from fixed-Cd as
  expected and clamps out-of-grid with one warning; bad atmosphere/gravity strings
  raise `ValueError`.

**Reuse:** the `DragSensitive` interface note in CLAUDE.md (implement Java
interfaces via `@JImplements`/`@JOverride`; can't subclass Java classes);
`VariableCd` (Chunk 5).

**You provide:** nothing.

**Verify:** `pytest tests/propagation -v` green; a 1-day LEO propagation with
`leo_default` completes and shows physically reasonable drag decay.

> ### ✅ Checkpoint B — propagator physics - Done
> Run `/code-review` then `/simplify` on the diff (the force-model assembly is
> dense and easy to get subtly wrong). Commit + push.

---

## Chunk 9 — Box geometry + attitude wiring - Complete and Claude verified

**Goal:** non-spherical spacecraft and the full attitude family — the last piece of
the propagator. After this, `propagate_numerical` is feature-complete.

**Create / edit:**
- `src/propygator/propagation/numerical.py` — when geometry is `box_and_panels`,
  build `BoxAndSolarArraySpacecraft` (dimensions, solar-array area/axis, absorption
  + specular) driving **both** drag and SRP; wire the `AttitudeConfig` →
  `_to_provider()` (Chunk 6) into the propagator; route a box `VariableCd` through
  the same custom `DragSensitive` (Orekit still computes projected area from
  attitude; the table supplies the scalar Cd — Tier A). Emit the
  **attitude/geometry consistency warning** (non-default attitude + sphere →
  one-time warn, proceed). `IncidenceVariableCd` on a box → `NotImplementedError`
  (Tier B deferred) with a clear message.
- **Tests:** box + `InPlaneTracking` completes and its drag cross-section behaves
  vs `LofAligned`; each attitude mode runs end-to-end; attitude metadata strings
  are byte-exact; sphere + non-default attitude emits exactly one warning;
  `IncidenceVariableCd` runtime raises the deferred error.

**Reuse:** `attitude.py` (Chunk 6), `spacecraft.py` (Chunk 5).

**You provide:** nothing.

**Verify:** `pytest tests/propagation -v` green; the features.md "box bus,
in-plane tracking" and "solar sail, rolled 30°" examples run to a `Trajectory`.

**As-built decisions (recorded — they refine, not contradict, the contract):**
- **`BoxAndSolarArraySpacecraft` wiring (verified against installed 13.1.x).** The
  10-arg ctor `(x, y, z, sun, arrayArea, arrayAxis, dragCoeff, liftRatio, absorption,
  specular)` builds one object that drives both drag (`DragForce(atm, box)`) and SRP
  (`SolarRadiationPressure(sun, earth, box)`); `liftRatio=0.0` (v1 models no lift).
  A box `VariableCd` is routed by a custom `@JImplements DragSensitive` that
  delegates to `box.dragAcceleration` with the table Cd as the box's single
  **"global drag factor"** driver: the box is built with base `dragCoeff=1.0` and
  drag is **exactly linear** in that factor (verified to ~1e-21), so the effective Cd
  equals the table value while Orekit still computes the attitude-driven projected
  area. (This is "the same custom `DragSensitive`" of the plan in spirit — a thin
  delegating sensitive — not literally the sphere's isotropic one.)
- **`attitude` metadata gate.** The optional `attitude` key is emitted exactly when
  geometry is a **box AND** drag or SRP was wired — the same "reflect what's acting"
  gate as the `spacecraft` key (Chunk 8). Attitude affects the result only through a
  non-spherical cross-section under a surface force, so a sphere (any forces) or a
  force-free box leaves it dynamically inert and omits the key.
- **Example-test cost (deviation from a literal reading of Verify).** The two
  features.md box examples are exercised at **reduced duration (~2 orbits)** rather
  than the documented 1-day / 7-day spans: the short run hits every chunk-9 code
  path identically (box drag/SRP, the `VariableCd` routing, attitude wiring,
  metadata), and the literal full-duration snippets are run verbatim end-to-end in
  Chunk 12. This keeps the propagation suite fast (the 7-day 70×70+drag+SRP+box run
  would otherwise be the single most expensive test in the repo).

> ### ✅ Checkpoint C — propagator complete - Done
> 1. **Refresh `CLAUDE.md`**: `propagate_numerical` and all configs now exist —
>    update "Project state" (Feature 1.1 propagation core done; outputs next) and
>    the module-status notes (`propagation/` no longer an empty stub).
> 2. `/code-review` + `/simplify` on the full propagator.
> 3. Commit + push.

---

## Chunk 10 — CSV export: `io/exports.py::export_csv` - Complete and Claude verified

**Goal:** the tabular output — the 16 default columns, opt-in columns, and metadata
header. Completes stack-compat part (c).

**Create / edit:**
- `src/propygator/io/exports.py` — `export_csv(traj, path, *, columns=None)`:
  the 16 default columns (`epoch_utc`, `epoch_mjd_utc`, `x/y/z_eme2000_m`,
  `vx/vy/vz_eme2000_mps`, `x/y/z_itrf_m`, `latitude_deg`/`longitude_deg`/
  `altitude_m`, `speed_inertial_mps`, `speed_itrf_mps`) computed via
  `Trajectory.to_frame(ITRF)` and `to_geodetic`; `columns` is **additive** — opt-in
  group tokens (`"keplerian"`, `"sun"`) appended to the defaults in a fixed
  canonical order. Keplerian (a,e,i,Ω,ω,ν) **computed in EME2000**, Sun position +
  unit sat→Sun direction (Sun from `core/bodies.py`); `TrajectoryMetadata` written
  as `# key: value` header comments. No eclipse flag (would break the io→core-only
  dependency rule, architecture §7).

  > As-built (chunk 10): the original draft's "16" enumerated only 15 columns;
  > `speed_itrf_mps` (ground-relative speed magnitude, the intended complement to
  > `speed_inertial_mps`) was added as the 16th, confirmed with the user. `columns`
  > is the additive-group-token design (not an explicit column list), so the leading
  > 16-column schema is always stable.
- **`tests/test_stack_compat.py` part (c)** — bulk `Trajectory` (~10⁵ samples)
  `to_frame` + CSV export/reload + dtype comparison; remove the `# TODO(1.1)`
  marker.
- **Tests:** exact column names/order; round-trip read matches; metadata header
  present and parseable; opt-in columns appear when requested.

**Reuse:** `Trajectory.to_dataframe` (groundwork), Chunk 3 conversions.

**You provide:** nothing.

**Verify:** `pytest tests/test_stack_compat.py tests/io -v` green (part c passes);
a CSV opens with correct headers and a metadata comment block.

---

## Chunk 11 — Plotting (split into 11a–11e) - Complete and verified

The full plotting surface is split into five session-sized sub-chunks. The
**decision gates (coastline source + locked cosmetics) are front-loaded into 11a**
so they never block a build mid-session, and the styling baseline is fixed before
any snapshot is recorded. The `_draw_*(ax, traj, ...)` primitive signature is
pinned in 11b/11c so the 11d composite can compose them (matplotlib can't move axes
between figures — features.md "Outputs"). Do 11a → 11e in order; any two adjacent
sub-chunks can be merged into one session if it still has capacity. All sub-chunk
tests are headless (`matplotlib.use("Agg")`). Create `tests/plotting/__init__.py`
in 11a (first chunk to touch this area).

### Chunk 11a — Styling baseline + Earth basemap asset  ← decision gate

**Goal:** the locked visual baseline and the shared map machinery everything else
draws on. Nothing renders a trajectory yet — this fixes the cosmetics and the asset
so the 11b–11e snapshots are stable the first time they're recorded.

**Create / edit:**
- `src/propygator/plotting/propygator.mplstyle` — the matplotlib style, applied
  **per-figure via a context manager** (never mutate global `rcParams` on import);
  the analogous Plotly shared layout template. Locks: blue→red time colormap
  (ground track / 3D), dark-blue time-series line, black outlines.
- `src/propygator/plotting/` `_render_earth_basemap()` — draws the bundled Natural
  Earth coastline as a **black `LineCollection`** onto a supplied `Axes`; the same
  coastline is reused to drape the 3D ITRF sphere in 11e.
- `data/` — the committed low-res Natural Earth coastline asset (no cartopy).
- **Tests:** the context manager applies/reverts per-figure (global `rcParams`
  unchanged after a `plot_*` call); `_render_earth_basemap()` draws a non-empty
  black coastline headless. (No trajectory snapshots yet.)

**Reuse:** nothing new — this is the foundation 11b–11e build on.

**You provide:** **decisions needed, resolved here so later sub-chunks aren't
blocked.** (1) Approve the bundled coastline source — Claude proposes Natural Earth
1:110m (public domain), reduced and committed to `data/`; you OK adding the asset.
(2) Sign off the locked cosmetics: dark-blue hex, blue→red colormap endpoints,
default figure sizes, axis labels, legend placement (features.md defers these to
implementation). Snapshots are only stable once these are fixed.

**Verify:** `pytest tests/plotting -v` green headless; styling is per-figure (no
global `rcParams` mutation); the basemap renders a coastline.

### Chunk 11b — matplotlib timeseries (`plot_altitude`, `plot_speed`)

**Goal:** the two simplest plots and the `_draw_*(ax, ...)` primitive pattern the
composite later reuses.

**Create / edit:**
- `src/propygator/plotting/timeseries.py` — `_draw_altitude(ax, traj)` and
  `_draw_speed(ax, traj, *, frame)` drawing onto a **supplied `Axes`**; thin public
  `plot_altitude(traj)` and `plot_speed(traj, *, frames=(EME2000,))` wrappers (one
  dark-blue speed-*magnitude* panel per frame; inertial vs ITRF ground-relative per
  features.md). **Pin the primitive signature — 11d depends on it.**
- **Snapshot tests** + a structural assertion (panel count tracks `frames`).

**Reuse:** 11a styling; `Trajectory.to_frame` (ITRF speed); altitude via Chunk 3
`to_geodetic` on ITRF states (per the geodetic-altitude convention).

**Verify:** `pytest tests/plotting -v` green; `plot_altitude` / `plot_speed` return
matplotlib figures; snapshots recorded and matching.

### Chunk 11c — matplotlib ground track (`plot_ground_track`)

**Goal:** the 2D map plot and its geodetic plumbing.

**Create / edit:**
- `src/propygator/plotting/trajectories.py` — `_draw_ground_track(ax, traj, *,
  show_map_overlay=True, color_by_time=True)`: **convert to ITRF first**
  (`Trajectory.to_frame(ITRF)`), then `to_geodetic` per sample for lat/lon —
  honoring `to_geodetic`'s strict ITRF-input contract from Chunk 3 (no
  auto-conversion); blue→red `LineCollection`; optional `_render_earth_basemap()`
  overlay. Thin public `plot_ground_track(traj, *, show_map_overlay=True,
  color_by_time=True)`.
- **Snapshot tests** (with and without the map overlay).

**Reuse:** 11a basemap; Chunk 3 `to_geodetic` (strict ITRF) + `Trajectory.to_frame`.

**Verify:** `pytest tests/plotting -v` green; ground track renders the coastline
overlay; snapshots match.

### Chunk 11d — composite `plot_summary` (GridSpec)

**Goal:** the default visual — one stacked figure composing the 11b/11c primitives.

**Create / edit:**
- `src/propygator/plotting/composite.py` — `plot_summary(traj, *,
  speed_frames=(EME2000,), show_map_overlay=True)`: a `GridSpec` figure (ground
  track spanning the top row at a larger height weight, altitude beneath, one speed
  panel per `speed_frames`; the time-series rows share the x-axis), calling the same
  `_draw_*` primitives onto its own axes.
- **Tests:** structural assertions on the panel layout (row count tracks
  `speed_frames`; shared x-axis) + a snapshot.

**Reuse:** 11b/11c `_draw_*` primitives unchanged; 11a styling.

**Verify:** `pytest tests/plotting -v` green; `plot_summary` returns one composed
matplotlib figure; the layout snapshot matches.

### Chunk 11e — Plotly `plot_3d`

**Goal:** the only interactive output — the 3D view, inertial and ITRF.

**Create / edit:**
- `src/propygator/plotting/trajectories.py` — `plot_3d(traj, *, frame=EME2000,
  show_earth=True, show_map_overlay=False, color_by_time=True)` (Plotly): blue→red
  time-colored trace; the ITRF view drapes the 11a coastline on the Earth sphere;
  the inertial view holds the orbit still as Earth rotates beneath (features.md "Map
  machinery"). Apply the 11a Plotly layout template.
- **Tests:** structural assertions on the Plotly figure (trace types, Earth toggle)
  + a snapshot where practical.

**Reuse:** 11a Plotly template + basemap coastline; `Trajectory.to_frame`.

**Verify:** `pytest tests/plotting -v` green; `plot_3d` returns a
`plotly.graph_objects.Figure`; the ITRF / inertial variants render.

---

## Chunk 12 — `export_all` + top-level re-exports + README / notebook / CHANGELOG - Complete and Claude verified

**Goal:** assemble the convenience entry points and the public surface, then prove
the end-to-end "typical user code" runs.

**Create / edit:**
- `src/propygator/io/exports.py` — `export_all(traj, output_dir, *, summary=True,
  plot_3d=True, csv=True, show_map_overlay=True, speed_frames=(EME2000,),
  frames_3d=(EME2000,), csv_columns=None, filename_prefix="trajectory") ->
  dict[str, Path]` per features.md (booleans, `Sequence[Frame]` tuple defaults,
  frame-suffixed 3D files when both inertial+ITRF requested).
- `src/propygator/__init__.py` — re-export the full Feature 1.1 surface
  (architecture §7 list): `propagate_numerical`, `ForceModelConfig`,
  `SpacecraftConfig`, `SpacecraftGeometry`, `VariableCd`, `IntegratorConfig`, the
  attitude family, `plot_*`, `export_csv`, `export_all`. Keep imports lazy enough
  that `import propygator` stays JVM-free (verify).
- `README.md` quick-example refresh; `notebooks/02_numerical_propagation.ipynb`
  (nbstripout-clean); `CHANGELOG.md` `[Unreleased]` populated (Keep-a-Changelog).
- **Tests:** the three features.md §1.1 examples run to outputs; `export_all`
  returns the right path dict and writes the files; `import propygator as pgr`
  exposes every new name and does not start the JVM.

**Reuse:** Chunks 10–11 (export/plot building blocks).

**You provide:** nothing (README/notebook content Claude drafts; you review).

**Verify:** `python -c "import propygator, jpype; print(jpype.isJVMStarted())"` →
`False`; the simple example (`propagate_numerical` → `export_all`) writes
`trajectory_summary.png` / `trajectory.csv` etc.; `pytest -v` full suite green.

---

## Chunk 13 — Feature wrap-up: full sweep, review, docs, merge - Code review complete, merge deferred in favor of additional builds

**Goal:** land Feature 1.1 on `main`.

**Create / edit / run:**
- Full local CI parity: `pytest` and `pre-commit run --all-files` both green from
  repo root.
- `/code-review` + `/simplify` final pass across the whole feature diff (`git diff
  main`); address findings.
- **Refresh `CLAUDE.md`** "Project state" to: Feature 1.1 complete; next feature is
  1.3 (TLE propagator) per architecture §12; update the module-status notes
  (`propagation/`, `plotting/`, `io/` are implemented; the deferred-method list is
  retired).
- Finalize `CHANGELOG.md` (move `[Unreleased]` → `[v0.1.0] - YYYY-MM-DD` if
  tagging).
- **Open and merge the PR** (git walkthrough above): `gh pr create …`, confirm CI
  green on the PR, `gh pr merge --squash --delete-branch`, `git switch main && git
  pull`, optional `git tag v0.2.0 && git push --tags`.

**You provide:** confirm `gh` is authenticated; decide whether to tag `v0.2.0`;
final approval to merge into `main` (an outward action — Claude won't push/merge
without your explicit go-ahead).

**Verify:** `main` contains Feature 1.1 with green CI; `import propygator as pgr;
pgr.propagate_numerical(...)` works on a fresh `main` checkout.

> ### ✅ Final checkpoint — feature done
> CLAUDE.md, CHANGELOG, and the architecture §12 build order all reflect that 1.1
> is done and 1.3 is next.

---

## End-state verification (Feature 1.1 complete → usable) - Done

From repo root, `conda activate propygator`, on `main` after merge:
1. `python -c "import propygator, jpype; print(jpype.isJVMStarted())"` → `False`
   (import stays JVM-free).
2. The features.md §1.1 simple example runs: `propagate_numerical(initial,
   duration=86400, output_step=60)` → a 1441-sample EME2000 `Trajectory`;
   `export_all(...)` writes summary PNG + 3D HTML + CSV.
3. `Trajectory` conversions all work: `.to_frame(ITRF)`, `.at(epoch)`,
   `to_keplerian()` round-trips, `to_geodetic`.
4. `pytest -v` → all core + propagation + io + plotting + stack-compat (a, b, c)
   green.
5. `pre-commit run --all-files` → clean.
6. No `NotImplementedError` remains in the tree except the intended deferrals
   (Tier B `IncidenceVariableCd` runtime, UT1).

At that point Feature 1.3 (TLE propagator) starts — it reuses 1.1's `Trajectory`,
plotting, and exporters wholesale (architecture §12, features §1.3).

## Notes / deferred (not Feature 1.1)

- **Tier B `IncidenceVariableCd`** runtime (incidence-keyed box drag) — ships as a
  validated skeleton; runtime raises `NotImplementedError` (architecture §13).
- **`NadirPointing(velocity_reference="ecef")`** runtime (Earth-relative velocity
  yaw) — ships (Chunk 6) as a validated skeleton: it constructs/validates and
  serializes (`nadir_pointing:vel=ecef`), but `_to_provider` raises
  `NotImplementedError`; only `"inertial"` is wired. Completing it needs a custom
  `@JImplements TargetProvider` subtracting Earth rotation (architecture §13).
- **Full per-facet Sentman drag**, time-varying/programmed attitude, local-orbital
  frames beyond TNW, RTN/LVLH frames — deferred (architecture §13).
- **TLE type + `tle/`, tracking, passes** — Features 1.3–1.5.
- **Escape / re-entry guards** — none in v1: escape propagates faithfully (Cartesian
  orbit type), re-entry surfaces only as a `min_step_s`-saturation `PropagationError`,
  and a drag-off sub-surface perigee is returned uncaught. Planned as a configurable
  re-entry floor (~120 km geodetic) + a permissive upper-altitude ceiling
  (~1 M km ≈ Earth's sphere of influence) escape safety-net — not an input
  eccentricity rejection (which would forbid valid HEO/hyperbolic cases). Guards the
  boundary; does not model entry or deep space — deferred (architecture §13,
  features.md §1.1).
- **Backward propagation is unsupported in v1** (`propagate_numerical` requires
  `duration > 0`; features.md §1.1). Consequently, stack-compat test (b) — the
  "numerical round-trip" — is realized as **one-period closure** (propagate a
  point-mass orbit over exactly one Keplerian period and assert it returns to the
  initial state at ≤ 10⁻⁸ relative), not a literal forward-then-backward run.
  Architecture §11 (b) was updated to match this contract in Chunk 7. If backward
  propagation is ever added, the literal round-trip can replace the closure check.
