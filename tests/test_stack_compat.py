"""Stack-compatibility boundary tests (build-plan chunk 6).

Guards the NumPy <-> JPype <-> Orekit boundary against silent breakage when the
conda stack updates — especially the dtype/promotion behaviour at the boundary
(architecture §11). Ported from the standalone ``test_numpy_compat.py``.

Coverage status:
  * Part (a) — boundary primitives + a raw-Orekit Keplerian propagation — is
    portable today and lives below.
  * Part (b) — numerical round-trip via ``propagate_numerical`` (build-plan chunk
    7) — lives below. v1 does not support backward propagation (features.md §1.1),
    so the round-trip is realized as **one-period closure**: a point-mass orbit
    propagated over exactly one Keplerian period must return to its initial state.
  * Part (c) — bulk ``Trajectory`` CSV round-trip via ``io.exports`` (build-plan
    chunk 10) — lives below; asserts the vectorized export/reload paths keep
    float64 positions/velocities and an int64 two-part epoch store.

Unlike the pure-Python ``tests/core/*`` suite (which asserts the JVM stays
down), every test here starts the JVM via the session-scoped ``orekit`` fixture.
"""

from __future__ import annotations

import jpype
import numpy as np
import pandas as pd
import pytest

from propygator import Epoch, Frame, KeplerianElements, TimeScale
from propygator.core.states import Trajectory
from propygator.io import export_csv
from propygator.propagation import ForceModelConfig, propagate_numerical

# Every test in this module needs the JVM up + orekit-data loaded.
pytestmark = pytest.mark.usefixtures("orekit")


# --- (a) smoke: JVM start + Epoch.to_orekit() / raw Orekit construction -----


def test_jvm_started():
    assert jpype.isJVMStarted()


def test_epoch_to_orekit_constructs_absolutedate():
    from org.orekit.time import AbsoluteDate

    ad = Epoch.from_iso("2026-01-01T00:00:00", scale=TimeScale.UTC).to_orekit()
    assert isinstance(ad, AbsoluteDate)


@pytest.mark.parametrize(
    "iso, scale",
    [
        ("2026-06-15T12:34:56.5", TimeScale.UTC),  # modern UTC
        ("2017-01-01T00:00:00", TimeScale.UTC),  # leap-second boundary (TAI-UTC=37)
        ("2024-01-01T00:00:00", TimeScale.TAI),  # constant-offset TAI route
        ("2024-01-01T00:00:00", TimeScale.TT),  # constant-offset TT route
    ],
)
def test_epoch_to_orekit_matches_orekit_timescale(iso, scale):
    """Cross-check the pure-Python time stack against Orekit's authority.

    ``Epoch.to_orekit()`` builds an ``AbsoluteDate`` from propygator's two-double
    count; this asserts that instant equals the one Orekit parses from the *same*
    ISO string in the *same* time scale. For the UTC cases this validates the
    bundled leap-second table directly against orekit-data's UTC-TAI history — the
    one authority cross-check the otherwise self-referential ``test_time`` suite
    lacks (it only checks internal round-trips and hard-coded offsets).
    """
    from org.orekit.time import AbsoluteDate, TimeScalesFactory

    orekit_scale = {
        TimeScale.UTC: TimeScalesFactory.getUTC(),
        TimeScale.TAI: TimeScalesFactory.getTAI(),
        TimeScale.TT: TimeScalesFactory.getTT(),
    }[scale]
    reference = AbsoluteDate(iso, orekit_scale)
    built = Epoch.from_iso(iso, scale=scale).to_orekit()
    # The two-double -> AbsoluteDate construction is sub-nanosecond; 1e-6 s is a
    # safe envelope that still catches a wrong leap count or a sign error.
    assert abs(built.durationFrom(reference)) < 1e-6


# --- (a) Java Vector3D -> NumPy extraction ----------------------------------


def test_vector3d_to_numpy():
    from org.hipparchus.geometry.euclidean.threed import Vector3D

    v = Vector3D(1.5, 2.5, 3.5)
    arr = np.array([v.getX(), v.getY(), v.getZ()])
    assert arr.dtype == np.float64
    assert np.allclose(arr, [1.5, 2.5, 3.5])


