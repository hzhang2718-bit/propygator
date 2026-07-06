# Prospective additions — planetary gravity, Earth radiation pressure, progress reporting

> **Status update (2026-07-05):** items 1–2 were scoped into
> `general-upgrades-1.md` "Planetary Third-Body & Earth Radiation Pressure" (build
> plan archived at `docs/history/build-plan-additional-perturbations.md`). **Item 1
> (planetary gravity) shipped** as the lumped `planets_third_body` toggle — this doc's
> §2.3 per-planet-booleans lean was superseded by the contract. **Item 2 (Earth
> radiation) is blocked on upstream**: §3's `KnockeRediffusedForceModel` is defective
> in every installable Orekit (≤ 13.1.5 — wrong visible-cap horizon bound, fixed in
> Orekit 13.1.6); the fully-built runtime is parked in `experiments/earth-radiation/`
> with the evidence and resume recipe. **Item 3 (progress reporting) remains
> unscoped** — §4 is still the live reference for it.

> **Status: FINDINGS / ANALYSIS — not a design contract and not a build plan.** A
> standalone feasibility/difficulty assessment of three candidate enhancements to the
> numerical propagator, written to capture the reasoning before any build decision. It
> does **not** supersede anything. The binding designs remain `docs/features.md` §1.1
> (the `propagate_numerical` contract: signature, `ForceModelConfig`, the `force_models`
> metadata grammar) and `docs/architecture.md`. Each item here, if adopted, gets folded
> into a build plan the usual way. The Orekit-API claims below were confirmed against the
> installed build (orekit_jpype 13.1.x) by direct introspection on 2026-06-20; the call
> sites cited are current as of this branch.

## 1. Scope

Three independently-shippable ideas, two of them new force models and one a UX feature:

1. **Gravity from other planets** — third-body attraction from Venus, Jupiter, etc.
2. **Radiation pressure from Earth** — reflected sunlight (albedo) plus Earth's thermal IR.
3. **A progress bar / progress messages** for long propagations.

All three target `propagate_numerical` (`propagation/numerical.py`) — the only
long-running, force-configurable verb in v1. None requires fighting the JPype boundary;
each is a stock Orekit mechanism slotting into wiring that already exists. The real work
is in three recurring friction points, collected once in §5: the **`force_models`
metadata grammar** (a contract), the **frozen public signature** (a contract), and the
**JPype default-method trap**.

| Item | Difficulty | One-line reason |
|---|---|---|
| Planetary third-body gravity | **Easy** (≈ an afternoon) | Identical to the Sun/Moon path already wired; no new data |
| Earth radiation pressure | **Moderate** | Orekit ships the model and it reuses the existing optics, but adds a tuning knob, real runtime cost, and a scope decision |
| Progress reporting | **Easy** (log messages) → easy–moderate (bar/callback) | Step-handler mechanism proven; mostly an architecture-fit decision |

---

## 2. Gravity from other planets

### 2.1 What's already there

The third-body path is fully built — for Sun and Moon. The wiring is two lines
(`numerical.py:720-723`):

```python
if fm.sun_third_body:
    propagator.addForceModel(ThirdBodyAttraction(_sun()))
if fm.moon_third_body:
    propagator.addForceModel(ThirdBodyAttraction(_moon()))
```

`ThirdBodyAttraction` accepts any `CelestialBody`, and the body accessors in
`core/bodies.py` (`_sun()` at :79, `_moon()` at :89) are one-line wrappers over
`CelestialBodyFactory`.

### 2.2 The Orekit API (confirmed)

The same `CelestialBodyFactory` that yields Sun/Moon exposes every planet:
`getMercury / getVenus / getMars / getJupiter / getSaturn / getUranus / getNeptune /
getPluto`, plus `getSolarSystemBarycenter` / `getEarthMoonBarycenter`. Critically,
`getJupiter()` **resolved and returned a µ** in the probe — which means the JPL DE
ephemeris already shipped in orekit-data covers the planets. **No new ~500 MB data
dependency, no new resolver path** — the same file that already powers Sun/Moon answers
for the planets.

### 2.3 What it takes

- **`core/bodies.py`** — add `_jupiter()`, `_venus()`, … each a verbatim clone of
  `_moon()` with a different factory method.
