# Build plan: Planetary Third-Body & Earth Radiation Pressure

> **Status: ARCHIVED (2026-07-05) — Chunk 1 (planets) shipped; Chunks 2–3 (ERP)
> built, reverted, and BLOCKED on upstream Orekit; Chunk 4 ran planets-only.**
> Chunk 2's effect-envelope test exposed the `KnockeRediffusedForceModel`
> horizon-bound defect present in every installable Orekit (≤ 13.1.5; fixed upstream
> in 13.1.6) — see the contract section's **Outcome** note and
> `experiments/earth-radiation/` (bug evidence, the parked Chunk-2 patch, and the
> resume recipe; Chunks 2–3 below are the recipe's authoritative sequencing when the
> feature resumes). Derived from the **"Planetary Third-Body & Earth Radiation
> Pressure"** section of `docs/general-upgrades-1.md`, which is the **binding
> contract** for this work (the way "ECEF InPlaneTracking" was for its plan). Every
> field, token, wiring rule, and deliverable below traces to that section — cited
> inline as "(contract: <heading>)". Where this plan and the contract disagree, the
> **contract wins**; fix the plan. Status headers are the maintainer's — trust the git
> log for true status.

## Context

`ForceModelConfig` gains two opt-in booleans: **`planets_third_body`** (lumped
third-body gravity from the pinned seven-planet set — Mercury, Venus, Mars, Jupiter,
Saturn, Uranus, Neptune) and **`earth_radiation`** (Knocke's rediffused Earth albedo +
thermal-IR radiation pressure through the existing SRP optics). Both are stock Orekit
force models slotting into wiring that already exists — **no `@JImplements` proxies, no
new data** (the bundled DE ephemeris already answers for the planets). The
`propagate_numerical` signature is untouched; both fields are off in every preset, so
default runs stay bit-identical.

**This is one of several independent general upgrades** headed for **v0.5.0** (fourth,
after Tier B drag, the live-dashboard mutate-in-place layer, and ECEF InPlaneTracking).
Its branch — `feature/additional-perturbations`, already created by the maintainer —
merges to `main` with **no version bump and no tag** (v0.5.0 is tagged once, after all
upgrades land). `general-upgrades-1.md` stays alive for any remaining upgrades.

**End state:** `ForceModelConfig(planets_third_body=True)` wires seven
`ThirdBodyAttraction`s and emits `third_body:planets`;
`ForceModelConfig(earth_radiation=True)` wires `KnockeRediffusedForceModel` at a
benchmark-chosen `_EARTH_RADIATION_ANGULAR_RESOLUTION` and emits `earth_radiation`; the
`spacecraft`/`attitude` metadata gates cover drag/SRP/ERP; the honest-magnitude numbers
(ERP-vs-SRP fraction for the reference sail and a conventional bus; the tiny planetary
effect) are committed evidence quoted by the docs.

### Source-of-truth docs (do not silently diverge)

- `docs/general-upgrades-1.md` **"Planetary Third-Body & Earth Radiation Pressure"** —
  the binding contract. Key sub-headings: *Supercessions*, *Context*, *Details* (API at
  a glance, The planet set, Planets wiring, Earth-radiation wiring,
  `_EARTH_RADIATION_ANGULAR_RESOLUTION`, Metadata, Validation, Failure modes,
  Performance, Docstrings, Evidence deliverables, Out of scope, Build shape).
- `docs/features.md` §1.1 and `docs/architecture.md` §13 — authoritative **except** the
  spots the contract's *Supercessions* list replaces; reconciled in Chunk 4.
- `docs/prospective-forces-and-progress-findings.md` §2/§3/§5 — the analysis basis
  (Orekit-API claims confirmed by introspection 2026-06-20: every planet getter resolves
  off the bundled DE ephemeris; `KnockeRediffusedForceModel` present with the 4-arg +
  TimeScale constructors). Its §4 (progress reporting) stays unscoped — the doc remains
  in `docs/` as that item's reference.
- `experiments/ecef-attitude-benefit/` — the committed template for Chunk 3's study
  (driver shape, figure + ASCII `results.txt` + folder `README.md` provenance pattern,
  and the reference-sail scenario itself).

### Decisions already locked (do not relitigate)

- **One lumped toggle**, pinned seven-planet set, wired in heliocentric order; **one**
  token `third_body:planets` after `third_body:moon`. No per-planet toggles, no Pluto,
  no barycenters (contract: *The planet set*, *Out of scope*).
