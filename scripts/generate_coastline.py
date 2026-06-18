"""Generate the shipped low-resolution Earth coastline asset (maintainer tool).

The plotting map overlays (``plot_ground_track`` and the ``plot_3d`` ITRF view)
draw a bundled coastline so propygator does not depend on ``cartopy`` (which would
pull GEOS/PROJ into the install and bloat the static-hosting payload). This script
produces that committed asset, ``data/coastline_110m.npz``, once; end users load
the small array and compute nothing (features.md §1.1 "Map machinery").

**What it does.** It downloads the public-domain **Natural Earth 1:110m coastline**
GeoJSON (the lowest-resolution Natural Earth tier — already "reduced", so no extra
geometry simplification is applied), flattens every ``LineString`` /
``MultiLineString`` into ``(longitude, latitude)`` polylines, and concatenates them
into a single ``(K, 2)`` float64 array with a ``[NaN, NaN]`` row separating
consecutive polylines. The NaN-separated layout draws directly: matplotlib's
``LineCollection`` consumes the split polylines and Plotly's ``Scatter3d`` treats
NaN as a line break, so both the 2D overlay and the 3D drape read the one asset.

**Dependencies / where to run.** Needs only ``requests`` (already a propygator
runtime dependency) and the standard-library ``json`` — there is no shapefile
reader and no new generation-only dependency. Run it from a checkout with network
access; the import is deferred inside :func:`download_geojson` so ``--help`` works
offline. Nothing here is imported by the package.

Examples
--------
Regenerate the committed asset from the pinned Natural Earth release::

    python scripts/generate_coastline.py --force

Use a different Natural Earth ref or output path::

    python scripts/generate_coastline.py --ref master --output /tmp/coast.npz
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

# Natural Earth vector data, mirrored as GeoJSON by the canonical community repo.
# Pinned to a tagged release for reproducibility (override with --ref). The 1:110m
# coastline is public domain (Natural Earth terms of use).
_REPO = "nvkelso/natural-earth-vector"
_DEFAULT_REF = "v5.1.2"
_GEOJSON_PATH = "geojson/ne_110m_coastline.geojson"
_LICENSE = "public domain (Natural Earth)"

_DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "coastline_110m.npz"


def _source_url(ref: str) -> str:
    """Raw-content URL for the 1:110m coastline GeoJSON at ``ref``."""
    return f"https://raw.githubusercontent.com/{_REPO}/{ref}/{_GEOJSON_PATH}"


def download_geojson(ref: str) -> dict:
    """Fetch and parse the Natural Earth 1:110m coastline GeoJSON at ``ref``.

    Uses ``requests`` (deferred import so ``--help`` runs without it / offline).
    """
    import requests  # runtime dependency; imported here so --help works offline

    url = _source_url(ref)
    logger.info("Downloading %s", url)
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def _polylines_from_geojson(geojson: dict) -> list[NDArray[np.float64]]:
    """Flatten the coastline features into a list of ``(M, 2)`` lon/lat polylines.

    GeoJSON stores coordinates as ``[longitude, latitude]`` (degrees), which is the
    order the asset preserves. ``LineString`` yields one polyline; ``MultiLineString``
    yields one per part. Any other geometry type is skipped with a warning.
    """
    polylines: list[NDArray[np.float64]] = []
    for feature in geojson["features"]:
        geometry = feature["geometry"]
        gtype = geometry["type"]
        if gtype == "LineString":
            polylines.append(np.asarray(geometry["coordinates"], dtype=np.float64))
        elif gtype == "MultiLineString":
            for part in geometry["coordinates"]:
                polylines.append(np.asarray(part, dtype=np.float64))
        else:  # pragma: no cover - the coastline layer is only (Multi)LineString
            logger.warning("skipping unexpected geometry type %r", gtype)
    return polylines


def _nan_separated(polylines: list[NDArray[np.float64]]) -> NDArray[np.float64]:
    """Concatenate polylines into one ``(K, 2)`` array, NaN-separating each."""
    separator = np.array([[np.nan, np.nan]], dtype=np.float64)
    parts: list[NDArray[np.float64]] = []
    for index, polyline in enumerate(polylines):
        if index > 0:
            parts.append(separator)
        parts.append(polyline)
    return np.concatenate(parts, axis=0)


def generate(ref: str) -> tuple[NDArray[np.float64], dict[str, object]]:
    """Build the NaN-separated ``(K, 2)`` lon/lat array plus provenance metadata."""
    geojson = download_geojson(ref)
    polylines = _polylines_from_geojson(geojson)
    coastline = _nan_separated(polylines)
    n_points = int(np.sum(np.isfinite(coastline[:, 0])))
    logger.info(
        "Flattened %d polylines into a (%d, 2) array (%d coordinate points)",
        len(polylines),
        coastline.shape[0],
        n_points,
    )
    metadata: dict[str, object] = {
        "source": "Natural Earth 1:110m coastline",
        "url": _source_url(ref),
        "ref": ref,
        "license": _LICENSE,
        "layout": "lon/lat degrees, [NaN, NaN] rows separate polylines",
        "n_polylines": len(polylines),
        "n_points": n_points,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return coastline, metadata


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: download, flatten, and write the ``.npz`` asset."""
    parser = argparse.ArgumentParser(
        description="Generate the shipped low-res Earth coastline asset.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--output", type=Path, default=_DEFAULT_OUTPUT, help="Output .npz path."
    )
    parser.add_argument(
        "--ref",
        default=_DEFAULT_REF,
        help="Natural Earth (nvkelso/natural-earth-vector) git ref to download.",
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing output file."
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Debug-level logging."
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    output: Path = args.output
    if output.exists() and not args.force:
        logger.error("%s already exists; pass --force to overwrite.", output)
        raise SystemExit(1)

    coastline, metadata = generate(args.ref)

    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        coastline=coastline,
        metadata_json=np.asarray(json.dumps(metadata)),
    )
    logger.info("Wrote %s (array shape %s)", output, coastline.shape)


if __name__ == "__main__":
    main()
