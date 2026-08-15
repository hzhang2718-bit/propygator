# Build plan - Extended validation study involving additional drag-significant propagations, TLE fitting tests, and table noise

## GRACE-FO and Swarm windows used

10 windows in total, each 13 days long. Drawn once, frozen here and in the
driver, never re-drawn at runtime.

| # | name | t0 | end (excl.) | F10.7 (range) | Ctr81 | Ap max | ap3 max | Kp max |
|---|---|---|---|---|---|---|---|---|
| 1 | `low_2019_12` | 2019-12-23 | 2020-01-05 | 71.9 (70-73) | 71.3 | 5 | 12 | 2.7 |
| 2 | `low_2021_04` | 2021-04-15 | 2021-04-28 | 77.4 (75-83) | 75.0 | 28 | 48 | 5.0 |
| 3 | `low_2021_06` | 2021-06-17 | 2021-06-30 | 82.3 (76-92) | 79.3 | 6 | 15 | 3.0 |
| 4 | `moderate_2022_04` | 2022-04-30 | 2022-05-13 | 120.0 (109-133) | 129.9 | 15 | 32 | 4.3 |
| 5 | `intense_2024_06` | 2024-06-14 | 2024-06-27 | 187.8 (167-203) | 191.1 | 17 | 39 | 4.7 |
| 6 | `storm_2024_08` | 2024-08-11 | 2024-08-24 | 243.3 (225-282) | 218.6 | **127** | 207 | 8.0 |
| 7 | `intense_2024_11` | 2024-11-23 | 2024-12-06 | 200.2 (174-225) | 201.0 | 11 | 32 | 4.3 |
| 8 | `storm_2025_05` | 2025-05-26 | 2025-06-08 | 139.2 (121-164) | 134.8 | **98** | 179 | 7.7 |
| 9 | `moderate_2025_07` | 2025-07-23 | 2025-08-05 | 147.2 (143-156) | 145.8 | 27 | 39 | 4.7 |
| 10 | `storm_2026_01` | 2026-01-13 | 2026-01-26 | 167.1 (117-232) | 145.2 | **144** | 300 | 8.7 |

Indices are window aggregates read from the same CSSI file NRLMSISE-00
consumes (`orekit-data/CSSI-Space-Weather-Data/SpaceWeather-All-v1.2.txt`):
F10.7 and Ctr81 are 13-day means, Ap/ap3/Kp are 13-day maxima. The driver
re-reads them at runtime rather than trusting this table.

### How they were selected

Candidates were all 2,887 13-day windows in the drawable span (t0 from
2018-09-01, skipping GRACE-FO commissioning, through 2026-04-26 so no window
crosses the 2026-05-09 OBSERVED boundary). Band rules were fixed before the
draw: **both** NRLMSISE-00 solar inputs in range -- window-mean daily F10.7
*and* Ctr81 -- at low <= 85, moderate 110-150, intense >= 185; non-storm bands
additionally need daily Ap <= 30 *and* 3-hourly ap <= 50 across all 13 days
(quiet in the model and in reality) and F10.7 max/min <= 1.35; >= 30 days from
every other window and from the three frozen v0.7.2 windows; <= 2 per band per
calendar year. Within each band the pick is a uniform draw, `random.Random`,
**seed 20260814**. Storm windows are not a draw -- only 8 events in the whole
span reach daily Ap >= 80, so the three are a selection from a census, chosen
for placement (below) and for spread in the F10.7 backdrop.

Two consequences to record rather than engineer away. Solar flux is bimodal
(a near-empty gap at Ctr81 86-103), so "moderate" is a transition rather than a
plateau. And **"intense" exists only in 2024** -- 17 eligible starts, all
2024-06-13 to 2024-11-28 -- so that band is confounded with mission epoch and
altitude, and the findings say so.

### Storm placement is deliberate

With every fit arc ending at day 6 and the forecast running days 6-13, the
three storms sit at different offsets so they test different things:

