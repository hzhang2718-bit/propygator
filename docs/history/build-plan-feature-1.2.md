# Build plan: Feature 1.2 — TLE fitter (`fit_tle`)

> **Status: BUILD PLAN (started).** Derived from `features.md` **§1.2** (drafted
> 2026-07-07), which is the **binding contract** for this work — every signature row,
> field-policy rule, and failure mode below traces to it, cited inline as "(contract:
> <heading>)". Where this plan and the contract disagree, the **contract wins**; fix
> the plan. Status headers are the maintainer's — trust the git log for true status.
> Built after 1.5 (architecture §12); treated as a plus, not a blocker — **this plan
> has a real STOP path at Checkpoint A.**

## Context

`fit_tle(reference, *, fitting_span, force_models, spacecraft, initial_guess,
max_iterations, fit_bstar, norad_id, name, progress) -> TLE` — the repo's first
*estimation* feature: an iterative batch-least-squares fit of SGP4 mean elements
(+ optionally B\*) against a reference trajectory, riding Orekit's
`TLEPropagatorBuilder` + `BatchLSEstimator`. The faithful sibling of the shipped
`TLE.from_state_unfitted`, which becomes the default seed (contract: intro; Fit
mechanism).

**End state:** the architecture §8 paths run end-to-end — (a) numerical trajectory
→ shareable TLE, (b) user-assembled `Trajectory` → TLE, (c) SGP4 self-refit —
returning a physically complete TLE under the "identity inherits, physics
fitted-or-zeroed" field policy; **`fit_tle_detailed` returning the `FitResult`
diagnostics beside it** (added at Checkpoint A — see the Chunk 0 outcome);
non-convergence raises the new `TLEFitError`; per-iteration `iter N | rms …`
progress lines.

**Risk profile: moderate, front-loaded.** The machinery exists in the pinned Orekit
13.1.x and every JPype pattern needed is already proven in this repo — but
convergence robustness across orbit regimes is a numerical behavior no amount of
plumbing guarantees. Hence Chunk 0: the whole recipe runs as a throwaway probe
**before any propygator surface is written**, and Checkpoint A is a genuine
GO/STOP.

### Source-of-truth docs (do not silently diverge)

- `docs/features.md` **§1.2** — the binding contract (Public signature,
  Reference-input paths, Fit mechanism, Fitted-TLE field policy, Progress
  reporting, Failure modes, Validated domain & de-risking, Testing, Resolved
  decisions).
- `docs/architecture.md` §8 (the matching signature + the three worked user paths),
  §13 (the extended `fit_tle` resolved bullet; the former `FitResult` deferral —
  exercised at Checkpoint A, now in scope).
- `docs/history/general-upgrades-1.md` Part B — the `progress` commitment and the
  indeterminate-mode framing 1.2 now pins (contract: Progress reporting).
- `CLAUDE.md` "Java↔Python boundary notes" — the `@JImplements` default-method trap
  and the test-inside-the-real-call-path discipline (memory: `BatchLSObserver` is
  the one new proxy).

### Decisions already locked (do not relitigate)

- **Mechanism:** `TLEPropagatorBuilder` + `BatchLSEstimator` (Levenberg–Marquardt)
  over subsampled **PV** measurements; `BatchLSObserver` proxy for per-iteration
  reporting; SDP4 branch automatic from the fitted mean motion (contract: Fit
  mechanism). Orekit literal spellings verified against the 13.1.x javadoc at
  implementation — a wrong name is a compile-time error (contract: status header).
- **Fitted epoch = reference start** (first sample in the fitting span); all
  measurements forward of epoch.
- **Seed (Chunk-0-resolved, 2026-07-10):** the **fixed-point refinement** —
  `FixedPointTleGenerationAlgorithm().generate(first_sample, template)` with
  `template = initial_guess` else `TLE.from_state_unfitted(first_sample)` —
  anchored at the reference start. Same optimum as the raw template, roughly half
  the iterations (probe: 14 vs 22 / 18 vs 22 / 2 vs 24); raw template is the
  fallback if generation fails. Mechanics in the Chunk 0 outcome below (contract:
  Fit mechanism step 1, amended).
