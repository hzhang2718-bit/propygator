# Feature 1.3 (TLE propagator) — pre-build-plan notes

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

## Note 4 — The sky view pulls Feature 1.5's topocentric math forward

§1.3's sky-view output (`plot_sky_track` + the `look_angles` primitive, features §1.3
"Sky view") introduces the **first topocentric look-angle computation in the
codebase**. That math is otherwise Feature 1.5's: `find_passes` "is allowed to
internally convert to topocentric" (architecture §10) and the planned
`plot_sky_chart` (`plotting/passes.py`) is a 1.5 deliverable. Building it in 1.3 is
**pulling 1.5's foundation forward, deliberately** — not duplicating it. Build-plan
consequences:

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
- **Scope discipline = geometry only.** `plot_sky_track` draws the raw az/el path and
  nothing else; passes (rise/set/culmination), eclipse/lit shading, and magnitude stay
  in 1.5's `plot_sky_chart`. This is the line that keeps 1.3 from absorbing 1.5.
- **Disjoint-arc rendering.** Mask samples below `min_elevation_deg` to `NaN` so the
  polyline lifts between successive passes instead of drawing chords across the sky
  disk; if *no* sample clears the horizon, draw the empty disk + warn-once (features
  §1.3 "Sky view").
- **`plot_sky_track` is an additive plotting verb** in `plotting/trajectories.py`
  (beside `plot_ground_track`) — `propagate_tle`'s signature is untouched; the sky view
  consumes the returned `Trajectory` + a `GroundStation`, like every other output.

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
  propagators then share one contract-bearing helper *and* one memory cap (the cap is propagator-agnostic —
  each sample is a p/v row + a propagate call either way; generalize the cap's error
  message, which currently reasons about "an ephemeris query," since 1.3 evaluates the
  analytic propagator per grid epoch with no `EphemerisGenerator`). `_realized_sample_count`
  is *not* needed by 1.3 (no stop-and-report). Refactor `numerical.py` to import the
  promoted helpers instead of defining them locally.
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