| window | storm at | fit arc (0-6 d) | forecast (6-13 d) | tests |
|---|---|---|---|---|
| `storm_2024_08` | day 1 | contains Ap 127 | quiet | does a storm-contaminated arc poison a calm forecast |
| `storm_2025_05` | days 3-8 | disturbed (Ap 62) | storm (Ap 98/69/60) | nonstationarity -- the `s` half of the gate |
| `storm_2026_01` | day 6 | clean (Ap <= 25) | storm (Ap 73/144/73) | the contract's mandated fit-right-before-onset case |

`storm_2026_01` satisfies the contract's pre-onset requirement exactly: the
model's onset sits at the 2026-01-19 UTC day boundary, which is where day 6
starts, so the arc is entirely pre-onset and the forecast opens at onset. No
extra days need downloading for it.

This set also separates geomagnetic storm from high solar flux, which v0.7.2
could not -- its storm window was also its highest-F10.7 window. Here the storm
backdrops are F10.7 243 / 139 / 167.

### Swarm

Swarm A/B reuse this list. Divergences (a Swarm maneuver inside a window) are
recorded per the contract, since a non-matching window confounds body with
epoch. The Swarm list cannot be finalised before the contract's 4-step format
resolution settles, because Part B may be dropped outright; sequence it as
format inspection -> Swarm window list.

### **Chunk 1: Data download, extraction, and maneuver screening**

**Goal.** Land each window's 13 days, keep only what the study reads, and gate
every window before any compute is spent on it. Windows above are provisional
until they clear this chunk.

