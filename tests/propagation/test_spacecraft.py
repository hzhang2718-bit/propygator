"""Pure-Python tests for ``SpacecraftConfig`` / ``SpacecraftGeometry`` / ``VariableCd``.

The whole spacecraft surface is on the "safe before init" boundary (architecture
§10): construction, validation, table interpolation, and the ``spacecraft`` metadata
serializer must never start the JVM (build-plan chunk 5). The custom ``DragSensitive``
that *consumes* a table at runtime is built later (chunk 8) and is not exercised here.
"""

from __future__ import annotations

import warnings
from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from propygator.propagation import (
    BoxFaceCd,
    SpacecraftConfig,
    SpacecraftGeometry,
    VariableCd,
)


def test_no_jvm_started():
    import jpype

    assert not jpype.isJVMStarted()


# --- SpacecraftConfig ------------------------------------------------------


def test_config_defaults():
    c = SpacecraftConfig()
    assert c.mass_kg == 1000.0
    assert c.geometry.kind == "sphere"
    assert c.geometry.area_m2 == 1.0
    assert c.geometry.drag_coefficient == 2.2
    assert c.geometry.reflectivity_coefficient == 1.5


def test_config_is_frozen():
    c = SpacecraftConfig()
    with pytest.raises(FrozenInstanceError):
        c.mass_kg = 5.0  # type: ignore[misc]


@pytest.mark.parametrize("mass", [0.0, -1.0, float("nan"), float("inf")])
def test_config_bad_mass(mass):
    with pytest.raises(ValueError):
        SpacecraftConfig(mass_kg=mass)


# --- sphere geometry -------------------------------------------------------


def test_sphere_defaults():
    g = SpacecraftGeometry.sphere(area_m2=2.5)
    assert g.kind == "sphere"
    assert g.area_m2 == 2.5
    assert g.drag_coefficient == 2.2
    assert g.reflectivity_coefficient == 1.5


@pytest.mark.parametrize("area", [0.0, -1.0, float("nan"), float("inf")])
def test_sphere_bad_area(area):
    with pytest.raises(ValueError):
        SpacecraftGeometry.sphere(area_m2=area)


def test_sphere_negative_cd_raises():
    with pytest.raises(ValueError):
        SpacecraftGeometry.sphere(area_m2=1.0, drag_coefficient=-0.1)


def test_sphere_negative_cr_raises():
    with pytest.raises(ValueError):
        SpacecraftGeometry.sphere(area_m2=1.0, reflectivity_coefficient=-0.1)


def test_sphere_high_cd_warns_not_raises():
    with pytest.warns(UserWarning):
        g = SpacecraftGeometry.sphere(area_m2=1.0, drag_coefficient=6.0)
    assert g.drag_coefficient == 6.0


def test_sphere_high_cr_warns_not_raises():
    with pytest.warns(UserWarning):
        g = SpacecraftGeometry.sphere(area_m2=1.0, reflectivity_coefficient=3.5)
    assert g.reflectivity_coefficient == 3.5


def test_sphere_accepts_variable_cd():
    table = _toy_table()
    g = SpacecraftGeometry.sphere(area_m2=1.0, drag_coefficient=table)
    assert g.drag_coefficient is table


def test_sphere_rejects_box_face_cd():
    bf = _box_face_table()
    with pytest.raises(ValueError, match="no flow incidence"):
        SpacecraftGeometry.sphere(area_m2=1.0, drag_coefficient=bf)  # type: ignore[arg-type]


# --- box geometry ----------------------------------------------------------


def test_box_defaults():
    g = SpacecraftGeometry.box_and_panels(
        x_length_m=2.0, y_length_m=1.5, z_length_m=1.0
    )
    assert g.kind == "box"
    assert (g.x_length_m, g.y_length_m, g.z_length_m) == (2.0, 1.5, 1.0)
    assert g.solar_array_area_m2 == 0.0
    assert g.solar_array_axis == (0.0, 1.0, 0.0)
    assert g.drag_coefficient == 2.2
    assert g.absorption_coefficient == 0.3
    assert g.specular_reflection_coefficient == 0.6


