"""Pure-Python tests for ``Trajectory`` + ``TrajectoryMetadata`` (build-plan chunk 5).

Construction, validation, the sequence protocol, and ``to_dataframe`` are part of
the "safe before init" surface (architecture §10) — these tests must not start
the JVM.
"""

from __future__ import annotations

import numpy as np
import pytest

from propygator import Epoch, Frame, State, TimeScale, Trajectory
from propygator.core.states import _default_metadata


def _epoch(i: int = 0, scale: TimeScale = TimeScale.UTC) -> Epoch:
    base = Epoch.from_iso("2024-01-01T00:00:00", scale=scale)
    return base.shifted_by(60.0 * i)


def _positions(n: int) -> np.ndarray:
    return (np.arange(n * 3, dtype=np.float64).reshape(n, 3)) + 7.0e6


def _velocities(n: int) -> np.ndarray:
    return (np.arange(n * 3, dtype=np.float64).reshape(n, 3)) + 1.0e3


def _meta() -> dict:
    return {
        "propygator_version": "0.1.0",
        "orekit_version": "unknown",
        "propagator": "test",
    }


def _state(i: int = 0, frame: Frame = Frame.EME2000, scale: TimeScale = TimeScale.UTC):
    return State(
        _epoch(i, scale),
        np.array([7.0e6 + i, 0.0, 0.0], dtype=np.float64),
        np.array([0.0, 7.5e3, 0.0], dtype=np.float64),
        frame,
    )


def _traj(n: int = 4) -> Trajectory:
    epochs = [_epoch(i) for i in range(n)]
    return Trajectory.from_arrays(
        epochs, _positions(n), _velocities(n), Frame.EME2000, metadata=_meta()
    )


def test_no_jvm_started():
    import jpype

    assert not jpype.isJVMStarted()


# --- construction / round-trip ---------------------------------------------


def test_from_arrays_list_roundtrip():
    n = 4
    traj = _traj(n)
    assert len(traj) == n
    assert traj.frame is Frame.EME2000
    assert traj.epoch_scale is TimeScale.UTC
    s2 = traj[2]
    assert isinstance(s2, State)
    np.testing.assert_array_equal(s2.position, _positions(n)[2])
    np.testing.assert_array_equal(s2.velocity, _velocities(n)[2])
    assert s2.epoch.to_iso() == _epoch(2).to_iso()


def test_from_arrays_datetime64_path():
    times = np.array(
        ["2024-01-01T00:00:00", "2024-01-01T00:01:00"], dtype="datetime64[ns]"
    )
    traj = Trajectory.from_arrays(
        times,
        _positions(2),
        _velocities(2),
        Frame.EME2000,
        epoch_scale=TimeScale.UTC,
        metadata=_meta(),
    )
    assert len(traj) == 2
    assert traj[0].epoch.to_iso() == "2024-01-01T00:00:00"
    assert traj[1].epoch.to_iso() == "2024-01-01T00:01:00"


def test_from_arrays_datetime64_subsecond_precision():
    times = np.array(["2024-01-01T00:00:00.250000000"], dtype="datetime64[ns]")
    traj = Trajectory.from_arrays(
        times, _positions(1), _velocities(1), Frame.EME2000, metadata=_meta()
    )
    assert traj[0].epoch.to_iso() == "2024-01-01T00:00:00.25"


def test_from_states_roundtrip():
    states = [_state(i) for i in range(3)]
    traj = Trajectory.from_states(states)
    assert len(traj) == 3
    back = traj[1]
    np.testing.assert_array_equal(back.position, states[1].position)
    assert back.epoch.to_iso() == states[1].epoch.to_iso()
    assert back.frame is Frame.EME2000


def test_from_states_default_metadata():
    traj = Trajectory.from_states([_state(0)])
    assert traj.metadata["propagator"] == "user"
    assert traj.metadata["orekit_version"] == "unknown"
    assert traj.metadata["propygator_version"]  # non-empty


def test_default_metadata_helper():
    md = _default_metadata()
    assert md["propagator"] == "user"
    assert set(md) == {"propygator_version", "orekit_version", "propagator"}


# --- read-only enforcement -------------------------------------------------


def test_positions_read_only():
    traj = _traj()
    with pytest.raises(ValueError):
        traj.positions[0, 0] = 0.0


def test_velocities_read_only():
    traj = _traj()
    with pytest.raises(ValueError):
        traj.velocities[0, 0] = 0.0


def test_epoch_arrays_read_only():
    traj = _traj()
    with pytest.raises(ValueError):
        traj._epochs_int[0] = 0
    with pytest.raises(ValueError):
        traj._epochs_frac[0] = 0.0


def test_from_arrays_does_not_freeze_caller_arrays():
    n = 3
    pos = _positions(n)
    vel = _velocities(n)
    Trajectory.from_arrays(
        [_epoch(i) for i in range(n)], pos, vel, Frame.EME2000, metadata=_meta()
    )
    # The caller's arrays must remain writable (from_arrays copies defensively).
    pos[0, 0] = 1.0
    vel[0, 0] = 1.0