**Download** (maintainer's step). Daily `noLRI` tarballs. GFZ ISDC serves the
identical JPL RL04 bundles from an open directory with **no login** --
`isdc-data.gfz.de/grace-fo/Level-1B/JPL/INSTRUMENT/RL04/<year>/` -- so this is
scriptable without Earthdata auth. The `ACX` and `LRI` variants hold only
accelerometer and laser-ranging products; GNV1B, MAS1B and THR1B are all in
`noLRI`. There is therefore no lighter route to THR1B and no way to screen
before downloading -- confirmed against both PO.DAAC and ISDC.

**Extract.** GNV1B + MAS1B + THR1B, both satellites, gzipped; discard the rest.
The new folder gets its own small finder that globs `.gz`; the frozen tree's
finder does not glob it and is not edited.

**Screen, tier 1 -- THR1B, at extraction time.** Pure parse, no JVM. Clean iff
`accum_dur_orb_ctrl` is unchanged across all 13 days *and* every per-record
`on_time_orb_ctrl_1`/`_2` is zero, for both satellites. Runs *before* the
tarball is discarded, so a failing window can still be slid while its source is
on disk. Exact, no threshold, and unconfounded by storms.

**Screen, tier 2 -- the contract's deg-5 polynomial**, as its own orchestrator
group over all ten windows, before any Part 2/3 run. Minutes per window against
Part 2's ~16 h. Catches what a thruster log cannot.

**Then** each window's driver re-prints the tier-1 verdict in its results
header -- free to recompute, and it keeps every results file verifiable
standalone.

**Failure handling.** A level-band window slides by the fewest whole days that
clears the burn by >= 1 day, up to +/-10 days while staying in band; failing
that, take the next seeded pick. Storm windows are never slid -- replace from
the remaining five events in the census, in a ranking fixed before screening
begins. Every retirement is recorded.

**Verify.** t0 round-trip and seam continuity as the frozen study does; both
screens CLEAN for all ten windows and both satellites, printed with the
accumulator values that justify the call.

**Checklist**
- [ ] Window 1
- [ ] Window 2
- [ ] Window 3
- [ ] Window 4
- [ ] Window 5
- [ ] Window 6
- [ ] Window 7
- [ ] Window 8
- [ ] Window 9
- [ ] Window 10


## Part 1: table noise

**Independent of Chunk 1 and cheap, so it runs first.** It reads only the three
frozen v0.7.2 windows already on disk -- zero downloads, no dependency on the
ten-window landing. Doing it ahead of Part 2 also shakes down the shared module
and the THR1B parser that Part 2 then inherits.

### **Chunk 2: table noise -- GRACE-FO C/D over the three inherited windows**

**Goal.** Re-measure the twin ratios on this contract's geometry, over the three
frozen v0.7.2 windows (`quiet_2019`, `active_2023`, `storm_2024`). Chunk 0's
numbers are superseded by the 2026-08-13 geometry and are **not** carried
forward: every run here is fresh, and the stale artifacts are deleted rather
than left in the tree to be misread.

**One chunk, not three.** Measured from Chunk 0's timings, one window costs
~7 min (per satellite: the 23-evaluation fit ~110-180 s, three 1-day
propagations ~40 s, the deg-5 screen ~20 s), so all three run in one process in
**~25-30 min** against Part 2's ~16 h. The driver still takes a window argument
for debugging; `run_all.py` invokes it once over all three so the cross-window
summary is computed rather than transcribed, and two JVM boots are saved.

**Decisions locked** (2026-08-14, maintainer):
1. **Per-satellite MAS1B mass.** Chunk 0 shared one mass between the twins, but
   that was mandated by the retired `T` contract, where the constant had to
   cancel. Mass is a reading, so each twin gets its own. The effect on the Cd
   ratio is exactly the mass ratio (0.001 / 0.102 / 0.097 %); the shared-mass
   form is one multiplication away and is printed beside it.
2. **3D RMS is the headline, alone.** Radial / along / cross go in the
   breakdown table, not the ratio table.
3. **Stale artifacts are deleted**, not duplicated around.
4. **Both screens run here**, THR1B and the deg-5 polynomial, as the contract
   mandates for every window.
5. **Qualification is reported as explicit HIT/MISS**, per window and in the
   summary. A miss is written down as a miss.

**Create.**
- `gracefo/thr1b.py` -- the tier-1 thruster parser. **Resolve the record format
  by inspecting one delivered file before writing it**, the same discipline the
  contract applies to the Swarm reader; the fields wanted are
  `on_time_orb_ctrl_1`/`_2` and `accum_dur_orb_ctrl`, which are separate from
  the twelve attitude-control thrusters. Written here against data already on
  disk so Part 2's Chunk 1 inherits a parser that has been exercised.
- `gracefo/run_table_noise.py` -- the driver.
- `gracefo/results_table_noise.txt` -- the evidence (one file for the part).

**Edit.**
- `gracefo/gracefo_ext_common.py` -- rewritten to this contract. `A_REF_M2` =
  **1.0013468** m^2 (Table 5 front panel 0.9551567 + boom 0.0461901, boom folded
  into the ram face); box **x = 0.7588835** (height) **, y = 3.6100207**
  (length)**, z = 1.3195** (width) m, matching `InPlaneTracking`'s +Y-on-wind
  axes. `CD_FIT_TOL` stays **0.002**. Scan ceilings return to v0.7.2's **5.0 /
  8.0** -- Chunk 0 raised them to 5.4/8.6 to compensate for its smaller
  `A_ref`, and at `A_ref ~ 1.0 m^2` the original values are again right (`Cd`
  and `CdA` are numerically near-equal). Delete `A_REF_BRACKET_M2`,
  `BOX_GEOMETRY_SYSTEMATIC`, `MEASURED_ANCHORS` and the whole `T` framing --
  the contract judges the tables by position error, not by `T`.
  `fit_cd_scalar`, `force_config`, `sphere_spacecraft`, `box_spacecraft` and
  the table accessors carry over unchanged.
- `run_all.py` -- drop the `twin` group, register `noise` ->
  `gracefo/results_table_noise.txt`, one invocation, `--data-root` pointed at
  the frozen tree exactly as `twin` did.
- `README.md` -- replace the A/m convention table and the Chunk 0 findings
  block; the `T`-era prose goes with them.

**Delete.** `gracefo/run_twin_checkout.py` and `gracefo/results_twin.txt`. Both
are built on the retired `A_ref` and the retired metric, and moving the shared
constants would red their `--verify` anyway. Git history keeps them, and
Checkpoint A's GO rests on ratios this chunk re-measures.

**Reuse.** Frozen and read-only: `common.py` (`ric_components`, `rms`,
`OMEGA_EARTH`) and `gracefo/gnv1b.py` (`find_window_files`, `parse_gnv1b`),
reached via `--data-root` so the frozen tarballs are read in place -- nothing
extracted, compressed, moved or deleted there. This study's `mas1b.py` is
already correct and is not touched.

**The runs.** 1-day arc from each window's t0, both satellites, per the
contract: the scalar-Cd fit, then three propagations -- fitted Cd, sphere table,
box table flown `InPlaneTracking(velocity_reference="ecef")`. No drag-off run;
the drag signal per window is Part 2's job. Window t0s are the frozen study's,
unchanged: 2019-11-14, 2023-12-20, and **2024-05-11** for the storm (skipping
the on-disk 05-10 onset day, matching both the frozen study and Chunk 0).
Screen span is 3 loaded days for both screens, so the two verdicts cover the
same window.

**Output shape.** Per window: versions + convention header (`A_ref`, box
dimensions, per-satellite mass), parse report, MAS1B masses, formation and
leader, both screen verdicts, parser checks, then per satellite the t0
round-trip, the fitted Cd with its `B = Cd*A/m` beside it, and the three runs.
Then two tables and, at the end, the cross-window summary:

- `[ratios]` -- the four contract metrics on **3D RMS**, one row each, with C/D,
  the deviation from 1.0, and HIT/MISS against its bar.
- `[values]` -- the compact numerator/denominator table: the same four
  quantities, C and D printed separately.
- `[breakdown]` -- full radial / along / cross / 3D per satellite per run, plus
  arc-mean conditions and what the shipped tables predict at them.

**Two pre-registered predictions, checkable before the run.** The geometry
change cancels exactly from a twin ratio, so `Cd_fit(C)/Cd_fit(D)` must
reproduce Chunk 0's **0.88 % / 0.41 % / 0.46 %**; and every fitted Cd must land
at Chunk 0's value scaled by 0.9551567/1.0013468 = 0.95387, i.e. **~2.032 /
3.385 / 4.047**. Missing either is a wiring signal, not a finding. The three RMS
ratios are the genuinely new numbers -- Chunk 0 never propagated the tables
per twin.

**Verify.**
- Both geometry identities asserted and printed: ram face `H*W` = 1.00134678 vs
  `A_ref` 1.0013468, side total `2L(H+W)` = 15.0060149 vs Table 5's 15.0060150.
  Both hold to 8 figures.
- t0 ITRF -> EME2000 -> ITRF round-trip <= 5e-9 m, C/D epoch grids aligned,
  grid uniformity and `|r0|` as Chunk 0 printed them.
- Both screens CLEAN for all three windows and both satellites, printed with the
  accumulator values that justify the tier-1 call.
- The two predictions above.
- `run_all.py --verify --only noise` reproduces the committed file.

**Qualification** (contract, "The design - table noise"). `Cd_fit(C)/Cd_fit(D)`
within **10 %** of 1.0 -- a failure warrants a bug search. The three RMS ratios
close to 1.0, with a departure **> 20 %** demanding attention and possibly a bug
search if no non-bug explanation is found. Record with the run: the model gives
both twins *identical* geometry (the box's +/-Y faces are equal-area, so the
180 deg relative yaw is invisible to `InPlaneTracking`), so the tapered-bus
asymmetry the contract flags as expected physics is present in the truth and
absent from the model. That is why these ratios can leave 1.0 at all.

**Checklist**
- [ ] `thr1b.py` (format resolved by inspection first)
- [ ] `gracefo_ext_common.py` rewritten; stale Chunk 0 artifacts deleted
- [ ] `run_table_noise.py` + `run_all.py` group
- [ ] quiet_2019
- [ ] active_2023
- [ ] storm_2024
- [ ] Qualification read; README updated

## Part 2: drag-significant propagations

Needs Chunk 1 (13 days landed and screened per window) and Chunk 2
(`gracefo_ext_common.py` rewritten to this contract, `thr1b.py` exercised). The
ten windows run **in table order**, one per chunk, and are independent of each
other -- `--only drag_04` is a complete unit of work.

**This part has no benchmark and none is added below.** The contract states an
expectation, not a requirement; the evidence exists to be analysed. Nothing here
is scored HIT/MISS and no driver flags a verdict.

### **Chunk 3: Part 2 apparatus (no committed evidence)**

**Goal.** Build everything the ten window chunks share, and settle the Swarm
question *before* ten chunks are written against it. This chunk commits no 7-day
evidence; it is verified on a smoke arc and on JVM-free identities.

**Create.**
- `gracefo/run_drag_window.py` -- the per-window driver. `<window>` positional;
  `--sat C|D` (default `C`), `--data-root`, `--parse-only`, `--only-config` (a
  debugging resume, never a route to committed evidence), and `--emit-fixture`
  for Deliverable 4's pinned-test literals -- carried from birth so Part 4 does
  not retrofit it.
- `swarm/swarm_common.py`, `swarm/<reader>.py`, `swarm/run_drag_window.py`,
  `swarm/README.md` -- conditional on the gate below. Box 5.0 (length, +Y on the
  wind) x 1.0 (height) x 1.0 (width) m, mass 419.0 kg, `A_ref` 1.0 m^2, every one
  of them an estimate and labelled as one in the header.
- `summarize_drag.py` -> `results_drag_summary.txt`. A pure text parse of the
  committed per-window files -- JVM-free, seconds. It runs against partial
  evidence and prints `N/10 windows`, so it is useful from Chunk 4 onward and the
  tenth window closes it for free.

**Edit.**
- `gracefo/gracefo_ext_common.py` -- add `ARC_DAYS = 7.0`, `LOAD_DAYS = 8`,
  `READ_HORIZONS_D = (1, 3, 7)`. Nothing else: Chunk 2 lands the geometry, the
  fitter, `force_config`, the scan ceilings and the table accessors.
- `run_all.py` -- register the 20 window groups and the summary, plus a small
  alias map (`drag` -> `drag_01..drag_10`, `swarm` -> `swarm_01..swarm_10`).
  Twenty bare names in `--only` is unusable otherwise.
- `README.md` -- layout, and a findings row per window.

**Reuse.** Frozen and read-only: `common.py` (`ric_components`, `rms`) and
`gracefo/gnv1b.py` (`parse_gnv1b`). This study's own: `windows.py` and the `.gz`
finder from Chunk 1, `mas1b.py`, and Chunk 2's `thr1b.py`.

**The Swarm gate.** The contract's 4-step format resolution runs here, against
one delivered file rather than against documentation, because step 4 is "drop
Part B" and that decision must be made once rather than discovered at Chunk 9.
Time scale is the known trap: Swarm products are served on GPS time, so
**GPS + 19 s = TAI via the locked route (`gracefo/gnv1b.py:44-46`), never a
hand-rolled leap table**. Checks before the reader's output is trusted: PV
magnitudes in range, epoch continuity across file seams, uniform grid, and the
one that actually catches a wrong time scale -- propagate from t0 and compare
the first sample against truth, the frozen study's 4.2e-9 m class. Then the
maintainer's download, and the polynomial-only screen (Swarm has no THR1B
analogue) produces the Swarm window list and its divergences; a divergent window
confounds body with epoch and is recorded on the row. Record from the delivered
ephemeris rather than from literature: **Swarm A and B are not a twin pair** --
B flies the higher orbit -- so an A-vs-B drag difference is an altitude
difference before it is a body difference. If the gate fails, Part B is dropped:
each window chunk loses its `swarm_NN` group, the drop is recorded in the README,
and nothing else in the study moves.

