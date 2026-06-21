# Feature 1.3,4 (TLE propagator and live tracker) — pre-build-plan notes

> **Status: NOTES, not a build plan.** Captured during the 1.3 design review
> (2026-06-20). These are prerequisite/scoping items to fold into the Feature 1.3
> build plan when it is drafted. They record work that `features.md` §1.3
> *references* but does not itself spell out. The binding contract stays
> `features.md` §1.3 + `architecture.md` §6/§7 — nothing here changes a signature.

## Why these exist

§1.3 reads as "1.3 reuses 1.1's `Trajectory`, plotting stack, and exporters
wholesale; only the propagation core and the native output frame differ." That is
true for the *output* surface, but it understates three prerequisites that must
exist before `propagate_tle` can be called at all. None are blockers; they are
scope the build plan needs to sequence explicitly.

## Note 1 — The `TLE` core type must be built first (it does not exist yet)

`TLE` is specified in `architecture.md` §6 but is **not implemented anywhere** in
`src/` — `tle/` is a bare `__init__.py`. Everything in §1.3 takes a `TLE`, so the
first build stage is the type itself, in `core/` (architecture §6 places it there;
building a TLE from a `State` keeps the dependency rule clean):

- `TLE` frozen dataclass: `line1`, `line2`, `name=None`.
- `from_strings(line1, line2, name=None)` — parse + **checksum validation** (raises
  `ValueError` at construction per architecture §10, so `propagate_tle` always
  receives a valid TLE).
- `from_norad_id(norad_id, source="celestrak")` — depends on the fetch path (Note 3).
- `from_state_unfitted(state, *, norad_id=None, bstar=None, name=None)` — the §1.3
  row→TLE utility (its own sub-stage; see Note 2).
- `.epoch -> Epoch`, `.norad_id -> int`, `.to_orekit()` (lazy, `TYPE_CHECKING`-
  annotated, same pattern as `Epoch.to_orekit`).

**Only `from_strings` is safe-before-init** (pure-Python parse + checksum, no JVM).
`from_state_unfitted` is **not**: its settled mechanics (Note 2) call
`state.to_frame(Frame.TEME).to_keplerian()`, and both `State.to_frame` and
`State.to_keplerian` run `_ensure_started()` (`core/states.py:162,196`), so building
a TLE from a state **starts the JVM** — it groups with `to_orekit()` and
`from_norad_id` (JVM / network), not with `from_strings`. Add `TLE` to the
top-level re-exports and to the "safe before init" surface list (architecture §10)
for `from_strings` and bare construction only — **not** `from_state_unfitted`
(which starts the JVM), so the `tests/core/*` "no JVM started" suite must not
exercise it.

## Note 2 — `from_state_unfitted` needs more field decisions than §1.3 lists

§1.3 specifies the `norad_id` / `bstar` placeholders, but a bare `State` carries
**none** of the other TLE fields. Before building, enumerate and pin a default for
each non-physical field Orekit's `TLE(...)` constructor requires, e.g.:

- classification (default `U`),
- international designator (launch year / number / piece — placeholder),
- element-set number,
- revolution number at epoch,
- ephemeris type,
- first/second derivatives of mean motion (zero — not recoverable from one state,
  same rationale as B*).

