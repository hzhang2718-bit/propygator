"""Tests for the locked plotting styling baseline (build-plan chunk 11a).

Pure-Python and headless (the ``tests/plotting`` conftest pins the Agg backend); no
JVM. These pin the cosmetic baseline the §11 snapshots record against and assert the
key invariant that styling is applied *per figure* — the global ``rcParams`` are
unchanged after a styled block — so the style never leaks out of a ``plot_*`` call.
"""

from __future__ import annotations

import matplotlib
import matplotlib.colors as mcolors
import pytest

from propygator.plotting.style import (
    MARKER_END,
    MARKER_START,
    OUTLINE_COLOR,
    PLOTLY_TIME_COLORSCALE,
    TIME_CMAP,
    TIME_COLOR_END,
    TIME_COLOR_START,
    TIMESERIES_COLOR,
    _apply_plotly_template,
    _mpl_style,
    _plotly_template,
)

# rcParams keys the style sheet sets; snapshotted to prove the context restores them.
_STYLE_KEYS = [
    "axes.edgecolor",
    "axes.grid",
    "axes.axisbelow",
    "grid.color",
    "grid.linewidth",
    "lines.linewidth",
    "figure.facecolor",
    "axes.labelsize",
]


def test_mpl_style_applies_then_reverts() -> None:
    """The context applies the bundled style and fully restores rcParams on exit."""
    before = {key: matplotlib.rcParams[key] for key in _STYLE_KEYS}

    with _mpl_style():
        # A few values that prove the sheet took effect (defaults differ from these).
        assert matplotlib.rcParams["axes.grid"] is True
        assert matplotlib.rcParams["lines.linewidth"] == pytest.approx(1.4)
        assert matplotlib.rcParams["grid.linewidth"] == pytest.approx(0.6)
        assert mcolors.to_hex(matplotlib.rcParams["axes.edgecolor"]) == "#000000"

    after = {key: matplotlib.rcParams[key] for key in _STYLE_KEYS}
    assert after == before


def test_mpl_style_default_line_is_navy() -> None:
    """Inside the styled context, the default prop-cycle colour is the dark navy."""
    with _mpl_style():
        first = matplotlib.rcParams["axes.prop_cycle"].by_key()["color"][0]
    assert mcolors.to_hex(first) == TIMESERIES_COLOR


def test_importing_style_does_not_mutate_global_rcparams() -> None:
    """Merely using the module leaves global rcParams at their defaults (grid off)."""
    # The style sheet turns the grid on; if importing/using the module leaked that
    # globally, this default would be wrong. (matplotlib's built-in default is False.)
    assert matplotlib.rcParams["axes.grid"] is False


def test_time_cmap_endpoints() -> None:
    """The time colormap runs blue→red between the locked endpoints."""
    assert isinstance(TIME_CMAP, mcolors.Colormap)
    assert mcolors.to_hex(TIME_CMAP(0.0)) == TIME_COLOR_START
    assert mcolors.to_hex(TIME_CMAP(1.0)) == TIME_COLOR_END
    # The Plotly colorscale mirrors the same endpoints.
    assert mcolors.to_hex(PLOTLY_TIME_COLORSCALE[0][1]) == TIME_COLOR_START
    assert mcolors.to_hex(PLOTLY_TIME_COLORSCALE[-1][1]) == TIME_COLOR_END


def test_locked_colours() -> None:
    """The dark-navy line colour and black outline are the agreed hexes."""
    assert TIMESERIES_COLOR == "#1f3b73"
    assert TIME_COLOR_START == "#2166ac"
    assert TIME_COLOR_END == "#b2182b"
    assert OUTLINE_COLOR == "black"


def test_endpoint_markers() -> None:
    """Start = blue circle; end cosmetics = red + black edge (shape built at draw)."""
    assert MARKER_START["marker"] == "o"
    # The end glyph's shape (a heading-rotated triangle) is data-dependent, so it has no
    # "marker" key — it would collide with the MarkerStyle the caller passes.
    assert "marker" not in MARKER_END
    assert mcolors.to_hex(MARKER_START["c"]) == TIME_COLOR_START
    assert mcolors.to_hex(MARKER_END["c"]) == TIME_COLOR_END
    assert MARKER_START["edgecolors"] == OUTLINE_COLOR
    assert MARKER_END["edgecolors"] == OUTLINE_COLOR


def test_plotly_template_is_white() -> None:
    """The shared Plotly template carries the white-background layout cosmetics."""
    template = _plotly_template()
    assert template.layout.paper_bgcolor == "white"
    assert template.layout.plot_bgcolor == "white"


def test_apply_plotly_template_sets_figure_template() -> None:
    """Applying the template wires it onto a figure in place."""
    import plotly.graph_objects as go

    fig = go.Figure()
    _apply_plotly_template(fig)
    assert fig.layout.template is not None
    assert fig.layout.template.layout.paper_bgcolor == "white"