@pytest.mark.parametrize("dim", ["x_length_m", "y_length_m", "z_length_m"])
@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan")])
def test_box_bad_dimension(dim, bad):
    kwargs = {"x_length_m": 1.0, "y_length_m": 1.0, "z_length_m": 1.0, dim: bad}
    with pytest.raises(ValueError):
        SpacecraftGeometry.box_and_panels(**kwargs)


def test_box_negative_array_area_raises():
    with pytest.raises(ValueError):
        SpacecraftGeometry.box_and_panels(
            x_length_m=1.0, y_length_m=1.0, z_length_m=1.0, solar_array_area_m2=-1.0
        )


def test_box_zero_axis_raises():
    with pytest.raises(ValueError):
        SpacecraftGeometry.box_and_panels(
            x_length_m=1.0,
            y_length_m=1.0,
            z_length_m=1.0,
            solar_array_axis=(0.0, 0.0, 0.0),
        )


def test_box_nonfinite_axis_raises():
    with pytest.raises(ValueError):
        SpacecraftGeometry.box_and_panels(
            x_length_m=1.0,
            y_length_m=1.0,
            z_length_m=1.0,
            solar_array_axis=(float("nan"), 1.0, 0.0),
        )


def test_box_axis_normalized_silently():
    g = SpacecraftGeometry.box_and_panels(
        x_length_m=1.0, y_length_m=1.0, z_length_m=1.0, solar_array_axis=(0.0, 2.0, 0.0)
    )
    assert g.solar_array_axis == (0.0, 1.0, 0.0)
    g2 = SpacecraftGeometry.box_and_panels(
        x_length_m=1.0, y_length_m=1.0, z_length_m=1.0, solar_array_axis=(1.0, 1.0, 0.0)
    )
    assert g2.solar_array_axis is not None
    np.testing.assert_allclose(g2.solar_array_axis, (2.0**-0.5, 2.0**-0.5, 0.0))


@pytest.mark.parametrize(
    "absn,spec",
    [(-0.1, 0.5), (1.1, 0.0), (0.5, -0.1), (0.5, 1.1)],
)
def test_box_optics_out_of_range_raises(absn, spec):
    with pytest.raises(ValueError):
        SpacecraftGeometry.box_and_panels(
            x_length_m=1.0,
            y_length_m=1.0,
            z_length_m=1.0,
            absorption_coefficient=absn,
            specular_reflection_coefficient=spec,
        )


def test_box_optics_sum_over_one_raises():
    with pytest.raises(ValueError, match="diffuse"):
        SpacecraftGeometry.box_and_panels(
            x_length_m=1.0,
            y_length_m=1.0,
            z_length_m=1.0,
            absorption_coefficient=0.7,
            specular_reflection_coefficient=0.6,
        )


def test_box_high_cd_warns_not_raises():
    with pytest.warns(UserWarning):
        g = SpacecraftGeometry.box_and_panels(
            x_length_m=1.0, y_length_m=1.0, z_length_m=1.0, drag_coefficient=7.0
        )
    assert g.drag_coefficient == 7.0


def test_box_accepts_variable_and_box_face_tables():
    table = _toy_table()
    bf = _box_face_table()
    g1 = SpacecraftGeometry.box_and_panels(
        x_length_m=1.0, y_length_m=1.0, z_length_m=1.0, drag_coefficient=table
    )
    # A convex bus (solar_array_area_m2 == 0, the default) accepts a BoxFaceCd.
    g2 = SpacecraftGeometry.box_and_panels(
        x_length_m=1.0, y_length_m=1.0, z_length_m=1.0, drag_coefficient=bf
    )
    assert g1.drag_coefficient is table
    assert g2.drag_coefficient is bf


