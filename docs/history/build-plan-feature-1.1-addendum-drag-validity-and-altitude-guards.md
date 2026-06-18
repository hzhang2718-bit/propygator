# Build plan: Feature 1.1 Addendum — Drag-model validity domain & altitude guards

> **Status: BUILD PLAN (started).** Derived from
> `docs/history/feature-1.1-addendum-drag-validity-and-altitude-guards.md`, which is the
> **binding contract** for this work (the way `features.md` §1.1 was for the
> original 1.1 build plan). Every threshold, signature, metadata key, and
> invariant below traces to a section of that addendum — cited inline as
> "(addendum §X)". Where this plan and the addendum disagree, the **addendum
> wins**; fix the plan.

## Context

Feature 1.1 (the numerical propagator) is **code-complete** on branch
`feature/numerical-propagator` (its own build plan is archived at
`docs/history/build-plan-feature-1.1.md`; merge into `main` is intentionally
deferred). `propagate_numerical`, the config dataclasses, the attitude family,
the `plot_*` verbs, and `export_csv`/`export_all` all exist and are re-exported
at the top level. 549 tests pass.

**This plan builds the drag-validity & altitude-guard addendum** — two coupled
workstreams (addendum §0):

1. **Offline (maintainer) — the drag-model validity domain.** Expand the
   reference experiment to map *where* the variable-Cd table is valid (a
   body-size-dependent Knudsen low-altitude floor and an empirical high-altitude
   cut), prove the experiment and the table generator are the same physics, and
   regenerate the shipped table to the validated band. Runs in the throwaway
   venv (`docs/experiments_venv.md`); reference-only, not shipped, not in CI.
2. **Runtime (shipped) — the altitude/regime guard system.** A geocentric-radius
   guard family: terminal impact + escape backstops (custom Orekit event
   detectors), edge-aware drag-regime warnings (Kn floor + table edges), a
   classified min-step re-entry catch, optional user `AltitudeLimits`, and a
   stop-and-report reporting contract (raising only a construction-time `ValueError`
   for an unreasonable limit) with new `Trajectory` metadata.

The end state matches addendum §8 "What the end product looks like" and §10
"Definition of done": a normal LEO run is unchanged; a decaying run stops and
reports `terminated`/`termination_reason`/`termination_epoch`; impact/escape
terminate cleanly; reasonable user limits stop & report (unreasonable ones rejected at construction); and the shipped Cd table only claims the
altitude band the experiment validated.

**Source-of-truth docs (do not silently diverge):**
- `docs/history/feature-1.1-addendum-drag-validity-and-altitude-guards.md` — **the
  binding contract.** §1 supersession map, §2 the collapse-vs-Kn asymmetry, §3
  the experiment, §4 derived quantities, §5 the model-equivalence invariant, §6
  the runtime guard contract (6.1 thresholds, 6.3 mechanism, 6.4 `AltitudeLimits`,
  6.6 reporting), §7 table regeneration, §10 definition of done.
- `docs/features.md` §1.1 and `docs/architecture.md` (§6 data model, §10
  lazy-JVM/explicit-frame/internal-Orekit, §11 testing, §13 deferrals) — still
  authoritative **except** for the sections the addendum §1 map supersedes/extends.
- `docs/experiments_venv.md` — the throwaway-venv pattern for Chunks 1–4.
- `docs/orekit_setup_reference.md` — JVM boilerplate + Java↔Python boundary
  patterns. **Self-flagged stale; verify any snippet against the installed
  13.1.x API** (a wrong constant spelling is a runtime error).

**Decisions already locked (do not relitigate):**
- **Accommodation anchor α = 0.90** at the 400 km / solar-max anchor, in *both*
  `cd_core.calibrate_K` and the generator's `ANCHOR_ALPHA` (already reconciled in
  the working tree; addendum §5, with citations). Chunk 3 only has to *prove* the
  two models now agree.
- **Escape ceiling = lunar-gravity-parity radius ≈ 327,000 km** (perigee parity; a
  fixed hard-coded policy constant, *not* Orekit-derived — addendum §6.3), not the
  old ~1,000,000 km Sun-Earth SOI ceiling.
- **High-altitude sweep ceiling ≈ 1400 km** (addendum §3.2 — modestly above the
  ~1200 km table ceiling; the high limit is non-binding).
- **Guard axis = geocentric radius**, terminal stops via custom radius event
  detectors (never the stock `AltitudeDetector`, never step size; addendum §6.3).
- **Reporting contract** = stop-and-report for all runtime terminations (system
  backstops, re-entry, *and* reasonable user-limit crossings); the only `raise` is a
  construction-time `ValueError` for an unreasonable `AltitudeLimits` (addendum §6.6).
- **Eccentricity gates retained** as-is (addendum §6.5) — this work *adds* the
  escape backstop, it does not remove validation.

