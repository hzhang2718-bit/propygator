# Build plan: Feature 1.1 Addendum — ECEF Nadir Yaw-Steering & Direction-Indicating Plot Markers

> **Status: BUILD PLAN (not started).** Derived from
> `docs/feature-1.1-addendum-ecef-nadir-and-direction-markers.md`, which is the **binding
> contract** for this work (the way `features.md` §1.1 was for the original 1.1 build plan and
> the drag-validity addendum was for its plan). Every signature, threshold, and route below
> traces to a section of that addendum — cited inline as "(addendum §X)". Where this plan and
> the addendum disagree, the **addendum wins**; fix the plan.

## Context

Feature 1.1 (the numerical propagator) and the drag-validity & altitude-guards addendum are
**merged and released** in `v0.1.0`; `main` is clean. This plan adds two small, independent
finishing touches (addendum §0), bundled into **one branch / one PR** because they share no
code and add no new public name:

1. **ECEF nadir yaw-steering** — replace the `_to_provider` deferral with a working custom
   `TargetProvider` proxy that steers body +Y to the Earth-relative velocity
   `v_rel = v_inertial − ω⊕ × r` (the ground-track direction), keeping body −Z on nadir.
2. **Direction glyphs** — the two spatial plots' end markers gain a direction of travel
   (ground-track heading triangle; 3-D velocity cone). The start circle is unchanged.

End state = addendum §4 ("What the end product looks like") and §8 ("Definition of done"):
`NadirPointing(velocity_reference="ecef")` propagates a box and yaws ~3° off the inertial mode;
both spatial plots read directionally; no public API changes; recommend a MINOR bump to `v0.2.0`.

**Source-of-truth docs (do not silently diverge):**
- `docs/feature-1.1-addendum-ecef-nadir-and-direction-markers.md` — **the binding contract.**
  §1 supersession map, §2 ECEF (2.2 current skeleton, 2.3 implementation contract + the two
  JPype traps, 2.4 verification), §3 glyphs (3.1 triangle, 3.2 cone, 3.3 reconciliation), §6
  versioning, §7 decisions log, §8 definition of done.
- `docs/features.md` §1.1 and `docs/architecture.md` (§6 data model, §10 conventions, §11
  testing, §13 deferrals) — authoritative **except** the sections the addendum §1 map
  supersedes/extends (reconciled in the wrap-up chunk).
- Memory note `ecef-nadir-targetprovider-route` — the **proven** proxy shape, the two traps,
  the zero-derivative trick, the ω⊕×r-via-transform refinement, and the 3.08° verification
  anchor. The ECEF route is not exploratory; this is transcription of a tested recipe.
- `docs/orekit_setup_reference.md` — JVM boilerplate; **self-flagged stale, verify any snippet**.

**Decisions already locked (do not relitigate):**
- **ECEF route** = a custom `@JImplements(TargetProvider)` proxy in the `AlignedAndConstrained`
  secondary slot (primary −Z→NADIR unchanged), **not** `YawCompensation` (measured the heavier
  option; addendum §2.3, §7). Empirically confirmed in a real `propagate()`.
- **`ω⊕ × r`** = derived from the inertial↔ITRF `Transform` (exact), not a hardcoded
  `ω = (0,0,7.292e-5)` (addendum §2.3).
- **Ground-track triangle** = `atan2(Δlat, Δlon)` heading of the last non-dateline-wrapping
  segment, exact under plate carrée + `aspect="equal"` (addendum §3.1).
- **3-D cone** = `go.Cone` at the final sample along the final velocity, **scene-relative**
  size `sizeref = k × (max position span)`, single red via a constant colorscale (addendum §3.2).
- **No new public name / exception / signature / metadata change** — `__init__.py` re-export
  list and the public type inventory are **untouched** (addendum §1).
- **Out of scope (untouched deferrals):** backward-in-time propagation, Tier B
  `IncidenceVariableCd`, UT1, per-facet Sentman drag, RTN/LVLH frames (addendum §0).

**Decisions to confirm at the relevant chunk (defaults chosen; "You provide" flags them):**
- **Branch name** (Git section) — default `feature/ecef-nadir-and-direction-markers`.
- **Cone size factor `k`** (~4–6 % of scene span) + `anchor` (tip-forward), and the **triangle
  base-marker rotate offset** — *build-time visual tuning only*, the approaches are settled
  (addendum §7 "Still open"). Claude picks; the user may eyeball the rendered figures.
