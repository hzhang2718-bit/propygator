"""Shared analysis kit for the real-world-validation study (reference-only).

The cross-leg math every driver needs: the RIC (radial / along-track /
cross-track) residual decomposition, the RMS helper, and the IERS Earth
rotation rate. Extracted from the Chunk 0 driver (``lageos/run_lageos.py``)
during the 2026-07-15 study reorganization so the GRACE-FO leg no longer
imports the LAGEOS driver module for its helpers.

Pure NumPy -- no propygator, no Orekit, no JVM. Drivers import it by
inserting the study root on ``sys.path``::

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from common import OMEGA_EARTH, ric_components, rms

Not shipped, not in CI, outside ``testpaths``.
"""

from __future__ import annotations

import numpy as np

# IERS conventional Earth rotation rate, for the RIC triad's inertial-velocity
# correction (see ric_components).
OMEGA_EARTH = np.array([0.0, 0.0, 7.292115146706979e-5])  # rad/s


def ric_components(
    residuals_m: np.ndarray,
    truth_pos_m: np.ndarray,
    truth_vel_ms: np.ndarray,
    earth_fixed: bool = True,
) -> np.ndarray:
    """Decompose residual vectors into radial / along-track / cross-track.

    Pure NumPy; the triad is built from the truth PV at each epoch. With
    ``earth_fixed`` the truth velocity is Earth-relative, so it is corrected to
    inertial (v + omega x r) before building the along/cross axes — using the
    ECEF velocity directly would tilt the along-track axis by ~10 deg for
    LAGEOS. Returns ``(N, 3)`` columns ``[radial, along, cross]``.
    """
    v = truth_vel_ms + (np.cross(OMEGA_EARTH, truth_pos_m) if earth_fixed else 0.0)
    r_hat = truth_pos_m / np.linalg.norm(truth_pos_m, axis=1, keepdims=True)
    h = np.cross(truth_pos_m, v)
    c_hat = h / np.linalg.norm(h, axis=1, keepdims=True)
    i_hat = np.cross(c_hat, r_hat)
    return np.stack(
        [
            np.einsum("ij,ij->i", residuals_m, r_hat),
            np.einsum("ij,ij->i", residuals_m, i_hat),
            np.einsum("ij,ij->i", residuals_m, c_hat),
        ],
        axis=1,
    )


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x))))
