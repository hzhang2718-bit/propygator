"""Tests for the Feature 1.5 pass exporters (``export_passes_csv`` /
``export_passes_ics``, build-plan Chunk 4).

All headless — hand-built :class:`~propygator.core.observation.Pass` fixtures,
**no JVM** (a ``Pass`` carries only scalars and pure-Python ``Epoch`` objects, so
these tests deliberately do not request the ``orekit`` fixture and run in the
pure-Python phase). Two exporters:

- **CSV** — the DataFrame columns, UTC-only, under a ``# key: value`` metadata
  header (a column-parity test pins it to ``passes_to_dataframe``).
- **ICS** — a hand-rolled VCALENDAR; the output is a pure function of
  ``(passes, name)`` (deterministic ``DTSTAMP``/``UID``/``PRODID``), so the whole
  file is snapshot-tested, plus a structural parse.
"""

from __future__ import annotations

import pandas as pd

from propygator import (
    Epoch,
    Pass,
    TimeScale,
    export_passes_csv,
    export_passes_ics,
    passes_to_dataframe,
)


def _utc(iso: str) -> Epoch:
    return Epoch.from_iso(iso, scale=TimeScale.UTC)


def _hand_pass(
    rise_iso: str,
    culm_iso: str,
    set_iso: str,
    *,
    max_el: float,
    peak_mag: float | None,
    sunlit: bool = True,
    azimuths: tuple[float, float, float] = (120.0, 155.0, 200.0),
) -> Pass:
    return Pass(
        rise=_utc(rise_iso),
        culmination=_utc(culm_iso),
        set=_utc(set_iso),
        max_elevation_deg=max_el,
        peak_magnitude=peak_mag,
        sunlit_at_culmination=sunlit,
        rise_azimuth_deg=azimuths[0],
        culmination_azimuth_deg=azimuths[1],
        set_azimuth_deg=azimuths[2],
    )


def _two_passes() -> list[Pass]:
    """A faint magnitude-less pass and a bright one (exercises both SUMMARY shapes)."""
    return [
        _hand_pass(
            "2026-06-23T06:11:54",
            "2026-06-23T06:13:33",
            "2026-06-23T06:15:13",
            max_el=13.10,
            peak_mag=None,
        ),
        _hand_pass(
            "2026-06-23T07:46:41",
            "2026-06-23T07:49:59",
            "2026-06-23T07:53:18",
            max_el=51.61,
            peak_mag=-3.2,
        ),
    ]


# --- CSV ----------------------------------------------------------------------


def _read_csv(path):
    """Reload an exported passes CSV, skipping the ``# key: value`` header."""
    return pd.read_csv(path, comment="#")


def test_passes_csv_columns_match_the_dataframe(tmp_path):
    """The CSV column set/order tracks ``passes_to_dataframe`` (drift guard)."""
    passes = _two_passes()
    out = tmp_path / "passes.csv"
    export_passes_csv(passes, out)
    df = _read_csv(out)
    assert list(df.columns) == list(passes_to_dataframe(passes).columns)


def test_passes_csv_values(tmp_path):
    passes = _two_passes()
    out = tmp_path / "passes.csv"
    export_passes_csv(passes, out)
    df = _read_csv(out)

    assert len(df) == 2
    # UTC ISO strings (microsecond precision, matching the trajectory CSV epoch).
    assert df["rise"].iloc[0] == "2026-06-23T06:11:54.000000"
    assert df["set"].iloc[1] == "2026-06-23T07:53:18.000000"
    # duration_s = set - rise in seconds.
    assert df["duration_s"].iloc[0] == (15 * 60 + 13) - (11 * 60 + 54)  # 199 s
    assert df["max_elevation_deg"].iloc[1] == 51.61
    assert df["set_azimuth_deg"].iloc[0] == 200.0
    # A magnitude-less pass leaves peak_magnitude empty (NaN on reload).
    assert pd.isna(df["peak_magnitude"].iloc[0])
    assert df["peak_magnitude"].iloc[1] == -3.2
    assert bool(df["sunlit_at_culmination"].iloc[1]) is True


