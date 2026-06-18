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
    IncidenceVariableCd,
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


def test_sphere_rejects_incidence_table():
    inc = _toy_incidence_table()
    with pytest.raises(ValueError, match="incidence"):
        SpacecraftGeometry.sphere(area_m2=1.0, drag_coefficient=inc)  # type: ignore[arg-type]


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


def test_box_accepts_variable_and_incidence_tables():
    table = _toy_table()
    inc = _toy_incidence_table()
    g1 = SpacecraftGeometry.box_and_panels(
        x_length_m=1.0, y_length_m=1.0, z_length_m=1.0, drag_coefficient=table
    )
    g2 = SpacecraftGeometry.box_and_panels(
        x_length_m=1.0, y_length_m=1.0, z_length_m=1.0, drag_coefficient=inc
    )
    assert g1.drag_coefficient is table
    assert g2.drag_coefficient is inc


# --- VariableCd table ------------------------------------------------------


def _toy_table() -> VariableCd:
    radius_axis = np.array([1.0, 2.0, 3.0])
    density_axis = np.array([10.0, 20.0])
    grid = np.array([[2.0, 2.2], [2.4, 2.6], [2.8, 3.0]])
    return VariableCd.from_table(
        grid, radius_axis=radius_axis, density_axis=density_axis
    )


def _toy_incidence_table() -> IncidenceVariableCd:
    grid = np.zeros((2, 2, 2, 2))
    axis = np.array([0.0, 1.0])
    return IncidenceVariableCd.from_table(
        grid,
        radius_axis=axis,
        density_axis=axis,
        azimuth_axis=axis,
        elevation_axis=axis,
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


def test_variable_cd_clamps_and_warns_once():
    t = _toy_table()
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        below = t(-100.0, 5.0)  # both axes below their minimum
        above = t(1000.0, 1000.0)  # both axes above their maximum
    # Clamped to the corners of the grid.
    assert below == pytest.approx(2.0)
    assert above == pytest.approx(3.0)
    # Out-of-grid warns exactly once across multiple calls.
    assert sum(issubclass(r.category, UserWarning) for r in records) == 1


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
    # The shipped table spans the approved geocentric-radius extents.
    assert t._radius_axis is not None
    assert t._radius_axis[0] == pytest.approx(6_528_000.0)
    assert t._radius_axis[-1] == pytest.approx(7_578_000.0)
    # A physically realized LEO point returns a free-molecular Cd.
    assert 2.0 < t(6_828_000.0, 1e-12) < 3.5


# --- IncidenceVariableCd skeleton ------------------------------------------


def test_incidence_constructs_and_validates():
    inc = _toy_incidence_table()
    assert isinstance(inc._metadata_id(), str)


def test_incidence_with_array_axis():
    grid = np.zeros((2, 2, 2, 2, 2))
    axis = np.array([0.0, 1.0])
    inc = IncidenceVariableCd.from_table(
        grid,
        radius_axis=axis,
        density_axis=axis,
        azimuth_axis=axis,
        elevation_axis=axis,
        array_axis=axis,
    )
    assert inc._array_axis is not None


def test_incidence_shape_mismatch_raises():
    grid = np.zeros((2, 2, 2))  # too few dims for 4 axes
    axis = np.array([0.0, 1.0])
    with pytest.raises(ValueError):
        IncidenceVariableCd.from_table(
            grid,
            radius_axis=axis,
            density_axis=axis,
            azimuth_axis=axis,
            elevation_axis=axis,
        )


def test_incidence_runtime_raises_not_implemented():
    inc = _toy_incidence_table()
    with pytest.raises(NotImplementedError, match="Tier B"):
        inc(0.5, 0.5, 0.5, 0.5)


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


def test_content_hash_distinguishes_2d_from_incidence():
    # Same numeric axes, different table kind -> different hash (axis set folded in).
    axis = np.array([0.0, 1.0])
    table = VariableCd.from_table(np.zeros((2, 2)), radius_axis=axis, density_axis=axis)
    inc = IncidenceVariableCd.from_table(
        np.zeros((2, 2, 2, 2)),
        radius_axis=axis,
        density_axis=axis,
        azimuth_axis=axis,
        elevation_axis=axis,
    )
    assert table._metadata_id() != inc._metadata_id()