**Decisions to confirm before/at the relevant chunk (defaults chosen; "You
provide" flags them):**
- **Branch strategy** (see Git section) — recommended: a new branch off
  `feature/numerical-propagator`.
- **Kn-floor atmosphere profile** — initial-epoch vs conservative high-activity
  (addendum §6.3, §9). **Default: conservative high-activity** (stabler, safer,
  deterministic for tests). Confirmed at Chunk 9.
- **Validated band numbers** (upper cut, `floor_altitude(L)` curve) — *outputs of
  Chunks 1–3*, not guessed; you sign off before the table is regenerated (Chunk 4)
  and before the runtime floor is wired (Chunk 9).

**Architecture invariants to honor in every runtime chunk** (CLAUDE.md /
architecture §4, §10): Orekit/Java types stay internal (public APIs accept/return
only propygator types); import `jpype`/`orekit_jpype`/`pyhelpers` **lazily inside
functions**, never at module top; SI internally (km only at the user boundary);
frames explicit; `pathlib.Path`; `logging`, never `print`; frozen dataclasses with
`__post_init__` validation; new public types re-exported from the top-level
`__init__.py` while keeping `import propygator` JVM-free.

---

## How to use this plan

- **11 numbered chunks**, each sized for one Claude Code session and
  independently verifiable. Two workstreams:
  - **Chunks 1–4 are offline/maintainer** (throwaway venv; produce committed
    *evidence* — figures + captured stdout + the regenerated `.npz` — not pytest
    tests; reference-only, excluded from CI/lint/mypy).
  - **Chunks 5–10 are shipped runtime code** (propygator conda env; pytest, with
    JVM-touching tests acquiring the `orekit` fixture). **Chunk 11 is wrap-up.**
- Each chunk lists **Goal / Create-Edit / Reuse / You provide / You run /
  Verify**. **You provide** is called out every chunk (often "nothing") so you
  always know whether a session needs input from you.
- **Sequencing.** The default order follows the addendum's staging (expand
  experiment → analyze → derive constants → regenerate table → build guards). The
  two workstreams are *largely independent*: the **only** hard cross-dependency is
  **Chunk 9** (Kn-floor + table-edge warnings), which consumes the validated Kn
  method and the band numbers from Chunks 2–4. So if you'd rather start with
  shipped code, Chunks 5–8 and 10 can precede the experiment chunks; just keep
  Chunk 9 after Chunks 2–4 (and after Chunk 6, whose drag-path/clamp it builds on).
- **Checkpoints** (CLAUDE.md refresh + `/code-review` + `/simplify`) are marked
  inline after the chunks where they pay off.
- **New test files** land in the existing `tests/propagation/` package (created in
  the original 1.1 build) and `tests/core/` (for the new exception). No new test
  subpackage is needed. The offline chunks add no pytest files.
- **Mergeable chunks:** 7 (user limits) can fold into 6 if that session has
  capacity; 10 (hyperbolic verify + docstring) is small and can ride with 9 or 11.
  They're split for safety, not because they must be separate.

---

## Git: branch strategy (read once, before Chunk 1) - Done

You've now done one feature branch (`feature/numerical-propagator`); the full
end-to-end walkthrough is in `docs/history/build-plan-feature-1.1.md` ("Git: the
feature-branch walkthrough") if you want to re-read the rhythm. Only one wrinkle
is new here.

**The wrinkle: Feature 1.1 isn't merged to `main` yet.** This addendum *extends*
the 1.1 propagator, so its code must sit on top of the 1.1 code, which lives only
on `feature/numerical-propagator`. So you do **not** branch from `main`.

**Recommended (confirm before Chunk 1):** create a new branch from the 1.1 branch
so the two bodies of work stay reviewable as separate PRs:
```powershell
conda activate propygator
git switch feature/numerical-propagator
git pull
git switch -c feature/drag-validity-and-altitude-guards
git push -u origin feature/drag-validity-and-altitude-guards
```
Then the eventual merge order is your call — either merge 1.1 first and this PR
after, or merge both together. (An equally valid simpler option: just keep
committing on `feature/numerical-propagator` and ship one larger PR. Pick based on
how separable you want the review to be.)

**Per-chunk rhythm** is unchanged: `git status` → `git add -A` →
`git commit -m "addendum chunk N: <summary>"` → `git push` (CI runs on the
branch). Commit/push and PR/merge are **yours** — Claude won't push or open a PR
without you asking.

**You provide (git):** confirm the branch choice before Chunk 1; `gh`
authenticated before Chunk 11.

---

## Chunk 1 — Experiment expansion: continuous sweep + geocentric-radius rekey + storm cohort + thresholds - Done

**Goal:** turn the interior-only collapse study into a *boundary-finding* one — a
dense altitude sweep on the **production axis** (geocentric radius), with a storm
cohort and explicit pass/fail against the acceptance thresholds. This maps the
**high-altitude (collapse) limit**; the low-altitude limit is Chunk 2 (addendum
§2 — they fail at opposite ends and need different instruments).

**Create / edit** (all in `experiments/drag-coefficient-verification/`, throwaway
venv):
- `cd_sphere_experiment.py` (and `cd_box_experiment.py` to match) —
  - Replace the 11-point coarse grid (`ALTS = np.arange(300., 801., 50.)`) with a
    **dense sweep ~130–1400 km, ~60–100 points** (addendum §3.2). Run modestly
    above the ~1200 km table ceiling so the degradation curve is seen on both
    sides of the cut; no higher (the high limit is non-binding).
  - **Re-key the collapse analysis on geocentric radius** (addendum §3.6):
    convert each sample's geodetic altitude to radius with the **forward
    closed-form `r(h, φ)`** the generator already uses
    (`generate_sphere_cd_table.py` `_geocentric_radius`, ~lines 107–116) and bin
    the collapse on radius. Forward-direction only — do **not** introduce any
    per-sample inverse conversion.
  - **Storm-tail importance sampling** (addendum §3.3): extend `make_conditions()`
    to reach **Ap ∈ [100, 400], F10.7 ∈ [200, 320]**. A *modest* cohort (a handful
    of high-Ap conditions) is enough to confirm no threshold breach; only escalate
    to a ~20% re-weighting if the residual visibly degrades. The extremes must
    still be exercised (§5 needs the generator to span them later).
  - **Acceptance thresholds as code** (addendum §3.1): compute collapse RMS and
    report it against **green ≤ ~5%** and **red ~30%** per altitude band and under
    storm conditions — print a clear pass/fail, not an eyeballed plot.
- Update the figure(s) + the captured-stdout results file to the new axis/sweep.

**Reuse:** the existing `cd_core.py` collapse machinery (`cd_total`, `v_rel`,
`SPECIES`/`IDX`); the generator's forward `_geocentric_radius` formula (re-derive
or mirror it in the experiment — do not import the package). The experiment's
existing provenance pattern (committed PNG + redirected stdout, per its README).

