# Swarm leg — Part 2's limited-information stress case

Swarm A and B run the **identical five drag configurations** the GRACE-FO leg
runs, over the same ten frozen windows. The difference is what is known about
the spacecraft: GRACE-FO's geometry is traceable to the L1 Handbook, and
Swarm's is not. That is the point of this leg, not a defect in it — it measures
what propygator does when a body's properties are estimates.

## The format, resolved against a delivered file

The contract requires the format settled **by inspection of one delivered file,
not documentation** (Part B, step 1). What ESA's POD/RN module serves for these
windows, read off
`SW_OPER_SP3ACOM_2__20191222T235942_20191223T235942_0201.ZIP`:

| | finding |
|---|---|
| format | **SP3-d**, one satellite per file, `V` records present, 8640 epochs/day on a **10 s** grid, header count matching the body |
| time system | **GPS** (the `%c` field) → the locked leap-free route, GPS + 19 s = TAI |
| frame | **IGS14**, an ITRF realization → `Frame.ITRF` |
| satellites | Swarm A = `L47` (~435 km), Swarm B = `L48` (~502 km) |

This is contract **step 2** — an SP3 product is available, so it is preferred,
and `swarm_sp3.py` is a thin wrapper over the frozen `lageos/sp3.py` rather than
a new reader. The one thing that parser cannot do is open a `.ZIP`; everything
else — the GPS→TAI conversion, the km→m and dm/s→m/s scaling, the column
layout — is reused unchanged. The frozen module is imported, never edited.

**The time-scale trap is closed by measurement, not assumption.** Reading these
files as UTC costs ~18 s, or ~137 km of pure along-track error, and every
magnitude, seam and grid check stays clean while it happens. The check that
catches it: Swarm's t0 must land on GPS midnight of the window's `t0`, asserted
per run. In window 1 it lands at `2019-12-23T00:00:19 TAI` — bit-identical to
GRACE-FO C's t0, offset `+0.000 s`.

**The V-records are Earth-fixed**, measured rather than assumed: differentiating
the positions reproduces them to `1e-4 m/s`, against a 20–500 m/s gap between
the Earth-fixed and inertial conventions. So velocities go straight in as
GNV1B's do, and no Lagrange differentiation is needed.

**The files are cut on GPS days and named in UTC.** A file tagged
`20191222T235942_20191223T235942` holds GPS day `2019-12-23`: in 2019 GPS runs
18 s ahead of UTC, so `23:59:42 UTC` *is* `00:00:00 GPS` of the next day. Every
file starts exactly 86400 s after the previous one (verified at every seam), so
the file for a window day is found by its **second** timestamp, never its first.

## What is estimated, and what that costs

| | value | source |
|---|---|---|
| box | **1.0 × 5.0 × 1.0 m** (x = height, y = length on the wind, z = width) | ESA mission description; sources disagree |
| `A_ref` | **1.0 m²** — the ram face | "ram area ~1 m²", square shape assumed |
| mass | **419.0 kg** | drag mass with half the propellant load |

An orbit residual constrains only `ρ·Cd·A/m`, so the **fitted-Cd row absorbs any
error in these** and cannot be read as a body property. The two **table** rows do
not absorb it: they are directly proportional to the area and mass above, so a
table-vs-truth gap on this leg conflates geometry error with model error in a way
the GRACE-FO leg's Handbook-traceable geometry does not. Read the Swarm table
rows accordingly.

The mass is a fixed literal — identical for both satellites and every window.
GRACE-FO reads its per-window mass from MAS1B; Swarm has no such product here.

**A and B are not a twin pair.** B flies ~70 km higher, measured off the
delivered ephemerides rather than taken from literature, so an A-vs-B difference
is an altitude difference before it is a body difference. They are never read as
a twin ratio the way GRACE-FO C/D are in Part 1.

## The maneuver screen, and its limits

Swarm has no THR1B analogue, so the **degree-5 polynomial is the only gate** —
and it went 0-for-2 against the two known-real burns in Chunk 2 (0.8 % and 1.9 %
against its 10 % bar), because it normalizes by an unfitted `Cd = 2.3`
along-track error of tens of kilometres. Its verdict is printed on every run and
recorded as **weak evidence, not a quiet window** (contract amendment
2026-08-21). An undetected Swarm maneuver stays a live risk on every row.

The bar is **not** re-fitted — the contract forbids re-fitting a pre-registered
threshold and reporting success. To pay for the screen without a sixth
propagation, the `Cd = 2.3` run is propagated over the full 8-day load and does
double duty; every RMS is still read over the 7-day arc alone.

## Truth data

Downloaded by the maintainer from the POD/RN modules of
<https://swarm-diss.eo.esa.int/#swarm/Level2daily/Entire_mission_data>, into
`data/swarm/<window>/` — 8 daily `.ZIP` files per satellite, which is what a
7-day arc needs with its `t0 + 7 d` endpoint sample. Raw truth is never
committed (`data/` is gitignored).

## Running

```
conda run --no-capture-output -n propygator python run_all.py --only swarm_01
conda run -n propygator python swarm/run_drag_window.py low_2019_12 --parse-only
```

`--parse-only` is the cheap JVM-free check. `--smoke` runs a short
two-configuration arc that prints its own NOT-EVIDENCE banner; it proves the
driver end to end and must never be committed as a result.
