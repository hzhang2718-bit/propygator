# Build plan: Feature 1.2 — TLE fitter (`fit_tle`)

> **Status: BUILD PLAN (not started).** Derived from `features.md` **§1.2** (drafted
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
fitted-or-zeroed" field policy; non-convergence raises the new `TLEFitError`;
per-iteration `iter N | rms …` progress lines.

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
  §13 (the extended `fit_tle` resolved bullet; the `FitResult` deferral).
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
- **Seed:** `initial_guess`, else `TLE.from_state_unfitted` on the first sample;
  Orekit's `FixedPointTleGenerationAlgorithm` is probed in Chunk 0 as an *internal*
  alternative, not a contract change.
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
- **`FitResult` stays deferred** (architecture §13) — but see the Chunk-0 probe
  item on residual availability, which can trigger a maintainer revisit *within
  this branch* (contract: Still open; the drafting-session flag).
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

## Chunk 0 — Feasibility probe → GO/STOP Checkpoint A

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

---

## Chunk 1 — `TLEFitError` + `fit_tle` skeleton: pre-flight, reference normalization, seed & identity

**Goal:** everything *around* the estimator — the exception, the validation table,
both reference paths normalized to "a trajectory + a template TLE", ready for
Chunk 2 to consume (contract: Public signature; Reference-input paths; Failure
modes; Fitted-TLE field policy).

**Create / edit:**
- `src/propygator/core/exceptions.py` — `TLEFitError(PropygatorError)` (sibling of
  `PropagationError`; docstring: non-convergence / diverged fit, carries iteration
  count + last RMS in the message, never a raw Java trace). Top-level re-export.
- `src/propygator/tle/fitter.py` — `fit_tle` with the full contract signature:
  - **Pre-flight** (`ValueError` rows): `fitting_span <= 0`, `max_iterations < 1`,
    `Trajectory` with < 2 samples in span, non-inertial `State`, unbound first
    sample (e ≥ 1 / a ≤ 0 via `to_keplerian` — surfaced cleanly); the
    warn-and-ignore for `force_models`/`spacecraft` with a `Trajectory`; the
    < 1-revolution warn-once.
  - **Reference normalization:** State path → internal `propagate_numerical`
    (`force_models` default `leo_default()`, `spacecraft` default
    `SpacecraftConfig()`, default `LofAligned`, `IntegratorConfig.high_precision()`,
    ~300-sample internal grid, `progress=False`); Trajectory path → leading-portion
    clip, any input frame.
  - **Seed + identity:** `initial_guess` else the Chunk-0-chosen seed at the
    reference start epoch; identity resolution (kwarg → `initial_guess` →
    placeholder) staged for the final assembly.
- **Tests** (`tests/tle/test_fitter.py`): the full `ValueError` table (JVM-free
  rows fixture-free; the bound-orbit row under the `orekit` fixture); the
  Trajectory-path warning; span clipping; internal-propagation failure passthrough
  (`NumericalPropagationError` unchanged).

**Reuse:** `propagate_numerical` + its presets; `TLE.from_state_unfitted`;
`Epoch.seconds_since`; the §1.3 warn-once idiom.

**You provide:** nothing.

**You run:** the git rhythm.

**Verify:** `conda run -n propygator pytest tests/tle -v` green; the pre-flight
rows all raise before any Orekit estimation import; mypy clean.

---

## Chunk 2 — The estimator core (JVM-touching; the fit itself)

**Goal:** the batch LS wired end-to-end inside `fit_tle`, with the Chunk-0-tuned
constants — measurements, builder, optimizer, B\* toggle, convergence → TLE
assembly, non-convergence → `TLEFitError` (contract: Fit mechanism; Fitted-TLE
field policy; Failure modes).

**Create / edit:**
- `src/propygator/tle/fitter.py`:
  - PV measurement construction from the normalized reference (even subsampling to
    the internal cap; sigma/weight constants from Chunk 0).
  - `TLEPropagatorBuilder(template, PositionAngleType…, positionScale,
    generation_algorithm)` + `BatchLSEstimator(LevenbergMarquardtOptimizer(), …)`;
    `max_iterations` bounds iterations and evaluations; the `BSTAR` driver selected
    iff `fit_bstar`.
  - Convergence → assemble the returned `TLE` under the field policy (identity
    inherits — kwargs win; ṅ/n̈ zeroed; element-set/rev-number inherited verbatim;
    checksums via the Orekit formatter + `from_strings` re-validation — the
    `from_state_unfitted` pattern).
  - Non-convergence / diverged LS (the Hipparchus too-many-iterations /
    too-many-evaluations exceptions, caught at the boundary) → `TLEFitError` with
    iteration count + last RMS; no raw Java trace.
- **Tests** (`tests/tle/test_fitter.py`, `orekit` fixture):
  - **The self-fit gate (path (c)):** fit from a `propagate_tle` trajectory of a
    known TLE; assert tens-of-meters RMS over the span + close element recovery
    (the Chunk-0 numbers, now pinned).
  - The field-policy table: with/without `initial_guess`, kwarg precedence,
    ṅ/n̈ = 0, placeholder set.
  - `TLEFitError` via `max_iterations=1` on a deliberately poor seed.
  - `fit_bstar=False` holds the seed's B\*.

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

## Chunk 3 — Progress wiring (indeterminate mode)

**Goal:** the reporter driven per the contract on **every** exit path — the
`BatchLSObserver` proxy feeding `iter N | rms …` lines, the State-path phase line,
the honest final line, the callable budget fraction (contract: Progress
reporting).

**Create / edit:**
- `src/propygator/tle/fitter.py`: the `BatchLSObserver` `@JImplements` proxy →
  `reporter` per iteration; `start` line before JVM boot; the State-path
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

## Chunk 4 — Validation battery: the honest-numbers tests

**Goal:** the contract's remaining test rows — the quantitative claims the docs
will make, pinned (contract: Testing / reference cases; Validated domain).

**Create / edit** (`tests/tle/test_fitter.py`, `orekit` fixture):
- **Numerical fit (path (a)):** 2-day LEO `leo_default` reference → assert
  convergence and a bounded, documented km-level RMS (the lossiness caveat made
  quantitative; the pinned bound comes from Chunk 0, with slack).
- **B\* recovery:** a drag-dominated LEO case — `fit_bstar=True` recovers a
  plausible B\* and beats `fit_bstar=False` on propagate-back residual.
- **Deep-space branch:** the Vallado 08195-class case through a fit; the fitted
  TLE selects SDP4 (mean motion below the 225-min cutoff) and converges — or, if
  Chunk 0 showed deep-space fragility, pins the honest `TLEFitError` behavior and
  the docstring's validated-domain wording instead.
- **Path (b) smoke:** a `Trajectory.from_arrays`-built reference (the observational
  path) fits.
- Top-level export + `tests/test_public_surface.py` update.

**Reuse:** the Vallado fixtures already in the suite; `Trajectory.from_arrays`.

**You provide:** nothing.

**You run:** the git rhythm.

**Verify:** `conda run -n propygator pytest tests/tle -v` green; the documented
RMS numbers match what the docstring/README will claim.

---

## Chunk 5 — Wrap-up: docs, notebook, sweep, release

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
    fitted TLE back and plot the divergence (the lossiness caveat made visible).
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
   fitted-or-zeroed); checksums valid; `from_strings` re-validation passes.
4. **Failure honesty:** non-convergence → `TLEFitError` with iterations + last
   RMS; every `ValueError` row pre-flight; no raw Java traces.
5. **Progress:** `iter N | rms …` lines, honest final line on every exit path,
   callable budget fraction — eyeballed live at Chunk 3.
6. **Invariants:** `import propygator` JVM-free; `tests/core` no-JVM; mypy /
   pre-commit green.
7. **Docs:** README all-✅, features §1.2 Outcome, notebook 07, CHANGELOG,
   CLAUDE.md; this plan retired to `docs/history/`.

## Notes / deferred (not this plan)

- **`FitResult` / `fit_tle_detailed`** — deferred (architecture §13) unless the
  Chunk-0 residual-availability finding triggers the maintainer's in-branch
  revisit (Checkpoint A item 3).
- **Epoch at span midpoint** as an alternative anchor — deferred; start-anchored
  per the contract.
- **The pure-NumPy differential-correction fallback** — named, dormant; only if
  Checkpoint A forces it.
- **Forwarding determinate progress through the State-path internal propagation**
  (today: suppressed + a phase line) — polish, deferred.
- **Numerical orbit determination** (estimating the propagator's own Cd, etc.) —
  out of scope for v1 (architecture §13's drag-modeling note).
