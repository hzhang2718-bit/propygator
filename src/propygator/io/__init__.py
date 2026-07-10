"""Output surface: file exports of trajectories and pass lists.

``export_csv`` (tabular) and ``export_all`` (the bundled summary + 3-D + CSV
aggregator) export a :class:`~propygator.core.states.Trajectory`;
``export_passes_csv`` / ``export_passes_ics`` export a ``find_passes`` pass list
(Feature 1.5). All four are re-exported at the top level (``propygator.export_csv``
…). The subpackage depends only on ``core/`` at import time (architecture §7) — a
``Pass`` is a ``core/`` type, so the pass exporters add no new edge; ``export_all``
reaches into ``plotting/`` lazily, inside the function body (see ``exports`` module
docstring).
"""

from .exports import export_all, export_csv, export_passes_csv, export_passes_ics

__all__ = ["export_all", "export_csv", "export_passes_csv", "export_passes_ics"]