Mechanics already settled by §1.3: compute osculating elements **in TEME**
(`state.to_frame(Frame.TEME).to_keplerian()`), map ν→M
(`KeplerianElements.mean_anomaly()`), derive the mean-motion field from `a`
(`n = sqrt(µ/a³)` — the *osculating* mean motion, part of the documented
non-faithfulness), then format + checksum. Pin a single source of µ (reuse the
Earth GM the rest of the library already uses) — note that is the library's WGS84 GM, while
SGP4/TLE mean motion is a WGS72/Kozai quantity, so the derived mean-motion field
carries a small constants mismatch *on top of* the mean-vs-osculating gap; fold this
into the docstring's documented non-faithfulness rather than reconciling it (it is a
format-valid, not faithful, utility). The checksum/format logic has no
sub-design in §1.3 — it lives in `tle/parsing.py` and needs its own build step (or
lean on Orekit's `TLE` formatting + checksum).

## Note 3 — `fetch_tle` / sources are a prerequisite for the §1.3 examples

The §1.3 / README examples (`fetch_tle("ISS")`, `from_norad_id`) assume
`tle/sources.py` (`fetch_tle`, `fetch_celestrak`, `fetch_spacetrack`), the
`~/.propygator/cache/` 6h/24h TTL cache (architecture §10), and the popular-
satellite registry in `core/catalogs.py` — none of which exist yet.
`propagate_tle` *in isolation* needs only `TLE.from_strings`, so the build plan can
stage the fetch infrastructure separately (it is shared with feature 1.4). Flag the
dependency so the "usable from the README" milestone is not assumed to fall out of
`propagate_tle` alone.

**Source scope — DECIDED: CelesTrak only for v1.** Both `fetch_tle` and `from_norad_id`
default `source="celestrak"` (architecture §6/§7 reconciled — §7's stale
`source="auto"` literal is dropped). `"auto"` multi-source resolution and
`fetch_spacetrack` (with the `SPACETRACK_*` credentials, architecture §3/§10) are
**deferred** until a second source is actually wired; with a single source an `"auto"`
default would only mislead. The `source` parameter stays in both signatures
(forward-compatible) but `"celestrak"` is its only valid value for v1 — the broader
Space-Track design in architecture §3/§7/§8/§10 remains as deferred future capability,
not deleted. For the name-fallback (features §1.3) to carry anything, `fetch_tle` and
`TLE.from_strings`' 3-line form must populate `tle.name` from CelesTrak's line-0 / the
catalog friendly name.

## Note 4 — Sky view RELOCATED to Feature 1.4 (no longer a 1.3 build item)

> **Superseded by the §1.3 redesign (features.md:594, 679–681).** Earlier drafts built
> the observer-centric sky view *in* 1.3 to pull Feature 1.5's topocentric math forward.
> The whole sky view — the `look_angles(station, state) -> AzElRange` primitive
> (`core/observation.py`), the `_draw_sky_track` primitive, and the `plot_sky_track`
> verb (`plotting/trajectories.py`) — has **moved to Feature 1.4**, whose live tracker
> needs a live sky panel. It is still built *before* 1.5 in the build order
> (architecture §12), so the forward-pull for 1.5's `find_passes` / `plot_sky_chart` is
> preserved. **None of this is in the 1.3 build plan anymore;** `propagate_tle`'s
> signature was never affected (the sky view was always an additive plotting verb, not a
> propagator knob). The design substance below is retained as scoping for the **Feature
> 1.4** build plan, not 1.3.

Carry into the 1.4 build plan (re-homed, substance unchanged):

- **`look_angles(station, state) -> AzElRange` is the shared primitive**, built once
  in `core/observation.py` (with the `AzElRange` value type) and reused *verbatim* by
  1.5's `find_passes`. Stage it as its own build step, ahead of the plot verb.
- **It is JVM-touching, NOT safe-before-init.** It builds an Orekit `TopocentricFrame`
  on the `core/bodies.py` Earth ellipsoid, so it lazy-imports jpype inside the body
  (same pattern as `to_geodetic`) and joins the "starts the JVM" group. `core/
  observation.py`'s module docstring currently states construction "never touches the
  JVM" — that stays true for the **value types** (`GroundStation` / `GeodeticPosition`
  / `Pass` / `AzElRange`), but the docstring must be updated to carve out
  `look_angles`, and the `tests/core/*` "no JVM started" suite must **not** call it
  (acquire the JVM via the `orekit` fixture instead, per the one-JVM-per-process
  ordering rule).
- **`AzElRange` value type is safe-before-init** (pure-Python frozen dataclass, like
  its siblings) — only the `look_angles` *call* starts the JVM. Add `AzElRange` to the
  top-level re-exports.
- **Carve `look_angles` / `AzElRange` into the architecture §10 safe-before-init
  enumeration.** §6 and the two bullets above already state the split (the value types
  are safe-before-init; the `look_angles` *call* is JVM-touching), but architecture
  §10's worked "safe before init" list — and its companion "JVM startup is reserved
  for" list — names `GroundStation` / `Pass` / `TLE.from_strings` / `VariableCd` and
  does **not** yet mention `AzElRange` or `look_angles`. That list is illustrative, not
  exhaustive (it already omits `GeodeticPosition`), so this is a docs-completeness
  cleanup, not a blocker — but when 1.4 lands, add `AzElRange` construction to the
  safe-before-init surface and `look_angles` to the JVM-startup list, alongside the
  `core/observation.py` docstring carve-out noted above. (Surfaced by the 2026-06-20
  §1.3 audit.)
