# Build plan - Extended validation study involving additional drag-significant propagations, TLE fitting tests, and table noise

## GRACE-FO and Swarm windows used

10 windows in total, each 14 days long. Drawn once, frozen here and in the
driver, never re-drawn at runtime.

| # | name | t0 | end (excl.) | F10.7 (range) | Ctr81 | Ap max | ap3 max | Kp max |
|---|---|---|---|---|---|---|---|---|
| 1 | `low_2019_12` | 2019-12-23 | 2020-01-06 | 71.9 (70-73) | 71.3 | 8 | 18 | 3.3 |
| 2 | `low_2021_04` | 2021-04-15 | 2021-04-29 | 77.3 (75-83) | 75.0 | 28 | 48 | 5.0 |
| 3 | `low_2021_06` | 2021-06-17 | 2021-07-01 | 83.1 (76-94) | 79.3 | 13 | 27 | 4.0 |
| 4 | `moderate_2022_04` | 2022-04-29 | 2022-05-13 | 120.2 (109-133) | 129.8 | 15 | 32 | 4.3 |
| 5 | `intense_2024_06` | 2024-06-14 | 2024-06-28 | 187.4 (167-203) | 191.3 | 17 | 39 | 4.7 |
| 6 | `storm_2024_08` | 2024-08-11 | 2024-08-25 | 242.5 (225-282) | 218.8 | **127** | 207 | 8.0 |
| 7 | `intense_2024_11` | 2024-11-23 | 2024-12-07 | 198.6 (174-225) | 200.8 | 11 | 32 | 4.3 |
| 8 | `storm_2025_05` | 2025-05-26 | 2025-06-09 | 137.4 (115-164) | 134.7 | **98** | 179 | 7.7 |
| 9 | `moderate_2025_07` | 2025-07-23 | 2025-08-06 | 147.8 (143-157) | 145.8 | 27 | 39 | 4.7 |
| 10 | `storm_2026_01` | 2026-01-13 | 2026-01-27 | 166.0 (117-232) | 145.2 | **144** | 300 | 8.7 |

Indices are window aggregates read from the same CSSI file NRLMSISE-00
consumes (`orekit-data/CSSI-Space-Weather-Data/SpaceWeather-All-v1.2.txt`):
F10.7 and Ctr81 are 14-day means, Ap/ap3/Kp are 14-day maxima. The driver
re-reads them at runtime rather than trusting this table.

### How they were selected

Candidates were all 2,887 13-day windows in the drawable span (t0 from
2018-09-01, skipping GRACE-FO commissioning, through 2026-04-26 so no window
crosses the 2026-05-09 OBSERVED boundary). Band rules were fixed before the
draw: **both** NRLMSISE-00 solar inputs in range -- window-mean daily F10.7
*and* Ctr81 -- at low <= 85, moderate 110-150, intense >= 185; non-storm bands
additionally need daily Ap <= 30 *and* 3-hourly ap <= 50 across every day of
the window (quiet in the model and in reality) and F10.7 max/min <= 1.35;
>= 30 days from every other window and from the three frozen v0.7.2 windows;
<= 2 per band per calendar year. Within each band the pick is a uniform draw,
`random.Random`, **seed 20260814**. Storm windows are not a draw -- only 8
events in the whole span reach daily Ap >= 80, so the three are a selection
from a census, chosen for placement (below) and for spread in the F10.7
backdrop.

Two consequences to record rather than engineer away. Solar flux is bimodal
(a near-empty gap at Ctr81 86-103), so "moderate" is a transition rather than a
plateau. And **"intense" exists only in 2024** -- 17 eligible starts, all
2024-06-13 to 2024-11-28 -- so that band is confounded with mission epoch and
altitude, and the findings say so.

### The 13 -> 14 day extension (2026-08-15)

Windows were lengthened to 14 days after the draw, because the TLE part's
last forecast sample sits at day 13 and daily truth files cover [day, day+1),
so that sample is the first one in the fourteenth file. **The draw was not
re-run.** Re-deriving the candidate set on 14-day windows and re-drawing under
the same seed would return a different ten, discarding the storm placement
design below -- and the storms are a census selection rather than a draw, so
they would not survive it either. The extra day is a data-loading requirement,
not a change to the regime being sampled.

What was done instead: **every drawn window was re-verified against the same
band rules over its full 14 days.** Nine passed unchanged. Window 4
`moderate_2022_04` failed -- its fourteenth day, 2022-05-13 at F10.7 149.5,
pushed the F10.7 max/min flatness rule from 1.220 to **1.372** against a cap of
1.35 fixed before the draw. Under this plan's own failure rule it slid by the
fewest whole days that clears: **-1 day, t0 2022-04-30 -> 2022-04-29**, which
restores the ratio to 1.220 (Ap max 15, ap3 max 32, separation 302 d). The
slide prepends a day rather than appending one, so the window keeps its
original span and only its t0 anchor moves. Recorded as the retirement this
plan requires; no other window moved.

