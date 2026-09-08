# SESAM Accommodation — Contract

**Status:** proposed, not built. Binding for the energy-accommodation model shared
by `data/sphere_cd_default.npz` and `data/box_face_cd_default.npz`. Wins over
`docs/build-plan-sesam-accommodation.md` on conflict; `features.md` and
`architecture.md` win over both. Archive to `docs/history/` at close.

## 1. Defect

`generate_sphere_cd_table._accommodation` implements SESAM's atomic-oxygen Langmuir
coverage term alone and uses the coverage *as* α, so α → 0 as coverage falls. SESAM
blends that coverage against a non-zero clean-surface coefficient; the α → 0 limit
is unphysical and inflates Cd on the windward half wherever coverage is incomplete.

## 2. Model (normative)

Adopt SESAM as published — Pilinski, Argrow, Palo & Bowman, *J. Spacecraft &
Rockets* 50(3), 556–571 (2013) — in the form ADBSat ships as
`toolbox/accom_models/accom_SESAM.m` with `accom_goodman.m`:

```
alpha       = (1 - theta) * alpha_clean + theta
theta       = K_L * P_O / (1 + K_L * P_O)
K_L         = s_o * K_Lo + K_Lf                          [torr^-1]
P_O         = 0.5 * rho_O * V^2 * Cd_sphere(s) / (101325/760) [torr]
alpha_clean = K_s * mu / (1 + mu)^2
mu          = m_bar / m_s
E_r         = 0.5 * m_O * V^2
zeta        = exp(2*sqrt(E_b*E_r) / (k*T_ab))
s_o         = ( sqrt(pi*k*T_ab*E_r) * (erf((sqrt(E_b)-sqrt(E_r))/sqrt(k*T_ab))
                                       + erf(sqrt(E_r/(k*T_ab))))
              + k*T_ab*exp(-(E_b+E_r)/(k*T_ab)) * (exp(E_b/(k*T_ab)) - zeta) )
            / ( sqrt(pi*k*T_ab*E_r) * (erf(sqrt(E_r/(k*T_ab))) + 1)
              + k*T_ab*exp(-E_r/(k*T_ab)) )
```

`Cd_sphere(s)` is the existing incident-only sphere form already in
`_sphere_cd_species`; `m_bar` is the number-weighted mean molecular mass over the
same seven `_SPECIES`, anomalous oxygen excluded (ADBSat `environment.m`'s
default); `s` is the bulk speed ratio on `m_bar`.

| symbol | value |
|---|---|
| `K_s` substrate coefficient | 2.4 |
| `m_s` surface molecule mass | 65 amu |
| `E_b` adsorption energy | 5.7 eV |
| `T_ab` transition temperature | 93.31 K |
| `K_Lo` / `K_Lf` | 5e6 / 3e4 torr^-1 |

`s_o`'s second numerator term underflows to `0` below ~4.15 km/s and to `NaN`
above it, so evaluate it as the exact equivalent `k*T_ab * (exp(-E_r/(k*T_ab)) -
exp(-(sqrt(E_b)-sqrt(E_r))^2/(k*T_ab)))`.

The model has no free parameter, so `ANCHOR_ALPHA` and
`_calibrate_accommodation_K` are deleted rather than retuned.

SESAM is published for spherical and randomly tumbling objects; applying its α per
flat face at arbitrary incidence follows ADBSat and is an extension of the paper.

## 3. Deliberate deviation from ADBSat

SESAM is driven by propygator's `_relative_speed` (co-rotation subtracted), not
ADBSat's `sqrt(mu/(R_E+h))`. Recorded so the port is not later read as a
transcription error.

## 4. What does not change

Both closed forms; the Moe/Mehta 2/3 reflected-velocity branch; the per-species
mass-flux weighting and its seven-species set; `_relative_speed`; the leeward
floor at 0.0; every axis, grid extent and regrid step; the public API. No
signature in `features.md` §1.1 is touched — this changes table *values*, not the
surface that serves them.

## 5. Deliverables

