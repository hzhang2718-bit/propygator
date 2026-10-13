# Build Plan — SESAM Accommodation

Working blueprint for `docs/history/sesam-accommodation.md`, which wins on conflict.
Status headers are the maintainer's. Archive to `docs/history/` at close.

**Precondition.** Part B of `docs/history/build-plan-earth-radiation.md` is closed
(shipped in `v0.8.2`, 2026-09-07), so this plan is unblocked.

**Do not recreate or update the conda env before Chunk 7.** The `jpype1=1.5.*` pin
holds a fresh env at the installed `orekit_jpype 13.1.4.0`, but a recreate
re-resolves other builds (Python patch, OpenJDK build), which would put two changes
in one `--verify` diff.

---

## Chunk 1 — Port SESAM into the generator - Done

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
and a transcription of ADBSat `accom_SESAM.m` over one shared MSIS case set, both
sides on ADBSat's constants and speed with anomalous oxygen zeroed, so contract §3
and the constant differences are out of the comparison (`_SPECIES` fixes AMU at
import, so the script patches it or the constants are passed in). Agreement below
1e-6 relative, or STOP and report.

**Record (2026-10-12).** PASS over 4480 MSIS states (α 0.0437–0.9999): max relative
difference 5.0e-7 on raw float32 pymsis rows, 8.4e-16 with rows cast to float64.

## Chunk 2 — Mirror into the experiment kernel - Done

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

## Chunk 3 — Regenerate both tables - Done

**Goal.** New `.npz` at the shipped seed (`20260611`), conditions (80) and axes.

**Create/Edit.** Run both generators with `--force`. Metadata drops `anchor_alpha`
and records the SESAM constants and the citation; `accommodation` restates the model.

**Reuse.** The throwaway venv (`docs/experiments_venv.md`) — `pymsis` + `scipy` are
not in the conda env.

**Verify.** Every contract §6 invariant, cell by cell. Then **log** the grid deltas
into the chunk record: mean / median / p95 / min / max for the sphere grid, the box
θ = 0 slice and the box θ = 90 slice. The θ = 90 slice must hold contract §6's
≤ 1e-15 relative bound.

**Run order.** 5a (venv drivers) → 4 → 3 → 5b, so the generator metadata records
the re-measured cross-validation and collapse figures.

**Record (2026-10-12).** Relative grid deltas vs the tables at `00d40f8`; axes unchanged.

| grid (650 cells) | mean | median | p95 | min | max |
|---|---:|---:|---:|---:|---:|
| sphere | −3.81 % | −3.58 % | −0.78 % | −10.33 % | −0.30 % |
| box θ = 0 | −5.12 % | −4.83 % | −1.15 % | −13.84 % | −0.44 % |
| box θ = 90 | −2.7e-18 | 0 | 0 | −2.3e-16 | 0 |

§6 all PASS: α > 0 over 4480 sampled states (min 0.0437); new α ≥ old everywhere
(min gain 7.1e-4); every sphere cell and all 20,800 windward box cells decrease;
θ = 90 max 2.3e-16 relative; box grid ≥ 0, leeward max |Δ| 6.8e-4; floored cells
11,325 → 10,937, pre-floor min −5.77e-4 → −5.43e-4.

## Chunk 4 — Re-measure the cross-validations - Done

**Goal.** Both generators' `CROSS_VALIDATION_MAX_REL_PCT` describe the shipped tables.

**Create/Edit.** Run `cross_validate_models.py` and `cross_validate_box_face.py`;
update the two constants and the two `_results.txt`.

**Verify.** Both agree ≪ 1 %; each constant equals its results file.

## Chunk 5 — Regenerate the Tier A / Tier B evidence - Done

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

## Chunk 6 — Re-run the ECEF feather benefit - Done

**Goal.** `experiments/ecef-attitude-benefit/` matches the shipped table.

**Create/Edit.** Re-run `ecef_feather_benefit.py`; refresh its `_results.txt` and README.

**Verify.** Measure, do not predict: both legs fly the same table, so the ratio may
barely move while the absolute along-track figure does. Whatever moves, the
`features.md` §1.1 Tier B paragraph must be restated from this run.
Restate the same paragraph's Sun-pointing "< 1 %" claim from
`cd_box_benefit_study_results.txt` (now 1.12 % final).

## Chunk 7 — Regenerate the two studies' α-dependent evidence - Done

**Goal.** `run_all.py --verify` is green in both studies (contract §8).

**Create/Edit.** In the conda env, regenerate only the groups whose drivers load a
table:

- `experiments/extended-validation/` — `--only noise`, `drag_01..10`,
  `swarm_01..10`, then `drag_summary` (~9.7 h, from the committed wall-time lines);
  then `tle_01..10`, `tle_summary`, `tle_bench` (~19 min; their `state_sphere` /
  `state_box` rows fly the tables).
- `experiments/real-world-validation/` — `--only drag,state-path` (~1 h).

**Reuse.** Each study's `run_all.py`; per-group `--only` is its documented default.

**Do not touch.** extended-validation `screen`; real-world-validation `lageos`,
`fit`, `sweep` — their drivers reference no table. The playbook's recipe stands: the
bench verdicts never read the `state_*` rows.

**Verify.** `--verify` clean on every regenerated group and still clean on the
untouched ones, apart from extended-validation's unmasked `[versions]` stamp line.
Read the ten-window sphere-vs-`Cd = 2.3` outcome against contract §8's
pre-registered reading **before** writing any document.

**Record (2026-10-13).** Every regenerated file moved only table-fed rows; baseline
`--verify` clean on the untouched groups (`screen` bar its `[versions]` line), spot-check
`--verify` clean on rwv `drag` and extval `tle_01` at `42ea058`.