The band rules above are therefore stated on 14 days, while the candidate count
and the draw itself remain 13-day facts. Both readings are recorded rather than
reconciled, because reconciling them would mean re-drawing. One number in that
13-day record does not tie out and is left as drawn: 2,887 candidates implies a
t0 span starting 2018-06-01, not the 2018-09-01 the same sentence states (the
gap is exactly 92 days). Since the draw is not being re-run, it is recorded
rather than corrected.

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

**Goal.** Land each window's 14 days, keep only what the study reads, and gate
every window before any compute is spent on it. Windows above are provisional
until they clear this chunk.

**Create.** `gracefo/windows.py` (frozen window list, CSSI re-read, this study's
`.gz` finder; JVM-free), `gracefo/thr1b.py` (the tier-1 parser -- **resolve the
record format by inspecting a delivered file first**, and note the wanted fields
are separate from the twelve attitude-control thrusters),
`gracefo/fetch_windows.py`, `gracefo/run_screen.py`, and
`gracefo/results_screen.txt` -- the last **regenerated in Chunk 2** on the
rewritten geometry, so this chunk's is a rehearsal.

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

**MAS1B outages** (2026-08-20). Some days carry no MAS1B records -- one in
`storm_2024_08`, seven consecutive in `moderate_2025_07`, both satellites; real
outages, not truncated files (`num_records` is cross-checked against the body on
every file). The mass is the mean over the days that exist, never interpolated.
Tank gas varies by under 0.03 % of total mass across a whole window, so every
estimator of it lands far inside the fit's own 0.05-0.1 % resolution; the driver
prints the missing days and the bound they put on the mean beside it.

**Screen, tier 1 -- THR1B, as each window's fourteenth day lands.** Pure parse,
no JVM. Clean iff `accum_dur_orb_ctrl` is unchanged across all 14 days *and*
every per-record `on_time_orb_ctrl_1`/`_2` is zero, for both satellites. It
reads the extracted `.gz` products, not the tarballs, so discarding each tarball
at extraction time costs it nothing. Exact, no threshold, unconfounded by storms.
A day may legitimately carry no records at all (C logs 1-5 activations a day by
2024-2025); because the accumulator is cumulative, an interior gap is screened
through and is recorded rather than failed, while a gap on the window's first or
last day is escalated.

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

**A burn on D alone is recorded, not retired** (2026-08-20). The contract runs
every window on C; D is read on the ten windows only as Chunk 14's cross-tag
discriminator, which a burn makes easier, and the table-noise part that needs D
runs on the three frozen v0.7.2 windows. The screen prints `REVIEW -- burn on D`
and stops there -- the disposition is the maintainer's, never the script's.
Those burns are also the study's only known-positive maneuvers, so tier 2 is
scored against them: Swarm has no THR1B and is screened by tier 2 alone, and
this is the only calibration of that gate against a maneuver known to be real.

**Verify.** t0 round-trip and seam continuity as the frozen study does; both
screens CLEAN **for C** on all ten windows, printed with the accumulator values
that justify the call. D is screened and reported identically, but a flag on D
alone does not fail the window (see the failure rule) -- `intense_2024_11` and
`storm_2025_05` both carry a real D burn and are kept.

**The t0 round-trip bound is 5e-8 m, raised from 5e-9 m (2026-08-18).** The
round trip is pure float noise through two rotations: one ulp at GRACE-FO's
6.8746e6 m is 9.3e-10 m. Measured hourly across the three frozen windows, both
satellites (1,152 epochs): median 5.6e-9 m, worst 2.99e-8 m -- so 5e-8 m clears
the worst case by **1.7x**. The old bound sat just above the frozen study's
single observed 4.2e-9 m, which was one draw from this distribution, not a bar.

**Checklist**
- [X] Window 1
- [X] Window 2
- [X] Window 3
- [X] Window 4
- [X] Window 5
- [?] Window 6
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
- `gracefo/run_screen.py` -- delete the `A_REF CAVEAT` paragraph from the module
  docstring, and the matching note in `README.md`'s "Landing the truth data".
  Both exist only to warn that Chunk 1's tier-2 numbers predate this geometry;
  once it lands they are false. Then regenerate `results_screen.txt` on the new
  `A_ref` -- Chunk 1's is a rehearsal and is not committed evidence.

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
- t0 ITRF -> EME2000 -> ITRF round-trip <= 5e-8 m, C/D epoch grids aligned,
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
- [ ] `gracefo_ext_common.py` rewritten; stale Chunk 0 artifacts deleted
- [ ] `run_table_noise.py` + `run_all.py` group
- [ ] quiet_2019
- [ ] active_2023
- [ ] storm_2024
- [ ] Qualification read; README updated