**You provide:** confirm the throwaway venv is available (`pymsis` + `scipy` +
`matplotlib`, per `docs/experiments_venv.md`). Nothing else.

**You run:** in the venv, run the sweep and redirect stdout to the results file
(the experiment's documented pattern); eyeball the new figure; commit the evidence.

**Verify:** the collapse RMS-vs-radius curve is produced; the green-line crossing
(the high-altitude cut) is identifiable; the storm cohort's RMS is reported
against §3.1. Bare `pytest` is unaffected (experiment is outside `testpaths`).

---

## Chunk 2 — Knudsen low-altitude diagnostic + body-size floor curve - Done

**Goal:** the **model-validity instrument** the collapse experiment is blind to
(addendum §2). A separate Knudsen-number diagnostic that finds the
free-molecular floor as a function of body size — the load-bearing physics of the
whole guard system, and the method the runtime re-implements in Chunk 9.

**Create / edit** (`experiments/drag-coefficient-verification/`, venv):
- A new module (e.g. `kn_floor.py`) computing, for a stated characteristic length
  `L` (addendum §3.4–3.5):
  - **Composition-weighted mean free path λ** from the NRLMSISE per-species number
    densities and per-species collision cross-sections σ — **not** a single lumped
    σ (composition shifts across 120–250 km). Add a small documented σ table.
  - **`Kn = λ / L`**, with the **free-molecular threshold `Kn = 10`** (0.1 < Kn <
    10 is the transitional regime where DRIA over-predicts; Kn = 100 would be
    over-conservative).
  - **`floor_altitude(L)`** = scan altitude for the `Kn = 10` crossing, evaluated
    at a **conservative high-activity** atmosphere (denser → shorter λ → the
    crossing moves up → a higher, safer floor).
  - Emit the **floor-altitude-vs-`L` curve** over a representative range (0.1 m
    CubeSat → ~10 m bus/station). Expected ballpark ~110 km (small) rising to
    ~200–230 km (large), solar-activity dependent — *the run produces the
    authoritative numbers; this is not the answer* (addendum §3.4).
- A figure (floor vs L) + captured stdout as committed evidence.

**Reuse:** `cd_core.py`'s MSIS-row access and `IDX`/`SPECIES` (per-species
densities are already pulled there); the venv `pymsis`. This is mostly **net-new**
code — there is no λ/Kn machinery in the experiment today (audit confirmed).

**You provide:** nothing (σ values come from standard kinetic-theory references;
cite them in the module docstring).

**You run:** run in the venv; commit the figure + stdout.

**Verify:** the `floor_altitude(L)` curve is produced and monotonic in `L`; a
couple of hand-checked points land in the expected ballpark; the conservative
atmosphere gives a *higher* floor than a mid-activity one (sanity of the
direction).

---

## Chunk 3 — Phase-2 analysis + model cross-validation (the §5 invariant) - Done

**Goal:** turn the Chunk 1–2 runs into the **committed constants** the rest of the
work consumes, and discharge the addendum's single most important correctness
constraint (§5): prove the experiment and the table generator are the same
physics, so a limit found in one transfers to the other.

**Create / edit** (`experiments/drag-coefficient-verification/`, venv):
- **Phase-2 derived quantities** (addendum §4), recorded as evidence:
  1. **Upper table boundary** — the radius/altitude where collapse RMS crosses the
     §3.1 green line (a soft *confidence label*, expected non-binding), plus a
     *coverage ceiling* (how high to extend the grid so legitimate high LEO does
     not trip nuisance warnings).
  2. **`floor_altitude(L)`** from Chunk 2.
  3. **Lower boundary** — expected to stay **~150 km** (current `radius_min`); not
     extended downward.
