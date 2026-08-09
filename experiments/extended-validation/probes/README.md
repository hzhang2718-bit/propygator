# Probes (Chunk 5 onward)

The fitter / storm / fading-memory probes and their results.

`anchors.py` -- the shared anchor and forecast harness (anchor placement, the
staging-fit pair, the arm runners, the ITRF-on-truth-grid diff) -- is a **Chunk
5 deliverable**, not a later extraction: Chunks 6, 7, 8 and 9 all consume it.

Thresholds are **frozen inputs** carried verbatim from
`docs/tle-fitting-playbook.md`: `RATIO_THRESHOLD = 0.05`, `S_THRESHOLD = 0.1`.
Re-fitting them to this study's data and reporting that they classify is
circular and forbidden; any recalibration is a separate, clearly labelled
post-hoc section.
