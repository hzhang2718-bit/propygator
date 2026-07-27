"""LAGEOS-2 ablation matrix — the Chunk 1 per-toggle wiring proof.

Evidence for ``docs/history/build-plan-real-world-validation.md`` Chunk 1: rerun the
Chunk 0 arc with one ``ForceModelConfig`` change at a time and require every
ablation to move the truth residual by roughly its physically predicted order
(and ``planets_third_body`` to move ~nothing). This is direct evidence that
each toggle actually reaches Orekit — the class of bug internal tests
structurally cannot see, because the truth orbit can't share the wiring.

The "predicted order" column is **computed, not quoted**: per-force
acceleration scales are evaluated along the truth orbit (gravity-field degree
sums from the actual EIGEN-6S coefficients, third-body/tide scales from the DE
ephemeris distances, Schwarzschild from the sampled PV) and turned into a
1-day free-drift bound a*t^2/2 — a *secular upper limit*; orbit-periodic
forces average 1–2 orders below it, so the advisory flag accepts a wide
window below each bound.

Two tables: **A (wiring proof)** measures each toggle's sign-free dynamical
effect |case − baseline| — a boolean toggle can only add or omit an Orekit
force, so effect-at-the-predicted-order (and null where predicted null) is
the wiring evidence. **B (agreement vs truth)** shows the signed side: a
removed contribution that opposes the unmodeled along-track floor (ERP +
thermal thrust) can legitimately *improve* the total residual.

Reference-only: not shipped, not in CI, outside ``testpaths``. Runs in the
propygator conda env (starts the JVM, needs orekit-data); cwd-independent.
Evidence appends to the Chunk 0 ``results.txt`` (build-plan convention):

    cd experiments/real-world-validation/lageos
    conda run -n propygator python run_ablations.py >> results.txt

Stdout is ASCII-only (captured under cp1252); progress goes to stderr.
"""

from __future__ import annotations

import math
import sys
import time as _time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_lageos as rl  # noqa: E402  (Chunk 0 LAGEOS-2 constants + DATA_DIR)
from common import OMEGA_EARTH, ric_components, rms as _rms  # noqa: E402
from sp3 import parse_sp3  # noqa: E402

from propygator import (  # noqa: E402
    ForceModelConfig,
    Frame,
    IntegratorConfig,
    SpacecraftConfig,
    SpacecraftGeometry,
    State,
    propagate_numerical,
)

# Physical constants (SI definitions / IERS nominal values, not fitted numbers):
_C_LIGHT = 299792458.0  # m/s (exact)
_SOLAR_CONSTANT = 1361.0  # W/m^2 at 1 AU
_AU = 1.495978707e11  # m
_K2_LOVE = 0.30  # nominal degree-2 Love number (solid-tide scale estimate)

# The Chunk 0 baseline
# (docs/history/build-plan-real-world-validation.md Chunk 0 step 2).
_BASELINE = {
    "drag": False,
    "solid_tides": True,
    "ocean_tides": True,
    "relativity": True,
}

# (case label, ForceModelConfig overrides on top of the baseline, expectation key)
_CASES = [
    ("srp off", {"srp": False}, "srp"),
    ("relativity off", {"relativity": False}, "relativity"),
    ("tides off (solid+ocean)", {"solid_tides": False, "ocean_tides": False}, "tides"),
    (
        "sun+moon third body off",
        {"sun_third_body": False, "moon_third_body": False},
        "sun+moon",
    ),
    ("gravity 20x20", {"gravity_degree": 20, "gravity_order": 20}, "gravity>20"),
    ("gravity 8x8", {"gravity_degree": 8, "gravity_order": 8}, "gravity>8"),
    ("planets third body ON", {"planets_third_body": True}, "planets"),
]


def _body_distance_m(body: object, epoch, eme2000: object) -> float:
    """Earth-center distance of an Orekit CelestialBody at ``epoch``."""
    return float(
        body.getPVCoordinates(epoch.to_orekit(), eme2000).getPosition().getNorm()
    )


