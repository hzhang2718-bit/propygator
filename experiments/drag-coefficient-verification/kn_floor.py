"""
Knudsen-number low-altitude validity floor for the free-molecular drag model.

This is the *model-validity* instrument the collapse experiment is blind to
(drag-validity addendum sec. 2). The collapse study (cd_sphere_experiment.py)
uses the free-molecular Sentman/DRIA C_D as its own ground truth, so it stays
tight *precisely where the model is becoming wrong* at low altitude. The
breakdown is a separate, body-size-dependent question: below some altitude a
meter-scale body leaves free-molecular flow (Knudsen number Kn -> O(1)), the
transitional regime sets in, and the DRIA closed form systematically
over-predicts C_D. This module finds that floor.

Method (addendum sec. 3.4-3.5):
  * Mean free path, COMPOSITION-WEIGHTED:
        lambda = 1 / (sqrt(2) * sum_i n_i * sigma_i)
    over the major NRLMSISE-00 species, with n_i the per-species NUMBER density
    [1/m^3] and sigma_i = pi d_i^2 the per-species hard-sphere collision cross
    section. The sum runs per species (NOT a single lumped sigma) so the O->He->H
    composition shift across this band is carried; sigma differs by species.
    Temperature drops out -- lambda depends only on number densities and sigma.
    The sqrt(2) self-collision relative-speed factor is applied uniformly: a
    documented single-gas simplification, adequate for a conservative guard floor
    (in the N2/O2/O-dominated floor band ~100-250 km it agrees with a fully
    mass-corrected mixture form to a few %, well inside the ~20-30% sigma
    uncertainty; the mass correction only bites where light H/He dominate, i.e.
    above ~500 km, which never sets the floor).
  * Knudsen number Kn = lambda / L for a body of characteristic length L [m].
  * Free-molecular threshold Kn = 10 (the conventional conservative criterion;
    0.1 < Kn < 10 is transitional where DRIA over-predicts; Kn = 100 would be
    over-conservative).
  * floor_altitude(L): scan altitude for the Kn = 10 crossing, evaluated at a
    CONSERVATIVE high-activity atmosphere (denser at altitude -> shorter lambda
    -> the crossing moves up -> a higher, safer floor).

This is the method the runtime re-implements at propagation setup (addendum
sec. 6.3) -- a third independent reconstruction, subject to the sec. 5
equivalence check. Keep the physics importable and small so that cross-check
(addendum Chunk 3 / runtime Chunk 9) is a clean comparison.

Collision-cross-section sources. sigma_i = pi d_i^2 from representative
hard-sphere / kinetic collision diameters d_i:
  * Molecular N2, O2, Ar: standard kinetic-diameter tables (e.g. Breck, Zeolite
    Molecular Sieves, 1974; widely tabulated gas-kinetic diameters).
  * He, H: gas-kinetic collision diameters (same family of tables).
  * Atomic O, N: aeronomy collision diameters ~3.0e-10 m (Bird, Molecular Gas
    Dynamics and the Direct Simulation of Gas Flows, 1994, VHS reference data;
    atomic-species values carry more uncertainty than the lab-measured molecular
    ones). The floor band is N2/O2/O-dominated where the values are best known,
    and the diagnostic is a deliberately conservative fence -- larger sigma ->
    shorter lambda -> higher floor, so the uncertain direction is the safe one.

Reference-only (addendum / experiment README): not shipped, not in CI, not
linted/type-checked. Runs in the throwaway venv (docs/experiments_venv.md) with
pymsis + scipy. Reuses cd_core's NRLMSISE-00 column map (SPECIES).
"""
import numpy as np

from cd_core import SPECIES  # per-species (column index, mass) NRLMSISE-00 map

# --- per-species hard-sphere collision cross sections ----------------------
# Kinetic / collision diameters d_i [m]; sigma_i = pi d_i^2 [m^2]. Keyed on the
# same species names cd_core.SPECIES uses. See the module docstring for sources.
_KINETIC_DIAMETER_M = {
    "N2": 3.64e-10,
    "O2": 3.46e-10,
    "O": 3.00e-10,   # atomic; aeronomy estimate, more uncertain
    "HE": 2.18e-10,
    "H": 2.40e-10,   # atomic; estimate, more uncertain
    "AR": 3.40e-10,
    "N": 3.00e-10,   # atomic; estimate, more uncertain
}
SIGMA = {sp: float(np.pi * d * d) for sp, d in _KINETIC_DIAMETER_M.items()}

# Free-molecular Knudsen threshold (addendum sec. 3.4).
KN_FREE_MOLECULAR = 10.0

_SQRT2 = float(np.sqrt(2.0))  # single-gas relative-speed factor (see docstring)