def test_getitem_returns_immutable_state():
    s = _traj()[0]
    # Materialized States are immutable value objects (architecture §6): their
    # backing arrays are read-only copies.
    with pytest.raises(ValueError):
        s.position[0] = 123.0
    with pytest.raises(ValueError):
        s.velocity[0] = 123.0


# --- metadata validation ---------------------------------------------------


def test_missing_metadata_key_rejected():
    n = 2
    with pytest.raises(ValueError, match="missing required keys"):
        Trajectory.from_arrays(
            [_epoch(i) for i in range(n)],
            _positions(n),
            _velocities(n),
            Frame.EME2000,
            metadata={"propagator": "x"},
        )


def test_from_arrays_copies_metadata():
    n = 2
    meta = _meta()
    traj = Trajectory.from_arrays(
        [_epoch(i) for i in range(n)],
        _positions(n),
        _velocities(n),
        Frame.EME2000,
        metadata=meta,
    )
    meta["propagator"] = "mutated"  # caller mutates their own dict afterward
    assert traj.metadata["propagator"] == "test"  # trajectory record unaffected


def test_termination_metadata_keys_are_optional_and_round_trip():
    # The addendum §6.6 termination keys are additive/optional: they are not in
    # the required set (so a normal run with none of them constructs fine), and a
    # terminated run carries them through unchanged.
    from propygator.core.states import _REQUIRED_METADATA_KEYS

    for key in ("terminated", "termination_reason", "termination_epoch"):
        assert key not in _REQUIRED_METADATA_KEYS

    n = 2
    meta = _meta()
    meta["terminated"] = True
    meta["termination_reason"] = "user_min"
    meta["termination_epoch"] = "2026-06-14T09:12:44Z"
    traj = Trajectory.from_arrays(
        [_epoch(i) for i in range(n)],
        _positions(n),
        _velocities(n),
        Frame.EME2000,
        metadata=meta,
    )
    assert traj.metadata["terminated"] is True
    assert traj.metadata["termination_reason"] == "user_min"
    assert traj.metadata["termination_epoch"] == "2026-06-14T09:12:44Z"


# --- array validation ------------------------------------------------------


def test_rejects_float32_positions():
    n = 2
    with pytest.raises(ValueError, match="float64"):
        Trajectory.from_arrays(
            [_epoch(i) for i in range(n)],
            _positions(n).astype(np.float32),
            _velocities(n),
            Frame.EME2000,
            metadata=_meta(),
        )


def test_rejects_wrong_position_shape():
    n = 2
    with pytest.raises(ValueError, match="shape"):
        Trajectory.from_arrays(
            [_epoch(i) for i in range(n)],
            np.zeros((n, 2), dtype=np.float64),
            _velocities(n),
            Frame.EME2000,
            metadata=_meta(),
        )


def test_rejects_inconsistent_n():
    with pytest.raises(ValueError, match="shape"):
        Trajectory.from_arrays(
            [_epoch(0), _epoch(1)],
            _positions(3),
            _velocities(3),
            Frame.EME2000,
            metadata=_meta(),
        )


