"""Tests for ``propygator.io.exports.export_csv`` (build-plan chunk 10).

Every test starts the JVM via the session-scoped ``orekit`` fixture (frame
conversions / geodetic / Sun all cross into Orekit). Trajectories are synthesized
directly from a circular orbit rather than propagated, which exercises the full
export plumbing (EME2000/ITRF conversion, geodetic projection, Keplerian and Sun
columns, the metadata header) without the cost of a real propagation.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import matplotlib
import numpy as np
import pandas as pd
import pytest

matplotlib.use("Agg")  # headless: export_all renders the summary figure

from propygator import Frame
from propygator.core.states import Trajectory
from propygator.io import export_all, export_csv

pytestmark = pytest.mark.usefixtures("orekit")

# WGS84 mu — matches State.to_keplerian's mu so a circular orbit's osculating
# semi-major axis comes back ~= the geometric radius.
_MU = 3.986004418e14

EXPECTED_DEFAULT = [
    "epoch_utc",
    "epoch_mjd_utc",
    "x_eme2000_m",
    "y_eme2000_m",
    "z_eme2000_m",
    "vx_eme2000_mps",
    "vy_eme2000_mps",
    "vz_eme2000_mps",
    "x_itrf_m",
    "y_itrf_m",
    "z_itrf_m",
    "latitude_deg",
    "longitude_deg",
    "altitude_m",
    "speed_inertial_mps",
    "speed_itrf_mps",
]
KEPLERIAN_COLS = [
    "semi_major_axis_m",
    "eccentricity",
    "inclination_deg",
    "raan_deg",
    "arg_perigee_deg",
    "true_anomaly_deg",
]
MEAN_ANOMALY_COLS = ["mean_anomaly_deg"]
SUN_COLS = [
    "sun_x_eme2000_m",
    "sun_y_eme2000_m",
    "sun_z_eme2000_m",
    "sun_dir_x_eme2000",
    "sun_dir_y_eme2000",
    "sun_dir_z_eme2000",
]


def _circular_trajectory(n: int = 6, radius_m: float = 7.0e6, step_s: float = 60.0):
    """A physically self-consistent circular EME2000 orbit in the xy-plane."""
    v = math.sqrt(_MU / radius_m)
    omega = v / radius_m  # mean motion (rad/s)
    t = np.arange(n) * step_s
    theta = omega * t
    pos = np.stack(
        [radius_m * np.cos(theta), radius_m * np.sin(theta), np.zeros(n)], axis=1
    )
    vel = np.stack([-v * np.sin(theta), v * np.cos(theta), np.zeros(n)], axis=1)
    base = np.datetime64("2024-01-01T00:00:00", "ns")
    offsets = (t * 1e9).astype("int64").astype("timedelta64[ns]")
    epochs = base + offsets
    return Trajectory.from_arrays(epochs, pos, vel, Frame.EME2000)


def _read(path):
    """Reload an exported CSV, skipping the ``# key: value`` metadata header."""
    return pd.read_csv(path, comment="#")


def test_default_columns_names_and_order(tmp_path):
    traj = _circular_trajectory()
    out = tmp_path / "traj.csv"
    export_csv(traj, out)
    df = _read(out)
    assert list(df.columns) == EXPECTED_DEFAULT
    assert len(df) == len(traj)


def test_default_column_count_is_16():
    # Pins the documented count (features.md §1.1: 16 default columns, including
    # speed_itrf_mps alongside speed_inertial_mps).
    assert len(EXPECTED_DEFAULT) == 16


def test_eme2000_and_itrf_columns_round_trip(tmp_path):
    traj = _circular_trajectory()
    out = tmp_path / "traj.csv"
    export_csv(traj, out)
    df = _read(out)

    eme = traj.to_frame(Frame.EME2000)
    itrf = traj.to_frame(Frame.ITRF)
    for axis, comp in enumerate("xyz"):
        np.testing.assert_allclose(
            df[f"{comp}_eme2000_m"], eme.positions[:, axis], rtol=1e-12
        )
        np.testing.assert_allclose(
            df[f"v{comp}_eme2000_mps"], eme.velocities[:, axis], rtol=1e-12
        )
        np.testing.assert_allclose(
            df[f"{comp}_itrf_m"], itrf.positions[:, axis], rtol=1e-9
        )
    # dtype preservation through the CSV round-trip.
    for col in EXPECTED_DEFAULT[1:]:  # all but the ISO epoch string
        assert df[col].dtype == np.float64