- **Version bump / CHANGELOG / commits / PR merge** are the **maintainer's** to author (project
  convention + memory `chunk-completion-and-commits-are-users`).

**Architecture invariants to honor (CLAUDE.md / architecture §4, §10):** Orekit/Java types stay
internal; import `jpype`/`orekit_jpype`/`pyhelpers` **lazily inside functions**, never at module
top; SI internally (deg only at the user boundary); frames explicit; `pathlib.Path`; `logging`,
never `print`; `import propygator` stays JVM-free; JVM-touching tests acquire the `orekit`
fixture (architecture §11; the `pytest_collection_modifyitems` ordering hook).

---

## How to use this plan

- **5 numbered chunks**, each sized for one Claude Code session and independently verifiable.
  - **Chunks 1–2 = Workstream A** (ECEF nadir; `attitude.py` + JVM-touching tests).
  - **Chunks 3–4 = Workstream B** (glyphs; `plotting/` + plot tests).
  - **Chunk 5 = wrap-up** (docs reconciliation, full sweep, version/CHANGELOG, PR).
- Each chunk lists **Goal / Create-Edit / Reuse / You provide / You run / Verify.**
- **The two workstreams are fully independent** — B (Chunks 3–4) may precede A (Chunks 1–2) if
  preferred. Within a workstream the order is fixed (build → verify; triangle → cone).
- **Mergeable chunks:** Chunk 2 (ECEF verify) can fold into Chunk 1 — the route is de-risked, so
  build+verify can be one sitting. Kept separate for safety, because the JPype proxy is the
  densest code in the addendum.
- **Checkpoints** (CLAUDE.md refresh + `/code-review` + `/simplify`) are marked inline after each
  workstream — where they pay off, mirroring the prior build plans.
- All test files already exist: `tests/propagation/test_attitude_providers.py` (JVM-touching
  attitude lowering), `tests/plotting/{test_style,test_plot_3d,test_trajectories,test_composite}.py`.
  No new test module is needed.

---

## Git: branch strategy (read once, before Chunk 1)

`main` is **clean and released** (`v0.1.0`), so branch straight from it (no off-feature-branch
wrinkle this time):

```powershell
conda activate propygator
git switch main
git pull
git switch -c feature/ecef-nadir-and-direction-markers
git push -u origin feature/ecef-nadir-and-direction-markers
```

(Branch name is a suggestion — keep the `feature/` prefix.) Because the two workstreams are
independent and small, **one branch and one PR covering both** is the natural choice (addendum §5).

**Per-chunk rhythm:** `git status` → `git add -A` → `git commit -m "addendum chunk N: <summary>"`
→ `git push` (CI runs on the branch). **Commit/push, the CHANGELOG entry, the version bump, and
PR/merge are the maintainer's** — Claude won't push, author CHANGELOG narrative, bump the version,
or open/merge a PR without being asked.

**You provide (git):** confirm the branch name before Chunk 1; `gh` authenticated before Chunk 5.

---

## Chunk 1 — ECEF velocity `TargetProvider` + wire into `_to_provider`

**Goal:** replace the `_ECEF_DEFERRED_MESSAGE` raise (`attitude.py:405-407`) with a working
custom `@JImplements(TargetProvider)` proxy that yields the Earth-relative velocity direction,
swapped into the existing `AlignedAndConstrained` secondary slot. The inertial branch and the
other six modes stay byte-identical (addendum §2.3).

**Create / edit** — `src/propygator/propagation/attitude.py`:
- A new lazy helper (model it on `_build_law_backed_provider`, `attitude.py:436-524`) that builds
  the `@JImplements(org.orekit.attitudes.TargetProvider)` proxy. It must implement (addendum §2.3):
  1. **`getTargetDirection`** — one Python method serving **both** Java overloads. Hand-dispatch
     on `hasattr(pv, "toTimeStampedPVCoordinates")`: field-PV → return a **constant**
     `FieldVector3D` (zero derivatives); plain-PV → return a `Vector3D`. (JPype overload-collapse
     trap.)
  2. **`getDerivative2TargetDirection`** — the **default** overload `AlignedAndConstrained`
     actually invokes; return a constant `FieldVector3D` (default-method trap — a proxy with only
     the abstract method fails with `UndeclaredThrowableException`).
  3. **Skip** the `FieldUnivariateDerivative2<T>` field-state overload (never hit by a
     double-precision `NumericalPropagator`; mirrors `_build_law_backed_provider` skipping the
     Field `getAttitude`).
  - The direction is `v_rel = v_inertial − ω⊕ × r`, computed from the inertial→ITRF `Transform`
    at the sample date (transform the PV to ITRF, re-express that velocity's direction back in
    EME2000) — **not** a hardcoded ω (addendum §2.3). **Zero-derivative trick**: v1 zeroes
    attitude rates, so the Field returns are constants built from the value direction — no field
    calculus.
