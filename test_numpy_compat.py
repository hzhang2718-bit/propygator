"""
Tests the NumPy <-> JPype <-> Orekit boundary across the patterns we'll
actually use. Run from the orekit-project folder with the `orekit` conda
environment active.
"""

import sys

# --- 1. Versions and clean imports -----------------------------------------
print("=" * 60)
print("Test 1: Imports and versions")
print("=" * 60)

import numpy as np
import jpype
import orekit_jpype as orekit

print(f"Python:        {sys.version.split()[0]}")
print(f"NumPy:         {np.__version__}")
print(f"JPype:         {jpype.__version__}")
print(f"orekit_jpype:  {orekit.__version__ if hasattr(orekit, '__version__') else '(no __version__ attr)'}")

orekit.initVM()
from orekit_jpype.pyhelpers import setup_orekit_curdir
setup_orekit_curdir("orekit-data")
print("VM started and data loaded\n")


# --- 2. Java -> NumPy: Vector3D extraction ---------------------------------
print("=" * 60)
print("Test 2: Java Vector3D -> NumPy array")
print("=" * 60)

from org.hipparchus.geometry.euclidean.threed import Vector3D
v = Vector3D(1.5, 2.5, 3.5)
arr = np.array([v.getX(), v.getY(), v.getZ()])
print(f"Vector3D values: ({v.getX()}, {v.getY()}, {v.getZ()})")
print(f"NumPy array:     {arr}")
print(f"NumPy dtype:     {arr.dtype}")
assert arr.dtype == np.float64, "Expected float64"
assert np.allclose(arr, [1.5, 2.5, 3.5]), "Values do not match"
print("PASS\n")


# --- 3. NumPy -> Java: build Vector3D from NumPy array ---------------------
print("=" * 60)
print("Test 3: NumPy array -> Java Vector3D")
print("=" * 60)

np_vec = np.array([10.0, 20.0, 30.0], dtype=np.float64)
v2 = Vector3D(float(np_vec[0]), float(np_vec[1]), float(np_vec[2]))
print(f"NumPy input:  {np_vec}")
print(f"Vector3D out: ({v2.getX()}, {v2.getY()}, {v2.getZ()})")
assert v2.getX() == 10.0 and v2.getY() == 20.0 and v2.getZ() == 30.0
print("PASS\n")


# --- 4. JArray of double from NumPy ----------------------------------------
print("=" * 60)
print("Test 4: NumPy array -> Java double[] via JArray")
print("=" * 60)

np_data = np.array([1.1, 2.2, 3.3, 4.4, 5.5], dtype=np.float64)
j_arr = jpype.JArray(jpype.JDouble)(np_data.tolist())
print(f"NumPy:          {np_data}")
print(f"Java array len: {len(j_arr)}")
print(f"Java array[0]:  {j_arr[0]}")
print(f"Java array[-1]: {j_arr[-1]}")
assert len(j_arr) == 5
assert j_arr[0] == 1.1 and j_arr[-1] == 5.5
print("PASS\n")


# --- 5. Java double[] -> NumPy via list comprehension ----------------------
print("=" * 60)
print("Test 5: Java double[] -> NumPy array")
print("=" * 60)

back_to_np = np.array(list(j_arr))
print(f"Round-tripped: {back_to_np}")
print(f"dtype:         {back_to_np.dtype}")
assert np.allclose(back_to_np, np_data)
print("PASS\n")


# --- 6. Larger scale: propagate and collect states -------------------------
print("=" * 60)
print("Test 6: Propagate orbit, collect positions into NumPy array")
print("=" * 60)

from org.orekit.time import AbsoluteDate, TimeScalesFactory
from org.orekit.frames import FramesFactory
from org.orekit.orbits import KeplerianOrbit, PositionAngleType
from org.orekit.propagation.analytical import KeplerianPropagator
from org.orekit.utils import Constants

utc = TimeScalesFactory.getUTC()
inertial = FramesFactory.getEME2000()
epoch = AbsoluteDate(2026, 1, 1, 0, 0, 0.0, utc)

# LEO-ish orbit
a = 7000e3  # semi-major axis, meters
e = 0.001
i = np.radians(51.6)
omega = 0.0
raan = 0.0
nu = 0.0
mu = Constants.EIGEN5C_EARTH_MU

orbit = KeplerianOrbit(a, e, i, omega, raan, nu,
                       PositionAngleType.TRUE, inertial, epoch, mu)
prop = KeplerianPropagator(orbit)

# Sample positions over one orbit (~90 min)
n_samples = 100
times_sec = np.linspace(0, 90 * 60, n_samples)
positions = np.zeros((n_samples, 3), dtype=np.float64)

for k, dt in enumerate(times_sec):
    state = prop.propagate(epoch.shiftedBy(float(dt)))
    p = state.getPVCoordinates().getPosition()
    positions[k] = [p.getX(), p.getY(), p.getZ()]

print(f"positions shape: {positions.shape}")
print(f"positions dtype: {positions.dtype}")
print(f"first position:  {positions[0]}")
print(f"last position:   {positions[-1]}")
radii = np.linalg.norm(positions, axis=1)
print(f"radius range:    [{radii.min():.1f}, {radii.max():.1f}] m")
# For a near-circular orbit at a=7000 km, radius should stay near 7e6 m
assert 6.9e6 < radii.min() and radii.max() < 7.1e6
print("PASS\n")


# --- 7. dtype edge cases ---------------------------------------------------
print("=" * 60)
print("Test 7: dtype edge cases (float32, int32, int64)")
print("=" * 60)

for dt in [np.float32, np.float64, np.int32, np.int64]:
    a = np.array([1, 2, 3], dtype=dt)
    # Cast to Python float for Vector3D constructor
    vv = Vector3D(float(a[0]), float(a[1]), float(a[2]))
    assert vv.getX() == 1.0
    print(f"  {dt.__name__:10s} -> Vector3D OK")
print("PASS\n")


print("=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)
print("NumPy 2.x is functioning correctly with orekit_jpype on this stack.")