# Extended Validation — drag propagations, TLE fitting tests, and table noise

Evidence tree for the study contracted in `docs/extended-validation-updated.md`.
**The contract wins on every conflict**; `docs/features.md` and
`docs/architecture.md` win over the contract. The working blueprint is
`docs/build-plan-extended-validation-updated.md`.

Every external claim propygator makes rests on one satellite (GRACE-FO 1). This
study widens that base in three parts: **table noise** on the GRACE-FO C/D
formation twin, **drag propagations** over ten stratified GRACE-FO windows plus
**Swarm A/B** as a limited-information stress case, and **TLE fitting tests**
against the playbook and the r/s gate.

## Layout

```
extended-validation/
├── README.md          this file
├── run_all.py         regenerate / --verify orchestrator; --list is authoritative
├── drag_common.py     Part 2 primitives shared by both legs (the per-day rule)
├── summarize_drag.py  cross-window text parse → results_drag_summary.txt
├── data/              raw truth + reference docs (gitignored, never committed)
│   ├── reference/     third-party reference PDFs (see "Reference documents")
│   ├── tarballs/      TRANSIENT download staging, deleted after extraction
│   ├── gracefo/<window>/   GNV1B / MAS1B / THR1B, both satellites, gzipped
│   │                      84 files per window, ~269 MB, ~2.6 GB for all ten
│   └── swarm/<window>/     SP3 .ZIP, A and B, 8 days — the arc's span
├── gracefo/
│   ├── windows.py            frozen ten-window list, CSSI re-read, .gz finder
│   ├── thr1b.py              tier-1 thruster parser
│   ├── mas1b.py              tank-gas mass parser
│   ├── gracefo_ext_common.py leg geometry, mass, force set, scalar-Cd fitter
│   ├── fetch_windows.py      download → extract → gzip → screen
│   ├── run_screen.py         both maneuver gates  → results_screen.txt
│   ├── run_table_noise.py    the twin ratios      → results_table_noise.txt
│   ├── run_drag_window.py    Part 2, one window   → results_drag/window_NN_*.txt
│   └── results_drag/         one file per window (group `drag_NN`)
└── swarm/             the Swarm A/B leg — see swarm/README.md
    ├── swarm_sp3.py          SP3 reader (ZIP + concat over the frozen parser)
    ├── swarm_common.py       ESTIMATED geometry and mass
    ├── run_drag_window.py    Part 2, one window, both satellites
    └── results_drag/         one file per window (group `swarm_NN`)
```

**Why `swarm/` has its own README and `gracefo/` does not.** This file *is* the
GRACE-FO leg's documentation — the A/m convention, the geometry, the truth
provenance and the findings all live here. The Swarm leg carries facts with no
home in it: the contract requires the delivered SP3 format recorded, and every
Swarm number rests on estimated mass and geometry that must be read with the
row. Splitting those out beats growing a second convention table here that would
drift from the first.

**Group names.** `--only drag_04` is one complete window; the aliases `drag`,
`swarm` and `part2` expand to the twenty window groups plus the summary, because
twenty bare names in `--only` is unusable. `run_all.py --list` prints every
group with its output path and every alias with its expansion.

## Running

Everything runs in the **propygator conda env** — the locked departure from
`docs/experiments_venv.md`, because propygator is the system under test. Nothing
here needs the `pymsis`/`scipy` generation venv: the table figures are `.npz`
lookups, not generator runs.

```
conda run --no-capture-output -n propygator python run_all.py --list
conda run --no-capture-output -n propygator python run_all.py --only noise
conda run --no-capture-output -n propygator python run_all.py --verify --only noise
```

Use `--no-capture-output`; without it `conda run` buffers everything to the end
and a long run looks hung.

**Per-group `--verify` is the documented default.** A whole-study regenerate
re-runs Part 2 and is a scheduled multi-hour act, not a pre-commit check.
`--only <group>` is what a normal session runs; `--parse-only` on a driver is
the cheap JVM-free check.

## Conventions

One A/m convention covers every non-box run — the `Cd = 2.3` run, the fitted-Cd
run and the sphere-table run alike.

| | value | source |
|---|---|---|
| `A_ref` | **1.0013468 m²** | L1 Handbook Table 5: front panel 0.9551567 + boom 0.0461901, boom folded into the ram face |
| box | **0.7588835 × 3.6100207 × 1.3195 m** (x = height, y = length, z = width) | width read off Figure 2; height fitted so `H·W` = `A_ref`; length fitted so `2L(H+W)` = Table 5's published 15.0060150 m² |
| mass | **dry 569.914 kg + MAS1B tank gas, per satellite** | Handbook Table 4 + JPL press kit + MAS1B |
| `CD_FIT_TOL` | **0.002** | the fit's quantization rung, ~20× below the twin deviations measured |