# --- (a) NumPy -> Java Vector3D ---------------------------------------------


def test_numpy_to_vector3d():
    from org.hipparchus.geometry.euclidean.threed import Vector3D

    np_vec = np.array([10.0, 20.0, 30.0], dtype=np.float64)
    v = Vector3D(float(np_vec[0]), float(np_vec[1]), float(np_vec[2]))
    assert (v.getX(), v.getY(), v.getZ()) == (10.0, 20.0, 30.0)


# --- (a) NumPy -> Java double[] via JArray, and back ------------------------


def test_numpy_jarray_round_trip():
    np_data = np.array([1.1, 2.2, 3.3, 4.4, 5.5], dtype=np.float64)
    j_arr = jpype.JArray(jpype.JDouble)(np_data.tolist())
    assert len(j_arr) == 5
    assert j_arr[0] == pytest.approx(1.1)
    assert j_arr[-1] == pytest.approx(5.5)

    back = np.array(list(j_arr))
    assert back.dtype == np.float64
    assert np.allclose(back, np_data)


# --- (a) dtype edge cases ---------------------------------------------------


@pytest.mark.parametrize("dtype", [np.float32, np.float64, np.int32, np.int64])
def test_vector3d_dtype_edges(dtype):
    from org.hipparchus.geometry.euclidean.threed import Vector3D

    a = np.array([1, 2, 3], dtype=dtype)
    # Cast to Python float for the Vector3D constructor regardless of source dtype.
    v = Vector3D(float(a[0]), float(a[1]), float(a[2]))
    assert v.getX() == 1.0 and v.getY() == 2.0 and v.getZ() == 3.0


# --- (a) raw-Orekit Keplerian propagation -> (N, 3) float64 -----------------


def test_raw_keplerian_propagation_shape_dtype():
    from org.orekit.frames import FramesFactory
    from org.orekit.orbits import KeplerianOrbit, PositionAngleType
    from org.orekit.propagation.analytical import KeplerianPropagator
    from org.orekit.utils import Constants

    inertial = FramesFactory.getEME2000()
    # Exercise the propygator Epoch -> Orekit AbsoluteDate boundary directly.
    epoch = Epoch.from_iso("2026-01-01T00:00:00", scale=TimeScale.UTC).to_orekit()

    a = 7000e3  # semi-major axis, meters
    e = 0.001
    i = np.radians(51.6)
    orbit = KeplerianOrbit(
        a,
        e,
        i,
        0.0,  # argument of perigee
        0.0,  # RAAN
        0.0,  # true anomaly
        PositionAngleType.TRUE,
        inertial,
        epoch,
        Constants.EIGEN5C_EARTH_MU,
    )
    prop = KeplerianPropagator(orbit)

    n_samples = 100
    times_sec = np.linspace(0, 90 * 60, n_samples)
    positions = np.zeros((n_samples, 3), dtype=np.float64)
    for k, dt in enumerate(times_sec):
        state = prop.propagate(epoch.shiftedBy(float(dt)))
        p = state.getPVCoordinates().getPosition()
        positions[k] = [p.getX(), p.getY(), p.getZ()]

    assert positions.shape == (n_samples, 3)
    assert positions.dtype == np.float64
    # Near-circular orbit at a = 7000 km: radius stays close to 7e6 m throughout.
    radii = np.linalg.norm(positions, axis=1)
    assert 6.9e6 < radii.min() and radii.max() < 7.1e6


# --- (b) numerical one-period round-trip ------------------------------------


