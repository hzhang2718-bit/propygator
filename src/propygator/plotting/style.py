"""The locked plotting cosmetic baseline (build-plan chunk 11a).

This module fixes the visual baseline every ``plot_*`` function draws against so the
§11 snapshot tests are stable the first time they are recorded (features.md §1.1
"Styling"): the blue→red time colormap, the dark-navy time-series colour, the
endpoint marker glyphs, default figure sizes, and the analogous Plotly layout
template.

Two invariants:

- **Per-figure, never global.** :func:`_mpl_style` is a *context manager* wrapping
  ``matplotlib.style.context`` on the shipped ``propygator.mplstyle``; importing this
  module does not mutate global ``rcParams`` and each ``plot_*`` applies the style
  only for the duration of its own figure build.
- **Cosmetic, tunable post-snapshot.** The exact hexes / sizes here are the
  deliberately-locked baseline (features.md defers them to implementation); they may
  be retuned, which simply re-records the snapshots.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import matplotlib.style as mpl_style
from matplotlib.colors import LinearSegmentedColormap

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractContextManager

    import plotly.graph_objects as go

    from ..core.frames import Frame
    from ..core.states import Trajectory


def _require_min_samples(traj: "Trajectory", minimum: int = 2) -> None:
    """Raise ``ValueError`` if ``traj`` has fewer than ``minimum`` samples.

    The drawing primitives index the first/last sample and build a time-coloured
    line, so an empty trajectory crashes them with a bare ``IndexError`` and a
    single sample yields a degenerate (zero-width) time axis and colorbar. Every
    public ``plot_*`` calls this first so the failure is one clean, consistent
    ``ValueError`` at the boundary rather than an opaque error from inside matplotlib.
    """
    n = len(traj)
    if n < minimum:
        raise ValueError(
            f"plotting requires at least {minimum} trajectory samples, got {n}."
        )


def _dedupe_frames(frames: Sequence[Frame], *, what: str) -> list[Frame]:
    """De-duplicate ``frames`` preserving order; raise ``ValueError`` if empty.

    ``Frame.J2000`` is an enum alias of ``Frame.EME2000``, so aliased/repeated frames
    collapse to one. ``what`` names the caller (e.g. ``"plot_speed `frames`"``) for the
    error message. Shared by the verbs that take a frame sequence (``plot_speed`` /
    ``plot_summary``) so the de-dupe and the empty-input guard read the same everywhere.
    """
    ordered = list(dict.fromkeys(frames))
    if not ordered:
        raise ValueError(f"{what} requires at least one frame.")
    return ordered


# --- locked colours ---------------------------------------------------------

#: Time colormap endpoints, t=0 → t=end (ColorBrewer RdBu extremes): a saturated
#: blue start and red end with a still-visible purple midtone on a white background.
TIME_COLOR_START = "#2166ac"  # blue
TIME_COLOR_END = "#b2182b"  # red

#: Dark navy for every time-series (altitude / speed) line.
TIMESERIES_COLOR = "#1f3b73"

#: Black for all outlines: axes spines, marker edges, the coastline.
OUTLINE_COLOR = "black"

#: The blue→red "time" colormap for the (time-ordered) ground-track and 3D traces,
#: read by a matplotlib ``LineCollection`` and the Plotly trace colorscale alike.
TIME_CMAP = LinearSegmentedColormap.from_list(
    "propygator_time", [TIME_COLOR_START, TIME_COLOR_END]
)

#: Plotly colorscale mirroring ``TIME_CMAP`` (used by the 3D trace in chunk 11e).
PLOTLY_TIME_COLORSCALE: list[list[Any]] = [
    [0.0, TIME_COLOR_START],
    [1.0, TIME_COLOR_END],
]


# --- endpoint markers (drawn on the time-coloured spatial plots; chunks 11c/11e) ---

#: Base scatter size (points²) for an endpoint marker; the end glyph is enlarged so it
#: reads at the same visual weight as the start circle.
_MARKER_SIZE = 70.0

#: Start-of-trajectory marker: a blue circle with a black edge. Spread as
#: ``ax.scatter(lon, lat, **MARKER_START)`` (matplotlib); the Plotly start glyph
#: is a matching blue circle. The end glyph is direction-indicating (a heading
#: triangle in 2-D, a velocity cone in 3-D) and is built in the draw functions.
MARKER_START: dict[str, Any] = {
    "marker": "o",
    "c": TIME_COLOR_START,
    "edgecolors": OUTLINE_COLOR,
    "s": _MARKER_SIZE,
    "zorder": 5,
    "label": "start",
}

#: End-of-trajectory marker cosmetics: a red glyph with a black edge. The glyph
#: *shape* — a triangle rotated to the local track heading — is data-dependent, so it
#: cannot live here; ``_draw_ground_track`` builds the rotated ``MarkerStyle`` and
#: spreads these keys alongside it (hence no ``"marker"`` key, which would collide).
MARKER_END: dict[str, Any] = {
    "c": TIME_COLOR_END,
    "edgecolors": OUTLINE_COLOR,
    "s": _MARKER_SIZE * 1.7,
    "zorder": 5,
    "label": "end",
}


# --- default figure sizes ---------------------------------------------------

#: One time-series panel (``plot_altitude`` / a single ``plot_speed`` panel), inches.
FIGSIZE_TIMESERIES = (9.0, 3.2)
#: The 2D ground-track map, inches (≈ 2:1 for a −180..180 / −90..90 extent).
FIGSIZE_GROUND_TRACK = (9.0, 4.5)
#: The stacked ``plot_summary`` composite, inches.
FIGSIZE_SUMMARY = (9.0, 10.0)
#: The Plotly ``plot_3d`` view, *pixels* (Plotly sizes in px, not inches).
FIGSIZE_3D_PX = (800, 700)


# --- matplotlib style application -------------------------------------------

_STYLE_PATH = Path(__file__).with_name("propygator.mplstyle")


def _mpl_style() -> AbstractContextManager[None]:
    """Return a context manager applying the bundled style for one figure build.

    Wraps ``matplotlib.style.context`` on the shipped ``propygator.mplstyle`` so the
    global ``rcParams`` are restored on exit — the style is applied per figure and
    never mutated globally. Use as::

        with _mpl_style():
            fig, ax = plt.subplots()
            ...
    """
    return mpl_style.context(str(_STYLE_PATH))


# --- Plotly layout template -------------------------------------------------


def _plotly_template() -> go.layout.Template:
    """Build the shared Plotly layout template (white, matching the mpl baseline).

    Plotly is imported lazily so the matplotlib-only plots (chunks 11b–11d) never pay
    to import it. The blue→red trace colouring is applied by the 3D draw code via
    :data:`PLOTLY_TIME_COLORSCALE`; this template carries only layout cosmetics.
    """
    import plotly.graph_objects as go

    axis = {
        "showbackground": False,
        "gridcolor": "#cccccc",
        "zerolinecolor": "#cccccc",
        "linecolor": "black",
    }
    return go.layout.Template(
        layout={
            "paper_bgcolor": "white",
            "plot_bgcolor": "white",
            "font": {"size": 12, "color": "black"},
            "scene": {"xaxis": axis, "yaxis": axis, "zaxis": axis},
        }
    )


def _apply_plotly_template(fig: go.Figure) -> None:
    """Apply the shared Plotly layout template to ``fig`` in place."""
    fig.update_layout(template=_plotly_template())
