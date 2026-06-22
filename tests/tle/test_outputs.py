"""ISS end-to-end output reuse for ``propagate_tle`` (Feature 1.3, build-plan chunk 5).

Proves the §1.3 "outputs reused unchanged" claim: a fixed ISS TLE propagated to a
native-TEME :class:`~propygator.core.states.Trajectory` flows through 1.1's plotting
and export stack with no new code. Covers ``plot_summary`` / ``export_all`` /
``export_csv`` (including the new ``mean_anomaly`` token) and the verify-only Note-5
check that a TEME (ECI) 3-D view correctly draws no coastline.

Every test starts the JVM once via the session-scoped ``orekit`` fixture, so
``conftest``'s ordering hook schedules this module after the pure-Python
``tests/core/*`` "no JVM started" guards (architecture §11).
"""

from __future__ import annotations

import matplotlib
import pytest

matplotlib.use("Agg")  # headless: plot_summary / export_all render matplotlib figures

import matplotlib.pyplot as plt
import pandas as pd

from propygator import (
    TLE,
    Frame,
    export_all,
    export_csv,
    plot_3d,
    plot_summary,
    propagate_tle,
)

pytestmark = pytest.mark.usefixtures("orekit")

# The same fixed, real ISS (ZARYA) TLE used across the 1.3 tests — epoch
# 2026-06-20T09:57:02 UTC, NORAD 25544, a near-Earth (SGP4) orbit.
ISS_NAME = "ISS (ZARYA)"
ISS_LINE1 = "1 25544U 98067A   26171.41461525  .00008813  00000+0  16600-3 0  9990"
ISS_LINE2 = "2 25544  51.6327 284.1189 0004557 208.5194 151.5545 15.49333088572250"

# The 16 default CSV columns, in order (features.md §1.1) — duplicated here rather
# than imported from tests/io so this end-to-end module stands alone.
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


def _iss_trajectory(duration: float = 5400.0, output_step: float = 60.0):
    """One ISS orbit (~91 samples) in native TEME from a fixed TLE."""
    tle = TLE.from_strings(ISS_LINE1, ISS_LINE2, name=ISS_NAME)
    return propagate_tle(tle, duration, output_step=output_step)


def _read(path):
    """Reload an exported CSV, skipping the ``# key: value`` metadata header."""
    return pd.read_csv(path, comment="#")


def test_propagate_tle_returns_teme_trajectory():
    traj = _iss_trajectory()
    assert traj.frame is Frame.TEME
    assert len(traj) > 1


def test_plot_summary_consumes_teme_trajectory():
    """plot_summary renders a TEME-framed trajectory unchanged (converts internally)."""
    traj = _iss_trajectory()
    fig = plot_summary(traj)
    try:
        assert fig is not None
        assert len(fig.axes) > 0
    finally:
        plt.close(fig)


def test_export_all_default_outputs(tmp_path):
    """The full bundle (summary PNG + inertial 3-D HTML + 16-column CSV) writes."""
    traj = _iss_trajectory()
    result = export_all(traj, tmp_path / "iss", filename_prefix="iss")

    assert set(result) == {"summary", "3d_eme2000", "csv"}
    for path in result.values():
        assert path.exists() and path.stat().st_size > 0

    df = _read(result["csv"])
    assert list(df.columns) == EXPECTED_DEFAULT
    assert len(df) == len(traj)


def test_export_csv_keplerian_mean_anomaly_snapshot(tmp_path):
    """Fixed-ISS CSV snapshot: keplerian + mean_anomaly columns, in canonical order."""
    traj = _iss_trajectory()
    out = tmp_path / "iss.csv"
    export_csv(traj, out, columns=["keplerian", "mean_anomaly"])
    df = _read(out)

    # Opt-in Keplerian + mean-anomaly columns are computed in EME2000 and appended in
    # canonical order (keplerian block, then mean_anomaly), after the 16 defaults.
    assert list(df.columns) == EXPECTED_DEFAULT + KEPLERIAN_COLS + MEAN_ANOMALY_COLS
    assert len(df) == len(traj)
    # Metadata header records the SGP4 propagator (reproducibility record).
    assert traj.metadata["propagator"] == "sgp4"


def test_plot_3d_teme_draws_no_coastline():
    """Note 5 (verify-only): a TEME (ECI) 3-D view warns and draws no coastline."""
    traj = _iss_trajectory()
    with pytest.warns(UserWarning, match="ignored for the TEME"):
        fig = plot_3d(traj, frame=Frame.TEME, show_map_overlay=True)
    assert "coastline" not in {t.name for t in fig.data}
