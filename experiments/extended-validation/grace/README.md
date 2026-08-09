# GRACE leg (Chunk 1 onward)

Original GRACE A (NORAD 27391) and GRACE B (27392), 2002-2017.

Lands here in Chunk 1: `grace_l1b.py` (the reader, its own module -- never an
additive edit to the frozen `gnv1b.py`), `grace_common.py` (leg config), and
`run_grace_checkout.py`.

**Open until Chunk 1:** the L1B record format (ASCII vs binary) and the
per-month download volume. PO.DAAC serves GRACE as **monthly bundles, ~250 MB**
(confirmed 2026-08-09), so cost scales with distinct months touched, not days.

The decisive parse self-check is the **A-B separation**, asserted as a band
(roughly 150-300 km), never a point value -- the gap is actively maintained and
drifts. `|r|` and `|v|` carry the sharp part of the check.