- **Cross-validation script** (addendum §5) — the named deliverable: drive *both*
  `cd_core.py` and the generator's `_sphere_cd_*` internals off **one identical set
  of NRLMSISE rows** at shared `(radius, density, condition)` points and assert
  **max relative agreement ≪ 1%**. Reconcile-first items:
  - **(i) Accommodation anchor** — already α = 0.90 in both (working tree); confirm.
  - **(ii) Relative-speed formula** — verify the two `v_rel`/speed computations
    agree (the Earth-rotation rate is written two ways — `2π/86164.1 s` vs the
    `7.2921159e-5 rad/s` constant — which are numerically equal; check the *full*
    formula, not just the constant).

  The generator's heavy imports are deferred inside `generate()`, so importing its
  `_sphere_cd_*` helpers in the venv is cheap. Commit the script's stdout as
  evidence.

**Reuse:** Chunks 1–2 outputs; the generator module's importable internals; the
provenance pattern.

**You provide:** **sign off the validated band** — the upper cut/coverage ceiling
and the retained ~150 km lower edge. These feed Chunks 4, 9, and 10.

**You run:** run the cross-validation in the venv; commit evidence; record the
band numbers (in the experiment README and/or addendum §9).

**Verify:** the two Cd models agree ≪ 1% at the shared points (if not, reconcile
before proceeding — a divergence here invalidates the regenerated table); the
three Phase-2 quantities are recorded with evidence.

> ### ✅ Checkpoint A — validity domain established - Done
> 1. The validity domain (high cut, `floor_altitude(L)` curve, ~150 km floor) is
>    measured against the §3.1 thresholds and the two Cd models are proven equal
>    (addendum §10 items 1–2).
> 2. Record the agreed band numbers where the runtime chunks will read them.
> 3. Commit + push.

---

## Chunk 4 — Cd table regeneration to the validated band - Done

**Goal:** ship a table that claims **only** what was validated (addendum §5/§7) —
the table generator's edits + the regenerated `data/sphere_cd_default.npz` +
confidence labelling.

**Create / edit:**
- `scripts/generate_sphere_cd_table.py` — the **generator-side twin** of "extend
  the experiment" (audit-flagged; addendum §7):
  - Lift the **hardcoded internal altitude sampling** (`linspace(130.0, 1250.0,
    48)`, ~line 268) to a constant/CLI arg so it tracks the validated band.
  - **Parameterize the condition sweep** (`_sample_conditions`, ~lines 213–239)
    to include the **storm tails** the experiment validated, so the regridded
    cloud spans the same certified extremes.
  - Keep the **internal-sampling-wider-than-grid margin** (it samples beyond the
    grid so the regrid covers mesh corners rather than nearest-filling them);
    record **both** the grid band and the internal-sampling band in
    `metadata_json` (addendum §5.3 — "grid *axes* = validated band", not the
    internal sampling).
  - Add a **confidence label** for reduced-confidence regions (above the
    green-line altitude) to `metadata_json`. The runtime loader reads only
    `grid`/`radius_axis`/`density_axis` and ignores `metadata_json`
    (`spacecraft.py` `VariableCd.sphere_default`, ~lines 283–291), so this is
    format-compatible with **no loader change**.
- `data/sphere_cd_default.npz` — regenerate to the validated extents/conditions.

**Reuse:** the existing generator structure (regrid + nearest-fill edge handling);
the Chunk 3 cross-validation result (must be green before committing the `.npz`).

**You provide:** final sign-off on the shipped grid extents (the Chunk 3 band) and
the regenerated table before it's committed.

**You run:** regenerate in the venv; commit the new `.npz` + the generator edits +
the cross-validation record.

**Verify:** the `.npz` grid axes equal the validated band; `metadata_json` carries
both bands + the confidence label; the cross-validation (§5) is recorded as done
*before* the commit. Back in the conda env, `VariableCd.sphere_default()` still
loads (no loader change). `python scripts/generate_sphere_cd_table.py --help`
runs in the bare env.

---

## Chunk 5 — Runtime foundations: `AltitudeLimits` + escape policy constant + metadata keys - Done

**Goal:** the pure-Python, safe-before-init surface of the guard system —
unit-testable with **no JVM**. Establishes the home module (`propagation/guards.py`)
the JVM-touching guard code lands in next.

