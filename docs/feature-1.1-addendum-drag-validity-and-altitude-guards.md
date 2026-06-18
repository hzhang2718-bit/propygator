# propygator — Feature 1.1 Addendum: Drag-Model Validity Domain & Altitude Guards

> **Status: DESIGN / SOURCE OF TRUTH.** This is an add-on design for the
> already-feature-complete numerical propagator (Feature 1.1). It is the binding
> reference for the *next* build plan (the chunked plan will be derived from this,
> the way `docs/history/build-plan-feature-1.1.md` was derived from `features.md`
> §1.1). It is **not** itself a build plan.
>
> **It supersedes specific, enumerated sections of `architecture.md` and
> `features.md` for the time being** (see §1, the supersession map). Where this
> document and those two conflict, *this* document wins until a future
> reconciliation folds it back in. It supersedes **only** what it must; everything
> not listed in §1 is untouched and those docs remain authoritative.

> **Naming convention.** This is one of several planned add-ons to Feature 1.1.
> Each lives in its own file named `feature-1.1-addendum-<topic>.md` so they can be
> written, reviewed, and reconciled independently. This file's topic is the
> propagator's **drag-model validity domain** and the **altitude/regime guard
> system** that bounds and communicates it.

---

## 0. Purpose & scope

Two coupled questions drove this design:

1. **Where is the variable-Cd table actually valid?** The `experiments/drag-coefficient-verification/` study showed the free-molecular sphere Cd collapses onto a single `(geocentric radius, total density)` surface to sub-1% over **300–800 km**, but the shipped table (`scripts/generate_sphere_cd_table.py`) spans **~150–1200 km**, and the experiment does not characterize the edges. The table's *limits* are an unknown to be resolved.
2. **What altitude bounds should the propagator enforce?** The answer to (1) feeds directly into the guard thresholds.

The work is staged: **expand the experiment → analyze → derive constants → implement the guards and regenerate the table.** This document specifies all of it as a contract.

**In scope:** the expanded validity experiment; the Knudsen-number low-altitude floor; the table-edge and regime warnings; the terminal impact/escape backstops; user-settable altitude limits; the unbound-orbit propagation contract; the termination-reporting contract; the Cd-table regeneration invariant.

**Out of scope (unchanged non-goals):** modeling atmospheric entry (aerothermodynamics, breakup, footprint) and deep-space/cislunar dynamics. propygator *guards* these boundaries; it does not *model* beyond them. Per-facet free-molecular Sentman drag remains deferred (`features.md` §1.1, architecture §13).

---

## 1. Supersession map (read this first; it is the reconciliation key)

| Source section | Relationship | What changes |
|---|---|---|
| `features.md` §1.1 → **"Escape and re-entry"** (lines 361–364) | **SUPERSEDED** | The "Planned (deferred)" design is replaced wholesale by §6 here: the ~120 km hardcoded terminal re-entry floor is replaced by *regime warnings (Kn floor) + a graceful classified re-entry catch + an impact backstop at the Earth radius + optional user limits*; the ~1,000,000 km Sun-Earth SOI ceiling is replaced by the **lunar-gravity-parity** ceiling (~346,000 km, §6.3); the previously-open reporting contract is **resolved** (§6.6). The "*Today*" paragraph (current behavior) remains accurate and is retained. |
| `architecture.md` §13 → **"Escape / re-entry guards"** (line 1044) | **SUPERSEDED (resolved)** | This deferral is closed; the guard design is now specified (§6). |
| `architecture.md` §13 → **"Coefficient of drag modeling"** (line 1042) | **EXTENDED** | Unchanged in design; this add-on adds the empirical *validity domain* (altitude band, Kn floor) and strengthens the table-generation-vs-experiment invariant (§5). |
| `features.md` §1.1 → **"Drag-coefficient modeling"** (lines 368–409) | **EXTENDED** | The Tier A/B design is unchanged. Line 374's "the shipped table must be generated on the same geocentric-radius convention" is **strengthened** to the full invariant in §5. The "Out-of-grid → clamp + one-time warning" rule (line 403) is **refined** into the regime-warning tier (§6.2), including the low/high-altitude severity asymmetry. |
| `features.md` §1.1 → **"Public signature"** (lines 13–25) | **EXTENDED** | One keyword-only parameter is added: `limits: AltitudeLimits | None = None` (§6.4). No existing parameter changes. |
| `features.md` §1.1 → **"`propagate_numerical` behavior" → Failure modes table** (lines 343–359) & **Metadata** (lines 289–308) | **EXTENDED** | New rows/keys for altitude-limit termination and graceful stop-and-report (§6.6). |
| `features.md` §1.1 → **"Model limitations (docstring)"** (lines 411–423) | **EXTENDED** | Gains a line stating the drag-model altitude validity band (§6.7). |
| `architecture.md` §6 → **`TrajectoryMetadata`** (lines 491–518) | **EXTENDED** | Gains optional `terminated`, `termination_reason`, `termination_epoch` keys (§6.6). Additive only. |
| `architecture.md` §6 → **`KeplerianElements`** (lines 340–356) & eccentricity validation in `core/elements.py` | **UNCHANGED (explicitly retained)** | The eccentricity gates (`e<0`, parabolic `e==1`, a/e sign coherence, hyperbolic ν-asymptote) stay exactly as-is. Hyperbolic orbits already propagate; this add-on only adds the runaway backstop. See §6.5. |