## Part 2: drag-significant propagations

Needs Chunk 1 (14 days landed and screened per window) and Chunk 2
(`gracefo_ext_common.py` rewritten to this contract). The
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
  `READ_DAYS = (1, 3, 7)`. Named `READ_DAYS`, not `READ_HORIZONS_D`: these
  index **individual days**, not cumulative horizons, and the old name invites
  the accumulate-from-t0 read the contract forbids. Nothing else: Chunk 2 lands
  the geometry, the fitter, `force_config`, the scan ceilings and the table
  accessors.
- `run_all.py` -- register the 20 window groups and the summary, plus a small
  alias map (`drag` -> `drag_01..drag_10`, `swarm` -> `swarm_01..swarm_10`).
  Twenty bare names in `--only` is unusable otherwise.
- `README.md` -- layout, and a findings row per window.

**Reuse.** Frozen and read-only: `common.py` (`ric_components`, `rms`) and
`gracefo/gnv1b.py` (`parse_gnv1b`). This study's own: `windows.py`, the `.gz`
finder and `thr1b.py` from Chunk 1, and `mas1b.py`.

**The Swarm gate.** The contract's 4-step format resolution runs here, against
one delivered file rather than against documentation, because step 4 is "drop
Part B" and that decision must be made once rather than discovered at Chunk 9.
Time scale is the known trap: Swarm products are served on GPS time, so
**GPS + 19 s = TAI via the locked route (`gracefo/gnv1b.py:44-46`), never a
hand-rolled leap table**. Checks before the reader's output is trusted: PV
magnitudes in range, epoch continuity across file seams, uniform grid, and the
one that actually catches a wrong time scale -- propagate from t0 and compare
the first sample against truth, judged against the 5e-8 m bound above rather
than the frozen study's single 4.2e-9 m reading. Then the
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

**The day 1, day 3 and day 7 numbers are read off those five trajectories, never
re-propagated** -- the contract says so, and it is the easiest way to
accidentally triple the study's cost.

**What is recorded.** Radial / along / cross / 3D RMS for **each individual day,
days 1-7**. Nothing is accumulated from t0: per the contract, day N is the RMS
over [N-1 d, N d] alone, because a 0-N d window is dominated by its early,
still well-fitted portion and understates the error at the horizon actually
being read. There is no 0-1 / 0-3 / 0-7 d row anywhere in this study. Day 1 is
the one value the two conventions share, which is what keeps the v0.7.2
comparison below valid. RIC via `ric_components(..., earth_fixed=True)`, the
frozen study's convention. 8 days are loaded, not 7, so the t0 + 7 d endpoint
sample exists; Chunk 1 already extracted 14, so it costs parse time only.

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
- t0 ITRF -> EME2000 -> ITRF round-trip <= 5e-8 m; seam continuity; uniform grid
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
so it is the **day-1** row that compares to them -- and day 1 is identical under
both conventions, so the comparison survives the per-day rule exactly. Reading
them against day 3 or day 7 would not be like-for-like. A bounded loss where
drag is weak alongside a large gain where drag is strong is what the contract
expects to see repeated; an inversion is written into the findings as what it
is.

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

### **Chunk 7: window 4 -- `moderate_2022_04`** (moderate, t0 2022-04-29, ceiling 5.0)