- **`ForceModelConfig`** (`force_models.py:88`) — new toggles. *Design decision:* discrete
  booleans (`jupiter_third_body: bool`, …) match the existing `sun_third_body` pattern and
  read cleanly, but only Venus and Jupiter matter dynamically for Earth orbits; a single
  `extra_third_bodies: tuple[str, ...] = ()` is terser if more than a couple are wanted.
  Recommendation: a couple of explicit booleans, to stay parallel with what's there and
  keep the metadata grammar simple. Keep them **off in every preset** (opt-in).
- **`_add_perturbation_forces`** (`numerical.py:691`) — add the `ThirdBodyAttraction`
  calls beside the Sun/Moon ones, and mirror the new facts into `_WiredForces`
  (`numerical.py:327`) so the metadata stays honest.
- **The metadata grammar** — see §5.1. New tokens `third_body:jupiter`, etc., in the fixed
  token order.
- Tests + the `features.md` §1.1 preset/grammar/docstring update.

### 2.4 Caveat worth stating in the design

Planetary perturbations on an Earth satellite are tiny — roughly 1e-10–1e-13 of central
gravity (Venus and Jupiter dominate). This is a high-precision-GEO / completeness feature,
not something that visibly changes a LEO trajectory. **Easy to add; modest in payoff** —
scope it honestly as "for users who want full third-body completeness."

---

## 3. Radiation pressure from Earth (albedo + IR)

### 3.1 The Orekit API (confirmed)

Orekit ships the model: `org.orekit.forces.radiation.KnockeRediffusedForceModel` is
present in the installed build, with constructors:

```
KnockeRediffusedForceModel(ExtendedPositionProvider sun, RadiationSensitive spacecraft,
                           double equatorialRadius, double angularResolution)
KnockeRediffusedForceModel(... same four ..., TimeScale)
```

The decisive convenience: the `RadiationSensitive` argument is **exactly the interface the
existing SRP code already produces**. `_build_srp_force` (`numerical.py:595`) already builds
an `IsotropicRadiationSingleCoefficient` for a sphere and reuses the
`BoxAndSolarArraySpacecraft` for a box — both implement `RadiationSensitive`. So the
spacecraft-optics half is free; you pass the same object. `sun` (`_sun()`),
`equatorialRadius` (`Constants.WGS84_EARTH_EQUATORIAL_RADIUS`), and the Earth body are all
already on hand. A first cut is genuinely small:

```python
if fm.earth_radiation:
    propagator.addForceModel(
        KnockeRediffusedForceModel(_sun(), radiation_sensitive, R_eq, angular_resolution)
    )
```

### 3.2 Why it's *moderate*, not easy

Four wrinkles lift this above the planetary-gravity item:

1. **It's albedo *and* Earth IR, not albedo alone.** Knocke's "rediffused" model bundles
   reflected sunlight (visible albedo) *with* the planet's own thermal infrared
   re-emission. Orekit offers only the combined model. The feature must be **named/scoped
   honestly** — `earth_radiation` (albedo + IR), not `earth_albedo`. That's a contract
   decision, not a code one.
2. **A new continuous tuning knob with no home.** `angularResolution` (radians) sets how
   finely Earth's lit, visible cap is discretized. Unlike every existing force toggle it's
   not a boolean. Either hardcode a sensible default (~0.087 rad ≈ 5°) or add a field — and
   a field on `ForceModelConfig` reopens the "models vs. coefficients" split the design
   deliberately keeps clean (`force_models.py` module docstring). Recommendation: a sensible
   hardcoded default for v1, like the `_OCEAN_TIDE_DEGREE` precedent (`numerical.py:108`).
3. **Real runtime cost.** Knocke sums radiation over many surface elements *every integrator
   substep*, where SRP uses a single Sun direction. At fine resolution it can dominate
   wall-clock time. The codebase already cares about per-substep cost (the drag-proxy note
   at `numerical.py:421`); pick a coarse default and document the cost.
4. **The §5 contract work** — a new `earth_radiation` token in the grammar, plus the
   preset/docstring updates.

### 3.3 What it takes

- **`ForceModelConfig`** (`force_models.py:88`) — `earth_radiation: bool = False` (off in
  all presets), and the chosen resolution handling.
- **`_build_earth_radiation_force(...)`** in `numerical.py`, parallel to `_build_srp_force`
  (`numerical.py:595`), reusing the same sphere/box `RadiationSensitive`. For a box that
  means one shared object now driving **three** forces (drag + SRP + Earth radiation), all
  built once in `_add_perturbation_forces` (`numerical.py:691`).
