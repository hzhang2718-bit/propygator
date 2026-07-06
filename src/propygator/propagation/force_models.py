"""``ForceModelConfig`` — which perturbations act, and which model each uses.

A frozen, pure-Python dataclass on the "safe before init" surface (architecture
§10): construction and validation never touch Orekit or start the JVM. It carries
*which* perturbations are enabled and *which named model* each uses, but not the
spacecraft's mass / area / coefficients (those live in ``SpacecraftConfig``) — the
split keeps the two concerns orthogonal (features.md §1.1).

**String-named models are resolved later.** ``gravity_field`` and
``atmosphere_model`` are stored verbatim and resolved against orekit-data at the
top of ``propagate_numerical`` (Feature 1.1, build-plan chunks 7–8), raising
``ValueError`` with a known-name list on a miss — they cannot be validated here
without a running JVM. ``__post_init__`` checks only the integer gravity controls,
which are pure-Python.

**The ``force_models`` metadata grammar** (features.md §1.1) lives here too: a
deterministic, greppable list of tokens in a fixed order, so the same forces yield
byte-identical metadata. The serializer is a standalone pure function
(:func:`_serialize_force_models`) driven by explicit force *facts*, not by reading
a config — ``propagate_numerical`` (chunks 7–9) calls it with the forces it
actually wired into the propagator, so the metadata never claims a force that is
not acting. :meth:`ForceModelConfig._metadata_tokens` is the thin convenience
wrapper that passes the config's own fields.
"""

from __future__ import annotations

from dataclasses import dataclass


def _serialize_force_models(
    *,
    gravity_field: str,
    gravity_degree: int,
    gravity_order: int,
    sun_third_body: bool,
    moon_third_body: bool,
    planets_third_body: bool,
    drag: bool,
    atmosphere_model: str,
    srp: bool,
    solid_tides: bool,
    ocean_tides: bool,
    relativity: bool,
) -> list[str]:
    """Build the deterministic ``force_models`` metadata token list.

    Fixed token order (features.md §1.1): gravity, ``third_body:sun``,
    ``third_body:moon``, ``third_body:planets``, drag, ``srp``, ``tides:solid``,
    ``tides:ocean``, ``relativity``. A disabled force emits no token; gravity is
    always present (point mass is ``gravity:<field>:0x0``). ``third_body:planets``
    is a single lumped token — its meaning (the pinned seven-planet set) lives in
    features.md §1.1 (general-upgrades-1.md "Planetary Third-Body & Earth
    Radiation Pressure").

    Driven by explicit facts rather than a :class:`ForceModelConfig` so
    ``propagate_numerical`` can serialize the forces it *actually wired* into the
    propagator (chunks 7–9) — which, during the incremental builds, is not the same
    as the config booleans. The metadata must never claim a force that is not
    acting, so the propagator drives this from what it added, not from the config.
    """
    tokens = [f"gravity:{gravity_field}:{gravity_degree}x{gravity_order}"]
    if sun_third_body:
        tokens.append("third_body:sun")
    if moon_third_body:
        tokens.append("third_body:moon")
    if planets_third_body:
        tokens.append("third_body:planets")
    if drag:
        tokens.append(f"drag:{atmosphere_model}")
    if srp:
        tokens.append("srp")
    if solid_tides:
        tokens.append("tides:solid")
    if ocean_tides:
        tokens.append("tides:ocean")
    if relativity:
        tokens.append("relativity")
    return tokens


@dataclass(frozen=True)
class ForceModelConfig:
    """Which perturbations act on the spacecraft, and which model each uses.

    Each field is independently togglable; the three presets
    (:meth:`leo_default`, :meth:`geo_default`, :meth:`keplerian`) are
    good-general-purpose starting points, not "best possible physics" — users flip
    individual booleans from there. Immutable; field validation runs in
    :meth:`__post_init__` (no Orekit calls). See the module docstring for why the
    ``gravity_field`` / ``atmosphere_model`` strings are validated later.

    ``planets_third_body`` lumps third-body gravity from the seven planets other
    than Earth (Mercury–Neptune, off the DE ephemeris already in orekit-data).
    Planetary accelerations on an Earth orbiter are ~1e-10–1e-13 of central
    gravity (Venus and Jupiter dominate): a completeness option for
    high-precision or long-arc work — it will not visibly move a LEO trajectory.
    """

    gravity_degree: int = 70
    gravity_order: int = 70
    gravity_field: str = "EIGEN-6S"
    sun_third_body: bool = True
    moon_third_body: bool = True
    planets_third_body: bool = False
    drag: bool = True
    atmosphere_model: str = "NRLMSISE-00"  # | "Harris-Priester" | "DTM-2000"
    srp: bool = True
    solid_tides: bool = False
    ocean_tides: bool = False
    relativity: bool = False

    def __post_init__(self) -> None:
        deg = self.gravity_degree
        order = self.gravity_order
        # Spherical-harmonics constraint, checkable without a JVM: a non-negative
        # degree and an order in [0, degree]. degree == order == 0 is the point-mass
        # (Keplerian) case. The named gravity_field / atmosphere_model strings are
        # NOT validated here — they resolve against orekit-data in
        # propagate_numerical (chunks 7–8).
        if deg < 0:
            raise ValueError(f"gravity_degree must be >= 0, got {deg!r}")
        if order < 0:
            raise ValueError(f"gravity_order must be >= 0, got {order!r}")
        if order > deg:
            raise ValueError(
                f"gravity_order must be <= gravity_degree; got gravity_order="
                f"{order!r} > gravity_degree={deg!r}"
            )

    @classmethod
    def leo_default(cls) -> "ForceModelConfig":
        """LEO preset: 70×70 gravity, sun+moon, drag (NRLMSISE-00), SRP.

        Gravity- and drag-dominated. Identical to the bare ``ForceModelConfig()``
        defaults — LEO is the default operating point.
        """
        return cls()

    @classmethod
    def geo_default(cls) -> "ForceModelConfig":
        """GEO preset: 12×12 gravity, sun+moon, SRP; drag off.

        Gravity-degree-limited with negligible drag at GEO altitude; SRP is a
        leading perturbation.
        """
        return cls(gravity_degree=12, gravity_order=12, drag=False)

    @classmethod
    def keplerian(cls) -> "ForceModelConfig":
        """Two-body preset: point-mass gravity only, every perturbation off.

        The bit-exact analytical comparison case for tests (features.md §11).
        """
        return cls(
            gravity_degree=0,
            gravity_order=0,
            sun_third_body=False,
            moon_third_body=False,
            drag=False,
            srp=False,
        )

    def _metadata_tokens(self) -> list[str]:
        """This config's ``force_models`` metadata tokens (every enabled force).

        A convenience wrapper over :func:`_serialize_force_models` passing this
        config's own fields. ``propagate_numerical`` does NOT use this — it calls
        the module function with the forces it actually wired into the propagator
        (chunks 7–9), so the recorded metadata tracks the real force model.
        """
        return _serialize_force_models(
            gravity_field=self.gravity_field,
            gravity_degree=self.gravity_degree,
            gravity_order=self.gravity_order,
            sun_third_body=self.sun_third_body,
            moon_third_body=self.moon_third_body,
            planets_third_body=self.planets_third_body,
            drag=self.drag,
            atmosphere_model=self.atmosphere_model,
            srp=self.srp,
            solid_tides=self.solid_tides,
            ocean_tides=self.ocean_tides,
            relativity=self.relativity,
        )
