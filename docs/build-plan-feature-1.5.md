# Build plan: Feature 1.5 — Ground passes + brightness (`find_passes`)

> **Status: BUILD PLAN (not started).** Derived from `features.md` **§1.5** (drafted
> 2026-07-07), which is the **binding contract** for this work — every signature,
> semantic rule, and failure row below traces to it, cited inline as "(contract:
> <heading>)". Where this plan and the contract disagree, the **contract wins**; fix
> the plan. Status headers are the maintainer's — trust the git log for true status.

## Context

The synthesis feature: `find_passes(tle, station, duration, *, start=None,
min_elevation_deg=10.0, visible_only=True, standard_magnitude=None, progress=True)
-> list[Pass]`, plus five consumers (`passes_to_dataframe`, `plot_sky_chart`,
`plot_pass_timeline`, `export_passes_csv`, `export_passes_ics`). It is composition
over shipped primitives — `propagate_tle`, the `core/observation.py` topocentric
kernel, the `core/progress.py` reporter — with the only new physics being the
conical-umbra shadow test and the phase-law magnitude (contract: intro).

**End state:** the README's "Coming next" example runs verbatim; a visual observer
gets tonight's ISS passes as a DataFrame, a calendar file, a sky chart, and a
timeline; `Pass` carries the three new azimuth fields; all six surfaces are
top-level exports.

**Risk profile: low.** No new Orekit interface proxies, no estimation loop, no new
dependencies. The two things that can genuinely go wrong — pass times disagreeing
with reality, and the magnitude convention being off by the qsmag offset — each get
an explicit verification gate below.

### Source-of-truth docs (do not silently diverge)

- `docs/features.md` **§1.5** — the binding contract (Public signature, Pass
  semantics, the `Pass` extension, Search algorithm, Lighting model, Brightness,
  Outputs, Time zones, Progress, Failure modes, Testing, Resolved decisions).
- `docs/architecture.md` §6 (`Pass`, updated 2026-07-07), §7 (module homes +
  dependency rule), §10 (explicit-frame rule; safe-before-init vs JVM-startup
  lists — extended in Chunk 6), §3 (magnitude-table citation requirement).
- `docs/history/build-plan-feature-1.3,4-notes.md` Note 4 — the sky-view relocation
  record and the *resolved* sampling-vs-event finder choice (see "Decisions already
  locked").
- `docs/history/general-upgrades-1.md` Part A/Part B — the inherited `tz=` and
  `progress` surfaces (both shipped; 1.5 only consumes them).

### Decisions already locked (do not relitigate)

- **Sampling-based finder, not event-based** — the resolution of the Note-4 open
  choice. Rationale: (a) it reuses the shipped batched `look_angles_track` kernel
  verbatim (the 1.4 forward-pull realized); (b) an event-based finder would need
  *three* new detector wirings (elevation crossing, elevation extremum, eclipse)
  through the `FunctionalDetector` proxy pattern on a `TLEPropagator` — new JVM
  surface for no accuracy gain at the contract's ~0.5 s refinement tolerance;
  (c) SGP4 evaluation is analytic and cheap, so dense sampling costs nothing.
  The event-based route (`ElevationDetector`) stays the named alternative **only if**
  grazing-pass coverage (below) proves unreliable under sampling.
- **`visible_only=True` default**; visibility = "sunlit ∧ observer dark (Sun el ≤
  −6°) at some point while above the gate" (contract: Pass semantics).
- **`Pass` gains exactly three `None`-default azimuth fields** (contract: The `Pass`
  type; architecture §6 already updated). No stored sky arc.
- **`tz=` on the formatters, not `find_passes`** (contract: Time zones; the approved
  deviation recorded in `docs/history/general-upgrades-1.md` Part A).
- **Conical umbra, penumbra = lit; refraction out of scope** (contract: Lighting
  model).
- **`compute_magnitude(state, station, standard_magnitude)` requires EME2000 and
  does not check eclipse** (contract: Brightness; architecture §10).
- **No bespoke text-table formatter; ICS is hand-rolled UTC; CSV is UTC-only**
  (contract: Outputs).
