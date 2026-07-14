"""Chunk 2c diagnostic probe: is the NRLMSISE-00 instance propygator builds
driven by the real-time 3-hourly ap, or by the daily Ap only?

Motivation: the Gannon-storm onset arc (t0 2024-05-10, ``results.txt``) fitted
Cd = 1.777 -- *below* even the quiet-2019 window -- and the fixed-Cd
storm-surprise run diverged smoothly from hour 3, hours before storm onset.
Hypothesis: the model is driven by the daily Ap (105 on 05-10, an average
dominated by the evening storm), smearing storm-level density backward across
the actually-quiet morning.

Method: density at the SAME Earth-fixed point and SAME UT hour on 2024-05-09
(daily Ap 5, 3-hourly ap 3), 2024-05-10 pre-onset (daily Ap 105, but real
3-hourly ap 9 at 06:00), and 2024-05-11 (daily Ap 271, 3-hourly ap 236). Same
UT hour at the same ECEF point = same local solar time; F10.7 is near-identical
(slightly *decreasing*) across the three days -- so any large density jump on
the pre-onset quiet morning can only come from the daily geomagnetic index.

Recorded output (2026-07-13; quoted in README.md "Storm window" section):

    2024-05-09T06:00:00  rho = 1.425e-12 kg/m^3  daily Ap =   5.0  ap now =   3.0  F10.7 = 230.7
    2024-05-10T06:00:00  rho = 2.740e-12 kg/m^3  daily Ap = 105.0  ap now =   9.0  F10.7 = 221.0
    2024-05-11T06:00:00  rho = 4.653e-12 kg/m^3  daily Ap = 271.0  ap now = 236.0  F10.7 = 215.7

The 05-10 pre-onset density is 1.92x the 05-09 value at identical real-time ap
-- matching the onset-arc fitted-Cd ratio 3.405/1.777 = 1.92 almost exactly.
Conclusion: Orekit's ``NRLMSISE00`` at default switches (the construction in
``propygator.propagation.numerical``) consumes the *daily* Ap; the
``CssiSpaceWeatherData`` provider does supply the true 3-hourly ap (printed
here as "ap now" = ``getAp()[1]``), but the model's default switch
configuration does not use the ap-history array. The ap-history mode
(``withSwitch(9, -1)`` per the NRLMSISE-00 convention) is a named follow-on,
not wired in propygator.

Reference-only: not shipped, not in CI, outside ``testpaths``. Runs in the
propygator conda env (starts the JVM, needs orekit-data):

    conda run -n propygator python probe_ap_driving.py

ASCII-only stdout.
"""

import propygator

propygator.init()

from org.hipparchus.geometry.euclidean.threed import Vector3D  # noqa: E402
from org.orekit.models.earth.atmosphere import NRLMSISE00  # noqa: E402
from org.orekit.models.earth.atmosphere.data import CssiSpaceWeatherData  # noqa: E402

from propygator import Epoch, Frame, TimeScale  # noqa: E402
from propygator.core import bodies  # noqa: E402

cssi = CssiSpaceWeatherData(CssiSpaceWeatherData.DEFAULT_SUPPORTED_NAMES)
# Same construction as propygator.propagation.numerical (default switches).
atm = NRLMSISE00(cssi, bodies._sun(), bodies._earth())
itrf = Frame.ITRF.to_orekit()
point = Vector3D(6851.0e3, 0.0, 0.0)  # equatorial ECEF point at ~473 km altitude

print("same ITRF point, same UT hour -> same local solar time; only geomagnetic")
print("input differs (F10.7 near-identical across the three days)")
for iso in (
    "2024-05-09T06:00:00",
    "2024-05-10T06:00:00",  # pre-onset: real 3-hourly ap ~9, daily Ap 105
    "2024-05-11T06:00:00",  # full storm: 3-hourly ap 236, daily Ap 271
):
    date = Epoch.from_iso(iso, TimeScale.UTC).to_orekit()
    rho = float(atm.getDensity(date, point, itrf))
    ap = cssi.getAp(date)
    f107 = float(cssi.getInstantFlux(date))
    print(
        f"  {iso}  rho = {rho:.3e} kg/m^3   daily Ap = {float(ap[0]):5.1f}   "
        f"3-hourly ap now = {float(ap[1]):5.1f}   F10.7 = {f107:.1f}"
    )