- `_WiredForces` + grammar token + `features.md` §1.1.

### 3.4 Caveat worth stating in the design

Earth radiation pressure is most relevant for **low-altitude, high-area-to-mass craft** —
it's a recognized term in precise LEO orbit determination (e.g. altimetry missions). At GEO
it's small. So it's a *more useful* addition than planetary gravity for the LEO regime this
propagator targets, which argues for doing it despite the higher cost.

---

## 4. A progress bar / progress messages

### 4.1 The mechanism is proven

The feasibility question was: can progress be reported *during* the single blocking
`propagator.propagate(end_date)` call (`numerical.py:1037`) while the code still generates
its ephemeris the way it does now (`getEphemerisGenerator()` at `numerical.py:1026`)? The
probe answers **yes, cleanly**:

- A Python `OrekitFixedStepHandler` proxy (`@JImplements`) registered via
  `propagator.getMultiplexer().add(step_seconds, handler)` fires on schedule during
  `propagate()`. Its `handleStep(state)` exposes the current date, so
  `fraction = state.getDate().durationFrom(start) / duration` is a clean, **monotonic
  0 → 1** progress signal.
- It **coexists with ephemeris generation**: one probe run produced 361 progress callbacks
  (60 s cadence over 6 h) *and* a complete ephemeris. The step handler and the ephemeris
  generator are independent.

### 4.2 Where the time goes

`propagate_numerical` has two cost phases. The **integration** (`propagate()`,
`numerical.py:1037`) dominates on long / force-heavy runs (per-substep NRLMSISE-00 drag,
tides) and is what the step handler covers. The post-propagation **sampling loop**
(`numerical.py:1063-1084`) is already pure Python and trivially wrappable, but is rarely the
bottleneck.

### 4.3 Three options, increasing effort

**(a) Log messages — no signature change, no dependency (recommended first cut).** The repo
convention is *logging, never prints*, with a top-level `NullHandler`, so `logger.info` is
default-silent and only surfaces for users who attach a handler / set the level. Start/end
info logs already exist (`numerical.py:933` and `:1154`); a progress handler emitting
`logger.info("propagate_numerical: %.0f%% (t+%.0fs)", ...)` at coarse intervals slots right
in. **Zero contract change, zero new deps, fully idiomatic.** ≈ 30–40 lines: a
`_make_progress_handler(start_date, duration)` proxy plus one `getMultiplexer().add(...)`
before the propagate call.

**(b) Opt-in callback parameter** — `progress: Callable[[float], None] | None = None`. More
flexible (drives a notebook widget, a GUI bar, or tqdm). But this adds a knob to the
**frozen, binding signature** (`features.md` §1.1; the signature at `numerical.py:819`), so
it's a deliberate doc edit (see §5.2), not a silent add.

**(c) A `tqdm` bar** — nicest UX, but `tqdm` writes to stderr (the print-vs-log tension) and
is a new dependency. Make it an optional `[progress]` extra layered on top of (b), never the
default.

Recommendation: ship (a) now; leave (b) as the seam for later programmatic hooks.

### 4.4 Friction points to budget for (all minor)

- **JPype default-method trap (§5.3).** The probe confirmed the proxy must implement **all
  three** of `init` / `handleStep` / `finish` — `init` and `finish` are interface
  *default* methods, and Python proxies don't inherit them, so a call to one you skipped
  fails. Cost: two trivial extra methods.
- **Throttle the emission.** 361 Java→Python calls over a 6 h run is fine, but emit a log
  line only when crossing a new whole-percent (or every K wall-clock seconds) so long runs
  don't spam the log and the boundary cost stays negligible.
- **Progress is sim-time, not wall-clock-linear.** Monotonic 0 → 1 (good), but force cost
  varies across the orbit (drag near perigee), so any ETA is approximate. One-line docstring
  caveat.
- **Composes with the guard system for free.** The handler is *read-only* — it only observes
  state. On early termination (impact / escape / reentry) or the failure/recovery path, it
  simply stops being called; the existing `try/except` + partial-recovery machinery
  (`numerical.py:1036-1059`) is untouched. Backward propagation is unsupported
  (`duration > 0`), so the fraction is always 0 → 1.

---

## 5. Cross-cutting concerns (shared by all three)

### 5.1 The `force_models` metadata grammar is a contract (items 2 & 3)