The one window whose t0 moved for the 14-day extension (slid -1 d; see "The
13 -> 14 day extension" above). Its span is otherwise the drawn one.

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

Needs Chunk 1 (14 days landed and screened) and Chunk 2 (`gracefo_ext_common.py`
rewritten). Independent of Part 2's runs -- this part fits to *truth*, the two
state-path rows being the only exception. GRACE-FO C only, no Swarm.

**This is the part that carries benchmarks**, three of them, all pre-registered
and adjudicated in Chunk 18.

**Arc geometry.** `T = t0 + 6 d` is the common arc end. Every arc ends there and
they differ only in how far back they reach; left-aligning them would leave each
method forecasting from a different epoch and the part would measure arc-end
epoch rather than method. Forecast is `[T, T + 7 d]`, i.e. window days 6-13, read
at **day 1, day 3 and day 7 past T**. The longest arc is the 6 d fading-memory
one, reaching back to exactly t0 -- which, with the 7 d forecast, is why the
window is 14 days.

**Cost: ~5-10 min per window, ~1-1.5 h for the part**, dominated by the 14-day
1 Hz parse. There is no golden-section Cd fit anywhere here; 14 BatchLS fits over
<= 300 measurements each are seconds apiece. Windows therefore run **3-4 to a
chunk** rather than one, while staying separately addressable as `--only tle_NN`.

### The 13 scored configurations

| id | configuration | arc | B\* |
|---|---|---|---|
| `naive_2d` | the shipped 2 d default -- **also staging fit `fit2`** | T-2 d .. T | free |
| `arm_transplant` | hold `fit2`'s B\* on a fresh 1 d refit (carrier idiom) | T-1 d .. T | held |
| `arm_zero` | fresh 1 d refit, B\* = 0 | T-1 d .. T | held at 0 |
| `arm_fresh` | freshest 1 d fit | T-1 d .. T | free |
| `catalog` | Space-Track `gp_history`, latest epoch at or before T | -- | -- |
| `state_sphere` | numerical reference (sphere table), then fit | T-2 d .. T | free |
| `state_box` | numerical reference (box table, IPT-ecef), then fit | T-2 d .. T | free |
| `fade_tau_{0.5,0.75,1,1.5,2,3}` | 300 measurements, sigma inflated `exp(age/tau)` | T-6 d .. T | free |

**14 fits run, 13 scored.** The 3 d staging fit (`fit3`, B\* free, T-3 d .. T)
exists only to supply `s` and is not a scored row.

**The gate is evaluated at runtime, exactly as the playbook prescribes.**
`r = sigma0 * sigma(B*) / |B*|` off `fit2`; `s = |B*(fit3) - B*(fit2)| / |B*(fit2)|`.
Thresholds frozen at **r < 0.05 and s < 0.1**, carried verbatim and never
re-fitted (contract). All three arms run in every window regardless, so the
driver never needs to know which one the gate picked: **the gate -> arm mapping
lives in `summarize_tle.py`**, a JVM-free text pass that can be re-scored in
seconds without re-running a fit.

| r < 0.05 | s < 0.1 | arm |
|---|---|---|
| yes | yes | `arm_transplant` |
| no | -- | `arm_zero` |
| yes | no | `arm_fresh` |

The third row reads "freshest 1 d fit" in the playbook, ambiguous between free
and held B\*. It is named `arm_fresh` (free) on the contract's own arithmetic --
three *distinct* playbook fits, and held-zero is already `arm_zero`. The summary
prints the `arm_zero`-substituted mapping as a labelled sensitivity line; both
configurations are measured in every window either way.

**r and s come from the unweighted fits only.** Age weighting turns `sigma0` and
the covariance into weighted quantities and the thresholds do not carry over, so
the weighted fits' own diagnostics are printed but never feed the gate (contract
build caveat; `tle-fit-strategy-findings.md` sec 3, the conservative default).

**Not measured, and the findings must say so:** the log-spaced-sampling axis that
naturally pairs with short tau. The contract specifies uniform 300 measurements,
so the fading-memory result characterises the uniform-sampling version alone.

### **Chunk 14: Part 3 apparatus (no committed evidence)**

**Goal.** Build what the window chunks share and land the catalogue pull, before
ten windows are written against either. Verified on JVM-free identities and a
smoke arc.

**Create.**
- `gracefo/tle_fit_common.py` -- arc geometry (`ARC_END_DAY = 6.0`,
  `FORECAST_DAYS = 7.0`, `READ_DAYS = (1, 3, 7)`, `LOAD_DAYS = 14`); the 13
  configurations **as data**, so the driver loops and the summary keys off row
  ids; `parse_bstar`; `compute_rs`; `R_THRESHOLD = 0.05` / `S_THRESHOLD = 0.1`
  as constants carrying the no-refit note; and the age-weighted fit harness
  lifted from `tle-fit-strategy/probe2_epoch_and_weights.py`. **This is the one
  module in the study that imports fitter privates** (`_run_estimation`,
  `_MEASUREMENT_CAP`, `_SIGMA_POSITION_M`, `_SIGMA_VELOCITY_MS`,
  `_ProgressReporter`) -- documented unsupported usage, framed exactly as probe 2
  framed it, and the reason age weighting is testable with no API change.
- `gracefo/catalog_tles.py` -- the pulled two-line sets keyed by window, with
  epoch and staleness. Frozen literals; no runtime network (reproducibility rule).
- `gracefo/run_tle_window.py` -- `<window>` positional, `--data-root`,
  `--only-config`, `--parse-only`, `--emit-fixture` for Deliverable 4.
- `summarize_tle.py` -> `results_tle_summary.txt` -- JVM-free text parse of the
  committed per-window files; runs against partial evidence and prints `N/10`.

**Edit.** `run_all.py` -- register `tle_01..tle_10` plus `tle_summary`, alias
`tle` -> `tle_01..tle_10`. `README.md` -- layout and a findings row per window.

**Reuse.** Frozen: `common.py` (`ric_components`, `rms`), `gracefo/gnv1b.py`
(`parse_gnv1b`). This study's own: `windows.py` and the `.gz` finder (Chunk 1),
`mas1b.py`, `thr1b.py` (Chunk 1), and `gracefo_ext_common.py`'s `force_config`,
`sphere_spacecraft`, `box_spacecraft`, `sphere_table`, `box_table` for the two
state rows.