def test_numerical_one_period_round_trip():
    """A point-mass orbit propagated one full period returns to its initial state.

    The §11 "math is wrong?" guard, realized within the v1 forward-only contract:
    a closed two-body orbit is exactly periodic, so propagating ``keplerian``
    (point-mass) gravity over one Keplerian period must reproduce the initial
    position and velocity to ~1e-8 relative or better. A silent dtype promotion or
    a frame/mu mistake in the vectorized boundary would blow this far past
    tolerance. (Backward propagation is unsupported in v1 — features.md §1.1 — so
    this period-closure stands in for the literal forward/backward round-trip.)
    """
    from org.orekit.forces.gravity.potential import GravityFieldFactory
    from org.orekit.orbits import CartesianOrbit

    initial = KeplerianElements(
        semi_major_axis_m=7000e3,
        eccentricity=0.001,
        inclination_rad=np.radians(51.6),
        raan_rad=0.0,
        arg_perigee_rad=0.0,
        true_anomaly_rad=0.0,
    ).to_state(
        Epoch.from_iso("2026-01-01T00:00:00", scale=TimeScale.UTC), Frame.EME2000
    )

    # The period under the same point-mass mu the propagation uses.
    mu = float(GravityFieldFactory.getNormalizedProvider(0, 0).getMu())
    orbit = CartesianOrbit(
        initial.to_orekit().getPVCoordinates(),
        Frame.EME2000.to_orekit(),
        initial.epoch.to_orekit(),
        mu,
    )
    period = float(orbit.getKeplerianPeriod())

    # output_step == duration gives two samples: the start and exactly one period.
    traj = propagate_numerical(
        initial, period, output_step=period, force_models=ForceModelConfig.keplerian()
    )
    final = traj[-1]

    pos_rel = float(np.linalg.norm(final.position - initial.position)) / float(
        np.linalg.norm(initial.position)
    )
    vel_rel = float(np.linalg.norm(final.velocity - initial.velocity)) / float(
        np.linalg.norm(initial.velocity)
    )
    assert pos_rel < 1e-8
    assert vel_rel < 1e-8


# --- (c) bulk Trajectory CSV round-trip -------------------------------------


def test_bulk_trajectory_csv_round_trip(tmp_path):
    """A large Trajectory survives to_frame + CSV export/reload with dtypes intact.

    The §11 part-(c) boundary guard: a silent dtype promotion in the vectorized
    paths (per-sample ``to_frame`` transform, the ``to_dataframe`` epoch conversion,
    the CSV text round-trip) would surface here. The trajectory is synthesized
    directly from a circular orbit (not propagated) so the test exercises the
    export/reload plumbing rather than the integrator. ``N_SAMPLES`` is ~1e5 to
    stress the bulk path; it can be tuned down if the suite needs to be faster
    (same fast-suite tradeoff as chunk 9's example tests).
    """
    n = 100_000
    mu = 3.986004418e14
    r = 7.0e6
    v = float(np.sqrt(mu / r))
    omega = v / r
    t = np.arange(n) * 1.0  # 1-second cadence
    theta = omega * t
    pos = np.stack([r * np.cos(theta), r * np.sin(theta), np.zeros(n)], axis=1)
    vel = np.stack([-v * np.sin(theta), v * np.cos(theta), np.zeros(n)], axis=1)
    base = np.datetime64("2024-01-01T00:00:00", "ns")
    epochs = base + (t * 1e9).astype("int64").astype("timedelta64[ns]")

    traj = Trajectory.from_arrays(epochs, pos, vel, Frame.EME2000)
    assert traj._epochs_int.dtype == np.int64
    assert traj.positions.dtype == np.float64
    assert traj.velocities.dtype == np.float64

    out = tmp_path / "bulk.csv"
    export_csv(traj, out)

    df = pd.read_csv(out, comment="#")
    assert len(df) == n

    reloaded = Trajectory.from_arrays(
        df["epoch_utc"].to_numpy().astype("datetime64[ns]"),
        df[["x_eme2000_m", "y_eme2000_m", "z_eme2000_m"]].to_numpy(),
        df[["vx_eme2000_mps", "vy_eme2000_mps", "vz_eme2000_mps"]].to_numpy(),
        Frame.EME2000,
    )
    assert reloaded._epochs_int.dtype == np.int64
    assert reloaded.positions.dtype == np.float64
    assert reloaded.velocities.dtype == np.float64
    assert len(reloaded) == n
    # EME2000 positions survived the text round-trip (to_frame(EME2000) is a copy).
    np.testing.assert_allclose(reloaded.positions, pos, rtol=1e-9)
