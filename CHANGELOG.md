# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
