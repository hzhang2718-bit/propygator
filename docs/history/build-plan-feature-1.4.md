# Build plan: Feature 1.4 — Real-time tracker

> **Status: BUILD PLAN (not started).** Sequenced, session-sized chunks for the realtime
> primitives + reusable sky-view + live dashboard, modeled on
> `docs/history/build-plan-feature-1.3.md`. The binding contract is `docs/features.md`
> §1.4; the prerequisite/scoping notes are `docs/build-plan-feature-1.3,4-notes.md`.
> Chunk-completion headers, the CHANGELOG, and the release tag are the maintainer's to
> author (trust the git log for true status).

## Context

Feature 1.3 (TLE propagator) shipped in `v0.3.0`; `main`/HEAD is `1b36dca` (one docs
commit past the `v0.3.0` tag), 738 tests pass, and `tle/` + the 1.1 output stack are
built and re-exported. **Feature 1.4, the real-time tracker, is the next feature**
(architecture §12 order: 1.3 → **1.4** → 1.5 → 1.2). It "answers where is this satellite
*now*, and show me" and is mostly **composition** over shipped verbs — it adds little new
physics. Three layers:

1. **Realtime primitives** — `current_state(tle) -> State` (TEME) and
   `current_ground_position(tle) -> GeodeticPosition` (lat/lon/alt), cheap one-shot
   queries (`tracking/realtime.py`).
2. **The reusable sky-view** — the topocentric `look_angles` family + `AzElRange`
   (`core/observation.py`) and the geometry-only `plot_sky_track` / `_draw_sky_track`
   (`plotting/trajectories.py`). Built here because the live dashboard needs a sky panel,
   and **reused verbatim by Feature 1.5** — so building it now pulls 1.5's topocentric
   foundation forward (architecture §12).
3. **The live dashboard** — `live_track(...)`, the substance of the feature: a
   backend-agnostic `matplotlib.animation.FuncAnimation` over a rolling, **now-centred**
   `Trajectory` buffer (`tracking/live.py`), with 3 panels (ground track / altitude /
   speed) or 4 (+ sky view when a `GroundStation` is given). Display-only; not saved.

The end state is a *usable* feature: `pgr.current_ground_position(tle)` gives lat/lon/alt
now; `pgr.plot_sky_track(traj, station)` draws an observer sky view; `pgr.live_track("ISS",
station)` opens a live, self-updating dashboard in a desktop window or a `%matplotlib
widget` notebook canvas — exactly as `docs/features.md` §1.4 and `README.md` show.

**Why this needs a plan (not just "implement §1.4").** §1.4 reads as "composition over
1.1/1.3," but it silently assumes several pieces that **don't exist yet**, plus genuine
edits to *already-shipped* 1.1/1.3 code. The plan sequences them so each is its own early
step, not a mid-feature discovery (build-plan notes "Feature 1.4 build prerequisites"):

- a `StaleTLEWarning(UserWarning)` **category** (shipped 1.3 raises a bare `UserWarning`);
- a public `Trajectory.start_epoch` / `end_epoch` **span accessor** (today private,
  `_epoch_at`);
- **realtime-TTL plumbing** so `fetch_tle` can reach the 6 h `_TTL_REALTIME_S` (today
  unreachable through it);
- the single-shot `_tle_state_at(tle, epoch) -> State` helper the primitives ride on;
- the whole **topocentric kernel** (`look_angles` / `look_angles_track` / `sun_look_angles`
  / `moon_look_angles` / `observer_snapshot` / `AzElRange`) — `core/observation.py` today
  has only the value types `GroundStation` / `GeodeticPosition` / `Pass`;
- the **sky-track plot** (`plot_sky_track` / `_draw_sky_track`) — new;
- additive **seams** in the shipped 1.1 `_draw_speed` / `_draw_ground_track` /
  `_track_heading_deg` primitives (all defaulting to current behaviour → 1.1 snapshots
  stay byte-stable);
- `tracking/` is a bare `__init__.py` stub today.

## Source-of-truth documents (do not silently diverge)

- **`docs/features.md` §1.4** — the binding contract: the `live_track` signature, the
  realtime-primitive signatures, the `AzElRange` / `look_angles` family signatures, the
  `plot_sky_track` signature, the buffer-engine behaviour, the panel set/layout, and the
  per-frame compute/draw split. Most important file. (Buffer *magnitudes* are explicitly
  tunable placeholders, not contract — finalized during the build.)
- **`docs/build-plan-feature-1.3,4-notes.md`** — Note 4 (sky-view relocated to 1.4, with
  the batched-path / `_draw_sky_track`-primitive / 1.5-de-risking refinements) and the
  **"Feature 1.4 build prerequisites"** section (`StaleTLEWarning`, span accessor, TTL
  plumbing). Every prerequisite below traces here. Not a contract; changes no signature.
- **`docs/architecture.md`** — §6 (`AzElRange`/`look_angles`, `TrajectoryMetadata`,
  `Trajectory`), §7 (module tree + dependency rule + the sanctioned lazy-`plotting` import
  exception, the `__init__` re-export list), §8 (1.4 data flow), §10 (the two TTLs +
  Feature-1.4 plumbing note, explicit frames, safe-before-init, Orekit-types-internal,
  Plotly-vs-matplotlib), §11 (testing), §12 (build order), §13 (the resolved 1.4 decisions).
