"""``KeplerianElements`` — the classical orbital-element representation.

A frozen, SI dataclass holding the six classical elements with the **true
anomaly** as the canonical angular coordinate (architecture §6). Construction and
field validation are pure-Python and safe before JVM init; the conversions
(:meth:`KeplerianElements.from_state`, :meth:`to_state`) and the derived-anomaly
methods (:meth:`mean_anomaly`, :meth:`eccentric_anomaly`) are deferred to
Feature 1 (build-plan chunk 5 ships the validated skeleton only).

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


_DEFERRED_NOTE = (
    "{name} is deferred to Feature 1 (numerical propagator); KeplerianElements "
    "ships as a validated skeleton in the groundwork build (build-plan chunk 5)."
)


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
            raise ValueError(
                f"semi_major_axis_m must be finite and nonzero, got {a!r}"
            )
        if not math.isfinite(e) or e < 0.0:
            raise ValueError(f"eccentricity must be finite and >= 0, got {e!r}")
        # For a bound (elliptical) orbit a must be positive; hyperbolic orbits
        # (e > 1) legitimately carry a < 0, so only constrain the e < 1 case.
        if e < 1.0 and a <= 0.0:
            raise ValueError(
                f"elliptical orbit (e={e!r} < 1) requires semi_major_axis_m > 0, "
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

    def mean_anomaly(self) -> float:
        """Mean anomaly M from the stored true anomaly (deferred to Feature 1)."""
        raise NotImplementedError(
            _DEFERRED_NOTE.format(name="KeplerianElements.mean_anomaly")
        )

    def eccentric_anomaly(self) -> float:
        """Eccentric anomaly E from the stored true anomaly (deferred to Feature 1)."""
        raise NotImplementedError(
            _DEFERRED_NOTE.format(name="KeplerianElements.eccentric_anomaly")
        )

    @classmethod
    def from_state(cls, state: "State") -> "KeplerianElements":
        """Osculating elements of ``state`` in its own frame (deferred to Feature 1)."""
        raise NotImplementedError(
            _DEFERRED_NOTE.format(name="KeplerianElements.from_state")
        )

    def to_state(self, epoch: "Epoch", frame: "Frame") -> "State":
        """Cartesian state at ``epoch`` in ``frame`` (deferred to Feature 1)."""
        raise NotImplementedError(
            _DEFERRED_NOTE.format(name="KeplerianElements.to_state")
        )
