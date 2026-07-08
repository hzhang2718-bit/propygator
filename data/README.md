# data/

Small bundled reference data for propygator, kept in version control. This is
distinct from the large external `orekit-data/` (leap seconds, EOP, ephemerides),
which is *not* shipped and is fetched separately via
`scripts/download_orekit_data.py`.

## Contents

- **`sphere_cd_default.npz`** — the shipped variable drag-coefficient table loaded by
  `VariableCd.sphere_default()` (Feature 1.1). A `(geocentric radius, total density)`
  grid of free-molecular sphere Cd values, with keys `grid` (shape
  `(n_radius, n_density)`), `radius_axis` (m), `density_axis` (kg/m³, log-spaced), and
  a `metadata_json` provenance string. Regenerate with
  `python scripts/generate_sphere_cd_table.py` (a one-time maintainer step needing the
  generation-only deps in `scripts/requirements-generate.txt`; see that script's
  docstring). End users load the committed array and compute nothing.

  The runtime lookup (`VariableCd.__call__`) interpolates bilinearly in *raw* density
  between the log-spaced nodes, whereas the generator regridded in log10(density);
  across one density cell the two schemes differ by only ~0.1–0.3 % of Cd (negligible
  against thermospheric density uncertainty), so raw-linear interpolation is kept.

- **`box_face_cd_default.npz`** — the shipped per-face drag-coefficient table loaded by
  `BoxFaceCd.default()` (Tier B drag, `docs/history/general-upgrades-1.md` "Tier B Drag"). A
  `(geocentric radius, total density, face-flow angle θ)` grid of free-molecular **box
  face** Cd values (Schaaf–Chambre/Sentman DRIA, normal pressure + tangential shear,
  referenced to the face's *full* area), with keys `grid` (shape
  `(n_radius, n_density, n_incidence)`), `radius_axis` (m), `density_axis` (kg/m³,
  log-spaced), `incidence_axis` (rad, uniform over `[0, π]`), and a `metadata_json`
  provenance string. The runtime sums `CdA = Σ_i Cd_i(θ_i)·A_i` over the six faces of a
  convex box. It shares the sphere table's gas-surface assumptions (SESAM α anchor,
  300 K wall, diffuse re-emission) — cross-table coherence. Regenerate with
  `python scripts/generate_box_face_cd_table.py` (same generation-only deps as the
  sphere table; see that script's docstring). End users load the committed array and
  compute nothing.

- **`coastline_110m.npz`** — the bundled low-resolution **Natural Earth 1:110m**
  coastline used to draw map overlays on ground-track plots and to drape the 3D ITRF
  Earth (Feature 1.1 plotting, `propygator.plotting.basemap`). No `cartopy`: it stores
  a single NaN-separated `(K, 2)` float64 array under key `coastline` — `[longitude,
  latitude]` degrees, with `[NaN, NaN]` rows separating consecutive polylines — plus a
  `metadata_json` provenance string. The 1:110m tier is already the lowest-resolution
  Natural Earth coastline, so no extra geometry simplification is applied. Regenerate
  with `python scripts/generate_coastline.py` (downloads the public-domain GeoJSON;
  needs only `requests`, an existing runtime dependency). Natural Earth data is public
  domain.

## A note on packaging

These assets live at the repo root, **outside** the importable package
(`docs/architecture.md` §5). The package loads them via a path into the source tree,
which works for an editable install (`pip install -e .`) and source checkouts —
propygator's only distribution mode (`docs/project_meta.md`: GitHub-only, no PyPI). A
built *wheel* would not contain this directory; if propygator ever ships one, move the
asset(s) into `src/propygator/`, add them to `[tool.setuptools.package-data]`, and
switch the `_data_dir()` helpers (in `propagation/spacecraft.py` and
`plotting/basemap.py` — duplicated, two lines each, so `plotting/` need not import
across the `propagation` boundary) to `importlib.resources` — no caller changes needed.