- `docs/history/build-plan-feature-1.3.md` **(RETIRED)** — the model for this plan's **style**
  (per-chunk template, inline checkpoints, git walkthrough, the "new test subpackage" reminder).
- `docs/orekit_setup_reference.md` — JVM boundary patterns. **Self-flagged stale; verify
  against the installed 13.1.x API** before trusting any snippet.

## Decisions locked with the maintainer for this build

- **Scope & git — full feature, single squash-PR.** Build all of 1.4 (primitives + sky-view
  + live dashboard) on the **existing** branch `feature/tle-tracker`, single squash-PR into
  `main` at the end (GitHub Flow, project_meta §3) — mirrors the 1.3 build.
- **Test reference data — Claude self-sources + cross-checks.** The topocentric and Sun/Moon
  validations use *independent cross-checks* (zenith → elevation ≈ 90°, horizon → ≈ 0°,
  range = geometric distance) plus one *transcribed, in-test-cited* published almanac value
  for Sun/Moon az-el — the same self-sourcing approach as 1.3's Vallado vectors. No
  externally-provided reference numbers are a blocker.
- **`fetch_tle` realtime TTL — internal selector (recommended).** Add a keyword-only
  `ttl_s: float | None = None` to `fetch_tle` (forwarded to `fetch_celestrak`; default
  keeps 24 h), so the live/realtime path selects `_TTL_REALTIME_S`. Alternative (the
  live path calls `fetch_celestrak(ttl_s=_TTL_REALTIME_S)` directly) is noted in the
  Chunk-1 review; pick whichever keeps the call graph cleanest.
- **Per-chunk git is the maintainer's to trigger** (standing convention, memory):
  Claude will **not** commit, push, open the PR, write the CHANGELOG, or tag the release
  unasked; on request Claude runs the add/commit/push for a chunk. The release is `v0.4.0`.

**Explicitly OUT of scope for 1.4** (do not build here):
- `find_passes` / `Pass` rise-set-culmination, eclipse/lit shading, brightness/magnitude,
  `plot_sky_chart`, the `core/catalogs.py` magnitude table — all **Feature 1.5**. The
  1.4↔1.5 line: `plot_sky_track` draws **geometry only**.
- Planet markers in the sky panel (`CelestialBodyFactory` + DE ephemeris) and bright-star
  markers — deferred / out of scope (features §1.4 "Still open").
- A `tz=` parameter on `live_track`, time-acceleration, saving the animation to mp4/gif,
  off-thread rebuild, blitting — all deferred (features §1.4 "Still open"). The clock seam
  is built **tz-ready** (UTC now) so the future `tz=` lands additively.

## Architecture invariants to honor in every chunk (CLAUDE.md / architecture §4, §10)

Orekit types stay internal (public APIs accept/return only propygator types); import
`jpype`/`orekit_jpype`/`pyhelpers` **lazily inside functions**, never at module top; **all
JVM/topocentric geometry stays in `core/`** so `tracking/live.py` is pure composition (no
Orekit code in `live.py`); SI internally; **frames explicit** (`current_state` returns TEME,
no silent conversion; functions returning non-frame-carrying types — `GeodeticPosition`,
`AzElRange` — may convert internally); `pathlib.Path`; `logging`, never `print`; frozen
dataclasses with `__post_init__` validation. **`tracking/live.py` lazy-imports `plotting/`
+ matplotlib in-body** (the `export_all` precedent, architecture §7) so the engine's
static module graph stays clean and adds no new import edge; `import propygator` stays
**JVM-free** (matplotlib is *already* loaded at import by the top-level `plot_*` verbs —
a deliberate public-namespace choice, architecture §7/§10 — so the package is not, and
never was, matplotlib-free on import; the in-body imports only keep `live.py` itself a
clean headless leaf). **One-JVM-per-process
test ordering:** every JVM-touching test acquires the JVM via the `orekit` fixture so
`conftest.py`'s hook schedules it after the pure-Python `tests/core/*` "no JVM started"
guards.

## How to use this plan

- **10 numbered chunks (Chunk 0 = branch setup + commit plan)**, each sized for one Claude
  Code session and independently verifiable. Run in order — later chunks depend on earlier.
- Each chunk lists **Goal / Create-edit / Reuse / You provide / Verify**. **You provide** is
  called out every chunk (often "nothing") so you know whether a session needs input.
- **Checkpoints** (CLAUDE.md refresh + `/code-review` + `/simplify`) are marked inline after
  Chunk 5 (the reusable layer is done) and Chunk 8 (the dashboard is whole) — the moments to
  consolidate before the next layer.
- Adjacent small chunks (3+4 the `core/observation.py` kernel; 1+2 if a session has
  capacity) can be merged — they're split for safety, not because they must be separate.
- **Per-chunk git rhythm** (the "you run" each chunk): `git add -A` →
  `git commit -m "Feature 1.4 chunk N: <summary>"` → `git push`. Commit at the end of each
  chunk or more often.
- **New test subpackage:** Chunk 2 is the first to touch `tracking/`, so it must create
  `tests/tracking/__init__.py` or `pytest tests/tracking` collects nothing (the existing
  `tests/{core,io,plotting,propagation,tle}/__init__.py` are the precedent).