Anything not in this table is **not** superseded.

**New additions (not supersessions).** §6 introduces two brand-new public names that are *additions* — not edits to existing text — so they are deliberately absent from the map above: the `AltitudeLimits` config dataclass (§6.4) and the `AltitudeLimitError` exception (a `PropagationError` subclass, §6.6). The eventual reconciliation must register them where every other public type lives: `architecture.md` §6 (data model) and §7 (the `__init__.py` re-export list), `core/exceptions.py` (the exception), and a `CHANGELOG.md` `[Unreleased]` entry — all at build time.

---

## 2. Background: the validity question has two different answers

The central insight from the audit, and the reason a naive experiment expansion would mislead:

**A `(altitude, density) → Cd` *collapse* holding is not the same as the Cd *model* being correct.** There are two distinct limits, and they fail at opposite ends:

- **Collapse limit (high-altitude).** Above ~700 km the thermosphere shifts O→He→H, the energy-accommodation coefficient decouples from `(alt, ρ)`, and the collapse scatter genuinely widens. **The experiment can measure this** by watching per-altitude scatter rise. *But drag force ∝ ρ, which is negligible up there, so this limit is soft and rarely binding.*
- **Model-validity limit (low-altitude).** Below ~150–200 km a meter-scale body leaves free-molecular flow (Knudsen number → O(1)); the Sentman/DRIA closed form **systematically over-predicts Cd** in the transitional regime. **The collapse experiment is BLIND to this** — it uses the free-molecular model as its own ground truth, so the collapse stays tight (O-dominated, stable accommodation) *precisely where the model is becoming wrong.* This limit is **hard**, depends on **body size** (Kn = λ/L), and is where drag matters most.

**Consequence for the design:** the high-altitude limit is found by extending the collapse experiment; the low-altitude limit must be found by a **separate Knudsen diagnostic**, never by collapse scatter. The guard system reflects this asymmetry (§6).

---

## 3. Phase 1 — the expanded Cd validity experiment

Extends `experiments/drag-coefficient-verification/` (reference-only code; not shipped, not in CI; runs in the throwaway venv per `docs/experiments_venv.md`). Goal: map the validity domain, not just re-confirm the interior. The generator has a *parallel* change surface (see §7): §5 requires it to match the validated band, so "extend the experiment" is not only an experiment edit.

### 3.1 Acceptance thresholds (define before running)

The collapse residual is a *secondary* error term; the dominant term is the **15–30% thermospheric density-model uncertainty** (`features.md` §1.1, line 407). Two thresholds, set up front so "analyze the results" is a threshold-crossing, not eyeballing:

- **Green / negligible: ≤ ~5%** collapse RMS (≈ ⅓ of the 15% density floor → adds < ~2% in quadrature). Inside this, the table is "as good as it needs to be."
- **Red / model-breakdown: ~30%.** A 30% collapse residual is not "acceptable error" — it means `(alt, ρ)` is no longer a sufficient statistic, i.e. the table's premise has failed. Treat 30% as a **stop line**, not an acceptance bar.

These bound the *high-altitude* (collapse) limit. The *low-altitude* limit is set by the Knudsen diagnostic (§3.4), independently.

### 3.2 Continuous altitude sweep

Replace the 11-point coarse grid (300–800 km / 50 km) with a dense sweep (**~130–1400 km, ~60–100 points**). Run *modestly above* the eventual table ceiling (~1200 km) so the degradation curve is characterized on both sides of the cut — you cannot locate a boundary you stop at — but no higher: the high-altitude limit is **non-binding** (drag ∝ ρ → 0, §2), so extending to 2000 km would spend the most effort on the regime that matters least. Output: collapse RMS vs altitude as a curve; the high-altitude cut is where it crosses the §3.1 green line.