**Layout.** One results file per window per leg, in named folders so twenty files
stay legible:

```
gracefo/results_drag/window_01_low_2019_12.txt   group drag_01
swarm/results_drag/window_01_low_2019_12.txt     group swarm_01
results_drag_summary.txt                         group drag_summary
```

`_run_group` already mkdirs each output's parent, so the folders cost nothing,
and `--list` prints every group's path, which keeps the terse group names
self-documenting. The contract's "one results file per part" gives way here to
its own twice-stated per-window separability requirement;
`results_drag_summary.txt` is what restores the one-file read.

**Verify.**
- JVM-free identities, both bodies: GRACE-FO ram `H*W` = 1.0013468 and side total
  `2L(H+W)` = 15.0060150 to 8 figures; Swarm ram `1.0 * 1.0` = 1.0 m^2. Axis check
  PASS for both boxes (the wired +Y-on-wind mapping gives the smallest face-sum
  `Sigma Cd_i*A_i`). Table lookups finite at window-mean conditions.
- **Smoke arc, explicitly not evidence:** 0.5 d, drag-off and Cd = 2.3 only, on
  window 1, both legs -- proves driver, reader, RIC read and output shape end to
  end in ~2 min.
- The Swarm reader's checks above.
- `run_all.py --list` shows the 20 groups plus the summary, and the aliases
  expand.