def test_box_with_arrays_rejects_box_face_cd():
    # BoxFaceCd is convex-box-only: a paneled box (solar_array_area_m2 > 0) is rejected
    # at construction, never at propagation (general upgrades 1, "Tier B Drag").
    bf = _box_face_table()
    with pytest.raises(ValueError, match="convex box only"):
        SpacecraftGeometry.box_and_panels(
            x_length_m=1.0,
            y_length_m=1.0,
            z_length_m=1.0,
            solar_array_area_m2=5.0,
            drag_coefficient=bf,
        )


# --- VariableCd table ------------------------------------------------------


def _toy_table() -> VariableCd:
    radius_axis = np.array([1.0, 2.0, 3.0])
    density_axis = np.array([10.0, 20.0])
    grid = np.array([[2.0, 2.2], [2.4, 2.6], [2.8, 3.0]])
    return VariableCd.from_table(
        grid, radius_axis=radius_axis, density_axis=density_axis
    )


def _box_face_table() -> BoxFaceCd:
    """A small per-face table with a head-on→leeward Cd falloff over θ ∈ [0, π]."""
    radius_axis = np.array([6.6e6, 7.0e6])
    density_axis = np.array([1e-13, 1e-11])
    incidence_axis = np.array([0.0, np.pi / 2, np.pi])
    # grid[radius, density, incidence]: high head-on, ~0.07 edge-on, ~0 leeward.
    grid = np.array(
        [
            [[3.0, 0.07, 0.0], [3.2, 0.07, 0.0]],
            [[2.8, 0.06, 0.0], [3.0, 0.06, 0.0]],
        ]
    )
    return BoxFaceCd.from_table(
        grid,
        radius_axis=radius_axis,
        density_axis=density_axis,
        incidence_axis=incidence_axis,
    )


def test_variable_cd_exact_at_grid_nodes():
    radius_axis = np.array([1.0, 2.0, 3.0])
    density_axis = np.array([10.0, 20.0])
    grid = np.array([[2.0, 2.2], [2.4, 2.6], [2.8, 3.0]])
    t = VariableCd.from_table(grid, radius_axis=radius_axis, density_axis=density_axis)
    for i, r in enumerate(radius_axis):
        for j, d in enumerate(density_axis):
            assert t(r, d) == pytest.approx(grid[i, j])


def test_variable_cd_bilinear_midpoint():
    radius_axis = np.array([0.0, 2.0])
    density_axis = np.array([0.0, 10.0])
    grid = np.array([[0.0, 2.0], [4.0, 10.0]])
    t = VariableCd.from_table(grid, radius_axis=radius_axis, density_axis=density_axis)
    # Centre of the cell: mean of the four corners.
    assert t(1.0, 5.0) == pytest.approx((0.0 + 2.0 + 4.0 + 10.0) / 4.0)


def test_variable_cd_clamps_and_warns_per_edge():
    # Edge-aware clamp warnings (addendum §6.2): each boundary warns once, with a
    # tailored message — the low radius edge is loud (model invalid), the high edge is
    # soft (drag negligible), the density edge is neutral.
    t = _toy_table()  # radius_axis [1,2,3], density_axis [10,20]
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        below = t(-100.0, 5.0)  # radius below min (low edge) + density below min
        above = t(1000.0, 1000.0)  # radius above max (high edge) + density above max
        t(-100.0, 5.0)  # repeat: must not re-warn any already-warned boundary
    # Clamped to the corners of the grid (unchanged clamp behavior).
    assert below == pytest.approx(2.0)
    assert above == pytest.approx(3.0)
    msgs = [str(r.message) for r in records if issubclass(r.category, UserWarning)]
    # Three distinct boundaries, each warned exactly once and edge-tailored.
    assert sum("below the drag-table grid" in m for m in msgs) == 1  # low edge, loud
    assert sum("above the drag-table grid" in m for m in msgs) == 1  # high edge, soft
    assert (
        sum("total density outside the table grid" in m for m in msgs) == 1
    )  # density
    assert len(msgs) == 3