**Layout.**

```
gracefo/results_tle/window_01_low_2019_12.txt   group tle_01
results_tle_summary.txt                         group tle_summary
```

**The Space-Track pull** (maintainer's step, blocking). NORAD **43476**
(GRACE-FO C), `gp_history`, the latest epoch at or before T, for each of the ten
windows. Cross-tagging between close-flying objects is a known failure mode, so
each pull is checked before use: propagate it into the forecast window and
confirm the residual against **C** truth is smaller than against **D** truth. The
twins fly ~180 km apart, so a cross-tag shows as a ~200 km along-track offset
that mere staleness will not produce. Staleness (T minus TLE epoch) is recorded
on every catalogue row -- it is the known confounder in any catalogue comparison.

**Verify.**
- **Arc-end alignment**: every scored arc's last sample is T, asserted and
  printed. The structural check of the whole part.
- The gate function returns the documented arm for each corner case, and its
  thresholds assert equal to the playbook's literals.
- **tau = None no-op**: the weighted harness on an unweighted arc reproduces
  public `fit_tle_detailed` to < 1 m in-arc RMS with the same B\* -- catches
  drift in `_run_estimation` behind the private import.
- Truth coverage: the last loaded sample is at or past T + 7 d.
- Smoke arc, explicitly not evidence: window 1, three configurations
  (`naive_2d`, `arm_zero`, one tau), day-1 read only, ~2 min.
- `run_all.py --list` shows the groups and the alias expands.

**Checklist**
- [ ] Space-Track pull + cross-tag check, all 10 windows
- [ ] `tle_fit_common.py` (+ the tau = None no-op)
- [ ] `run_tle_window.py` + smoke arc
- [ ] `summarize_tle.py`, `run_all.py` groups + alias, README

### Chunks 15-17 -- the windows, in table order

**Per window.** Load 14 days of GNV1B for C at 60 s; MAS1B mass; THR1B verdict
re-printed. `T = t0 + 6 d`. Run `fit2` and `fit3`, then the 13 scored
configurations, forecasting each fitted TLE over `[T, T + 7 d]` at 60 s against
truth.

**What is recorded.** Per configuration: in-arc RMS, B\*, and radial / along /
cross / 3D RMS for **day 1, day 3 and day 7 past T** -- per-day, `[N-1 d, N d]`,
nothing accumulated, matching Part 2 and the units the playbook's own published
numbers were measured in. RIC via `ric_components(..., earth_fixed=True)`.

**Output blocks.** `[gate]` r, s, the `sigma0` and `sigma(B*)` that produced r,
and the arm the mapping selects. `[rows]` the 13 configurations, fixed-width with
a stable id column so the summary stays a plain text parse. `[catalog]` epoch,
staleness, cross-tag verdict. `[state]` each numerical reference's drift vs truth
over the arc, RMS and end -- the number that explains any degradation in those
two rows. `[breakdown]` full RIC per configuration per day.

**The two state rows.** 2 d arc ending at T, matching `naive_2d` so the delta is
purely reference-model error. Numerical propagation from the truth state at
T-2 d (ITRF -> EME2000), `force_config(drag=True)`,
`IntegratorConfig.high_precision()`, 60 s output; the box flown
`InPlaneTracking(velocity_reference="ecef")` through the external
propagate-then-fit route, which `results_fit_state_path.txt` measured as
equivalent to the native State path (rows 4 vs 5, deltas <= 1.9 m) and which is
the only route that can express that attitude. Expect degradation roughly the
size of the reference drift -- the a-priori tables cannot meet sec 1.2's
single-digit-% calibration bar. Recorded as an expectation, not a bar.

**Verify**, per window:
- every fit converged (no `TLEFitError`), in-arc RMS in the ~500-700 m SGP4
  lossiness class, anything past ~2 km flagged
- arc-end alignment re-asserted; catalogue epoch <= T and cross-tag PASS
- neither state-path reference carries `terminated` metadata
- r and s computed from `fit2`/`fit3` only, printed with their inputs
- `run_all.py --verify --only tle_NN` reproduces

**Read.** Fill the window's rows in `results_tle_summary.txt`.

### **Chunk 15: windows 1-3** -- `low_2019_12`, `low_2021_04`, `low_2021_06`

Read window 1's output shape critically before the other nine inherit it. All
three are low-activity, so expect r to fail its threshold (v0.7.2 measured
0.15-1.14 quiet) and the mapping to select `arm_zero` throughout -- the first
transfer test of the gate's quiet arm.

- [ ] window 1 (shape read)
- [ ] window 2
- [ ] window 3

### **Chunk 16: windows 4-6** -- `moderate_2022_04`, `intense_2024_06`, `storm_2024_08`

First storm window. `storm_2024_08`'s Ap 127 sits on day 1, behind both staging
arcs, so the gate sees a calm arc there; selecting a non-storm arm is the correct
call, not a miss.

- [ ] window 4
- [ ] window 5
- [ ] window 6

### **Chunk 17: windows 7-10** -- `intense_2024_11`, `storm_2025_05`, `moderate_2025_07`, `storm_2026_01`

`storm_2025_05` spans days 3-8, so its storm is inside the staging arcs and
across the forecast start -- the `s` half of the gate is what is under test.
`storm_2026_01`'s model onset sits at the 2026-01-19 UTC day boundary, which is
where day 6 starts, so its arc is entirely pre-onset and the forecast opens at
onset: the contract's mandated fit-right-before-onset case, needing no extra
download. Closes `results_tle_summary.txt` at 10/10.

- [ ] window 7
- [ ] window 8
- [ ] window 9
- [ ] window 10

### **Chunk 18: adjudication**

**Goal.** Score the three pre-registered benchmarks and write down what missed.
A text pass over the ten committed files -- no JVM, no re-runs.

**Scoring rule.** Anchor-to-anchor scatter runs 2-3x, so differences under
**1.5x** are noise (contract). Where two configurations land within 1.5x at the
same window and day, both count as correct.

**`[bench-1]` the gate + playbook beat the naive fit.** Gate-selected arm vs
`naive_2d` at days 1, 3 and 7 across ten windows = **30 comparisons**; bar is
**>= 70 % (21/30)**. Printed strict *and* under the 1.5x tie rule, so a reader
can see whether the verdict hinges on it. Stated on the row: these are ten
independent runs read at three days, not 30 independent trials.

**`[bench-2]` the gate beats any fixed arm.** For each window and day the correct
set is every arm within 1.5x of the best. The gate's success rate must be
**strictly higher** than the rate for always-`arm_transplant`, always-`arm_zero`
and always-`arm_fresh`. A miss means the gate is *redundant*, not wrong -- one arm
did the job everywhere -- which revises the playbook toward that arm. Reported
alongside the sensitivity line for the `arm_zero`-substituted mapping.

**`[bench-3]` fading memory.** Per band, the median over that band's windows of
`day-3 RMS(gate-selected arm) / day-3 RMS(fade_tau_X)`. Promotion needs a
**single** tau at **>= 1.5x in at least two bands** with **no band below 0.8x**
(none made > 1.25x worse). Default is **DEFER**. Bands are the window table's
low / moderate / intense / storm.

**`[misclass]`** every window whose gate-selected arm was not in the correct set,
listed with its r, s and the arm that won. A misclassification is the finding.

**`[post-hoc]`** labelled and separate: what r/s thresholds would have classified
this data best. A post-hoc observation, never a claim that the frozen gate passed.

**Also recorded.** Catalogue staleness against each catalogue row's outcome; the
state-path rows' degradation against their measured reference drift; every
configuration's convergence and in-arc RMS class.

**Checklist**
- [ ] `results_tle_summary.txt` closed at 10/10
- [ ] three benchmark verdicts, HIT/MISS, misses written as misses
- [ ] post-hoc block labelled
- [ ] playbook revision decision recorded (the doc rewrite is Part 4)

## Part 4: Wrap-up and docs work

Needs Chunk 18 for anything that quotes a verdict; Chunk 19 needs nothing at all.
This is the only part that touches `tests/`, `docs/`, the root `README.md` and the
notebooks, and the only part whose deliverables are sentences rather than numbers.
The guidance below is deliberately broad -- the contract's Deliverables section is
the authority on *what* must exist; this plan only sequences it.

The six contract deliverables map on as: 1 -> Chunk 20, 2 -> Chunk 21, 3 -> Chunk
22, 4 -> Chunk 23, 5 -> Chunks 24 and 25, 6 -> Chunk 19.

**Nothing here regenerates evidence or softens a verdict.** Wrap-up transcribes
committed results files; a missed benchmark is written down as missed.

### **Chunk 19: the DSMC correction (prose only)**

**Goal.** Apply the contract's "One important correction" and nothing else.
Independent of every result in this study, so it can run at any point; it is first
because it is the only wrap-up item with no dependency.

**Edit.** The four live claims the contract lists, each additively, each with a
dated note, every surrounding measured number left in place -- the two spots in the
findings doc, the frozen study README's summary row, and `CLAUDE.md` -- plus one
correction block appended to `gracefo/README.md`.

**Wording discipline: withdrawn, not refuted.** The band's lower edge traces to a
genuine DSMC study of the GRACE bus whose values were never checked against the
paper, so the correction may **not** assert the tables fall outside a correct band.
It may only say the credibility claim rested on a mis-sourced upper edge.

**Do not touch.** `gracefo_common.py:65`, `results.txt`, `run_gracefo.py`, and
`docs/history/`. No results file is regenerated.

**The rename links ride here** (maintainer-approved 2026-08-16). Chunk 21 renames
the findings doc, leaving two stale paths in the frozen study's README (lines 30
and 90). Repoint those two links as part of this chunk's prose edit and record them
as riding the sanctioned exception -- link text only, no number, no table, no code,
same file the DSMC block already lands in. `CHANGELOG.md`'s mention is a historical
entry and stays as written. The rename is a certainty, not a contingency, so the
new name goes in even if this chunk runs first.

