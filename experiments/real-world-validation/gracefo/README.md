# GRACE-FO vs. GNV1B reduced-dynamic orbits (real-world validation, Chunks 2 + 2b)

Evidence for `docs/build-plan-real-world-validation.md` Chunks 2 and 2b — the
**drag-stack** diagnostic. After the LAGEOS-2 leg established the conservative-force
floor (Chunks 0–1), this leg measures the full drag pipeline (NRLMSISE-00 + real CSSI
space weather + the shared `DragSensitive` proxy) against a real drag-perturbed LEO
orbit: GRACE-FO 1 at ~500 km, with cm-level GPS-determined truth from the mission's
Level-1B GPS-navigation product. The residual is decomposed into "pipeline" vs.
"density model" *by construction* — a drag-off / drag-on / fitted-Cd trio (Chunk 2,
Runs 1–3), then the two **no-fit a-priori Cd-table runs** (Chunk 2b, Runs 4–5:
`VariableCd.sphere_default` and the per-face `BoxFaceCd.default` flown wind-aligned)
— run in a solar-quiet and a solar-active week so the quiet-vs-active contrast is
visible in the fitted Cd and the residual ratio. **Checkpoint B (pinnable bounds +
the `box_and_panels` geometry decision) is called on these numbers; Runs 4 & 5 are
the direct geometry evidence.**

**Reference-only.** Not shipped, not in CI, outside `testpaths`. Everything is
shipped propygator + the pinned Orekit 13.1.x, so it runs in the **propygator conda
env** (starts the JVM, needs orekit-data) — the study's one locked departure from
`docs/experiments_venv.md`:

```
cd experiments/real-world-validation/gracefo
conda run -n propygator python run_gracefo.py quiet_2019  >  results.txt
conda run -n propygator python run_gracefo.py active_2023 >> results.txt
```

`--parse-only` stops before the JVM-touching steps (parser + grid checks only).
Stdout is ASCII-only (cp1252 redirect); the Cd-fit progress goes to stderr.

## Truth data (not committed)

