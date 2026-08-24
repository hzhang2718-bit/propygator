# Real-world validation study

Evidence for `docs/history/build-plan-real-world-validation.md`: propygator's numerical
propagator and TLE fitter measured against **real orbits** for the first time.
Every propygator surface is extensively tested, but internal tests are
structurally blind to *self-consistent wiring bugs* (a factor-of-2 in area, a
frame flip, a toggle that never reaches Orekit) — a measured orbit is the one
oracle that can't share the misconception. Three legs, each building on the
last:

1. **LAGEOS-2 vs. ILRS precise orbits** (`lageos/`) — the conservative-force +
   wiring diagnostic: a passive laser-ranged sphere at ~5,800 km, cm-level
   truth, no meaningful drag. Chunk 0 (the 7-day diff → Checkpoint A) and
   Chunk 1 (the per-toggle ablation matrix).
2. **GRACE-FO vs. GNV1B reduced-dynamic orbits** (`gracefo/`) — the drag
   stack: real LEO at ~500 km, GPS-determined truth, in solar-quiet /
   solar-active / Gannon-storm windows. Chunks 2 (drag-off / drag-on /
   fitted-Cd trio), 2b (the no-fit a-priori Cd-table runs), 2c (the storm
   stress case).
3. **TLE fitter vs. reality** (`gracefo/run_fit_vs_catalog.py`) — Chunk 3:
   a propygator-fitted TLE vs. the operational Space-Track catalog TLE at
   predicting real GNV1B truth, plus three maintainer-elected extensions
   (fitting-span sweep, State-path composition check, a-priori-table rows).

**Status (2026-07-16):** Chunks 0–4 complete — Checkpoint A resolved **GO**
(day-1 residual 3.6 m RMS, tier 1 with ~3× margin), Checkpoint B resolved
(relationship pins; `box_and_panels` geometry upgrade **deferred**), and the
Chunk 4 wrap-up shipped the pinned tests
(`tests/propagation/test_real_world_*.py`, `tests/tle/test_fitter_real_world.py`),
the findings doc (`docs/validation-findings.md`), and the README
Validation note. Chunks 5 and 6 are order-independent follow-ons on their own
branches off `main`; the build plan stays active.

## Layout

```
real-world-validation/
├── README.md            this file — the study index
├── common.py            shared analysis kit (RIC decomposition, rms, omega-Earth)
├── run_all.py           orchestrator: regenerate/verify every results file
├── data/                raw truth files (gitignored, never committed)
├── lageos/              leg 1 — Chunks 0 + 1
│   ├── sp3.py           minimal SP3-c parser (+ Lagrange velocity fallback)
│   ├── run_lageos.py    Chunk 0 driver (7-day conservative diff)
│   ├── run_ablations.py Chunk 1 driver (per-toggle ablation matrix)
│   ├── results.txt      committed evidence (both chunks)
│   └── README.md        provenance, method, result readings
└── gracefo/             legs 2 + 3 — Chunks 2, 2b, 2c, 3
    ├── gnv1b.py         minimal GNV1B parser (tarball-aware, GPS→TAI)
    ├── gracefo_common.py leg config: constants, box geometry, spacecraft/force
    │                    factories, measured anchors (Run-3 fitted Cds)
    ├── run_gracefo.py   Chunks 2/2b/2c driver (Runs 1–5 per window)
    ├── run_fit_vs_catalog.py  Chunk 3 driver (primary / --fit-bstar=off /
    │                    --sweep / --state-path)
    ├── probes/          diagnostic probes (not evidence drivers)
    │   ├── probe_tables.py      superseded scratch probe (kept for provenance)
    │   └── probe_ap_driving.py  the daily-Ap-driving proof (Chunk 2c finding)
    ├── results.txt                     drag evidence (quiet/active/storm ×2)
    ├── results_fit_vs_catalog.txt     Chunk 3 primary + fit-bstar=off
    ├── results_fit_span_sweep.txt     fitting-span sweep
    ├── results_fit_state_path.txt     State-path check + a-priori-table rows
    └── README.md        provenance, method, result readings
```

## Running the study

Everything runs in the **propygator conda env** (starts the JVM, needs
orekit-data) — the study's one locked departure from
`docs/experiments_venv.md`. Raw truth files must be on disk under `data/`
(download pointers in each leg README; free NASA Earthdata login).

One command regenerates all five results files (~60–90 min, dominated by the
golden-section Cd fits):

