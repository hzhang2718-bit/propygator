# Build Plan — SESAM Accommodation

Working blueprint for `docs/sesam-accommodation.md`, which wins on conflict.
Status headers are the maintainer's. Archive to `docs/history/` at close.

**Precondition.** Part B of `docs/build-plan-earth-radiation.md` is closed. Chunk 3
below moves Run 5 of the real-world-validation `drag` group far past the
below-printed-precision leeward-floor artifact that Part B exists to reconcile, so
closing Part B afterwards conflates two divergences of different character in one
`--verify` diff.

---

## Chunk 1 — Port SESAM into the generator

**Goal.** `generate_sphere_cd_table` computes α by SESAM; the anchor machinery is gone.

**Create/Edit.** Replace `_accommodation(n_atomic_O, temperature, langmuir_K)` with
a form taking the MSIS rows and the relative speed (SESAM needs `m_bar` and `V`,
neither reachable from the current arguments). Delete `_calibrate_accommodation_K`
and `ANCHOR_ALPHA`. Update both call sites — `generate_sphere_cd_table.generate`
and `generate_box_face_cd_table.generate`, which calls `gen._accommodation`. Clamp
the two `exp` calls per contract §2.

**Reuse.** `_COL`, `_SPECIES`, `_relative_speed`, `_sphere_cd_species`'s incident
terms for `Cd_sphere(s)` in `P_O`.

**Verify — STOP gate.** A throwaway parity script drives the new `_accommodation`
and a direct transcription of ADBSat `accom_SESAM.m` over one shared MSIS case set,
using ADBSat's speed convention so contract §3 is out of the comparison. Agreement
below 1e-9 relative, or STOP and report.

## Chunk 2 — Mirror into the experiment kernel

**Goal.** The generator and the experiment kernel carry one α, so the
cross-validators keep comparing like with like.

**Create/Edit.** Replace `alpha_sesam` and `calibrate_K` in
`experiments/drag-coefficient-verification/cd_core.py`; update the call sites in
`cd_sphere_experiment.py`, `cd_box_experiment.py`, `cd_box.py`, `cd_box_faces.py`.

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

**Create/Edit.** Re-run `cd_sphere_experiment.py`, `cd_box_experiment.py`,
`cd_box_incidence_convergence.py`, `cd_box_benefit_estimate.py`,
`cd_box_benefit_study_edgeon.py`; refresh their `_results.txt`, PNGs and the leg README.

**Reuse.** The throwaway venv; each driver's existing verdict structure.

**Verify.** Every verdict is restated from the new run, never carried over.
`cd_box_benefit_study.py` and `kn_floor*` carry no α dependence (`kn_floor.py`
imports only `SPECIES`) — confirm that by inspection rather than assuming it.

## Chunk 6 — Re-run the ECEF feather benefit

**Goal.** `experiments/ecef-attitude-benefit/` matches the shipped table.

**Create/Edit.** Re-run `ecef_feather_benefit.py`; refresh its `_results.txt` and README.

**Verify.** Measure, do not predict: both legs fly the same table, so the ratio may
barely move while the absolute along-track figure does. Whatever moves, the
`features.md` §1.2 Tier B paragraph must be restated from this run.

## Chunk 7 — Tests

**Goal.** Suite green, pins honest.

**Verify.** `pre-commit run --all-files`, then `conda run -n propygator pytest`.
Watch `FACE_SUM_BAND_M2` in `tests/propagation/test_real_world_gracefo.py` (the
band's lower edge is the tightest pin against this change) and `SPHERE_RATIO_BOUND`
in `tests/propagation/test_extended_validation_drag.py`. Re-pin only against
measured values, keeping the repo's measured-times-generous-margin policy.

## Chunk 8 — Documents

**Goal.** No document still claims the α = 0.90 anchor.

**Create/Edit.**
- `docs/features.md` — the §1.1 "Where the table comes from" provenance and the
  Tier B `BoxFaceCd` paragraph, both of which name the anchored α.
- `docs/history/general-upgrades-1.md` and the Feature 1.1 drag-validity addendum —
  **Supercession notes, not rewrites**; the addendum's "α = 0.90 in *both*
  `cd_core.calibrate_K` and `ANCHOR_ALPHA`, already reconciled" requirement is
  retired by Chunk 1 deleting both.
- `experiments/real-world-validation/README.md` — frozen-evidence conflict note
  replacing the "Expected — do not regenerate" bullet (contract §8).
- `experiments/extended-validation/README.md` — the same note.
- `experiments/drag-coefficient-verification/README.md` — regenerated numbers.
- `CLAUDE.md` as-built notes.

**Verify.** `grep -rn "ANCHOR_ALPHA\|anchored .* 0\.90\|alpha = 0\.90" docs/ experiments/ src/ scripts/ tests/`
returns nothing stale.

## Chunk 9 — Close

**Goal.** Plan and contract archived.

**Create/Edit.** Move both documents to `docs/history/`.

**Verify.** CHANGELOG entry, version bump and release are the maintainer's;
`v0.7.3` is the precedent for a table-regeneration patch.