**Verify.** The frozen study's `run_all.py --verify` still passes. That is the
proof the correction stayed additive.

**Checklist**
- [ ] four live claims corrected, additively and dated
- [ ] `gracefo/README.md` correction block
- [ ] two frozen-README link paths repointed
- [ ] frozen `--verify` green

### **Chunk 20: evidence surface close-out**

**Goal.** Deliverable 1 -- every results file committed and regenerable by one
orchestrator command, with the per-window separability the contract asks for twice.

**Edit.**
- `run_all.py` -- final group set (Chunk 1's screen group, `noise`, `drag_01..10`,
  `swarm_01..10`, `drag_summary`, `tle_01..10`, `tle_summary`) plus the aliases;
  `--list` prints every group with its output path; `--verify` masks wall-clock
  lines and matches the committed files' line endings.
- `experiments/extended-validation/README.md` -- finalized: layout, the window
  table, how to regenerate a single window, and a findings-at-a-glance table with
  one row per part.

**Record the verify policy in that README.** A whole-study `--verify` re-runs Part
2 and is a scheduled multi-hour act, not a pre-commit check. `--only <group>` is
what a normal session runs and `--parse-only` is the cheap check. Say it there so a
later reader does not launch the full sweep casually.

**Verify.** `--list` complete and every listed path exists; one group per part
re-verified; no results file carries a wall-clock-dependent line `--verify` cannot
mask.

