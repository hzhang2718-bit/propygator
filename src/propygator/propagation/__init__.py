"""Propagation configuration and the numerical propagator (Feature 1.1).

Re-exports the pure-Python, safe-before-init config dataclasses as they land.
``propagate_numerical`` is added in build-plan chunk 7; the top-level
``propygator`` re-export of this surface is deferred to chunk 12.
"""

from __future__ import annotations

from .attitude import (
    AttitudeConfig,
    CustomAttitude,
    Inertial,
    InPlaneTracking,
    LofAligned,
    LofOffset,
    NadirPointing,
    SunPointing,
)
from .force_models import ForceModelConfig
from .guards import AltitudeLimits
from .integrators import IntegratorConfig
from .numerical import propagate_numerical
from .spacecraft import (
    BoxFaceCd,
    SpacecraftConfig,
    SpacecraftGeometry,
    VariableCd,
)

__all__ = [
    "propagate_numerical",
    "ForceModelConfig",
    "IntegratorConfig",
    "SpacecraftConfig",
    "SpacecraftGeometry",
    "VariableCd",
    "BoxFaceCd",
    "AltitudeLimits",
    "AttitudeConfig",
    "LofAligned",
    "LofOffset",
    "Inertial",
    "SunPointing",
    "NadirPointing",
    "InPlaneTracking",
    "CustomAttitude",
]