**Create / edit:**
- `src/propygator/propagation/guards.py` (new) — `AltitudeLimits` frozen dataclass
  exactly per addendum §6.4: `min_altitude_km: float | None = None`,
  `max_altitude_km: float | None = None`; `__post_init__` validates each finite
  if given, `min < max`, and **raises `ValueError`** (like every other config
  dataclass) on an *unreasonable* limit — one outside the system backstops that
  could never bind: `min_altitude_km < 0` (below the surface) or `max_altitude_km`
  above the escape-parity altitude. Both are pure altitude comparisons against
  fixed policy bounds, so the validator stays **JVM-free / safe-before-init**.
  Also define the module-level **escape-parity policy constant** here (perigee
  lunar parity; `0.90 · D_perigee`, formula + chosen `D` in a comment; *not*
  Orekit-derived). Store it as an **altitude** bound (≈ 320,650 km = the ≈ 327,000 km
  perigee-parity *radius* minus the WGS84 equatorial radius) so this `max` check
  needs no `R⊕` and stays JVM-free; the Chunk 6 escape detector lowers the *same*
  constant to a geocentric radius (adding the Orekit `R⊕`, identical to how user
  limits are lowered) — one source of truth for both. Docstring records the
  "geodetic km → geocentric-radius via equatorial radius, converted once at setup"
  approximation (the ~21 km latitude spread is within a guard's tolerance).
- *(No new exception type.)* An unreasonable `AltitudeLimits` raises the builtin
  `ValueError` from `__post_init__` (above); a reasonable limit never raises — it
  stops & reports at runtime (Chunk 7). So `core/exceptions.py` is **unchanged**.
- `src/propygator/core/states.py` — extend the `TrajectoryMetadata` `TypedDict`
  (`total=False`) with the three **optional, additive** keys (addendum §6.6):
  `terminated: bool`, `termination_reason: str`, `termination_epoch: str`. Do
  **not** add them to `_REQUIRED_METADATA_KEYS`. (Allowed values for
  `termination_reason`: `"reentry" | "impact" | "escape" | "user_min" |
  "user_max"`.)
- `src/propygator/__init__.py` — re-export `AltitudeLimits`; keep `import propygator`
  JVM-free.
- **Tests** (`tests/propagation/test_guards.py`, pure-Python): every
  `AltitudeLimits.__post_init__` branch — finite, `min < max`, and the
  unreasonable-limit `ValueError` (negative `min`; `max` above the escape-parity
  altitude); constructing `AltitudeLimits` does **not** start the JVM.

**Reuse:** the frozen-dataclass + `__post_init__` **`ValueError`** idiom from
`IntegratorConfig` (`integrators.py:44–66`) / `SpacecraftGeometry`.

**You provide:** nothing (the dataclass is fully specified in §6.4).

**You run:** the per-chunk git rhythm.

**Verify:** `pytest tests/propagation/test_guards.py tests/core -v` green and
JVM-free; `python -c "import propygator, jpype; print(jpype.isJVMStarted())"` →
`False`.

---

## Chunk 6 — Terminal radius detectors (impact + escape) + sampling clamp + stop-and-report - Done

**Goal:** the core new Orekit integration surface — custom geocentric-radius event
detectors that stop the run cleanly at impact and escape, the ephemeris-sampling
fix they require, and the partial-`Trajectory` + termination-metadata assembly
(addendum §6.1 thresholds 1 & 6, §6.3 mechanism, §6.6 stop-and-report).

**Create / edit:**
- `src/propygator/propagation/guards.py` — a `@JImplements(EventDetector)` radius
  detector: `g(state) = r − r_threshold` with an `Action.STOP` handler (one
  factory for the impact threshold, one for escape). **Override every interface
  method the propagator invokes, including JPype `default` methods** — Python
  proxies do not inherit them (the lesson already recorded for `CustomAttitude`);
  model it on the `attitude.py` `AttitudeProvider` proxy (~lines 464–524).
  Thresholds:
  - **Impact** `r = R⊕` — use `Constants.WGS84_EARTH_EQUATORIAL_RADIUS`
    (= 6,378,137 m; already used in `core/bodies.py`), not a literal.
  - **Escape** `r = r_lunar_parity` — lower the **escape-parity policy constant
    from Chunk 5** (perigee lunar parity, stored as the ≈ 320,650 km altitude bound)
    to a geocentric radius by adding the Orekit equatorial radius (→ ≈ 327,000 km),
    the *same* altitude→radius lowering used for user limits. It is a **fixed,
    hard-coded policy constant — *not* derived from Orekit `Constants`** (the
    Earth-Moon distance is not a `Constants` member; the value is a deliberately
    fuzzy fence — addendum §6.3).
- `src/propygator/propagation/numerical.py` —
  - Register the impact + escape detectors on the propagator (both always active;
    addendum §6.1).
  - **Clamp the ephemeris-sampling loop to the achieved span.** The current
    success path samples a fixed count of offsets up to the *planned* end (~lines
    810–841); a terminal `Action.STOP` shortens the realized span, so read
    `ephemeris.getMaxDate()` and only sample offsets `≤ (maxDate − start)`,
    recomputing the realized sample count. **This one clamp serves impact, escape,
    and the Chunk-8 re-entry catch** — build it generally.
  - When a terminal detector fires, assemble a **partial `Trajectory`** with
    `terminated=True`, `termination_reason` (`"impact"` / `"escape"`), and
    `termination_epoch` (ISO-8601 UTC of the crossing). **Write the three keys
    only when terminated** so a normal run's metadata/CSV are byte-identical to
    today (addendum §6.6, §8).
- **Tests** (`tests/propagation/`, JVM-touching → `orekit` fixture): a drag-off
  sub-surface orbit stops at `R⊕` with `termination_reason="impact"` and a partial
  trajectory ending near the crossing; a climbing/hyperbolic-ish state stops at the
  escape radius with `"escape"`; a normal LEO run is **unchanged** (no `terminated`
  key, same sample count as before). Verify the detector fires inside a real
  `propagate()` (not in isolation) — the JPype default-method trap only shows up in
  the real call path.

**Reuse:** the `@JImplements`/`@JOverride` pattern (CLAUDE.md Java-boundary notes;
`attitude.py`); `Trajectory.from_arrays` (accepts a short sample list already); the
metadata keys from Chunk 5; `core/bodies.py` constants.

**You provide:** nothing.

**Verify:** `pytest tests/propagation -v` green; impact/escape produce partial
trajectories with the right metadata; the normal-run regression (unchanged
output) passes.

---

## Chunk 7 — User altitude limits (`limits=` param + tightest-of nesting + stop & report) - Done

**Goal:** wire `AltitudeLimits` into the public signature and make a *reasonable*
user-limit crossing **stop & report** like the system backstops (addendum §6.1
threshold 5, §6.4, §6.6). Unreasonable limits are already rejected at construction
by Chunk 5's `__post_init__` `ValueError`, so there is nothing to do for them here.

**Create / edit:**
- `src/propygator/propagation/numerical.py` — add the keyword-only parameter
  `limits: AltitudeLimits | None = None` (the **only** signature change; addendum
  §6.4). Lower each supplied limit **once at setup** to a geocentric-radius
  threshold (equatorial-radius reference) and register a radius detector for it,
  reusing the Chunk 6 detector + stop-and-report machinery.
  Enforce the **tightest-of rule**: user limits can only *tighten* termination,
  never loosen the always-on system backstops (1, 6). On a user-limit crossing,
  **stop & report** — return the partial `Trajectory` with `terminated=True`,
  `termination_reason="user_min"`/`"user_max"`, and `termination_epoch`, exactly
  like impact/escape (addendum §6.6). **No exception is raised on a crossing**; the
  only user-limit error is Chunk 5's construction-time `ValueError`.
- The crossing epoch goes into `termination_epoch` (ISO-8601 UTC), per the §8
  stop-and-report example — there is no user-facing exception message to format.
- `docs/features.md` §1.1 failure-modes table gets the new construction-time
  `ValueError` row (unreasonable `AltitudeLimits`) in the Chunk-11 reconciliation
  (note it here so it isn't forgotten).
- **Tests** (`orekit` fixture): a run that dips below a reasonable `min_altitude_km`
  **stops & reports** with `termination_reason="user_min"` and the right
  `termination_epoch`; a run that stays in-band has no `terminated` key; a user limit
  *tighter* than the system backstops fires before them. (The unreasonable-limit
  `ValueError` is already covered by Chunk 5's pure-Python test.)

**Reuse:** Chunk 5 `AltitudeLimits` + the escape-parity constant; Chunk 6 detector
mechanism + threshold lowering + stop-and-report assembly.

**You provide:** nothing.

**Verify:** `pytest tests/propagation -v` green; the §8 "user-bounded run, reasonable
limits, leaves the band" example **stops & reports** as shown, and the
unreasonable-limits example raises `ValueError` at construction.

*(Mergeable into Chunk 6 if that session has capacity — it reuses the same
detector machinery.)*

---

## Chunk 8 — Min-step re-entry classifier + partial-trajectory recovery - Done

**Goal:** the graceful default for a drag-driven decay — catch the integrator's
min-step failure, classify it, and **stop-and-report** a genuine re-entry while
still failing loudly on a real numeric/config error (addendum §6.6). This is the
fiddliest runtime chunk; the recovery mechanism was **verified feasible** during
the audit.

**Create / edit:**
- `src/propygator/propagation/numerical.py` / `guards.py` — wrap the
  `propagate()` call so a Hipparchus min-step `PropagationError` is **caught and
  classified**:
  - **Re-entry** iff **drag enabled** AND the orbit is **descending** AND its
    **osculating perigee is already irrecoverably below the floor** (perigee radius
    below the table lower edge / ~120–150 km — *not* merely the instantaneous
    altitude, since a healthy low pass is descending half of every orbit; addendum
    §6.6 as tightened). → return a partial `Trajectory`, `terminated=True`,
    `termination_reason="reentry"`.
  - **Otherwise re-raise** as a genuine `PropagationError` (too-tight tolerance,
    bad setup, non-low-altitude stiffness). **Invariant: prefer a false re-raise
    over a false `reentry`** — when in doubt, re-raise.
  - **Partial recovery** (the verified recipe): read
    `generator.getGeneratedEphemeris()` after the exception to recover samples up
    to the failure. Handle the two edges found in the audit: (a) on a config-error
    saturation with **no good steps**, `getGeneratedEphemeris()` *itself* raises —
    wrap it and fall through to the plain re-raise with **no** partial attached;
    (b) a real decay's partial span can dip **below `R⊕`**, so the impact detector
    (Chunk 6) should fire first — order it ahead of relying on this catch. Sample
    only the achieved span (the Chunk-6 clamp).
  - The re-raised error may carry the partial `Trajectory` as an attribute.
- **Tests** (`orekit` fixture): a **drag-driven decay** returns a partial
  `Trajectory` with `termination_reason="reentry"` (use a low-perigee LEO with
  drag on, long enough to decay); a **non-re-entry min-step failure** (e.g. an
  over-tight tolerance on a healthy orbit) **still raises** `PropagationError`; the
  config-error/no-good-steps case raises cleanly with no partial.

**Reuse:** Chunk 6's sampling clamp + partial-trajectory assembly; the existing
`PropagationError` and the `getGeneratedEphemeris()` call already present in
`numerical.py` (~lines 814/823); the `IntegratorConfig.min_step_s` setup.

**You provide:** *optionally* a reference decaying initial state (low perigee,
known to re-enter within a feasible duration) to anchor the test; otherwise Claude
picks one — confirm at review.

**Verify:** `pytest tests/propagation -v` green; the §8 "run that reaches
re-entry" example returns a partial trajectory with the three metadata keys; the
over-tight-tolerance control case still raises.

> ### ✅ Checkpoint B — terminal guards + reporting contract complete - Done
> 1. Impact, escape, user-limit, and re-entry paths all behave per §6.6
>    (stop-and-report for all crossings; the only `raise` is the construction-time
>    `ValueError` for an unreasonable limit), with partial trajectories where specified.
> 2. **Refresh `CLAUDE.md`** "Project state": the guard system is partway in
>    (`propagation/guards.py` exists; `propagate_numerical` gained `limits=` and
>    terminal detectors). Note the addendum is the active build plan.
> 3. `/code-review` + `/simplify` on the diff (the detector + min-step-catch logic
>    is dense and easy to get subtly wrong). Commit + push.

---

## Chunk 9 — Kn-floor + table-edge regime warnings (the warning tier) - Done

**Goal:** the two-tier warning system (addendum §6.2) — edge-aware, warn-once
drag-regime warnings at the **Kn floor**, the **table lower edge**, and the **table
upper edge**, plus the runtime Kn-floor computation (the *third* reconstruction of
the §3.4 method). **Depends on Chunks 2–4** (the validated Kn method + band
numbers) and on Chunk 6's drag path/clamp.

**Create / edit:**
- `src/propygator/propagation/guards.py` —
  - A **runtime Kn-floor scan**: at propagation setup, compute `floor_altitude(L)`
    from the spacecraft's characteristic length `L` (sphere → diameter
    `2√(A/π)`; box → **max edge length**, conservative) and the atmosphere model,
    by scanning for the `Kn = 10` crossing — **re-implementing** the §3.4 method
    (the package may not import the experiment). Evaluate λ at the **conservative
    high-activity** profile (the confirmed default; addendum §6.3/§9). This is a
    **third reconstruction subject to the §5 equivalence check** — cross-check a
    few `floor_altitude(L)` points against the committed Chunk-2 experiment curve.
  - A small **per-species density helper** (this does not exist yet — the drag
    force only queries scalar density). Place it near `_resolve_atmosphere` in
    `numerical.py` or in `core/bodies.py`; it returns the species number densities
    λ needs. One-time at setup, not per-substep.
- `src/propygator/propagation/numerical.py` / the drag-evaluation path —
  edge-aware **warn-once** checks (mirroring the existing `VariableCd` clamp
  warn-once box, `spacecraft.py` `_clamp_warned=[False]` ~line 206 +
  `_warn_clamped_once` ~lines 328–339):
  - **Low edge (Kn floor / table lower edge):** loud — *"WARNING: below the
    free-molecular / drag-table validity floor (~N km for this body); drag modeling
    is invalid here and results may be wildly off."*
  - **High edge (table upper edge):** soft — *"NOTE: above the drag-table altitude
    ceiling; drag is negligible at this altitude, so the effect on results is
    minimal."*
  - The existing **clamp stays** (out-of-grid still clamps per-axis; raising/
    extrapolating still rejected) — the message is upgraded and edge-aware, and the
    Kn floor adds a second trigger. With **drag off**, no drag-regime warning fires.
- **Tests** (`orekit` fixture): a body crossing the Kn floor / lower edge emits the
  loud warning **once**; a high-altitude run with a table emits the soft note once;
  drag-off emits neither; the Kn floor is computed from geometry (a bigger body →
  higher floor); a couple of runtime `floor_altitude(L)` points match the
  experiment curve to the §5 tolerance.

**Reuse:** the `VariableCd` clamp warn-once box; the validated §3.4 method +
`floor_altitude(L)` curve + table-edge numbers from Chunks 2–4; the atmosphere
resolution in `numerical.py` (~lines 275–311).

**You provide:** confirm the **Kn-floor atmosphere profile** (default: conservative
high-activity).

**Verify:** `pytest tests/propagation -v` green; the §8 "decaying orbit dips below
the floor" warning appears once with the right body-specific `~N km`.

---

## Chunk 10 — Unbound-orbit end-to-end verification + docstring limitation note - Done

**Goal:** prove the escape backstop makes already-supported unbound orbits *safe*,
and add the user-facing limitation note (addendum §6.5, §6.7).

**Create / edit:**
- **Verification, not new validation** (addendum §6.5 — the eccentricity gates are
  *retained*): confirm a **hyperbolic Cartesian initial `State`** round-trips
  end-to-end through `propagate_numerical` (Orekit numerical propagator + force
  models — the `CartesianOrbit` path has no bound check) and that the **escape
  detector catches the climb-out**, terminating with
  `termination_reason="escape"`. Confirm the detector resolves the single crossing
  cleanly at ~51× the LEO radius (check `maxCheck`/threshold scaling).
- `src/propygator/propagation/numerical.py` docstring — add the §6.7 limitation
  bullet to the "Spacecraft-model limitations (v1)" block:
  *"Drag modeling is valid only within an altitude band (free-molecular flow above
  a body-size-dependent floor of ~N km, up to the Cd-table ceiling). Below the
  floor the run continues with a warning but drag is unreliable; a decaying orbit
  ends gracefully at re-entry, impact and escape terminate the run, and user limits
  may tighten this."*
- **Tests** (`orekit` fixture): the §8 "hyperbolic / escape trajectory" example
  propagates and terminates at escape with a partial trajectory.

**Reuse:** Chunk 6 escape detector; the existing hyperbolic handling in
`core/elements.py` (~lines 59–104) and the `CartesianOrbit` propagation path.

**You provide:** *optionally* a hyperbolic reference state; otherwise Claude
constructs one.

**Verify:** `pytest tests/propagation -v` green; a hyperbolic run terminates at
escape rather than running to absurd distances.

*(Small — can ride with Chunk 9 or Chunk 11.)*

---

## Chunk 11 — Wrap-up: full sweep, review, docs reconciliation, PR - Done

**Goal:** land the addendum — clean diff, the supersession map folded back into the
governing docs, and the PR.

**Create / edit / run:**
- Full local CI parity: `pytest` and `pre-commit run --all-files` both green from
  repo root.
- `/code-review` + `/simplify` final pass across the whole addendum diff.
- **Reconcile the docs (addendum §1 map + §10 item 7).** Fold the superseded/
  extended sections back into the source-of-truth docs and register the new names:
  - `features.md` §1.1 — supersede "Escape and re-entry"; extend the signature
    (`limits=`), the failure-modes table (construction-time `ValueError` for an
    unreasonable `AltitudeLimits`), the metadata block (the three keys), the
    drag-coefficient-modeling §5 invariant, and the model-limitations docstring line.
  - `architecture.md` — close the §13 "Escape / re-entry guards" deferral; extend
    §13 "Coefficient of drag modeling" (validity domain); extend §6
    `TrajectoryMetadata` (the three keys) and register `AltitudeLimits` in the §6
    data model + §7 re-export list. (No new exception type — an unreasonable
    `AltitudeLimits` raises the builtin `ValueError`.)
  - `CHANGELOG.md` `[Unreleased]` — the guard system, `AltitudeLimits`, the
    metadata keys, the regenerated table.
  - **Refresh `CLAUDE.md`** "Project state": the addendum is built; remove its
    "not yet built" framing; note the regenerated table.
- **Open the PR** (Git section): `gh pr create` against your chosen base, confirm
  CI green, then `gh pr merge --squash --delete-branch` — **your call** on timing
  and on whether this merges with or after the deferred Feature 1.1 PR.

**You provide:** confirm `gh` authenticated; decide the merge ordering vs the 1.1
PR; final go-ahead to merge (an outward action — Claude won't push/merge without
it).

**Verify:** `pytest -v` full suite green; `pre-commit run --all-files` clean;
`import propygator as pgr` exposes `AltitudeLimits` and stays JVM-free; the addendum
§1 map is fully carried into `features.md`/`architecture.md`.

> ### ✅ Final checkpoint — addendum done - Done
> CLAUDE.md, CHANGELOG, features.md, and architecture.md all reflect the validity
> domain + guard system as built; the supersession map is discharged.

---

## End-state verification (addendum complete → guards live) - Done

Mirrors addendum §10 "Definition of done." From repo root, `conda activate
propygator`, on the merged branch:
1. **Experiment evidence** (§10.1–2): the expanded experiment + Kn-floor curve are
   committed with figures + stdout, measured against the §3.1 thresholds; the
   experiment↔generator cross-validation (§5) passed and is recorded.
2. **Table** (§10.3): `data/sphere_cd_default.npz` covers exactly the validated
   band, with both bands + a confidence label in `metadata_json`.
3. **Guards** (§10.4): warnings (two-tier, edge-tailored), terminal impact/escape
   detectors (via `@JImplements`, all default methods overridden, sampling clamped
   to the achieved span), the classified min-step re-entry catch with partial
   recovery (incl. the empty-ephemeris and sub-`R⊕` edges), `AltitudeLimits` +
   `limits=`, the reporting contract, the metadata keys (written only when
   terminated), and the docstring note are all in.
4. **Unbound** (§10.5): a hyperbolic state round-trips and terminates at escape.
5. **Tests** (§10.6): warning emission at each edge; clean stop-and-report at
   impact/escape; the re-entry catch returns a partial `Trajectory` on a
   drag-driven decay while a non-re-entry min-step failure still raises; a reasonable
   user-limit crossing stops & reports (`user_min`/`user_max`) while an unreasonable
   `AltitudeLimits` raises `ValueError` at construction; hyperbolic propagation
   terminates at escape; the Kn floor is computed from geometry. JVM-touching tests
   use the `orekit` fixture.
6. **Docs** (§10.7): the §1 supersession map is carried into
   `features.md`/`architecture.md`; CHANGELOG + CLAUDE.md updated.
7. `python -c "import propygator, jpype; print(jpype.isJVMStarted())"` → `False`.

## Notes / deferred (not this addendum)

- **Tier B `IncidenceVariableCd`** runtime and **`NadirPointing(velocity_reference=
  "ecef")`** remain deferred validated skeletons (architecture §13) — untouched here
  (a box with `IncidenceVariableCd` + drag still raises `NotImplementedError`).
- **Per-facet free-molecular Sentman drag** remains deferred (addendum §0).
- **Modeling** atmospheric entry (aerothermodynamics, breakup, footprint) and
  deep-space/cislunar dynamics is out of scope — propygator *guards* these
  boundaries, it does not model beyond them (addendum §0). The escape backstop
  intentionally terminates Earth-bound trajectories with apogee beyond lunar parity.
- **UT1** remains deferred (needs EOP data; architecture/CLAUDE.md).