- **1.5 ships as its own tagged release** (the v0.1.0–v0.4.0 per-feature pattern;
  version number is the maintainer's call at release prep).

### Decisions to confirm (defaults chosen; "You provide" flags them)

- **Reference station + TLE for the cross-check fixture (Chunk 3).** Default: a
  fixed historical ISS TLE + the README's Durham station (35.99°N, 78.90°W, 130 m).
- **Branch name.** Default `feature/find-passes` (maintainer creates off `main`).
- **The Checkpoint A agreement eyeball** (pass-time/elevation deltas vs the
  independent reference) is the maintainer's.

### Architecture invariants to honor (CLAUDE.md / architecture §4, §10)

Orekit/Java types stay internal; `jpype`/`org.orekit.*` imports **lazily inside
functions**; the extended `Pass` and the magnitude table stay **pure-Python, safe
before init**; SI internally, human units at the boundary; `logging`, never `print`
(the progress reporter is the one sanctioned exception, already shipped);
`pathlib.Path` in the exporters; JVM-touching tests acquire the **`orekit` fixture**
(the conftest hook orders them after the pure-Python guards); new `src/` modules
pass mypy (`src` + `scripts` are type-gated); `import propygator` stays JVM-free.

---

## How to use this plan

- **6 numbered chunks**, each sized for one Claude Code session and independently
  verifiable, ordered by the dependency chain: value types + reference data → the
  physics kernel → the search engine → tables/exports → plots → wrap-up.
- Each chunk lists **Goal / Create-Edit / Reuse / You provide / You run / Verify**.
- **One eyeball gate:** Checkpoint A (after Chunk 3) — the external
  reference-agreement check. Not a GO/STOP on feasibility (the feature is low-risk);
  a disagreement means bug-hunt, not abandonment.
- **`/code-review` + `/simplify` checkpoints:** after Chunk 3 (the engine) and in
  the Chunk 6 sweep.
- **Commits, CHANGELOG entries, chunk-header "done" marks, the merge, and the
  release are the maintainer's.** Claude writes code and runs read-only/test
  commands; the maintainer commits, pushes, and cuts the release.
- **Mergeable chunks:** 4 + 5 can merge into one session (both are pure consumers of
  `Pass`); split them if the snapshot work runs long.

---

## Git (read once)

The maintainer creates **`feature/find-passes`** off `main`; the whole feature rides
on it (the 1.4 full-feature-on-one-branch precedent). Per-chunk rhythm: maintainer
commits + pushes after each verified chunk (CI runs on the branch). Release prep
(version bump → **reinstall editable** → CHANGELOG → squash-merge → annotated tag)
follows `docs/release-process.md` at the end of Chunk 6 and is the maintainer's.

---

## Chunk 1 — `Pass` extension + the cited standard-magnitude table (pure-Python, safe before init)

**Goal:** the two `core/` prerequisites — the extended `Pass` value type and the
citation-backed magnitude table — constructible and validating with **no JVM**
(contract: The `Pass` type; Brightness; architecture §3/§6).

**Create / edit:**
- `src/propygator/core/observation.py` — `Pass` gains
  `rise_azimuth_deg: float | None = None`, `culmination_azimuth_deg: float | None =
  None`, `set_azimuth_deg: float | None = None` (after the existing fields; defaults
  keep hand-built objects valid). Docstring: populated by `find_passes`; documents
  the visible-pass semantics (`sunlit_at_culmination` can be `False` on a visible
  pass) and the clamped-endpoint caveat.
- `src/propygator/core/catalogs.py` — `_STANDARD_MAGNITUDES: dict[int, float]`
  (NORAD id → standard magnitude in the **contract convention**: 1000 km range, 50%
  phase / φ = 90°), seeded for the existing registry's LEO objects from McCants's
  `qsmag` **with the constant offset applied** (qsmag is 1000 km, 100% illumination;
  offset ≈ +2.5·log₁₀ π ≈ +1.24 mag — see Verify). Every entry carries an in-source
  citation comment (source file + retrieval date + raw value + applied offset), per
  architecture §3. Plus a small `_standard_magnitude(norad_id) -> float | None`
  accessor.
- **Tests** (`tests/core/` — fixture-free, no JVM): extended-`Pass` construction
  (with and without azimuths) stays safe-before-init; table entries all finite and
  in a sane band (≈ −3 … +8); the accessor's hit/miss behavior.

**Reuse:** the existing `core/catalogs.py` registry (ids + the qsmag-alignment note
in its module docstring, which anticipated exactly this chunk); the `Pass` dataclass
conventions.

**You provide:** nothing.

**You run:** nothing beyond the git rhythm.

**Verify:** `conda run -n propygator pytest tests/core -v` green with **no JVM**.
**The offset direction check (the one real risk here):** for satellites present in
both sources (ISS, HST), the converted values must land near the Heavens-Above
intrinsic magnitudes (e.g. ISS ≈ −1.8 in the 50%-phase convention) — a sign error
puts them ~2.5 mag off, unmistakably. Record the comparison in the table's header
comment.

---

## Chunk 2 — The visibility kernel (`tracking/visibility.py`)

**Goal:** the feature's only new physics, isolated and unit-tested before the
engine consumes it: the conical-umbra sunlit test, the phase angle, and
`compute_magnitude` (contract: Lighting model; Brightness).

**Create / edit:**
- `src/propygator/tracking/visibility.py`:
  - `_is_sunlit(sat_positions_m, sun_positions_m) -> np.ndarray[bool]` — vectorized
    conical-umbra test in pure NumPy (inputs in one common inertial frame): lit ⟺
    not fully inside the umbra cone (penumbra counts as lit). Consistent with the
    §1.1 SRP conical-shadow convention.
  - `_phase_angle_rad(sat_pos, sun_pos, station_pos) -> np.ndarray` — Sun–satellite–
    observer angle.
  - `compute_magnitude(state: State, station: GroundStation, standard_magnitude:
    float) -> float` — fetches the Sun at `state.epoch` (lazy JVM via `core/bodies`),
    requires EME2000 (`ValueError` otherwise — the `to_geodetic` frame-rule pattern),
    applies `mag = std + 5·log₁₀(range/1000 km) − 2.5·log₁₀(F(φ)/F(90°))` with the
    diffuse-sphere `F(φ) = ((π−φ)cos φ + sin φ)/π`. Purely photometric — no eclipse
    check (the caller gates lighting). Formula citation in the docstring.
- A small internal helper to fetch Sun position arrays for a list of epochs (thin
  loop over the `core/bodies` Sun accessor; fine at per-pass scale — contract:
  Search algorithm step 3).
- **Tests** (`tests/tracking/test_visibility.py`):
  - Umbra geometry, JVM-free with synthetic vectors: satellite directly behind
    Earth → dark; sun-side → lit; the penumbra-grazing edge → lit.
  - **Cross-check vs Orekit** (`orekit` fixture): sample a real LEO trajectory
    through an eclipse season and compare `_is_sunlit` against Orekit's
    `EclipseDetector` umbra `g`-function sign over the samples (agreement except
    within a sample of the crossing) — an independent implementation check.
  - `compute_magnitude`: hand-computed example pinned (range 1000 km, φ = 90° →
    exactly `standard_magnitude`; range 2000 km → +1.505 mag; φ → 0 → brighter by
    2.5·log₁₀ π); the EME2000 frame-rule `ValueError`.

**Reuse:** `core/bodies` Sun accessor (shipped for SRP/third-body);
`State.to_frame`; the repo's lazy-import idiom.

**You provide:** nothing.

**You run:** the git rhythm.

**Verify:** `conda run -n propygator pytest tests/tracking/test_visibility.py -v`
green; the Orekit cross-check agrees; mypy clean.

---

## Chunk 3 — The pass-search engine (`find_passes`) → Checkpoint A

**Goal:** the headline verb, end-to-end per the contract — scan, bracket, refine,
gate, annotate, filter, report progress, honor every failure row (contract: Public
signature; Pass semantics; Search algorithm; Failure modes).

**Create / edit:**
- `src/propygator/tracking/passes.py` — `find_passes`:
  - **Pre-flight:** the `ValueError` table (`duration <= 0`, `min_elevation_deg`
    outside `[0, 90)`, non-finite `standard_magnitude`); `start=None → Epoch.now()`;
    reporter `start` line **before** JVM boot (the §1.1 convention).
  - **Coarse scan:** one `propagate_tle` over the window at `_COARSE_STEP_S = 30.0`
    (module constant, tunable) + one `look_angles_track` → the elevation/azimuth
    arrays.
  - **Bracketing with grazing-pass coverage:** candidate passes = maximal runs of
    samples above the gate, **plus** isolated local maxima within
    `_GRAZE_MARGIN_DEG` (~2°) *below* the gate — refined and then discarded if the
    refined maximum still misses the gate. This closes the "pass shorter than one
    coarse step" hole without shrinking the global step.
  - **Refinement (recommended shape):** per candidate, a **fine batched grid** —
    `propagate_tle` over the bracketing window at `_FINE_STEP_S = 1.0` +
    `look_angles_track` (one `TopocentricFrame` build per pass) — then sub-second
    interpolation of the threshold crossings and the elevation maximum to the
    contract's ~0.5 s tolerance. (The contract's scalar-`look_angles` bisection is
    the fallback shape; the batched grid reuses the kernel and avoids per-call
    station-frame rebuilds. Mechanism, not contract — pick whichever survives
    contact with the code.)
  - **Lighting + magnitude, per pass only:** on the fine grid — Sun positions via
    the Chunk-2 helper, `_is_sunlit`, station Sun elevation ≤ −6°
    (`_TWILIGHT_SUN_EL_DEG = -6.0`), the visible-portion test, `sunlit_at_culmination`,
    and `peak_magnitude` = brightest magnitude over the visible portion (standard
    magnitude resolved: explicit kwarg → `_standard_magnitude(tle.norad_id)` →
    `None`).
  - **Assembly:** `Pass` objects with the three azimuths (at the refined rise/
    culmination/set epochs), window-edge clamping, the always-up warn-once, the
    `visible_only` filter, rise-time sort.
  - **Progress:** determinate fraction over scan + refinement (`scanned / total`),
    honest final line on every exit path (`done | N passes …`; `failed at NN%` on an
    escaping error) — the §1.1 `try/finally` pattern.