The recorded `force_models` token list is a **deterministic, fixed-order, greppable
grammar** so the same config yields byte-identical metadata (`_serialize_force_models`,
`force_models.py:31`; `features.md` §1.1, ~line 322). Adding any force means adding a token
**at a defined position** in that order and updating the example in `features.md`:

- Planetary gravity → `third_body:jupiter`, `third_body:venus`, … grouped with the existing
  `third_body:sun` / `third_body:moon` block.
- Earth radiation → e.g. `earth_radiation`, naturally adjacent to `srp`.

This is the part to treat carefully — it's the genuine contract, more than the physics.
Drive it from `_WiredForces` (what was *actually wired*), never the config booleans, exactly
as the existing serializer does, so metadata never claims a force that isn't acting.

### 5.2 The public signature is a binding contract (item 3b; not items 1/2)

`features.md` §1.1 signatures are binding. **Items 1 and 2 don't touch the signature** —
they ride inside `ForceModelConfig`, which is the designed extension point (new fields are
additive and backward-compatible, though still a `features.md` edit). **Item 3 only touches
the signature if you choose option (b)/(c)**; option (a) is signature-free. Prefer the
additive-config / log-only routes precisely because they avoid editing the frozen verb
signature.

### 5.3 The JPype default-method trap (item 3; not items 1/2)

Items 1 and 2 use stock Orekit force-model classes — no Python proxy, no trap. Item 3
implements the `OrekitFixedStepHandler` interface from Python, so it hits the known trap:
Python proxies don't inherit Java interface `default` methods, and you must implement every
one the Java caller invokes (`init`/`handleStep`/`finish`). This is the same gotcha already
handled elsewhere — the guard detectors deliberately use `FunctionalDetector` + a 1-method
`ToDoubleFunction` + native `StopOnEvent` to *dodge* it (`propagation/guards.py`). For the
step handler the simplest route is to just implement all three methods (proven in the
probe).

### 5.4 Dependencies and "logging, never prints"

Items 1 and 2 add **no dependencies**. Item 3 adds none for option (a); `tqdm` only for
option (c), and only as an optional extra. The "logging, never prints" convention plus the
top-level `NullHandler` is why log-based progress is the idiomatic default and a raw bar is
the opt-in.

---

## 6. Net assessment

- **Planetary third-body gravity — Easy.** A near-verbatim extension of the wired Sun/Moon
  path, no new data, no signature change. Effort is concentrated in the config-surface
  decision and the metadata-grammar token order, not the physics. Low payoff (tiny
  perturbations); ship it as opt-in completeness.
- **Earth radiation pressure — Moderate.** Orekit ships `KnockeRediffusedForceModel` and it
  reuses the existing sphere/box optics, so the wiring is small; the cost is the
  albedo-vs-IR scope/naming decision, a new angular-resolution knob, real per-substep
  runtime, and the grammar token. Most *useful* of the three for the LEO target regime.
- **Progress reporting — Easy (log) to easy–moderate (bar/callback).** The step-handler
  mechanism is proven and composes with the ephemeris generator and the guard system for
  free. Option (a) — log messages from a fixed-step handler — is small, dependency-free,
  contract-free, and idiomatic; richer UX (callback param, tqdm) costs a signature edit
  and/or an optional dep.

All three are mechanically additive behind config/log seams that already exist; the binding
contracts (signature, metadata grammar) are the things to extend deliberately rather than
the JVM boundary.

## 7. See also

- `docs/features.md` §1.1 — the `propagate_numerical` contract: signature, `ForceModelConfig`
  presets, the `force_models` metadata grammar, SRP shadow.
- `docs/architecture.md` — §4/§10 (Orekit types stay internal; lazy JVM), §6
  (`TrajectoryMetadata`), and the force-model / spacecraft sections.
- `src/propygator/propagation/numerical.py` — `_add_perturbation_forces` (:691), the
  third-body wiring (:720-723), `_build_srp_force` (:595), the `propagate()` call (:1037),
  the ephemeris generator (:1026), the sampling loop (:1063-1084), the start/end info logs
  (:933, :1154).
- `src/propygator/propagation/force_models.py` — `ForceModelConfig` (:88) and
  `_serialize_force_models` (:31, the grammar).
- `src/propygator/core/bodies.py` — `_sun` (:79) / `_moon` (:89) accessors to clone.
- `src/propygator/propagation/guards.py` — the `FunctionalDetector` pattern that dodges the
  JPype default-method trap (the contrast case for the step-handler proxy in §5.3).
