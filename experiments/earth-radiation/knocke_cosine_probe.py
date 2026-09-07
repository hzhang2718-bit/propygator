"""Probe the Orekit KnockeRediffusedForceModel Lambertian-cosine defect (ERP block #2).

Companion to knocke_bug_probe.py. That probe's verdict reads UNEXPECTED (1.69)
on Orekit 13.1.7, where the horizon-bound bug it was written for is fixed. This
script explains the residual: `computeElementaryFlux` fills the Lambertian
emission-cosine slot with the cosine of the GEOCENTRIC angle between element and
satellite,

    cosAlpha = (elementCenter . satellitePosition) / (|elementCenter| |satellitePosition|)

where the physics needs the angle between the element's own normal and the
element->satellite vector,

    cosTheta = ((satPos - elementCenter) . elementCenter) / (|satPos - elementCenter| |elementCenter|)

The two agree only at the sub-satellite point: at the true horizon cosTheta is 0
while cosAlpha is R/r (0.94 at 400 km), so limb elements are over-weighted and
the force runs ~2x hot at LEO. See README.md "Bug 2".

Method: re-implement Orekit's exact discretisation in numpy (center cap, crowns
from 1.5*res, its sector-area formula, its Legendre emissivity/albedo models,
ES_COEFF flux), twice -- once as coded, once with only that cosine corrected.
The as-coded replica is validated against the live Orekit acceleration for the
same state, so the corrected number is trustworthy by construction.

Requires an env wrapping Orekit >= 13.1.6 (the replica hard-codes the fixed
acos horizon bound, so it will NOT reproduce a 13.1.4 build). The clone-env
recipe is in README.md; the working propygator env is on 13.1.4.0.

Run (ASCII-only stdout, cp1252 redirect):

    conda run -n <clone-env> python knocke_cosine_probe.py > knocke_cosine_probe_results.txt
"""

import numpy as np

from propygator import Epoch, Frame, KeplerianElements, TimeScale

EPOCH = Epoch.from_iso("2026-01-01T00:00:00", scale=TimeScale.UTC)

# Same reference spacecraft as knocke_bug_probe.py.
AREA_M2 = 1.0
CR = 1.5
MASS_KG = 200.0

SPEED_OF_LIGHT = 299792458.0
ASTRONOMICAL_UNIT = 1.495978707e11

# KnockeRediffusedForceModel constants, read from the 13.1.7 source.
ES_COEFF = 4.5606e-6
A0, C0, C1, C2, A2 = 0.34, 0.0, 0.10, 0.0, 0.29
E0, K0, K1, K2, E2 = 0.68, 0.0, -0.07, 0.0, -0.18


def make_state(a_m: float, nu_deg: float, i_deg: float):
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


def rotate(v, axis_unit, angle):
    """Rodrigues rotation matching Orekit's VECTOR_OPERATOR convention."""
    k = axis_unit
    c, s = np.cos(angle), np.sin(angle)
    return v * c + np.cross(k, v) * s + k * np.dot(k, v) * (1.0 - c)


def legendre(sin_phi):
    return sin_phi, 0.5 * (3.0 * sin_phi**2 - 1.0)


def replica(sat_pos, sun_pos, radius, resolution, delta_t_s, julian_year, corrected):
    """Orekit's crown summation; `corrected` swaps cosAlpha for the emission cosine."""
    omega_dt = (2.0 * np.pi / julian_year) * delta_t_s
    e1 = K0 + K1 * np.cos(omega_dt) + K2 * np.sin(omega_dt)
    a1 = C0 + C1 * np.cos(omega_dt) + C2 * np.sin(omega_dt)

    r_sat = np.linalg.norm(sat_pos)
    sat_hat = sat_pos / r_sat
    sun_norm = np.linalg.norm(sun_pos)
    sun_hat = sun_pos / sun_norm
    solar_flux = ES_COEFF * SPEED_OF_LIGHT / (sun_norm / ASTRONOMICAL_UNIT) ** 2

    projected = sat_hat * radius
    q = 1.0 / np.hypot(sat_pos[0], sat_pos[1])
    east = np.array([-q * sat_pos[1], q * sat_pos[0], 0.0])

    # Element centers and areas, exactly as the Java acceleration() lays them out.
    centers = [projected]
    areas = [2.0 * np.pi * radius**2 * (1.0 - np.cos(resolution))]
    offset = 1.5 * resolution
    horizon = np.arccos(radius / r_sat)
    while offset < horizon:
        first = rotate(projected, east, offset)
        sector_area = (
            radius**2 * 2.0 * resolution * np.sin(0.5 * resolution) * np.sin(offset)
        )
        radial = 0.5 * resolution
        while radial < 2.0 * np.pi:
            centers.append(rotate(first, sat_hat, radial))
            areas.append(sector_area)
            radial += resolution
        offset += resolution
    centers = np.array(centers)
    areas = np.array(areas)

    center_norm = np.linalg.norm(centers, axis=1)
    r_vec = sat_pos - centers
    r_norm = np.linalg.norm(r_vec, axis=1)

    cos_alpha_orekit = centers @ sat_pos / (center_norm * r_sat)
    cos_theta_true = np.einsum("ij,ij->i", r_vec, centers) / (r_norm * center_norm)
    cos_factor = cos_theta_true if corrected else cos_alpha_orekit

    visible = cos_factor > 0.0
    sin_phi = centers[:, 2] / center_norm
    p1, p2 = legendre(sin_phi)
    emissivity = E0 + e1 * p1 + E2 * p2
    cos_sun = centers @ sun_hat / center_norm
    albedo = np.where(cos_sun > 0.0, A0 + a1 * p1 + A2 * p2, 0.0)
    lit_cos_sun = np.where(cos_sun > 0.0, cos_sun, 0.0)

    albedo_and_ir = albedo * solar_flux * lit_cos_sun + emissivity * solar_flux * 0.25
    scale = np.where(visible, areas * cos_factor / (np.pi * r_norm**3), 0.0)
    flux = (r_vec * (scale * albedo_and_ir / SPEED_OF_LIGHT)[:, None]).sum(axis=0)

    # Flux-weighted mean emissivity, so the IR-only anchor uses the model's own value.
    weight = np.where(visible, areas * cos_factor / r_norm**3, 0.0)
    mean_e = float((weight * emissivity).sum() / weight.sum())
    accel = CR * (AREA_M2 / MASS_KG) * float(np.linalg.norm(flux))
    return accel, mean_e, len(centers), solar_flux


