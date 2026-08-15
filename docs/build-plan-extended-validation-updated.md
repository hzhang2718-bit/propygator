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

Important points
- Rewrite old chunk 0 code according to updated contract
- Do each window separately (3 chunks) unless they are light
- Use CD_FIT_TOL = 0.002
- Record the following metrics:
    - Cd_fit(C)/Cd_fit(D)               in sample, 1D
    - RMS_Cd_fit(C)/RMS_Cd_fit(D)       propagated on fitted Cd, 1D
    - RMS_sphere(C)/RMS_sphere(D)       propagated, 1D
    - RMS_box(C)/RMS_box(D)             propagated, 1D
    - All the numerators and denominators above separately in a separate, compact table
- Use new GRACE-FO dimensions from updated contract
- Everything is re-run, do *not* use old chunk 0 results
- Examine the results to see if they pass the qualification in the contract

## Part 2: drag-significant propagations

## Part 3: TLE fitting validation

## Part 4: Wrap-up and docs work