def compute_expectations(eph) -> dict[str, dict[str, float]]:
    """Per-force acceleration scales sampled along the truth orbit (pure compute).

    Returns ``{key: {"a": mean acceleration m/s^2, "bound": 1-day free-drift m}}``.
    Everything is evaluated from the actual orbit + the actual EIGEN-6S
    coefficients + the actual DE-ephemeris body distances — no literature
    residual table. Norm-invariant quantities are computed straight in ITRF
    components (with the truth velocity corrected to inertial by omega x r).
    """
    from org.orekit.forces.gravity.potential import GravityFieldFactory

    from propygator.core import bodies

    idx = np.arange(0, len(eph.epochs), 30)  # hourly samples along the week
    pos = eph.positions_m[idx]
    v_in = eph.velocities_ms[idx] + np.cross(OMEGA_EARTH, pos)
    r = np.linalg.norm(pos, axis=1)
    r_mean = float(np.mean(r))

    provider = GravityFieldFactory.getNormalizedProvider(70, 70)
    mu = float(provider.getMu())
    ae = float(provider.getAe())
    g_central = mu / r_mean**2

    # Gravity truncation: RSS degree strength from the real normalized
    # coefficients, a_n ~ (mu/r^2) (n+1) (ae/r)^n * sqrt(sum_m Cnm^2 + Snm^2).
    harmonics = provider.onDate(eph.epochs[0].to_orekit())
    a_deg = {}
    for n in range(2, 71):
        rss = math.sqrt(
            sum(
                float(harmonics.getNormalizedCnm(n, m)) ** 2
                + float(harmonics.getNormalizedSnm(n, m)) ** 2
                for m in range(0, n + 1)
            )
        )
        a_deg[n] = g_central * (n + 1) * (ae / r_mean) ** n * rss

    def trunc(above: int) -> float:
        return math.sqrt(sum(a_deg[n] ** 2 for n in range(above + 1, 71)))

    # Third-body + tide scales from actual ephemeris distances (Sun/Moon sampled
    # hourly; the seven planets at mid-week — their distances barely move in 7 d).
    eme2000 = Frame.EME2000.to_orekit()
    sun, moon = bodies._sun(), bodies._moon()
    gm_sun, gm_moon = float(sun.getGM()), float(moon.getGM())
    d_sun = np.array([_body_distance_m(sun, eph.epochs[i], eme2000) for i in idx])
    d_moon = np.array([_body_distance_m(moon, eph.epochs[i], eme2000) for i in idx])

    a_3b = float(np.mean(2.0 * gm_sun * r / d_sun**3 + 2.0 * gm_moon * r / d_moon**3))
    # Solid-tide scale: the k2-redistributed degree-2 potential of each raising
    # body, |a| ~ 3 k2 GM_b ae^5 / (d^3 r^4); the ablation also removes ocean
    # tides (~10-20% extra on top of this).
    a_tide = float(
        np.mean(
            3.0 * _K2_LOVE * gm_sun * ae**5 / (d_sun**3 * r**4)
            + 3.0 * _K2_LOVE * gm_moon * ae**5 / (d_moon**3 * r**4)
        )
    )

    mid = eph.epochs[len(eph.epochs) // 2]
    a_planets = 0.0
    for accessor in (
        bodies._mercury,
        bodies._venus,
        bodies._mars,
        bodies._jupiter,
        bodies._saturn,
        bodies._uranus,
        bodies._neptune,
    ):
        body = accessor()
        d = _body_distance_m(body, mid, eme2000)
        a_planets += 2.0 * float(body.getGM()) * r_mean / d**3

    # Cannonball SRP at the actual mean Sun distance.
    a_srp = (
        (_SOLAR_CONSTANT / _C_LIGHT)
        * float(np.mean((_AU / d_sun) ** 2))
        * rl.LAGEOS2_CR
        * rl.LAGEOS2_AREA_M2
        / rl.LAGEOS2_MASS_KG
    )

    # Schwarzschild term evaluated on the sampled PV.
    rv = np.einsum("ij,ij->i", pos, v_in)
    v2 = np.einsum("ij,ij->i", v_in, v_in)
    vec = (4.0 * mu / r - v2)[:, None] * pos + 4.0 * rv[:, None] * v_in
    a_rel = float(np.mean(mu / (_C_LIGHT**2 * r**3) * np.linalg.norm(vec, axis=1)))

    day = 86400.0
    out = {}
    for key, a in [
        ("srp", a_srp),
        ("relativity", a_rel),
        ("tides", a_tide),
        ("sun+moon", a_3b),
        ("gravity>20", trunc(20)),
        ("gravity>8", trunc(8)),
        ("planets", a_planets),
    ]:
        out[key] = {"a": a, "ratio": a / g_central, "bound": 0.5 * a * day**2}

    print("[expected orders]  computed along the truth orbit (nothing quoted)")
    print(f"  central gravity at r = {r_mean / 1e3:.0f} km: {g_central:.3e} m/s2")
    print(f"  {'force':<24}{'a (m/s2)':>12}{'a/g':>12}{'1-day bound (m)':>18}")
    for key, e in out.items():
        print(f"  {key:<24}{e['a']:>12.3e}{e['ratio']:>12.3e}{e['bound']:>18.3f}")
    print(
        "  bound = a*t^2/2, a secular upper limit -- orbit-periodic forces\n"
        "  average 1-2 orders below it; a bound << 1 m predicts a null row."
    )
    return out


def main() -> None:
    print()
    print("=" * 74)
    print("Chunk 1 -- LAGEOS-2 ablation matrix: the per-toggle wiring proof")
    print("=" * 74)

    files = sorted(rl.DATA_DIR.glob("*.sp3*"))
    if not files:
        raise SystemExit(f"no SP3 file under {rl.DATA_DIR} (see README.md)")
    eph = parse_sp3(files[0])
    n = len(eph.epochs)
    span_s = eph.epochs[-1].seconds_since(eph.epochs[0])
    t_rel = np.arange(n) * eph.epoch_interval_s
    m_day1 = t_rel <= 86400.0 + 1e-6
    print(
        f"[data] {files[0].name}: {n} epochs, {span_s / 86400.0:.3f} days "
        "(the Chunk 0 arc)"
    )

    state0 = State(
        eph.epochs[0], eph.positions_m[0], eph.velocities_ms[0], Frame.ITRF
    ).to_frame(Frame.EME2000)
    spacecraft = SpacecraftConfig(
        mass_kg=rl.LAGEOS2_MASS_KG,
        geometry=SpacecraftGeometry.sphere(
            area_m2=rl.LAGEOS2_AREA_M2, reflectivity_coefficient=rl.LAGEOS2_CR
        ),
    )

    expect = compute_expectations(eph)

    def run_case(overrides: dict) -> np.ndarray:
        cfg = ForceModelConfig(**{**_BASELINE, **overrides})
        traj = propagate_numerical(
            state0,
            span_s,
            output_step=eph.epoch_interval_s,
            force_models=cfg,
            spacecraft=spacecraft,
            integrator=IntegratorConfig.high_precision(),
        )
        if len(traj) != n:
            raise SystemExit(f"sample count mismatch: {len(traj)} vs {n}")
        return traj.to_frame(Frame.ITRF).positions

    def along_at_7d(diff: np.ndarray) -> float:
        """Signed along-track component of ``diff`` at the final truth epoch."""
        return float(ric_components(diff, eph.positions_m, eph.velocities_ms)[-1, 1])

    t_wall = _time.perf_counter()
    pos_base = run_case({})
    cases = [(label, key, run_case(ov)) for label, ov, key in _CASES]
    t_wall = _time.perf_counter() - t_wall

    d_base = pos_base - eph.positions_m
    base_norm = np.linalg.norm(d_base, axis=1)
    base_d1, base_d7 = _rms(base_norm[m_day1]), _rms(base_norm)

    # Table A -- the wiring proof: |case - baseline| is the toggle's dynamical
    # effect, sign-free and independent of the unmodeled-force floor. A boolean
    # toggle can only add or omit an Orekit force (it cannot distort one), so
    # "effect present at the predicted order / null where predicted null" IS
    # the evidence that the toggle reaches Orekit.
    print(
        f"[ablation matrix A -- wiring proof]  8 x 7-day propagations, "
        f"{t_wall:.0f} s wall"
    )
    print("  effect = |case - baseline| trajectory difference, 3D RMS (m)")
    print(f"  {'case':<26}{'eff d1 rms':>12}{'eff d7 rms':>12}{'bound1d':>12}  flag")
    problems = []
    stats = []
    for label, key, pos_c in cases:
        eff = np.linalg.norm(pos_c - pos_base, axis=1)
        eff_d1, eff_d7 = _rms(eff[m_day1]), _rms(eff)
        bound = expect[key]["bound"]
        if bound < 0.5:  # predicted-null row
            ok = eff_d1 < 0.5
            flag = "null OK" if ok else "REVIEW"
        else:  # predicted-visible: inside (bound/1000, 3*bound) -- see docstring
            ok = (bound / 1000.0) < eff_d1 < (3.0 * bound)
            flag = "OK" if ok else "REVIEW"
        if not ok:
            problems.append(label)
        print(f"  {label:<26}{eff_d1:>12.3f}{eff_d7:>12.3f}{bound:>12.3f}  {flag}")
        stats.append((label, pos_c))

    # Table B -- agreement vs truth: the signed side of the story. A removed
    # force whose contribution opposes the unmodeled along-track floor
    # (ERP + thermal thrust, the Chunk 0 residual) can *improve* the total.
    print("[ablation matrix B -- agreement vs truth]  3D RMS (m); along@7d signed")
    print(
        f"  {'case':<26}{'day1 rms':>10}{'delta':>10}{'day7 rms':>10}"
        f"{'delta':>10}{'along@7d':>10}"
    )
    print(
        f"  {'baseline (Chunk 0)':<26}{base_d1:>10.3f}{'--':>10}{base_d7:>10.3f}"
        f"{'--':>10}{along_at_7d(d_base):>+10.1f}"
    )
    improves = []
    for label, pos_c in stats:
        d_c = pos_c - eph.positions_m
        c_norm = np.linalg.norm(d_c, axis=1)
        d1, d7 = _rms(c_norm[m_day1]), _rms(c_norm)
        if d7 < base_d7 - 0.5:
            improves.append(label)
        print(
            f"  {label:<26}{d1:>10.3f}{d1 - base_d1:>+10.3f}{d7:>10.3f}"
            f"{d7 - base_d7:>+10.3f}{along_at_7d(d_c):>+10.1f}"
        )

    print("[checks]")
    print(
        "  wiring (table A): every effect inside its predicted-order window, "
        f"nulls null: {'PASS' if not problems else 'REVIEW'}"
    )
    if problems:
        for p in problems:
            print(f"  REVIEW -> {p}")
        print(
            "  a misbehaving row = a located wiring bug: Checkpoint A item-3 "
            "exit (normal fix path) before the study resumes."
        )
    if improves:
        print(f"  vs-truth improvements (table B): {', '.join(improves)}")
        print(
            "  reading: those contributions partially oppose the unmodeled\n"
            "  along-track floor (ERP + thermal thrust) over this week -- see the\n"
            "  along@7d signs. The wiring proof is table A; the sign-level\n"
            "  attribution is a findings-doc note, not resolvable from one week."
        )


if __name__ == "__main__":
    main()