**Checklist**
- [ ] Swarm gate resolved (format inspected, or Part B dropped and recorded)
- [ ] `run_drag_window.py` + smoke arc
- [ ] `swarm/` leg, reader checks, smoke arc
- [ ] `summarize_drag.py`, `run_all.py` groups + aliases, README

### Chunks 4-13 -- one window each, in table order

**The runs. Five configurations, five propagations, per body.** One 7-day
propagation each from the window's t0, `output_step` 60 s,
`IntegratorConfig.high_precision()`:

1. drag off
2. drag on, `Cd = 2.3`
3. drag on, in-arc scalar Cd fit over the **full 7-day** along-track RMS
4. sphere table (`VariableCd.sphere_default()`) on `A_ref`
5. box table (`BoxFaceCd.default()`), flown `InPlaneTracking(velocity_reference="ecef")`

**The 0-1 d, 0-3 d and 0-7 d numbers are read off those five trajectories, never
re-propagated** -- the contract says so, and it is the easiest way to
accidentally triple the study's cost.

**What is recorded.** Radial / along / cross / 3D RMS accumulated from t0 over
0-1 d, 0-3 d and 0-7 d, plus the same four for each of days 1-7. RIC via
`ric_components(..., earth_fixed=True)`, the frozen study's convention. 8 days
are loaded, not 7, so the t0 + 7 d endpoint sample exists; Chunk 1 already
extracted 13, so it costs parse time only.

