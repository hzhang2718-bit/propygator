"""propygator — orbital simulation and satellite tracking built on Orekit.

Importing this package does NOT start the JVM (lazy init lands in a later
chunk). Only __version__ and the package logger's NullHandler are wired up
here; the public verb/type surface is re-exported as later chunks land.
"""

import logging
from importlib.metadata import version

__version__ = version("propygator")

# Silent by default; applications opt in via logging.basicConfig(...).
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = ["__version__"]