# --- conservative / reference atmosphere profiles --------------------------
# The floor is evaluated at a CONSERVATIVE high-activity atmosphere: solar max +
# disturbed geomagnetic, dayside equatorial (the densest case), so the Kn = 10
# crossing -- and hence the floor -- sits high and safe (addendum sec. 3.4). The
# binding runtime choice is confirmed at Chunk 9; this is the documented Chunk-2
# profile. MID_ACTIVITY exists only to confirm the conservatism DIRECTION (the
# high-activity floor must come out higher).
CONSERVATIVE_HIGH = dict(
    date=np.datetime64("2002-07-01T12:00"),  # solar-max era, summer noon
    lon=0.0,
    lat=0.0,                                 # equatorial dayside -> dense
    f107=250.0,
    f107a=250.0,
    ap=45.0,
    label="conservative high-activity (F10.7=250, Ap=45)",
)
MID_ACTIVITY = dict(
    date=np.datetime64("2008-07-01T12:00"),  # solar-min era
    lon=0.0,
    lat=0.0,
    f107=120.0,
    f107a=120.0,
    ap=10.0,
    label="mid-activity (F10.7=120, Ap=10)",
)

# --- representative body characteristic lengths (addendum sec. 3.5) ---------
# L = 0.1 m (1U CubeSat) -> 30 m (station/truss scale). At runtime L is derived
# from geometry: sphere -> diameter 2*sqrt(A/pi); box -> max edge length
# (conservative). This grid is the committed evidence curve; the runtime is NOT
# confined to it (it scans for the actual L), and the curve is ~logarithmic in L
# so reading just past either end is safe.
L_GRID_M = np.geomspace(0.1, 30.0, 30)

REFERENCE_BODIES = (
    ("1U CubeSat", 0.10),
    ("3U CubeSat", 0.34),
    ("smallsat", 1.0),
    ("small bus", 3.0),
    ("large bus", 5.0),
    ("ISS module", 10.0),
    ("station", 30.0),
)


# --- physics ----------------------------------------------------------------


def mean_free_path(msis_row):
    """Composition-weighted hard-sphere mean free path lambda [m] from one MSIS row.

    lambda = 1 / (sqrt(2) * sum_i n_i * sigma_i) over the major species, with n_i
    the per-species NUMBER density [1/m^3] (NRLMSISE-00 columns, SI from pymsis)
    and sigma_i the per-species cross section (SIGMA). Non-finite / non-positive
    species densities are skipped. Returns +inf if every species is empty.
    """
    total = 0.0
    for sp, (col, _mass) in SPECIES.items():
        n = msis_row[col]
        if not np.isfinite(n) or n <= 0.0:
            continue
        total += n * SIGMA[sp]
    if total <= 0.0:
        return float("inf")
    return 1.0 / (_SQRT2 * total)


def knudsen(msis_row, length_m):
    """Knudsen number Kn = lambda / L for a body of characteristic length L [m]."""
    return mean_free_path(msis_row) / length_m


def msis_row(profile, alt_km):
    """One NRLMSISE-00 state row at ``alt_km`` under a fixed condition ``profile``.

    pymsis is imported lazily (it is only available in the experiment venv), so
    the pure physics above stays importable without it.
    """
    from pymsis import msis

    p = profile
    return msis.run(
        [p["date"]], [p["lon"]], [p["lat"]], [alt_km],
        [p["f107"]], [p["f107a"]], [[p["ap"]] * 7], version=0,
    )[0]


def floor_altitude(
    length_m,
    *,
    profile=CONSERVATIVE_HIGH,
    kn_threshold=KN_FREE_MOLECULAR,
    alt_lo_km=85.0,
    alt_hi_km=450.0,
):
    """Geodetic altitude [km] where Kn = ``kn_threshold`` for a body of length L.

    The free-molecular floor: below it the body has left free-molecular flow and
    the Sentman/DRIA C_D over-predicts (addendum sec. 2, 3.4). Kn rises with
    altitude (density falls -> lambda grows), so there is a single crossing;
    found with ``scipy.optimize.brentq`` on f(h) = Kn(h) - threshold. Each eval
    is one MSIS call (a few dozen total). Returns ``nan`` if the crossing is not
    bracketed by [alt_lo_km, alt_hi_km].
    """
    from scipy.optimize import brentq

    def f(alt_km):
        return knudsen(msis_row(profile, alt_km), length_m) - kn_threshold

    f_lo = f(alt_lo_km)
    f_hi = f(alt_hi_km)
    if not (np.isfinite(f_lo) and np.isfinite(f_hi)) or f_lo * f_hi > 0.0:
        return float("nan")  # no sign change -> crossing outside the bracket
    return float(brentq(f, alt_lo_km, alt_hi_km, xtol=1.0e-3))