Both geometry identities are asserted at runtime, not just printed: ram face
`H·W` = 1.00134678 against `A_ref` 1.0013468, and sides `2L(H+W)` = 15.0060149
against 15.0060150. The box is flown `InPlaneTracking(velocity_reference="ecef")`
with +Y on the wind, so every face-flow angle is constant (ram 0, leeward π,
four sides π/2).

**The length is not a physical dimension.** It preserves the *total* side area,
which is the only side quantity drag sees on a wind-aligned box; it does not
preserve the nadir/zenith vs slant split.

**This is the repository's third `A_ref`** (v0.7.2 used 1.027 m²; the retired
Chunk 0 build used 0.9551567 m²). A fitted Cd means nothing without its `A_ref`
and mass, so **never compare a Cd across two conventions** — every driver prints
the convention-free `B = Cd·A/m` beside every fitted Cd, and that is the number
that travels.

## The frozen-evidence rule

`experiments/real-world-validation/` is **imported, never edited**. This tree
imports exactly two modules from it — `common.py` and `gracefo/gnv1b.py` — both
read-only. Its windows are read in place through `--data-root`, so nothing there
is extracted, compressed, moved or deleted; `run_all.py` records that path in the
group definition so the provenance is visible.

**No `src/` change on this branch.** A contradiction with a binding contract is a
bug report exiting to the normal fix path, never a silent amendment.

## Landing the truth data (maintainer's step)

All commands run from the study root.

```
conda run -n propygator python gracefo/fetch_windows.py --all --dry-run  # URLs + budget
conda run -n propygator python gracefo/fetch_windows.py --all            # ~1.5-3 h
```

One day at a time: fetch, extract the six kept members, gzip, screen when the
window's fourteenth day lands, delete the tarball. Idempotent — an interrupted
run resumes by being re-run. Then the committed screening evidence:

```
conda run -n propygator python run_all.py --only screen              # ~1-1.5 h
conda run -n propygator python gracefo/run_screen.py --parse-only    # tier 1, no JVM
```

### Data gaps and burns in the landed windows

Some daily products legitimately carry no records; both parsers record and
report them rather than raising. Neither case is a truncated download — every
file declares `num_records`, cross-checked against the records actually read.

- **THR1B, C only** — four interior days across `storm_2024_08`, `storm_2025_05`
  and `moderate_2025_07`. C's activation rate fell from ~450/day in 2019–2022 to
  1–5/day by 2024–2025, so a day with none is ordinary. All are bracketed by an
  unchanged *cumulative* `accum_dur_orb_ctrl`, so a burn inside a gap would have
  raised the next reading. A zero-record day at a window **edge** would be a real
  hole and is escalated; none has occurred.
- **MAS1B, both satellites** — 2024-08-23, and seven consecutive days
  (2025-07-25…31) in `moderate_2025_07`. MAS1B is periodic, so these are
  telemetry outages, not quiet days. The missing days can move the window mean by
  at most 0.0102 kg (0.0017 % of total mass), far below the fit's own resolution,
  and that bound prints beside the mass on every affected window.

**Burns on GRACE-FO D.** `intense_2024_11` (2024-12-04, +288 s) and
`storm_2025_05` (2025-06-04, +214 s) carry real orbit-maintenance burns on D; C
is clean in both. Recorded call: **keep both windows** — every Part 2 run is on
C, and D is read on the ten windows only as Chunk 14's cross-tag discriminator,
which a burn makes easier rather than harder.

**Tier 2 missed both** — 0.8 % and 1.9 % departure against its 10 % bar. These
are the study's only known-positive maneuvers, so this is the one calibration
that gate will ever get, and it fails it. The bar is **not** re-fitted: the rule
normalizes by an *unfitted* `Cd = 2.3` along-track error, which over 14 days
reaches 5–166 km across the twenty satellite-windows, so a burn's signature
cannot register against it. v0.7.2 set the same 10 % against a 186.6 m signal —
the rule did not change, its denominator moved three orders of magnitude. The
burn *is* visible in the twin contrast (departure 625 m on clean C vs 1298 m on
burned D in `intense_2024_11`; 551 m vs 1425 m in `storm_2025_05`, so ~2.1× and
~2.6× on the satellite that fired), but two points are not a calibration and it
does not transfer to Swarm, whose A/B pair differs by altitude. Weigh this in the
Swarm gate decision: Swarm has no THR1B analogue and is screened by tier 2 alone.

## Data access