def test_rejects_nonfinite_positions():
    n = 2
    bad = _positions(n)
    bad[0, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        Trajectory.from_arrays(
            [_epoch(i) for i in range(n)],
            bad,
            _velocities(n),
            Frame.EME2000,
            metadata=_meta(),
        )


def test_rejects_non_monotonic_epochs():
    # __post_init__ requires strictly-increasing epochs: Trajectory.at and the
    # Ephemeris that backs it take the first/last samples as the span and assume
    # chronological order, so out-of-order samples are rejected at construction.
    n = 4
    epochs = [_epoch(0), _epoch(2), _epoch(1), _epoch(3)]
    with pytest.raises(ValueError, match="strictly increasing"):
        Trajectory.from_arrays(
            epochs, _positions(n), _velocities(n), Frame.EME2000, metadata=_meta()
        )


def test_rejects_duplicate_epochs():
    # Duplicate timestamps are not strictly increasing (and would break Hermite).
    n = 2
    epochs = [_epoch(0), _epoch(0)]
    with pytest.raises(ValueError, match="strictly increasing"):
        Trajectory.from_arrays(
            epochs, _positions(n), _velocities(n), Frame.EME2000, metadata=_meta()
        )


def test_direct_init_rejects_int_epochs_wrong_dtype():
    n = 2
    with pytest.raises(ValueError, match="int64"):
        Trajectory(
            np.zeros(n, dtype=np.int32),
            np.zeros(n, dtype=np.float64),
            TimeScale.UTC,
            _positions(n),
            _velocities(n),
            Frame.EME2000,
            _meta(),
        )


def test_direct_init_ut1_rejected():
    n = 2
    with pytest.raises(NotImplementedError, match="UT1"):
        Trajectory(
            np.zeros(n, dtype=np.int64),
            np.zeros(n, dtype=np.float64),
            TimeScale.UT1,
            _positions(n),
            _velocities(n),
            Frame.EME2000,
            _meta(),
        )


# --- from_states / from_arrays input validation ----------------------------


def test_from_states_empty_rejected():
    with pytest.raises(ValueError):
        Trajectory.from_states([])


def test_from_states_mixed_frame_rejected():
    with pytest.raises(ValueError, match="frame"):
        Trajectory.from_states([_state(0, Frame.EME2000), _state(1, Frame.ITRF)])


def test_from_states_mixed_scale_rejected():
    with pytest.raises(ValueError, match="scale"):
        Trajectory.from_states(
            [_state(0, scale=TimeScale.UTC), _state(1, scale=TimeScale.TT)]
        )


def test_from_arrays_empty_epoch_list_rejected():
    with pytest.raises(ValueError):
        Trajectory.from_arrays(
            [], np.zeros((0, 3)), np.zeros((0, 3)), Frame.EME2000, metadata=_meta()
        )


def test_from_arrays_mixed_epoch_scale_rejected():
    with pytest.raises(ValueError, match="TimeScale"):
        Trajectory.from_arrays(
            [_epoch(0, TimeScale.UTC), _epoch(1, TimeScale.TT)],
            _positions(2),
            _velocities(2),
            Frame.EME2000,
            metadata=_meta(),
        )


def test_datetime64_wrong_unit_rejected():
    times = np.array(["2024-01-01", "2024-01-02"], dtype="datetime64[D]")
    with pytest.raises(ValueError, match="datetime64"):
        Trajectory.from_arrays(
            times, _positions(2), _velocities(2), Frame.EME2000, metadata=_meta()
        )


def test_datetime64_not_1d_rejected():
    times = np.array(
        [["2024-01-01T00:00:00"], ["2024-01-01T00:01:00"]], dtype="datetime64[ns]"
    )
    with pytest.raises(ValueError, match="1-D"):
        Trajectory.from_arrays(
            times, _positions(2), _velocities(2), Frame.EME2000, metadata=_meta()
        )


def test_datetime64_nat_rejected():
    times = np.array(["2024-01-01T00:00:00", "NaT"], dtype="datetime64[ns]")
    with pytest.raises(ValueError, match="NaT"):
        Trajectory.from_arrays(
            times, _positions(2), _velocities(2), Frame.EME2000, metadata=_meta()
        )


# --- indexing / iteration --------------------------------------------------


def test_negative_index():
    traj = _traj(4)
    assert traj[-1].epoch.to_iso() == _epoch(3).to_iso()


def test_index_out_of_range_raises():
    traj = _traj(4)
    with pytest.raises(IndexError):
        _ = traj[4]


def test_slice_index_rejected():
    traj = _traj(4)
    with pytest.raises(TypeError, match="slice"):
        _ = traj[0:2]


def test_iter_materializes_states():
    traj = _traj(4)
    states = list(traj)
    assert len(states) == 4
    assert all(isinstance(s, State) for s in states)
    assert states[0].epoch.to_iso() == _epoch(0).to_iso()


# --- to_dataframe ----------------------------------------------------------


def test_to_dataframe_shape_columns_attrs():
    n = 4
    traj = _traj(n)
    df = traj.to_dataframe()
    assert list(df.columns) == [
        "epoch_utc",
        "x_m",
        "y_m",
        "z_m",
        "vx_mps",
        "vy_mps",
        "vz_mps",
    ]
    assert len(df) == n
    assert df.attrs["frame"] == "EME2000"
    assert df.attrs["epoch_scale"] == "UTC"
    assert df.attrs["metadata"]["propagator"] == "test"
    np.testing.assert_array_equal(df["x_m"].to_numpy(), _positions(n)[:, 0])


def test_to_dataframe_epoch_dtype_is_ns():
    df = _traj(3).to_dataframe()
    assert str(df["epoch_utc"].dtype) == "datetime64[ns, UTC]"


def test_to_dataframe_empty_epoch_dtype_is_ns():
    empty = Trajectory.from_arrays(
        np.array([], dtype="datetime64[ns]"),
        np.zeros((0, 3), dtype=np.float64),
        np.zeros((0, 3), dtype=np.float64),
        Frame.EME2000,
        metadata=_meta(),
    )
    df = empty.to_dataframe()
    assert len(df) == 0
    # The empty case must not regress to datetime64[s] — dtype stays ns.
    assert str(df["epoch_utc"].dtype) == "datetime64[ns, UTC]"


# --- equality --------------------------------------------------------------


def test_equality_is_identity():
    traj = _traj()
    # Equality must not raise (the dataclass default would, on the ndarray
    # fields); it falls back to identity.
    assert traj == traj
    assert traj != _traj()
    assert traj != 42


# Note: Trajectory.at and Trajectory.to_frame are Orekit-crossing (they start the
# JVM), so their tests live in tests/test_conversions.py under the `orekit` fixture
# — they cannot run here without violating the safe-before-init invariant.
