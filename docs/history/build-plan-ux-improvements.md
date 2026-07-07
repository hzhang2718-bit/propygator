# Build plan: Civil Time Zones & Progress Reporting

> **Status: ARCHIVED (2026-07-06) — all four chunks built on
> `feature/ux-improvements`; both parts shipped in full.** See the contract
> section's **Outcome** note for what was learned at build (the endpoint-tick
> fix in the proxy's `finish`, the widened `try/finally` over setup, the
> consistent elapsed clock). Derived from the **"Civil Time Zones & Progress
> Reporting"** section of `docs/general-upgrades-1.md`, which is the **binding
> contract** for this work (the way "Planetary Third-Body & Earth Radiation
> Pressure" was for its plan). Every surface, behavior rule, and deliverable below
> traces to that section — cited inline as "(contract: <heading>)". Where this plan
> and the contract disagree, the **contract wins**; fix the plan. Status headers
> are the maintainer's — trust the git log for true status. Line numbers cited
> below are current as of branch creation (2026-07-06); re-verify before editing.

## Context

Two independent user-experience upgrades on one branch. **Part A:** `live_track`
gains a keyword-only `tz: USTimeZone | tzinfo | None = None` that re-expresses the
dashboard's suptitle readout clock in a US civil zone (DST-correct via `zoneinfo`);
the default stays UTC, byte-identical. It rides the tz-ready `_format_clock` seam
already shipped in `tracking/live.py` — the helper *already takes* `tz` and does
`.astimezone(tz).strftime(... %Z)` (`live.py:349-359`), so the core time model is
untouched. **Part B:** `propagate_numerical` gains
`progress: bool | ProgressCallback = True` — plain, throttled, ASCII-only stderr
status lines from an `OrekitFixedStepHandler` proxy, so a long propagation never
looks frozen. This is the **one deliberate edit to the frozen §1.1 signature**
among the general upgrades, plus a **sanctioned narrow exception** to "logging,
never prints" (stderr-only, TTY-gated, opt-out, transient).

**This is one of several independent general upgrades** headed for **v0.5.0**
(fifth, after Tier B drag, the live-dashboard mutate-in-place layer, ECEF
InPlaneTracking, and the lumped planetary third body). Its branch —
`feature/ux-improvements`, already created by the maintainer — merges to `main`
with **no version bump and no tag** (v0.5.0 is tagged once, after all upgrades
land). `general-upgrades-1.md` stays alive for any remaining upgrades.

**End state:** `live_track("ISS", tz=USTimeZone.PACIFIC)` renders
`… · 2026-07-05 11:42:03 PDT` (and `PST` in winter, automatically) while `tz=None`
stays byte-identical to today; a bare `propagate_numerical(...)` prints
`start` / throttled progress / `done` lines to a TTY stderr (coarse 25/50/75
milestones when non-TTY), `progress=False` silences it, `progress=<callable>`
receives the 0→1 fraction and the library prints nothing; a guard-stopped run ends
with an honest `stopped at NN% | <reason> …` line; `USTimeZone` and
`ProgressCallback` are top-level exports; `tzdata` is a declared dependency.

### Source-of-truth docs (do not silently diverge)

- `docs/general-upgrades-1.md` **"Civil Time Zones & Progress Reporting"** — the
  binding contract. Key sub-headings: *Supercessions*, *Context*, *Part A — time
  zones (details)* (`USTimeZone`, Resolution, Threading, User-visible change,
  Dependency, Out of scope), *Part B — progress reporting (details)* (Surface,
  Reporter behavior, Mechanism, Composition with the guard system, Sanctioned
  exception, Default-on implications, Out of scope), *Build shape*.
- `docs/features.md` §1.1 / §1.4 and `docs/architecture.md` — authoritative
  **except** the spots the contract's *Supercessions* list replaces; reconciled in
  Chunk 4 (the §Logging carve-out lands with Chunk 3, where the exception first
  exists in code).
- `docs/prospective-forces-and-progress-findings.md` §4 / §5.2 / §5.3 — the
  progress-reporting mechanism reference (probed 2026-06-20: the
  `OrekitFixedStepHandler` proxy fires during `propagate()` and coexists with the
  ephemeris generator). Its item-3 status header flips in Chunk 4.

### Decisions already locked (do not relitigate)

- **Civil zones are display-only.** `Epoch` / `TimeScale` / `to_iso` gain nothing;
  `tz` lives on the display verb and threads into `_format_clock` — **no change to
  `_format_clock`'s body**, only its docstring (contract: *Part A → Threading*).
- **Default UTC**, not system-local; **US-only enum** (Eastern / Central /
  Mountain / Pacific / Alaska / Hawaii / Arizona) + a raw-`tzinfo` escape hatch;
  the seven IANA keys are pinned verbatim by the contract (contract: *Part A →
  `USTimeZone`*).
- **`tzdata` is declared**, not assumed: conda-forge name **`python-tzdata`** in
  `environment.yml` (the conda package named plain `tzdata` is the raw IANA
  database, no Python module), PyPI name **`tzdata`** in `pyproject` runtime deps
  (contract: *Part A → Dependency*). Probed 2026-07-06: the env already resolves
  `ZoneInfo("America/Los_Angeles")` DST-correctly (→ PDT), so no env rebuild is
  needed to develop.
- **Progress is default-on, plain milestone lines, no new dependency** — no tqdm,
  no `\r` bar (contract: *Context*, *Out of scope (Part B)*). The reporter is
  swappable behind `progress`, so tqdm is a later zero-API-change promotion.
- **Fraction denominator is the realized span** `(n_samples − 1) · output_step` —
  the actual `propagate()` target, not the requested `duration` (which the grid
  floors); a single-sample run has `span == 0` and gets `start`/`done` only
  (contract: *Mechanism*).
- **Non-TTY coarsens, it does not silence**: `start` + 25/50/75 + `done` — this is
  what keeps Jupyter (captured, non-TTY stderr) informative; interactive batch
  loops opt out with `progress=False` (contract: *Reporter behavior*, *Default-on
  implications*).
- **`logger.info` milestones are emitted regardless** of `progress` mode and TTY
  state — logging is not "printing"; `progress` governs only the stderr/callable
  emission (contract: *Reporter behavior*, last bullet).
- **The `finally` spans propagation through termination classification** — the
  reason in the `stopped at NN%` line is only known after the guard system
  classifies; the re-raise path gets a reasonless `failed at NN%` (contract:
  *Composition with the guard system*).
- **Forward commitments only** for 1.5/1.2: both eventually take the same
  `progress` param (1.5 determinate, 1.2 indeterminate) and 1.5 the same `tz=`
  surface — **no 1.5/1.2 code lands on this branch** (contract: *Part A → Feature
  1.5 inheritance*, *Part B → Features 1.5 / 1.2*).
- **Bundle into v0.5.0** — no tag / version bump in this plan.

### Architecture invariants to honor (CLAUDE.md / architecture §4, §10)

Orekit/Java types stay internal; `jpype`/`org.orekit.*` imports **lazily inside
functions**; `USTimeZone` / `_resolve_tz` / all of `core/progress.py` stay
**pure-Python, safe before init** (`zoneinfo` is stdlib and JVM-free — fine in
`tests/core`); the step-handler proxy implements **all three** interface methods
(`init`/`handleStep`/`finish` — the JPype default-method trap, findings §5.3);
JVM-touching tests acquire the **`orekit` fixture**; reporter output
**ASCII-only** (the Windows cp1252 stderr class); errors carry actionable
messages, never raw tracebacks; mypy gates `src/`.

---

## How to use this plan

- **4 numbered chunks**, each sized for one Claude Code session and independently
  verifiable:
  - **Chunk 1 is Part A end-to-end** (pure-Python + a display-verb thread + deps).
  - **Chunks 2–3 are Part B** (the headless reporter, then the JVM wiring — the
    contract's two halves in dependency order).
  - **Chunk 4 is wrap-up.**
- Each chunk lists **Goal / Create-Edit / Reuse / You provide / You run / Verify**.
- **No STOP gate.** One soft checkpoint: **Checkpoint A** (after Chunk 3) — the
  maintainer runs a long propagation **in a real terminal** and eyeballs the fine
  TTY cadence and line format. This is load-bearing: every harness/CI/pytest
  context is non-TTY, so the fine cadence is human-verifiable only.
- **`/code-review` + `/simplify` checkpoints:** after Chunk 1 (the Part A diff),
  after Chunk 3 (the Part B diff), and in the Chunk 4 sweep.
- **Commits, CHANGELOG entries, chunk-header "done" marks, and the merge are the
  maintainer's.** Claude writes code and runs read-only/test commands; the
  maintainer runs the GUI/terminal smokes, commits, and pushes.
- **Mergeable chunks:** 2 + 3 can share a session (the reporter is small and its
  consumer lands immediately); split if the JVM test session runs long.

---

## Git (read once)

The branch **`feature/ux-improvements`** already exists (created by the maintainer
off `main`); the contract section and this plan ride on it. Per-chunk rhythm:
`git status` → `git add -A` →
`git commit -m "ux-improvements chunk N: <summary>"` → `git push` (CI runs on the
branch). **Do NOT** bump `pyproject.toml` version or tag — v0.5.0 is cut after all
the general upgrades land.

---

## Chunk 1 — Part A: `USTimeZone` + `tz=` on `live_track`, end-to-end - Done

**Goal:** `live_track(..., tz=USTimeZone.PACIFIC)` renders the readout clock in
DST-correct Pacific civil time; `tz=None` stays byte-identical; `USTimeZone` is a
top-level export; `tzdata` is declared (contract: *Part A — time zones (details)*,
all sub-headings; *Supercessions → Part A*).

**Create / edit:**
- `src/propygator/core/time.py`:
  - `USTimeZone(Enum)` immediately after `TimeScale` (`time.py:61-72`), the seven
    members **verbatim from the contract** (EASTERN `America/New_York` … ARIZONA
    `America/Phoenix`); docstring notes the US-only scope + the raw-`tzinfo`
    escape hatch and that this is *civil display* time, deliberately outside the
    physics `TimeScale` model.
  - `_resolve_tz(tz: USTimeZone | tzinfo | None) -> tzinfo` beside it:
    `None → timezone.utc`; `tzinfo` returned as-is; `USTimeZone` lowered to
    `ZoneInfo(member.value)`; anything else raises `TypeError` naming the three
    accepted forms. Wrap `ZoneInfoNotFoundError` (stripped tz database) as
    `PropygatorError` (`core/exceptions.py`) with a remedy message naming **both**
    install names (`pip install tzdata` / `conda install python-tzdata`), `from
    exc` — never a raw traceback. `zoneinfo` imports at module top (stdlib,
    JVM-free, cheap).
  - Module docstring: one sentence distinguishing civil display zones from the
    physics scales (UT1 deferral text untouched).
- `src/propygator/tracking/live.py`:
  - `live_track` gains trailing keyword-only `tz: USTimeZone | tzinfo | None =
    None` (after `refresh_s`, `live.py:488`); resolved **once at entry** —
    `tz_resolved = _resolve_tz(tz)` before the engine/figure are built, so a bad
    `tz` fails fast — and threaded into the one `_format_clock(now)` call site
    (`live.py:812` → `_format_clock(now, tz=tz_resolved)`). `USTimeZone` /
    `_resolve_tz` import from `..core.time` at module top (pure-Python; `live.py`
    stays Orekit-free).
  - `_format_clock` **docstring only** (`live.py:350-358`): the "v1 always renders
    UTC; a future `tz=` … out of scope for 1.4" note is rewritten to describe the
    shipped path (contract: *Supercessions → Part A*, `_format_clock` bullet). The
    body at `live.py:359` is untouched.
  - `live_track` docstring: a `tz` paragraph — default UTC unchanged; only the
    suptitle readout localizes (panels are elapsed-hours/spatial); `%Z` renders
    the zone name so DST self-documents.
- `src/propygator/__init__.py`: `USTimeZone` added to the `from .core.time import`
  line (`__init__.py:43`) and to `__all__` (`:83`).
- **Dependencies:** `environment.yml` — `- python-tzdata` in the conda list
  (before the `pip:` block); `pyproject.toml` — `"tzdata"` appended to
  `[project] dependencies` (`pyproject.toml:14-21`). No env rebuild needed
  (already present transitively); note in the commit that a fresh
  `conda env create` now pins it explicitly.
- **Tests** (`tests/core/test_time.py` — pure-Python, no JVM; `zoneinfo` is fine
  there):
  - The enum is **exactly** the pinned seven members with the pinned IANA values.
  - `_resolve_tz(None) is timezone.utc`; a `tzinfo` instance passes through
    identically; `USTimeZone.EASTERN` resolves to a `ZoneInfo` with
    `key == "America/New_York"`.
  - **DST pins:** a July UTC instant re-expressed in EASTERN has a −4 h offset
    (`EDT`), a January instant −5 h (`EST`); ARIZONA holds −7 h in both months and
    HAWAII −10 h (the no-DST members).
  - The `TypeError` path (e.g. a bare string) and the `ZoneInfoNotFoundError` →
    `PropygatorError` wrap (monkeypatch `ZoneInfo` in `core.time` to raise; assert
    the message names `tzdata`).
- **Tests** (`tests/tracking/test_live_dashboard.py`): extend the existing
  `_format_clock` pair (`:319-332`) with a resolved-`USTimeZone` case — a July
  epoch through `_resolve_tz(USTimeZone.PACIFIC)` renders `… PDT` and shifts the
  civil hour by −7; a winter epoch renders `… PST` (the end-to-end
  seam-plus-resolution proof, still headless).
- **Tests** (`tests/test_public_surface.py`): `EXPECTED_NAMES` (`:32-55`) gains
  `"USTimeZone"`.
- `run/live_dashboard_demo.py` (gitignored, on the maintainer's disk): add a
  `--tz` flag lowering a friendly name to a `USTimeZone` member, for the manual
  smoke.

**Reuse:** the shipped `_format_clock` seam wholesale (`live.py:349-359` — zero
body change is the point); `Epoch.to_datetime()` (`time.py:361`); the existing
`_format_clock` test shapes (`test_live_dashboard.py:319-332`); `PropygatorError`.

**You provide:** the manual GUI smoke — `python run/live_dashboard_demo.py --tz
pacific` (or eastern), confirming the readout clock shows the localized time +
zone name and everything else is unchanged.

**You run:** the GUI smoke; the per-chunk git rhythm.

**Verify:** `conda run -n propygator pytest tests/core tests/tracking
tests/test_public_surface.py -v` green with the `tests/core` no-JVM property
intact;
`conda run -n propygator python -c "import propygator, jpype; print(propygator.USTimeZone.PACIFIC.value, jpype.isJVMStarted())"`
→ `America/Los_Angeles False`; `pre-commit run --all-files` green (mypy covers the
new `src/` code).

> ### ✅ Checkpoint — Part A shipped
> 1. `tz=None` byte-identical; localized readout confirmed by the GUI smoke.
> 2. `/code-review` + `/simplify` on the Chunk 1 diff.
> 3. Commit + push.

---

## Chunk 2 — Part B: the `_ProgressReporter` (headless, pure-Python) - Done

**Goal:** `core/progress.py` exists with both modes, the TTY gate, the
10-percent/heartbeat throttle, ASCII-only rendering, the callable pass-through,
and the idempotent finalize — fully unit-tested with **no JVM and no sleeping**
(contract: *Reporter behavior*, *Surface*; *Supercessions → Part B*, Code bullet).

**Create / edit:**
- `src/propygator/core/progress.py` (new; module docstring cites the sanctioned
  exception: stderr-only, TTY-gated, opt-out, transient, never stdout, never the
  root logger):
  - `ProgressCallback = Callable[[float], None]` — the **public** alias (it names
    a public parameter type).
  - `_ProgressReporter` — suggested shape (build finalizes names, not behavior):
    - Constructed with the verb name (`"propagate_numerical"`), the resolved
      emission mode lowered from the `progress` argument (built-in printer /
      callable / silent), and **injectable** `stream` and `clock` (defaults:
      resolve `sys.stderr` **at write time** — late binding keeps pytest capture
      and user redirection honest — and `time.monotonic`). The TTY gate reads
      `stream.isatty()` per the contract.
    - **Determinate mode:** `start(detail: str)` prints immediately;
      `update(fraction)` emits on each new **10%** boundary *or* ≥ **~5 s** since
      the last emission (TTY) — non-TTY emits **only** on crossing 25/50/75;
      `finish(detail)` prints the `done` (or `stopped at NN% | …`) line.
    - **Indeterminate mode:** `step(text)` per-iteration lines (`iter N | rms …`),
      same TTY/throttle discipline — built and tested now so the seam has its 1.2
      shape, **no runtime consumer this branch**.
    - `close()` — idempotent: a no-op after `finish()`, otherwise emits the
      honest `failed at NN%` fallback (the `finally` hook).
    - Every emission is **ASCII-only** (`|`, `-`, `#` separators; the contract's
      illustrative line format); `logger.info` milestones fire on the coarse
      boundaries **regardless** of mode and TTY.
    - Callable mode: forward the fraction on each throttled tick, **print
      nothing**; exceptions from the user callable propagate (their bug, not
      swallowed).
    - Degenerate zero-span guard: a reporter driven with no `update()` ticks
      still produces clean `start`/`done` (contract: *Mechanism*, parenthetical).
- **Tests** (`tests/core/test_progress.py` — new; a fake stream recording writes
  with a settable `isatty()`, and a fake manually-advanced clock, so the heartbeat
  is tested without wall-clock sleeps):
  - TTY: `start` immediate; ticks at 10% boundaries; a heartbeat line after +5 s
    fake-clock with no percent change; no spam between boundaries.
  - Non-TTY: exactly `start` + 25/50/75 + `done` for a full sweep of updates.
  - Callable: receives a monotonic ≤1.0 fraction sequence; the stream stays empty.
  - Silent (`progress=False` lowering): stream empty; `logger.info` milestones
    still emitted (assert via `caplog`).
  - `close()` without `finish()` emits one `failed at NN%` line; after `finish()`
    it is a no-op; double-`close()` safe.
  - Zero-tick run: `start` + `done` only. Every captured byte `.encode("ascii")`s.
  - Indeterminate: `step()` lines render; no percentage appears.

**Reuse:** the repo's logger-per-module pattern; `tests/core`'s no-JVM discipline
(this file must not disturb it — `progress.py` imports nothing beyond stdlib).

**You provide:** nothing.

**You run:** the per-chunk git rhythm (or hold the commit and land Chunks 2+3
together).

**Verify:** `conda run -n propygator pytest tests/core -v` green and JVM-free;
`pre-commit run --all-files` green.

---

## Chunk 3 — Part B: the step-handler proxy + `progress=` in `propagate_numerical` - Done

**Goal:** a bare `propagate_numerical(...)` reports progress through the shipped
reporter from inside the real `propagate()`; `progress=False` / callable behave
per the contract table; a guard-stopped run ends with the reason-bearing line; the
convention carve-out lands in `architecture.md` + `CLAUDE.md` (contract:
*Surface*, *Mechanism*, *Composition with the guard system*, *Sanctioned
exception*; *Supercessions → Part B*).

**Create / edit:**
- `src/propygator/propagation/numerical.py`:
  - **Signature** (`:888-899`): trailing `progress: bool | ProgressCallback =
    True` after `name` — the one deliberate §1.1 edit; `ProgressCallback`
    imported from `..core.progress`. Validate early beside the existing argument
    checks: a non-bool non-callable raises `TypeError`.
  - **Docstring:** a "Progress reporting" paragraph after the model-limitations
    block — the contract table (True / False / callable), the TTY-gated stderr
    behavior, the non-TTY coarsening, and the sanctioned-exception one-liner.
  - **Reporter start** immediately after the existing start `logger.info`
    (`:1008-1018`) and **before** `_ensure_started()` (`:1020`) — the start line
    then also covers JVM startup latency, the first real "it began" signal.
    Detail string from facts already in hand: span hours, `integrator.type`,
    `n_samples`.
  - **The proxy:** a small factory (e.g. `_make_progress_step_handler(start_date,
    span_s, reporter)`) returning an
    `@JImplements("org.orekit.propagation.sampling.OrekitFixedStepHandler")`
    class instance implementing **all three** of `init`/`handleStep`/`finish`
    (`init`/`finish` as no-op bodies; the default-method trap, findings §5.3;
    JPype imports lazily inside). `handleStep(state)` computes
    `fraction = state.getDate().durationFrom(start_date) / span_s` and calls
    `reporter.update(fraction)` — `span_s` is the **realized** span
    `float(end_date.durationFrom(start_date))` (`:1097-1098`), not `duration`
    (contract: *Mechanism*).
  - **Registration** just before `t0` (`:1100`):
    `propagator.getMultiplexer().add(handler_step_s, handler)`. Suggested
    `handler_step_s = span_s / 1000` (≤1000 JPype crossings — negligible; the
    reporter throttles output, the handler cadence only bounds heartbeat
    resolution — build finalizes the constant with a comment). **Skip
    registration when `span_s == 0`** (the single-sample run: `start`/`done`
    only).
  - **The `finally`:** wrap from the registration/`t0` region through the
    classification + `Trajectory` build (`:1100-1222`) in `try/finally` with
    `reporter.close()` in the `finally`. On the normal path call
    `reporter.finish(...)` beside the existing done `logger.info` (`:1229-1234`)
    — the `done | <span> | <wall> | <N> samples` line, or, when `terminated`, the
    `stopped at NN% | <termination_reason> at t+… | <wall> | <N> samples
    (partial)` line (reason + epoch available from `:1167-1202`). The re-raise
    path (`:1223-1228`) raises **inside** the `try`, so `close()` emits the
    reasonless `failed at NN%` — every exit path ends with one honest final line
    (contract: *Composition with the guard system*). The post-propagation
    sampling loop is inside the wall-clock but gets no ticks of its own (contract:
    not covered).
- `src/propygator/__init__.py`: `ProgressCallback` re-exported (import from
  `.core.progress`; added to `__all__`).
- `docs/architecture.md` §Logging (`architecture.md:1058-1072`) + `CLAUDE.md`
  "Architecture invariants" ("Logging, never prints" bullet): the
  **sanctioned-exception clause** — transient progress output may go to stderr
  provided it is TTY-gated, opt-out (`progress=False`), never stdout, never the
  root logger (contract: *Sanctioned exception*; the carve-out lands here, with
  the code that first exercises it — Chunk 4 only reconciles the remaining doc
  spots).
- **Tests** (`tests/propagation/test_numerical.py`, `orekit` fixture, all through
  a real `propagate()` on a short cheap arc — e.g. the keplerian-ish configs the
  file already uses):
  - **Callable seam:** `progress=<recorder>` collects a monotonic fraction
    sequence within [0, 1] ending ≈ 1.0, and `capsys` shows **nothing** on
    stderr.
  - **Default under pytest** (captured stderr is non-TTY): the run emits the
    coarse set — assert the `start` and `done` lines and that any percent lines
    are within {25, 50, 75}.
  - **`progress=False`:** `capsys` stderr empty.
  - **Guard stop:** reuse a terminating scenario from the guard tests (e.g. an
    `AltitudeLimits` stop) with `progress=True`; the final stderr line contains
    `stopped` and the recorded `termination_reason`.
  - **Public surface:** `EXPECTED_NAMES` gains `"ProgressCallback"`
    (`test_public_surface.py:32-55`).
  - **Regression:** the full suite green — every existing `propagate_numerical`
    call is unaffected in results/metadata (progress writes only to captured
    stderr; if any existing test asserts on stderr contents, give it
    `progress=False` rather than weakening the assert).

**Reuse:** the Chunk-2 reporter as-is; the `@JImplements` three-method pattern
(`attitude.py`'s `TargetProvider` proxy is the shipped precedent); the realized
`end_date`/`last_offset` already computed at `:1097-1098`; the classification
facts at `:1167-1202`; the guard-test terminating scenarios.

**You provide:** nothing until Checkpoint A.

**You run:** the per-chunk git rhythm; the Checkpoint-A terminal smoke.

**Verify:** `conda run -n propygator pytest` (full suite) green;
`conda run -n propygator python -c "import propygator, jpype; print(jpype.isJVMStarted())"`
→ `False`; `pre-commit run --all-files` green; a redirected run
(`conda run … > out.txt 2> err.txt`) shows only the coarse milestone lines in
`err.txt` and **nothing** on stdout.

> ### 🔎 Checkpoint A — TTY cadence eyeballed (soft; not a STOP gate)
> 1. Maintainer runs a real multi-minute propagation **in an interactive
>    terminal** (e.g. a 7-day drag-on LEO arc) and confirms: `start` appears
>    immediately, the 10%/heartbeat cadence feels right, lines are clean ASCII,
>    `done` reports honest wall/samples — the one path no automated context can
>    exercise (everything harness-side is non-TTY).
> 2. `/code-review` + `/simplify` on the Chunks 2–3 diff.
> 3. If the cadence/format disappoints, tune `_ProgressReporter` constants (pure
>    Python, no contract change — the 10% / ~5 s numbers are contract, the feel
>    around them is not) before Chunk 4.
> 4. Commit + push.

---

## Chunk 4 — Wrap-up: docs reconciliation, sweep, merge (no tag)

**Goal:** land the upgrade — the contract's *Supercessions* folded back, the
findings doc item-3 status flipped, clean sweep, merge to `main`. **No version
bump, no tag.**

**Create / edit / run:**
- Full local CI parity: `conda run -n propygator pytest` and
  `conda run -n propygator pre-commit run --all-files` green from repo root.
- `/code-review` + `/simplify` final pass across the whole diff.
- **Reconcile the docs** (the contract's *Supercessions* list — exactly those
  spots):
  - `features.md` §1.4 — the ground-track-panel "UTC clock" paragraph (`:895`),
    the "Time-zone exposure" deferred bullet (`:905` — the `live_track` half
    realized, the general-tools half re-pointed at 1.5), and the `live_track`
    signature block (`:799` — the trailing `tz` parameter; buffer magnitudes
    untouched).
  - `features.md` §1.1 — the `propagate_numerical` signature gains `progress`;
    a new "Progress reporting" paragraph (default-on reporter, `False` opt-out,
    callable seam).
  - `architecture.md` §Logging + `CLAUDE.md` — confirm the Chunk-3 carve-out
    reads as the contract's clause (edit only if drift).
  - `docs/prospective-forces-and-progress-findings.md` — the status header's
    item-3 sentence flips to "scoped by general-upgrades-1 §Civil Time Zones &
    Progress Reporting; shipped" (§4 stays the mechanism reference).
  - `README.md` — the `live_track` example/prose gains a `tz=` mention; the
    `propagate_numerical` blurb gains the progress default + `progress=False`.
  - **Add the Outcome note** to the contract section's header blockquote (the
    ECEF/blitting/perturbations precedent): shipped in full (or what actually
    happened), Supercessions folded back.
  - **Leave `general-upgrades-1.md` in place** (alive for any remaining
    upgrades).
  - **You** update `CHANGELOG.md` `[Unreleased]` (per
    `docs/changelog-guidelines.md` — note the deliberate default-behavior change:
    a bare `propagate_numerical` now prints progress) and refresh `CLAUDE.md`
    "Project state" (the narrative artifacts are yours).
- **Merge:** `gh pr create` against `main`, CI green,
  `gh pr merge --squash --delete-branch` — **your call**. This plan then retires
  to `docs/history/`.

**You provide:** CHANGELOG + CLAUDE.md narrative edits; the merge go-ahead.

**Verify:** full `pytest` + `pre-commit run --all-files` green; `pyproject.toml`
version **unchanged** (the `tzdata` dependency line is the only pyproject edit);
every *Supercessions* spot carried; `import propygator` stays JVM-free.

---

## End-state verification (shipped → on `main`, untagged)

1. **Part A:** `USTimeZone` is the pinned seven-member enum, top-level exported;
   `_resolve_tz` covers None/tzinfo/enum + the actionable `tzdata` error;
   `live_track(tz=…)` localizes exactly the readout clock, DST-correct via
   `zoneinfo`; `tz=None` byte-identical; `python-tzdata`/`tzdata` declared in
   `environment.yml`/`pyproject.toml`.
2. **Part B:** `progress: bool | ProgressCallback = True` on
   `propagate_numerical`; the reporter is stderr-only, ASCII-only, TTY-gated
   (fine cadence on a TTY, `start`+25/50/75+`done` otherwise), `logger.info`
   milestones regardless; the fraction runs over the realized span; every exit
   path (done / guard stop / re-raise) ends with one honest final line;
   `ProgressCallback` top-level exported.
3. **Conventions:** `architecture.md` §Logging and `CLAUDE.md` carry the
   sanctioned-exception clause; no stdout writes anywhere; no new dependencies
   beyond the declared `tzdata`.
4. **Docs:** the *Supercessions* map carried into `features.md` §1.1/§1.4 and
   `README.md`; the findings doc's item-3 status flipped (§4 stays the mechanism
   reference); the contract section carries its Outcome note; CHANGELOG +
   CLAUDE.md updated; **version unchanged / untagged**.
5. `conda run -n propygator python -c "import propygator, jpype; print(jpype.isJVMStarted())"`
   → `False`.

## Notes / deferred (not this plan)

- **Feature 1.5 / 1.2 consumption** of `tz=` and `progress=` — forward
  commitments; they land with those features.
- **tqdm / rich, a `\r` animated bar, covering the sampling loop or
  `propagate_tle`, non-US enum members, localizing the CSV `epoch_utc` column,
  any `Epoch`/`TimeScale`/`to_iso` change** — all contract *Out of scope*.
- **The indeterminate mode's callable semantics** — pinned by 1.2's own contract
  when it starts (the mode itself ships now, reporter-side only).
- **v0.5.0 tag** — the separate cross-upgrade step once all general upgrades
  land.