- **GRACE-FO daily tarballs — GFZ ISDC, no login.**
  `isdc-data.gfz.de/grace-fo/Level-1B/JPL/INSTRUMENT/RL04/<year>/gracefo_1B_<date>_RL04.ascii.noLRI.tgz`
  serves the identical JPL RL04 bundles PO.DAAC does, from an open directory,
  which is what makes `fetch_windows.py` scriptable without Earthdata auth. The
  `ACX` and `LRI` variants hold only accelerometer and laser-ranging products;
  GNV1B, MAS1B and THR1B are all in `noLRI`, so there is **no lighter route to
  THR1B and no way to screen before downloading.** Each tarball carries both
  satellites. No checksums are published, hence `fetch_windows.py`'s functional
  integrity check. Note `low_2019_12` straddles two yearly directories, so the
  URL year comes from each **day**, never from the window's `t0`.
- **Budget, measured:** 148 MB/day in, **19.23 MB/day retained** gzipped for both
  satellites. Ten windows = ~20.2 GB downloaded, **~2.6 GB retained**, ~1.5–3 h.
- **Parse cost, measured:** 0.6 s/day/satellite from the extracted `.gz` against
  4.7 s from a tarball, so a 14-day two-satellite load is ~17 s. The build plan's
  conditional `.npy` cache is therefore **not needed**.
- **Swarm SP3 — ESA, POD/RN modules.**
  <https://swarm-diss.eo.esa.int/#swarm/Level2daily/Entire_mission_data> serves
  daily `SW_OPER_SP3<A|B>COM_2__*.ZIP`. **SP3-d on GPS time in IGS14**, 10 s
  grid, V-records present and Earth-fixed — all four resolved against a
  delivered file, not documentation, per the contract's step 1. Files are cut on
  **GPS** days and named in **UTC**, so a file is found by its *second*
  timestamp. 8 days per window per satellite, which is what a 7-day arc needs
  with its `t0 + 7 d` endpoint sample. Full record in `swarm/README.md`.
- **Catalog TLEs** — per-anchor Space-Track `gp_history` pulls; object identity
  checked on every pull, since close-formation pairs are a cross-tagging hazard.
- **Raw truth files are never committed** (`data/` gitignored).

## Reference documents

Not committed — `data/reference/` is gitignored, consistent with how this repo
treats orekit-data and raw truth. Re-fetch:

- **GRACE-FO Level-1 Data Product User Handbook**, 2019-09-11 —
  <https://isdc-data.gfz.de/grace-fo/DOCUMENTS/Level-1/>
  Table 4 (per-satellite launch mass), Table 5 (faceted surface model),
  §3.2.3 (Science Reference Frame + in-flight attitude), §4.2.17 (MAS1B format).
- **JPL GRACE-FO Launch Press Kit**, "Spacecraft and Instruments" —
  <https://www.jpl.nasa.gov/news/press_kits/grace-fo/mission/spacecraft/>
  Dimensioned envelope; propellant load.

Values extracted from these live as cited literals in `gracefo/gracefo_ext_common.py`.

## Findings at a glance

Every part that produces a number resolves its pre-registered predictions
explicitly as **hit or miss**; a miss is written down as a miss.

| Part | Group | Results file | Headline |
|---|---|---|---|
| 0 — maneuver screening | `screen` | `gracefo/results_screen.txt` | **10/10 windows CLEAN on C**, both gates. Two carry a real burn on D (`intense_2024_11`, `storm_2025_05`) and are kept — see the failure rule above. |
| 1 — table noise | `noise` | `gracefo/results_table_noise.txt` | **12/12 metrics HIT.** Worst departure 6.55 % against a 20 % bar; the twin Cd ratio within 1.15 % of 1.0 against a 10 % bar. |
| 2 — drag propagations | `drag_01..10`, `swarm_01..10`, `drag_summary` | `gracefo/results_drag/`, `swarm/results_drag/`, `results_drag_summary.txt` | **5/10 windows.** In low solar activity windows, sphere Cd tends to perform slightly worse than the reference Cd - 2.3. Box table tends to be about as bad as drag off. This is in line with v0.7.2 patterns, and the tables generally do worse with Swarm. In higher solar activity windows, the tables generally perform better, with the sphere table taking the lead.|
| 3 — TLE fitting | `tle_01..10`, `tle_summary` | pending | — |

### Part 2 — drag propagations, per window

Five configurations, five propagations, one 7-day arc from each window's t0;
day 1 / day 3 / day 7 read off those five trajectories, never re-propagated.
**This part has no benchmark** — the contract states an expectation, not a
requirement, so no row below is scored and no driver flags a verdict. What
warrants a bug search is an *inversion*: a table run losing badly where drag is
strong.

Each cell carries the **day-1** removed fraction of the drag-off signal for
`Cd = 2.3` / sphere table / box table, then the in-arc fitted Cd with its
convention-free `B = Cd·A/m`. Full per-day tables are in the per-window files.

