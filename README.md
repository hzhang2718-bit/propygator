# propygator

A Python library for orbital simulation and satellite tracking, built on [Orekit](https://www.orekit.org/).

[![CI](https://github.com/hzhang2718-bit/propygator/actions/workflows/ci.yml/badge.svg)](https://github.com/hzhang2718-bit/propygator/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Status: under construction.** The architecture is fully designed (see
> [`docs/architecture.md`](docs/architecture.md)) and the package groundwork is in
> place. The feature APIs in the quick example below are the *target* surface and
> are being implemented.

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

```python
import propygator as pgr

# Pull ISS TLE
iss = pgr.fetch_tle("ISS")

# See where it is right now (returns a GeodeticPosition directly)
print(f"Lat/lon: {pgr.current_ground_position(iss)}")

# Propagate forward 1 day with SGP4 at 60-second output cadence
traj = pgr.propagate_tle(iss, duration=86400, output_step=60)

# Plot the ground track
pgr.plot_ground_track(traj).show()

# Find tonight's visible passes from Durham
durham = pgr.GroundStation("Durham", 35.99, -78.90, altitude_m=130)
passes = pgr.find_passes(
    iss, durham,
    start=pgr.Epoch.now(),
    duration=86400,
    min_elevation_deg=20,
)

for p in passes:
    print(f"Pass at {p.culmination.to_iso()}, max el {p.max_elevation_deg:.1f}°, "
          f"mag {p.peak_magnitude:.1f}")
```

The top-level `propygator` namespace exposes the common verbs; power users reach
into submodules for fine control (same pattern as NumPy or pandas).

## Features

Planned v1 feature set:

- **Numerical propagation** — high-fidelity orbit propagation from an initial
  state vector with configurable force models.
- **TLE propagation** — SGP4 propagation of TLEs.
- **TLE fitting** — least-squares fit of a TLE against a reference trajectory.
- **Real-time tracking** — current position, ground track, and altitude for a TLE.
- **Ground passes + brightness** — visible passes from a ground station, with
  estimated visual magnitude.

## Notebooks

Tutorial and demo notebooks live in [`notebooks/`](notebooks/), numbered for
ordering. Rendered HTML versions will be posted on the projects page _(link to be
added)_.

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