**Checklist**
- [ ] `run_all.py` groups, aliases, `--list`, `--verify`
- [ ] study README finalised incl. findings-at-a-glance and the verify policy

### **Chunk 21: findings -- append to the existing doc, then rename**

**Goal.** Deliverable 2. This study does **not** get its own findings document. Its
findings are appended to `docs/real-world-validation-findings.md`, which is then
renamed **`docs/validation-findings.md`** -- one validation record for the
repository rather than two that have to be read together.

**Rules.**
- **Continue the section numbering**, new sections from **section 9**. Sections 1-8
  keep their numbers so every existing citation into section 3 / 4 / 5 still
  resolves.
- **The v0.7.2 numbers are not edited.** Where this study re-scopes an earlier
  claim -- the single-satellite readings in sections 4 and 5 above all -- the
  re-scope is an additive forward pointer, never a rewrite.
- Rewrite only the title and the status block, to cover both studies and to name
  the archived contract and build plan.

**What the new sections cover** (guidance, not an outline to transcribe): why the
study exists and what it attacks; truth provenance for the new windows, including
the Swarm reader's format and time-scale resolution or Part B's drop; the window
table and how it was drawn; one section per part; every pre-registered benchmark
resolved HIT or MISS, with misses written as misses; the post-hoc threshold block
labelled as post-hoc; the contract's "What this study does not claim" carried over,
so no statement of the form "the tables are off by X %" appears anywhere; honest
caveats -- at minimum the intense band's 2024-only epoch confound, any window where
Swarm diverged, the uniform-sampling scope of the fading-memory result, and the
daily-Ap storm smearing; and the named follow-ons.

**Fix broken references**: this touches v0.7.2 frozen material and likely others.
First conduct a blast radius scan, then update the references. This is a sanctioned
edit to the frozen docs.

**Verify.** Every number traceable to a committed results file; sections 1-8
unchanged apart from the additive re-scoping notes (diff-checkable); the
fading-memory verdict stated with its bar quoted rather than paraphrased.

**Checklist**
- [ ] new sections appended from section 9
- [ ] sections 1-8 numbers intact; re-scoping notes additive
- [ ] renamed to `docs/validation-findings.md`; title + status block rewritten

### **Chunk 22: playbook revision**

**Goal.** Deliverable 3. This study exists partly to invalidate the playbook, so
the revision follows Chunk 18's verdict rather than defending the recipe.

**Edit `docs/tle-fitting-playbook.md`.** Evidence base restated (ten windows across
four activity bands, GRACE-FO C for Part 3); the r/s thresholds validated **or
corrected**; any recalibration presented as post-hoc and labelled as such; the
third arm's free-vs-held ambiguity resolved the way the study measured it; and the
gate's domain of validity written down -- r certifies in-arc observability, s
catches nonstationarity, neither certifies forward validity.

