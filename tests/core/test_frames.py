"""Pure-Python tests for the ``Frame`` enum (build-plan chunk 4).

None of these tests may start the JVM — Frame access is part of the "safe
before init" surface (architecture §10). ``test_no_jvm_started`` guards that.
"""

from __future__ import annotations

from propygator import Frame


def test_no_jvm_started():
    import jpype

    assert not jpype.isJVMStarted()


def test_j2000_is_eme2000_alias():
    assert Frame.J2000 is Frame.EME2000
    assert Frame.J2000.value == "EME2000"


def test_lookup_by_value_returns_canonical():
    assert Frame("EME2000") is Frame.EME2000


def test_alias_excluded_from_iteration():
    members = list(Frame)
    # J2000 is the same object as EME2000, which is present...
    assert Frame.J2000 in members
    # ...but the alias name itself is not yielded separately.
    names = [m.name for m in members]
    assert "J2000" not in names
    assert set(names) == {"EME2000", "ITRF", "TEME"}


def test_supported_value_set():
    assert {f.value for f in Frame} == {"EME2000", "ITRF", "TEME"}


# Frame.to_orekit() is JVM-touching as of Feature 1.1 — its resolution is tested
# under the orekit fixture in tests/test_conversions.py, not here (this suite must
# stay JVM-free; see test_no_jvm_started).