**Header.** propygator and resolved `orekit_jpype` versions; `A_ref`, box
dimensions and the axis check; the window's MAS1B mass (Swarm: the fixed 419.0 kg,
flagged as an estimate); the re-printed THR1B verdict with the accumulator values
that justify it; window-aggregate F10.7 / Ctr81 / Ap / ap3 / Kp re-read from CSSI
at runtime. **Every fitted Cd prints `B = Cd*A/m` beside it** -- the only
convention-free number.

**The fit block prints its coarse scan**, not just the winner. Those seven
evaluations are already paid for, and the table is the only way a reader can see
whether the 7-day objective was single-welled; golden section otherwise papers
over a second well. Print bracket width, evaluation count, and an explicit
RAILED marker if the fit sits at the ceiling. Ceilings are 5.0, or 8.0 on the
three storm windows (6, 8, 10).

**Verify**, per body:
- t0 ITRF -> EME2000 -> ITRF round-trip <= 5e-9 m; seam continuity; uniform grid
- screens re-printed CLEAN (GRACE-FO both, Swarm polynomial)
- **no trajectory carries `terminated` metadata** -- a guard trip would silently
  shorten an RMS window, and 7 days through a storm is where that stops being
  hypothetical
- the drag-off signal clears the conservative floor by an order of magnitude
- the fit is not railed and its bracket is <= `CD_FIT_TOL`
- `run_all.py --verify --only drag_NN` reproduces -- a scheduled act at 20-40 min;
  `--parse-only` is the routine cheap check

**Read.** Fill the window's row in the summary, and note any Swarm divergence.

**Cost**, from Chunk 0's measured timings (a 23-evaluation 1-day fit at 110-180 s,
so 5-8 s per 1-day propagation):

| | per body | per window (3 bodies) | x10 |
|---|---|---|---|
| 4 non-fit 7-day runs | ~2-4 min | ~6-12 min | 1-2 h |
| the 7-day Cd fit (~23 evals) | ~13-23 min | ~40-70 min | 7-12 h |
| parse + screens | ~1-3 min | ~5-10 min | ~1 h |
| **total** | **~16-30 min** | **~50-90 min** | **~9-15 h** |

The fit is ~80 % of the study's compute, which is why per-window separability is
the only mitigation that matters. Measure the 8-day 1 Hz parse in Chunk 3; if it
turns out to cost minutes rather than seconds, cache the subsampled arrays as
gitignored `.npy` under `data/`.

**The expectation, recorded for reading -- not a bar.** The contract's table of
the fraction of the drag-off signal each option removed:

