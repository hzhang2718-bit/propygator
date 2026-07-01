# Build plan: Tier B Drag — per-face incidence Cd (`BoxFaceCd`)

> **Status: BUILD PLAN (not started).** Derived from the **"Tier B Drag"** section of
> `docs/general-upgrades-1.md`, which is the **binding contract** for this work (the
> way `features.md` §1.1 was for the 1.1 build plan, and the drag-validity addendum
> was for its own plan). Every signature, table-semantics rule, threshold, and
> invariant below traces to that section — cited inline as "(contract: <heading>)".
> Where this plan and the contract disagree, the **contract wins**; fix the plan.
> Status headers are the maintainer's — trust the git log for true status.

## Context

`BoxFaceCd` is the realized form of the deferred Tier B box-drag extension that
`features.md` §1.1 sketched as `IncidenceVariableCd` (today a *validated skeleton*
in `propagation/spacecraft.py:409-519` whose `__call__` only ever raises). It adds a
**per-face, incidence-resolved** free-molecular drag coefficient for a **convex box**
— one universal, geometry-independent table that resolves how each of the six faces
meets the flow, summed exactly (no self-shadowing in free-molecular flow). It is the
better-designed successor to the old whole-body `(radius, density, azimuth, elevation)`
grid; the supersession map is in the contract's **Supercessions** section.

**This is one of several independent general upgrades** headed for **v0.5.0**. Per the
maintainer's decision: each upgrade is its own branch/PR into `main`; **v0.5.0 is
tagged once, after all the general upgrades land** — so this plan's wrap-up **merges
to `main` and does *not* bump the version or tag a release** (that is a separate,
cross-upgrade coordination step). Keep the branch and the docs reconciliation scoped
to Tier B only; `general-upgrades-1.md` stays alive for the other upgrades.

**Two coupled workstreams** (mirroring the drag-validity addendum, which had the same
offline-experiment → shipped-runtime shape):

1. **Offline (maintainer) — evidence the interpolated per-face table is accurate.**
   A new incidence-interpolation convergence study on the existing `cd_box.py`
   per-face kernel, an independent Orekit-free shipped generator
   (`scripts/generate_box_face_cd_table.py` → `data/box_face_cd_default.npz`), and a
   cross-validation gate proving generator == kernel ≪ 1% on the force-relevant
   `CdA`. Runs in the throwaway venv (`experiments/drag-coefficient-verification/.venv-experiments`,
   already present); reference-only, not shipped, not in CI.
2. **Runtime (shipped) — the `BoxFaceCd` type + per-face drag path.** Rename/redesign
   the skeleton into a first-class shipped Cd option, and build the per-face
   acceleration path inside the existing shared custom `DragSensitive` proxy.

**Shipping is gated on a benefit study** (contract: **Evidence pipeline** item 4):
ship only if the Tier-A → `BoxFaceCd` along-track divergence is **material AND
survives best-fit constant-Cd recalibration** for a representative sail. Per the
maintainer's decision this gate is **front-loaded**: a cheap, kernel-only benefit
estimate runs early (Chunk 1) with an explicit **STOP** point so the feature can be
dropped *before* the runtime is built; the rigorous propagation-based study (Chunk 6)
is the final confirmation.

**End state:** a user can drop `pgr.BoxFaceCd.default()` into
`box_and_panels(drag_coefficient=...)` on a convex box (`solar_array_area_m2 == 0`),
with `from_table` / `from_callable` for custom tables. `propagate_numerical`'s
signature is **unchanged**; the only user-visible surface change is the widened
`drag_coefficient` type and the new `Cd=table:box_face_default` metadata value.
Misuse fails at **construction** (`ValueError`), never mid-propagation.

### Source-of-truth docs (do not silently diverge)

- `docs/general-upgrades-1.md` **"Tier B Drag"** — the binding contract. Key
  sub-headings: *Supercessions*, *Context*, *Details* (Type, API at a glance, Table
  semantics, Runtime (per-face sum), Why all faces, Convention, Geometry coupling,
  Validation, Out-of-grid & drag-regime warnings, Metadata, Docstring), *Evidence
  pipeline* (1 convergence study, 2 generator, 3 cross-validation, 4 benefit study).
- `docs/features.md` §1.1 ("Drag-coefficient modeling") and `docs/architecture.md`
  §13 ("Coefficient of drag modeling") — authoritative **except** the spots the
  contract's *Supercessions* list replaces; reconciled in Chunk 7.
- `docs/tier-b-drag-interpolation-findings.md` — the analysis behind this design
  (low-risk linear interpolation for the convex box; convergence-study template).
  Not a contract; its "deferred" framing is retired in Chunk 7.
