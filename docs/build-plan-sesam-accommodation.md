# Build Plan — SESAM Accommodation

Working blueprint for `docs/sesam-accommodation.md`, which wins on conflict.
Status headers are the maintainer's. Archive to `docs/history/` at close.

**Precondition.** Part B of `docs/history/build-plan-earth-radiation.md` is closed
(shipped in `v0.8.2`, 2026-09-07), so this plan is unblocked. Chunk 3
below moves Run 5 of the real-world-validation `drag` group far past the
below-printed-precision leeward-floor artifact that Part B exists to reconcile, so
closing Part B afterwards conflates two divergences of different character in one
`--verify` diff.

**Do not recreate or update the conda env before Chunk 7.** The installed
`orekit_jpype` is `13.1.4.0` and a fresh env lands `13.1.7.1`, which would put two
changes in one `--verify` diff.

---

## Chunk 1 — Port SESAM into the generator

**Goal.** `generate_sphere_cd_table` computes α by SESAM; the anchor machinery is gone.

**Create/Edit.** Replace `_accommodation(n_atomic_O, temperature, langmuir_K)` with
a form taking the MSIS rows and the relative speed (SESAM needs `m_bar` and `V`,
neither reachable from the current arguments). Delete `_calibrate_accommodation_K`
and `ANCHOR_ALPHA`. Update both call sites — `generate_sphere_cd_table.generate`
and `generate_box_face_cd_table.generate`, which calls `gen._accommodation`.
Evaluate `s_o`'s second numerator term in contract §2's exact form.

**Reuse.** `_COL`, `_SPECIES`, `_relative_speed`, `_sphere_cd_species`'s incident
terms for `Cd_sphere(s)` in `P_O`.

**Verify — STOP gate.** A throwaway parity script drives the new `_accommodation`
and a transcription of ADBSat `accom_SESAM.m` over one shared MSIS case set, the
transcription driven with ADBSat's own constants, species set and speed convention
so contract §3 and the constant differences are out of the comparison. Agreement
below 1e-6 relative, or STOP and report.

## Chunk 2 — Mirror into the experiment kernel

**Goal.** The generator and the experiment kernel carry one α, so the
cross-validators keep comparing like with like.

**Create/Edit.** Replace `alpha_sesam` and `calibrate_K` in
`experiments/drag-coefficient-verification/cd_core.py`; update the call sites in
`cd_sphere_experiment.py`, `cd_box_experiment.py`, `cd_box_benefit_estimate.py`,
`cd_box_incidence_convergence.py`, `cross_validate_models.py`,
`cross_validate_box_face.py`. `cd_box.py` and `cd_box_faces.py` take α as an
argument and need no edit.

**Reuse.** Chunk 1's implementation, transcribed — the two stay independent
reconstructions by design.

**Verify.** Generator α and kernel α agree to machine precision on a shared case set.

## Chunk 3 — Regenerate both tables

**Goal.** New `.npz` at the shipped seed (`20260611`), conditions (80) and axes.

**Create/Edit.** Run both generators with `--force`. Metadata drops `anchor_alpha`
and records the SESAM constants and the citation; `accommodation` restates the model.

**Reuse.** The throwaway venv (`docs/experiments_venv.md`) — `pymsis` + `scipy` are
not in the conda env.

**Verify.** Every contract §6 invariant, cell by cell. Then **log** the grid deltas
into the chunk record: mean / median / p95 / min / max for the sphere grid, the box
θ = 0 slice and the box θ = 90 slice. The θ = 90 slice must be bit-identical.

## Chunk 4 — Re-measure the cross-validations

**Goal.** Both generators' `CROSS_VALIDATION_MAX_REL_PCT` describe the shipped tables.

**Create/Edit.** Run `cross_validate_models.py` and `cross_validate_box_face.py`;
update the two constants and the two `_results.txt`.

**Verify.** Both agree ≪ 1 %; each constant equals its results file.

## Chunk 5 — Regenerate the Tier A / Tier B evidence

**Goal.** `experiments/drag-coefficient-verification/` matches the shipped tables.

**Create/Edit.** Re-run, in the throwaway venv, `cd_sphere_experiment.py`,
`cd_box_experiment.py`, `cd_box_incidence_convergence.py`,
`cd_box_benefit_estimate.py`; then, **in the conda env** (both import propygator and
need the JVM), `cd_box_benefit_study.py` and `cd_box_benefit_study_edgeon.py`.
Refresh their `_results.txt`, PNGs and the leg README.

**Reuse.** Each driver's existing verdict structure.

**Verify.** Every verdict is restated from the new run, never carried over.
`cd_box_benefit_study.py` reads the regenerated table through `BoxFaceCd.default()`,
so its Tier B GO-with-caveat verdict is re-derived, not carried. Only `kn_floor*`
carries no α dependence (`kn_floor.py` imports only `SPECIES`) — confirm that by
inspection rather than assuming it.

