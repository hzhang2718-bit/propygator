# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.8.1] - 2026-09-06

### Added

- An extended validation study that examines the numerical propagator during
drag-significant runs and tests propygator's TLE fitting mechanisms and playbook.
- Ran 1-day arc propagations on the GRACE-FO twin using fitted Cd, sphere Cd, and
box Cd. The resulting RMS values are similar, as expected. The fitted Cd values also
agree well.
- Ran 14-day drag-significant propagations on GRACE-FO C, Swarm A, and Swarm B with
drag off, Cd = 2.3, Cd = fitted, sphere Cd, and box Cd. The results are analyzed and
compiled in the experiment's README.
- Ran TLE fitting tests over the 10 windows to test the fidelity of naive 2-day fits,
the TLE playbook, the catalog TLE, fitting from state, and fading memory fits. The
results are then parsed and compared against stated benchmarks.
- Compiled findings in `docs/validation-findings.md`. Formerly
`docs/real-world-validation-findings.md`.
- Revised the TLE fitting playbook to reflect new evidence and findings.
- Revised the showcase notebook to incorporate new findings.
- Added regression tests for this study.

### Fixed

- Withdrew the DSMC statement from the real-world validation study after a closer
read revealed that the cited paper does not support the previously claimed Cd band.

## [0.8.0] - 2026-07-26

### Added

- TLE `FitResult` exposes the new fields of a 7 x 7 symmetric Cartesian `covariance`
  matrix, covering `Px`, `Py`, `Pz`, `Vx`, `Vy`, `Vz`, and `BSTAR`
  (when `fit_bstar=True`). In addition, `FitResult` also exposes `parameter_names`,
  `sigma0`, and derived raw `sigmas`. These values, especially for `BSTAR`, shed more
  light on the success of the fit and whether a refit with `BSTAR` held is potentially
  beneficial.
- TLE `FitResult` gains residual diagnostics. These include the norm of velocity
  residuals (`velocity_residuals_ms`) and signed position residuals on radial,
  along-track, and cross-track axes (`residuals_ric_m`). These values help expose
  systematic fit errors that indicate a refit may be necessary.
- New tests covering `FitResult` additions, including GRACE-FO data pinned tests.
  Covariance symmetry check was loosened during testing to prevent rejections of
  valid TLE fits.
- Experiment exploring a decision matrix for getting the most out of the TLE fitter.
  The results are confirmative and documented in docs/ and the TLE fitting notebook.
- Experiment exploring the "fading memory" (age-weighted) TLE fitting process. The idea
  is deemed worth further exploration. However, it is not implemented as of now because
  early results are inconclusive against a pre-registered bar and whether it is truly
  superior to the newly drafted decision matrix.

## [0.7.3] - 2026-07-17

### Added

- Construction-time validations to ensure that the shipped and user-input Cd tables do
  not have negative entries.
- New tests to ensure that the shipped Cd tables have no negative entries.
- Notes about Cd table changes to the real-world validation experiment and its
  associated documentation.

### Changed

- `from_table` now rejects custom Cd tables with negative entries (which earlier versions
  accepted).

### Fixed

- Slightly negative entries in the `BoxFaceCd` table are floored at 0 at table
  generation. The shipped `BoxFaceCd` table is regenerated. Previously, wrapping the
  shipped table in a callable raised `ValueError` mid-propagation due to the table's
  negative entries and run-time checks.

## [0.7.2] - 2026-07-16

### Added

- Experiments on propygator's real-life fidelity with real satellite data from
  ILRS, NASA GRACE-FO, and Space-Track. Relevant files are under
  experiments/real-world-validation.
- Study on the LAGEOS-2 satellite targeting numerical propagator's ability to
  propagate drag-free arcs. Conclusion: propygator has high fidelity with drag-free
  orbits.
- Study on the LAGEOS-2 satellite targeting different forces' wiring in the numerical
  propagator. Conclusion: forces reach Orekit, and their effects are in expected
  ranges.
- Study on the GRACE-FO satellite targeting numerical propagator and the shipped
  drag tables' ability to propagate drag-significant arcs. Conclusion: fidelity is
  limited but respectable, and 1-day propagations have sub-kilometer precision with
  possible exceptions during geomagnetic storms.
- Study on the GRACE-FO satellite targeting the quality of the TLE fitter.
  Conclusion: TLE fitter consistently converges on measured truth, and it performs
  roughly as well as the catalogue TLE. A fitting span of 2 days seems optimal. Propygator
  TLE is also accurate to 22 km under the worst-case scenario after 3 days.
  Strategic setting of the B* term during times of quiet solar activity can
  create a large improvement. Fitting from a single state generates results comparable
  to fitting from a known trajectory during quiet solar activity or with a fitted Cd.
  Fitting from a single state has a greater loss of accuracy during high solar activity
  with uncalibrated Cd.
- This study exposed a couple of minor issues that will be the target of future work.
  These include fixing the slightly negative numbers in the BoxFaceCd table and
  exposing covariance in TLE FitResult to help detect B* fitting issues.
- Added new tests to pin down the numerical propagator's accuracy with LAGEOS and
  GRACE-FO.
- Added new tests to pin down TLE fitting fidelity on a real subsample.
- Documentation of the real-world validation experiment under
  docs/real-world-validation-findings.md.

## [0.7.1] - 2026-07-11

### Fixed

- The size determination of the cone end-marker in 3D plots is shifted from the
  bounding box of the trajectory to the largest fixed axis-range span. This allows
  the cone to stay visible even for very short trajectories.

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
