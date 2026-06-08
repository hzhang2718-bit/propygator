"""``State`` — the canonical "where is this object, when, in what frame."

A :class:`State` is an immutable Cartesian position+velocity at an :class:`Epoch`
in an explicit :class:`Frame`. Construction and validation are pure-Python and
safe before JVM init (architecture §10); only the deferred conversion methods
(:meth:`State.to_frame`, :meth:`State.to_keplerian`, :meth:`State.to_orekit`)
touch Orekit, and they land with Feature 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from .frames import Frame
from .time import Epoch

if TYPE_CHECKING:
    # Type-only. org.orekit.* is a runtime JPype stub; KeplerianElements lands
    # in build-plan chunk 5 (core/elements.py).
    import org.orekit.propagation  # noqa: F401

    from .elements import KeplerianElements  # noqa: F401


_FEATURE1_NOTE = (
    "{name} is deferred to Feature 1 (numerical propagator). It performs an "
    "Orekit-backed conversion, so it is not part of the pure-Python, "
    "safe-before-init surface (architecture §10)."
)


@dataclass(frozen=True)
class State:
    """An object's Cartesian position+velocity at an epoch, in an explicit frame.

    Immutable, with the frame mandatory (no defaults). No Orekit types appear in
    the field annotations. ``position``/``velocity`` are SI (meters, m/s), shape
    ``(3,)``, ``float64`` — enforced in :meth:`__post_init__` so a buggy path
    producing shape ``(1, 3)``, ``float32``, or a non-finite value fails at the
    construction site rather than surfacing later as an opaque Orekit failure.
    """

    epoch: Epoch
    position: np.ndarray
    velocity: np.ndarray
    frame: Frame

    def __post_init__(self) -> None:
        # Type annotations don't enforce ndarray-ness; a non-array would fail on
        # .shape with an opaque AttributeError, so check it first for a clean error.
        if not isinstance(self.position, np.ndarray) or not isinstance(
            self.velocity, np.ndarray
        ):
            raise TypeError(
                "position and velocity must be numpy.ndarray, got "
                f"{type(self.position).__name__} and {type(self.velocity).__name__}"
            )
        if self.position.shape != (3,) or self.velocity.shape != (3,):
            raise ValueError(
                f"position and velocity must have shape (3,), "
                f"got {self.position.shape} and {self.velocity.shape}"
            )
        if self.position.dtype != np.float64 or self.velocity.dtype != np.float64:
            raise ValueError("position and velocity must be float64")
        # np.isfinite is False for both NaN and inf.
        if not (
            np.all(np.isfinite(self.position)) and np.all(np.isfinite(self.velocity))
        ):
            raise ValueError("position and velocity must be finite (no NaN or inf)")

    def to_frame(self, target_frame: Frame) -> "State":
        """Return this state expressed in ``target_frame`` (deferred to Feature 1)."""
        raise NotImplementedError(_FEATURE1_NOTE.format(name="State.to_frame"))

    def to_keplerian(self) -> "KeplerianElements":
        """Return the osculating classical elements (deferred to Feature 1)."""
        raise NotImplementedError(_FEATURE1_NOTE.format(name="State.to_keplerian"))

    if TYPE_CHECKING:

        def to_orekit(self) -> "org.orekit.propagation.SpacecraftState": ...

    else:

        def to_orekit(self):
            """Build the Orekit ``SpacecraftState`` (deferred to Feature 1)."""
            raise NotImplementedError(_FEATURE1_NOTE.format(name="State.to_orekit"))