| removed | quiet | active | storm |
|---|---|---|---|
| Cd = 2.3 | 86 % | 67 % | 56 % |
| sphere table | 53 % | 80 % | 63 % |
| box table | -24 % | 79 % | 96 % |

`summarize_drag.py` prints each window's removed fraction beside it, with **no
verdict column**. Continuity note: those figures were built from 1-day results,
so it is the 0-1 d row that compares to them. A bounded loss where drag is weak
alongside a large gain where drag is strong is what the contract expects to see
repeated; an inversion is written into the findings as what it is.

One conversion to state before someone misreads it: putting a frozen v0.7.2
fitted Cd onto this study's convention takes **both** factors,
`(A_frozen/A_this) * (m_this/m_frozen)` = `(1.027/1.0013468) * (m_this/600.0)`,
and at GRACE-FO's MAS1B mass they very nearly cancel. So this study's fitted Cd
will land close to the frozen 1.98 / 3.32 / 3.97 in level. That is two
conventions moving in opposite directions, not a cross-study check.

Each chunk below carries the same three items: GRACE-FO C, Swarm A/B, and the
read into the summary.

### **Chunk 4: window 1 -- `low_2019_12`** (low, t0 2019-12-23, ceiling 5.0)

First full run of the apparatus: read the output shape critically here, before
the other nine inherit it.

- [ ] GRACE-FO C
- [ ] Swarm A/B
- [ ] read + summary row

### **Chunk 5: window 2 -- `low_2021_04`** (low, t0 2021-04-15, ceiling 5.0)

- [ ] GRACE-FO C
- [ ] Swarm A/B
- [ ] read + summary row

### **Chunk 6: window 3 -- `low_2021_06`** (low, t0 2021-06-17, ceiling 5.0)

- [ ] GRACE-FO C
- [ ] Swarm A/B
- [ ] read + summary row

### **Chunk 7: window 4 -- `moderate_2022_04`** (moderate, t0 2022-04-30, ceiling 5.0)

- [ ] GRACE-FO C
- [ ] Swarm A/B
- [ ] read + summary row

### **Chunk 8: window 5 -- `intense_2024_06`** (intense, t0 2024-06-14, ceiling 5.0)

Intense exists only in 2024, so this row and Chunk 10's are confounded with
mission epoch and altitude. Record it on the row rather than in the findings
alone.

- [ ] GRACE-FO C
- [ ] Swarm A/B
- [ ] read + summary row

### **Chunk 9: window 6 -- `storm_2024_08`** (storm, t0 2024-08-11, ceiling 8.0)

Ap 127 on day 1. The first window where the 7-day in-arc fit is a compromise
across storm and non-storm portions, so expect a poor fit residual and a Cd
sitting between the two -- the contract already flags that storms defeat a
scalar Cd. Read the coarse scan here.

- [ ] GRACE-FO C
- [ ] Swarm A/B
- [ ] read + summary row

### **Chunk 10: window 7 -- `intense_2024_11`** (intense, t0 2024-11-23, ceiling 5.0)

- [ ] GRACE-FO C
- [ ] Swarm A/B
- [ ] read + summary row

### **Chunk 11: window 8 -- `storm_2025_05`** (storm, t0 2025-05-26, ceiling 8.0)

Storm across days 3-8, i.e. inside Part 2's arc and across its end.

- [ ] GRACE-FO C
- [ ] Swarm A/B
- [ ] read + summary row

### **Chunk 12: window 9 -- `moderate_2025_07`** (moderate, t0 2025-07-23, ceiling 5.0)

- [ ] GRACE-FO C
- [ ] Swarm A/B
- [ ] read + summary row

### **Chunk 13: window 10 -- `storm_2026_01`** (storm, t0 2026-01-13, ceiling 8.0)

Onset sits at day 6, so Part 2's arc is entirely pre-onset -- the drag runs here
are the clean-arc counterpart to Part 3's mandated fit-right-before-onset case.
Closes `results_drag_summary.txt` at 10/10.

- [ ] GRACE-FO C
- [ ] Swarm A/B
- [ ] read + summary row

## Part 3: TLE fitting validation

## Part 4: Wrap-up and docs work