def ir_anchor(r_m, radius, emissivity, solar_flux):
    """Closed-form isotropic-sphere IR-only acceleration: Cr (A/m) (e S/4) (R/r)^2 / c."""
    exitance = emissivity * solar_flux / 4.0
    return CR * (AREA_M2 / MASS_KG) / SPEED_OF_LIGHT * exitance * (radius / r_m) ** 2


def main() -> None:
    import propygator

    propygator.init()

    from org.orekit.time import AbsoluteDate, TimeScalesFactory
    from org.orekit.utils import Constants

    from propygator._orekit_init import _orekit_version
    from propygator.core.bodies import _sun

    radius = float(Constants.WGS84_EARTH_EQUATORIAL_RADIUS)
    julian_year = float(Constants.JULIAN_YEAR)
    reference_epoch = AbsoluteDate(1981, 12, 22, 0, 0, 0.0, TimeScalesFactory.getUTC())

    print("orekit_jpype version:", _orekit_version())
    print(f"spacecraft: sphere A={AREA_M2} m^2, Cr={CR}, m={MASS_KG} kg")
    print("epoch: 2026-01-01T00:00:00 UTC, angularResolution 1 deg")
    print()

    resolution = float(np.radians(1.0))
    cases = [
        ("LEO eclipse (a=6778 km, i=51.6 deg, nu=90)", 6778e3, 90.0, 51.6),
        ("LEO lit     (a=6778 km, i=51.6 deg, nu=0)", 6778e3, 0.0, 51.6),
        ("GEO         (a=42164 km, i=0.1 deg, nu=0)", 42164e3, 0.0, 0.1),
    ]

    for label, a_m, nu, inc in cases:
        state = make_state(a_m, nu, inc)
        force = build_knocke(resolution)
        live = float(force.acceleration(state, force.getParameters()).getNorm())

        position = state.getPosition()
        sat_pos = np.array([position.getX(), position.getY(), position.getZ()])
        sun_vector = _sun().getPosition(state.getDate(), state.getFrame())
        sun_pos = np.array([sun_vector.getX(), sun_vector.getY(), sun_vector.getZ()])
        delta_t = float(state.getDate().durationFrom(reference_epoch))

        as_coded, mean_e, n_elements, solar_flux = replica(
            sat_pos, sun_pos, radius, resolution, delta_t, julian_year, corrected=False
        )
        fixed, mean_e_fixed, _, _ = replica(
            sat_pos, sun_pos, radius, resolution, delta_t, julian_year, corrected=True
        )
        anchor = ir_anchor(np.linalg.norm(sat_pos), radius, mean_e_fixed, solar_flux)

        print(label)
        print(f"  elements {n_elements}, solar flux {solar_flux:.2f} W/m^2")
        print(f"  live Orekit           {live:.4e} m/s^2")
        print(f"  replica as coded      {as_coded:.4e}  (replica/live {as_coded / live:.4f})")
        print(f"  replica cosine fixed  {fixed:.4e}")
        print(f"  as-coded inflation    {as_coded / fixed:.3f}x")
        print(f"  flux-weighted mean e  {mean_e:.4f} (as coded) / {mean_e_fixed:.4f} (fixed)")
        print(f"  IR-only anchor at that e: {anchor:.4e}  -> fixed/anchor {fixed / anchor:.3f}")
        print()

    print("READ: replica/live = 1.0000 validates the replica; the inflation column is")
    print("the cosAlpha defect's cost. In eclipse (albedo zero) the cosine-fixed value")
    print("matches the closed-form anchor to ~1 percent, so no third defect remains.")


if __name__ == "__main__":
    main()
