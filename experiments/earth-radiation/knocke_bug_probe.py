"""Probe the Orekit KnockeRediffusedForceModel horizon-angle defect (ERP block).

Evidence for the general-upgrades-1.md "Planetary Third-Body & Earth Radiation
Pressure" Outcome note: the `earth_radiation` feature is BLOCKED because every
released Orekit through 13.1.5 bounds the visible-cap crown loop with
asin(R/r) where the correct Earth-central bound is acos(R/r) (fixed on the
13.1.6 tag, 2026-06-03). The wrong cap makes the force ~2.4-3x too strong at
LEO (a ~70 deg cap instead of ~20 deg) and ~10x too weak at GEO (an ~8.7 deg
cap instead of ~81 deg) -- the over/under-counting flips with altitude, which
is this probe's fingerprint.

This script is also the RESUME SANITY CHECK: when a new orekit_jpype (wrapping
Orekit >= 13.1.6) is trialled in a cloned env, run it again -- the verdict at
the bottom says whether the fix is in. Self-contained: builds the Knocke force
directly from org.orekit (no propygator ERP runtime required; that code is
parked in erp-runtime-chunk2.patch).

Run (conda env -- JVM + orekit-data; ASCII-only stdout, cp1252 redirect):

    conda run -n propygator python knocke_bug_probe.py > knocke_bug_probe_results.txt
"""

import numpy as np

from propygator import Epoch, Frame, KeplerianElements, TimeScale
from propygator._orekit_init import _orekit_version

EPOCH = Epoch.from_iso("2026-01-01T00:00:00", scale=TimeScale.UTC)

# Reference spacecraft: 1 m^2 sphere, Cr = 1.5, 200 kg (A/m = 0.005 m^2/kg).
AREA_M2 = 1.0
CR = 1.5
MASS_KG = 200.0

# --- textbook anchors (see README for the derivations) -----------------------
# SRP at 1 AU: P0 * Cr * A/m; early January adds ~+3.4% (Sun ~0.983 AU).
SRP_1AU = 4.56e-6 * CR * (AREA_M2 / MASS_KG)
# LEO eclipse (IR-only) anchor: for an isotropic sphere the elementary Knocke
# fluxes sum to M_ir * sin^2(rho) (rho = horizon half-angle, sin rho = R/r):
# a = Cr * (A/m) / c * M_ir * (R/r)^2, with Knocke M_ir = 0.68 * 1361/4 W/m^2.
R_EARTH = 6378137.0
M_IR = 0.68 * 1361.0 / 4.0  # ~231 W/m^2


def ir_only_anchor(r_m: float) -> float:
    return CR * (AREA_M2 / MASS_KG) / 299792458.0 * M_IR * (R_EARTH / r_m) ** 2


def make_state(a_m: float, nu_deg: float, i_deg: float):
    # The shipped State -> SpacecraftState crossing; neither force reads an orbit
    # or mu, and withMass attaches the probe mass (verified bit-identical to a
    # hand-built CartesianOrbit + SpacecraftState route).
    initial = KeplerianElements(
        semi_major_axis_m=a_m,
        eccentricity=0.001,
        inclination_rad=np.radians(i_deg),
        raan_rad=0.0,
        arg_perigee_rad=0.0,
        true_anomaly_rad=np.radians(nu_deg),
    ).to_state(EPOCH, Frame.EME2000)
    return initial.to_orekit().withMass(MASS_KG)


def build_knocke(resolution_rad: float):
    from org.orekit.forces.radiation import (
        IsotropicRadiationSingleCoefficient,
        KnockeRediffusedForceModel,
    )
    from org.orekit.utils import Constants

    from propygator.core.bodies import _sun

    radiation = IsotropicRadiationSingleCoefficient(AREA_M2, CR)
    return KnockeRediffusedForceModel(
        _sun(), radiation, Constants.WGS84_EARTH_EQUATORIAL_RADIUS, resolution_rad
    )


