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

`from_strings` / `from_state_unfitted` are safe-before-init (parse/validate only);
`to_orekit()` and `from_norad_id` cross the JVM / network. Add `TLE` to the
top-level re-exports and to the "safe before init" surface list (architecture §10)
for the construction/parse paths.

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
Earth GM the rest of the library already uses). The checksum/format logic has no
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

## Also fold in

- **Sample-count reuse — DECIDED (#7).** `propagate_tle` lives in
  `tle/propagator.py`, which may import only from `core/` (§7 dependency rule), so
  it **cannot** import `_sample_count` from `propagation/numerical.py`. **Promote**
  `_sample_count`, the epoch-grid generation, **and the `_MAX_OUTPUT_SAMPLES` cap +
  its guard** (`numerical.py:120,271`) down into `core/`, so both propagators share
  one contract-bearing helper *and* one memory cap (the cap is propagator-agnostic —
  each sample is a p/v row + a propagate call either way). `_realized_sample_count`
  is *not* needed by 1.3 (no stop-and-report). Refactor `numerical.py` to import the
  promoted helpers instead of defining them locally.
- **Stale-TLE warn-once — DECIDED (#7).** Add a 1.3-specific warn-once (not an
  error) when the worst-case age over the span,
  `max(|start − tle.epoch|, |(start + duration) − tle.epoch|)`, exceeds 30 days.
  Pure-`Epoch` arithmetic, in the propygator-side pre-flight. (features §1.3
  "Failure modes and terminal behavior".)
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