def test_variable_cd_in_range_does_not_warn():
    t = _toy_table()
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning becomes an error
        assert t(2.0, 15.0) == pytest.approx(2.5)


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "grid": np.zeros((2, 2)),
            "radius_axis": np.array([1.0, 2.0, 3.0]),
            "density_axis": np.array([1.0, 2.0]),
        },  # shape mismatch
        {
            "grid": np.zeros((2, 2)),
            "radius_axis": np.array([2.0, 1.0]),
            "density_axis": np.array([1.0, 2.0]),
        },  # not increasing
        {
            "grid": np.array([[1.0, np.nan], [1.0, 1.0]]),
            "radius_axis": np.array([1.0, 2.0]),
            "density_axis": np.array([1.0, 2.0]),
        },  # non-finite grid
        {
            "grid": np.zeros((1, 2)),
            "radius_axis": np.array([1.0]),
            "density_axis": np.array([1.0, 2.0]),
        },  # axis too short
        {
            "grid": np.array([[1.0, 1.0], [1.0, -1e-6]]),
            "radius_axis": np.array([1.0, 2.0]),
            "density_axis": np.array([1.0, 2.0]),
        },  # negative entry (Cd >= 0, validated since v0.7.3)
    ],
)
def test_variable_cd_from_table_validation(kwargs):
    with pytest.raises(ValueError):
        VariableCd.from_table(**kwargs)


def test_variable_cd_from_callable():
    t = VariableCd.from_callable(lambda radius_m, density_kgm3: 2.5)
    assert t(7_000_000.0, 1e-12) == 2.5
    assert t._metadata_id() == "<lambda>"


def test_variable_cd_from_callable_rejects_noncallable():
    with pytest.raises(ValueError):
        VariableCd.from_callable(42)  # type: ignore[arg-type]


def test_variable_cd_rejects_non_finite_input():
    """NaN/inf slip past the clamp comparisons, so they must be rejected up front."""
    t = _toy_table()
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finite"):
            t(bad, 15.0)
        with pytest.raises(ValueError, match="finite"):
            t(2.0, bad)


def test_variable_cd_from_callable_validates_result():
    """A callable returning a non-finite or negative Cd fails with a clear error."""
    nan_cd = VariableCd.from_callable(lambda radius_m, density_kgm3: float("nan"))
    with pytest.raises(ValueError, match="invalid Cd"):
        nan_cd(7_000_000.0, 1e-12)
    negative_cd = VariableCd.from_callable(lambda radius_m, density_kgm3: -1.0)
    with pytest.raises(ValueError, match="invalid Cd"):
        negative_cd(7_000_000.0, 1e-12)


def test_sphere_default_loads_committed_asset():
    t = VariableCd.sphere_default()
    assert t._metadata_id() == "sphere_default"
    assert t._grid is not None and t._grid.ndim == 2
    # The shipped table spans the validated geocentric-radius band (drag-validity
    # addendum: ~150 km lower edge retained, upper edge extended to ~1,400 km).
    assert t._radius_axis is not None
    assert t._radius_axis[0] == pytest.approx(6_528_000.0)
    assert t._radius_axis[-1] == pytest.approx(7_778_000.0)
    # A physically realized LEO point returns a free-molecular Cd.
    assert 2.0 < t(6_828_000.0, 1e-12) < 3.5


# --- BoxFaceCd (per-face incidence table) ----------------------------------


def test_box_face_constructs_and_validates():
    bf = _box_face_table()
    assert isinstance(bf._metadata_id(), str)


def test_box_face_exact_at_grid_nodes():
    bf = _box_face_table()
    # Lands exactly on grid nodes -> returns the stored value.
    assert bf(6.6e6, 1e-13, 0.0) == pytest.approx(3.0)
    assert bf(6.6e6, 1e-13, np.pi / 2) == pytest.approx(0.07)
    assert bf(7.0e6, 1e-11, np.pi) == pytest.approx(0.0)


def test_box_face_trilinear_interior():
    # Cell centre across all three axes: mean of the eight corners.
    radius_axis = np.array([0.0, 2.0])
    density_axis = np.array([0.0, 4.0])
    incidence_axis = np.array([0.0, np.pi])
    grid = np.arange(8.0).reshape(2, 2, 2)  # corners 0..7
    bf = BoxFaceCd.from_table(
        grid,
        radius_axis=radius_axis,
        density_axis=density_axis,
        incidence_axis=incidence_axis,
    )
    assert bf(1.0, 2.0, np.pi / 2) == pytest.approx(grid.mean())