**Also.** `docs/tle-fit-strategy-findings.md` -- record which of its open routes
this study executed and which survive. Archive it to `docs/history/` if only the
refit-cadence route is left; otherwise trim it to what remains. Its pre-registered
fading-memory bar is resolved in Chunk 18 and is quoted here, not restated.

**Checklist**
- [ ] playbook revised to the measured verdict
- [ ] `tle-fit-strategy-findings.md` closed, trimmed, or archived

### **Chunk 23: pinned regression tests**

**Goal.** Deliverable 4. These exist to catch a wiring regression, not to freeze a
physical result.

**Create** new test files rather than editing the v0.7.2 pins, which stay exactly
as they are. Roughly one per part: a twin-ratio pin from Part 1, a drag-relationship
pin from one Part 2 window, and a gate-classification pin from Part 3.

**Policy, inherited verbatim.** Measured value x a margin generous enough to absorb
an orekit-data refresh, and **relationships over absolutes** -- the tables beat
drag-off in a strong-drag window, the twin ratio sits near 1.0, the gate classifies
a named window as it did -- rather than an RMS pinned to three figures.

**Mechanics.** Fixtures are in-file literals emitted by the drivers'
`--emit-fixture` flags (carried from Chunks 3 and 14), so no test reads truth data
or the network. Any JVM-touching test acquires the JVM through the `orekit`
fixture -- that is how `conftest.py`'s ordering hook knows to schedule it after the
no-JVM guards.

**Verify.** Full `pytest` green; each new test fails when its fixture literal is
perturbed; added suite runtime in seconds, not minutes.

**Checklist**
- [ ] Part 1 pin
- [ ] Part 2 pin
- [ ] Part 3 pin
- [ ] full suite green, v0.7.2 pins untouched

### **Chunk 24: reconciliation**

**Goal.** Deliverable 5, everything except the showcase.

**Edit.**
- Root `README.md` "Validation" -- the evidence base is no longer a single
  satellite; refresh the drag and TLE bullets and repoint the findings link.
- `notebooks/07_tle_fitting.ipynb` section 9 -- hand-transcribed playbook numbers,
  updated by hand per the repo convention.
- `CLAUDE.md` -- the study moves from in-flight to shipped: release history,
  validation-evidence section, source-of-truth list (contract and build plan
  archived, findings doc renamed), and the follow-on state.
- **Inbound-link sweep for the rename** -- grep for the old filename and repoint
  every live reference. Expected: root README, `CLAUDE.md`, both notebooks, and the
  frozen study README (done in Chunk 19). `CHANGELOG.md` and anything under
  `docs/history/` are historical records and stay as written.

**Checklist**
- [ ] README validation section
- [ ] notebook 07 section 9
- [ ] `CLAUDE.md`
- [ ] rename sweep clean (no live reference to the old path)

### **Chunk 25: `notebooks/00_showcase.ipynb`**

**Goal.** The showcase gets its own chunk, because it is the one artifact rendered
outside the repository.

**The maintainer provides the details of this edit at build time.** Do not infer
them from the findings doc -- the showcase is a curated tour, and which numbers it
carries is an editorial call rather than a transcription.

**Constraints that hold whatever the edit turns out to be.** The notebook is
deliberately offline and deterministic -- pinned TLE, explicit `start=`, no
`fetch_tle`, no `Epoch.now()`, writes no files -- so the export reproduces exactly;
its validation numbers are hand-transcribed and updated by hand; `nbstripout` strips
outputs on commit.

**Export** A fresh static HTML export if any number moved -- the export
tooling is deliberately not committed and the rendered HTML lives in the website
repo.

**Checklist**
- [ ] edit details received from maintainer
- [ ] showcase updated; runs offline and deterministically end to end
- [ ] export needed? recorded either way

### **Chunk 26: release readiness and archival**

**Goal.** Leave the branch mergeable and the docs tree honest.

**Run.** `pre-commit run --all-files`; `conda run -n propygator pytest`; per-group
`run_all.py --verify` across the three parts, plus the frozen study's `--verify`.

**Archive.** `docs/extended-validation-updated.md` (the contract instructs its own
archival) and this build plan, both to `docs/history/`.

**Record the fading-memory verdict.** DEFER closes the question and the sweep stays
committed as a recipe. PROMOTE ships this study **without** the API change; the
`measurement_decay_tau` amendment is then its own feature branch off `main`, with
its own minor release.

**Maintainer's.** Version bump to `v0.8.1` and the editable reinstall that bump
requires, the CHANGELOG entry, the PR, the squash-merge, the tag. If anything landed
on `main` during the study, the study is re-run before the merge.

**Checklist**
- [ ] hooks, full suite, per-group verifies, frozen verify
- [ ] contract + build plan archived to `docs/history/`
- [ ] fading-memory verdict recorded (DEFER default)
- [ ] handed to maintainer for version bump, CHANGELOG, PR, tag
