# LAGEOS-2 vs. ILRS precise orbits (real-world validation, Chunks 0–1)

Evidence for `docs/history/build-plan-real-world-validation.md` Chunk 0 — the
conservative-force + wiring diagnostic. A measured orbit is the one oracle that
can't share a wiring misconception with propygator's own tests: LAGEOS-2 is a
passive laser-ranged sphere (the one satellite `SpacecraftGeometry.sphere`
models *exactly*) at ~5,800 km altitude — no meaningful drag, cm-level truth —
so a 7-day diff against the ILRS orbit validates gravity + tides + third body +
relativity + cannonball SRP end-to-end. **Checkpoint A (GO / INVESTIGATE) is
called on these numbers.**

**Reference-only.** Not shipped, not in CI, outside `testpaths`. Everything is
shipped propygator + the pinned Orekit 13.1.x, so it runs in the **propygator
conda env** (starts the JVM, needs orekit-data) — the study's one locked
departure from `docs/experiments_venv.md`:

```
conda run -n propygator python experiments/real-world-validation/lageos/run_lageos.py > experiments/real-world-validation/lageos/results.txt
```

`--parse-only` stops before the JVM-touching steps (parser + velocity-route
checks only). Stdout is ASCII-only (cp1252 redirect); progress goes to stderr.

## Truth data (not committed)

`experiments/real-world-validation/data/lageos/esa.orb.lageos2.230422.v70.sp3.gz`
— an ILRS analysis-center weekly orbit product (ESA AC), downloaded by the
maintainer from the CDDIS SLR products archive (NASA Earthdata login). Raw
truth files are **never committed** (the `data/` directory is gitignored);
committed evidence is this README + `results.txt`.

Product facts (read from the SP3 header by `sp3.py`, echoed in `results.txt`):

- SP3-c, satellite `L52` (LAGEOS-2, NORAD 22195), **with V-records**
- span 2023-04-16 00:00 → 2023-04-23 00:00 (7.000 days), 120 s interval,
  5041 epochs
- time system **UTC** (so the epochs go into `Epoch` directly; the parser's
  GPS + 19 s = TAI route is exercised by the GRACE-FO leg instead)
- coordinate system `SLR08` (SLRF2008 — an ITRF realization; the cm-level
  realization difference vs. Orekit's IERS-2010 ITRF is far below every
  threshold in this study — noted, not modeled, per the build plan)

## Spacecraft parameters (re-confirmed 2026-07-12)