def test_speed_columns_are_velocity_magnitudes(tmp_path):
    traj = _circular_trajectory()
    out = tmp_path / "traj.csv"
    export_csv(traj, out)
    df = _read(out)

    eme = traj.to_frame(Frame.EME2000)
    itrf = traj.to_frame(Frame.ITRF)
    np.testing.assert_allclose(
        df["speed_inertial_mps"], np.linalg.norm(eme.velocities, axis=1), rtol=1e-12
    )
    np.testing.assert_allclose(
        df["speed_itrf_mps"], np.linalg.norm(itrf.velocities, axis=1), rtol=1e-9
    )


def test_epoch_columns(tmp_path):
    traj = _circular_trajectory()
    out = tmp_path / "traj.csv"
    export_csv(traj, out)
    df = _read(out)

    # ISO 8601 with 'T' separator and microseconds; UTC implied by the column name.
    assert df["epoch_utc"].iloc[0] == "2024-01-01T00:00:00.000000"
    # epoch_mjd_utc: days since 1858-11-17 00:00 UTC.
    ref = (
        datetime(2024, 1, 1, tzinfo=timezone.utc)
        - datetime(1858, 11, 17, tzinfo=timezone.utc)
    ).total_seconds() / 86400.0
    assert abs(df["epoch_mjd_utc"].iloc[0] - ref) < 1e-6
    assert df["epoch_mjd_utc"].is_monotonic_increasing


def test_metadata_header_present_and_parseable(tmp_path):
    traj = _circular_trajectory()
    out = tmp_path / "traj.csv"
    export_csv(traj, out)

    header = [
        ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.startswith("#")
    ]
    # One comment line per metadata key, each parseable as "# key: value".
    assert len(header) == len(traj.metadata)
    parsed = {}
    for line in header:
        assert line.startswith("# ")
        key, _, value = line[2:].partition(": ")
        parsed[key] = value
    assert parsed["propagator"] == traj.metadata["propagator"]
    assert "propygator_version" in parsed


def test_metadata_newline_is_sanitized(tmp_path):
    """A metadata value with an embedded newline must not forge a CSV data row."""
    traj = _circular_trajectory()
    traj.metadata["name"] = "evil\n1,2,3,4,5,6,7,8"
    out = tmp_path / "traj.csv"
    export_csv(traj, out)

    lines = out.read_text(encoding="utf-8").splitlines()
    header = [ln for ln in lines if ln.startswith("#")]
    # Each metadata key stays on exactly one comment line — no forged extra line.
    assert len(header) == len(traj.metadata)
    name_line = next(ln for ln in header if ln.startswith("# name:"))
    assert "evil" in name_line and "1,2,3" in name_line  # collapsed onto one line
    # The documented reload still parses cleanly with exactly one row per sample.
    assert len(_read(out)) == len(traj)


def test_metadata_formula_trigger_is_neutralized(tmp_path):
    """A metadata value starting with a spreadsheet formula trigger is quoted."""
    traj = _circular_trajectory()
    traj.metadata["name"] = "=cmd()"
    out = tmp_path / "traj.csv"
    export_csv(traj, out)

    header = [
        ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.startswith("#")
    ]
    name_line = next(ln for ln in header if ln.startswith("# name:"))
    assert name_line == "# name: '=cmd()"  # leading quote neutralizes the formula


def test_keplerian_opt_in_appends_columns(tmp_path):
    traj = _circular_trajectory()
    out = tmp_path / "traj.csv"
    export_csv(traj, out, columns=["keplerian"])
    df = _read(out)

    assert list(df.columns) == EXPECTED_DEFAULT + KEPLERIAN_COLS
    # Circular 7000 km orbit: sma ~= radius, eccentricity ~= 0.
    np.testing.assert_allclose(df["semi_major_axis_m"], 7.0e6, rtol=1e-6)
    assert (df["eccentricity"] < 1e-3).all()