- **Scope discipline = geometry only.** `plot_sky_track` draws the raw az/el path and
  nothing else; passes (rise/set/culmination), eclipse/lit shading, and magnitude stay
  in 1.5's `plot_sky_chart`. This is the line that keeps the relocated sky view from
  absorbing 1.5.
- **Disjoint-arc rendering.** Mask samples below `min_elevation_deg` to `NaN` so the
  polyline lifts between successive passes instead of drawing chords across the sky
  disk; if *no* sample clears the horizon, draw the empty disk + warn-once.
- **`plot_sky_track` is an additive plotting verb** in `plotting/trajectories.py`
  (beside `plot_ground_track`) — `propagate_tle`'s signature is untouched; the sky view
  consumes a `Trajectory` + a `GroundStation`, like every other output.

Refinements surfaced by the 2026-06-20 §1.3 audit (fold into the 1.4 design — the
codebase already chose these patterns elsewhere):

- **Batch the topocentric path.** A `TopocentricFrame` depends only on the station, not
  the sample, so calling `look_angles` per sample rebuilds it and re-crosses the JPype
  boundary N times. Mirror the established batched idiom `geodetic_track(traj)`
  (`core/frames.py:145`): add a `look_angles_track(station, trajectory)` returning
  `AzElRange` arrays (or have `plot_sky_track` build the station `TopocentricFrame` once
  and reuse it), keeping per-state `look_angles` as the ergonomic primitive. Cheap at
  design time, awkward to retrofit once the call shape is frozen — and it compounds in
  1.5, which also walks dense trajectories.
