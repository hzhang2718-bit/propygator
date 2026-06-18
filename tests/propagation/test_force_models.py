"""Pure-Python tests for ``ForceModelConfig`` (build-plan chunk 4).

Construction, presets, validation, and the ``force_models`` metadata serializer
are all on the "safe before init" surface (architecture §10) — these tests must
not start the JVM. The named ``gravity_field`` / ``atmosphere_model`` strings are
resolved later (chunks 7–8) and are not exercised here.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from propygator.propagation import ForceModelConfig
from propygator.propagation.force_models import _serialize_force_models


def test_no_jvm_started():
    import jpype

    assert not jpype.isJVMStarted()


def test_defaults():
    c = ForceModelConfig()
    assert c.gravity_degree == 70
    assert c.gravity_order == 70
    assert c.gravity_field == "EIGEN-6S"
    assert c.sun_third_body is True
    assert c.moon_third_body is True
    assert c.drag is True
    assert c.atmosphere_model == "NRLMSISE-00"
    assert c.srp is True
    assert c.solid_tides is False
    assert c.ocean_tides is False
    assert c.relativity is False


def test_is_frozen():
    c = ForceModelConfig()
    with pytest.raises(FrozenInstanceError):
        c.drag = False  # type: ignore[misc]


# --- presets ---------------------------------------------------------------


def test_leo_default_equals_bare_defaults():
    assert ForceModelConfig.leo_default() == ForceModelConfig()


def test_geo_default():
    c = ForceModelConfig.geo_default()
    assert (c.gravity_degree, c.gravity_order) == (12, 12)
    assert c.drag is False
    assert c.srp is True
    assert c.sun_third_body is True and c.moon_third_body is True
    assert c.solid_tides is False and c.ocean_tides is False and c.relativity is False


def test_keplerian():
    c = ForceModelConfig.keplerian()
    assert (c.gravity_degree, c.gravity_order) == (0, 0)
    assert c.sun_third_body is False and c.moon_third_body is False
    assert c.drag is False and c.srp is False
    assert c.solid_tides is False and c.ocean_tides is False and c.relativity is False


# --- validation ------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"gravity_degree": -1},
        {"gravity_order": -1},
        {"gravity_degree": 4, "gravity_order": 5},  # order > degree
    ],
)
def test_rejects_bad_gravity(kwargs):
    with pytest.raises(ValueError):
        ForceModelConfig(**kwargs)


def test_zonal_only_allowed():
    # order < degree (zonal-only) is a valid spherical-harmonics field.
    c = ForceModelConfig(gravity_degree=70, gravity_order=0)
    assert c.gravity_order == 0


# --- metadata serializer ---------------------------------------------------


def test_metadata_full_leo_with_solid_tides():
    c = ForceModelConfig(solid_tides=True)
    assert c._metadata_tokens() == [
        "gravity:EIGEN-6S:70x70",
        "third_body:sun",
        "third_body:moon",
        "drag:NRLMSISE-00",
        "srp",
        "tides:solid",
    ]


def test_metadata_geo_default():
    assert ForceModelConfig.geo_default()._metadata_tokens() == [
        "gravity:EIGEN-6S:12x12",
        "third_body:sun",
        "third_body:moon",
        "srp",
    ]


def test_metadata_keplerian_is_point_mass():
    assert ForceModelConfig.keplerian()._metadata_tokens() == ["gravity:EIGEN-6S:0x0"]


def test_metadata_token_order_is_fixed():
    # Everything on: the full fixed order, both tides emitted independently.
    c = ForceModelConfig(solid_tides=True, ocean_tides=True, relativity=True)
    assert c._metadata_tokens() == [
        "gravity:EIGEN-6S:70x70",
        "third_body:sun",
        "third_body:moon",
        "drag:NRLMSISE-00",
        "srp",
        "tides:solid",
        "tides:ocean",
        "relativity",
    ]


def test_metadata_is_deterministic():
    c = ForceModelConfig.leo_default()
    assert c._metadata_tokens() == c._metadata_tokens()


def test_metadata_reflects_atmosphere_model():
    c = ForceModelConfig(atmosphere_model="DTM-2000")
    assert "drag:DTM-2000" in c._metadata_tokens()


def test_serializer_is_driven_by_facts_not_config():
    # The standalone serializer is driven by explicit facts so propagate_numerical
    # can record only the forces it actually wired (e.g. gravity-only in chunk 7),
    # independent of any config's booleans.
    tokens = _serialize_force_models(
        gravity_field="EIGEN-6S",
        gravity_degree=70,
        gravity_order=70,
        sun_third_body=False,
        moon_third_body=False,
        drag=False,
        atmosphere_model="NRLMSISE-00",
        srp=False,
        solid_tides=False,
        ocean_tides=False,
        relativity=False,
    )
    assert tokens == ["gravity:EIGEN-6S:70x70"]