### 3.3 Storm-tail importance sampling

Current sampling is uniform over the interior (F10.7 ≤ 250, Ap ≤ 80). Add a deliberate storm cohort reaching **Ap ∈ [100, 400], F10.7 ∈ [200, 320]** — the events when drag matters most and when the `(alt, ρ)` mapping is most stressed. A *modest* cohort (a handful of high-Ap conditions) is enough to confirm the collapse does not breach the §3.1 thresholds; escalate to a larger (~20%) re-weighting only if that handful shows the residual degrading. Either way the same extremes must still be exercised, since §5 requires the generator's regridded cloud to span them. Report the result.

### 3.4 Knudsen low-altitude diagnostic (the model-validity instrument)

A *separate* diagnostic from the collapse metric (§2). For a stated body characteristic length `L`:

- **λ (mean free path): composition-weighted** from the NRLMSISE per-species number densities and species collision cross-sections — not a single lumped σ — since composition shifts across this band.
- **Threshold: Kn = λ/L ≥ 10** (the conventional conservative free-molecular criterion; 0.1 < Kn < 10 is transitional, where DRIA over-predicts; Kn ≥ 100 would be over-conservative).
- **Conservative atmosphere:** evaluate at high solar activity (expanded → denser at altitude → shorter λ → the Kn = 10 crossing moves *up* → a higher, safer floor).
- **Output:** the floor altitude as a function of `L` (the §3.5 curve). Expected ballpark **~110 km (0.1 m CubeSat) rising to ~200–230 km (5–10 m bus)**, and higher still at high solar activity — *the experiment produces the authoritative numbers; this range is not the answer.*

### 3.5 Body-size parametrization

The collapse is size-independent, but the Kn floor is not. Emit the floor-altitude-vs-`L` curve over a representative range (e.g. 0.1 m CubeSat, 1 m smallsat, 5–10 m bus, even higher ones for space stations). This both validates the free-molecular boundary and *is* the lookup the runtime mirrors (§6.3).

### 3.6 Geocentric-radius axis (close the confound)

The experiment currently keys on **geodetic altitude**; the shipped table and runtime key on **geocentric radius**. Convert each sample to geocentric radius via the forward closed-form `r(h, φ)` (the same map the generator already uses, `generate_sphere_cd_table.py:107–116`) and key the collapse analysis on radius, so the validation lands on the production axis. This is offline, cheap, forward-direction only — it does **not** touch the (correctly avoided) per-substep *inverse* conversion. The residual confound is second-order (density is an explicit axis and absorbs most of the latitude spread), but closing it removes it cleanly.

---

## 4. Phase 2 — analysis & derived quantities