- **Factor a `_draw_sky_track(ax, traj, station, ...)` primitive** for the polar setup
  (N-up clockwise theta, light-blue disk, zenith-at-center radius, NaN arc-masking) so
  1.5's `plot_sky_chart` layers passes/brightness on the same axes-drawing code — the
  same `_draw_*(ax, ...)` convention features §1.1 established ("designing the
  primitives up front is cheap; retrofitting is not").
- **Scope the 1.5 de-risking honestly.** `look_angles` is a genuine shared primitive for
  az/el *reporting* and a sampling-based finder, but accurate rise/culmination/set in
  `find_passes` is naturally Orekit event detection (`ElevationDetector` / an extremum
  detector) inside the propagator, not sampling a finished `Trajectory`. So the 1.4/1.5
  build plan should record the open choice — sampling-based finder (full `look_angles`
  reuse) vs. event-based finder (`look_angles` for reporting only) — and not overstate
  how much the relocated sky view de-risks 1.5's core pass-finding algorithm.

## Note 5 — TEME is an ECI frame

- This means that the 3D plotly Earth in TEME should **not** have coastlines imposed
  on it.

## Also fold in

- **Sample-count reuse — DECIDED (#7).** `propagate_tle` lives in
  `tle/propagator.py`, which may import only from `core/` (§7 dependency rule), so
  it **cannot** import `_sample_count` from `propagation/numerical.py`. **Promote
  into a new `core/sampling.py`**: `_sample_count`, the epoch-grid generation, the
  `_MAX_OUTPUT_SAMPLES` cap + its guard (`numerical.py:120,271`), **and the
  propagator-agnostic pre-flight checks** — `duration > 0`, `output_step > 0`,
  `output_step <= duration`. Those three currently live inside the *monolithic*
  `_validate_inputs` (`numerical.py:205`) intermixed with numerical-only checks
  (inertial frame, integrator type, gravity/atmosphere names), so "reuse 1.1's
  validation wholesale" is **not** literally possible — the shared subset must be
  extracted, leaving the numerical-specific checks behind in `numerical.py`. Both
  propagators then share one contract-bearing helper *and* one memory cap (the cap is
  propagator-agnostic — each sample is a p/v row + a propagate call either way). The
  cap's error message has been **pre-generalized in place** (`numerical.py`, now
  propagator-neutral) so it moves to `core/sampling.py` verbatim; see "Sample-cap error
  message" below for the canonical text and rationale. `_realized_sample_count` is *not*
  needed by 1.3 (no stop-and-report). Refactor `numerical.py` to import the promoted
  helpers instead of defining them locally.
- **Stale-TLE warn-once — DECIDED (#7).** Add a 1.3-specific warn-once (not an
  error) when the worst-case age over the span,
  `max(|start − tle.epoch|, |(start + duration) − tle.epoch|)`, exceeds 30 days.
  Pure-`Epoch` arithmetic, in the propygator-side pre-flight. (features §1.3
  "Failure modes and terminal behavior".) **Prerequisite — the difference helper does
  not exist yet.** `Epoch.shifted_by` is pure-Python (`time.py:312`) so
  `start + duration` is fine, and `Epoch.now` / `to_iso` exist, but there is **no
  `Epoch − Epoch` difference** (seconds between two epochs) — add one as its own build
  step (trivial from the two-part TAI count). The "pure-`Epoch` arithmetic" claim, and
  the both-ends age computation, depend on it.
- **Metadata timestamps must be forced to UTC — build reminder.** `Epoch.to_iso()`
  renders the wall-clock *in the epoch's own scale with no zone suffix* (`time.py:325`),
  so the `tle_epoch` / `start` / `created_at` keys (documented "iso utc str") must be
  serialized via `epoch.in_scale(TimeScale.UTC).to_iso()` (a pure relabel of the same
  instant, `time.py:302`). `start` defaults to `tle.epoch` and the trajectory inherits
  its scale, so this is not hypothetical — reuse 1.1's existing UTC-ISO serialization
  path and never hand `to_iso()` a TT/TAI epoch for a metadata value.
- **`output_step` default — DECIDED (#8).** Drop the 60 s default: `output_step` is
  **required + keyword-only**, matching 1.1 exactly. This makes the
  `output_step > duration` guard unambiguous and lets 1.3 reuse 1.1's pre-flight
  validation wholesale (positive/ordered checks + the promoted sample cap above).
- **`PropagationError` shape — DECIDED & APPLIED (#6, option b).** `PropagationError`
  is now an (abstract-in-practice) base; `propagate_numerical` raises
  `NumericalPropagationError` (carries `partial_trajectory`), and 1.3's `propagate_tle`
  will raise **`TLEPropagationError`** (no `partial_trajectory` — SGP4 never
  stops-and-reports). Both subclass `PropagationError`, so `except PropagationError`
  still catches either. All three are defined in `core/exceptions.py` and re-exported
  at the top level *now* (ahead of 1.3), so §1.3 already references real types — **1.3
  just has to raise `TLEPropagationError` at its `OrekitException` catch site.**
  Background (verified at review): a numerical min-step failure surfaces as a Hipparchus
  `MathIllegalStateException` ("minimal step size … reached"), an SGP4 decay as an
  Orekit `OrekitException` (`OrekitMessages.TOO_LARGE_ECCENTRICITY_FOR_PROPAGATION_MODEL`;
  `getSpecifier()` / `getParts()` give a locale-independent enum + value), so if 1.3
  ever wants a *decay-specific message* it can match `getSpecifier()` without parsing
  strings.
- **Sample-cap error message — DRAFTED & pre-generalized.** Once the cap moves to
  `core/sampling.py` it is raised for **both** propagators, so its wording must be
  propagator-neutral. The old numerical-only phrase "an ephemeris query" (true only of
  1.1's `EphemerisGenerator` sampling — 1.3 evaluates `TLEPropagator` analytically per
  grid epoch, no bounded ephemeris) has already been replaced **in place** in
  `numerical.py` by "one propagator evaluation"; the cap constant's comment was
  generalized the same way ("per-sample propagator evaluations"). Canonical text, which
  moves to `core/sampling.py` verbatim during the promotion (item 1):

  ```python
  raise ValueError(
      f"duration/output_step requests {n_samples} output samples, exceeding the "
      f"{_MAX_OUTPUT_SAMPLES} cap; increase output_step or shorten duration "
      "(each sample allocates a position+velocity row and one propagator "
      "evaluation, so a much larger count would exhaust memory)."
  )
  ```

  The stable substring `"output samples"` is preserved, so the existing pin
  (`tests/propagation/test_numerical.py:174`, `match="output samples"`) stays green;
  add the analogous cap test on the `propagate_tle` path so both propagators exercise
  the shared raise.