- **Tests** (`tests/tracking/test_passes.py`, `orekit` fixture for the JVM paths):
  - **The external cross-check (the substance of Checkpoint A):** a fixed historical
    ISS TLE + the Durham station over a 2–3 day window; assert rise/set within a few
    seconds, max elevation and the three azimuths within ~1° of the committed
    reference fixture (provenance below).
  - Refinement pin (elevation at refined rise/set ≈ `min_elevation_deg`); the
    grazing-candidate path (a synthetic near-threshold case); mid-pass shadow entry
    (visible pass, `sunlit_at_culmination=False`); a daytime pass excluded under the
    default and present-annotated under `visible_only=False`; `[]` on a never-up
    case; window-straddle clamping; the always-up warn-once (a GEO TLE from a
    low-latitude station); the `ValueError` table; magnitude-`None` for an
    off-registry satellite; a `progress=<callable>` fraction capture.
- **Reference-data fixture** (`experiments/pass-verification/`, the 1.4 self-sourced
  + cross-checked precedent): a generator script computing the same passes with
  **Skyfield** in a throwaway venv (documented per `docs/experiments_venv.md`
  hygiene; ASCII-only output), its committed `results.txt` + README with full
  provenance (TLE lines, station, tool versions), and — at plan time — a one-off
  maintainer eyeball of a *near-future* window against Heavens-Above with a current
  TLE as the sanity leg. The pinned numbers land in the test as cited constants.