def test_box_face_from_callable():
    bf = BoxFaceCd.from_callable(
        lambda radius_m, density_kgm3, theta_rad: 2.0 + theta_rad
    )
    assert bf(7e6, 1e-12, 0.5) == pytest.approx(2.5)
    assert bf._metadata_id() == "<lambda>"


def test_box_face_from_callable_named():
    bf = BoxFaceCd.from_callable(
        lambda radius_m, density_kgm3, theta_rad: 2.2, name="my_law"
    )
    assert bf._metadata_id() == "my_law"


def test_box_face_from_callable_rejects_noncallable():
    with pytest.raises(ValueError):
        BoxFaceCd.from_callable(42)  # type: ignore[arg-type]


def test_box_face_from_callable_validates_result():
    nan_cd = BoxFaceCd.from_callable(
        lambda radius_m, density_kgm3, theta_rad: float("nan")
    )
    with pytest.raises(ValueError, match="invalid Cd"):
        nan_cd(7e6, 1e-12, 0.5)
    negative_cd = BoxFaceCd.from_callable(
        lambda radius_m, density_kgm3, theta_rad: -1.0
    )
    with pytest.raises(ValueError, match="invalid Cd"):
        negative_cd(7e6, 1e-12, 0.5)


def test_box_face_rejects_non_finite_input():
    bf = _box_face_table()
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finite"):
            bf(bad, 1e-12, 0.5)
        with pytest.raises(ValueError, match="finite"):
            bf(7e6, bad, 0.5)
        with pytest.raises(ValueError, match="finite"):
            bf(7e6, 1e-12, bad)


def test_box_face_clamps_radius_density_and_warns_per_edge():
    # (radius, density) clamp to the nearest edge with an edge-tailored warn-once,
    # reusing the shared VariableCd messages; theta never clamps.
    bf = _box_face_table()  # radius [6.6e6, 7.0e6], density [1e-13, 1e-11]
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        below = bf(1.0, 1e-20, 0.0)  # radius + density both below min
        above = bf(9e6, 1e-3, np.pi)  # radius + density both above max
        bf(1.0, 1e-20, 0.0)  # repeat: must not re-warn an already-warned boundary
    # Clamped to the corner grid values (head-on low corner; leeward high corner).
    assert below == pytest.approx(3.0)
    assert above == pytest.approx(0.0)
    msgs = [str(r.message) for r in records if issubclass(r.category, UserWarning)]
    assert sum("below the drag-table grid" in m for m in msgs) == 1  # low edge, loud
    assert sum("above the drag-table grid" in m for m in msgs) == 1  # high edge, soft
    assert sum("total density outside the table grid" in m for m in msgs) == 1
    assert len(msgs) == 3


