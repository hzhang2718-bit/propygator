# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Package scaffolding: `src/propygator/` layout, `pyproject.toml` (single-source
  `0.1.0` version, MIT), and `environment.yml` pinning Python 3.11 / OpenJDK 17 /
  orekit_jpype 13.1.x with an editable `pip: -e .[dev]` install.
- Lazy JVM initialization (`propygator.init`, one JVM per process) and
  `clear_cache`, with typed exceptions (`PropygatorError`,
  `OrekitDataMissingError`, `JVMAlreadyStartedError`) and the orekit-data
  resolution order (`OREKIT_DATA_PATH` → `~/.propygator/orekit-data/` →
  `./orekit-data/`). Importing the package does not start the JVM.
- Pure-Python core data model with shape/dtype/finiteness validation: `Epoch` +
  `TimeScale` (bundled leap-second table), `Frame`, `State`, `Trajectory` +
  `TrajectoryMetadata`, `KeplerianElements`, `Orientation`, and the observation
  types `GroundStation` / `GeodeticPosition` / `Pass`. Orekit conversions
  (`to_orekit` / `to_frame`) are deferred to Feature 1.1.
- Test harness: session-scoped JVM + orekit-data fixture (`tests/conftest.py`),
  pure-Python core tests, and the NumPy ↔ JPype ↔ Orekit stack-compatibility
  boundary test.
- Tooling: pre-commit hooks (ruff lint + format, mypy, nbstripout, file hygiene),
  ruff/mypy configuration, and `scripts/download_orekit_data.py`.
- Continuous integration: GitHub Actions workflow (Ubuntu, Python 3.11) that
  builds the conda env from `environment.yml`, caches orekit-data, and runs
  `pytest` followed by `pre-commit run --all-files`.