---

## Git: the feature-branch walkthrough (read once, before Chunk 1)

The branch already exists (`feature/tle-tracker`, even with `main`, clean tree) but is **not
yet pushed** to `origin`. Short form (the full tutorial is in
`docs/history/build-plan-feature-1.1.md`).

**One-time, before Chunk 1:**
```powershell
conda activate propygator
git switch feature/tle-tracker        # already on it; confirm
git push -u origin feature/tle-tracker  # set upstream so CI runs on the branch
```

**At the very end (Chunk 9):**
```powershell
gh pr create --base main --head feature/tle-tracker `
  --title "Feature 1.4: real-time tracker" --body "..."
# CI green on the PR, then:
gh pr merge --squash --delete-branch
git switch main; git pull
git tag v0.4.0      # you author the release + CHANGELOG (your standing convention)
git push --tags
```

**You provide (git):** `gh` installed + authenticated before Chunk 9 (only needed at the
end). Claude will not commit/push/PR/tag/CHANGELOG without being asked.

---

## Chunk 0 — Branch setup + commit this plan - Done

**Goal:** start the feature line and commit this plan as its first commit.

**Create-edit:** push the existing `feature/tle-tracker` upstream (above); commit this
`docs/build-plan-feature-1.4.md` as the first commit on the branch.

**You provide:** confirmation to start (and that Claude may drive git, if desired).

**Verify:** `git branch` shows `* feature/tle-tracker`; `git push` set the upstream; the
plan is committed; CI runs on the branch.

---

## Chunk 1 — Shipped-code prerequisites (small additive edits to 1.1/1.3) - Done

**Goal:** land the three small additive edits to *already-shipped* code that the realtime
layer and the live engine depend on — each independently testable — before any new
subsystem. A clean warm-up chunk; no new physics.

**Create-edit:**
- `core/exceptions.py` — add **`class StaleTLEWarning(UserWarning)`** (beside the existing
  exception classes; it is a *warning*, not a `PropygatorError`). A `UserWarning` subclass,
  so it is additive and backward-compatible (existing `UserWarning` filters still match it).
- `tle/propagator.py` — pass **`category=StaleTLEWarning`** at the existing stale-TLE
  `warnings.warn(...)` site (`propagator.py:105`); import the class. Behaviour/message
  unchanged — only the category is now specific, so the live engine can suppress *this*
  warning surgically without swallowing all `UserWarning`s.
- `core/states.py` — add public **`start_epoch`** / **`end_epoch`** properties on
  `Trajectory` (thin read-only wrappers over `self._epoch_at(0)` / `self._epoch_at(-1)`; no
  JVM). These are the *realized* span endpoints `Trajectory.at` already bounds-checks
  against (`states.py:684`) — the single source of truth the engine clamps to. Independently
  useful (1.5 walks dense trajectories too).
- `tle/sources.py` — add keyword-only **`ttl_s: float | None = None`** to `fetch_tle`,
  forwarded to `fetch_celestrak(ttl_s=...)` when set (default `None` keeps the 24 h general
  TTL). The live/realtime path passes `_TTL_REALTIME_S` (6 h). (`fetch_celestrak` already
  takes `ttl_s`; this just makes it reachable through `fetch_tle` — architecture §10 the
  Feature-1.4 plumbing note.)
- Re-export `StaleTLEWarning` from the top-level `__init__.py` (`__all__` + import), beside
  the other exception/warning types.

**Reuse:** the existing warning/exception module; `Trajectory._epoch_at`;
`fetch_celestrak(ttl_s=...)` (already parameterized).

**You provide:** confirm the `fetch_tle` realtime-TTL approach (recommended: the `ttl_s`
param above vs. the live path calling `fetch_celestrak` directly).

**Verify:** targeted tests — `StaleTLEWarning` subclasses `UserWarning`; `propagate_tle`'s
stale warn is now `pytest.warns(StaleTLEWarning)` **and** 1.3's existing
`pytest.warns(UserWarning)` stale test still passes (backward-compat); `Trajectory.start_epoch
== _epoch_at(0)` / `end_epoch == _epoch_at(-1)` with the JVM down (pure-Python, in the
`tests/core` no-JVM suite); `fetch_tle(..., ttl_s=_TTL_REALTIME_S)` forwards the 6 h TTL
(mock the HTTP/cache layer, `tmp_path` cache dir). `import propygator` still JVM-free.

---

## Chunk 2 — Realtime primitives (`tracking/realtime.py`) + `_tle_state_at` - Done

**Goal:** the cheap "where is it now" layer — `current_state` / `current_ground_position` —
and the shared single-shot TEME-`State` helper they ride on. First code in `tracking/`.

**Create-edit:**
- `tle/propagator.py` — add **`_tle_state_at(tle, epoch) -> State`**:
  `TLEPropagator.selectExtrapolator(tle.to_orekit())` → `propagate(epoch.to_orekit())` →
  `getPVCoordinates(Frame.TEME.to_orekit())` → `State(epoch, pos, vel, Frame.TEME)`.
  JVM-touching (reuse the `propagate_tle` JVM idiom). **Deliberately *not* `propagate_tle`'s
  per-sample loop body** — it builds its own propagator for one point, so `propagate_tle`'s
  hoisted-propagator loop is untouched (features §1.4 "Real-time primitives").
- New **`tracking/realtime.py`**:
  - `current_state(tle: TLE) -> State` — `_tle_state_at(tle, Epoch.now())`; returns TEME, no
    conversion (architecture §10; users call `.to_frame(...)`).
  - `current_ground_position(tle: TLE) -> GeodeticPosition` —
    `to_geodetic(_tle_state_at(tle, Epoch.now()).to_frame(Frame.ITRF))`; returns lat/lon/alt
    directly (carries no `Frame`, so the internal TEME→ITRF→geodetic conversion is allowed).
- Re-export `current_state` / `current_ground_position` from the top-level `__init__.py`.
- New **`tests/tracking/__init__.py`** (first `tracking/` test subpackage — else collection
  is empty). `tests/tracking/test_realtime.py` (`orekit` fixture): `_tle_state_at(tle,
  fixed_epoch)` equals `propagate_tle(tle, small_dur, output_step=small)[0]` at that epoch
  (identical SGP4 evaluation at `start`); `current_state(tle).frame is Frame.TEME`;
  `current_ground_position(tle)` returns a `GeodeticPosition` with ISS-plausible
  lat/lon/alt; both reuse the `tests/core/test_tle.py` ISS fixture. For determinism, freeze
  `Epoch.now` via monkeypatch (or assert frame/shape only).

**Reuse:** `propagate_tle`'s JVM idiom + `tle.to_orekit()`; `Epoch.now()`; `to_geodetic`
(`core/frames.py`); `State.to_frame`; the `tests/core/test_tle.py` ISS fixture.

**You provide:** nothing (reuses the 1.3 ISS fixture).

**Verify:** `pytest tests/tracking/test_realtime.py` green; `import propygator;
propygator.current_state` resolves with the JVM down.

---

## Chunk 3 — Topocentric kernel: `AzElRange` + `look_angles` + `look_angles_track` - Done

**Goal:** the observer-centric counterpart to `to_geodetic` / `geodetic_track` — the value
type plus the single-shot and batched look-angle primitives over one shared private
station-`TopocentricFrame` builder. The piece **1.5 reuses verbatim**.

**Create-edit:**
- `core/observation.py`:
  - **`@dataclass(frozen=True) class AzElRange`** (`azimuth_deg` 0=N→E clockwise;
    `elevation_deg` 0=horizon, +90=zenith, negative below; `range_m`) — pure-Python,
    **safe-before-init**, finiteness validation in `__post_init__` like its siblings.
  - private **`_station_topocentric_frame(station)`** — lazy-import jpype, `_ensure_started()`,
    build an Orekit `TopocentricFrame` on `core/bodies._earth()` at the station's geodetic
    point. The one shared kernel.
  - private projection helper turning a body PV (in some frame) + the station frame + epoch
    into an `AzElRange` (`getAzimuth` / `getElevation` / `getRange`).
  - **`look_angles(station, state) -> AzElRange`** — build the frame once, project `state`'s
    PV at `state.epoch`. Converts input internally (no frame demanded — `AzElRange` carries
    no `Frame`, mirroring `to_geodetic`'s allowance).
  - **`look_angles_track(station, trajectory) -> (az[], el[], range[])`** float64 arrays —
    build the station frame **once**, loop samples. The batched analogue of `geodetic_track`,
    but **station-keyed → NOT memoized on the `Trajectory`** (the engine holds the arrays).
  - Update the module docstring: the value types stay "never touches the JVM," but carve out
    that the `look_angles` / `look_angles_track` *calls* do (the `to_geodetic` precedent).
- Re-export `AzElRange` + `look_angles` from the top-level `__init__.py` (per architecture
  §7 the batched `look_angles_track` stays reachable via `propygator.core.observation`).
- Tests: add a pure-Python `AzElRange` construction/validation test to the existing
  **`tests/core/test_observation.py`** (stays in the no-JVM suite). The JVM look-angle tests
  go in a **fixture-gated** new file `tests/tracking/test_observation.py` (`orekit` fixture).
  Self-sourced cross-checks: a `State` placed at the station's local **zenith** → elevation
  ≈ 90°; far on the **horizon** → ≈ 0°; `range_m` ≈ the geometric station→satellite distance;
  `look_angles_track` arrays equal per-sample `look_angles` over a short trajectory.

**Reuse:** `to_geodetic` / `geodetic_track` (`core/frames.py`) as the structural template;
`core/bodies._earth()`; `Epoch.to_orekit`; the `Frame.to_orekit` idioms.

**You provide:** nothing (self-sourced cross-checks, per the locked decision).

**Verify:** the pure-Python `AzElRange` test runs in the no-JVM `tests/core` suite; the JVM
cross-checks pass; `import propygator; propygator.look_angles` resolves JVM-free; `tests/core`
still asserts no JVM started.

---

## Chunk 4 — Sun/Moon look-angles + `observer_snapshot` (`core/observation.py`) - Done

**Goal:** the same topocentric kernel projecting the **Sun** and **Moon** (the dashboard sky
tint/markers, and 1.5's observer-darkness gate), plus the combined per-frame
`observer_snapshot` that projects satellite + Sun + Moon from **one** station-frame build.

**Create-edit:**
- `core/observation.py`:
  - **`sun_look_angles(station, epoch) -> AzElRange`** / **`moon_look_angles(station, epoch)
    -> AzElRange`** — build the station frame once, project `core/bodies._sun()` /
    `_moon()`'s position at `epoch` through the shared projection helper.
  - **`observer_snapshot(station, epoch, state) -> (sat, sun, moon)`** AzElRange triple —
    build the station frame **once**, project all three (the live dashboard's per-frame
    batch; calling the three singles separately would rebuild the identical frame 3×).
- Re-export `sun_look_angles` / `moon_look_angles` from the top-level `__init__.py`
  (`observer_snapshot` stays in `core.observation`, like `look_angles_track`).
- Tests (`tests/tracking/test_observation.py`, `orekit` fixture): Sun/Moon az-el at a known
  station + epoch vs. a **transcribed, in-test-cited** published almanac value, coarse
  tolerance (~0.5–1°, almanac vs. Orekit-DE differ slightly); `observer_snapshot` returns the
  same three `AzElRange`s as the separate `look_angles` / `sun_look_angles` /
  `moon_look_angles` calls (one frame build).

**Reuse:** the Chunk-3 private kernel (`_station_topocentric_frame` + projection helper);
`core/bodies._sun()` / `_moon()` (already built for SRP/third-body).

**You provide:** nothing (Claude transcribes + cites a public almanac value per the locked
decision; you may optionally name a preferred station/epoch).

**Verify:** Sun/Moon almanac agreement within tolerance; `observer_snapshot` consistency; the
re-exports resolve JVM-free. (Chunks 3+4 may be done in one session — both edit
`core/observation.py`.)

---

## Chunk 5 — Sky-track plot: `plot_sky_track` + `_draw_sky_track` - Done

**Goal:** the geometry-only polar sky view — a thin verb over a `_draw_sky_track(ax, ...)`
primitive, sharing one drawing path with the dashboard's sky panel; **reused verbatim by
1.5**.

**Create-edit:**
- `plotting/trajectories.py`:
  - **`_draw_sky_track(ax, trajectory, station, *, min_elevation_deg=0.0, azel=None,
    track_style=None, warn_never_visible=True)`** — matplotlib **polar** projection: North at
    top, azimuth clockwise (`set_theta_zero_location('N')`, `set_theta_direction(-1)`); radius
    = zenith angle so **zenith at centre, horizon at rim** (el 90°→0° ⇒ r 0°→90°). Maps the
    trajectory via `look_angles_track` (one `TopocentricFrame`) **unless** a precomputed
    `azel=(az,el,range)` is handed in (the dashboard seam — no per-frame JVM). Fixed light-blue
    disk; single dark-blue track (not the time gradient). **Disjoint arcs:** mask samples below
    `min_elevation_deg` to `NaN` so the pen lifts between passes (no chord across the disk).
    **Never-visible:** if no sample clears the horizon, draw the empty disk and
    `warnings.warn` once — *suppressible* via `warn_never_visible=False` (the live dashboard,
    where a transient blank sky is normal). `track_style` is the optional styling seam
    (default = the contract dark-blue line; the dashboard overrides it with a halo stroke).
  - **`plot_sky_track(trajectory, station, *, min_elevation_deg=0.0) -> Figure`** — thin
    wrapper mirroring `plot_ground_track`: `_require_min_samples`, `_mpl_style`,
    `_draw_sky_track(ax, ...)`, `_suptitle_from_metadata`, `tight_layout`. Returns the native
    matplotlib `Figure`.
- Add `plot_sky_track` to `plotting/__init__.py` `__all__`/imports and re-export from the
  top-level `__init__.py`.
- Tests (`tests/plotting/test_trajectories.py` or a new `test_sky_track.py`): a **snapshot**
  of `plot_sky_track` over an ISS TLE + a station with ≥1 pass (architecture §11 plot-snapshot
  strategy); the **never-visible** case draws the empty disk + warns once (`pytest.warns`);
  the **NaN-masking** lifts the pen between passes (assert the plotted theta/r contain NaN
  separators, no chord). Note (Note 5): the sky view is observer-relative az/el, independent
  of the trajectory's frame, so a TEME (ECI) input is fine and there is no coastline concern.

**Reuse:** `look_angles_track` (Chunk 3); the `_draw_*` / `plot_*` wrapper pattern
(`plot_ground_track`, `timeseries.py`); `_require_min_samples` / `_mpl_style` /
`_suptitle_from_metadata`.

**You provide:** a station + ISS TLE + span that yields a visible pass for the snapshot, or
confirm Claude may pick one (e.g. the 1.3 ISS fixture + a mid-latitude station over ~1 day).

**Verify:** `pytest tests/plotting` green incl. the new sky snapshot(s); `plot_sky_track`
returns a matplotlib `Figure`; the polar conventions are correct (zenith centre, N-up
clockwise); the standalone verb keeps the warn-once.

> **Checkpoint after Chunk 5.** Refresh CLAUDE.md "Project state": the realtime primitives,
> the full `core/observation.py` topocentric kernel, and `plot_sky_track` are landed;
> `tracking/` is no longer a bare stub. Run `/code-review` then `/simplify` on the branch
> diff; address findings. **Everything to here is the reusable, 1.5-shared layer** — complete
> and self-contained before the dashboard.

---

## Chunk 6 — Dashboard plot-primitive seams (additive to the shipped 1.1 `_draw_*`) - Done

**Goal:** grow the precise additive seams the live dashboard needs into the shipped 1.1
primitives — **all defaulting to current behaviour** so 1.1's snapshot tests stay
**byte-stable** (the checkpoint to hold). Isolated here so the byte-stability gate is the
chunk's whole verification.

**Create-edit:**
- `plotting/timeseries.py` — **`_draw_speed(ax, traj, *, frame=None, speeds_kms=None,
  color=None, label=None)`**: when `speeds_kms` is supplied, plot it directly (no `to_frame`),
  draw with `color`/`label` + a **legend** instead of the single-frame **title**, and treat
  `frame` as optional (it drives neither the conversion nor the title once `speeds_kms` is
  given). Default path (`speeds_kms=None`) is byte-identical to today (compute via
  `to_frame(frame)`, single title) — so two frames can share one axis cheaply and the live
  redraw never re-runs `to_frame`.
- `plotting/trajectories.py`:
  - **`_track_heading_deg(lon, lat, *, at_index=None)`** — `None` → today's last-valid-segment
    behaviour (unchanged); an index → the heading of the segment **bracketing** that index, so
    the live current-position marker takes its heading from the buffer segment around `now`,
    not the end of track.
  - **`_draw_ground_track(..., endpoint_labels=None / suppress_end_marker=False)`** (one new
    optional seam) — relabel the buffer endpoints **past edge** / **future edge** (or suppress
    the end triangle) for the centred buffer, where the "end" is the *future* leading edge, not
    where the satellite is. Default = today's start/end + end triangle.

**Reuse:** the existing `_draw_speed` / `_draw_ground_track` / `_track_heading_deg`.

**You provide:** nothing.

**Verify:** **1.1's existing plot snapshot tests are byte-stable** — the critical gate; run
`pytest tests/plotting` and confirm `test_timeseries` / `test_trajectories` / `test_composite`
snapshots are unchanged. New unit tests exercise each seam (a precomputed `speeds_kms` path
with legend; `_track_heading_deg(at_index=...)`; the endpoint relabel/suppress). `plot_speed`
/ `plot_ground_track` output unchanged.

---

## Chunk 7 — The buffer engine (pure, headless-testable) in `tracking/live.py` - Done

**Goal:** the symmetric-buffer state machine — **no matplotlib** — that the `FuncAnimation`
driver sits on. Tested headlessly; the design's explicit seam (features §1.4 "Buffer engine").

**Create-edit:**
- New **`tracking/live.py`** — the engine (a small class or closure; no display):
  - **Target resolution:** a `TLE` → re-propagate only; a name / NORAD `int` → `fetch_tle`
    (with the realtime TTL, Chunk 1) → mark as **auto-refresh**.
  - **Buffer build:** a `Trajectory` centred on `now` over `[now − half_window_s, now +
    half_window_s]` via `propagate_tle`, propagated with a small **leading guard margin** past
    the displayed edge so the realized last sample sits beyond `now + half_window_s` even
    across a blocking rebuild.
  - **Drain-triggered rebuild:** rebuild when `now` reaches the displayed leading edge — **not**
    on the `refresh_s` tick; re-fetch (fetched targets) rides on the rebuild.
  - **Per-frame state:** `buffer.at(min(now, buffer.end_epoch))` — clamp to the realized span
    endpoint via Chunk-1's `end_epoch` accessor (never re-derive the sample grid), so a stall
    degrades to a frozen marker, not a `Trajectory.at` out-of-span `ValueError`.
  - **Stale handling:** check staleness **once at startup** → single notice; suppress the
    per-rebuild `StaleTLEWarning` for the session (Chunk 1's category) — not a blanket
    `UserWarning` swallow (a genuine decay still raises `TLEPropagationError`).
  - **Precompute-per-rebuild seam:** compute once per buffer and hold for its lifetime — the
    ITRF speed array (one `to_frame(ITRF)`), the inertial speed read **straight off**
    `buffer.velocities` (rotation-invariant `|v|`, no conversion), and (with a station) the
    `look_angles_track` az/el arrays. (`geodetic_track` is auto-memoized on the buffer.)
  - Buffer **magnitudes** (`output_step` / `half_window_s` / `refresh_s`) wired as parameters;
    starting values are the design placeholders, tuned in Chunk 8.
- Tests `tests/tracking/test_live_engine.py` (`orekit` fixture, **headless** — matplotlib
  never imported): with a frozen `now` (monkeypatch `Epoch.now`) the buffer is centred and
  spans window + guard; a rebuild triggers when the frozen clock crosses the leading edge, not
  on a refresh tick; `buffer.at(min(now, end_epoch))` never raises at/just past the realized
  edge; a fetched target re-fetches on rebuild while a raw TLE does not (mock `fetch_tle`); a
  pre-stale raw TLE emits exactly **one** startup notice and **no** per-rebuild repeat; the
  precomputed arrays match a direct compute.

**Reuse:** `propagate_tle`; `Trajectory.at` + `start_epoch` / `end_epoch` (Chunk 1);
`geodetic_track`; `look_angles_track` (Chunk 3); `fetch_tle(ttl_s=...)` (Chunk 1);
`StaleTLEWarning` (Chunk 1).

**You provide:** the buffer-magnitude starting values, or accept the design placeholders
(`output_step=10 s`, `half_window_s=2700 s`, `refresh_s=1 s`) to tune in Chunk 8; confirm the
auto-refresh + startup-stale-suppress behaviour.

**Verify:** `pytest tests/tracking/test_live_engine.py` green **headlessly** (the engine
never touches matplotlib — asserted by AST-checking that `tracking/live.py` has **no
top-level matplotlib / plotting / Orekit import**, since a `sys.modules` check can't
isolate it: the package already loads matplotlib at import via the re-exported `plot_*`
verbs); `import propygator` stays **JVM-free** (it is *not* matplotlib-free — by design,
architecture §7/§10).

---

## Chunk 8 — The `FuncAnimation` driver + dashboard panels + `live_track` - Done

**Goal:** wrap the engine in a backend-agnostic `matplotlib.animation.FuncAnimation`, assemble
the adaptive 3-/4-panel `GridSpec`, wire the per-frame **O(1)** redraw through the Chunk-6
seams + `observer_snapshot`, and ship `live_track`.

**Create-edit:**
- `tracking/live.py` — **`live_track(target, station=None, *, output_step=…, half_window_s=…,
  refresh_s=…) -> FuncAnimation`** (the **exact** §1.4 signature; `target: TLE | str | int`).
  **Lazy-import `plotting/` + `matplotlib` (incl. `.animation`) in-body** (the `export_all`
  precedent).
  - **Layout:** adaptive `GridSpec` — 3-panel `GridSpec(3,1,height_ratios=[2,1,1])` (ground
    track hero row, altitude, speed; time-series share the x-axis); 4-panel `GridSpec(3,2,
    height_ratios=[2,1,1], width_ratios=[1.4,1])` with the square sky polar spanning rows 1–2
    in col 1 (added only when `station` is given). Ratios are tunable placeholders.
  - **Per-frame `update()` (all O(1)):** read `now` from the wall clock; `state_now =
    buffer.at(min(now, end_epoch))`; **one** `itrf_now = state_now.to_frame(ITRF)` reused for
    the sub-satellite marker + the live title (`to_geodetic` → lat/lon/alt) + the heading glyph
    via `_track_heading_deg(at_index=…)`; the two-frame speed overlay via the precomputed
    `_draw_speed(speeds_kms=…, color/label)`; the sky panel via `_draw_sky_track(azel=…,
    track_style=halo, warn_never_visible=False)` + `observer_snapshot(station, now, state_now)`
    for the live glyph + Sun/Moon markers + sun-tinted background; `axvline` now-cursors on the
    two time-series; a **UTC clock** via a tz-ready seam — a small `_format_clock(epoch, tz=
    timezone.utc)` over `Epoch.to_datetime()` (UTC now; additive `tz=` later, no core change).
    v1 = clear-and-redraw.
  - Return the `FuncAnimation`; document that the caller **must keep a reference**
    (`anim = live_track(...)`) and the `%matplotlib inline` non-animation caveat.
- Re-export `live_track` from the top-level `__init__.py`.
- Tests: per the design the **animation loop is not snapshot-tested**. Add a headless **smoke**
  test (force the `Agg` backend) that `live_track(...)` builds a `FuncAnimation` and a single
  `update(0)` runs without error against a frozen clock (both 3-panel and 4-panel-with-station)
  — exercising the wiring without asserting pixels.

**Reuse:** the Chunk-7 engine; the Chunk-6 `_draw_*` seams; `observer_snapshot` /
`sun_look_angles` (Chunk 4); `_draw_sky_track` (Chunk 5); `_draw_altitude` /
`_draw_ground_track`; `Epoch.to_datetime` (`core/time.py`); the `export_all` lazy-import idiom.

**You provide:** `GridSpec` ratio preferences (or accept placeholders); final buffer-magnitude
tuning against look/feel; a **live visual check on your machine** under a GUI backend
(`%matplotlib qt` / a `%matplotlib widget` notebook) — the animation can't be CI-verified.

**Verify:** the headless smoke test passes; **you** confirm the live dashboard renders +
animates (3-panel, and 4-panel with a station) in a GUI / notebook-widget backend; the
`live_track` re-export adds no new import cost — its matplotlib / `plotting` imports are
in-body, so `import propygator` stays **JVM-free** and gains no matplotlib beyond what the
top-level `plot_*` verbs already load.

> **Checkpoint after Chunk 8** — the dashboard is whole. Refresh CLAUDE.md; run `/code-review`
> then `/simplify` over the full branch diff; address findings. Consolidation before the
> docs/merge wrap-up.

---

## Chunk 9 — Wrap-up: docs reconciliation, CI parity, review, merge - Done

**Goal:** make the docs match the built reality, prove the whole suite + hooks are green, and
land 1.4 on `main`.

**Create-edit / actions:**
- **Docs reconciliation:**
  - `architecture.md` §7 tree — mark built: `tracking/realtime.py` (`current_state` /
    `current_ground_position`) + `tracking/live.py` (`live_track`); `core/observation.py`
    extended with the look-angle kernel (`look_angles` / `look_angles_track` /
    `sun_look_angles` / `moon_look_angles` / `observer_snapshot` + `AzElRange`);
    `plotting/trajectories.py` `plot_sky_track` / `_draw_sky_track`.
  - `architecture.md` §10 — the caching note: `fetch_tle` now reaches the 6 h realtime TTL
    (the Feature-1.4 plumbing note resolved); the **safe-before-init** list — add `AzElRange`
    (safe) and `look_angles` / `look_angles_track` / `sun_look_angles` / `moon_look_angles` /
    `observer_snapshot` (the JVM-startup list).
  - `features.md` §1.4 — flip status DRAFTED → BUILT/SHIPPED; record the **finalized buffer
    magnitudes** (replace the placeholders); fold the "build prerequisite" parentheticals
    (TTL plumbing, `StaleTLEWarning`, `start_epoch`/`end_epoch`) now that they're built.
  - `docs/build-plan-feature-1.3,4-notes.md` — mark the "Feature 1.4 build prerequisites"
    items built.
  - `CLAUDE.md` "Project state" — 1.4 built + re-exported (`current_state` /
    `current_ground_position` / `live_track` / `look_angles` / `sun_look_angles` /
    `moon_look_angles` / `AzElRange` / `plot_sky_track` / `StaleTLEWarning`); `tracking/` no
    longer a stub; **next feature is 1.5**.
  - Move `docs/build-plan-feature-1.4.md` → `docs/history/` (the established post-merge
    archive step).
- **CI parity:** full `conda run -n propygator pytest` green; `pre-commit run --all-files`
  green (ruff-check + ruff-format + mypy over `src`+`scripts` + nbstripout + hygiene).
- **Review:** `/code-review` then `/simplify` over the full branch diff; address findings.
- **Merge (maintainer triggers):** open the squash-PR, CI green, `gh pr merge --squash
  --delete-branch`, then `v0.4.0` tag + CHANGELOG (maintainer authors these).

**Reuse:** the 1.3 Chunk-9 wrap-up rhythm (CI parity + review + docs reconciliation) as the
template.

**You provide:** `gh` authenticated; you drive the PR / merge / tag / CHANGELOG.

**Verify:** `pytest` + `pre-commit` both green on a clean tree; `import propygator` exposes
`current_state` / `current_ground_position` / `live_track` / `look_angles` / `sun_look_angles`
/ `moon_look_angles` / `AzElRange` / `plot_sky_track` and stays **JVM-free** (matplotlib is
loaded at import by the `plot_*` verbs, by design — not matplotlib-free); the
README/§1.4 examples run end-to-end.

---

## End-to-end verification (the "usable feature" gate)

After Chunk 9, this must work in an activated env (`conda run -n propygator python`):

```python
import propygator as pgr
tle = pgr.fetch_tle("ISS")                      # CelesTrak (24 h cache); name populated
gp = pgr.current_ground_position(tle)           # lat/lon/alt right now (no frame)
st = pgr.current_state(tle)                      # State in TEME
assert st.frame is pgr.Frame.TEME