def test_sun_opt_in_appends_columns(tmp_path):
    traj = _circular_trajectory()
    out = tmp_path / "traj.csv"
    export_csv(traj, out, columns=["sun"])
    df = _read(out)

    assert list(df.columns) == EXPECTED_DEFAULT + SUN_COLS
    # Sun is ~1 AU away; the direction columns are a unit vector.
    sun_range = np.linalg.norm(
        df[["sun_x_eme2000_m", "sun_y_eme2000_m", "sun_z_eme2000_m"]].to_numpy(), axis=1
    )
    assert ((sun_range > 1.3e11) & (sun_range < 1.6e11)).all()
    dir_norm = np.linalg.norm(
        df[["sun_dir_x_eme2000", "sun_dir_y_eme2000", "sun_dir_z_eme2000"]].to_numpy(),
        axis=1,
    )
    np.testing.assert_allclose(dir_norm, 1.0, atol=1e-12)


def test_mean_anomaly_opt_in_appends_column(tmp_path):
    traj = _circular_trajectory()
    out = tmp_path / "traj.csv"
    export_csv(traj, out, columns=["keplerian", "mean_anomaly"])
    df = _read(out)

    # mean_anomaly is a single column, appended after the keplerian block.
    assert list(df.columns) == EXPECTED_DEFAULT + KEPLERIAN_COLS + MEAN_ANOMALY_COLS
    # Each row equals an independently-computed M (degrees) from the EME2000
    # osculating elements; M depends only on e and ν, so this is frame-stable. The
    # recompute also uses math.degrees, so a missing degree-conversion in the builder
    # (radians vs degrees) would surface as a mismatch here.
    eme = traj.to_frame(Frame.EME2000)
    expected = np.array([math.degrees(s.to_keplerian().mean_anomaly()) for s in eme])
    np.testing.assert_allclose(df["mean_anomaly_deg"].to_numpy(), expected, rtol=1e-9)
    # Near-circular orbit (e ~ 0): M ~ ν, so the column reads as a degree anomaly.
    np.testing.assert_allclose(
        df["mean_anomaly_deg"].to_numpy(), df["true_anomaly_deg"].to_numpy(), atol=0.5
    )


def test_mean_anomaly_canonical_order_between_keplerian_and_sun(tmp_path):
    traj = _circular_trajectory()
    out = tmp_path / "traj.csv"
    # Tokens given out of order: mean_anomaly must land between keplerian and sun.
    export_csv(traj, out, columns=["sun", "mean_anomaly", "keplerian"])
    df = _read(out)
    assert (
        list(df.columns)
        == EXPECTED_DEFAULT + KEPLERIAN_COLS + MEAN_ANOMALY_COLS + SUN_COLS
    )


def test_mean_anomaly_token_leaves_other_groups_byte_stable(tmp_path):
    """Adding mean_anomaly must not perturb the default-16 or keplerian columns."""
    traj = _circular_trajectory()
    kep_only = tmp_path / "kep_only.csv"
    kep_plus_ma = tmp_path / "kep_plus_ma.csv"
    export_csv(traj, kep_only, columns=["keplerian"])
    export_csv(traj, kep_plus_ma, columns=["keplerian", "mean_anomaly"])

    df_kep = _read(kep_only)
    df_both = _read(kep_plus_ma)
    # The keplerian token's six-column set is unchanged when mean_anomaly is added.
    assert list(df_kep.columns) == EXPECTED_DEFAULT + KEPLERIAN_COLS
    # The shared columns carry byte-identical values (schema + data unperturbed).
    for col in EXPECTED_DEFAULT + KEPLERIAN_COLS:
        if col == "epoch_utc":
            assert (df_kep[col] == df_both[col]).all()
        else:
            np.testing.assert_array_equal(
                df_kep[col].to_numpy(), df_both[col].to_numpy()
            )


def test_group_order_is_canonical_regardless_of_token_order(tmp_path):
    traj = _circular_trajectory()
    out = tmp_path / "traj.csv"
    # Tokens given sun-first, but keplerian must still come first (canonical order).
    export_csv(traj, out, columns=["sun", "keplerian"])
    df = _read(out)
    assert list(df.columns) == EXPECTED_DEFAULT + KEPLERIAN_COLS + SUN_COLS


