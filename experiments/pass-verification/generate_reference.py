"""Generate the independent Skyfield reference pass table for Feature 1.5.

Computes the same search that ``tests/tracking/test_passes.py`` runs through
propygator — the fixed ISS (ZARYA) TLE over the Durham station, 2 days from
2026-06-23T00:00:00 UTC, 10 deg elevation gate — using **Skyfield** (an
entirely independent stack: python-sgp4 propagation, Skyfield's own
TEME-to-ITRS frame chain, topocentric geometry, and DE421 solar ephemeris; no
Orekit anywhere). The resulting table is the committed cross-check fixture the
build plan's Checkpoint A eyeballs (docs/history/build-plan-feature-1.5.md Chunk 3).

Run inside this experiment's throwaway venv (see README.md; the
docs/experiments_venv.md hygiene applies). Writes ``results.txt`` next to this
script and echoes it to stdout. ASCII-only output throughout (Windows cp1252).

Conventions matched to the propygator engine (features.md section 1.5):
- Geometric horizon: Skyfield ``find_events`` altitudes carry no refraction,
  same as propygator's geometric gate.
- ``sunlit_at_culmination`` via Skyfield ``is_sunlit`` (DE421). Note Skyfield
  models the shadow slightly differently from propygator's conical umbra, so
  knife-edge lighting flags may differ near a shadow crossing; times/angles are
  the authoritative comparison.
- Observer darkness context: the Sun's apparent altitude at the station at
  culmination (propygator gates visibility at <= -6 deg).
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

from skyfield.api import EarthSatellite, load, wgs84

# The fixture (keep byte-identical to tests/tracking/test_passes.py).
ISS_LINE1 = "1 25544U 98067A   26171.41461525  .00008813  00000+0  16600-3 0  9990"
ISS_LINE2 = "2 25544  51.6327 284.1189 0004557 208.5194 151.5545 15.49333088572250"
STATION_LAT_DEG = 35.99
STATION_LON_DEG = -78.90
STATION_ALT_M = 130.0
START_UTC = (2026, 6, 23, 0, 0, 0)
WINDOW_DAYS = 2.0
MIN_ELEVATION_DEG = 10.0


def main() -> None:
    lines: list[str] = []

    def emit(text: str = "") -> None:
        print(text)
        lines.append(text)

    ts = load.timescale()
    eph = load("de421.bsp")  # downloaded on first run, ~17 MB, gitignored
    satellite = EarthSatellite(ISS_LINE1, ISS_LINE2, "ISS (ZARYA)", ts)
    station = wgs84.latlon(
        STATION_LAT_DEG, STATION_LON_DEG, elevation_m=STATION_ALT_M
    )
    observer = eph["earth"] + station
    sun = eph["sun"]
    difference = satellite - station

    t0 = ts.utc(*START_UTC)
    t1 = ts.utc(
        START_UTC[0], START_UTC[1], START_UTC[2] + WINDOW_DAYS, *START_UTC[3:]
    )

    import skyfield

    emit("Skyfield reference pass table for the Feature 1.5 cross-check")
    emit("=" * 78)
    emit(f"generated_utc: {_dt.datetime.now(_dt.timezone.utc).isoformat()}")
    emit(f"python: {sys.version.split()[0]}")
    emit(f"skyfield: {skyfield.__version__}")
    emit("ephemeris: de421.bsp")
    emit(f"tle_line1: {ISS_LINE1}")
    emit(f"tle_line2: {ISS_LINE2}")
    emit(
        f"station: lat={STATION_LAT_DEG} deg lon={STATION_LON_DEG} deg "
        f"alt={STATION_ALT_M} m"
    )
    emit(f"window: {t0.utc_iso(places=0)} + {WINDOW_DAYS} days")
    emit(f"min_elevation: {MIN_ELEVATION_DEG} deg (geometric, no refraction)")
    emit()

    times, events = satellite.find_events(
        station, t0, t1, altitude_degrees=MIN_ELEVATION_DEG
    )

    def azel(t) -> tuple[float, float]:
        alt, az, _ = difference.at(t).altaz()  # no pressure arg: geometric
        return az.degrees, alt.degrees

    header = (
        f"{'#':>2} {'rise_utc':<26} {'raz':>7} {'culm_utc':<26} {'caz':>7} "
        f"{'cel':>7} {'set_utc':<26} {'saz':>7} {'sunlit_at_culm':>14} "
        f"{'sun_alt_culm':>12}"
    )
    emit(header)
    emit("-" * len(header))

    index = 0
    current: dict[str, object] = {}
    for t, event in zip(times, events):
        if event == 0:
            current = {"rise": t}
        elif event == 1:
            # keep the first culmination of the bracket (find_events can emit
            # stray culminations; a pass without one is labelled 'partial')
            if "culminate" not in current:
                current["culminate"] = t
        else:
            current["set"] = t
            rise = current.get("rise")
            culm = current.get("culminate")
            if rise is None or culm is None:
                emit(f"{index:>2} partial pass at window edge; skipped")
            else:
                raz, _ = azel(rise)
                caz, cel = azel(culm)
                saz, _ = azel(t)
                lit = bool(satellite.at(culm).is_sunlit(eph))
                sun_alt = (
                    observer.at(culm).observe(sun).apparent().altaz()[0].degrees
                )
                emit(
                    f"{index:>2} {rise.utc_iso(places=3):<26} {raz:7.2f} "
                    f"{culm.utc_iso(places=3):<26} {caz:7.2f} {cel:7.2f} "
                    f"{t.utc_iso(places=3):<26} {saz:7.2f} {str(lit):>14} "
                    f"{sun_alt:12.2f}"
                )
            index += 1
            current = {}
    if "rise" in current:
        emit(f"{index:>2} pass still in progress at window end; skipped")

    emit()
    emit(f"passes: {index}")

    out = Path(__file__).with_name("results.txt")
    out.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