`experiments/real-world-validation/data/gracefo/{quiet_2019,active_2023}/` — the
PO.DAAC **GRACE-FO Level-1B RL04** daily tarballs
(`gracefo_1B_<date>_RL04.ascii.noLRI.tgz`, dataset
[`GRACEFO_L1B_ASCII_GRAV_JPL_RL04`](https://podaac.jpl.nasa.gov/dataset/GRACEFO_L1B_ASCII_GRAV_JPL_RL04),
DOI [10.5067/GFJPL-L1B04](https://doi.org/10.5067/GFJPL-L1B04)), downloaded by the
maintainer with a NASA Earthdata login. `gnv1b.py` reads the one `GNV1B` member it
needs straight out of each tarball. Raw truth files are **never committed** (the
`data/` directory is gitignored); committed evidence is this README + `results.txt`.

Two 10-day windows are on disk; the driver loads the first 3 days of each (a 1-day
run/fit arc plus the maneuver-screen span):

- **`quiet_2019`** — 2019-11-14 → 23, deep solar minimum
- **`active_2023`** — 2023-12-20 → 29, solar maximum, screened storm-free

Product facts (read from the GNV1B header / data by `gnv1b.py`, echoed in
`results.txt`):

- 1 Hz `GNV1B` GPS-navigation states, satellite **C = GRACE-FO 1 (GRACE C, NORAD
  43476)**, product version 04
- `coord_ref` **E** = Earth-Centered Earth-Fixed → an ITRF realization
  (`Frame.ITRF`); position/velocity are already SI (m, m/s) in the product
- `gps_time` = continuous seconds past the GPS epoch 2000-01-01 12:00:00 GPS; the
  parser converts leap-second-free via the locked **GPS + 19 s = TAI** route (a base
  `Epoch.from_iso("2000-01-01T12:00:19", TimeScale.TAI).shifted_by(gps_time)`), so
  the GRACE-FO leg exercises the parser's GPS→TAI path the LAGEOS UTC file did not
- quality flags (`qualflg`) honored — a non-zero flag drops the record (none in
  these windows); 1 Hz subsampled to 60 s on the `gps_time` grid so kept epochs land
  exactly on `t0 + k·60 s` (the exact-grid diff)

## Spacecraft parameters (sphere-equivalent; re-confirmed 2026-07-12)

The named deferral (Checkpoint B) is the `box_and_panels` geometry-fidelity
upgrade; this leg starts with a **sphere-equivalent frontal area**, and the
scalar-Cd fit (Run 3) is the real diagnostic — it absorbs the Cd·A/m product, so the
exact area only sets the nominal starting point. (Chunk 2b probes that box geometry
no-fit with `InPlaneTracking(velocity_reference="ecef")` — the wind-aligned mode
`BoxFaceCd` is built for, and drag-equivalent to the physically faithful
`NadirPointing` for this near-circular, ram-dominated body.)

| Parameter | Value | Source |
|---|---|---|
| mass | 600 kg | [eoPortal GRACE-FO](https://www.eoportal.org/satellite-missions/grace-fo) / [NASA/JPL Quick Facts](https://gracefo.jpl.nasa.gov/overlay-quick-facts/) (launch mass ~600 kg) |
| frontal area | 1.0 m² | ram face of the ~3.1 × 1.9 × 0.8 m trapezoidal-prism body flying narrow-end-forward (eoPortal dimensions) |
| Cd (nominal) | 2.3 | free-molecular convention; the fitted Cd is the diagnostic — cf. [Mehta et al. 2013 (DSMC drag coefficients for GRACE)](https://ui.adsabs.harvard.edu/abs/2013AdSpR..52.2035M/abstract), which finds a physical Cd well above 2.3 |
| Cr | 1.3 | sphere reflection coefficient (1.0 absorbing – 2.0 specular); SRP is minor at 500 km |

### Chunk 2b geometry — the base-averaged rectangle at real dimensions

GRACE-FO is a trapezoidal prism; propygator models a rectangular box. Averaging the
two parallel widths gives a rectangle that **preserves the ram (frontal) area
exactly** and under-counts the wetted side area by ~9.5 % (→ ~2 % of Cd·A, far below
the density confound Runs 4–5 measure). Citable dimensions (JPL GRACE-FO Launch
Press Kit; cross-checked vs. eoPortal FLEXBUS/Astrium):

| Quantity | Value | Note |
|---|---|---|
| length L (along-track) | 3.123 m | long axis; rides the wind |
| height h (radial) | 0.780 m | |
| bottom / top width | 1.943 / 0.690 m | trapezoid faces nadir/zenith |
| **base-averaged width w** | **1.3165 m** | (1.943 + 0.690)/2 |
| **ram area A_ram** | **1.027 m²** | w·h — preserved exactly |

Box mapping (matches `InPlaneTracking`'s axes — body **+Y on the wind**):
`x_length_m = 0.780` (radial), `y_length_m = 3.123` (along-track/ram),
`z_length_m = 1.3165` (cross-track). Ram + leeward are the ±Y faces (1.027 m² each),
nadir/zenith the ±X faces (4.111 m² each), slant sides the ±Z faces (2.436 m² each)
— wetted side total 13.09 m². The baseline box is deliberately **not**
length-corrected (that would swap a traceable dimension for a fictitious one); the
+0.33 m variant is a one-off sensitivity check only (Verify 5).

## Method (`run_gracefo.py`, per window)

1. `gnv1b.py` parses the loaded days into one continuous ITRF ephemeris (GPS→TAI +19
   s, SI at source, QC-screened, 60 s subsample), verifying the seam continuity.
2. Initial `State` at t0 in `Frame.ITRF` → `.to_frame(Frame.EME2000)`; a **t0 sanity
   diff** (ITRF→EME2000→ITRF round trip ≪ 1 m) isolates frame/time conversion from
   dynamics before anything else.
3. **Space-weather context** — F10.7 / Ap / Kp at the window midpoint, read from the
   *same* `CssiSpaceWeatherData` NRLMSISE-00 consumes.
4. **Maneuver screen** — a drag-on arc over the loaded span; the along-track residual
   is fit with a smooth degree-5 polynomial and the largest departure reported (a
   thruster burn leaves a slope kink). Both windows read CLEAN. (Deliberate
   deviation from the plan's "drag-off scan over the candidate weeks": drag-on
   leaves a far smaller smooth residual for a kink to stand out against, and only
   the loaded days feed the runs — the SDS monthly reports remain the cross-check
   if a screen ever reads REVIEW.)
5. **Run 1 — drag off:** the LAGEOS conservative set (70×70, sun+moon, SRP, solid +
   ocean tides, relativity); the residual growth *is* the drag signal.
6. **Run 2 — drag on:** the same set + NRLMSISE-00 at the nominal Cd = 2.3.
7. **Run 3 — scalar Cd fit:** coarse scan + golden-section refine minimizing the
   1-day along-track RMS (~19 propagations around `propagate_numerical`).
8. Residuals decomposed radial / along-track / cross-track by the Chunk 0
   `ric_components` helper (imported from `run_lageos`, not duplicated), with the
   ECEF truth velocity corrected to inertial (v + ω⊕×r) so the along-track axis
   isn't tilted by Earth rotation. `high_precision` integrator throughout; the 60 s
   output grid coincides exactly with the truth grid (exact-grid diff).
9. **Cd-table diagnostic block (Chunk 2b):** NRLMSISE-00 queried along the truth
   arc (the same CSSI-driven model the drag force consumes), both shipped tables
   looked up at those conditions, and every number printed with an explicit
   quantity label — the raw face-sum `Σ Cd_i·A_i` (which for `BoxFaceCd` *is* the
   along-wind effective Cd·A, incidence being baked into each face's Cd) vs. the
   dimensionless Cd on the common A_ram = 1.027 m² reference (the build plan's
   flagged reference-area ISSUE fix). Face-flow angles under
   `InPlaneTracking(ecef)` are constant by construction (+Y held exactly on the
   wind): ram θ=0, leeward θ=π, all four sides θ=π/2 — the arc-mean varies only
   through the tables' (radius, density) inputs. Includes the **axis-convention
   check** (the face-sum under the two wrong wind-axis mappings, recomputed live).
10. **Run 4 — sphere table (no fit):** `VariableCd.sphere_default()` on the exact
    A_ram; attitude-independent. **Run 5 — box table (no fit):**
    `BoxFaceCd.default()` on the box above, flown `InPlaneTracking(ecef)`; SRP
    optics at the `box_and_panels` defaults (negligible at 500 km). Then the
    propagation-level consistency check (predicted vs. realized along-track @ 24 h,
    from `s = CdA_table/CdA_fit`), **Verify 4** (one propagation with the box Cd·A
    scaled onto the fitted product — the collapse test) and **Verify 5** (the
    +0.33 m length-corrected box — the geometry-insensitivity test).

## Result summary (2026-07-12 run)

Full tables in `results.txt`; Checkpoint B reads the along-track RMS row and the
fitted Cd. Both windows: t0 sanity ~4e-9 m (frame/time conversion clean to float
noise), maneuver screen CLEAN, 0 QC-dropped records, seamless day concatenation.

| | quiet_2019 | active_2023 |
|---|---|---|
| window midpoint F10.7 (81-day avg) | 69.8 (69.4) sfu | 190.1 (158.2) sfu |
| daily Ap / Kp | 2.0 / 0.46 | 4.0 / 0.96 |
| altitude | ~498 km | ~501 km |
| **Run 1** drag-off, along-track RMS (1 d) | **44.2 m** | **1057.8 m** |
| **Run 2** drag-on Cd=2.3, along-track RMS | **6.0 m** | **343.7 m** |
| Run 2 / Run 1 along-track ratio | 0.14 | 0.32 |
| **Run 3** Cd-fit, along-track RMS | **1.9 m** | **6.4 m** |
| **fitted Cd** (vs. 2.3 nominal) | **2.03** | **3.40** |
| Run 1 vs. LAGEOS conservative floor (~4 m/day) | ~11× | ~264× |
| **Run 4** sphere table (no fit), along-track RMS | **20.9 m** | **210.6 m** |
| **Run 5** box table (no fit, IPT-ecef), along-track RMS | **55.0 m** | **222.6 m** |
| Run 4 / Run 5 share of the fitted ρ·Cd·A product | 1.47× / 2.23× | 0.80× / 1.21× |
| Verify 4: box scaled onto the fitted product, along RMS | 1.85 m (Run 3: 1.86) | 6.45 m (Run 3: 6.36) |
| Verify 5: +0.33 m length-corrected box, Δ along RMS | +2.7 m | +35.7 m |

Radial and cross-track stay sub-metre (quiet) to metre-class (active); the residual
is almost purely along-track, the classic drag signature. Reading:

- **Run 1 ≫ the conservative floor** (11× quiet, 264× active) — drag dominates, and
  the drag-off residual scales with solar activity as expected: ~1 km/day at
  F10.7 ≈ 190 sits in the plan's "0.5–1 km/day, activity-dependent" band, while the
  deep-minimum 44 m/day falls well *below* that band (it was calibrated for average
  activity) yet still clears the order-of-magnitude floor gate.
- **Run 2 ≪ Run 1** — the NRLMSISE-00 pipeline carries the drag signal (a 7× / 3×
  reduction at the fixed nominal Cd).
- **Run 3 collapses the residual to single-metre-class in both windows** (44 → 1.9 m,
  1058 → 6.4 m along-track) — proof that a *single scalar* Cd absorbs almost all the
  model error, i.e. the pipeline is wired correctly and the remainder is genuine
  thermospheric-density bias, not a propygator defect.
- **The fitted Cd swings 2.03 → 3.40** from solar min to solar max. The orbit
  constrains only the ρ·Cd·A product, so read these as density biases *relative to
  the Cd = 2.3 · A = 1.0 m² assumption* — the data cannot factor density from Cd by
  itself. Anchored instead on the DSMC physical Cd (Mehta 2013, well above 2.3 —
  see the parameter table), the quiet window has NRLMSISE-00 substantially
  *over*-predicting deep-solar-minimum density (the Chunk 2b common-reference
  numbers below make this apples-to-apples: fitted Cd 1.98 on A_ram vs. the DSMC
  band's 2.65 low edge, a ≳ 25 % density over-prediction even at the band edge),
  while the active window comes out roughly unbiased (fitted Cd 3.32 on A_ram sits
  mid-band). Either way, the swing spans the ~10–30 % density-model uncertainty the
  plan named, now measured — the number that calibrates the maintainer's solar-sail
  expectations: a high-A/m sail lives in this same density-uncertainty band, so
  expect along-track prediction error to track solar activity the same way.

### A-priori Cd tables (Chunk 2b, Runs 4 & 5)

The pre-flight-Cd question: with **no reference Cd supplied**, what do propygator's
generated tables predict against a real orbit? Everything on the common
**A_ram = 1.027 m²** reference (the flagged reference-area ISSUE fix — the Run 3
fitted Cd is restated as × 1.0/1.027):

| Cd on A_ram = 1.027 m² | quiet_2019 | active_2023 |
|---|---|---|
| `VariableCd.sphere_default` (arc mean) | 2.92 | 2.70 |
| `BoxFaceCd.default` (face-sum / A_ram) | 4.42 | 4.06 |
| fitted (Run 3, restated) | 1.98 | 3.32 |
| DSMC physical band (Mehta 2013; arXiv 2503.21651) | 2.65–4.5 | 2.65–4.5 |

Reading:

- **Both tables are physically credible.** The sphere sits just above the DSMC
  band's low edge in both windows; the box lands *inside* the band (4.42 / 4.06,
  under the 4.5 top — the plan allowed it to exceed; it didn't). The box's larger
  Cd is the extra edge-on skin friction a sphere structurally cannot see — the
  more complete model, not an over-estimate.
- **The no-fit residuals are density-limited by construction** (an orbit constrains
  only ρ·Cd·A). Quiet: both tables over-predict drag (1.47× / 2.23× the fitted
  product) — NRLMSISE-00 over-models deep-solar-minimum density, so the physically
  *better* box Cd produces the *worse* orbit (55.0 vs 20.9 m along-track). That is
  the finding, not a defect. Active: the tables **bracket** the truth (0.80× /
  1.21×), which is why their residuals are similar magnitude with opposite sign
  (−481 / +486 m signed along-track at 24 h).
- **The axis convention is proven live** (build-plan Verify 1, gate figures
  recomputed from the refined geometry): the wired +Y-on-wind face-sum is
  4.54 m² (quiet arc) vs. 14.27 / 8.99 m² for the two wrong-axis mappings, and the
  propagation-level check — predicted vs. realized signed along-track @ 24 h from
  `s = CdA_table/CdA_fit` — agrees to 2–11 % across both runs and both windows.
  The plan's remembered "≈ 6 m² (≈ 4.3 on A_ram)" gate traced to the superseded
  probe geometry, as its ISSUE note suspected; the recomputed numbers are
  **4.54 m² / 4.42 on A_ram**.
- **Verify 4 — the collapse test:** one propagation with the box Cd·A scaled onto
  the fitted product lands at 1.85 m (Run 3: 1.86 m) quiet and 6.45 m (6.36 m)
  active — a single scalar absorbs the box's structure *completely* for this
  ram-dominated body. Direct proof the `box_and_panels` upgrade would add no
  non-absorbable fidelity for GRACE-class flight (its payoff is the edge-on sail
  regime GRACE doesn't exercise).
- **Verify 5 — geometry-insensitivity:** the +0.33 m length-corrected box moves the
  along-track RMS by +2.7 m (quiet) / +35.7 m (active) against density confounds of
  53 / 216 m — the residual is density-limited, not dimension-limited.
- One shipped-surface observation (normal fix path, low severity): the
  `box_face_default` grid's leeward half carries noise-level **negative** entries
  (min −5.8e-4; the whole θ=π slice is ≤ 0). Harmless in the table path (≤ 0.01 %
  of the face-sum) but `BoxFaceCd.from_callable` *rejects* Cd < 0, so wrapping the
  shipped table in a callable (as Verify 4 does) hits a mid-propagation
  `ValueError` without a clamp — an asymmetry between the two factory paths worth
  a generator floor-at-zero or a `from_table` normalization.

### Checkpoint B inputs (maintainer's call)

- **Pinnable bounds (Chunk 4):** the drag-off-≫-drag-on ordering and the ratio bound
  are the stable, wiring-sensitive facts (Run 1 ≫ Run 2 in both windows; Run 3 ≤ Run
  2). The absolute metres depend on the exact arc/window and orekit-data CSSI, so the
  pinned test should assert *relationships* (drag-on materially beats drag-off; the
  fit reduces the residual), not absolute metres — see Chunk 4's tolerance policy.
- **Geometry deferral — now with direct evidence (Runs 4 & 5):** the
  sphere-equivalent already explains the residuals (a single scalar Cd drives the
  along-track residual to single-metre-class in both windows), and Verify 4 shows
  the wind-aligned `BoxFaceCd` box, scaled onto the same fitted product, lands
  *exactly* on Run 3 (1.85 vs 1.86 m; 6.45 vs 6.36 m) — the box adds only
  absorbable scale for this ram-dominated body. The box table itself is validated
  as physically sound (DSMC-consistent, 4.42/4.06 on A_ram inside the 2.65–4.5
  band). Default hold: **defer** the fitted `box_and_panels` upgrade; its
  non-absorbable payoff belongs to the edge-on sail regime.
- **Storm-window stress case** — noted, not built (a candidate future density stress
  test per the plan).

## Files

- `gnv1b.py` — minimal GNV1B parser (tarball-aware; GPS→TAI, ITRF, QC screen,
  subsample, multi-day concatenation).
- `run_gracefo.py` — the Chunk 2 + 2b driver (steps above; reuses the Chunk 0
  `ric_components` / `_rms`).
- `probe_tables.py` — the retained 2026-07-12 scratch probe of the shipped Cd
  tables, the Chunk 2b diagnostic template (**superseded geometry** — its
  docstring says how; Run 5's driver code is the evidence path, not this).
- `results.txt` — captured stdout (the committed evidence; both windows appended).
