# propygator

A Python library for orbital simulation and satellite tracking, built on [Orekit](https://www.orekit.org/).

[![CI](https://github.com/hzhang2718-bit/propygator/actions/workflows/ci.yml/badge.svg)](https://github.com/hzhang2718-bit/propygator/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Status: v1 feature-complete.** All five v1 features are implemented — the
> **numerical propagator (1.1)**, **TLE fitting (1.2)**, **TLE propagator (1.3)**,
> **real-time tracking (1.4)**, and **ground-pass prediction (1.5)** — each with
> its plot + CSV/output surface (examples below). See
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
# 70x70 gravity + Sun/Moon third body + drag + SRP; tides, relativity, and a
# lumped seven-planet third body are opt-in booleans). Returns a Trajectory.
# Prints throttled progress lines to stderr while it runs (silence with
# progress=False, or pass a callable to drive your own bar).
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
# Readout clock in US civil time (DST-correct; default stays UTC):
# pgr.live_track("ISS", durham, tz=pgr.USTimeZone.EASTERN)
```

A walkthrough lives in
[`notebooks/05_realtime_tracking.ipynb`](notebooks/05_realtime_tracking.ipynb).

### Pass prediction (Feature 1.5)

Find a satellite's visible passes over a ground station — sunlit, observer in
darkness — with an estimated visual magnitude, and turn them into a table, a
calendar file, or a sky chart:

```python
import propygator as pgr

iss = pgr.fetch_tle("ISS")
durham = pgr.GroundStation("Durham", 35.99, -78.90, altitude_m=130)

passes = pgr.find_passes(iss, durham, 86400, min_elevation_deg=20)  # next 24 h

df = pgr.passes_to_dataframe(passes, tz=pgr.USTimeZone.EASTERN)     # tz-aware table
print(df[["rise", "max_elevation_deg", "peak_magnitude"]])

pgr.export_passes_ics(passes, "iss_passes.ics", name="ISS")        # add to a calendar
pgr.plot_sky_chart(iss, durham, passes)                            # where to look
```

### TLE fitting (Feature 1.2)

Re-express any reference orbit — a high-fidelity numerical propagation, a
user-assembled trajectory, or another TLE's output — as a shareable TLE, via
Orekit's batch least squares over the SGP4 mean elements (+ B\*). The faithful
sibling of `TLE.from_state_unfitted`: this one actually round-trips.

```python
import propygator as pgr

# Fit a TLE to 2 days of high-fidelity propagation from `initial` (the quick
# example's state — the State path builds the reference internally with
# leo_default physics). Or pass any Trajectory to fit it directly.
result = pgr.fit_tle_detailed(
    initial, fitting_span=86400 * 2, norad_id=90001, name="MYSAT"
)
fitted = result.tle                      # exactly what fit_tle(...) returns
print(fitted.line1)
print(fitted.line2)
print(f"converged in {result.iterations} iterations, rms {result.rms_m:.0f} m")

# Round-trip check: propagate the fitted TLE back over the fitted span.
back = pgr.propagate_tle(fitted, 86400 * 2, output_step=600, start=initial.epoch)
```

**The fit is inherently lossy** — SGP4 is a simplified model, so a full-force
numerical orbit can never be reproduced exactly. Expect a few hundred meters
RMS over a 2-day LEO span (~495 m in our validation fits); an SGP4-generated
reference is recovered essentially exactly. Non-convergence raises
`TLEFitError` (no partial result). A walkthrough lives in
[`notebooks/07_tle_fitting.ipynb`](notebooks/07_tle_fitting.ipynb).

**Fit diagnostics, and what to do with them.** `fit_tle_detailed` also returns
the estimator's `covariance` / `sigmas` / `sigma0` (Cartesian TEME at the fitted
epoch, plus `BSTAR`) and the signed residual structure `residuals_ric_m`
(radial / along-track / cross-track) alongside `velocity_residuals_ms`. These
matter because **in-arc RMS is an anti-signal for forward prediction** — a free
B\* on a short arc happily absorbs along-track error into a garbage drag
coefficient, and B\* handling alone is the difference between ~1 km and 50+ km
of drift at +3 days. [`docs/tle-fitting-playbook.md`](docs/tle-fitting-playbook.md)
turns two numbers off those diagnostics into a gate that picks the fitting
strategy, measured against GRACE-FO truth across quiet / active / storm drag
regimes.

## Features

The v1 feature set (all implemented):

- **Numerical propagation** — high-fidelity orbit propagation from an initial
  state vector with configurable force models, plus the plot + CSV output surface.
- **TLE propagation** — SGP4/SDP4 propagation of TLEs (`fetch_tle` /
  `propagate_tle`), reusing the same plot + CSV output surface.
- **Real-time tracking** — current position (`current_state` /
  `current_ground_position`), an observer sky view (`look_angles` /
  `plot_sky_track`), and a live, self-updating dashboard (`live_track`).
- **Ground passes + brightness** — visible passes from a ground station with
  estimated visual magnitude (`find_passes`), plus table / CSV / iCalendar / sky-chart
  / timeline output (`passes_to_dataframe`, `export_passes_csv`, `export_passes_ics`,
  `plot_sky_chart`, `plot_pass_timeline`).
- **TLE fitting** — least-squares fit of a TLE against a reference trajectory
  (`fit_tle`, plus `fit_tle_detailed` for the fit diagnostics), with the
  lossiness quantified and non-convergence raised honestly.

## Validation

Beyond the test suite, each surface is anchored to an independent external
reference — including **measured orbits** (cm-level ILRS laser ranging and
GRACE-FO GPS reduced-dynamic truth), the one oracle that can't share a wiring
misconception with the code's own tests:

- **SGP4/SDP4** — Vallado's AIAA 2006-6753 reference vectors (test-pinned).
- **Pass prediction** — Skyfield cross-check, agreement < 2 s / < 1° over a
  10-pass ISS table (test-pinned).
- **Numerical propagator** — LAGEOS-2 vs. ILRS precise orbits: **3.6 m RMS
  after one day** on conservative forces, with every force toggle's ablation
  signature verified against its computed order.
- **Drag stack** — GRACE-FO vs. GNV1B orbits across solar-quiet, solar-max,
  and Gannon-storm conditions: a single fitted Cd collapses the along-track
  residual to **1.9–6.4 m/day** (calm conditions); the remainder is
  thermospheric-density uncertainty, quantified.
- **TLE fitter** — fits measured GRACE-FO truth at ~630 m RMS and predicts at
  **operational-catalog parity** (0.8–2.1× the Space-Track TLE over +3 days).

Details, provenance, and honest caveats:
[`docs/real-world-validation-findings.md`](docs/real-world-validation-findings.md);
the committed evidence lives under
[`experiments/real-world-validation/`](experiments/real-world-validation/).

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
- [`06_pass_prediction.ipynb`](notebooks/06_pass_prediction.ipynb) — find visible
  passes, tabulate and export them (CSV / iCalendar), and plot the sky chart + timeline.
- [`07_tle_fitting.ipynb`](notebooks/07_tle_fitting.ipynb) — fit a shareable TLE
  to a numerical trajectory, quantify the lossiness, and read the fit diagnostics.

Rendered HTML versions will be posted on the projects page in the future.

## Architecture

The full design reference — data model, module structure, conventions, and the
key architectural decisions — lives in
[`docs/architecture.md`](docs/architecture.md).

## Development

Releases are cut from short-lived branches, squash-merged to `main` and
annotated-tagged (see [`docs/release-process.md`](docs/release-process.md)).
From **v0.7.2** onward this runs through GitHub Pull Requests with CI; earlier
releases were squash-merged locally.

## Acknowledgments

Built on [Orekit](https://www.orekit.org/) (Apache 2.0) and
[orekit_jpype](https://gitlab.orekit.org/orekit/orekit_jpype), the
JPype-based Python wrapper for Orekit.

## License

MIT — see [`LICENSE`](LICENSE).