- **`earth_radiation` = Knocke combined albedo + IR** (Orekit ships nothing finer); a
  **bare** token after `srp` (resolution not encoded — the ocean-tides precedent;
  `propygator_version` pins the constant).
- **The resolution knob is a module constant**, not a config field; its **value is
  chosen by the Chunk-3 benchmark**, not by this plan (contract:
  *`_EARTH_RADIATION_ANGULAR_RESOLUTION`*).
- **Optics are the SRP optics, reused**: sphere → `IsotropicRadiationSingleCoefficient`;
  box → the shared `BoxAndSolarArraySpacecraft`, now driving up to **three** forces.
- **Fields insert in metadata-grammar order** (not appended); the positional-index
  shift is accepted (contract: *Supercessions*, first bullet).
- **Independent toggles** (`earth_radiation` without `srp` is valid); **no shadow
  wiring** (Earth IR acts in eclipse; the model computes the lit cap itself).
- **Metadata gates widen**: `spacecraft` on drag/SRP/ERP; `attitude` on box + any of
  those three.
- **No STOP gate.** The evidence work is selection + characterization, not go/no-go
  (contract: *Context*, last bullet).
- **Bundle into v0.5.0** — no tag/version bump in this plan.

### Sequencing note (the one deliberate reorder, synced to the contract)

The contract's original *Build shape* sketch put the ERP experiment before the ERP
runtime. This plan runs **runtime first (Chunk 2), experiment second (Chunk 3)** — and
the contract's *Build shape* line was updated to match: unlike ECEF (whose
`CustomAttitude` stand-in let the study run pre-runtime through the shipped stack), ERP
has no stand-in — an experiment-first driver would have to re-derive raw-Orekit
propagation (gravity + box + attitude wiring) and would then measure something *other
than the shipped path*. Instead Chunk 2 lands the runtime with a **provisional**
constant, and Chunk 3 sweeps the resolution *through the shipped stack* by overriding
the module constant per rung (a one-line override, confined to the reference script and
documented in its header), then finalizes the constant. The deliverables and their
finalized-before-any-doc-quotes property are unchanged.

### Architecture invariants to honor (CLAUDE.md / architecture §4, §10)

Orekit/Java types stay internal; `jpype`/`org.orekit.*` imports **lazily inside
functions**; config construction + validation + serialization stay **pure-Python, safe
before init** (the `tests/core`-style no-JVM property); SI internally; `logging`, never
`print`; JVM-touching tests acquire the **`orekit` fixture** (that is how the conftest
hook orders them after the pure-Python guards); experiment stdout **ASCII-only**
(captured under cp1252).

---

## How to use this plan

- **4 numbered chunks**, each sized for one Claude Code session and independently
  verifiable:
  - **Chunks 1–2 are the shipped code** (planets end-to-end, then ERP runtime — each
    mixes a small pure-Python config surface with JVM-touching wiring/tests).
  - **Chunk 3 is committed evidence** (conda env only — every piece is shipped; no
    experiment venv, no pymsis/scipy) and finalizes the resolution constant.
  - **Chunk 4 is wrap-up.**
- Each chunk lists **Goal / Create-Edit / Reuse / You provide / You run / Verify**.
- **No STOP gate.** One soft checkpoint: **Checkpoint A** (after Chunk 3) — the
  maintainer confirms the chosen resolution constant and the honest numbers before any
  doc quotes them. If the benchmark shows no convergence plateau or pathological cost,
  pause and reconcile with the contract before Chunk 4.
- **`/code-review` + `/simplify` checkpoints:** after Chunk 2 (the full shipped diff to
  that point) and in the Chunk 4 sweep.
- **Commits, CHANGELOG entries, chunk-header "done" marks, and the merge are the
  maintainer's.** Claude writes code and runs read-only/test commands; the maintainer
  runs the study, commits, and pushes.
- **Mergeable chunks:** 1 + 2 can share a session (the config seams are the same
  pattern twice); split if the JVM test session runs long.

---

## Git (read once)

The branch **`feature/additional-perturbations`** already exists (created by the
maintainer off `main`); the contract section and this plan ride on it. Per-chunk
rhythm: `git status` → `git add -A` →
`git commit -m "additional-perturbations chunk N: <summary>"` → `git push` (CI runs on
the branch). **Do NOT** bump `pyproject.toml` version or tag — v0.5.0 is cut after all
the general upgrades land.

---