- In the `NadirPointing` branch of `_to_provider` (`attitude.py:405-416`): when
  `velocity_reference == "ecef"`, return `AlignedAndConstrained(Vector3D(0,0,-1),
  PredefinedTarget.NADIR, Vector3D(0,1,0), <custom provider>, _sun(), _earth())` — **the same
  shape as the inertial branch, only the secondary target swapped**. Remove the
  `raise NotImplementedError`.
- Delete the now-dead `_ECEF_DEFERRED_MESSAGE` constant (`attitude.py:312-318`) and the
  "ECEF raises `NotImplementedError`" sentence in the `_to_provider` docstring (≈ `:331-332`);
  note both `velocity_reference` options are now wired.

**Reuse:** `_build_law_backed_provider` (`attitude.py:436-524`) as the `@JImplements`/`@JOverride`
+ lazy-import + JVM-free-until-called template; the inertial `AlignedAndConstrained` call
(`:409-416`); `core.bodies._earth`/`_sun`; `Frame.ITRF.to_orekit()` for the transform; the memory
note `ecef-nadir-targetprovider-route` (the proven proxy shape + traps + 3.08° anchor) and
addendum §2.3.

**You provide:** confirm the branch name (Git section). Otherwise nothing — the route is proven.

**You run:** the per-chunk git rhythm. A quick live smoke — propagate a box with
`NadirPointing(velocity_reference="ecef")` for a few minutes — to confirm no
`UndeclaredThrowableException` / overload error (the traps surface **only inside a real
`propagate()`**, never in a bare `getAttitude`).

**Verify:** a box `propagate_numerical(..., attitude=NadirPointing(velocity_reference="ecef"))`
runs to completion (no raise); at a sampled state `+Y → v_rel` < 0.01° and `−Z → nadir` < 0.02°
(the §2.3 anchors). `pytest tests/propagation -v` green (no regression). `python -c "import
propygator, jpype; print(jpype.isJVMStarted())"` → `False`.

---

## Chunk 2 — ECEF verification tests + attitude docstring

**Goal:** lock the ECEF behavior with tests (addendum §2.4) and update the in-module docstring
wording. (features.md / architecture.md reconciliation is deferred to Chunk 5.)

**Create / edit:**
- `tests/propagation/test_attitude_providers.py` (JVM-touching → `orekit` fixture):
  - **Yaw vs inertial:** propagate a ~500 km / 51.6° circular box with `="ecef"` and
    `="inertial"`; the body +Y (or attitude rotation) differs by the `ω⊕ × r` yaw — pin **≈ 3.08°
    near the equator → ~0 at the max-latitude turning point** (addendum §2.4).
  - **Metadata unchanged:** `nadir_pointing:vel=ecef` still serializes; the `attitude` key is
    recorded only for a box with a wired surface force (unchanged gate).
  - **Sphere path unaffected:** a non-default attitude on a sphere still emits the one-time
    consistency warning and falls back to `LofAligned` (`numerical._resolve_attitude`).
  - **Regression:** the `inertial` branch and the other six modes lower without error (confirm
    ECEF didn't perturb the shared `AlignedAndConstrained` path).
- `src/propygator/propagation/attitude.py` — `NadirPointing` docstring + the `velocity_reference`
  comment: "`ecef` = deferred / validated-skeleton" → "`ecef` = Earth-relative (ground-track)
  velocity yaw, implemented" (addendum §1 row 3; the doc reconciliation in the other files is
  Chunk 5).

**Reuse:** the existing attitude-provider test helpers + a circular-LEO `State` builder; the
`orekit` fixture + `pytest_collection_modifyitems` ordering (architecture §11).

**You provide:** optionally a reference state; otherwise Claude builds the 500 km / 51.6° orbit.