1. `_accommodation` replaced in `scripts/generate_sphere_cd_table.py`; anchor
   machinery deleted; both call sites updated (the box generator calls it too).
2. The same model mirrored in `experiments/drag-coefficient-verification/cd_core.py`.
3. Both `.npz` regenerated at the shipped seed and axes.
4. Both generators' `CROSS_VALIDATION_MAX_REL_PCT` re-measured.
5. The α-dependent `drag-coefficient-verification` and `ecef-attitude-benefit`
   evidence regenerated.
6. Both validation studies' α-dependent `run_all.py` groups regenerated to a green
   `--verify` (§8).
7. Documents updated; no file still claims the α = 0.90 anchor.

## 6. Invariants (analytic — check cell by cell)

- α is strictly positive everywhere, and weakly greater than today's at every
  sampled state.
- **Every θ = 90° box entry is bit-identical.** The tangential-shear term carries
  no re-emission and so no α; a non-zero delta there means the port reached the
  shear path.
- Windward box entries (θ < 90°) and all sphere entries decrease.
- Leeward box entries stay ≥ 0.
- Both grids stay inside the bands the shipped tests assert.

No expected magnitudes are recorded here — none is a logged run yet. The build
plan's Chunk 3 measures and records them.

## 7. Acceptance

- The port reproduces a transcription of ADBSat `accom_SESAM.m` α to better than
  1e-6 relative on a shared case set, the transcription driven with ADBSat's own
  constants, species set and speed convention so §3 and the constant differences
  are not in the comparison, and carrying §2's exact `s_o` term because the
  published one cannot be evaluated in double precision.
- Generator and experiment-kernel α agree to machine precision.
- Both cross-validators pass at ≪ 1 %.
- `pre-commit run --all-files` and the full suite green.

## 8. Study evidence — regenerated, not frozen

Leaving `run_all.py --verify` red in two studies is not an acceptable end state, so
this is an authorized recomputation of frozen evidence — the second, after `v0.8.2`.
Only the groups whose drivers load a table are re-run:

| study | regenerate | leave untouched |
|---|---|---|
| extended-validation | `noise`, `drag_01..10`, `swarm_01..10`, `drag_summary` | `screen`, `tle_01..10`, `tle_summary`, `tle_bench` |
| real-world-validation | `drag`, `state-path` | `lageos`, `fit`, `sweep` |

The untouched groups' drivers reference no table — in `run_fit_vs_catalog.py` the
tables are reached only inside `_run_state_path`. Within a regenerated file only the
a-priori-table rows move; the drag-off and fitted-Cd rows carry no α. The
table-derived numbers in `docs/validation-findings.md` §1–8 and §9–17 are restated
from the re-run, the "Expected — do not regenerate" bullet in
`experiments/real-world-validation/README.md` is retired, and that README's `v0.8.2`
leeward-floor `--verify` narrative becomes historical.

**Pre-registered reading.** If the corrected sphere table no longer beats a naive
`Cd = 2.3` in the storm window, that is a finding, not a regression: restate §9–17,
both experiment READMEs, the root `README.md` and `notebooks/00_showcase.ipynb`, and
re-pin `SPHERE_RATIO_BOUND` to the measured relationship. Recorded before the run so
the outcome is not chosen after seeing it.

## 9. Out of scope

The reflected-velocity branch (Moe/Mehta 2/3 vs Koppenwallner 1/2 — both
published; ADBSat carries ours commented out as "Mehta DRIA Flat Plate");
anomalous oxygen in the weighting; the lift/side-force component the runtime
discards; any axis, geometry or API change.

## 10. Provenance

ADBSat (GPLv3, University of Manchester), `github.com/nhcrisp/ADBSat` @ `master`,
read 2026-09-07. Files consulted: `fmf_eq/coeff_DRIA.m`, `fmf_eq/coeff_sentman.m`,
`calc/calc_coeff.m`, `calc/environment.m`, `calc/ADBSatConstants.m`,
`accom_models/accom_SESAM.m`, `accom_models/accom_goodman.m`.