durham = pgr.GroundStation("Durham", 36.0, -78.9)
traj = pgr.propagate_tle(tle, 86400, output_step=60)   # TEME Trajectory
ae = pgr.look_angles(durham, traj[0])           # AzElRange (az/el/range), input auto-converted
fig = pgr.plot_sky_track(traj, durham)          # geometry-only polar sky view (matplotlib)

# Live dashboard (GUI backend / %matplotlib widget; keep the reference):
anim = pgr.live_track("ISS", durham)            # 4-panel live view; or pgr.live_track("ISS") for 3-panel
```

Plus: `import propygator` does not start the JVM (it *does* load matplotlib at import via
the re-exported `plot_*` verbs — by design, architecture §7/§10 — so it is JVM-free but not
matplotlib-free); the `tracking/live.py` engine module itself imports no matplotlib at its
module top (the display imports are in-body); the
`tests/core/*` suite still asserts "no JVM started"; the look-angle cross-checks and the
Sun/Moon almanac agreement pass; the buffer engine's headless tests pass; 1.1's plot snapshots
stay byte-stable through the Chunk-6 seams; the live animation is verified visually (not in CI).

## Chunk dependency map

```
0 branch setup + commit plan
1 prerequisites: StaleTLEWarning + start/end_epoch + fetch_tle ttl_s ──┐
2 realtime primitives + _tle_state_at            (needs 1)             │
3 core/observation kernel: AzElRange + look_angles(_track) ──┐         │
4 sun/moon look-angles + observer_snapshot       (needs 3)   │         │
5 plot_sky_track + _draw_sky_track               (needs 3)   ◀ Checkpoint (reusable layer done)
6 dashboard _draw_* seams (1.1 byte-stable)                  (independent; needs nothing new)
7 buffer engine (headless)                       (needs 1,3; uses propagate_tle/fetch_tle)
8 FuncAnimation driver + live_track              (needs 5,6,7)  ◀ Checkpoint (dashboard whole)
9 wrap-up: docs + CI + review + merge            (needs all)    ◀ final review + merge
```
Mergeable if a session has capacity: **3+4** (one `core/observation.py` session), **1+2**.
Independent of the dashboard line: **5** (and **6** can be done any time after Chunk 0).
