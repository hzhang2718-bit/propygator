# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.0] - 2026-07-11

### Added

- `fit_tle` and `fit_tle_detailed` functions, which take a state or a trajectory
  to a fitted tle through iterative fitting.
- Experiment demonstrating general success of the fitting procedure, as well as
  how fixed-point refinement can produce a seed that converges faster.
- `TLEFitError` and progress reporting wired to `fit_tle` and `fit_tle_detailed`.

## [0.6.0] - 2026-07-09

### Added

- Satellite pass finder from TLE data. The pass finder takes in TLE and outputs 5
  possible results: a pandas dataframe, sky view with passes labeled by brightness,
  pass timeline graphic, pass CSV export, and pass ICS export.

## [0.5.0] - 2026-07-07

### Added

- BoxFaceCd experiments demonstrating how it may be useful, but only for satellites
  where shear drag (previously unaccounted for) is highly significant.
- BoxFaceCd table that is shipped with the experiment, supporting BoxFaceCd.default().
- BoxFaceCd arguments that can be incorporated into propagate_numerical, including a
  default one for the shipped table and options for users to use their custom tables.
- The option to use ECEF velocity as the reference velocity in InPlaneTracking. An
  accompanying study shows that the slightly different reference velocity makes a
  minor but real impact.
- Gravity perturbations from Solar System planets now available in the force model.
- Printed progress messages that appear while the numerical propagator runs. These
  are on by default and can be turned off.
- The ability to display U.S. time zones in the live dashboard. UTC is still the
  default.

### Changed

- Instead of erasing every frame, TLE live dashboard now preserves zoom.

### Removed

- IncidenceVariableCd skeleton has been removed and replaced with BoxFaceCd table
  because solar array shadowing makes simple Cd table interpolation impossible.

### Fixed

- Elevation markers in live dashboard's sky view are corrected to have 90 degrees
  correspond to zenith.

## [0.4.0] - 2026-06-24

### Added

- Current state and position fetching functions running on TLE.
- Topocentric kernel for plotting sky views (geometric only for now).
- Real-time satellite tracking dashboard based on TLE propagation.

## [0.3.0] - 2026-06-22

### Added

- TLE propagation feature using Orekit's SGP4/SDP4 algorithm. Trajectories from TLE
  propagations are compatible to be plotted in the same way as numerical integrator
  results.
- Mean anomaly added as an option to the exported CSV.
- Data-fetching capabilities from CelesTrak, complemented with a list of popular
  satellites whose TLE can be fetched from name.
- New Jupyter notebook on the TLE propagator feature.

### Changed

- PropagationError rewired to account for numerical integration errors and TLE propagation
  errors separately. Separate NumericalPropagationError and TLEPropagationError now in
  place.
- Propagation input checks are promoted into core with generalized error messages.

## [0.2.0] - 2026-06-19

### Added

- Nadir-pointing attitude now supports ECEF (ground velocity) velocity
  tracking.

### Changed

- Plot end markers are updated. For ground track, the end marker is now a
  directed triangle instead of star. For 3D plots, the end marker is now
  a directed cone instead of diamond.

## [0.1.0] - 2026-06-17

### Added

- Configuration and environment files. Pinned Python 3.11, OpenJDK 17, and
  orekit_jpype 13.1.x. These are the basis of all future code.
- Lazy JVM init process, setting up and securing the tricky Python-Java interface for
  all future code.
- Set up pre-commit, lint, and CI as a sign of maintenance and care.
- Created core data types, including Epoch, Frame, State, KeplerianElements,
  Orientation, Trajectory, and TrajectoryMetadata. These types will be used by almost all,
  if not all future features. These ones are especially relevant to the numerical
  propagator feature.
- The numerical propagator feature, which is the first and most important feature of
  propygator. This major build included setting up conversion functions and propagation
  tools built upon Orekit.
- A table which takes altitude and atmospheric density to a Cd value, which can be
  interpolated. The table provides variable Cd when the Orekit atmosphere pipeline makes
  Sentman impossible to cleanly implement. An experiment folder which contains code
  that justifies this practice was also added.
- Structured exports interface, involving CSV, matplotlib graphs, and plotly graphs
  exports. These are used extensively by the numerical propagator and are good for future
  use by other features as well.
- Altitude guards based upon the Cd table, Knudsen number floor (supported by and
  cross-checked against justification in experiments folder), Earth-Moon gravity
  parity, ground impact, and user-tuned altitude limits.
- Created Jupyter notebooks folder for casual users to interact with propygator.