def test_passes_csv_metadata_header(tmp_path):
    passes = _two_passes()
    out = tmp_path / "passes.csv"
    export_passes_csv(passes, out)

    header = [
        ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.startswith("#")
    ]
    parsed = {}
    for line in header:
        key, _, value = line[2:].partition(": ")
        parsed[key] = value
    assert parsed["content"] == "passes"
    assert parsed["n_passes"] == "2"
    assert parsed["time_scale"] == "UTC"
    assert "propygator_version" in parsed
    assert "created_at" in parsed


def test_passes_csv_empty_list_writes_header_only(tmp_path):
    out = tmp_path / "passes.csv"
    export_passes_csv([], out)
    df = _read_csv(out)
    assert len(df) == 0
    assert list(df.columns) == list(passes_to_dataframe([]).columns)


# --- ICS ----------------------------------------------------------------------

_EXPECTED_ICS = (
    "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//propygator//passes//EN",
            "CALSCALE:GREGORIAN",
            "BEGIN:VEVENT",
            "UID:20260623T061154Z-0@propygator",
            "DTSTAMP:20260623T061154Z",
            "DTSTART:20260623T061154Z",
            "DTEND:20260623T061513Z",
            "SUMMARY:ISS pass - max el 13 deg",
            "END:VEVENT",
            "BEGIN:VEVENT",
            "UID:20260623T074641Z-1@propygator",
            "DTSTAMP:20260623T074641Z",
            "DTSTART:20260623T074641Z",
            "DTEND:20260623T075318Z",
            "SUMMARY:ISS pass - max el 52 deg\\, mag -3.2",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )
    + "\r\n"
)


def test_passes_ics_exact_snapshot(tmp_path):
    """The whole file is a pure function of (passes, name) — byte-stable."""
    out = tmp_path / "passes.ics"
    export_passes_ics(_two_passes(), out, name="ISS")
    # read_bytes (not read_text) so the mandated CRLF line breaks are verified.
    assert out.read_bytes().decode("utf-8") == _EXPECTED_ICS


def test_passes_ics_uses_crlf_line_breaks(tmp_path):
    out = tmp_path / "passes.ics"
    export_passes_ics(_two_passes(), out, name="ISS")
    raw = out.read_bytes()
    assert b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")  # no bare LF


def test_passes_ics_structure(tmp_path):
    out = tmp_path / "passes.ics"
    export_passes_ics(_two_passes(), out, name="ISS")
    lines = out.read_text(encoding="utf-8").splitlines()

    assert lines[0] == "BEGIN:VCALENDAR"
    assert lines[-1] == "END:VCALENDAR"
    assert lines.count("BEGIN:VEVENT") == 2
    assert lines.count("END:VEVENT") == 2

    # Every VEVENT carries the required fields; every timestamp is UTC (ends Z).
    for start in (i for i, ln in enumerate(lines) if ln == "BEGIN:VEVENT"):
        end = lines.index("END:VEVENT", start)
        block = lines[start + 1 : end]
        keys = {ln.split(":", 1)[0] for ln in block}
        assert {"UID", "DTSTAMP", "DTSTART", "DTEND", "SUMMARY"} <= keys
        for prop in ("DTSTAMP", "DTSTART", "DTEND"):
            value = next(ln.split(":", 1)[1] for ln in block if ln.startswith(prop))
            assert value.endswith("Z")


def test_passes_ics_name_defaults_to_generic_label(tmp_path):
    out = tmp_path / "passes.ics"
    export_passes_ics(_two_passes(), out)  # no name=
    text = out.read_text(encoding="utf-8")
    assert "SUMMARY:Satellite pass - max el 13 deg" in text


def test_passes_ics_magnitude_clause_omitted_when_none(tmp_path):
    out = tmp_path / "passes.ics"
    export_passes_ics(_two_passes(), out, name="ISS")
    # read_text applies universal newlines, so CRLF is normalized to \n here
    # (the raw CRLF is asserted in the snapshot/line-break tests).
    text = out.read_text(encoding="utf-8")
    # The faint (magnitude-less) pass has no ", mag ..." clause; the bright one does.
    assert "SUMMARY:ISS pass - max el 13 deg\n" in text
    assert "mag -3.2" in text