**You run:** the per-chunk git rhythm.

**Verify:** `pytest tests/propagation/test_attitude_providers.py -v` green; the equatorial yaw
pins to ≈ 3.08° (± tol) and → 0 at max latitude.

> ### ✅ Checkpoint A — Workstream A (ECEF) complete
> 1. `NadirPointing(velocity_reference="ecef")` lowers to a working provider, verified inside a
>    real `propagate()`; the deferral raise is gone (addendum §8 items 1–2).
> 2. **Refresh `CLAUDE.md`** "Project state": ECEF nadir now wired; remove it from the
>    "validated-skeleton deferrals" list. Note this addendum is the active build plan.
> 3. `/code-review` + `/simplify` on the `attitude.py` diff — the JPype proxy is the densest code
>    in the addendum and the easiest place to hide a subtle overload/default-method bug.
> 4. Commit + push.
>
> *(Chunk 2 is mergeable into Chunk 1 if a session has capacity — the route is de-risked.)*

---

## Chunk 3 — Ground-track heading-oriented triangle (matplotlib)

**Goal:** replace the ground-track end **star** with a **triangle rotated to the local track
heading** (addendum §3.1). `plot_summary` inherits it for free via `_draw_ground_track`.

**Create / edit:**
- `src/propygator/plotting/style.py` — **restructure `MARKER_END`** (`style.py:113-120`): the
  triangle's rotation is data-dependent, so **drop the `"marker"` key**; keep
  `c` / `edgecolors` / `s` / `zorder` / `label`. Update the `_MARKER_SIZE` comment
  (`style.py:96-98`, no longer "the star").
- `src/propygator/plotting/trajectories.py` `_draw_ground_track` (`:119-165`):
  - **Heading:** bearing of the **last non-dateline-wrapping** segment of the (lon, lat) track,
    `heading_deg = degrees(atan2(Δlat, Δlon))` — exact under plate carrée + `aspect="equal"`
    (isotropic degrees on screen). Reuse the keep-mask logic from `_dateline_segments`
    (`:101-116`) to skip a wrapping final segment; degenerate / coincident last points → point
    north (no rotation).
  - **Glyph:** `MarkerStyle("^").transformed(Affine2D().rotate_deg(heading_deg − 90))` — `"^"`
    points to +y = north = 90°, so the offset orients it along the heading. **Verify the
    base-marker orientation at build and pin the exact offset.** Draw
    `ax.scatter(lon[-1], lat[-1], marker=<MarkerStyle>, **MARKER_END)` (the dropped `marker` key
    avoids a double-kwarg). It stays a single scatter collection.
  - Keep the start circle, the red colour / visual weight, the `"end"` legend label.
  - Update the `_draw_ground_track` (`:133`) and `plot_ground_track` docstrings: "star" →
    "heading-oriented triangle".
- **Tests** (`tests/plotting/`, no JVM — matplotlib only):
  - `test_style.py::test_endpoint_markers` (`:89-96`): `MARKER_END` no longer has `"marker"` —
    assert the key is absent and the retained `c` / `edgecolors` are intact.
  - `test_trajectories.py`: add a **heading assertion** — the triangle's `MarkerStyle` rotation
    matches `atan2(Δlat, Δlon)` of the last valid segment. Confirm
    `test_ground_track_markers_match_geodetic_endpoints` (`:137-156`) stays green (still 2
    scatter collections; the endpoint *offset* is unchanged).
  - Re-record the ground-track image-bytes smoke `test_render_to_buffer_smoke`
    (`test_trajectories.py:239`) **and** the composite smoke
    `test_composite.py::test_summary_render_to_buffer_smoke` (`:135`) — both inherit the triangle
    via the shared `_draw_ground_track` primitive (addendum §3.3).

**Reuse:** `_dateline_segments` keep-mask (`:101-116`); `MARKER_START`/`MARKER_END` /
`OUTLINE_COLOR` / `_MARKER_SIZE` (`style.py`); `matplotlib.markers.MarkerStyle` +
`matplotlib.transforms.Affine2D`.

**You provide:** optionally eyeball the rendered ground track (triangle weight + orientation).

**You run:** the per-chunk git rhythm.

**Verify:** `pytest tests/plotting/test_style.py tests/plotting/test_trajectories.py
tests/plotting/test_composite.py -v` green; the end glyph is a heading-oriented triangle;
`_scatter_collections(ax)` still counts 2.

