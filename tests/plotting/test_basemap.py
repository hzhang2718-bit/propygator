"""Tests for the bundled Earth coastline basemap (build-plan chunk 11a).

Pure-Python and headless (the ``tests/plotting`` conftest pins the Agg backend); no
JVM. They assert the committed asset loads, splits into NaN-free polylines, and that
``_render_earth_basemap`` draws a non-empty *black* coastline onto a supplied Axes.
"""

from __future__ import annotations

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection

from propygator.plotting.basemap import (
    _coastline_lonlat,
    _coastline_polylines,
    _render_earth_basemap,
)


def test_coastline_asset_loads_nan_separated() -> None:
    """The asset is a read-only (K, 2) lon/lat array with NaN separators in range."""
    arr = _coastline_lonlat()
    assert arr.ndim == 2 and arr.shape[1] == 2
    assert arr.dtype == np.float64
    assert not arr.flags.writeable  # cached + frozen against mutation
    assert np.isnan(arr).any()  # polyline separators present
    lon, lat = arr[:, 0], arr[:, 1]
    assert -180.001 <= np.nanmin(lon) and np.nanmax(lon) <= 180.001
    assert -90.001 <= np.nanmin(lat) and np.nanmax(lat) <= 90.001


def test_polylines_split_clean() -> None:
    """Splitting yields many polylines, each a finite (M, 2) array (no NaN)."""
    polylines = _coastline_polylines()
    assert len(polylines) > 50  # Natural Earth 1:110m has ~134 coastline features
    for polyline in polylines:
        assert polyline.ndim == 2 and polyline.shape[1] == 2
        assert polyline.shape[0] >= 2
        assert np.isfinite(polyline).all()


def test_render_basemap_draws_black_nonempty() -> None:
    """The basemap is a black LineCollection added to the supplied Axes."""
    fig, ax = plt.subplots()
    try:
        collection = _render_earth_basemap(ax)
        assert isinstance(collection, LineCollection)
        assert collection in ax.collections

        segments = collection.get_segments()
        assert len(segments) > 50
        assert sum(len(seg) for seg in segments) > 1000  # thousands of coast points

        colors = collection.get_colors()
        assert len(colors) >= 1
        assert np.allclose(colors[0], mcolors.to_rgba("black"))
    finally:
        plt.close(fig)


def test_render_basemap_respects_color_override() -> None:
    """A caller may override the coastline colour (default is black)."""
    fig, ax = plt.subplots()
    try:
        collection = _render_earth_basemap(ax, color="#808080")
        assert np.allclose(collection.get_colors()[0], mcolors.to_rgba("#808080"))
    finally:
        plt.close(fig)