- **Field policy:** identity inherits (kwargs win), physics fitted-or-zeroed;
  ṅ/n̈ always zeroed, never inherited (contract: Fitted-TLE field policy).
- **`TLEFitError`** — new `PropygatorError` subclass, a *sibling* of
  `PropagationError` (fitting is not propagation); message carries iteration count
  + last RMS; **no partial TLE** (contract: Failure modes).
- **Progress:** indeterminate mode; the built-in reporter prints per-iteration
  `iter N | rms …` lines + honest final lines; a **callable receives
  `min(iteration / max_iterations, 1.0)`** — the budget fraction (contract:
  Progress reporting). The reporter's indeterminate `step()` mode shipped in
  v0.5.0, already built + tested — 1.2 only *drives* it.
- **State path** uses `IntegratorConfig.high_precision()` (the preset §1.1 designed
  for this), internal `progress=False`, and requires EME2000; **Trajectory path**
  accepts any frame (a `TLE` carries no frame — §10) and clips `fitting_span` to
  the leading portion (contract: Reference-input paths).
- **Validated domain = LEO** (+ one deep-space SDP4 case); elsewhere `TLEFitError`
  is an honest outcome (contract: Validated domain).
- **`FitResult` / `fit_tle_detailed` — IN SCOPE (Checkpoint A item 3, resolved
  2026-07-10).** The probe confirmed per-measurement residuals are free; the
  maintainer exercised the architecture §13 revisit and the contract was amended
  in step (features §1.2 "`FitResult` and `fit_tle_detailed`").
  `fit_tle_detailed` is the engine (identical parameter list) returning the
  frozen `FitResult(tle, iterations, evaluations, rms_m, residuals_m,
  measurement_epochs)`; `fit_tle` is the thin `.tle` wrapper. No `converged`
  flag — non-convergence raises, so the flag would be a constant `True`. Both
  top-level exports.