The experiment produces, as committed evidence (figures + captured stdout, per the experiment README's provenance pattern):

1. **Upper table boundary (empirical, soft).** The altitude where collapse RMS crosses the §3.1 green line. Expect this to be a *confidence label*, not a cliff — and, since drag is negligible there, expect it to be **non-binding**. Two numbers may emerge from the one high-altitude run: a *confidence-label altitude* (collapse degradation) and a *coverage ceiling* (how high to extend the grid so legitimate high/elliptical LEO does not trip nuisance warnings).
2. **Kn floor function, `floor_altitude(L)`** (§3.4–3.5), with `Kn = 10`.
3. **Lower table boundary.** Expected to stay **~150 km** (the current `radius_min`); not extended downward (unvalidated, volatile density).

These constants feed §6 (guards) and §7 (table regeneration).

---

## 5. Critical invariant — the shipped table must match the validated experiment

**This is the single most important correctness constraint in this document.**

The validity experiment (`experiments/.../cd_core.py`) and the production table generator (`scripts/generate_sphere_cd_table.py`) are **two independent reconstructions** of the same Sentman/DRIA physics — by deliberate design, the generator does *not* copy the experiment code (generator docstring; experiment README "not even by copying lines over"). **A validity limit derived from the experiment only transfers to the shipped table if the two implementations agree at the boundary** — otherwise you certify one codebase and ship another.

Therefore, before any limit derived in Phase 1–2 is wired into the runtime or used to regenerate the table:

1. **Cross-validate the two models** with a small committed script (throwaway venv, evidenced per §10's provenance pattern) that drives *both* `cd_core.py` and the generator's `_sphere_cd_*` internals off one identical set of NRLMSISE rows at shared `(radius, density, condition)` points and asserts max relative agreement ≪ 1% (well inside the §3.1 green line). **Reconcile the two known default divergences first**, or that target is unreachable by construction:
   - **(i) Accommodation anchor** — both are now set to **α = 0.90 at the 400 km / solar-max anchor** (`cd_core.calibrate_K` and the generator's `ANCHOR_ALPHA`, reconciled from the experiment's earlier 0.82). 0.90 is a commonly-accepted value there: Pilinski, Argrow & Palo's SESAM (2010, *J. Spacecraft & Rockets* 47(6), 951–956) lands ~0.85–0.93, and CHAMP-derived accommodation near 400 km (Moe & Moe 2005, *Planet. Space Sci.* 53(8), 793–801) is ~0.86–0.89.
   - **(ii) Relative-speed computation** — confirm the two `v_rel`/speed formulas agree; the Earth-rotation rate is written two ways (`2π/86164.1 s` vs the `7.2921159e-5 rad/s` constant), which are numerically equal, so check the *full* formula, not just the constant.

   If anything else diverges, reconcile *before* trusting either's edges.
2. **Generation must match the validated setup on every axis that matters:**
   - **Same physics model** (Sentman/DRIA, per-species mass-flux weighting, SESAM-style accommodation, same anchor) — verified by (1).
   - **Same axis** — geocentric radius (§3.6); already true of the generator, now also true of the experiment.
   - **Same condition coverage** — including the storm tails (§3.3); the generator's condition sweep must reach the same extremes the experiment validated, or it will interpolate Cd over a narrower cloud than was certified.
   - **Same altitude range** — the generator's internal altitude sampling and the grid extents must cover (and only claim) the range Phase 1 validated.
3. **The shipped grid *axes* must equal the validated band** (§4) — the table must not *claim* coverage the experiment did not exercise. This constrains the user-facing grid extents, **not** the generator's internal MSIS sampling, which deliberately spans a margin *wider* than the grid so the regrid interpolant covers the mesh corners rather than nearest-filling them. Keep that margin, and record **both** the grid band and the internal-sampling band in `metadata_json`. Reduced-confidence regions (above the green-line altitude) are *labeled in metadata*, not silently presented as validated.

In short: **what is generated must be what was validated, produced by a model proven equal to the validated one.** Generalizes `features.md` §1.1 line 374.

**The Knudsen instrument is a *third* reconstruction.** Because the package may not import the experiment, the runtime Kn-floor scan (§6.3) re-implements the §3.4 mean-free-path / Kn method a third time. The §5 equivalence obligation therefore extends to it: cross-check a few `floor_altitude(L)` points from the runtime scan against the committed experiment curve before the runtime floor is trusted.

---

## 6. Phase 3 — the altitude / regime guard system (runtime contract)

### 6.1 Threshold taxonomy

All guards operate on **geocentric radius** `r = |position|` in the propagation (EME2000) frame — one `sqrt`, no per-substep geodetic conversion (architecture §10; consistent with the table axis). Ordered low → high:

| # | Threshold | Tier | Applies when |
|---|---|---|---|
| 1 | Impact: `r < R⊕` (WGS84 equatorial, 6,378,137 m) | **TERMINAL — stop & report** | always |
| R | Re-entry *(reactive — not a radius; §6.6)*: drag-driven integrator min-step failure at low altitude | **TERMINAL — stop & report** | drag enabled |
| 2 | Knudsen floor: `r < R⊕ + floor_altitude(L)` (§4) | **WARNING** | drag enabled |
| 3 | Table lower edge (~150 km) | **WARNING** | drag enabled **and** a `VariableCd`/`IncidenceVariableCd` table is in use |
| — | *(validated band — silent, all good)* | — | — |
| 4 | Table upper edge (§4, empirical) | **WARNING (soft)** | drag enabled and a table is in use |
| 5 | User min/max altitude limits (§6.4) | **TERMINAL — raise** | when `limits` supplied |
| 6 | Escape: `r > r_lunar_parity` (~346,000 km, §6.3) | **TERMINAL — stop & report** | always |

The **effective** terminal bounds are the *tightest* of the system backstops (1, 6) and the user limits (5): user limits can only tighten termination, never loosen it. System backstops (1, 6) are non-negotiable and always active. A drag-driven re-entry is terminal too, but caught reactively (off the integrator failure) rather than by a radius — see §6.6.

### 6.2 Two-tier behavior

**Warning tier — "drag regime exceeded" (run continues, warn-once per boundary).** Triggered by thresholds 2, 3, or 4. The message is **tailored by edge**, because the two edges are physically asymmetric (§2):

- **Low edge (Kn floor / table lower edge):** drag is large and the model is invalid → loud, e.g. *"WARNING: below the free-molecular / drag-table validity floor (~N km for this body); drag modeling is invalid here and results may be wildly off."*
- **High edge (table upper edge):** Cd is uncertain but multiplies a near-zero force → soft, e.g. *"NOTE: above the drag-table altitude ceiling; drag is negligible at this altitude, so the effect on results is minimal."*

This refines the existing clamp-to-edge + one-time-warning behavior (`features.md` §1.1, line 403): the clamp **stays** (out-of-grid still clamps to the nearest edge per axis; raising mid-run or extrapolating are both rejected), the message is upgraded and edge-aware, and the Kn floor adds a second trigger. With **drag off**, no drag-regime warnings fire (there is no drag model to be invalid); the only low guard is the impact backstop.

**Terminal tier.** Thresholds 1 & 6 (system), 5 (user), and the reactive re-entry catch. See §6.3 and §6.6.

### 6.3 Mechanism

- **Terminal stops → custom radius-based Orekit event detectors**, not the integrator step size, and **not** the stock `AltitudeDetector` (which computes *geodetic* altitude against a body shape every step, reintroducing the conversion we avoid). Each is a thin `g(state) = r − r_threshold` with `Action.STOP`. A *terminal* detector is cheap: the root-finding fires once (at the single crossing); the per-step `g` is a norm. **Build notes (this is a new integration surface — there is no event-detector usage anywhere in the codebase today):** implement each detector as a `@JImplements(EventDetector)` proxy on the `attitude.py` `AttitudeProvider` template, and **override every interface method the propagator invokes, including JPype `default` methods** (Python proxies do not inherit them — the lesson already recorded for `CustomAttitude`); verify inside a *real* `propagate()` call, not in isolation. And note the success path currently samples the ephemeris at a fixed count of offsets up to the *planned* end — a terminal `Action.STOP` shortens the realized span, so the sampling loop must be **clamped to `ephemeris.getMaxDate()`** or it raises when it samples past the crossing. That one clamp serves impact, escape, and the re-entry catch alike.
  - **Impact:** `r_threshold = R⊕ = 6,378,137 m`. The exact value is non-critical — by `R⊕` the orbit is long destroyed and the §6.2 low warnings have fired.
  - **Escape:** `r_threshold = r_lunar_parity ≈ 346,000 km` — the Earth-Moon **equigravisphere** along the Earth-Moon line, where lunar gravity equals Earth's: with `μ⊕/μ☾ ≈ 81.3`, `r ≈ D · √81.3/(1+√81.3) ≈ 0.90 D ≈ 346,000 km` (≈ 8× GEO radius, ≈ 0.9× lunar distance). It is the edge of the *modeled* regime — propygator carries lunar third-body gravity as a *perturbation*; beyond parity the Moon dominates and the Earth-centered formulation breaks down. **This intentionally terminates Earth-bound trajectories whose apogee exceeds lunar parity (e.g. cislunar transfers, weak-stability-boundary orbits) — which is correct, because they are both out of the *modeled* regime (Moon-as-perturbation fails there) and out of *scope* (§0: no deep-space/cislunar dynamics).** It is a moving surface approximated as a static radius (adequate for a backstop). *(This is a deliberate, more-conservative choice than the previously-planned ~1,000,000 km ceiling — which is roughly the **Sun-Earth sphere of influence** (~924,000 km), not the ~1.5 M km Earth Hill sphere; both the prior design and this one prefer a clean radius backstop over an input eccentricity rejection.)*
- **Warnings → checks on the drag-evaluation path** (warn-once boxes, mirroring the existing `VariableCd` clamp warning). No event detector is needed for warnings (they do not stop the run and need no precise crossing).
- **Re-entry → a classified catch of the integrator's min-step failure** (§6.6), not a radius detector or a fixed floor.
- **Kn floor as a static constant.** `floor_altitude(L)` is computed **once at propagation setup** from the spacecraft's characteristic length `L` (sphere → diameter `2√(A/π)`; box → **max edge length**, conservative) and the configured atmosphere model, by scanning altitude for the `Kn = 10` crossing (the experiment's §3.4 method **re-implemented** at runtime — a third independent reconstruction, subject to the §5 equivalence check — over a few dozen atmosphere queries, one-time, not per-substep). The run then checks `r` against the resulting static floor radius. *(This needs a small internal per-species density helper that does not exist yet — the drag force only queries scalar density internally — so budget it as new setup-time code.)* *(Open sub-choice for the build plan: evaluate λ at the initial epoch's space weather — simplest, adapts to conditions — or at a conservative high-activity profile — stabler, slightly safer. Recommend the conservative profile.)*

### 6.4 User-settable altitude limits

New keyword-only parameter on `propagate_numerical` (the only signature change; `features.md` §1.1 lines 13–25 EXTENDED):

```python
@dataclass(frozen=True)
class AltitudeLimits:
    """Optional user terminal altitude bounds for a propagation.

    Altitudes are geodetic km above the WGS84 ellipsoid; each is converted ONCE
    at setup to a geocentric-radius threshold (reference: equatorial radius — a
    documented, slightly conservative approximation consistent with the no-
    per-substep-geodetic-conversion rule; the ~21 km latitude spread is within a
    guard's tolerance). None = no user limit on that side (system backstops still
    apply). Crossing a user limit RAISES (it is a user-requested assertion).
    """
    min_altitude_km: float | None = None
    max_altitude_km: float | None = None
    # __post_init__: finite if given; min < max; warn if a limit lies outside the
    # system backstops (it would be superseded by impact/escape).

# signature gains, keyword-only:
#   limits: AltitudeLimits | None = None      # None -> system backstops only
```

Pure-Python, frozen, safe before init (architecture §10; `None`-sentinel convention, `features.md` §1.1 line 29).

### 6.5 Unbound-orbit propagation (already supported — retained, plus the backstop)

No change to input validation. The repo *already* propagates unbound orbits and this is intentional (`features.md` §1.1 line 363–364):

- `KeplerianElements` already accepts hyperbolic `e > 1` end-to-end (validation + hyperbolic anomaly branches, `core/elements.py:55–140`); `propagate_numerical` takes a Cartesian `State` and has **no** bound-check.
- The eccentricity gates that exist are **validity/representability gates, not a bound restriction**, and are **retained**: `e < 0` (unphysical), `e == 1` (parabolic — no finite `a` in classical elements), a/e sign coherence, and the hyperbolic ν-asymptote (`elements.py:61–104`). Removing any would replace a clean construction-time error with a downstream NaN/crash — strictly worse.

So this add-on does **not** "roll back a check." It adds the **escape backstop** (§6.3, threshold 6) that makes propagating already-supported unbound orbits *safe* — runaway integration terminates cleanly instead of running to absurd distances, and the §6.2 high warnings cover the atmosphere model being driven past its LEO regime on the way out. **Build action:** verify a hyperbolic initial `State` round-trips end-to-end (Orekit numerical propagator + force models) and that the escape detector catches the climb-out — not "remove validation."

### 6.6 Reporting contract (resolves the previously-open question)

This pins what `features.md` §1.1 line 364 left open ("partial `Trajectory` + a `terminated` flag vs a dedicated `PropagationError` subclass"):

- **System backstops (impact, escape) and other physical terminations → stop & report.** Return a **partial `Trajectory`** (samples up to the crossing) with metadata:

  ```python
  # additive optional keys on TrajectoryMetadata (architecture §6 EXTENDED)
  terminated: bool                 # True if a guard stopped the run early
  termination_reason: str          # "reentry" | "impact" | "escape" | "user_min" | "user_max"
  termination_epoch: str           # ISO 8601 UTC of the crossing
  ```
  Re-entry/escape are legitimate physical *outcomes*, not errors — the user wants to know *when/where*.

- **User-set terminal limits (§6.4) → raise.** A user limit is an explicit assertion ("abort if it leaves my band"), so crossing it raises a clear exception (a `PropagationError` subclass, e.g. `AltitudeLimitError`, carrying the boundary and the crossing epoch). Failure-modes table (`features.md` §1.1) EXTENDED with this row.

- **Re-entry via a classified min-step catch → stop & report (the graceful default).** A decaying orbit with drag on stiffens until the adaptive integrator saturates `min_step_s` and the underlying Hipparchus integrator fails. This failure is **caught and classified**, not always re-raised:
  - If it occurred with **drag enabled**, with the orbit **descending** and its **osculating perigee already irrecoverably below the floor** (perigee radius below the table lower edge / ~120–150 km — *not* merely the instantaneous altitude, since a healthy low-perigee pass is descending half of every orbit and would otherwise be mislabeled), it is treated as physical re-entry → return a partial `Trajectory` with `terminated=True`, `termination_reason="reentry"`. The §6.2 low warnings will already have fired on the way down.
  - **Otherwise it re-raises as a genuine `PropagationError`** — a too-tight tolerance, a bad force/initial-state setup, or any non-low-altitude stiffness. Silently relabeling a config/numeric failure as "reentry" would hide a real bug, so **when in doubt the catch re-raises** (a loud error beats a quietly-truncated wrong result). The re-raised error **may carry the partial `Trajectory`** as an attribute for advanced recovery, while still failing loudly. **Invariant: prefer a false re-raise over a false `reentry`** — a missed re-entry surfaces as a loud, fixable error, whereas a false `reentry` would return a silently-truncated wrong trajectory.

  The Kn floor itself stays a **warning, never a terminal trigger** (§6.2): a survivable low-perigee orbit dips below it and climbs back out *without failing*, so it never reaches this classifier — only an actual integrator failure is classified. *(Implementation note — **verified feasible**. Running the propagator in ephemeris-generation mode and reading `generator.getGeneratedEphemeris()` after the exception recovers the samples up to the failure — confirmed on a real drag decay, which yielded a usable partial ephemeris. Two edges the build must handle: on a config-error saturation with no good steps, `getGeneratedEphemeris()` itself raises — wrap it and fall through to the plain re-raise with no partial attached; and a real decay's partial span can dip below `R⊕`, so order the impact detector (threshold 1) ahead of relying on this catch. Sample the recovered ephemeris only over its achieved span, per the §6.3 clamp.)*

**Downstream behavior of a partial/terminated `Trajectory`.** It is an ordinary `Trajectory`: every existing Feature 1.1 verb (`plot_*`, `export_csv`/`export_all`, `to_keplerian`, `to_frame`, `at`) operates on it unchanged, and plots may optionally annotate `termination_epoch`. The three metadata keys are written **only when `terminated=True`**, so a normal completed run's `Trajectory.metadata` and its `export_csv` header are byte-for-byte what they are today (the §8 "absent/False" case) — no churn for the common path.

### 6.7 Docstring limitation note (EXTENDS `features.md` §1.1 lines 411–423)

Add to the user-facing "Spacecraft-model limitations (v1)" block:

```
  * Drag modeling is valid only within an altitude band (free-molecular flow
    above a body-size-dependent floor of ~N km, up to the Cd-table ceiling).
    Below the floor the run continues with a warning but drag is unreliable;
    a decaying orbit ends gracefully at re-entry, impact and escape terminate
    the run, and user limits may tighten this.
```

---

## 7. Cd table regeneration

Regenerate `data/sphere_cd_default.npz` via `scripts/generate_sphere_cd_table.py`, subject to §5:

- **Generator-side code edits (the twin of "extend the experiment").** Widening the validated band is not only an experiment change: the generator's internal altitude sampling is a hardcoded literal (`linspace(130, 1250, 48)`, not a CLI arg) and its condition sweep is not parameterized for storm tails. Lift the altitude sampling to a constant/CLI arg so it tracks the validated band, and add the storm cohort to the condition sampler — so the regridded cloud spans the same certified extremes the experiment validated (§5 "same condition coverage" / "same altitude range").
- **Extents** set to the Phase 2 validated band (lower ~150 km retained; upper per §4).
- **Conditions** extended to the storm tails the experiment validated (§3.3) so the regridded cloud spans the certified extremes.
- **Confidence label** for reduced-confidence regions (above the green-line altitude) recorded in the table's `metadata_json`.
- Cross-validation against the experiment model (§5) done and recorded before the new `.npz` is committed.

This is a maintainer step (throwaway venv, `pymsis` + `scipy`); nothing changes for end users (they still load an array and compute nothing).

---

## 8. What the end product looks like

**Normal LEO run (inside the band) — unchanged from today:**

```python
import propygator as pgr
traj = pgr.propagate_numerical(iss_state, duration=86400.0, output_step=60.0)
# no warnings; traj.metadata["terminated"] is absent/False
```

**Decaying orbit, drag on, dips below the free-molecular floor:**

```text
WARNING: below the free-molecular / drag-table validity floor (~165 km for this
6.0 m body); drag modeling is invalid here and results may be wildly off.
```
(run continues; warning emitted once)

**Run that reaches re-entry (stop & report):**

```python
traj = pgr.propagate_numerical(decaying_state, duration=30*86400.0, output_step=600.0)
traj.metadata["terminated"]          # True
traj.metadata["termination_reason"]  # "reentry" — drag decay caught at min-step
                                     #   saturation ("impact" is reserved for a
                                     #   drag-off sub-surface orbit caught at R⊕)
traj.metadata["termination_epoch"]   # "2026-07-02T14:08:31Z"
# traj holds the samples up to re-entry
```

**User-bounded run that leaves the band (raises):**

```python
traj = pgr.propagate_numerical(
    state, duration=86400.0, output_step=60.0,
    limits=pgr.AltitudeLimits(min_altitude_km=200.0, max_altitude_km=2000.0),
)
# -> AltitudeLimitError: propagation crossed user min altitude 200.0 km
#    at 2026-06-14T09:12:44Z
```

**Hyperbolic / escape trajectory (already valid input; now safely bounded):**

```python
traj = pgr.propagate_numerical(hyperbolic_state, duration=10*86400.0, output_step=3600.0)
traj.metadata["terminated"]          # True
traj.metadata["termination_reason"]  # "escape"   (crossed ~346,000 km)
```

---

## 9. Decisions log

### Resolved by this add-on

- **Low-altitude guard** = a body-size-dependent **Kn ≥ 10 warning floor** (never terminal) + a **graceful classified re-entry catch** on the integrator's min-step failure (stop & report, `reentry`; non-re-entry failures still raise) + an **impact backstop at `R⊕`** (stop & report). Replaces the hardcoded ~120 km terminal re-entry floor.
- **Escape guard** = terminal stop & report at the **lunar-gravity-parity radius (~346,000 km)**, replacing the ~1,000,000 km Sun-Earth SOI ceiling.
- **Guard axis** = geocentric radius throughout; custom radius event detectors for terminal stops (not step size, not stock `AltitudeDetector`).
- **User altitude limits** = new `AltitudeLimits` config + `limits=` parameter; nests inside the system backstops; **raises** on crossing.
- **Reporting contract** = stop-and-report (partial `Trajectory` + `terminated`/`termination_reason`/`termination_epoch`) for system/physical terminations; **raise** for user limits.
- **Unbound orbits** = already supported; eccentricity gates **retained**; only the escape backstop is added.
- **Table generation invariant** = §5 (model equivalence + matched axis/conditions/range/extents).
- **Acceptance thresholds** = ~5% green / ~30% red for the collapse-limit; Kn = 10 for the model-validity floor.

### Still open (for the build plan to resolve)

- Exact **upper table boundary** and **`floor_altitude(L)` numbers** — outputs of Phase 1–2, not guessed here.
- Kn-floor atmosphere choice: **initial-epoch vs conservative high-activity** (§6.3). Recommend conservative.

---

## 10. Definition of done

1. Expanded experiment (§3) run in the venv; figures + captured stdout committed as evidence; validity domain (high cut, Kn floor curve) reported against the §3.1 thresholds.
2. Model cross-validation (§5) passed and recorded — Cd (experiment vs generator) **and** the runtime Kn-scan vs the experiment curve, with the accommodation anchor (α = 0.90) and the relative-speed formula reconciled first.
3. Table regenerated (§7) to the validated extents/conditions, with confidence labels.
4. Guard system (§6) implemented: warnings (two-tier, edge-tailored), terminal radius detectors (impact, escape) via `@JImplements` with every default method overridden and the ephemeris sampling clamped to the achieved span, classified min-step re-entry catch (stop & report) with partial-trajectory recovery (incl. the empty-ephemeris and sub-`R⊕` edges) on re-raise, `AltitudeLimits` + `limits=` param, reporting contract + metadata keys (written only when terminated), docstring note.
5. Hyperbolic round-trip + escape-catch verified (§6.5).
6. Tests: warning emission at each edge; clean stop-and-report at impact/escape; **classified re-entry catch returns a partial `Trajectory` on a drag-driven decay, while a non-re-entry min-step failure (e.g. an over-tight tolerance) still raises**; raise at user limits; hyperbolic propagation terminating at escape; Kn-floor computed from geometry. JVM-touching tests acquire the `orekit` fixture (architecture §11).
7. Supersession map (§1) carried into the eventual `features.md`/`architecture.md` reconciliation.