- §8 trigger **not fired**: the sphere still beats `Cd = 2.3` on day 1 of every storm
  window (`storm_2026_01` day-1 ratio 0.54 → 0.30), but its lead narrowed in
  `moderate_2022_04`, `storm_2024_08`, `intense_2024_11`, `storm_2025_05`,
  `moderate_2025_07` (day-1 ratio ~0.4–0.7 → 0.71–0.86).
- Same split everywhere: sphere better in low windows, worse once drag is active; box
  better in every window and leg.
- Checkpoint B re-read unchanged — the scaled box still collapses onto Run 3 in all
  four rwv windows.
- Table-noise still 12/12 HIT.
- Swarm `window_03` wall-time lines read ~7.5 h (machine sleep); numbers unaffected.

## Chunk 8 — Tests - Done

**Goal.** Suite green, pins honest.

**Verify.** `pre-commit run --all-files`, then `conda run -n propygator pytest`.
Watch `SPHERE_RATIO_BOUND` in `tests/propagation/test_extended_validation_drag.py`
(the pin most likely to move — it encodes the §8 finding, not just a band),
`RMS_BAND_M` in `tests/propagation/test_extended_validation_table_noise.py` (a lower
Cd raises the residual toward its 400 m ceiling), and `FACE_SUM_BAND_M2` in
`tests/propagation/test_real_world_gracefo.py`. `test_numerical.py` (1163, 1294) and
`test_public_surface.py` (137) are structural — confirm rather than re-pin. Re-pin
only against Chunk 7's measured values, keeping the repo's
measured-times-generous-margin policy. Both bounds are expected to hold; their
"measured" comments (34.7 m / 0.544; 227.7 / 233.0 m) are stale and need re-measuring
at the tests' 600 s cadence.

## Chunk 9 — Documents - Done

**Goal.** No document still claims the α = 0.90 anchor, and every table-derived
number is Chunk 7's.

**Create/Edit.**
- `docs/features.md` — the §1.1 "Where the table comes from" provenance and the
  Tier B `BoxFaceCd` paragraph, both of which name the anchored α; note here that
  the addendum's "α = 0.90 reconciled in *both* `cd_core.calibrate_K` and
  `ANCHOR_ALPHA`" requirement is retired by Chunk 1 deleting both. **`docs/history/`
  is not edited** — the archive records what was true then.
- `docs/architecture.md` — the §5 cross-validation figure (0.0191 %).
- `src/propygator/propagation/spacecraft.py` — the `BoxFaceCd.default()` docstring
  names the anchor; a shipped public docstring, so it is not optional. No API or
  behaviour change.
- `docs/validation-findings.md` — the table-derived numbers in §1–8 and §9–17,
  restated from Chunk 7 (contract §8), including §14's state-path rows and the
  Checkpoint B "absorbable scale" reading; the sphere-leads headline stands but with
  Chunk 7's narrower margins, and the active/storm sphere Cd (2.49 / 2.37) now sits
  below the withdrawn "DSMC band" floor that `run_gracefo.py` still prints.
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
- `scripts/generate_box_face_cd_table.py` — the "Leeward floor" docstring counts,
  restated from Chunk 3's `leeward_floor` metadata.
- `CLAUDE.md` as-built notes.

**Verify.** Two sweeps from the repo root in Git Bash. The second doubles as this
chunk's work list: run it first, then again at the end.

1. Anchor sweep — returns nothing stale:
   ```
   grep -rnE "ANCHOR_ALPHA|anchor_alpha|calibrate_K|Langmuir[- ]K\b|SESAM-style|anchored .*0\.90|(alpha|α) ?= ?0\.90|α anchor" \
     README.md CLAUDE.md docs/ data/ notebooks/ scripts/ src/ tests/ experiments/ \
     --include=*.md --include=*.py --include=*.ipynb --include=*.txt \
     --exclude-dir=history --exclude-dir=.venv-experiments \
     --exclude=sesam-accommodation.md --exclude=build-plan-sesam-accommodation.md
   ```
2. Moved-number sweep — numbers that left any results file, plus their roundings,
   searched in the prose docs; every final hit is a coincidence recorded in the
   chunk record (on the `v0.8.2` diff it caught all six number lines that release
   edited):
   ```
   git diff -U0 main -- 'experiments/*results*.txt' > /tmp/d.txt
   grep '^-[^-]' /tmp/d.txt | grep -oE '[0-9]+\.[0-9]+' | sort -u > /tmp/old.txt
   grep '^+[^+]' /tmp/d.txt | grep -oE '[0-9]+\.[0-9]+' | sort -u > /tmp/new.txt
   comm -23 /tmp/old.txt /tmp/new.txt \
     | awk -F. '{for(d=length($2);d>=1;d--){t=sprintf("%.*f",d,$0); if(length(t)>=4) print t}}' \
     | sort -u > /tmp/moved.txt
   [ -s /tmp/moved.txt ] && git grep -nwF -f /tmp/moved.txt -- README.md CLAUDE.md data/README.md docs/features.md docs/architecture.md \
     docs/validation-findings.md docs/tle-fitting-playbook-updated.md \
     'notebooks/0[07]_*.ipynb' 'experiments/*README.md'
   ```

## Chunk 10 — Close

**Goal.** Plan and contract archived.

**Create/Edit.** Move both documents to `docs/history/`, and repoint every live
`docs/sesam-accommodation.md` reference (`git grep`) to the archived path.

**Verify.** CHANGELOG entry, version bump and release are the maintainer's. Minor
bump (`v0.9.0`), not a `v0.7.3`-style patch: every default-table drag value moves
(Chunk 3 records by how much).