def test_duplicate_tokens_collapse(tmp_path):
    traj = _circular_trajectory()
    out = tmp_path / "traj.csv"
    export_csv(traj, out, columns=["keplerian", "keplerian"])
    df = _read(out)
    assert list(df.columns) == EXPECTED_DEFAULT + KEPLERIAN_COLS


def test_unknown_column_group_raises(tmp_path):
    traj = _circular_trajectory()
    out = tmp_path / "traj.csv"
    with pytest.raises(ValueError, match="unknown column group"):
        export_csv(traj, out, columns=["bogus"])


# --- export_all -------------------------------------------------------------


def test_export_all_default_outputs(tmp_path):
    traj = _circular_trajectory()
    out_dir = tmp_path / "run_01"  # does not exist yet -> must be created
    result = export_all(traj, out_dir)

    # Defaults: summary + a single inertial 3D (always frame-suffixed) + CSV.
    assert set(result) == {"summary", "3d_eme2000", "csv"}
    assert result["summary"] == out_dir / "trajectory_summary.png"
    assert result["3d_eme2000"] == out_dir / "trajectory_3d_eme2000.html"
    assert result["csv"] == out_dir / "trajectory.csv"
    for path in result.values():
        assert path.exists() and path.stat().st_size > 0


def test_export_all_creates_output_dir(tmp_path):
    traj = _circular_trajectory()
    out_dir = tmp_path / "nested" / "deeper"
    assert not out_dir.exists()
    export_all(traj, out_dir, summary=False, plot_3d=False)
    assert out_dir.is_dir()


def test_export_all_filename_prefix(tmp_path):
    traj = _circular_trajectory()
    result = export_all(traj, tmp_path, filename_prefix="iss")
    assert result["csv"].name == "iss.csv"
    assert result["summary"].name == "iss_summary.png"
    assert result["3d_eme2000"].name == "iss_3d_eme2000.html"


@pytest.mark.parametrize("bad_prefix", ["../escape", "sub/dir", "/abs", "..", ""])
def test_export_all_rejects_unsafe_filename_prefix(tmp_path, bad_prefix):
    """A prefix with separators / '..' / absolute root must not escape output_dir."""
    traj = _circular_trajectory()
    with pytest.raises(ValueError, match="filename_prefix"):
        export_all(traj, tmp_path, filename_prefix=bad_prefix)


def test_export_all_dedupes_aliased_3d_frames(tmp_path):
    """Frame.J2000 is an alias of Frame.EME2000, so it collapses to one 3D output."""
    traj = _circular_trajectory()
    result = export_all(
        traj,
        tmp_path,
        summary=False,
        csv=False,
        frames_3d=[Frame.EME2000, Frame.J2000],
    )
    assert set(result) == {"3d_eme2000"}


def test_export_all_two_3d_frames_are_suffixed(tmp_path):
    traj = _circular_trajectory()
    result = export_all(
        traj,
        tmp_path,
        summary=False,
        csv=False,
        frames_3d=[Frame.EME2000, Frame.ITRF],
    )
    assert set(result) == {"3d_eme2000", "3d_itrf"}
    assert result["3d_eme2000"] == tmp_path / "trajectory_3d_eme2000.html"
    assert result["3d_itrf"] == tmp_path / "trajectory_3d_itrf.html"
    for path in result.values():
        assert path.exists() and path.stat().st_size > 0


def test_export_all_booleans_toggle_outputs(tmp_path):
    traj = _circular_trajectory()

    csv_only = export_all(traj, tmp_path / "a", summary=False, plot_3d=False)
    assert set(csv_only) == {"csv"}
    assert not (tmp_path / "a" / "trajectory_summary.png").exists()
    assert not (tmp_path / "a" / "trajectory_3d_eme2000.html").exists()

    no_csv = export_all(traj, tmp_path / "b", csv=False)
    assert set(no_csv) == {"summary", "3d_eme2000"}
    assert not (tmp_path / "b" / "trajectory.csv").exists()


def test_export_all_forwards_csv_columns(tmp_path):
    traj = _circular_trajectory()
    result = export_all(
        traj, tmp_path, summary=False, plot_3d=False, csv_columns=["keplerian"]
    )
    df = _read(result["csv"])
    assert list(df.columns) == EXPECTED_DEFAULT + KEPLERIAN_COLS