| # | window | band | GRACE-FO C | Swarm A/B |
|---|---|---|---|---|
| 1 | `low_2019_12` | low | **82 / 49 / −36 %**; Cd 1.797, B 3.00e−3 | A **70 / 39 / −71 %**, Cd 1.737, B 4.15e−3<br>B **62 / 23 / −105 %**, Cd 1.597, B 3.81e−3 |
| 2 | `low_2021_04` | low | **87 / 56 / -25 %**; Cd 2.500, B 4.17e-3 | A **80 / 53 / -45 %**, Cd 2.390, B 5.70e-3<br>B **87 / 55 / -51 %**, Cd 2.498, B 5.96e-3 |
| 3 | `low_2021_06` | low | **74 / 94 / 50 %**; Cd 2.661, B 4.44e-3 | A **81 / 99 / 34 %**, Cd 2.389, B 5.70e-3<br>B **81 / 95 / 19 %**, Cd 2.328, B 5.56e-3 |
| 4 | `moderate_2022_04` | moderate | **57 / 69 / 92 %**; Cd 3.610, B 6.03e-3 | A **65 / 73 / 73 %**, Cd 1.501 **RAILED**, B 3.58e-3<br>B **59 / 72 / 77 %**, Cd 3.464 B 8.27e-3 |
| 5 | `intense_2024_06` | intense | **90 / 96 / 36 %**; Cd 2.460, B 4.13e-3 | A **87 / 99 / 26 %**, Cd 2.565, B 6.12e-3<br>B **96 / 85 / 1 %**, Cd 2.312 B 5.52e-3|
| 6 | `storm_2024_08` | storm | pending | pending |
| 7 | `intense_2024_11` | intense | pending | pending |
| 8 | `storm_2025_05` | storm | pending | pending |
| 9 | `moderate_2025_07` | moderate | pending | pending |
| 10 | `storm_2026_01` | storm | pending | pending |

**Every RMS is per-day**: day N is the RMS over [N−1 d, N d] alone, never
accumulated from t0. A 0–N d window is dominated by its early, still
well-fitted portion and understates the error at the horizon actually read.
Day 1 is the one value both conventions share, which is what keeps the frozen
v0.7.2 "removed fraction" comparison valid — and why only the day-1 column may
be read against it.

**Swarm burns and railed Cd**: during window 4, Swarm A almost certainly
experienced a burn. This caused its 7-day fitted Cd to be impacted and railed
against the Cd = 1.5 threshold. This fitted Cd is an artifact and should not
be taken literally. This burn is not marked by the deg 5 polynomial screen for
review, although the abnormally large signal value and the 6.5% departure indicate
that something is not right. Subsequently, all Swarm windows are screened with
a vis-viva energy probe in probes/. Only Swarm A in window 4 registered for a burn
with that screen, and the results sit in probes/ as well. As an aside, the deg 5
polynomial screen incorrectly flagged Swarm B in window 3.

The **Swarm leg rests on estimated mass and geometry**, and its only maneuver
gate is the degree-5 polynomial that missed both known-real burns in Chunk 2.
Both limits are recorded on every Swarm row rather than worked around; see
`swarm/README.md`. A and B are not a twin pair (435 km against 503 km), so the
gap between their figures is an altitude difference before it is a body one.
Swarm rows share the GRACE-FO t0 unless the row says otherwise.

In the low activity windows 1-3, the standard Cd = 2.3 performed very well, while
the sphere table gives generally acceptable results. The box table loses badly
in all weak drag windows, which was expected. Window 3, which had slightly higher
activity, appears to favor the tables more than the other windows.

In the higher activity windows 4-5, the sphere table generally dominates over
the standard Cd and the box table. The box table does perform better than no drag
in these windows, with a surprisingly good performance in window 4.

### Part 1 — table noise, GRACE-FO C/D over the three inherited windows

The four contract metrics, C/D, on 3D RMS over a 1-day arc:

| window | `Cd_fit` | `RMS_Cd_fit` | `RMS_sphere` | `RMS_box` |
|---|---|---|---|---|
| `quiet_2019` | +1.15 % | +0.79 % | −2.09 % | −0.91 % |
| `active_2023` | −0.53 % | −6.55 % | −2.38 % | +2.52 % |
| `storm_2024` | −0.56 % | −0.92 % | −1.36 % | +0.77 % |

Both maneuver screens CLEAN on all six satellite-windows. The ratios are able to
leave 1.0 at all because the twins fly a 180° relative yaw that puts opposite
ends of the same tapered bus into the wind, while the model's box has
equal-area ±Y faces — so that asymmetry is present in the truth and **absent
from the model**.

The measured claim is the modest one the contract asks for: two near-identical
bodies flying through the same atmosphere under the same model produce
consistent drag results. The four ratios do not support a stronger statement,
and none is made here — in particular this part sets no error bar on a fitted
Cd, and the fitted Cd levels are not compared across A/m conventions.