def test_box_face_in_range_does_not_warn():
    bf = _box_face_table()
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning becomes an error
        # An interior point across all three axes never warns (theta never clamps).
        assert bf(6.8e6, 1e-12, np.pi / 4) > 0.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "grid": np.zeros((2, 2)),  # 2-D grid for 3 axes -> shape mismatch
            "radius_axis": np.array([1.0, 2.0]),
            "density_axis": np.array([1.0, 2.0]),
            "incidence_axis": np.array([0.0, np.pi]),
        },
        {
            "grid": np.zeros((2, 2, 2)),
            "radius_axis": np.array([2.0, 1.0]),  # not increasing
            "density_axis": np.array([1.0, 2.0]),
            "incidence_axis": np.array([0.0, np.pi]),
        },
        {
            "grid": np.full((2, 2, 2), np.nan),  # non-finite grid
            "radius_axis": np.array([1.0, 2.0]),
            "density_axis": np.array([1.0, 2.0]),
            "incidence_axis": np.array([0.0, np.pi]),
        },
        {
            "grid": np.zeros((2, 2, 2)),
            "radius_axis": np.array([1.0, 2.0]),
            "density_axis": np.array([1.0, 2.0]),
            "incidence_axis": np.array([-0.1, np.pi]),  # below 0
        },
        {
            "grid": np.zeros((2, 2, 2)),
            "radius_axis": np.array([1.0, 2.0]),
            "density_axis": np.array([1.0, 2.0]),
            "incidence_axis": np.array([0.0, np.pi + 0.1]),  # above pi
        },
        {
            # negative entry (Cd >= 0, validated since v0.7.3)
            "grid": np.array([[[1.0, 1.0], [1.0, 1.0]], [[1.0, 1.0], [1.0, -1e-6]]]),
            "radius_axis": np.array([1.0, 2.0]),
            "density_axis": np.array([1.0, 2.0]),
            "incidence_axis": np.array([0.0, np.pi]),
        },
    ],
)
def test_box_face_from_table_validation(kwargs):
    with pytest.raises(ValueError):
        BoxFaceCd.from_table(**kwargs)


def test_box_face_default_loads_committed_asset():
    bf = BoxFaceCd.default()
    assert bf._metadata_id() == "box_face_default"
    assert bf._grid is not None and bf._grid.ndim == 3
    # Same validated geocentric-radius band as the sphere table, plus a full [0, pi]
    # face-flow-angle axis.
    assert bf._radius_axis is not None and bf._incidence_axis is not None
    assert bf._radius_axis[0] == pytest.approx(6_528_000.0)
    assert bf._radius_axis[-1] == pytest.approx(7_778_000.0)
    assert bf._incidence_axis[0] == pytest.approx(0.0)
    assert bf._incidence_axis[-1] == pytest.approx(np.pi)
    # Head-on (theta=0) is a real free-molecular per-face Cd; edge-on floors near ~0.07.
    head_on = bf(6_828_000.0, 1e-12, 0.0)
    edge_on = bf(6_828_000.0, 1e-12, np.pi / 2)
    assert 2.0 < head_on < 5.0
    assert 0.0 < edge_on < 0.5
    assert head_on > edge_on
    # Chunk 5 (v0.7.3): the grid is floored at 0.0 at generation, so the leeward
    # half — noise-level negative through v0.7.2 — serves values >= 0.
    assert bf._grid.min() >= 0.0
    assert bf(6_828_000.0, 1e-12, np.pi) >= 0.0


def test_shipped_grids_are_nonnegative():
    """Both committed tables satisfy the from_table >= 0 rule they now load through.

    The box grid is floored at generation (its leeward half was noise-negative
    through v0.7.2 — Chunk 5); the sphere grid never approaches zero (min ~2.1),
    so its half of the rule is trivially true, no regeneration needed.
    """
    box = BoxFaceCd.default()
    sphere = VariableCd.sphere_default()
    assert box._grid is not None and box._grid.min() >= 0.0
    assert sphere._grid is not None and sphere._grid.min() >= 0.0


def test_box_face_default_callable_wrap_serves_leeward():
    """An identity from_callable wrap of the shipped table returns >= 0 at θ = π.

    The Chunk 5 asymmetry: through v0.7.2 the table path tolerated the shipped
    grid's negative leeward noise, but from_callable's runtime check rejects
    Cd < 0 — so wrapping the shipped table (e.g. scaling it) raised ValueError
    mid-propagation. With the floored grid the wrap must serve the whole θ axis.
    """
    table = BoxFaceCd.default()
    wrapped = BoxFaceCd.from_callable(table, name="identity_wrap")
    for radius_m in (6_600_000.0, 6_828_000.0, 7_500_000.0):
        assert wrapped(radius_m, 1e-12, np.pi) >= 0.0


# --- metadata serializer ---------------------------------------------------


def test_metadata_sphere_fixed():
    c = SpacecraftConfig()
    assert c._metadata_string() == "sphere:A=1.0;m=1000.0,Cd=2.2,Cr=1.5"


