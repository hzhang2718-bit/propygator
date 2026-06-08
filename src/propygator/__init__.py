"""propygator — orbital simulation and satellite tracking built on Orekit.

Importing this package does NOT start the JVM. The JVM starts lazily on the
first Orekit-touching call, or via an explicit ``propygator.init(vmargs=...)``.
The public verb/type surface is re-exported as later chunks land.
"""

import logging
from importlib.metadata import version

from ._orekit_init import clear_cache, init
from .core.elements import KeplerianElements
from .core.exceptions import (
    JVMAlreadyStartedError,
    OrekitDataMissingError,
    PropygatorError,
)
from .core.frames import Frame
from .core.observation import GeodeticPosition, GroundStation, Pass
from .core.states import Orientation, State, Trajectory
from .core.time import Epoch, TimeScale

__version__ = version("propygator")

# Silent by default; applications opt in via logging.basicConfig(...).
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "__version__",
    "init",
    "clear_cache",
    "PropygatorError",
    "OrekitDataMissingError",
    "JVMAlreadyStartedError",
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
]