## Chunk 6 — Re-run the ECEF feather benefit

**Goal.** `experiments/ecef-attitude-benefit/` matches the shipped table.

**Create/Edit.** Re-run `ecef_feather_benefit.py`; refresh its `_results.txt` and README.

**Verify.** Measure, do not predict: both legs fly the same table, so the ratio may
barely move while the absolute along-track figure does. Whatever moves, the
`features.md` §1.1 Tier B paragraph must be restated from this run.

## Chunk 7 — Regenerate the two studies' α-dependent evidence

**Goal.** `run_all.py --verify` is green in both studies (contract §8).

**Create/Edit.** In the conda env, regenerate only the groups whose drivers load a
table:

- `experiments/extended-validation/` — `--only noise`, `drag_01..10`,
  `swarm_01..10`, then `drag_summary` (~9.7 h, from the committed wall-time lines).
- `experiments/real-world-validation/` — `--only drag,state-path` (~1 h).

**Reuse.** Each study's `run_all.py`; per-group `--only` is its documented default.

**Do not touch.** extended-validation `screen`, `tle_01..10`, `tle_summary`,
`tle_bench`; real-world-validation `lageos`, `fit`, `sweep` — their drivers
reference no table, so Part 3's TLE evidence and the playbook stand unchanged.

**Verify.** `--verify` clean on every regenerated group and still clean on the
untouched ones. Read the ten-window sphere-vs-`Cd = 2.3` outcome against contract
§8's pre-registered reading **before** writing any document.

## Chunk 8 — Tests

**Goal.** Suite green, pins honest.

**Verify.** `pre-commit run --all-files`, then `conda run -n propygator pytest`.
Watch `SPHERE_RATIO_BOUND` in `tests/propagation/test_extended_validation_drag.py`
(the pin most likely to move — it encodes the §8 finding, not just a band),
`RMS_BAND_M` in `tests/propagation/test_extended_validation_table_noise.py` (a lower
Cd raises the residual toward its 400 m ceiling), and `FACE_SUM_BAND_M2` in
`tests/propagation/test_real_world_gracefo.py`. `test_numerical.py` (1163, 1294) and
`test_public_surface.py` (137) are structural — confirm rather than re-pin. Re-pin
only against Chunk 7's measured values, keeping the repo's
measured-times-generous-margin policy.

## Chunk 9 — Documents

**Goal.** No document still claims the α = 0.90 anchor, and every table-derived
number is Chunk 7's.

**Create/Edit.**
- `docs/features.md` — the §1.1 "Where the table comes from" provenance and the
  Tier B `BoxFaceCd` paragraph, both of which name the anchored α; note here that
  the addendum's "α = 0.90 reconciled in *both* `cd_core.calibrate_K` and
  `ANCHOR_ALPHA`" requirement is retired by Chunk 1 deleting both. **`docs/history/`
  is not edited** — the archive records what was true then.
- `src/propygator/propagation/spacecraft.py` — the `BoxFaceCd.default()` docstring
  names the anchor; a shipped public docstring, so it is not optional. No API or
  behaviour change.
- `docs/validation-findings.md` — the table-derived numbers in §1–8 and §9–17,
  restated from Chunk 7 (contract §8).
- `experiments/real-world-validation/README.md` — retire the "Expected — do not
  regenerate" bullet and mark the `v0.8.2` leeward-floor `--verify` narrative
  historical (contract §8).
- `experiments/extended-validation/README.md`, `results_drag_summary.txt` prose —
  Chunk 7's numbers.
- `experiments/drag-coefficient-verification/README.md` — regenerated numbers.
- `README.md` (root) and `data/README.md` — both carry the anchor or the
  sphere-vs-`Cd = 2.3` headline.
- `notebooks/00_showcase.ipynb` and `07_tle_fitting.ipynb` §9 — hand-transcribed
  validation numbers, updated by hand per CLAUDE.md.
- `CLAUDE.md` as-built notes.

**Verify.** From the repo root,
`grep -rn "ANCHOR_ALPHA\|anchored .* 0\.90\|alpha = 0\.90\|SESAM α\|α anchor" README.md CLAUDE.md docs/ data/ notebooks/ scripts/ src/ tests/ experiments/ --include=*.md --include=*.py --include=*.ipynb --include=*.txt`
returns nothing stale.

## Chunk 10 — Close

**Goal.** Plan and contract archived.

**Create/Edit.** Move both documents to `docs/history/`.

**Verify.** CHANGELOG entry, version bump and release are the maintainer's;
`v0.7.3` is the precedent for a table-regeneration patch.