def test_metadata_sphere_table():
    c = SpacecraftConfig(
        geometry=SpacecraftGeometry.sphere(
            area_m2=1.0, drag_coefficient=VariableCd.sphere_default()
        )
    )
    assert (
        c._metadata_string() == "sphere:A=1.0;m=1000.0,Cd=table:sphere_default,Cr=1.5"
    )


def test_metadata_box_fixed():
    c = SpacecraftConfig(
        mass_kg=420.0,
        geometry=SpacecraftGeometry.box_and_panels(
            x_length_m=2.0, y_length_m=1.5, z_length_m=1.0, solar_array_area_m2=10.0
        ),
    )
    assert c._metadata_string() == (
        "box:x=2.0,y=1.5,z=1.0,arrays=10.0,axis=(0,1,0);m=420.0,Cd=2.2,abs=0.3,spec=0.6"
    )


def test_metadata_is_deterministic():
    c = SpacecraftConfig()
    assert c._metadata_string() == c._metadata_string()


def test_metadata_coerces_int_inputs_to_float():
    # Int-valued numerics must serialize with a decimal point, so a config built from
    # ints and the physically-identical float config share byte-identical metadata
    # (features.md §1.1 deterministic grammar).
    c_int = SpacecraftConfig(
        mass_kg=1000,
        geometry=SpacecraftGeometry.sphere(
            area_m2=1, drag_coefficient=2, reflectivity_coefficient=1
        ),
    )
    assert c_int._metadata_string() == "sphere:A=1.0;m=1000.0,Cd=2.0,Cr=1.0"
    c_float = SpacecraftConfig(
        mass_kg=1000.0,
        geometry=SpacecraftGeometry.sphere(
            area_m2=1.0, drag_coefficient=2.0, reflectivity_coefficient=1.0
        ),
    )
    assert c_int._metadata_string() == c_float._metadata_string()


def test_metadata_table_hash_for_user_table():
    table = _toy_table()
    c = SpacecraftConfig(
        geometry=SpacecraftGeometry.sphere(area_m2=1.0, drag_coefficient=table)
    )
    s = c._metadata_string()
    assert s.startswith("sphere:A=1.0;m=1000.0,Cd=table:")
    # A user table records a content hash, not a name.
    assert "table:sphere_default" not in s
    assert f"table:{table._metadata_id()}" in s


def test_metadata_box_face_default_token():
    c = SpacecraftConfig(
        mass_kg=420.0,
        geometry=SpacecraftGeometry.box_and_panels(
            x_length_m=2.0,
            y_length_m=1.5,
            z_length_m=1.0,
            solar_array_area_m2=0.0,
            drag_coefficient=BoxFaceCd.default(),
        ),
    )
    assert c._metadata_string() == (
        "box:x=2.0,y=1.5,z=1.0,arrays=0.0,axis=(0,1,0);"
        "m=420.0,Cd=table:box_face_default,abs=0.3,spec=0.6"
    )


def test_metadata_box_face_hash_for_user_table():
    bf = _box_face_table()
    c = SpacecraftConfig(
        geometry=SpacecraftGeometry.box_and_panels(
            x_length_m=1.0, y_length_m=1.0, z_length_m=1.0, drag_coefficient=bf
        )
    )
    s = c._metadata_string()
    assert "Cd=table:box_face_default" not in s  # a user table records a content hash
    assert f"Cd=table:{bf._metadata_id()}" in s


def test_content_hash_distinguishes_2d_from_box_face():
    # Same numeric axes, different table kind -> different hash (kind tag + axis set
    # folded in), so a 2-D VariableCd can never collide with a per-face BoxFaceCd.
    axis = np.array([0.0, 1.0])
    incidence = np.array([0.0, np.pi])
    table = VariableCd.from_table(np.zeros((2, 2)), radius_axis=axis, density_axis=axis)
    bf = BoxFaceCd.from_table(
        np.zeros((2, 2, 2)),
        radius_axis=axis,
        density_axis=axis,
        incidence_axis=incidence,
    )
    assert table._metadata_id() != bf._metadata_id()
