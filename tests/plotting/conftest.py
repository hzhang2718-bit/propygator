"""Force the headless Agg matplotlib backend for every plotting test (chunk 11a).

The plotting suite is fully headless (architecture §11): no display is opened and no
window pops up in CI. Selecting Agg here — before any test imports ``pyplot`` — keeps
the whole ``tests/plotting`` package off the default interactive backend.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