def build_srp():
    from org.orekit.forces.radiation import (
        IsotropicRadiationSingleCoefficient,
        SolarRadiationPressure,
    )

    from propygator.core.bodies import _earth, _sun

    radiation = IsotropicRadiationSingleCoefficient(AREA_M2, CR)
    return SolarRadiationPressure(_sun(), _earth(), radiation)


def accel(force, state) -> float:
    return float(force.acceleration(state, force.getParameters()).getNorm())


def main() -> None:
    import propygator

    propygator.init()  # the builders below cross into org.orekit directly
    print("orekit_jpype version:", _orekit_version())
    print(f"spacecraft: sphere A={AREA_M2} m^2, Cr={CR}, m={MASS_KG} kg")
    print("epoch: 2026-01-01T00:00:00 UTC")
    print()

    # States are invariant across the resolution ladders; build each once.
    leo_states = [make_state(6778e3, nu, 51.6) for nu in (0.0, 90.0, 270.0)]
    geo_states = [make_state(42164e3, nu, 0.1) for nu in (0.0, 270.0)]

    # SRP cross-check: validates the probe pattern (acceleration + getParameters).
    srp = build_srp()
    a_srp = accel(srp, leo_states[0])
    print(f"SRP at lit LEO point: {a_srp:.4e} m/s^2")
    print(f"  theory {SRP_1AU:.4e} * ~1.034 (January Sun distance) "
          f"= {SRP_1AU * 1.034:.4e}  -> ratio {a_srp / (SRP_1AU * 1.034):.3f}")
    print()

    # LEO resolution ladder (nu=90 is in eclipse at this epoch: IR-only).
    print("LEO ~400 km (a=6778 km, i=51.6 deg) Knocke ERP vs angularResolution:")
    print("  res[deg]   nu=0 [m/s^2]   nu=90 eclipse   nu=270")
    eclipse = float("nan")
    for deg in (90.0, 45.0, 30.0, 15.0, 10.0, 5.0, 2.0, 1.0):
        erp = build_knocke(float(np.radians(deg)))
        row = [accel(erp, state) for state in leo_states]
        print(f"  {deg:8.1f}   {row[0]:.4e}     {row[1]:.4e}      {row[2]:.4e}")
        if deg == 1.0:
            eclipse = row[1]  # the converged value the verdict below reads
    leo_anchor = ir_only_anchor(6778e3)
    print(f"  IR-only anchor at nu=90: {leo_anchor:.4e} m/s^2")
    print()

    # GEO ladder: with the asin bound the visible cap collapses to ~8.7 deg,
    # so the force is far too weak (and at 15 deg resolution the crown loop
    # never runs at all -- only the central element remains).
    print("GEO (a=42164 km, i=0.1 deg) Knocke ERP vs angularResolution:")
    print("  res[deg]   nu=0 [m/s^2]   nu=270")
    for deg in (15.0, 5.0, 2.0, 1.0):
        erp = build_knocke(float(np.radians(deg)))
        row = [accel(erp, state) for state in geo_states]
        print(f"  {deg:8.1f}   {row[0]:.4e}     {row[1]:.4e}")
    geo_anchor = ir_only_anchor(42164e3)
    print(f"  IR-only anchor: {geo_anchor:.4e} m/s^2 (dayside adds albedo, up to ~2x)")
    print()

    # Verdict off the converged (1 deg) LEO eclipse value -- IR-only physics is
    # the cleanest hand-verifiable anchor.
    ratio = eclipse / leo_anchor
    print(f"VERDICT (converged LEO eclipse / IR-only anchor = {ratio:.2f}):")
    if ratio > 1.7:
        print("  BUG PRESENT (asin horizon bound, Orekit <= 13.1.5): ERP is ~2.4-3x")
        print("  hot at LEO and ~10x cold at GEO. Do NOT ship earth_radiation.")
    elif 0.5 < ratio < 1.5:
        print("  LOOKS FIXED (acos bound, Orekit >= 13.1.6): proceed with the")
        print("  resume recipe in README.md (apply the patch, re-run the")
        print("  resolution benchmark, ship as its own branch).")
    else:
        print("  UNEXPECTED value -- investigate before shipping either way.")


if __name__ == "__main__":
    main()