**Reuse:** `propagate_tle` (+ its shared sample-grid cap and `StaleTLEWarning`,
which the engine inherits rather than reimplements — contract: Failure modes);
`look_angles_track`; the Chunk-2 kernel; `core/progress.py`'s determinate reporter
(shipped; no reporter changes).

**You provide:** confirmation of the fixture station/TLE; the Heavens-Above sanity
eyeball; the Checkpoint A call.

**You run:** the Skyfield generator (throwaway venv); the git rhythm.

**Verify:** `conda run -n propygator pytest tests/tracking -v` green; the
cross-check deltas within tolerance; bare `import propygator` still JVM-free.

> ### 👁 Checkpoint A — reference-agreement gate
> 1. Eyeball the committed deltas (rise/set seconds, elevation/azimuth degrees) vs
>    the Skyfield fixture and the Heavens-Above sanity leg.
> 2. Disagreement ⇒ bug-hunt (frame, refraction assumption, twilight threshold) —
>    not a STOP; the feature has no drop path.
> 3. `/code-review` + `/simplify` on the Chunks 1–3 diff. Commit + push.

---

## Chunk 4 — Pass table + exports (`passes_to_dataframe`, CSV, ICS)

**Goal:** the JVM-free consumers — the DataFrame with real tz-aware datetimes and
the two `io/` exporters (contract: Outputs; Time zones).

