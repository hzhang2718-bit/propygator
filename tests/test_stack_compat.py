"""Stack-compatibility boundary tests (build-plan chunk 6).

Guards the NumPy <-> JPype <-> Orekit boundary against silent breakage when the
conda stack updates — especially the dtype/promotion behaviour at the boundary
(architecture §11). Ported from the standalone ``test_numpy_compat.py``.

Coverage status:
  * Part (a) — boundary primitives + a raw-Orekit Keplerian propagation — is
    portable today and lives below.
  * Part (b) — numerical forward/backward round-trip via ``propagate_numerical``
    — depends on Feature 1.1. See the ``TODO(1.1)`` block at the end.
  * Part (c) — bulk ``Trajectory`` CSV round-trip — depends on Feature 1.1 +
    ``io.exports``. See the ``TODO(1.1)`` block at the end.

Unlike the pure-Python ``tests/core/*`` suite (which asserts the JVM stays
down), every test here starts the JVM via the session-scoped ``orekit`` fixture.
"""

from __future__ import annotations

import jpype
import numpy as np
import pytest

from propygator import Epoch, TimeScale

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


# --- (b) numerical forward/backward round-trip ------------------------------
# TODO(1.1): propagate a known Keplerian orbit forward then backward via
# pgr.propagate_numerical(...) and assert agreement with the initial State at
# 1e-8 relative or better. Catches "imports work but math is wrong" failures
# (e.g. silent dtype promotion). Depends on propagation.numerical (Feature 1.1).
# (architecture §11, stack-compat part b)


# --- (c) bulk Trajectory CSV round-trip -------------------------------------
# TODO(1.1): build a ~1e5-sample Trajectory, run to_frame() and to_dataframe(),
# export to CSV via io.exports, reload, and assert the reloaded trajectory keeps
# float64 positions/velocities and int64 _epochs_int. Catches dtype/promotion
# bugs in the vectorized paths. Depends on Feature 1.1 + io.exports.
# (architecture §11, stack-compat part c)
