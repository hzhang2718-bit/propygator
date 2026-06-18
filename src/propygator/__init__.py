"""propygator — orbital simulation and satellite tracking built on Orekit.

Importing this package does NOT start the JVM. The JVM starts lazily on the
first Orekit-touching call, or via an explicit ``propygator.init(vmargs=...)``.
Importing does pull matplotlib/plotly (the re-exported ``plot_*`` verbs), which
are pure-Python and JVM-free.

The Feature 1.1 surface is re-exported here: the data-model types, the
``propagate_numerical`` verb with its config dataclasses (``ForceModelConfig``,
``SpacecraftConfig``/``SpacecraftGeometry``, ``VariableCd``, ``IntegratorConfig``,
the attitude family), the ``plot_*`` functions, and ``export_csv`` / ``export_all``.
``IncidenceVariableCd`` (the deferred Tier-B skeleton) stays reachable via
``propygator.propagation``. Later features (1.3 TLE propagation onward) add more
verbs.
"""

import logging

from ._orekit_init import clear_cache, init
from .core.elements import KeplerianElements
from .core.exceptions import (
    JVMAlreadyStartedError,
    OrekitDataMissingError,
    PropagationError,
    PropygatorError,
)
from .core.frames import Frame
from .core.observation import GeodeticPosition, GroundStation, Pass
from .core.states import Orientation, State, Trajectory, _propygator_version
from .core.time import Epoch, TimeScale
from .io import export_all, export_csv
from .plotting import (
    plot_3d,
    plot_altitude,
    plot_ground_track,
    plot_speed,
    plot_summary,
)
from .propagation import (
    AttitudeConfig,
    CustomAttitude,
    ForceModelConfig,
    Inertial,
    InPlaneTracking,
    IntegratorConfig,
    LofAligned,
    LofOffset,
    NadirPointing,
    SpacecraftConfig,
    SpacecraftGeometry,
    SunPointing,
    VariableCd,
    propagate_numerical,
)

# Single-sourced via core.states._propygator_version (importlib.metadata), which
# returns "unknown" when running from a source tree without distribution metadata
# (the same value Trajectory metadata records), so import never hard-fails here.
__version__ = _propygator_version()

# Silent by default; applications opt in via logging.basicConfig(...).
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "__version__",
    "init",
    "clear_cache",
    "PropygatorError",
    "OrekitDataMissingError",
    "JVMAlreadyStartedError",
    "PropagationError",
    "Epoch",
    "TimeScale",
    "Frame",
    "State",
    "Trajectory",
    "KeplerianElements",
    "Orientation",
    "GroundStation",
    "GeodeticPosition",
    "Pass",
    # Feature 1.1 — numerical propagator
    "propagate_numerical",
    "ForceModelConfig",
    "IntegratorConfig",
    "SpacecraftConfig",
    "SpacecraftGeometry",
    "VariableCd",
    "AttitudeConfig",
    "LofAligned",
    "LofOffset",
    "Inertial",
    "SunPointing",
    "NadirPointing",
    "InPlaneTracking",
    "CustomAttitude",
    # Feature 1.1 — outputs
    "plot_summary",
    "plot_ground_track",
    "plot_3d",
    "plot_altitude",
    "plot_speed",
    "export_csv",
    "export_all",
]
