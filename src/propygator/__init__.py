"""propygator — orbital simulation and satellite tracking built on Orekit.

Importing this package does NOT start the JVM. The JVM starts lazily on the
first Orekit-touching call, or via an explicit ``propygator.init(vmargs=...)``.
Importing does pull matplotlib/plotly (the re-exported ``plot_*`` verbs), which
are pure-Python and JVM-free.

The Feature 1.1 surface is re-exported here: the data-model types, the
``propagate_numerical`` verb with its config dataclasses (``ForceModelConfig``,
``SpacecraftConfig``/``SpacecraftGeometry``, ``VariableCd``, ``IntegratorConfig``,
``AltitudeLimits``, the attitude family), the ``plot_*`` functions, and
``export_csv`` / ``export_all``.
``BoxFaceCd`` (the per-face, convex-box Tier-B drag table) is re-exported beside
``VariableCd``. Feature 1.3 adds the ``TLE`` type, the ``propagate_tle``
verb, and the CelesTrak ``fetch_tle`` path (``TLE.from_norad_id`` rides on it).
Feature 1.4 adds the realtime verbs (``current_state`` /
``current_ground_position`` / ``live_track``). The v0.5.0 general upgrades add
``USTimeZone`` (the ``live_track`` ``tz=`` civil display zones) and
``ProgressCallback`` (the type of a long-running verb's ``progress=`` callable).
Feature 1.5 adds the pass-prediction surface (``find_passes`` /
``passes_to_dataframe`` / ``export_passes_csv`` / ``export_passes_ics`` /
``plot_sky_chart`` / ``plot_pass_timeline``). Feature 1.2 adds the TLE fitter
(``fit_tle`` / ``fit_tle_detailed`` / ``FitResult``, with ``TLEFitError`` on
non-convergence) — the faithful sibling of ``TLE.from_state_unfitted``.
"""

import logging

from ._orekit_init import clear_cache, init
from .core.elements import KeplerianElements
from .core.exceptions import (
    JVMAlreadyStartedError,
    NumericalPropagationError,
    OrekitDataMissingError,
    PropagationError,
    PropygatorError,
    StaleTLEWarning,
    TLEFetchError,
    TLEFitError,
    TLEPropagationError,
)
from .core.frames import Frame
from .core.observation import (
    AzElRange,
    GeodeticPosition,
    GroundStation,
    Pass,
    look_angles,
    moon_look_angles,
    sun_look_angles,
)
from .core.progress import ProgressCallback
from .core.states import Orientation, State, Trajectory, _propygator_version
from .core.time import Epoch, TimeScale, USTimeZone
from .core.tle import TLE
from .io import export_all, export_csv, export_passes_csv, export_passes_ics
from .plotting import (
    plot_3d,
    plot_altitude,
    plot_ground_track,
    plot_pass_timeline,
    plot_sky_chart,
    plot_sky_track,
    plot_speed,
    plot_summary,
)
from .propagation import (
    AltitudeLimits,
    AttitudeConfig,
    BoxFaceCd,
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
from .tle import FitResult, fetch_tle, fit_tle, fit_tle_detailed, propagate_tle
from .tracking import (
    current_ground_position,
    current_state,
    find_passes,
    live_track,
    passes_to_dataframe,
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
    "NumericalPropagationError",
    "TLEPropagationError",
    "TLEFetchError",
    "TLEFitError",
    "StaleTLEWarning",
    "Epoch",
    "TimeScale",
    "USTimeZone",
    "Frame",
    "State",
    "Trajectory",
    "TLE",
    "KeplerianElements",
    "Orientation",
    "GroundStation",
    "GeodeticPosition",
    "Pass",
    "AzElRange",
    # Feature 1.1 — numerical propagator
    "propagate_numerical",
    "ProgressCallback",
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
    # Feature 1.1 — outputs
    "plot_summary",
    "plot_ground_track",
    "plot_3d",
    "plot_altitude",
    "plot_speed",
    "export_csv",
    "export_all",
    # Feature 1.3 — TLE propagator
    "propagate_tle",
    "fetch_tle",
    # Feature 1.2 — TLE fitter (built last; architecture §12)
    "fit_tle",
    "fit_tle_detailed",
    "FitResult",
    # Feature 1.4 — realtime primitives + live dashboard
    "current_state",
    "current_ground_position",
    "live_track",
    # Feature 1.4 — sky-view kernel (look_angles_track / observer_snapshot stay
    # reachable via propygator.core.observation)
    "look_angles",
    "sun_look_angles",
    "moon_look_angles",
    "plot_sky_track",
    # Feature 1.5 — passes (compute_magnitude stays at tracking.visibility)
    "find_passes",
    "passes_to_dataframe",
    "export_passes_csv",
    "export_passes_ics",
    "plot_sky_chart",
    "plot_pass_timeline",
]
