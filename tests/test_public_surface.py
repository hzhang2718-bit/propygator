"""Feature 1.1 public surface (build-plan chunk 12).

Two concerns:

1. ``import propygator as pgr`` exposes the full Feature 1.1 surface and does
   **not** start the JVM. This test deliberately does *not* request the ``orekit``
   fixture, so the ``pytest_collection_modifyitems`` hook in ``conftest.py`` runs it
   in the pure-Python phase (before any JVM-touching test), where the
   "import is JVM-free" assertion is meaningful.

2. The three "Typical user code" examples from features.md §1.1 run end-to-end to
   written outputs. These request the ``orekit`` fixture (real propagation) and are
   scheduled last. They run at **reduced duration (~1 orbit)** rather than the
   documented 1-day / 7-day spans — the short run exercises every wiring path
   (default + box geometry, ``VariableCd`` routing, attitude, ``export_all``)
   identically, keeping the suite fast (the same as-built precedent as chunk 9).
"""

from __future__ import annotations

import math

import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")  # headless: the examples render figures via export_all

import propygator as pgr

# Names the top level must expose after Feature 1.1 (architecture §7 re-export list).
EXPECTED_NAMES = [
    "propagate_numerical",
    "ForceModelConfig",
    "IntegratorConfig",
    "SpacecraftConfig",
    "SpacecraftGeometry",
    "VariableCd",
    "BoxFaceCd",
    "AttitudeConfig",
    "LofAligned",
    "LofOffset",
    "Inertial",
    "SunPointing",
    "NadirPointing",
    "InPlaneTracking",
    "CustomAttitude",
    "plot_summary",
    "plot_ground_track",
    "plot_3d",
    "plot_altitude",
    "plot_speed",
    "export_csv",
    "export_all",
]

_MU = 3.986004418e14  # WGS84, matches the propagator's Earth GM


def _initial_state() -> pgr.State:
    """An ISS-like circular LEO state in EME2000 (~420 km, 51.6° inclination)."""
    r = 6798137.0  # ~420 km altitude
    v = math.sqrt(_MU / r)
    inc = math.radians(51.6)
    epoch = pgr.Epoch.from_iso("2024-01-01T00:00:00")
    position = np.array([r, 0.0, 0.0], dtype=np.float64)
    velocity = np.array([0.0, v * math.cos(inc), v * math.sin(inc)], dtype=np.float64)
    return pgr.State(epoch, position, velocity, pgr.Frame.EME2000)


def _orbit_period_s() -> float:
    r = 6798137.0
    return 2.0 * math.pi * math.sqrt(r**3 / _MU)


# --- 1. import surface (JVM-free) -------------------------------------------


def test_public_surface_exposes_feature_1_1_names():
    missing = [name for name in EXPECTED_NAMES if not hasattr(pgr, name)]
    assert missing == [], f"missing top-level names: {missing}"
    # Everything advertised in __all__ resolves.
    assert all(hasattr(pgr, name) for name in pgr.__all__)


def test_import_does_not_start_jvm():
    import jpype

    # Importing propygator (which now pulls propagation/plotting/io) must stay
    # JVM-free; the JVM starts only on the first Orekit-touching call.
    assert not jpype.isJVMStarted()


# --- 2. the three features.md §1.1 examples ---------------------------------


@pytest.mark.usefixtures("orekit")
def test_example_simple_runs_to_outputs(tmp_path):
    initial = _initial_state()
    duration = _orbit_period_s()  # ~1 orbit (documented example uses 86400 s)
    traj = pgr.propagate_numerical(initial, duration, output_step=60)

    assert traj.frame is pgr.Frame.EME2000
    assert len(traj) == int(duration // 60) + 1

    result = pgr.export_all(traj, output_dir=tmp_path / "run_01")
    assert set(result) == {"summary", "3d_eme2000", "csv"}
    for path in result.values():
        assert path.exists() and path.stat().st_size > 0


@pytest.mark.usefixtures("orekit")
def test_example_box_in_plane_tracking_runs(tmp_path):
    initial = _initial_state()
    duration = _orbit_period_s()
    traj = pgr.propagate_numerical(
        initial,
        duration,
        output_step=60,
        spacecraft=pgr.SpacecraftConfig(
            mass_kg=420,
            geometry=pgr.SpacecraftGeometry.box_and_panels(
                x_length_m=2.0,
                y_length_m=1.0,
                z_length_m=1.0,
                solar_array_area_m2=10.0,
                drag_coefficient=pgr.VariableCd.sphere_default(),  # Tier A scalar Cd
            ),
        ),
        attitude=pgr.InPlaneTracking(),
    )

    result = pgr.export_all(
        traj,
        output_dir=tmp_path / "run_02",
        speed_frames=[pgr.Frame.EME2000, pgr.Frame.ITRF],
        frames_3d=[pgr.Frame.EME2000, pgr.Frame.ITRF],
    )
    # Both 3D frames requested -> frame-suffixed files.
    assert set(result) == {"summary", "csv", "3d_eme2000", "3d_itrf"}
    for path in result.values():
        assert path.exists() and path.stat().st_size > 0


@pytest.mark.usefixtures("orekit")
def test_example_solar_sail_rolled_runs():
    initial = _initial_state()
    duration = _orbit_period_s()  # documented example uses 7 days
    sail = pgr.SpacecraftConfig(
        mass_kg=50,
        geometry=pgr.SpacecraftGeometry.box_and_panels(
            x_length_m=10.0,
            y_length_m=10.0,
            z_length_m=0.001,
            solar_array_area_m2=0.0,
            specular_reflection_coefficient=0.85,
            absorption_coefficient=0.10,
        ),
    )
    traj = pgr.propagate_numerical(
        initial,
        duration,
        output_step=60,
        spacecraft=sail,
        attitude=pgr.LofOffset(roll_deg=30.0),
    )
    assert traj.frame is pgr.Frame.EME2000
    assert len(traj) == int(duration // 60) + 1
