# data/

Small bundled reference data for propygator, kept in version control. This is
distinct from the large external `orekit-data/` (leap seconds, EOP, ephemerides),
which is *not* shipped and is fetched separately via
`scripts/download_orekit_data.py`.

Currently empty. The low-resolution Natural Earth coastline used to draw map
overlays on ground-track plots is sourced during Feature 1.1 (plotting), not yet.
See `docs/architecture.md` §5 and the plotting notes in `CLAUDE.md`.
