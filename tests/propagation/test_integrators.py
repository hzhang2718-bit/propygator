"""Pure-Python tests for ``IntegratorConfig`` (build-plan chunk 4).

Construction and numeric validation are on the "safe before init" surface
(architecture §10) — these tests must not start the JVM. The ``type`` string and
the ``ClassicalRK4``-requires-``fixed_step_s`` coupling are resolved later, at the
top of ``propagate_numerical`` (chunk 7), and are not exercised here.
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from propygator.propagation import IntegratorConfig


def test_no_jvm_started():
    import jpype

    assert not jpype.isJVMStarted()


def test_defaults():
    c = IntegratorConfig()
    assert c.type == "DOP853"
    assert c.min_step_s == 1e-3
    assert c.max_step_s == 1000.0
    assert c.abs_tolerance_m == 1e-3
    assert c.rel_tolerance == 1e-10
    assert c.fixed_step_s is None


def test_is_frozen():
    c = IntegratorConfig()
    with pytest.raises(FrozenInstanceError):
        c.type = "ClassicalRK4"  # type: ignore[misc]


# --- presets ---------------------------------------------------------------


def test_default_preset_equals_bare_defaults():
    assert IntegratorConfig.default() == IntegratorConfig()


def test_fast_preset():
    c = IntegratorConfig.fast()
    assert c.type == "DormandPrince54"
    assert c.abs_tolerance_m == 10.0
    assert c.rel_tolerance == 1e-7


def test_high_precision_preset():
    c = IntegratorConfig.high_precision()
    assert c.type == "DOP853"
    assert c.abs_tolerance_m == 1e-5
    assert c.rel_tolerance == 1e-12


# --- validation ------------------------------------------------------------


@pytest.mark.parametrize(
    "field", ["min_step_s", "max_step_s", "abs_tolerance_m", "rel_tolerance"]
)
@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf])
def test_rejects_nonpositive_or_nonfinite(field, bad):
    with pytest.raises(ValueError):
        IntegratorConfig(**{field: bad})


def test_rejects_min_step_above_max_step():
    with pytest.raises(ValueError):
        IntegratorConfig(min_step_s=10.0, max_step_s=1.0)


def test_min_step_equal_to_max_step_allowed():
    c = IntegratorConfig(min_step_s=5.0, max_step_s=5.0)
    assert c.min_step_s == c.max_step_s == 5.0


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf])
def test_rejects_bad_fixed_step(bad):
    with pytest.raises(ValueError):
        IntegratorConfig(fixed_step_s=bad)


def test_accepts_positive_fixed_step():
    # ClassicalRK4 + fixed_step_s construct fine here; the "RK4 *requires* a fixed
    # step" coupling is enforced later, in propagate_numerical (chunk 7).
    c = IntegratorConfig(type="ClassicalRK4", fixed_step_s=10.0)
    assert c.fixed_step_s == 10.0


def test_fixed_step_none_is_default():
    assert IntegratorConfig().fixed_step_s is None