```
cd experiments/real-world-validation
conda run -n propygator python run_all.py              # regenerate in place
conda run -n propygator python run_all.py --only drag  # one group
conda run -n propygator python run_all.py --verify     # scratch run + diff vs committed
```

`run_all.py --list` shows the group → results-file map; each driver's
docstring carries its individual invocations. Drivers are cwd-independent,
print ASCII-only stdout (evidence is captured under cp1252), and send
progress to stderr.

## Findings at a glance

Full tables and readings live in the leg READMEs (the committed `results.txt`
files are the raw evidence); `docs/validation-findings.md`
consolidates them.

| Leg | Headline | Where |
|---|---|---|
| LAGEOS-2 conservative floor | day-1 residual **3.6 m RMS** (tier-1 GO); 7-day 23.6 m, almost purely along-track (the unmodeled ERP + thermal-thrust floor) | `lageos/README.md` |
| Ablation matrix | **all 7 toggles PASS** at their computed orders; predicted-null rows (gravity>20, planets) null at mm level | `lageos/README.md` |
| GRACE-FO drag pipeline | scalar-Cd fit collapses along-track RMS **44 → 1.9 m** (quiet) / **1058 → 6.4 m** (active): pipeline proven, remainder is density bias | `gracefo/README.md` |
| Fitted Cd across windows | **2.03 → 3.40 → 4.08** (quiet/active/storm on A=1 m²): the NRLMSISE-00 density-bias lever, measured | `gracefo/README.md` |
| A-priori Cd tables | both DSMC-credible on A_ram (sphere ~2.9/2.7, box ~4.4/4.1); no-fit residuals density-limited; box adds only absorbable scale for ram-dominated GRACE (geometry upgrade deferred) | `gracefo/README.md` |
| Storm stress (Gannon 2024) | box sign test → **H1** (density bias, not geometric over-drag); scalar-Cd fit degrades to 119 m; **NRLMSISE-00 at default switches is daily-Ap-driven** (onset smearing, `probes/probe_ap_driving.py`) | `gracefo/README.md` "Storm window" |
| Fitter vs. catalog | converges on real data (~630 m post-fit RMS); **catalog parity** with regime-appropriate `fit_bstar` (ratios 0.83–2.10); quiet 1-day B\*-on runaway = §1.2's own guidance validated | `gracefo/README.md` "Fitter vs. catalog" |
| Fitting-span sweep | 2-day `fitting_span` default **empirically vindicated**; regime rule: weak drag → hold a calibrated B\*, strong drag → fit B\* on ~2 d | `gracefo/README.md` sweep subsection |
| State path | free **iff** the ballistic coefficient is calibrated (single-digit-%); uncalibrated Cd costs 7× and no fit diagnostic can see it; a-priori tables can't meet the bar | `gracefo/README.md` state-path subsection |

**DSMC band correction (2026-08-24):** the "A-priori Cd tables" row's
DSMC-credible read cites a band withdrawn in full — see `gracefo/README.md`
"DSMC band correction."

## Conventions

- **Raw truth files are never committed** (`data/` is gitignored); committed
  evidence is each leg's README + results files.
- Evidence numbers are deterministic (same code, truth files, orekit-data);
  only wall-clock timings vary between runs — `run_all.py --verify` masks them.
- **`--verify` leaves its scratch directory behind, deliberately.** It runs into
  a fresh `rwv-verify-*` under the OS temp dir (`%TEMP%`, `/tmp`) and never
  removes it, so after a diff you can still open the regenerated file that
  produced it. Nothing reads them again and no committed evidence references
  one, so they are safe to delete at any time; clearing them is a manual step.
- **Evidence is frozen at its v0.7.2 numbers** — the historical record of what
  was measured against the table that shipped then. The Chunk 5 leeward floor
  (v0.7.3) regenerated `box_face_cd_default.npz`, so a post-v0.7.3 `--verify`
  of the `drag` / `state-path` groups differs from the committed
  `gracefo/results.txt` in exactly four `leeward -0.000` → `0.000` prints (the
  sign of a −3.4e-11 the floor zeroed; the numeric effect on Run 5 is
  ~1e-11 m² of Cd·A, below printed precision). Expected — do not regenerate.
- Shared code: `common.py` (cross-leg analysis math), `gracefo/gracefo_common.py`
  (leg config + measured anchors). Drivers stay the per-chunk entry points.
- Reference-only: not shipped, not in CI, outside `testpaths`, excluded from
  lint (`pyproject.toml` ruff `extend-exclude`).
