# GRACE-FO vs. GNV1B reduced-dynamic orbits (real-world validation, Chunk 2)

Evidence for `docs/build-plan-real-world-validation.md` Chunk 2 — the **drag-stack**
diagnostic. After the LAGEOS-2 leg established the conservative-force floor (Chunks
0–1), this leg measures the full drag pipeline (NRLMSISE-00 + real CSSI space
weather + the shared `DragSensitive` proxy) against a real drag-perturbed LEO orbit:
GRACE-FO 1 at ~500 km, with cm-level GPS-determined truth from the mission's Level-1B
GPS-navigation product. The residual is decomposed into "pipeline" vs. "density
model" *by construction* — a drag-off / drag-on / fitted-Cd trio, run in a
solar-quiet and a solar-active week so the quiet-vs-active contrast is visible in
the fitted Cd and the residual ratio. **Checkpoint B (pinnable bounds + the
`box_and_panels` geometry decision) is called on these numbers.**

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
  *over*-predicting deep-solar-minimum density (≳ 35 % even against the DSMC band's
  low edge), while the active window comes out roughly unbiased (the fitted product
  sits inside the DSMC-implied range); the apples-to-apples factorization on a
  common area reference is the Chunk 2b diagnostic block's job. Either way, the
  swing spans the ~10–30 % density-model uncertainty the plan named, now measured —
  the number that calibrates the maintainer's solar-sail expectations: a high-A/m
  sail lives in this same density-uncertainty band, so expect along-track
  prediction error to track solar activity the same way.

### Checkpoint B inputs (maintainer's call)

- **Pinnable bounds (Chunk 4):** the drag-off-≫-drag-on ordering and the ratio bound
  are the stable, wiring-sensitive facts (Run 1 ≫ Run 2 in both windows; Run 3 ≤ Run
  2). The absolute metres depend on the exact arc/window and orekit-data CSSI, so the
  pinned test should assert *relationships* (drag-on materially beats drag-off; the
  fit reduces the residual), not absolute metres — see Chunk 4's tolerance policy.
- **Geometry deferral:** the sphere-equivalent already explains the residuals — a
  single scalar Cd drives the along-track residual to single-metre-class in both
  windows, so a constant cross-section is *not* the limiting error here. Default
  hold: **defer** the `box_and_panels` fitted-geometry upgrade; the evidence is
  recorded either way.
- **Storm-window stress case** — noted, not built (a candidate future density stress
  test per the plan).

## Files

- `gnv1b.py` — minimal GNV1B parser (tarball-aware; GPS→TAI, ITRF, QC screen,
  subsample, multi-day concatenation).
- `run_gracefo.py` — the Chunk 2 driver (steps above; reuses the Chunk 0
  `ric_components` / `_rms`).
- `probe_tables.py` — the retained 2026-07-12 scratch probe of the shipped Cd
  tables, the Chunk 2b diagnostic template (**superseded geometry** — its
  docstring says how; Run 5's driver code is the evidence path, not this).
- `results.txt` — captured stdout (the committed evidence; both windows appended).
