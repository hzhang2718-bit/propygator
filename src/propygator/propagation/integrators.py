"""``IntegratorConfig`` — numerical-integrator selection and tolerances.

A frozen, pure-Python dataclass on the "safe before init" surface (architecture
§10): construction validates the numeric controls (step bounds, tolerances) but
never touches Orekit. The ``type`` string ("DOP853" | "DormandPrince54" |
"ClassicalRK4") *names* an integrator that is resolved against Orekit at the top of
``propagate_numerical`` (Feature 1.1, build-plan chunk 7), which also enforces the
type-dependent rule that ``ClassicalRK4`` requires ``fixed_step_s``. Neither the
name resolution nor that coupling is checked here — there is no JVM, and keeping
every ``type``-dependent check at one propagate-time locus avoids splitting the
rule. Construction validates only that ``fixed_step_s``, *when supplied*, is
finite and positive.

Three presets (features.md §1.1): :meth:`default` (DOP853, high-fidelity general
purpose), :meth:`fast` (DormandPrince54, quick-look), :meth:`high_precision`
(DOP853, tight tolerances for reference trajectories).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class IntegratorConfig:
    """Numerical-integrator type and its adaptive-step / tolerance controls.

    Tolerances are interpreted as meters of position via Orekit's
    ``OrbitType.CARTESIAN`` tolerance computation (applied in
    ``propagate_numerical``); the propagator builds the per-equation ``[abs, rel]``
    arrays from these two scalars. ``min_step_s`` / ``max_step_s`` bound the
    adaptive controller (the wide defaults mean a healthy propagation never bumps
    either). Immutable; numeric validation runs in :meth:`__post_init__`.
    """

    type: str = "DOP853"  # "DOP853" | "DormandPrince54" | "ClassicalRK4"
    min_step_s: float = 1e-3
    max_step_s: float = 1000.0
    abs_tolerance_m: float = 1e-3
    rel_tolerance: float = 1e-10
    fixed_step_s: float | None = None  # ClassicalRK4 only (checked at propagate time)

    def __post_init__(self) -> None:
        for name, val in (
            ("min_step_s", self.min_step_s),
            ("max_step_s", self.max_step_s),
            ("abs_tolerance_m", self.abs_tolerance_m),
            ("rel_tolerance", self.rel_tolerance),
        ):
            if not math.isfinite(val) or val <= 0.0:
                raise ValueError(f"{name} must be finite and > 0, got {val!r}")
        if self.min_step_s > self.max_step_s:
            raise ValueError(
                f"min_step_s must be <= max_step_s; got min_step_s="
                f"{self.min_step_s!r} > max_step_s={self.max_step_s!r}"
            )
        # fixed_step_s is optional here (only ClassicalRK4 needs it, enforced at
        # propagate time); validate it only if the user supplied a value.
        if self.fixed_step_s is not None and (
            not math.isfinite(self.fixed_step_s) or self.fixed_step_s <= 0.0
        ):
            raise ValueError(
                f"fixed_step_s, when given, must be finite and > 0, got "
                f"{self.fixed_step_s!r}"
            )

    @classmethod
    def default(cls) -> "IntegratorConfig":
        """High-fidelity general-purpose: DOP853, abs 1e-3 m, rel 1e-10.

        Identical to the bare ``IntegratorConfig()`` defaults.
        """
        return cls()

    @classmethod
    def fast(cls) -> "IntegratorConfig":
        """Quick-look / interactive: DormandPrince54, abs 10 m, rel 1e-7."""
        return cls(type="DormandPrince54", abs_tolerance_m=10.0, rel_tolerance=1e-7)

    @classmethod
    def high_precision(cls) -> "IntegratorConfig":
        """Precision work / reference trajectories: DOP853, abs 1e-5 m, rel 1e-12.

        The tight ``rel_tolerance`` is demanding: on a stiff/ill-posed case it can
        drive the adaptive step below ``min_step_s``, which raises
        ``NumericalPropagationError`` (Hipparchus stops rather than continuing at an
        oversized step). Flagged for verification against the round-trip tests
        (features.md §1.1).
        """
        return cls(type="DOP853", abs_tolerance_m=1e-5, rel_tolerance=1e-12)
