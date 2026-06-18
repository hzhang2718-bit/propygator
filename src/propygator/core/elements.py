"""``KeplerianElements`` — the classical orbital-element representation.

A frozen, SI dataclass holding the six classical elements with the **true
anomaly** as the canonical angular coordinate (architecture §6). Construction and
field validation are pure-Python and safe before JVM init; the conversions
(:meth:`KeplerianElements.from_state`, :meth:`to_state`) and the derived-anomaly
methods (:meth:`mean_anomaly`, :meth:`eccentric_anomaly`) cross into Orekit and
start the JVM lazily on first use (Feature 1.1, build-plan chunk 2).

Conventions pinned now (architecture §6):

- **Angle convention:** the stored anomaly is the true anomaly ν. Mean and
  eccentric anomaly are derived via methods, not stored as alternate fields, so
  there is a single canonical anomaly.
- **Units:** SI throughout — semi-major axis in meters, all angles in radians.
  Conversion to km/degrees happens only at the user-facing boundary.
- **Frame:** classical elements are frame-dependent (i and Ω are measured against
  the frame's equator / reference direction). The frame is supplied at conversion
  time via ``to_state(epoch, frame)`` rather than stored on the elements.

Singularity caveat: ω and ν are individually ill-conditioned as e→0 (only their
sum, the argument of latitude, is well-defined), and Ω is ill-conditioned as
i→0. Values stay finite but go erratic for the near-circular LEO orbits this
library targets; equinoctial elements are a future opt-in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .frames import Frame
    from .states import State
    from .time import Epoch


@dataclass(frozen=True)
class KeplerianElements:
    """The six classical orbital elements, SI, with true anomaly as the anomaly.

    Immutable. Field validation runs in :meth:`__post_init__` (no Orekit calls);
    conversions to/from :class:`~propygator.core.states.State` are deferred to
    Feature 1.
    """

    semi_major_axis_m: float  # a, meters
    eccentricity: float  # e, unitless, >= 0
    inclination_rad: float  # i, radians, in [0, pi]
    raan_rad: float  # Omega, radians
    arg_perigee_rad: float  # omega, radians
    true_anomaly_rad: float  # nu, radians (canonical anomaly)

    def __post_init__(self) -> None:
        a = self.semi_major_axis_m
        e = self.eccentricity
        i = self.inclination_rad
        if not math.isfinite(a) or a == 0.0:
            raise ValueError(f"semi_major_axis_m must be finite and nonzero, got {a!r}")
        if not math.isfinite(e) or e < 0.0:
            raise ValueError(f"eccentricity must be finite and >= 0, got {e!r}")
        # The sign of a is tied to the orbit class. Parabolic (e == 1) has an
        # undefined/infinite semi-major axis and is not representable in classical
        # elements; elliptical (e < 1) needs a > 0; hyperbolic (e > 1) needs a < 0.
        if e == 1.0:
            raise ValueError(
                "eccentricity == 1 (parabolic) has no finite semi_major_axis_m "
                "and is not representable in classical elements; unsupported."
            )
        if e < 1.0 and a <= 0.0:
            raise ValueError(
                f"elliptical orbit (e={e!r} < 1) requires semi_major_axis_m > 0, "
                f"got {a!r}"
            )
        if e > 1.0 and a >= 0.0:
            raise ValueError(
                f"hyperbolic orbit (e={e!r} > 1) requires semi_major_axis_m < 0, "
                f"got {a!r}"
            )
        if not math.isfinite(i) or not 0.0 <= i <= math.pi:
            raise ValueError(
                f"inclination_rad must be finite and in [0, pi], got {i!r}"
            )
        for name, val in (
            ("raan_rad", self.raan_rad),
            ("arg_perigee_rad", self.arg_perigee_rad),
            ("true_anomaly_rad", self.true_anomaly_rad),
        ):
            if not math.isfinite(val):
                raise ValueError(f"{name} must be finite, got {val!r}")

        # Hyperbolic orbits: the true anomaly is confined to the open interval
        # (-acos(-1/e), +acos(-1/e)) — the asymptote limit beyond which the
        # trajectory has no real point. Outside it the ν→M / ν→E conversions return
        # NaN, so reject it at construction rather than emitting a silent NaN later
        # (elliptic ν is unbounded mod 2π, so this applies only to e > 1).
        if e > 1.0:
            nu_limit = math.acos(-1.0 / e)
            if abs(self.true_anomaly_rad) >= nu_limit:
                raise ValueError(
                    f"hyperbolic (e={e!r}) true_anomaly_rad must satisfy "
                    f"|ν| < acos(-1/e) = {nu_limit!r}, got {self.true_anomaly_rad!r}"
                )

    def mean_anomaly(self) -> float:
        """Mean anomaly M derived from the stored true anomaly ν.

        Crosses into Orekit (``KeplerianAnomalyUtility``) so the conversion matches
        the rest of the library bit-for-bit; the elliptic (e < 1) and hyperbolic
        (e > 1) branches are selected on the eccentricity (e == 1 is rejected at
        construction). A pure angle conversion — independent of frame, epoch, and µ.
        """
        from .._orekit_init import _ensure_started

        _ensure_started()
        from org.orekit.orbits import KeplerianAnomalyUtility

        e = self.eccentricity
        nu = self.true_anomaly_rad
        if e < 1.0:
            return float(KeplerianAnomalyUtility.ellipticTrueToMean(e, nu))
        return float(KeplerianAnomalyUtility.hyperbolicTrueToMean(e, nu))

    def eccentric_anomaly(self) -> float:
        """Eccentric anomaly E (hyperbolic anomaly H for e > 1) from true anomaly ν.

        Orekit-backed (``KeplerianAnomalyUtility``), same elliptic/hyperbolic branch
        logic as :meth:`mean_anomaly`.
        """
        from .._orekit_init import _ensure_started

        _ensure_started()
        from org.orekit.orbits import KeplerianAnomalyUtility

        e = self.eccentricity
        nu = self.true_anomaly_rad
        if e < 1.0:
            return float(KeplerianAnomalyUtility.ellipticTrueToEccentric(e, nu))
        return float(KeplerianAnomalyUtility.hyperbolicTrueToEccentric(e, nu))

    @classmethod
    def from_state(cls, state: "State") -> "KeplerianElements":
        """Osculating classical elements of ``state`` in its own frame.

        Thin alias for :meth:`State.to_keplerian` (architecture §6): both compute
        the osculating elements in the state's own frame with no implicit
        conversion, so the conversion logic lives in exactly one place.
        """
        return state.to_keplerian()

    def to_state(self, epoch: "Epoch", frame: "Frame") -> "State":
        """Cartesian :class:`State` at ``epoch`` in ``frame`` built from these elements.

        Builds an Orekit ``KeplerianOrbit`` (true-anomaly convention) with Earth's
        WGS84 µ (:func:`core.bodies._earth_mu`) and reads its position+velocity in
        ``frame``. ``frame`` must be pseudo-inertial — a rotating frame such as
        ``ITRF`` raises ``ValueError``, since classical elements are only well-
        defined there. Note Orekit's constructor takes the perigee argument *before*
        the RAAN.
        """
        from .._orekit_init import _ensure_started

        _ensure_started()
        from org.orekit.orbits import KeplerianOrbit, PositionAngleType

        from .bodies import _earth_mu
        from .frames import _require_pseudo_inertial
        from .states import State, _vector3d_to_array

        ok_frame = _require_pseudo_inertial(
            frame,
            "to_state",
            "Build in an inertial frame (e.g. Frame.EME2000) and convert the "
            "resulting State with to_frame if you need a rotating frame.",
        )

        orbit = KeplerianOrbit(
            self.semi_major_axis_m,
            self.eccentricity,
            self.inclination_rad,
            self.arg_perigee_rad,
            self.raan_rad,
            self.true_anomaly_rad,
            PositionAngleType.TRUE,
            ok_frame,
            epoch.to_orekit(),
            _earth_mu(),
        )
        pv = orbit.getPVCoordinates()
        return State(
            epoch,
            _vector3d_to_array(pv.getPosition()),
            _vector3d_to_array(pv.getVelocity()),
            frame,
        )