---

## Chunk 4 — 3-D velocity-oriented cone (Plotly)

**Goal:** replace the 3-D end **diamond** with a **scene-relative `go.Cone`** oriented along the
final velocity (addendum §3.2). Start circle unchanged.

**Create / edit:**
- `src/propygator/plotting/trajectories.py` `plot_3d` (`:287-388`):
  - **Capture the converted trajectory once:** `converted = traj.to_frame(frame)`, then read
    **both** `converted.positions` (for `pos_km`, currently `:309`) and `converted.velocities[-1]`
    — `to_frame` is JVM-crossing, do **not** convert twice (addendum §3.2).
  - Replace the end `_endpoint_marker(..., symbol="diamond")` (`:358-362`) with a **`go.Cone`** at
    the final sample, vector = the final velocity *direction* in `frame`. Single red via a
    **constant colorscale + `showscale=False`** — the trick `_sphere_surface` already uses
    (`:229`). **Scene-relative size:** `sizemode="absolute"`, `sizeref = k × (max position span)`
    from the already-computed `pos_km` (`go.Cone` has **no pixel sizemode**; a hardcoded
    `sizeref` would shrink/vanish on GEO/escape scenes). Pin `anchor` tip-forward.
  - Keep the start circle marker (`_endpoint_marker(..., symbol="circle")`, `:353-357`) and the
    `"end"` legend entry.
  - Record `k` (~4–6 %) and `anchor` next to the other 3-D cosmetic constants
    (near `_MARKER_SIZE_3D`, `:88`). Update the `plot_3d` docstring (`:302`): "red diamond" →
    "velocity-oriented cone".
- **Tests** — `tests/plotting/test_plot_3d.py::test_endpoint_markers` (`:115-122`): replace the
  `end.marker.symbol == "diamond"` assertion with "a `go.Cone` trace exists at the final sample,
  oriented along the final velocity, single red colour; start is still a circle marker"
  (addendum §3.3).

**Reuse:** `_sphere_surface`'s constant-colorscale + `showscale=False` trick (`:229`); the
already-computed `pos_km` for `sizeref`; the existing `_endpoint_marker` for the unchanged start;
`Trajectory.velocities`.

**You provide:** optionally eyeball the 3-D figure (cone weight `k` + tip-forward orientation
vs the old diamond).

**You run:** the per-chunk git rhythm.

**Verify:** `pytest tests/plotting/test_plot_3d.py -v` green; the 3-D view shows a red cone at the
end pointing along the velocity; on a large-scene (e.g. GEO) trajectory the cone stays visible
(scene-relative); the start circle is unchanged.

> ### ✅ Checkpoint B — Workstream B (glyphs) complete
> 1. Both spatial plots read directionally (triangle + cone); `plot_summary` inherits the
>    triangle; start markers unchanged (addendum §8 items 3–4).
> 2. **Refresh `CLAUDE.md`** "Project state": the direction glyphs are in.
> 3. `/code-review` + `/simplify` on the `plotting/` diff (the wrap-up runs the whole-diff pass).
> 4. Commit + push.

---

## Chunk 5 — Wrap-up: docs reconciliation, full sweep, version/CHANGELOG, PR

**Goal:** land the addendum — clean diff, the §1 supersession map folded back into the governing
docs, version bump, PR (addendum §8 items 5–8, §1, §6).

**Create / edit / run:**
- **Full local CI parity:** `pytest` and `pre-commit run --all-files` both green from repo root.
- `/code-review` + `/simplify` final pass across the whole addendum diff.
- **Reconcile the docs (addendum §1 map):**
  - `architecture.md` §13 — close the "`NadirPointing` ECEF-relative velocity yaw" deferral
    (≈ line 1050: resolved via the custom `TargetProvider`); extend the §13 "Attitude family"
    note (≈ line 1037: `NadirPointing` now wires **both** `velocity_reference` options + the ECEF
    target provider).
  - `features.md` §1.1 — extend the `NadirPointing` docstring + `velocity_reference` comment
    (≈ lines 206–213); **delete** the failure-modes row `NadirPointing(velocity_reference='ecef')
    → NotImplementedError` (≈ line 363); extend the "Styling / cosmetic plot details deferred"
    note (≈ line 573) to record the new endpoint glyphs (triangle + cone) as the cosmetic baseline.
  - `docs/history/build-plan-feature-1.1.md` ECEF "Notes/deferred" bullet (≈ lines 847–851) —
    **left in place as a historical record, not edited** (per the §1 map).
  - **No `__init__.py` / re-export / exception / signature change** (the addendum adds no new
    public name; architecture §6 inventory and §7 re-export list are untouched).
