"""Output surface: file exports of a :class:`~propygator.core.states.Trajectory`.

``export_csv`` (tabular) and ``export_all`` (the bundled summary + 3-D + CSV
aggregator) are re-exported at the top level as ``propygator.export_csv`` /
``propygator.export_all``. The subpackage depends only on ``core/`` at import time
(architecture §7); ``export_all`` reaches into ``plotting/`` lazily, inside the
function body (see ``exports`` module docstring).
"""

from .exports import export_all, export_csv

__all__ = ["export_all", "export_csv"]
