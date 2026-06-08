"""propygator — orbital simulation and satellite tracking built on Orekit.

Importing this package does NOT start the JVM. The JVM starts lazily on the
first Orekit-touching call, or via an explicit ``propygator.init(vmargs=...)``.
The public verb/type surface is re-exported as later chunks land.
"""

import logging
from importlib.metadata import version

from ._orekit_init import clear_cache, init
from .core.exceptions import (
    JVMAlreadyStartedError,
    OrekitDataMissingError,
    PropygatorError,
)

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
]