## Chunk 1 — Planets third body, end-to-end - Done

**Goal:** `planets_third_body` constructs and validates with **no JVM**, wires seven
`ThirdBodyAttraction`s in heliocentric order, emits `third_body:planets` in the fixed
grammar slot, and its (tiny) effect is pinned at GEO (contract: *The planet set*,
*Planets wiring*, *Metadata*, *Evidence deliverables* 3).

**Create / edit:**
- `src/propygator/core/bodies.py` — seven accessors `_mercury()` … `_neptune()`, each a
  verbatim clone of `_moon()` (`bodies.py:89-96`) over the matching
  `CelestialBodyFactory` getter; extend the module docstring's Sun/Moon framing to
  cover the planets (still module-internal, lazy-JVM, uncached like Sun/Moon — the
  factory returns Orekit's own singletons).
- `src/propygator/propagation/force_models.py`:
  - `planets_third_body: bool = False` **inserted after** `moon_third_body`
    (`force_models.py:92`) — grammar order, not appended (contract: *Supercessions*).
  - `_serialize_force_models` (`:31`): new **required** keyword `planets_third_body`;
    token `third_body:planets` emitted after the moon token (`:61-62`); update the
    fixed-order docstring (`:47-50`) and the module-docstring grammar sentence.
  - `_metadata_tokens` (`:151-171`) passes the new field.
  - The class docstring gains the planetary honesty caveat sentence (contract:
    *Docstrings*): ~1e-10–1e-13 of central gravity, Venus/Jupiter dominate, a
    completeness option that will not visibly move a LEO trajectory.
  - Presets: **no changes** (the field defaults False everywhere; the preset docstrings
    still accurately say "sun+moon").
- `src/propygator/propagation/numerical.py`:
  - `_WiredForces` gains `planets_third_body: bool` (`numerical.py:304-310`).
  - `_add_perturbation_forces` (`:731`): the planets block immediately after the Moon
    line (`:763`) — seven `ThirdBodyAttraction` adds in heliocentric order (a loop over
    the seven accessors is fine); mirror the fact into the `_WiredForces` return
    (`:776-784`); extend the function docstring's force-order note.
  - The `_serialize_force_models` call site (`:1239-1250`) passes
    `wired.planets_third_body`.
- **Tests** (`tests/propagation/test_force_models.py` — pure-Python, fixture-free):
  - `test_defaults` (`:25`) gains `planets_third_body is False`; the three preset tests
    (`:49`, `:53`, `:62`) pin it False.
  - Grammar: extend `test_metadata_token_order_is_fixed` (`:120`) and
    `test_serializer_is_driven_by_facts_not_config` (`:145`) with the new token/keyword;
    add a planets-on serialization case (mirror `test_metadata_full_leo_with_solid_tides`
    `:95`) asserting `third_body:planets` sits between `third_body:moon` and the drag
    token.
- **Tests** (`tests/propagation/test_numerical.py`, `orekit` fixture):
  - **Metadata end-to-end:** a planets-on run records the token in the fixed slot
    (mirror `test_force_models_metadata_geo_and_tides_relativity` `:430`).
  - **The GEO effect pin** (contract deliverable 3 — the build plan decides it lives as
    a test, not an experiment; mirror the differential shape of
    `test_drag_lowers_semi_major_axis` `:611-635`): a GEO state, modest gravity
    (e.g. 8×8), sun+moon on, **drag and SRP off** (fast — no atmosphere queries, no
    spacecraft needed), `planets_third_body` on vs off over ~3 days; assert the final
    position divergence is **nonzero beyond integrator noise and small in absolute
    terms** — a wide band of order (0.1 m, 10 km), with the exact expected scale
    (meters-to-tens-of-meters from the ~1e-10 m/s² Venus+Jupiter tidal terms) computed
    and commented in-session.
  - **The LEO negligible pin** (cheap): the same differential at ~500 km over 1 day,
    asserting the divergence is far below the GEO one (order < 1 m). Keep it one tight
    case; drop it if suite time bites.

**Reuse:** the `_moon()` accessor pattern wholesale; the Sun/Moon `ThirdBodyAttraction`
wiring lines (`numerical.py:760-763`); the with/without differential test shape
(`test_numerical.py:611-635`).

**You provide:** nothing.

**You run:** the per-chunk git rhythm.

**Verify:** `conda run -n propygator pytest tests/propagation/test_force_models.py tests/core -v`
green with **no JVM**; `conda run -n propygator pytest tests/propagation -v` green; the
existing default-metadata tests (`test_numerical.py:400`) untouched and green — a
planets-off run's metadata is byte-identical to before;
`conda run -n propygator python -c "import propygator, jpype; print(jpype.isJVMStarted())"`
→ `False`.

---

## Chunk 2 — Earth-radiation runtime + tests (provisional constant)

**Goal:** `earth_radiation` wires `KnockeRediffusedForceModel` through the shipped SRP
optics inside a real `propagate()`; the metadata gates widen to three surface forces;
the resolution constant lands **provisional**, finalized by Chunk 3 (contract:
*Earth-radiation wiring*, *`_EARTH_RADIATION_ANGULAR_RESOLUTION`*, *Metadata*,
*Evidence deliverables* 4).

**Create / edit:**
- `src/propygator/propagation/force_models.py`:
  - `earth_radiation: bool = False` **inserted after** `srp` (`force_models.py:95`);
    `_serialize_force_models` gains the second **required** keyword, emitting the bare
    `earth_radiation` token after `srp` (`:65-66`); `_metadata_tokens` + both grammar
    docstrings updated (same seams as Chunk 1 — second pass over a now-familiar shape).
- `src/propygator/propagation/numerical.py`:
  - `_EARTH_RADIATION_ANGULAR_RESOLUTION` beside `_OCEAN_TIDE_DEGREE`
    (`numerical.py:111`), in radians, with a comment marking it **provisional pending
    the Chunk-3 benchmark** (suggested placeholder: 15° ≈ 0.2618 rad — conservative,
    cheap; the benchmark owns the final value).
  - `_build_earth_radiation_force(geometry, sun, box)` beside `_build_srp_force`
    (`:635-665`): sphere → its own `IsotropicRadiationSingleCoefficient(area_m2,
    reflectivity_coefficient)` (same asserts as `:657-661`; stateless, so a second
    instance is fine — hoist to share with SRP only if it falls out naturally); box →
    the shared `box`; the **4-arg** `KnockeRediffusedForceModel` constructor with
    `Constants.WGS84_EARTH_EQUATORIAL_RADIUS` (lazy import from
    `org.orekit.forces.radiation`).
  - `_add_perturbation_forces`: the box-build condition (`:754-758`) gains
    `or fm.earth_radiation`; the force is added **immediately after SRP** (`:768` —
    force-addition order = token order); `_WiredForces` field + return.
  - The metadata gates: `:1278` and `:1283` each gain `or wired.earth_radiation`, and
    **both "only drag/SRP consume mass/geometry" comments** (`:1276-1277`,
    `:1280-1282`) are updated — ERP is the third such force (contract: *Metadata* →
    Optional-key gates).
  - The `_serialize_force_models` call site (`:1239-1250`).
  - The `propagate_numerical` model-limitations docstring (`:939` block) gains the
    contract's Earth-radiation bullet **verbatim** (contract: *Docstrings*).
- **Tests** (`tests/propagation/test_force_models.py`): the same default/preset/grammar
  extensions as Chunk 1's, for `earth_radiation`.
- **Tests** (`tests/propagation/test_numerical.py`, `orekit` fixture):
  - **The widened `spacecraft` gate:** an ERP-only sphere run (drag off, SRP off,
    `earth_radiation=True`) records the `spacecraft` key and the `earth_radiation`
    token (mirror `test_spacecraft_metadata_present_when_surface_force_wired` `:473`).
  - **Box + ERP smoke through a real `propagate()`** (contract deliverable 4): a box
    with drag + SRP + ERP all on runs end-to-end — three forces driven off **one**
    shared `BoxAndSolarArraySpacecraft` — and records the `attitude` key (mirror
    `test_box_attitude_metadata_gated_on_surface_force` `:825`; add an ERP-only box
    case to pin the widened attitude gate).
  - **The ERP effect envelope** (differential, mirror `:611-635`): a high
    area-to-mass sphere (sail-like A/m ≈ 2 m²/kg) at ~500 km, drag off, SRP on,
    `earth_radiation` on vs off over ~6 h; assert the divergence is nonzero beyond
    integrator noise and **below the same-config SRP effect** (ERP is a fraction of
    SRP — the broad band; exact numbers computed and commented in-session). Direction
    sanity (mostly radially outward) lives in Chunk 3's study, not here — keep the test
    surface minimal.
  - **Regression:** preset metadata stays byte-identical (both fields off everywhere).

**Reuse:** `_build_srp_force`'s sphere/box split and asserts; the shared-box machinery;
the Chunk-1 seams (this chunk is deliberately the same pattern a second time); the test
shapes cited above.

**You provide:** nothing.

**You run:** the per-chunk git rhythm.

**Verify:** `conda run -n propygator pytest tests/propagation -v` green; a
both-fields-off run's metadata byte-identical; JVM-free import check green.

> ### ✅ Checkpoint — shipped surface built
> 1. Both fields construct/validate JVM-free, wire, and serialize per the contract.
> 2. `/code-review` + `/simplify` on the Chunks 1–2 diff.
> 3. Commit + push.

---

## Chunk 3 — ERP experiment: resolution benchmark + magnitude characterization

**Goal:** contract deliverables 1–2 — pick `_EARTH_RADIATION_ANGULAR_RESOLUTION` as the
coarsest converged rung and measure the honest ERP magnitudes, **through the shipped
stack**; finalize the constant (contract: *Evidence deliverables* 1–2,
*`_EARTH_RADIATION_ANGULAR_RESOLUTION`*).

**Create / edit** (all in a new `experiments/earth-radiation/`; reference-only, outside
`testpaths`, excluded from CI/lint; **ASCII-only prints**; wholly in the **conda env** —
every piece is shipped):
- **The resolution benchmark** (e.g. `erp_resolution_benchmark.py`): the reference sail
  — the ECEF study's scenario reused wholesale (`experiments/ecef-attitude-benefit/
  ecef_feather_benefit.py`: 1 m² / 0.5 kg thin-plate box at 500 km SSO,
  `InPlaneTracking(velocity_reference="ecef")`) — propagated at each rung of the ladder
  **90° → 45° → 30° → 15° → 10° → 5° → 2.5°**, finest rung as truth. Per rung, report
  the along-track ERP-effect error vs truth **and wall-clock time**; pick the
  **coarsest** rung whose error is well within the model's own uncertainty (a few % of
  the effect). Two cost containment defaults (confirm below): the sweep arc can be
  shorter than the characterization arc (~1–2 d suffices for convergence), and **drag
  off during the sweep** — the per-substep NRLMSISE-00 query would dominate wall-clock
  and cancels out of the resolution comparison anyway.
  - The rung override is
    `propygator.propagation.numerical._EARTH_RADIATION_ANGULAR_RESOLUTION = <value>`
    before each run — a deliberate, documented private-constant override, confined to
    this reference script and stated in its header (the reason the runtime landed
    first; see the plan's *Sequencing note*).
- **The magnitude characterization** (e.g. `erp_magnitude_study.py`, or the same
  driver): with/without `earth_radiation` at the **chosen** resolution, realistic
  config (drag + SRP on), multi-day arc, for **(a)** the reference sail and **(b)** the
  conventional bus (the 1000 kg / 1 m² default sphere). Report the ERP-vs-SRP
  acceleration fraction, the along-track divergence, and the direction sanity check
  (the differential acceleration is mostly radially outward). These are the numbers the
  docstring/CHANGELOG framing quotes.
- A figure (convergence + cost + divergence panels) + captured ASCII `results.txt` +
  folder `README.md` (the `experiments/ecef-attitude-benefit/` provenance pattern).
- **Finalize the constant:** set `_EARTH_RADIATION_ANGULAR_RESOLUTION` to the chosen
  value, drop "provisional", and cite this study in the comment (contract requirement).

**Reuse:** the ECEF benefit driver as the template (propagate-twice-and-diff, the
along-track metric, the sail scenario, the evidence-folder pattern);
`propagate_numerical` + `BoxFaceCd.default()` + `InPlaneTracking(...ecef)` (all
shipped).

**You provide:** confirmation of the sweep defaults (ladder, arc lengths, drag-off
sweep); **the Checkpoint-A confirmation of the chosen constant + quoted numbers.**

**You run:** `conda run -n propygator python experiments/earth-radiation/...`; eyeball
the figure; commit the evidence.

**Verify:** the sweep shows a clean convergence plateau (coarse rungs diverge, fine
rungs agree); the chosen rung's error ≪ the ERP effect; the full test suite stays green
at the final constant; the committed `results.txt` is ASCII-only.

> ### 🔎 Checkpoint A — constant + numbers confirmed (soft; not a STOP gate)
> 1. Maintainer confirms `_EARTH_RADIATION_ANGULAR_RESOLUTION` and the
>    sail/bus magnitude numbers the docs will quote.
> 2. If the benchmark surprises (no plateau, pathological cost), pause and reconcile
>    with the contract before Chunk 4.
> 3. Commit + push the evidence.

---

## Chunk 4 — Wrap-up: docs reconciliation, sweep, merge (no tag)

**Goal:** land the upgrade — the contract's *Supercessions* folded back, the findings
doc annotated, clean sweep, merge to `main`. **No version bump, no tag.**

**Create / edit / run:**
- Full local CI parity: `conda run -n propygator pytest` and
  `conda run -n propygator pre-commit run --all-files` green from repo root.
- `/code-review` + `/simplify` final pass across the whole diff.
- **Reconcile the docs** (the contract's *Supercessions* list — exactly those spots):
  - `features.md` §1.1 — the `ForceModelConfig` dataclass listing (`features.md:40-61`,
    both fields in grammar position); the preset table + prose (`:67-75`, the new
    False/False/False row + the extended off-in-all-presets sentence + both honesty
    caveats); the optional-physics-keys paragraph (`:330`, drag/SRP/ERP gates); the
    grammar paragraph + example (`:332-337`, the new fixed order); the
    model-limitations docstring block (`:447-468`, the Earth-radiation bullet).
  - `architecture.md` §13 — the resolved "Force inventory extended (v0.5.0)" bullet.
  - `docs/prospective-forces-and-progress-findings.md` — a short status note marking
    items 1–2 realized (superseded by the contract section / features.md §1.1); the doc
    **stays in `docs/`** as the progress-reporting (§4) reference.
  - `README.md` — the force-inventory mentions.
  - **Add the Outcome note** to the contract section's header blockquote (the
    ECEF/blitting precedent): shipped in full, the chosen constant, the headline
    numbers, Supercessions folded back.
  - **Leave `general-upgrades-1.md` in place** (alive for any remaining upgrades).
  - **You** update `CHANGELOG.md` `[Unreleased]` (per `docs/changelog-guidelines.md`)
    and refresh `CLAUDE.md` "Project state" + its "Forces:" line (the narrative
    artifacts are yours).
- **Merge:** `gh pr create` against `main`, CI green,
  `gh pr merge --squash --delete-branch` — **your call**. This plan then retires to
  `docs/history/`.

**You provide:** CHANGELOG + CLAUDE.md edits; the merge go-ahead.

**Verify:** full `pytest` + `pre-commit run --all-files` green; `pyproject.toml`
version **unchanged**; every *Supercessions* spot carried; `import propygator` stays
JVM-free.

---

## End-state verification (shipped → on `main`, untagged)

1. **Config:** both fields construct/validate JVM-free; all three presets carry both
   False; a both-off run's metadata (and `export_csv` header) is byte-identical to
   pre-upgrade.
2. **Planets:** seven `ThirdBodyAttraction`s wired in heliocentric order off the
   bundled DE ephemeris; `third_body:planets` in the fixed slot; the GEO effect pin
   holds (small, nonzero) and LEO is negligible.
3. **ERP:** `KnockeRediffusedForceModel` wired through the shipped SRP optics (sphere
   and box; the box drives three forces off one object); the constant is the
   benchmark-chosen value with a citing comment; the `earth_radiation` token in the
   fixed slot; the widened `spacecraft`/`attitude` gates pinned by tests.
4. **Evidence:** `experiments/earth-radiation/` committed — convergence plateau, chosen
   rung, wall-clock ladder, sail + bus magnitudes, direction sanity; the numbers quoted
   in docs come from this study.
5. **Docs:** the *Supercessions* map carried into `features.md` / `architecture.md` /
   `README.md`; the findings doc annotated (items 1–2 realized, §4 still live); the
   contract section carries its Outcome note; CHANGELOG + CLAUDE.md updated;
   **version unchanged / untagged**.
6. `conda run -n propygator python -c "import propygator, jpype; print(jpype.isJVMStarted())"` → `False`.

## Notes / deferred (not this plan)

- **Progress reporting** (findings doc §4) — deferred, unscoped; the findings doc stays
  its reference.
- **Per-planet toggles / an `extra_third_bodies` tuple, Pluto/barycenters, an
  `angular_resolution` config field, albedo-only/IR-only switches, per-face optical
  properties** — all contract *Out of scope*.
- **v0.5.0 tag** — the separate cross-upgrade step once all general upgrades land.