**Create / edit:**
- `src/propygator/tracking/passes.py` — `passes_to_dataframe(passes, *, tz=None)`:
  one row per pass; `rise`/`culmination`/`set` as tz-aware pandas datetimes (UTC
  default; converted via the shipped `core.time._resolve_tz` when `tz=` given);
  `duration_s` derived; the scalar columns straight off `Pass`. Pure formatting.
- `src/propygator/io/exports.py` — `export_passes_csv(passes, path) -> None` (the
  DataFrame columns, UTC only, the standard metadata-header pattern) and
  `export_passes_ics(passes, path, *, name=None) -> None` (hand-rolled VCALENDAR:
  one VEVENT per pass with UID/DTSTAMP/DTSTART/DTEND/SUMMARY, UTC `Z` timestamps,
  ASCII-safe SUMMARY like `ISS pass - max el 45 deg, mag -3.2`).
- Top-level `__init__.py` re-exports: `find_passes`, `passes_to_dataframe`,
  `export_passes_csv`, `export_passes_ics` (+ `tests/test_public_surface.py`
  update).
- **Tests:** DataFrame column set/dtypes snapshot incl. a `USTimeZone` conversion
  (DST-correct assertion); CSV snapshot; ICS snapshot + a structural parse (every
  VEVENT has the required fields; timestamps end in `Z`); `name=` default label.
  All headless — hand-built `Pass` fixtures, no JVM.

**Reuse:** `core.time._resolve_tz` + `USTimeZone` (shipped Part A);
`io/exports.py`'s metadata-header helpers; `Trajectory.to_dataframe` as the pandas
idiom template.

**You provide:** nothing.

**You run:** the git rhythm.

**Verify:** headless suite green with no JVM (these tests join the pure-Python
side); `import propygator` unchanged.

---

## Chunk 5 — The plots (`plot_sky_chart`, `plot_pass_timeline`)

**Goal:** the rich outputs in `plotting/passes.py`, snapshot-tested (contract:
Outputs; the 1.4 ↔ 1.5 line — the shared `_draw_sky_track` stays geometry-only).