- **1.2 ships as its own tagged release** after 1.5 (version number the
  maintainer's call).

### Decisions to confirm (defaults chosen; "You provide" flags them)

- **Probe scenarios (Chunk 0).** Defaults: (i) self-fit — a fixed ISS TLE,
  `propagate_tle` over 2 d at 60 s; (ii) numerical — the same orbit's first state
  through `propagate_numerical` `leo_default` / `high_precision`, 2 d. Optional
  third leg: a Molniya-class TLE (the Vallado 08195 case) for an early SDP4 read.
- **Branch name.** Default `feature/tle-fitter` (maintainer creates off `main`).
- **The GO/STOP call at Checkpoint A** is the maintainer's.

### Architecture invariants to honor (CLAUDE.md / architecture §4, §10)

Orekit/Java types stay internal (`fit_tle` takes/returns only propygator types);
`jpype`/`org.orekit.*` imports **lazily inside functions**; pre-flight validation
that needs no JVM stays JVM-free; SI internally; `logging`, never `print` (the
reporter is the sanctioned exception); JVM-touching tests acquire the **`orekit`
fixture**; new `src/` modules pass mypy; `import propygator` stays JVM-free.

---

## How to use this plan

- **6 chunks (0–5)**, each sized for one Claude Code session:
  - **Chunk 0 is the evidence gate** — a throwaway probe in the **conda env**
    (every piece is shipped Orekit + propygator; no experiment venv). Its output is
    committed *evidence* (ASCII-only captured output + README), not pytest tests.
  - **Chunks 1–4 are the shipped code**; **Chunk 5 is wrap-up.**
- Each chunk lists **Goal / Create-Edit / Reuse / You provide / You run / Verify**.
- **One STOP gate:** Checkpoint A (after Chunk 0). If the probe cannot converge the
  self-fit, or the estimator route is unworkable through JPype **and** the named
  NumPy fallback is judged not worth owning → **STOP**, record the evidence, add an
  Outcome note to `features.md` §1.2 (the blitting precedent), do not build
  Chunks 1–4.
- **`/code-review` + `/simplify` checkpoints:** after Chunk 2 (the estimator core)
  and in the Chunk 5 sweep.
- **Commits, CHANGELOG entries, chunk-header "done" marks, the merge, and the
  release are the maintainer's.** Claude writes code and runs read-only/test
  commands; the maintainer runs the probe, commits, and pushes.
- **Mergeable chunks:** 1 + 2 can merge into one session if the probe went
  smoothly; 3 + 4 likewise.

---

## Git (read once)

The maintainer creates **`feature/tle-fitter`** off `main` (after 1.5's release);
the probe evidence and the feature ride on it. Per-chunk rhythm: maintainer commits
+ pushes after each verified chunk. Release prep (version bump → **reinstall
editable** → CHANGELOG → squash-merge → annotated tag) follows
`docs/release-process.md` at the end of Chunk 5 and is the maintainer's.

---

## Chunk 0 — Feasibility probe → GO/STOP Checkpoint A - Done

**Goal:** run the **entire fit recipe** against the shipped stack before any
`src/` code exists, so the feature can be dropped cheaply and the internal knobs
(seed, `positionScale`, measurement count, convergence thresholds) arrive at
Chunk 2 pre-tuned (contract: Validated domain & de-risking).

**Create / edit** (all in a new `experiments/tle-fitting/`; reference-only, outside
`testpaths`, excluded from CI/lint; **ASCII-only prints** — stdout is captured under
cp1252):
- A probe driver (e.g. `fit_probe.py`) that, for each scenario:
  1. Builds the reference trajectory (shipped verbs only).
  2. Constructs the template/seed TLE — **both** seeds: `TLE.from_state_unfitted`
     and Orekit's `FixedPointTleGenerationAlgorithm` — and records iterations-to-
     converge for each.
  3. Wires `TLEPropagatorBuilder` + `BatchLSEstimator` + LM over ~300 evenly
     subsampled PV measurements; registers a `BatchLSObserver` `@JImplements` proxy
     that prints `iter N | rms` (this **is** the de-risk of the one new proxy — the
     default-method trap only surfaces in the real call path).
  4. Toggles the `BSTAR` driver on/off and records both fits.
  5. Reports: converged?, iterations, final RMS (m), fitted-vs-source element
     deltas (self-fit leg), and a propagate-back residual over the span.
- Scenarios: **(i) the self-fit** (known-exact answer — must recover the source TLE
  nearly exactly), **(ii) the numerical fit** (records the honest km-level RMS the
  docs will quote), optional **(iii) Molniya/SDP4**.
- A `positionScale` / convergence-threshold sensitivity sweep (a few values each —
  cheap, seconds per fit).
- Committed `results.txt` + folder `README.md` with provenance (the experiments
  pattern).

**Reuse:** `propagate_tle` / `propagate_numerical` / `TLE.from_state_unfitted`
(all shipped); `experiments/ecef-attitude-benefit/` as the probe-folder template;
the `FunctionalDetector`-era lazy-import idioms for the Orekit estimation
namespaces.

**You provide:** scenario confirmation; **the GO/STOP call at Checkpoint A.**

**You run:** `conda run -n propygator python experiments/tle-fitting/fit_probe.py`;
commit the evidence.

**Verify:** the self-fit recovers the source TLE (tens-of-meters RMS, elements
close); the numerical-fit RMS is recorded; the observer proxy fired every
iteration; both seeds converged (or the better one identified); B\* toggling
behaves. **Also record:** whether per-measurement residuals fall out of the
estimator essentially free — the flagged input to the maintainer's `FitResult`
revisit (contract: Still open).

> ### ⛔ GO/STOP Checkpoint A
> 1. **Self-fit fails to converge, or the estimator route is JPype-unworkable** →
>    either take the named pure-NumPy differential-correction fallback (7 params,
>    finite-difference Jacobian, `numpy.linalg.lstsq` — contract: Validated domain)
>    **if the maintainer judges it worth owning**, or **STOP**: record the
>    evidence, add the Outcome note to `features.md` §1.2, do not build Chunks 1–4.
> 2. **Self-fit converges** → **GO**; carry the tuned constants + the chosen seed
>    into Chunk 2.
> 3. Decide the `FitResult` revisit (build `fit_tle_detailed` in this branch vs
>    leave deferred) on the residual-availability finding.
> 4. Commit + push the evidence either way.

### Chunk 0 outcome — **GO** (probe run 2026-07-09, maintainer call 2026-07-10)

Evidence committed at `experiments/tle-fitting/` (driver + `results.txt` +
README). **All 19 fits in the matrix converged — the STOP path and the NumPy
fallback never came into play.** The numbers:

- **Self-fit (i): exact recovery.** With B\* estimated, the fitted TLE matches
  the source ISS TLE to the printed digit — propagate-back residual **0 m** over
  the full 2881-sample grid, every element delta 0, B\* 1.66e-4 recovered
  exactly. (The contract's "tens-of-meters" gate was conservative by orders of
  magnitude; Chunk 2 pins a tighter test bound.) `fit_bstar=False` degrades
  honestly: ~1.2 km RMS / 2.6 km max over 2 d, B\* held bit-exact.
- **Numerical fit (ii): ~495 m RMS / ~1119 m max over 2 d** (B\* on) — the
  documented lossiness number. B\* on beats off (541 m), and the fitted B\*
  (3.0e-5) is a fit residual, not the catalog 1.66e-4 — as the contract warns.
- **Molniya/SDP4 (iii): exact recovery too** (0 m propagate-back, deltas 0, B\*
  exact) — no deep-space fragility in the self-consistency case.
- **Seed comparison → fixed-point refinement chosen.** Same optimum from both
  seeds (identical fitted lines), but the refinement starts at ~7 km residual vs
  ~1100 km (the osculating-in-mean-slots offset) and converges in 14 vs 22 (i),
  18 vs 22 (ii), 2 vs 24 (iii) iterations. **Mechanics:**
  `FixedPointTleGenerationAlgorithm().generate(state, template)` iterates the
  mean elements until the TLE's own SGP4 osculating output reproduces the
  target state — a local osculating→mean inversion at the start epoch. It needs
  an **orbit-defined** `SpacecraftState`: wrap the first sample as
  `CartesianOrbit(PVCoordinates, TEME, epoch, TLEConstants.MU)` —
  `State.to_orekit()`'s `AbsolutePVCoordinates` form defines no orbit, and
  `TLEConstants.MU` (WGS-72 GM, SI) is the right mu (**`Constants` has no
  `WGS72_EARTH_MU` in 13.1.x** — the probe's first run failed on that name).
- **Sweep: flat.** positionScale 1–1000 m and threshold 1e-2–1e-4 all reach the
  same TLE in 21–22 iterations. **Constants carried into Chunk 2:** ~300 PV
  measurements, σ_pos 1 m / σ_vel 1 mm/s, weight 1, `positionScale` 1 m,
  parameters convergence threshold 1e-3, `PositionAngleType.MEAN`,
  `maxIterations = maxEvaluations = 100`.
- **The one new proxy is risk-free:** `BatchLSObserver` has a single abstract
  method and **no default methods** (verified by reflection *and* live in 19
  real fits — the default-method trap does not apply).
- **Observer fires per *evaluation*, not per iteration** — LM may re-evaluate
  within an iteration (seen live: `iter 4 | eval 5..9` on the Molniya B\*-off
  leg). Chunk 3's reporter dedupes on the iteration counter so exactly one
  `iter N | rms` line prints per iteration (contract: Progress reporting,
  amended).
- **Builder facts pinned:** propagation frame is TEME (PV measurements must be
  supplied in TEME — the Trajectory path converts internally, sanctioned by
  §10); the six orbital drivers (`Px…Vz`) default **selected**, the `BSTAR`
  propagation driver defaults **unselected** → select iff `fit_bstar`.
- **Residual availability → `FitResult` GO (item 3).** The observer receives an
  `EstimationsProvider` (observed + estimated per measurement) + the LS
  `Evaluation` (`getRMS`/`getResiduals`/`getCost`) every iteration — diagnostics
  are free. Maintainer exercised the revisit; contract amended in step
  (features §1.2 "`FitResult` and `fit_tle_detailed`").
- **Deliberately unexercised:** no fit failed, so the `TLEFitError` path rests
  on Chunk 2's forced-failure test (`max_iterations=1` on the raw unrefined
  seed), not on probe evidence.

---

## Chunk 1 — `TLEFitError` + `FitResult` + the verb skeletons: pre-flight, reference normalization, seed & identity - Done

**Goal:** everything *around* the estimator — the exception, the `FitResult`
value type, the validation table, both reference paths normalized to "a
trajectory + a template TLE", ready for Chunk 2 to consume (contract: Public
signature; `FitResult` and `fit_tle_detailed`; Reference-input paths; Failure
modes; Fitted-TLE field policy).

**Create / edit:**
- `src/propygator/core/exceptions.py` — `TLEFitError(PropygatorError)` (sibling of
  `PropagationError`; docstring: non-convergence / diverged fit, carries iteration
  count + last RMS in the message, never a raw Java trace). Top-level re-export.
- `src/propygator/tle/fitter.py` — `fit_tle_detailed` (the engine) + `fit_tle`
  (the thin `.tle` wrapper), both with the full contract signature:
  - **`FitResult`** — frozen dataclass `(tle, iterations, evaluations, rms_m,
    residuals_m, measurement_epochs)`; JVM-free constructible + validating
    (shape/finiteness in `__post_init__`); `residuals_m` gets the array-backed
    value-type treatment (defensive copy, read-only, value-based
    `__eq__`/`__hash__` — the `State`/`Orientation` pattern); no `converged`
    flag (non-convergence raises).
  - **Pre-flight** (`ValueError` rows): `fitting_span <= 0`, `max_iterations < 1`,
    `Trajectory` with < 2 samples in span, non-inertial `State`, unbound first
    sample (e ≥ 1 / a ≤ 0 via `to_keplerian` — surfaced cleanly); the
    warn-and-ignore for `force_models`/`spacecraft` with a `Trajectory`; the
    < 1-revolution warn-once.
  - **Reference normalization:** State path → internal `propagate_numerical`
    (`force_models` default `leo_default()`, `spacecraft` default
    `SpacecraftConfig()`, default `LofAligned`, `IntegratorConfig.high_precision()`,
    ~300-sample internal grid, `progress=False`); Trajectory path → leading-portion
    clip, any input frame (→ TEME internally; the builder frame, Chunk 0).
  - **Seed + identity:** the fixed-point refinement
    (`FixedPointTleGenerationAlgorithm().generate(first_sample, template)`,
    `template = initial_guess` else `from_state_unfitted`; the orbit-defined
    `CartesianOrbit`/`TLEConstants.MU` wrapping and raw-template fallback per the
    Chunk 0 outcome); identity resolution (kwarg → `initial_guess` →
    placeholder) staged for the final assembly.
- **Tests** (`tests/tle/test_fitter.py`): the full `ValueError` table (JVM-free
  rows fixture-free; the bound-orbit row under the `orekit` fixture); `FitResult`
  construction/validation rows (JVM-free); the Trajectory-path warning; span
  clipping; internal-propagation failure passthrough
  (`NumericalPropagationError` unchanged).

**Reuse:** `propagate_numerical` + its presets; `TLE.from_state_unfitted`;
`Epoch.seconds_since`; the §1.3 warn-once idiom; the `State`/`Orientation`
read-only-array pattern for `FitResult.residuals_m`.

**You provide:** nothing.

**You run:** the git rhythm.

**Verify:** `conda run -n propygator pytest tests/tle -v` green; the pre-flight
rows all raise before any Orekit estimation import; mypy clean.

---

## Chunk 2 — The estimator core (JVM-touching; the fit itself) - Done

**Goal:** the batch LS wired end-to-end inside `fit_tle_detailed`, with the
Chunk-0-tuned constants — measurements, builder, optimizer, B\* toggle,
convergence → TLE + `FitResult` assembly, non-convergence → `TLEFitError`
(contract: Fit mechanism; `FitResult` and `fit_tle_detailed`; Fitted-TLE field
policy; Failure modes).

**Create / edit:**
- `src/propygator/tle/fitter.py`:
  - PV measurement construction from the normalized reference (even subsampling to
    the internal cap; sigma/weight constants from Chunk 0: σ_pos 1 m, σ_vel
    1 mm/s, weight 1, `positionScale` 1 m, threshold 1e-3,
    `PositionAngleType.MEAN`).
  - `TLEPropagatorBuilder(template, PositionAngleType…, positionScale,
    generation_algorithm)` + `BatchLSEstimator(LevenbergMarquardtOptimizer(), …)`;
    `max_iterations` bounds iterations and evaluations; the `BSTAR` driver selected
    iff `fit_bstar` (defaults unselected — Chunk 0).
  - Convergence → assemble the returned `TLE` under the field policy (identity
    inherits — kwargs win; ṅ/n̈ zeroed; element-set/rev-number inherited verbatim;
    checksums via the Orekit formatter + `from_strings` re-validation — the
    `from_state_unfitted` pattern) **and the `FitResult` around it** (iterations/
    evaluations from the estimator; `rms_m` + `residuals_m` from the final
    observer callback's `EstimationsProvider`; `measurement_epochs` from the
    subsampled grid). `fit_tle` returns `.tle`.
  - Non-convergence / diverged LS (the Hipparchus too-many-iterations /
    too-many-evaluations exceptions, caught at the boundary) → `TLEFitError` with
    iteration count + last RMS; no raw Java trace; no partial `FitResult`.
- **Tests** (`tests/tle/test_fitter.py`, `orekit` fixture):
  - **The self-fit gate (path (c)):** fit from a `propagate_tle` trajectory of a
    known TLE; assert sub-meter propagate-back RMS + element recovery (Chunk 0
    measured *exact* recovery — pin a tight-but-safe bound, e.g. ≤ 1 m RMS).
  - The field-policy table: with/without `initial_guess`, kwarg precedence,
    ṅ/n̈ = 0, placeholder set.
  - `TLEFitError` via `max_iterations=1` on a deliberately poor seed (the raw
    unrefined template — the one failure path Chunk 0 left unexercised).
  - `fit_bstar=False` holds the seed's B\*.
  - **`fit_tle` / `fit_tle_detailed` agreement** + `FitResult` field invariants
    (residuals shape/read-only, `rms_m` consistent with `residuals_m`, epochs
    aligned) — contract: Testing.

**Reuse:** the Chunk-0 probe code (lifted, cleaned, and made lazy-importing —
the probe *is* the first draft of this chunk); `TLE.from_strings` re-validation.

**You provide:** nothing.

**You run:** the git rhythm.

**Verify:** the self-fit gate green; `import propygator` still JVM-free (all
estimation imports in-body).

> ### ✅ Checkpoint B — the fit works
> 1. Path (c) converges and recovers its source; failure raises `TLEFitError`.
> 2. `/code-review` + `/simplify` on the Chunks 1–2 diff.
> 3. Commit + push.

---

## Chunk 3 — Progress wiring (indeterminate mode) - Done

**Goal:** the reporter driven per the contract on **every** exit path — the
`BatchLSObserver` proxy feeding `iter N | rms …` lines, the State-path phase line,
the honest final line, the callable budget fraction (contract: Progress
reporting).

**Create / edit:**
- `src/propygator/tle/fitter.py`: the `BatchLSObserver` `@JImplements` proxy →
  `reporter` per iteration — **deduped on the iteration counter**, since Orekit
  fires the observer per *evaluation* and LM may re-evaluate within an iteration
  (Chunk 0 outcome; contract: Progress reporting); `start` line before JVM boot;
  the State-path
  `building reference trajectory | NN h` phase line; one wide `try/finally` from
  `reporter.start()` through TLE assembly so `done | converged in N iterations |
  rms …` / `failed at iter N | not converged | last rms …` always prints (the §1.1
  pattern); the callable form receives `min(iteration / max_iterations, 1.0)` and
  the library prints nothing.
- `src/propygator/core/progress.py` — **only if needed:** if the shipped
  indeterminate `step()` lacks a per-step detail string for the `rms` payload,
  extend it additively (headless unit tests alongside; the reporter has three
  consumers — do not reshape existing behavior).
- **Tests:** a callable capture (monotonic budget fractions, final 1.0 only on the
  budget-exhausted path); stderr-line shape via the existing reporter test harness
  (headless for the reporter, `orekit` fixture for the in-fit proxy path); the
  `progress=False` silence.

**Reuse:** `core/progress.py`'s indeterminate mode (shipped + tested in v0.5.0);
the `OrekitFixedStepHandler`-proxy test patterns from the 1.1 progress build.

**You provide:** an interactive-terminal eyeball of the iteration lines (the one
path no automated context can see — the ux-improvements Checkpoint-A precedent).

**You run:** one interactive `fit_tle` in a real terminal; the git rhythm.

**Verify:** every exit path ends with exactly one honest final line; reporter unit
suite still green (no reshaping).

---

## Chunk 4 — Validation battery: the honest-numbers tests - Done

**Goal:** the contract's remaining test rows — the quantitative claims the docs
will make, pinned (contract: Testing / reference cases; Validated domain).

**Create / edit** (`tests/tle/test_fitter.py`, `orekit` fixture):
- **Numerical fit (path (a)):** 2-day LEO `leo_default` reference → assert
  convergence and a bounded, documented sub-km RMS (the lossiness caveat made
  quantitative; Chunk 0 measured ~495 m RMS / ~1119 m max — pin with slack,
  e.g. ≤ 1 km RMS).
- **B\* recovery:** a drag-dominated LEO case — `fit_bstar=True` recovers a
  plausible B\* and beats `fit_bstar=False` on propagate-back residual
  (Chunk 0: 495 m vs 541 m on the ISS case).
- **Deep-space branch:** the Vallado 08195-class case through a fit; the fitted
  TLE selects SDP4 (mean motion below the 225-min cutoff) and converges
  (Chunk 0 measured exact recovery — no deep-space fragility to pin).
- **Path (b) smoke:** a `Trajectory.from_arrays`-built reference (the observational
  path) fits.
- Top-level export (`fit_tle`, `fit_tle_detailed`, `FitResult`, `TLEFitError`) +
  `tests/test_public_surface.py` update.

**Reuse:** the Vallado fixtures already in the suite; `Trajectory.from_arrays`.

**You provide:** nothing.

**You run:** the git rhythm.

**Verify:** `conda run -n propygator pytest tests/tle -v` green; the documented
RMS numbers match what the docstring/README will claim.

---

## Chunk 5 — Wrap-up: docs, notebook, sweep, release - Done

**Goal:** land the feature — docs reconciled, the walkthrough notebook, clean
sweep, squash-merge + tag (the maintainer's release). **The final v1 target verb
ships.**

**Create / edit / run:**
- Full local CI parity: `conda run -n propygator pytest` and
  `conda run -n propygator pre-commit run --all-files` green from repo root.
- `/code-review` + `/simplify` final pass across the whole diff.
- **Docs reconciliation:**
  - `README.md` — TLE fitting to ✅ with a worked example (fit a numerical
    trajectory, quote the honest RMS); the feature list is now all-✅.
  - `features.md` §1.2 — an **Outcome** note (as-built constants, the seed chosen,
    the achieved RMS numbers, the `FitResult` revisit decision); status header
    stays the maintainer's.
  - `architecture.md` §10 — `fit_tle` joins the JVM-startup list; §12 build-order
    status updated.
  - `notebooks/07_tle_fitting.ipynb` — propagate → fit → share → propagate the
    fitted TLE back and plot the divergence (the lossiness caveat made visible);
    a `fit_tle_detailed` cell plotting `residuals_m` over `measurement_epochs`.
  - **You** update `CHANGELOG.md` and `CLAUDE.md` "Project state".
- **Release** (maintainer, per `docs/release-process.md`): version bump →
  **reinstall editable** → squash-merge → annotated tag → push → `git branch -D`.
  This plan then retires to `docs/history/`.

**You provide:** CHANGELOG; the version number; the merge/tag go-ahead.

**Verify:** full `pytest` + `pre-commit` green; the README example runs;
`conda run -n propygator python -c "import propygator, jpype; print(jpype.isJVMStarted())"`
→ `False`.

---

## End-state verification (shipped → tagged on `main`)

1. **Evidence:** the Chunk-0 probe (self-fit recovery, numerical-fit RMS, seed
   comparison, sensitivity sweep) committed; the GO recorded at Checkpoint A.
2. **Paths:** (a)/(b)/(c) all fit end-to-end; the State path uses
   `high_precision` + the user's `spacecraft`; the Trajectory path accepts any
   frame and warns-and-ignores physics configs.
3. **Output:** the field policy holds (identity inherits, physics
   fitted-or-zeroed); checksums valid; `from_strings` re-validation passes;
   `fit_tle_detailed` returns the full `FitResult` and
   `fit_tle(...) == fit_tle_detailed(...).tle`.
4. **Failure honesty:** non-convergence → `TLEFitError` with iterations + last
   RMS; every `ValueError` row pre-flight; no raw Java traces.
5. **Progress:** `iter N | rms …` lines, honest final line on every exit path,
   callable budget fraction — eyeballed live at Chunk 3.
6. **Invariants:** `import propygator` JVM-free; `tests/core` no-JVM; mypy /
   pre-commit green.
7. **Docs:** README all-✅, features §1.2 Outcome, notebook 07, CHANGELOG,
   CLAUDE.md; this plan retired to `docs/history/`.

## Notes / deferred (not this plan)

- ~~**`FitResult` / `fit_tle_detailed`** — deferred~~ **pulled IN SCOPE at
  Checkpoint A (2026-07-10)** on the residuals-are-free finding — see "Decisions
  already locked" and the Chunk 0 outcome; contract amended in step.
- **Epoch at span midpoint** as an alternative anchor — deferred; start-anchored
  per the contract.
- **The pure-NumPy differential-correction fallback** — named, dormant; Checkpoint
  A did **not** force it (all 19 probe fits converged). Stays retired unless a
  later regime surprises.
- **Forwarding determinate progress through the State-path internal propagation**
  (today: suppressed + a phase line) — polish, deferred.
- **Numerical orbit determination** (estimating the propagator's own Cd, etc.) —
  out of scope for v1 (architecture §13's drag-modeling note).