- **Refresh `CLAUDE.md`** "Project state": ECEF nadir + direction glyphs built; remove
  `NadirPointing(velocity_reference='ecef')` from the validated-skeleton deferrals list (Tier B
  `IncidenceVariableCd` and UT1 remain). (Chunk-completion markers, CHANGELOG narrative, version
  bump, and commits are the **maintainer's** — flag, don't author.)
- `CHANGELOG.md` `[Unreleased]` / `[0.2.0]` — an **Added** line (ECEF nadir yaw-steering) + a
  **Changed** line (direction-indicating plot markers); bump `pyproject.toml` `0.1.0 → 0.2.0`
  (addendum §6). **Maintainer authors these.**
- **Open the PR:** `gh pr create` against `main`, confirm CI green, then
  `gh pr merge --squash --delete-branch` — the maintainer's call on timing.

**You provide:** confirm `gh` authenticated; author the version bump + CHANGELOG entry; give the
go-ahead for the squash-merge (outward actions — Claude won't push/merge/author CHANGELOG without it).

**Verify:** `pytest -v` full suite green; `pre-commit run --all-files` clean; `import propygator
as pgr` stays JVM-free (no new public name to expose); the §1 supersession map is fully carried
into `features.md`/`architecture.md`; the three "star"/"diamond" docstrings are updated.

> ### ✅ Final checkpoint — addendum done
> CLAUDE.md, CHANGELOG, features.md, and architecture.md all reflect ECEF nadir + direction
> glyphs as built; the §1 supersession map is discharged; no new `NotImplementedError`; the
> intended deferrals (Tier B `IncidenceVariableCd`, UT1, backward propagation) untouched.

---

## End-state verification (addendum complete → §8 definition of done)

From repo root, `conda activate propygator`, on the merged branch:
1. **ECEF wired (§8.1):** `_to_provider` lowers `NadirPointing(velocity_reference="ecef")` to a
   working provider (every propagator-invoked method incl. the Field overload), verified inside a
   real box `propagate()`; the `_ECEF_DEFERRED_MESSAGE` raise is removed.
2. **ECEF verified (§8.2):** ECEF-vs-inertial yaw equals the `ω⊕ × r` term (≈ 3.08° at the
   equator, → 0 at max latitude); metadata token + the sphere consistency-warning path unchanged;
   the other six attitude modes regression-free.
3. **Triangle (§8.3):** ground-track end is a heading-oriented triangle; dateline + degenerate
   edges handled; `plot_summary` inherits it via `_draw_ground_track`.
4. **Cone (§8.4):** 3-D end is a velocity-oriented, scene-relative-sized, single-colour cone; one
   `to_frame`; start circle unchanged.
5. **Reconciliation (§8.5):** `style.py` (`MARKER_END` restructured) + docstring edits done;
   `test_plot_3d` cone assertion + `test_style` `MARKER_END` update + ground-track heading
   assertion added; ground-track + `plot_summary` image smokes re-recorded;
   `pre-commit run --all-files` clean.
6. **Tests (§8.6):** JVM-touching paths use the `orekit` fixture.
7. **Docs (§8.7):** the §1 map carried into `features.md`/`architecture.md`; CHANGELOG + CLAUDE.md
   updated; version bumped to `0.2.0` (maintainer).
8. **No new `NotImplementedError` (§8.8);** Tier B `IncidenceVariableCd`, UT1, and backward
   propagation remain untouched. `python -c "import propygator, jpype;
   print(jpype.isJVMStarted())"` → `False`.

## Notes / deferred (not this addendum)

- **Backward-in-time propagation**, **Tier B `IncidenceVariableCd`** runtime, **UT1**, **per-facet
  Sentman drag**, and **RTN/LVLH frames** remain deferred (addendum §0).
- The **Tier B drag interpolation findings** live separately in
  `docs/tier-b-drag-interpolation-findings.md` and are **explicitly not part of this addendum** —
  do not fold them in here.
