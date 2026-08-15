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

## Part 3: TLE fitting validation

## Part 4: Wrap-up and docs work