| Parameter | Value | Source |
|---|---|---|
| mass | 405.38 kg | [ILRS LAGEOS-2 mission page](https://ilrs.gsfc.nasa.gov/missions/satellite_missions/current_missions/lrs2_general.html) |
| diameter | 0.60 m → A = π(0.30)² ≈ 0.2827 m² | same |
| Cr | 1.13 (plan-pinned) | literature range ~1.10–1.13; e.g. [Hattori & Otsubo 2019](https://www.sciencedirect.com/science/article/abs/pii/S0273117718306197) report a mean LAGEOS-2 CR ≈ 1.10 |

Cr is the Checkpoint-A tier-2 sweep knob if the day-1 residual lands in the
20–500 m band (SRP on LAGEOS-2 is a ~few-m/day effect, so the 1.10-vs-1.13
spread is far below the GO tier).

## Method (`run_lageos.py`)

1. `sp3.py` parses the week: header time-system field routes the epochs
   (UTC direct; GPS would go +19 s → TAI), km → m and dm/s → m/s at the
   boundary (SI rule), ITRF. Velocity comes from the V-records; a 7-point
   sliding-Lagrange differentiation of the positions is printed alongside as
   the cross-check (and is the route files without V-records would use).
2. Initial `State` at t0 in `Frame.ITRF` → `.to_frame(Frame.EME2000)` (the
   inertial-frame rule for `propagate_numerical`).
3. Config: `ForceModelConfig(drag=False, solid_tides=True, ocean_tides=True,
   relativity=True)` at the default 70×70 EIGEN-6S + Sun/Moon third body +
   cannonball SRP; `IntegratorConfig.high_precision()`; the sphere geometry
   above.
4. **t0 sanity diff** before anything else: the ITRF → EME2000 → ITRF round
   trip and the first propagated sample vs. truth must be ~0 (≪ 1 m) — it
   isolates frame/time conversion from all dynamics.
5. The output grid (`t0 + k·120 s`) is verified to coincide exactly with the
   truth grid, then the trajectory is converted back to ITRF and diffed
   sample-by-sample. (`Trajectory.at()` on the truth epochs — the build plan's
   wording — would reproduce these same samples, since Hermite interpolation
   is exact at its nodes; the script falls back to `.at()` if the grids ever
   misalign.)
6. Residuals decomposed radial / along-track / cross-track by a pure-NumPy
   helper (`ric_components` in the study-level `../common.py`, shared with the
   GRACE-FO leg). The triad is built from the truth PV with the ECEF velocity
   corrected to inertial (v + ω⊕×r) so the along-track axis isn't tilted by
   Earth rotation. RMS + max per component at 1 / 3 / 7 days.

## Files

- `sp3.py` — minimal generic SP3-c parser (+ Lagrange velocity helper).
- `run_lageos.py` — the Chunk 0 driver (steps above; LAGEOS-2 constants live
  here, the shared RIC/rms helpers in `../common.py`).
- `run_ablations.py` — the Chunk 1 ablation matrix (appends to `results.txt`:
  `conda run -n propygator python run_ablations.py >> results.txt`).
- `results.txt` — captured stdout (the committed evidence; Chunk 0 run + the
  Chunk 1 append). Regenerate both blocks with
  `python ../run_all.py --only lageos`.

## Result summary (2026-07-12 run)

Full tables in `results.txt` (regenerated 2026-07-15 from the reorganized
drivers — every number reproduced identically); Checkpoint A reads the day-1
row.

- **Parser:** epoch serialization round trip bit-exact for all 5041 epochs;
  grid exactly uniform (max deviation 0.0 s); position text round-trips
  digit-for-digit. V-records vs. 7-point Lagrange differentiation agree to
  **3.5e-5 m/s RMS / 1.4e-4 m/s max** — the sub-mm/s the plan expected, so the
  no-V-records fallback route is validated too.
- **t0 sanity (frame/time conversion isolated from dynamics):**
  ITRF → EME2000 → ITRF round trip and first-propagated-sample diffs both
  **~9e-10 m** — conversion is clean to float noise; everything after is
  dynamics.
- **Residuals (propagated − truth, RIC):**

  | horizon | radial RMS/max | along RMS/max | cross RMS/max | 3D RMS/max |
  |---|---|---|---|---|
  | 1 d | 0.11 / 0.20 m | 3.6 / 6.2 m | 0.05 / 0.11 m | **3.6 / 6.2 m** |
  | 3 d | 0.13 / 0.32 m | 10.6 / 18.2 m | 0.10 / 0.21 m | 10.6 / 18.2 m |
  | 7 d | 0.28 / 0.74 m | 23.6 / 40.5 m | 0.16 / 0.33 m | 23.6 / 40.5 m |

- **Checkpoint A reading: day-1 residual 3.6 m RMS / 6.2 m max — tier 1
  (≲ 20 m/day → GO)** with a factor-~3 margin (maintainer's call: **GO**,
  2026-07-12). The error is almost purely along-track and grows secularly
  (~6 m/day) with sub-meter radial and cross-track over the full week — the
  classic signature of the small unmodeled along-track accelerations (Earth
  radiation pressure + thermal thrust), i.e. exactly the literature floor for
  this force set. This is the number the Chunk 4 pin derives from; the parked
  `earth_radiation` toggle is the named next step for lowering the floor.
- 7-day 70×70 `high_precision` propagation wall time: ~11 s.

## Ablation matrix (Chunk 1, 2026-07-12 run)

`run_ablations.py` reruns the same arc with one `ForceModelConfig` change at a
time — the direct proof that each toggle reaches Orekit, the bug class
internal tests structurally cannot see. The "expected order" per force is
**computed, not quoted**: acceleration scales evaluated along the truth orbit
(degree sums from the actual EIGEN-6S coefficients, third-body/tide scales
from the DE-ephemeris distances, Schwarzschild from the sampled PV), turned
into a 1-day free-drift bound `a·t²/2` — a secular *upper* limit that
orbit-periodic forces average 1–2 orders below.

Two tables (full output in `results.txt`):

- **A — wiring proof** (`|case − baseline|` trajectory difference, sign-free):
  **all seven rows PASS.** Effects at day-7: sun+moon third body off → 781 m;
  gravity 8×8 → 25.6 m; tides off → 14.1 m; SRP off → 5.9 m; relativity off →
  4.5 m — each present, below its bound, and ordered exactly as the computed
  accelerations predict. The two predicted-null rows are null at the mm level:
  gravity 20×20 → 0.001 m (degrees > 20 genuinely don't matter at 5,800 km,
  as the coefficient sums predict) and **`planets_third_body` → 0.001 m** —
  the §"completeness only" claim confirmed against a real orbit.
- **B — agreement vs truth** (signed): `relativity off` and `tides off`
  *improve* the total vs-truth RMS (−4.5 m and −10.1 m at day 7). This is not
  a wiring signal: the baseline carries a ~−40 m signed along-track floor at
  day 7 (the unmodeled ERP + thermal-thrust budget), and those two (correct)
  contributions happen to oppose it this week — removing them cancels part of
  the floor (along@7d moves −40.5 → −32.6 / −27.9 m). A boolean toggle can
  only add or omit an Orekit force model, not distort one, so table A carries
  the wiring evidence; the sign-level attribution (how much of the floor is
  ERP vs. thermal thrust vs. a possible permanent-tide convention offset
  between EIGEN-6S and the solid-tide model) is a findings-doc note — not
  resolvable from one week, and immaterial at this study's thresholds.

**Chunk 1 verdict: the per-toggle wiring is proven** — no ablation misbehaves,
nulls are null, and the matrix is self-interpreting against its computed
expectations.