- `docs/orekit_setup_reference.md` — JVM boundary patterns. **Self-flagged stale;
  verify any snippet against the installed 13.1.x API.**

### Decisions already locked (do not relitigate)

- **Per-face, convex-box-only design** (not the old whole-body grid; not panels).
  A single universal table serves every convex box/plate geometry.
- **Axis = the face-flow angle θ over the full `[0, π]`** (head-on → edge-on →
  leeward), **not `cos θ`** — the shear's `sin θ` factor is smooth in θ but
  `√(1−cos²θ)` has an infinite-derivative cusp at the poles, so a `cos θ` axis
  interpolates badly there (contract: *Why all faces*). Key and interpolate in θ even
  though `cd_box.py` evaluates natively in `cos θ`.
- **All six faces evaluated** (windward + leeward), no windward-only truncation — it
  is the exact convex free-molecular drag, reproduces the committed all-faces collapse
  evidence, and is simpler (no branch).
- **Gas-surface assumptions baked into `default()`** match the Tier A sphere default
  exactly: SESAM accommodation anchored α = 0.90 at 400 km / solar max, diffuse
  re-emission, wall temperature 300 K (for cross-table coherence).
- **Drag does NOT route through `BoxAndSolarArraySpacecraft.dragAcceleration`** for
  `BoxFaceCd` (its single uniform Cd can't consume a per-face table). The Orekit box
  is still built — but only to drive SRP.
- **Bundle into v0.5.0** — no tag/version bump in this plan (see Context).

### Decisions to confirm (defaults chosen; "You provide" flags them)

- **Branch:** off `main` (which now carries 1.1 / 1.3 / 1.4). Default name
  `feature/tier-b-drag`. Confirm before Chunk 1.
- **Representative sail scenario** for the benefit estimates (Chunks 1 & 6) — a
  Sun-pointing LEO sail (high area-to-mass, the headline case `features.md` §1.1
  steers onto the box). Default: Claude picks one; confirm, or supply your own.
- **Table grid extents/resolution** (radius / density / incidence point counts) — an
  **output of the Chunk 1 convergence study**, not guessed; you sign off before the
  table is generated (Chunk 2). The `(radius, density)` axes reuse the Tier A
  validated band; the incidence axis spans the full `[0, π]`.

### Architecture invariants to honor in every runtime chunk (CLAUDE.md / architecture §4, §10)

Orekit/Java types stay internal; import `jpype`/`orekit_jpype`/`pyhelpers` **lazily
inside functions**, never at module top; SI internally (rad/m/kg; deg/km only at the
boundary); frames explicit; `pathlib.Path`; `logging`, never `print`; frozen / value
types with `__post_init__` validation; new public types re-exported from the
top-level `__init__.py` while keeping `import propygator` JVM-free.

---

## How to use this plan

- **7 numbered chunks**, each sized for one Claude Code session and independently
  verifiable. Two workstreams:
  - **Chunks 1–3 are offline/maintainer** (throwaway venv; produce committed
    *evidence* — figures + ASCII-only captured stdout + the generated `.npz` — not
    pytest tests; reference-only, excluded from CI/lint/mypy).
  - **Chunks 4–6 are shipped runtime code** (propygator conda env; pytest, with
    JVM-touching tests acquiring the `orekit` fixture). **Chunk 7 is wrap-up.**
- Each chunk lists **Goal / Create-Edit / Reuse / You provide / You run / Verify**.
  **You provide** is called out every chunk (often "nothing") so you always know
  whether a session needs input from you.
- **Two go/no-go gates:** Checkpoint A (after Chunk 1, the cheap early gate — a real
  STOP point) and the final benefit study (Chunk 6). If either says "not material /
  absorbable," **drop the feature** rather than ship.
- **`/code-review` + `/simplify` checkpoints** are marked inline after the chunks
  where they pay off (the §5-equivalence evidence; the dense runtime path; the
  wrap-up) — regular, not after every chunk.
- **Commits, CHANGELOG entries, chunk-header "done" marks, and the merge/tag are
  yours.** Claude writes code and runs read-only/test commands; you run the
  experiment in the venv, commit, and push. Claude won't push or open a PR unasked.
- **Mergeable chunks:** 1's convergence study + cheap benefit can split if a session
  runs long; 4 (type) + 5 (runtime) can merge in a big session. Split for safety.

---

## Git: branch strategy (read once, before Chunk 1)

`main` now carries 1.1 / 1.3 / 1.4, so — unlike the drag-validity addendum — there is
no "unmerged base" wrinkle. Branch straight off `main`:

```powershell
conda activate propygator
git switch main
git pull
git switch -c feature/tier-b-drag
git push -u origin feature/tier-b-drag
```

Per-chunk rhythm: `git status` → `git add -A` → `git commit -m "tier-b chunk N: <summary>"`
→ `git push` (CI runs on the branch). **Do NOT** bump `pyproject.toml` version or tag
in this plan — v0.5.0 is cut once, after all the general upgrades land.

**You provide (git):** confirm the branch name before Chunk 1; `gh` authenticated
before Chunk 7; the final merge-to-main go-ahead (an outward action).

---

## Chunk 1 — Convergence study + cheap benefit estimate → GO/NO-GO Checkpoint A - Done, checkpoint passed

**Goal:** the offline evidence that (a) linear interpolation over the θ axis is
accurate, and (b) `BoxFaceCd` plausibly beats a recalibrated Tier-A scalar — *before*
any runtime is built, so the feature can be dropped cheaply.

**Create / edit** (all in `experiments/drag-coefficient-verification/`, venv;
**ASCII-only prints** — stdout is captured under cp1252):
- A **new driver** (e.g. `cd_box_incidence_convergence.py`) on the existing
  `cd_box.py` `cd_panel_species` per-face kernel (contract: *Evidence pipeline* 1b):
  Cd vs θ on a **fine** `[0, π]` grid as truth → subsample to candidate **coarse**
  uniform grids → linearly interpolate back → report **max/RMS error vs spacing** and
  a Cd-vs-θ plot. Expect clean ≈ 2nd-order convergence (error ~4× per halving) with no
  special node placement, because the per-face Cd is C∞ in θ. Run at a single
  representative altitude (incidence is separable from `(radius, density)`;
  `tier-b-drag-interpolation-findings.md` §4.3).
- A **new cheap benefit driver** (e.g. `cd_box_benefit_estimate.py`): for the
  representative Sun-pointing sail, build a kinematic attitude history over a few days
  (Kepler orbit + Sun direction; **no Orekit, no integrator**), then compare the
  along-track drag work of **`CdA_BoxFace(t) = Σ Cd_i(θ_i)·A_i`** vs the **best-fit
  constant** `CdA` that Tier A would use (best scalar × Orekit-style windward
  projected area `Σ max(0, cos θ_i)·A_i`). Report the residual after re-fitting the
  scalar. This is the contract's benefit study (item 4) reduced to a kernel-only
  estimate — a DROP signal if the residual is clearly immaterial; otherwise proceed.
- Figures + captured ASCII stdout committed as evidence (the experiment's documented
  provenance pattern — see its `README.md`).

**Reuse:** `cd_box.py` `cd_panel_species` (the per-face kernel, already an all-faces
signed-γ basis); `cd_core.py` (`v_rel`, `SPECIES`, `IDX`, `geocentric_radius`,
`calibrate_K`, `alpha_sesam`); the experiment's PNG + redirected-stdout provenance
pattern. **Do not edit the sphere files** (`cd_core.py`/`cd_sphere_experiment.py`
stay untouched — add box logic alongside).

**You provide:** confirm the throwaway venv (`pymsis` + `scipy` + `matplotlib`); the
representative sail scenario (or accept Claude's); **the GO/NO-GO call at Checkpoint
A.**

**You run:** in the venv, run both drivers, redirect stdout to results files, eyeball
the figures, commit the evidence.

**Verify:** the convergence curve shows clean ~2nd-order falloff (a larger uniform
grid provably hits any error target); the Cd-vs-θ plot has no value jumps/kinks; the
benefit residual is quantified. Bare `pytest` unaffected (experiment outside
`testpaths`).

> ### ⛔ GO/NO-GO Checkpoint A — the cheap gate
> 1. If the cheap benefit residual is **clearly immaterial** (a recalibrated scalar
>    absorbs the divergence) → **STOP: drop `BoxFaceCd`**, record the evidence in
>    `tier-b-drag-interpolation-findings.md`, do not build the runtime.
> 2. If **material or ambiguous** → proceed; the rigorous study (Chunk 6) confirms.
> 3. Commit + push the evidence either way.

---

## Chunk 2 — Shipped generator + `data/box_face_cd_default.npz` - Done

**Goal:** the independent, Orekit-free generator that produces the headline default
table — the per-face twin of `generate_sphere_cd_table.py` (contract: *Evidence
pipeline* 2).

**Create / edit:**
- `scripts/generate_box_face_cd_table.py` (new) — **pure-numpy, Orekit-free** (so the
  Chunk-3 cross-validator can import it in the venv), modeled closely on
  `scripts/generate_sphere_cd_table.py`: sweep NRLMSISE-00 conditions, reconstruct
  the **full per-face free-molecular physics — normal pressure AND tangential shear**
  (Sentman/Schaaf-Chambre, DRIA) over `(radius, density, θ ∈ [0, π])`, regrid onto the
  signed-off mesh, write `grid`/`radius_axis`/`density_axis`/`incidence_axis` +
  `metadata_json`. **Share the Tier A accommodation model** (reuse
  `generate_sphere_cd_table._accommodation` / `_calibrate_accommodation_K` /
  `_geocentric_radius` / `_relative_speed`, importing them, exactly as
  `cross_validate_models.py` already imports `gen`) for cross-table coherence; the
  per-face coefficient is the new part. Defer heavy imports (`pymsis`, `scipy`) inside
  `generate()` so `--help` runs in the bare env. CLI with `--force`, grid-extent args,
  `--seed`.
- `data/box_face_cd_default.npz` (new committed asset) — generated to the Chunk-1
  signed-off extents (`(radius, density)` = the Tier A validated band; incidence =
  full `[0, π]`).

**Reuse:** `generate_sphere_cd_table.py` end-to-end (structure, regrid + nearest-fill
edge handling, `metadata_json` provenance block, `_DEFAULT_OUTPUT`/`data/` path); the
per-face closed form from `cd_box.py`.

**You provide:** sign off the grid extents/resolution (Chunk-1 output) before the
`.npz` is committed.

> **Chunk-1 result — recommended incidence-axis resolution (input to the sign-off).**
> The Chunk-1 convergence study (`cd_box_incidence_convergence.py`) shows linear
> interpolation of the per-face Cd over the **θ axis** converges cleanly at ~2nd
> order (RMS error ~4× per spacing-halving), with **no special node placement**:
> a uniform **33-node** axis (≈ 5.6° spacing) over `[0, π]` already gives **< 0.4 %
> max / < 0.1 % RMS** error vs the kernel, and **65 nodes** (≈ 2.8°) gives < 0.1 %
> max. **Recommend a uniform `incidence_axis` of ~49–65 nodes over `[0, π]`** (a
> safe margin past 33, still trivially small) — final point count is the maintainer's
> sign-off. The `(radius, density)` axes reuse the Tier A validated band/resolution.
> The Cd(θ) shape is altitude-stable (separability confirmed), so this resolution
> holds across the whole band.

**You run:** regenerate in the venv; commit the `.npz` + the script.

**Verify:** `conda run -n propygator python scripts/generate_box_face_cd_table.py --help`
runs in the bare env (no pymsis/scipy needed for `--help`); the `.npz` carries the
four arrays + `metadata_json` with both the grid band and internal-sampling band; the
per-face Cd floors at ~0.07 at θ = π/2 and tapers to ~0 by θ ≈ 110° (sanity vs the
contract).

---

## Chunk 3 — Cross-validation (the §5-equivalence invariant) - Done

**Goal:** prove the experiment kernel and the shipped generator are the same physics,
so the convergence/validity evidence transfers to the shipped table (contract:
*Evidence pipeline* 3).

**Create / edit** (`experiments/drag-coefficient-verification/`, venv; ASCII stdout):
- A **box cross-validator** (extend `cross_validate_models.py` or add
  `cross_validate_box_face.py`) driving **both** the `cd_box.py` kernel and
  `generate_box_face_cd_table.py`'s internals off **one identical set of
  `(radius, density, incidence)` rows**. Assert on the **force-relevant assembled
  `CdA = Σ Cd_i·A_i`** for a representative box swept over attitude × radius × density
  (an O(1 m²) quantity never near zero) with **`max rel diff ≪ 1 %`** — mirroring how
  the Tier A check asserts on *total* Cd, not per-species terms. Keep a **secondary
  max-absolute per-face check** (`|Cd_gen − Cd_exp| < ε_abs`, ε_abs well under the
  smallest force-relevant Cd) to catch local divergence where `Cd_i → ~0.07 → 0` makes
  a bare relative gate ill-posed.
- Commit the script's captured stdout as evidence.

**Reuse:** `cross_validate_models.py` (the import-the-generator-via-`sys.path`
pattern; the reconcile-first structure; `rel_diff`); the Chunk-2 generator internals;
`cd_box.py`.

**You provide:** nothing (sign-off on the recorded equivalence is implicit in the
green assert).

**You run:** run the cross-validation in the venv; commit evidence.

**Verify:** the two per-face models agree ≪ 1 % on `CdA` and within ε_abs per face
across the swept conditions (if not, reconcile before trusting the Chunk-2 table — a
divergence here invalidates the shipped default).

> ### ✅ Checkpoint B — offline evidence complete
> 1. Convergence (Chunk 1), generated table (Chunk 2), and generator==kernel
>    equivalence (Chunk 3) are all committed with figures + ASCII stdout.
> 2. `/code-review` + `/simplify` on the experiment + generator diff (the per-face
>    physics reconstruction is easy to get subtly wrong — esp. the shear term).
> 3. Commit + push.

---

## Chunk 4 — `BoxFaceCd` type (rename/redesign the skeleton) — pure-Python, safe before init - Done

**Goal:** the first-class shipped Cd type, constructible and validating with **no
JVM** (contract: *Type*, *API at a glance*, *Table semantics*, *Validation*,
*Metadata*; *Supercessions* "Code").

**Create / edit:**
- `src/propygator/propagation/spacecraft.py` — **rename/redesign**
  `IncidenceVariableCd` → `BoxFaceCd`:
  - Constructors `default()` (loads `data/box_face_cd_default.npz` via `_data_dir()`,
    mirroring `VariableCd.sphere_default` at `spacecraft.py:292-316`),
    `from_table(grid, *, radius_axis, density_axis, incidence_axis, name=None)`,
    `from_callable(fn, *, name=None)` where `fn(radius_m, density_kgm3, theta_rad) -> Cd`.
  - `__call__(radius_m, density_kgm3, theta_rad) -> float` (no longer raises): clamp
    `(radius, density)` to edges with the **same edge-aware warn-once** as `VariableCd`
    (reuse `_CLAMP_EDGE_MESSAGES` / `_warn_edge_once` / `_reset_edge_warnings` /
    `_clamp_to_axis`; θ never clamps — it spans the full `[0, π]`); trilinear lookup
    (extend the `_bilinear` pattern at `spacecraft.py:111-151`); reject non-finite /
    negative Cd from a callable (mirroring `VariableCd.__call__:330-343`).
  - **Validation** (contract table): `from_table` shape ≠ axes → `ValueError`;
    non-1-D/non-ascending/non-finite axis or grid → `ValueError` (reuse
    `_validate_axis:61-78`); a **new `incidence_axis` ∈ `[0, π]` range check** (the
    one validation `_validate_axis` does not cover).
  - **Metadata:** new `_content_hash` kind tag **`"cd_boxface"`** (so it can never
    collide with `"cd2d"`); `_metadata_id` returns `name` or hash; update `_format_cd`
    (`spacecraft.py:772-776`). `default()` records `Cd=table:box_face_default`.
  - Update the `DragCoefficient` alias (`spacecraft.py:523`) → `float | VariableCd |
    BoxFaceCd`, and the module-header docstring (today describes the deferred skeleton).
  - **Geometry validation** (`_validate_sphere:645-670`, `_validate_box:672-697`):
    `sphere` given a `BoxFaceCd` → `ValueError` (a sphere has no flow incidence);
    `box_and_panels` given a `BoxFaceCd` with `solar_array_area_m2 > 0` → `ValueError`
    (convex box only) — placed after the array-area finiteness check. Update the
    `sphere`/`box_and_panels` factory type hints (`drag_coefficient: float | VariableCd`
    stays for sphere; box widens).
- `src/propygator/__init__.py` — re-export `BoxFaceCd` beside `VariableCd`
  (`__init__.py:68,112`); keep `import propygator` JVM-free.
- **Tests** (`tests/propagation/test_spacecraft.py`, pure-Python; **rename/rewrite**
  the existing `IncidenceVariableCd` tests at lines 100/203/228/363-398/472): all
  constructors; `default()` loads and is callable; `__call__` clamps `(radius,
  density)` with warn-once and does not clamp θ; the validation table rows; the
  sphere-rejection and convex-box-rejection `ValueError`s; `"cd_boxface"` hash never
  equals a `"cd2d"` hash; the metadata token; **no JVM started**. Update
  `tests/test_public_surface.py` to assert `BoxFaceCd` is exported.

**Reuse:** the whole `VariableCd` machinery (`_validate_axis`, `_clamp_to_axis`,
`_content_hash`, `_CLAMP_EDGE_MESSAGES`, `_warn_edge_once`, `_reset_edge_warnings`,
`_data_dir`, the `sphere_default` loader shape, `_format_cd`).

**You provide:** nothing (fully specified in the contract).

**You run:** the per-chunk git rhythm.

**Verify:** `conda run -n propygator pytest tests/propagation/test_spacecraft.py tests/core tests/test_public_surface.py -v`
green and JVM-free; `conda run -n propygator python -c "import propygator, jpype; print(jpype.isJVMStarted())"`
→ `False`; `pgr.BoxFaceCd` is exported.

---

## Chunk 5 — Runtime per-face drag path + shared warnings (JVM-touching) - Done

**Goal:** the per-face acceleration path inside the existing shared custom
`DragSensitive` proxy — the core new integration surface (contract: *Runtime (per-face
sum)*, *Why all faces*, *Convention*, *Geometry coupling*, *Out-of-grid & drag-regime
warnings*).

**Create / edit:**
- `src/propygator/propagation/numerical.py`:
  - **Remove** the `IncidenceVariableCd` `NotImplementedError` branch
    (`numerical.py:499-504`) and wire `BoxFaceCd`.
  - Build a **per-face acceleration closure** (a sibling of `_sphere_accel:526-535` /
    `_box_accel:547-553`). The current `_build_drag_sensitive(cd_lookup, accel,
    kn_floor)` threads a **2-arg scalar** `cd_lookup(radius, density)` then
    `accel(state, density, relVel, scalar)`; the per-face path does not fit that, so
    the six `table(radius, density, θ_i)` lookups, the `CdA` assembly, and the
    table-edge warn-once move **into** the acceleration callable. Either branch
    `_build_drag_sensitive` (let `accel` own the lookup, `cd_lookup` a no-op) or add a
    small sibling proxy builder — **reuse the same `@JImplements(DragSensitive)`
    class** (no new Java interface, so no new default-method trap) and the shared
    `kn_floor` warn-once hook (`numerical.py:402,417-423`).
  - Per substep, inside the closure: `flow_hat = −relativeVelocity/|relativeVelocity|`
    rotated into the body frame via `state.getAttitude().getRotation().applyTo(...)`
    (**`applyTo`, verified to machine precision against Orekit's box drag — `applyInverseTo`
    is wrong by ~9 %**; contract: *Convention*, and the `ecef-nadir-targetprovider-route`
    memory); for each of the 6 faces (normals ±X/±Y/±Z; full areas `y·z`, `x·z`,
    `x·y` from the geometry) form `c_i = n_i·flow_hat` and
    `θ_i = arccos(clip(c_i, −1, +1))` (**the clip is mandatory** — an unclamped
    `arccos` returns NaN at exact head-on/leeward and silently poisons the
    acceleration; contract: *Runtime* bullet 2); look up `Cd_i`, assemble
    `CdA = Σ Cd_i·A_i` (full face areas — do **not** re-project), and apply the
    **sphere-style** `a = ½ (CdA/m) ρ |relativeVelocity| · relativeVelocity` (Orekit
    `+½` convention, as `_sphere_accel`). All six faces, no windward/leeward branch.
  - **Do not** call `box.dragAcceleration` for `BoxFaceCd`; the box object
    (`_build_box_spacecraft:431-471`, still built at base Cd 1.0) is passed to SRP only
    (`_build_srp_force:558-588`). The Kn floor (`_kn_floor_setup`, box → max edge
    length, `guards.py:438-451`) applies unchanged.
- **Tests** (`tests/propagation/test_numerical.py`, JVM-touching → `orekit` fixture):
  - A **hand-checked incidence value**: a fixed-attitude box where the analytic per-face
    `CdA` is computed independently matches the propagator's drag (one substep).
  - **Convention guard**: a windward-only `CdA` reconstruction reproduces Orekit's own
    `BoxAndSolarArraySpacecraft.dragAcceleration` at a non-axis-aligned attitude
    (confirms the `applyTo` rotation sense + face set), per the contract.
  - **All-faces vs windward-only**: a near-cubic bus at face-on shows the ~5–11 %
    shear contribution from the four edge-on faces (a regression that the leeward/edge
    terms are not dropped).
  - **Warnings**: a `BoxFaceCd` run crossing the Kn floor / low radius edge emits the
    loud warning once; high radius edge the soft note once; θ produces no clamp/seam.
  - Verify inside a real `propagate()` (the JPype boundary only behaves correctly in
    the real call path).

**Reuse:** the shared `_build_drag_sensitive` proxy + `kn_floor` hook; `_sphere_accel`
formula; `_build_box_spacecraft` (SRP); `core/bodies.py` constants; the `applyTo`
convention from the ECEF-nadir work.

**You provide:** *optionally* a hand-checked incidence reference value to anchor the
first test; otherwise Claude computes one — confirm at review.

**You run:** the per-chunk git rhythm.

**Verify:** `conda run -n propygator pytest tests/propagation -v` green; a `BoxFaceCd`
box propagates and its drag matches the independent per-face `CdA`; the convention and
warning tests pass; a fixed-Cd / `VariableCd` box run is **unchanged** (regression).

> ### ✅ Checkpoint C — runtime built
> 1. `BoxFaceCd` constructs, validates, and drives drag end-to-end per the contract.
> 2. **Refresh `CLAUDE.md`** "Project state" (note `BoxFaceCd` built on
>    `feature/tier-b-drag`, the skeleton retired). Note the contract is the active
>    binding doc for this surface.
> 3. `/code-review` + `/simplify` on the runtime diff (the per-face closure + the
>    rotation/clamp/lookup is dense and easy to get subtly wrong). Commit + push.

---

## Chunk 6 — Rigorous benefit study → final GO/NO-GO - Done

**Goal:** the contract's ship-or-drop gate (contract: *Evidence pipeline* 4), now with
the real runtime available — confirm (or refute) the Chunk-1 cheap signal.

**Create / edit** (hybrid — table from the venv, propagation in the conda env):
- A benefit-study harness (an `experiments/` driver + a short conda-env propagation
  script, or a `scripts/` analysis): propagate the representative Sun-pointing LEO
  sail over a multi-day window **twice** — once with Tier A (best-fit constant Cd) and
  once with `BoxFaceCd.default()` — and compare the **along-track divergence**, then
  **re-fit the constant Cd** to the `BoxFaceCd` run and check the divergence
  **survives** recalibration. Capture the result as evidence.

**Reuse:** the Chunk-1 sail scenario; `propagate_numerical` with both Cd options;
existing trajectory-diff / along-track tooling if present, else a small ASCII report.

**You provide:** confirm the sail + orbit (reuse Chunk 1's, or supply a final one);
**the final SHIP / DROP decision.**

**You run:** run both propagations; record the evidence.

**Verify:** the along-track divergence is quantified and the
survives-recalibration test is recorded.

> ### ⛔ Final GO/NO-GO
> - **Material AND non-absorbable** → **SHIP**: proceed to Chunk 7.
> - **Immaterial or absorbed by a recalibrated scalar** → **DROP**: record the
>   evidence, revert the runtime if desired (or keep it behind the docs as a validated
>   skeleton again), and do **not** reconcile the contract into `features.md`.

---

## Chunk 7 — Wrap-up: full sweep, review, docs reconciliation, merge (no tag) - Done

**Goal:** land Tier B — clean diff, the contract's *Supercessions* map folded back into
the governing docs, and the merge to `main`. **No version bump, no tag** (v0.5.0 is
cut later, after all general upgrades land).

> ### 📌 Pre-Chunk-7 session notes (2026-06-30) — benefit study done, decision = SHIP
>
> **Decision: SHIP** (maintainer's call, 2026-06-30). Chunk 6's gate is satisfied but
> *scenario-dependently* — this framing is what the docs must carry:
> - **Contract Sun-pointing sail** (the plan's named scenario): benefit is **< 1 %** —
>   a recalibrated *physical* constant Cd (best-fit ≈ 2.7) absorbs the Tier-A→BoxFace
>   divergence. On this case alone the gate reads DROP.
> - **Edge-on sail** (maintainer's actual primary application; a companion study added
>   at the maintainer's request): benefit is **~2.1× and NON-absorbable** — physical
>   Tier A (Cd=2.2 or `VariableCd`) under-predicts along-track by ~1400–1640 km / 5 d,
>   and the constant needed to patch it is Cd ≈ 4.74 (above the physical ~2.0–2.6 range,
>   still ~103 km residual). In that regime drag dominates SRP ~5000× (400 km, solar
>   max). **This is BoxFaceCd's load-bearing use case and is *why we ship*.**
>
> **"Careful documentation" is a first-class Chunk-7 task** (maintainer asked for it,
> beyond the mechanical *Supercessions*). Add the scenario-dependence, honestly, to the
> `BoxFaceCd` docstring **and** `features.md` §1.1 model-limitations: negligible over a
> recalibrated scalar for face-on / tumbling / Sun-pointing flight; ~2× and
> non-absorbable for grazing/edge-on flight (its intended regime).
>
> **Attitude caveat that MUST go in the docs** (verified in `attitude.py`, 2026-06-30):
> `InPlaneTracking` tracks **inertial** velocity only — it is parameterless, no
> `velocity_reference` (only `NadirPointing` got the `ecef` option, `attitude.py:400-418`).
> So a body held "edge-on" via `InPlaneTracking` sits a few degrees off the true
> Earth-relative flow — which is why the measured benefit is ~2×, **not** the idealized
> ~9×. Document the ~2× *with this caveat*; do not quote the idealized figure.
> - *Possible future upgrade, explicitly NOT part of Tier B:* give `InPlaneTracking` the
>   same `velocity_reference="ecef"` option (`_build_ecef_velocity_target_provider` already
>   exists and is reusable). It changes a shipped contract ("No parameters") so it needs
>   its own design note — flag it, don't bundle it into this wrap-up.
>
> **Chunk 6 evidence to commit** (currently untracked — maintainer's to commit), all in
> `experiments/drag-coefficient-verification/`:
> `cd_box_benefit_study.py` + `.png` + `_results.txt` (Sun-pointing, contract scenario);
> `cd_box_benefit_study_edgeon.py` + `.png` + `_results.txt` (edge-on companion);
> and the `README.md` edits documenting both (its sections (4) and (5)).
>
> **Numbers on hand** (for CHANGELOG / docstring if wanted) — edge-on: 400 km circular,
> inc 51.6°, 1 m² sail, 0.01 m edge, 2 kg, 5-day window, solar max — Tier A Cd=2.2 →
> −1639 km, `VariableCd` → −1426 km, best-fit Cd 4.74 (residual 103 km), drag/SRP ≈ 4970×.

**Create / edit / run:**
- Full local CI parity: `conda run -n propygator pytest` and
  `conda run -n propygator pre-commit run --all-files` both green from repo root.
- `/code-review` + `/simplify` final pass across the whole Tier B diff.
- **Reconcile the docs** (contract's *Supercessions* list — apply exactly those spots):
  - `features.md` §1.1 — `box_and_panels` signature → `float | VariableCd | BoxFaceCd`;
    replace the Tier B "incidence-keyed box table" paragraph and the
    `IncidenceVariableCd.from_table` API example with the `BoxFaceCd` design; update the
    validation table (sphere/box rejection rows), **remove** the
    `IncidenceVariableCd → NotImplementedError` failure-mode row, extend the metadata
    note, update the model-limitations docstring (the contract's *Docstring* block).
  - `architecture.md` §13 — replace the deferred Tier B description with the shipped
    `BoxFaceCd` (per-face, convex-only); update the two §13 cross-mentions of
    "deferred Tier-B `IncidenceVariableCd`" (module-tree comment ~line 718,
    exception-types note ~line 646).
  - `docs/tier-b-drag-interpolation-findings.md` — retire the "deferred / not built"
    framing (now built and shipped, or recorded as dropped if the gate failed).
  - Cd table clamp warning's wording changed from "VariableCd" to "Cd-table" for greater
    clarity. The old wording may be present in multiple docs.
  - **Leave `general-upgrades-1.md` in place** (it stays the source of truth for the
    other v0.5.0 upgrades); only its Tier B section is now "built."
  - **You** update `CHANGELOG.md` `[Unreleased]` and refresh `CLAUDE.md` "Project
    state" (the narrative artifacts are yours).
- **Merge:** `gh pr create` against `main`, confirm CI green, then
  `gh pr merge --squash --delete-branch` — **your call**. Do **not** tag v0.5.0 here.

**You provide:** confirm `gh` authenticated; the final merge go-ahead; CHANGELOG +
CLAUDE.md edits; the note that v0.5.0 tagging is deferred to the cross-upgrade step.

**Verify:** full `pytest` + `pre-commit run --all-files` green; `import propygator as
pgr` exposes `BoxFaceCd` and stays JVM-free; the contract's *Supercessions* spots are
all carried into `features.md`/`architecture.md`; `pyproject.toml` version is
**unchanged**.

---

## End-state verification (Tier B shipped → on `main`, untagged)

From repo root, `conda activate propygator`, on the merged branch:
1. **Offline evidence:** convergence study (clean ~2nd-order), the generated
   `box_face_cd_default.npz`, and the generator==kernel cross-validation (≪ 1 % on
   `CdA`) are committed with figures + ASCII stdout.
2. **Type:** `pgr.BoxFaceCd.default()/from_table/from_callable` construct and validate
   JVM-free; misuse (sphere, or box with arrays) raises `ValueError` at construction;
   metadata token `Cd=table:box_face_default`; `"cd_boxface"` hash never collides.
3. **Runtime:** a convex box with `BoxFaceCd` propagates; drag matches the independent
   per-face `CdA`; the `applyTo` convention + `arccos` clamp hold; warnings fire once;
   a fixed-Cd / `VariableCd` box run is unchanged.
4. **Benefit gate:** the rigorous study is recorded; the SHIP decision (or DROP) is
   evidenced.
5. **Tests:** the pure-Python `BoxFaceCd` suite + the JVM-touching drag tests (via the
   `orekit` fixture) pass; `pre-commit run --all-files` clean.
6. **Docs:** the contract's *Supercessions* map is carried into
   `features.md`/`architecture.md`; `general-upgrades-1.md` stays alive for the other
   upgrades; CHANGELOG + CLAUDE.md updated; **version unchanged / untagged**.
7. `conda run -n propygator python -c "import propygator, jpype; print(jpype.isJVMStarted())"` → `False`.

## Notes / deferred (not this plan)

- **Panels / non-convex bodies** (solar-array shadowing) stay out of scope — use a
  dedicated aero tool, or a fixed Cd / `VariableCd` (contract: *Context*).
- **Full per-facet Sentman** (per-facet material/temperature, multiple reflection,
  transitional/continuum flow), **UT1**, and the other general upgrades in
  `general-upgrades-1.md` are out of scope here.
- **v0.5.0 tag** is a separate, cross-upgrade step once all general upgrades land.