**Create / edit:**
- `src/propygator/plotting/passes.py`:
  - `plot_sky_chart(tle, station, passes, *, tz=None) -> Figure` — per pass:
    `propagate_tle` over `[rise, set]` + `look_angles_track` (recomputed arcs — the
    light-`Pass` trade), drawn on the `_draw_sky_track` polar conventions via its
    existing styling seam (never restyling the shared primitive's defaults):
    lit-segment vs eclipsed-segment styling (reusing Chunk 2's `_is_sunlit` on the
    arc), rise/set labels (tz-formatted times + azimuths), culmination marker with
    max elevation, magnitude annotation, title from `tle.name`.
  - `plot_pass_timeline(passes, *, tz=None) -> Figure` — wall-clock x-axis over the
    window, one bar per pass rise→set with height = max elevation, peak-magnitude
    annotation, `sunlit_at_culmination` bar styling, the minimum display width
    (positions exact), day-boundary gridlines. Pass-fields-only — no TLE, no JVM.
- **Tests:** figure snapshot tests for both verbs (architecture §11 — static plots,
  fully snapshot-testable, unlike 1.4's live view); a timeline smoke test with
  hand-built `Pass` fixtures (headless); the sky chart under the `orekit` fixture.

**Reuse:** `_draw_sky_track` + its styling seam (shipped 1.4); `plotting/style.py`;
the snapshot-test harness; `_resolve_tz`.

**You provide:** a look/feel eyeball of both figures (styling constants are
tunable placeholders).

**You run:** the git rhythm.

**Verify:** `conda run -n propygator pytest tests/plotting -v` green; the shared
`_draw_sky_track` / `plot_sky_track` snapshot tests **unchanged** (the primitive's
contract holds); `plot_*` re-exports wired.

---

## Chunk 6 — Wrap-up: docs, notebook, sweep, release

**Goal:** land the feature — docs reconciled, the walkthrough notebook, clean
sweep, squash-merge + tag (the maintainer's release).

**Create / edit / run:**
- Full local CI parity: `conda run -n propygator pytest` and
  `conda run -n propygator pre-commit run --all-files` green from repo root.
- `/code-review` + `/simplify` final pass across the whole diff.
- **Docs reconciliation:**
  - `README.md` — move Feature 1.5 from "Coming next" to shipped (✅ bullet + the
    worked example with the real signature and one output surface each).
  - `architecture.md` §10 — add `find_passes` / `compute_magnitude` /
    `plot_sky_chart` to the JVM-startup list; extended-`Pass` construction and
    `passes_to_dataframe` / `plot_pass_timeline` / the exporters noted
    safe-before-init (the Note-4 docs-completeness pattern).
  - `features.md` §1.5 — an **Outcome** note recording as-built deltas (tuned
    constants, the refinement shape actually chosen); status header stays the
    maintainer's.
  - `notebooks/06_pass_prediction.ipynb` — fetch → find → DataFrame → ICS → sky
    chart → timeline (nbstripout keeps outputs stripped).
  - **You** update `CHANGELOG.md` and `CLAUDE.md` "Project state" (the narrative
    artifacts are yours; CLAUDE.md drafting is delegated to Claude on request).
- **Release** (maintainer, per `docs/release-process.md`): version bump in
  `pyproject.toml` → **reinstall editable** (`pip install -e .[dev]` — the
  version-bump gotcha) → squash-merge → annotated tag → push → `git branch -D`.
  This plan then retires to `docs/history/`.

**You provide:** CHANGELOG; the version number; the merge/tag go-ahead.

**Verify:** full `pytest` + `pre-commit run --all-files` green; the README example
runs verbatim;
`conda run -n propygator python -c "import propygator, jpype; print(jpype.isJVMStarted())"`
→ `False`.

---

## End-state verification (shipped → tagged on `main`)

1. **The README example runs verbatim** and returns visible ISS passes.
2. **Cross-check:** the committed Skyfield fixture agreement (rise/set seconds,
   angles ~1°) recorded at Checkpoint A.
3. **Semantics:** mid-pass shadow entry yields a visible pass with
   `sunlit_at_culmination=False`; `visible_only=False` returns annotated geometric
   passes; magnitude `None` off-registry; every failure-mode row exercised.
4. **Outputs:** DataFrame (tz-aware), CSV (UTC), ICS (imports into a calendar
   client — one manual import eyeball), sky chart with lit/eclipse styling,
   timeline. All top-level exports present.
5. **Invariants:** `import propygator` JVM-free; `tests/core` still no-JVM; the
   shared `plot_sky_track` snapshots byte-stable; mypy/pre-commit green.
6. **Docs:** README/architecture/features/notebook/CHANGELOG/CLAUDE.md reconciled;
   this plan retired to `docs/history/`.

## Notes / deferred (not this plan)

- **Batched Sun-track kernel helper** in `core/observation.py` — only if per-pass
  profiling warrants (contract: Still open).
- **Observer-darkness band shading on the timeline** (station-aware + JVM) —
  deferred.
- **Exposing the −6° twilight threshold** as a parameter — deferred.
- **Bulk multi-satellite pass search** — out of scope; the per-TLE verb composes.
- **Event-based finder** (`ElevationDetector`) — the named alternative, dormant
  unless sampling-based grazing coverage fails its tests.
