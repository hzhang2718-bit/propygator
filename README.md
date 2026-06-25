# propygator

A Python library for orbital simulation and satellite tracking, built on [Orekit](https://www.orekit.org/).

[![CI](https://github.com/hzhang2718-bit/propygator/actions/workflows/ci.yml/badge.svg)](https://github.com/hzhang2718-bit/propygator/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Status: under construction.** The **numerical propagator (Feature 1.1)** and the
> **TLE propagator (Feature 1.3)** are implemented — propagate a state vector or a TLE
> and produce the full plot + CSV output surface (examples below). Real-time tracking
> and pass prediction (Features 1.4–1.5) are next; their APIs in the "Coming next"
> section are the *target* surface and are not implemented yet. See
> [`docs/architecture.md`](docs/architecture.md) for the full design.

## Install

Conda owns Orekit and Java; pip handles everything else. `environment.yml` is the
single source of truth and installs propygator in editable mode as part of env
creation.

```bash
git clone https://github.com/hzhang2718-bit/propygator.git
cd propygator
conda env create -f environment.yml
conda activate propygator
```

Two things to know:

- **Always activate the env before running Python.** NumPy here links Intel MKL,
  whose runtime libraries only resolve inside the activated env; an unactivated
  interpreter hard-crashes on the first linear-algebra call rather than raising a
  Python error.
- propygator uses the modern **`orekit_jpype`** wrapper, *not* the legacy
  JCC-based `orekit` package (which pulls OpenJDK 8). Most online tutorials
  reference the older one — its import boilerplate is different.

Orekit needs a data bundle (leap seconds, Earth-orientation parameters,
ephemerides) that is **not** shipped with the package. Fetch it once:

```bash
python scripts/download_orekit_data.py
```

This populates `~/.propygator/orekit-data/`. propygator's resolution order is
`OREKIT_DATA_PATH` → `~/.propygator/orekit-data/` → `./orekit-data/`.

## Quick example

Numerical propagation from a state vector, then the standard outputs:

```python
from pathlib import Path

import numpy as np
import propygator as pgr

# An ISS-like circular LEO (~420 km, 51.6 deg) in EME2000. Units are SI.
mu, r, inc = 3.986004418e14, 6_798_137.0, np.radians(51.6)
v = np.sqrt(mu / r)
initial = pgr.State(
    pgr.Epoch.from_iso("2024-01-01T00:00:00"),
    np.array([r, 0.0, 0.0]),
    np.array([0.0, v * np.cos(inc), v * np.sin(inc)]),
    pgr.Frame.EME2000,
)

# Propagate 1 day at 60-second cadence (default leo_default force model:
# gravity field + Sun/Moon + drag + SRP + tides). Returns a Trajectory.
traj = pgr.propagate_numerical(initial, duration=86400, output_step=60)

# Inspect: indexes/iterates as States, converts frames, gives osculating elements.
print(len(traj), "samples;", traj[0].to_keplerian())
itrf = traj.to_frame(pgr.Frame.ITRF)

# Plot (matplotlib figures; plot_3d returns an interactive Plotly figure).
pgr.plot_summary(traj)
pgr.plot_3d(traj).show()

# Write summary PNG + interactive 3-D HTML + CSV to a directory in one call.
pgr.export_all(traj, output_dir=Path("./run_01"))
```

The top-level `propygator` namespace exposes the common verbs; power users reach
into submodules for fine control (same pattern as NumPy or pandas). A fuller
walkthrough lives in
[`notebooks/02_numerical_propagation.ipynb`](notebooks/02_numerical_propagation.ipynb).

### TLE propagation (Feature 1.3)

Fetch a TLE by name (CelesTrak, with an on-disk cache), propagate it with SGP4/SDP4,
and run the same output stack. The result is a `Trajectory` in TEME — `.to_frame(...)`
to convert, or let the plot verbs default to EME2000:

```python
import propygator as pgr

# Fetch by friendly name (or NORAD id); or build offline from pasted lines with
# pgr.TLE.from_strings(line1, line2).
iss = pgr.fetch_tle("ISS")                        # CelesTrak + 24h cache; name set
traj = pgr.propagate_tle(iss, duration=86400, output_step=60)   # SGP4, native TEME
print(traj.frame, len(traj), "samples")           # Frame.TEME, ~1441 samples

pgr.plot_summary(traj)                             # reuses 1.1's plotting stack
pgr.export_csv(traj, "iss.csv", columns=["keplerian", "mean_anomaly"])

# Turn any row's state into a format-valid (not round-trip-faithful) TLE.
back = pgr.TLE.from_state_unfitted(traj[0], norad_id=25544)
```

### Real-time tracking (Feature 1.4)

Answer "where is it *now*, and show me." Cheap one-shot queries, an observer sky
view, and a live, self-updating dashboard — all composed over `propagate_tle`:

```python
import propygator as pgr

iss = pgr.fetch_tle("ISS")
print(pgr.current_ground_position(iss))           # live lat/lon/alt (no frame)
st = pgr.current_state(iss)                        # State in TEME (SGP4-native)

durham = pgr.GroundStation("Durham", 35.99, -78.90, altitude_m=130)
traj = pgr.propagate_tle(iss, duration=86400, output_step=60)
print(pgr.look_angles(durham, traj[0]))           # AzElRange (az / el / range)
pgr.plot_sky_track(traj, durham)                  # geometry-only polar sky view

# Live dashboard — keep the returned reference, under a GUI / %matplotlib widget backend.
anim = pgr.live_track("ISS", durham)              # 4-panel; pgr.live_track("ISS") for 3
```

A walkthrough lives in
[`notebooks/05_realtime_tracking.ipynb`](notebooks/05_realtime_tracking.ipynb).

### Coming next (Feature 1.5)

Pass prediction is designed but **not yet implemented** — this is the target
surface it will expose:

```python
import propygator as pgr

iss = pgr.fetch_tle("ISS")
durham = pgr.GroundStation("Durham", 35.99, -78.90, altitude_m=130)
passes = pgr.find_passes(                         # visible passes (1.5)
    iss, durham, start=pgr.Epoch.now(), duration=86400, min_elevation_deg=20
)
for p in passes:
    print(f"Pass at {p.culmination.to_iso()}, max el {p.max_elevation_deg:.1f} deg")
```

## Features

v1 feature set (✅ = implemented):

- ✅ **Numerical propagation** — high-fidelity orbit propagation from an initial
  state vector with configurable force models, plus the plot + CSV output surface.
- ✅ **TLE propagation** — SGP4/SDP4 propagation of TLEs (`fetch_tle` /
  `propagate_tle`), reusing the same plot + CSV output surface.
- ✅ **Real-time tracking** — current position (`current_state` /
  `current_ground_position`), an observer sky view (`look_angles` /
  `plot_sky_track`), and a live, self-updating dashboard (`live_track`).
- **TLE fitting** — least-squares fit of a TLE against a reference trajectory.
- **Ground passes + brightness** — visible passes from a ground station, with
  estimated visual magnitude.

## Notebooks

Tutorial and demo notebooks live in [`notebooks/`](notebooks/), numbered for
ordering:

- [`01_intro.ipynb`](notebooks/01_intro.ipynb) — the five-minute on-ramp.
- [`02_numerical_propagation.ipynb`](notebooks/02_numerical_propagation.ipynb) —
  the full numerical propagator (force models, spacecraft, attitude, guards, exports).
- [`03_demo.ipynb`](notebooks/03_demo.ipynb) — four contrasting orbits, end to end.
- [`04_tle_propagation.ipynb`](notebooks/04_tle_propagation.ipynb) — fetch and
  propagate a TLE with SGP4/SDP4, reusing the same output surface.
- [`05_realtime_tracking.ipynb`](notebooks/05_realtime_tracking.ipynb) — real-time
  primitives, the observer sky view, and the live tracking dashboard.

Rendered HTML versions will be posted on the projects page _(link to be added)_.

## Architecture

The full design reference — data model, module structure, conventions, and the
key architectural decisions — lives in
[`docs/architecture.md`](docs/architecture.md).

## Acknowledgments

Built on [Orekit](https://www.orekit.org/) (Apache 2.0) and
[orekit_jpype](https://gitlab.orekit.org/orekit-labs/python-wrapper), the
JPype-based Python wrapper for Orekit.

## License

MIT — see [`LICENSE`](LICENSE).
