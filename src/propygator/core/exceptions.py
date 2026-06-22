"""propygator-specific exception types.

Defined in ``core/`` (the innermost layer) so every subpackage can raise and
catch them without violating the inward dependency rule (architecture §7), and
re-exported from the top-level package namespace for user convenience.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only; importing Trajectory at runtime would invert the inward dependency
    # rule (states.py is an outer layer). Under ``from __future__ import annotations``
    # the attribute annotation below is a string, so no runtime import is needed.
    from .states import Trajectory


class PropygatorError(Exception):
    """Base class for all errors propygator raises deliberately.

    Catching this catches every library-intentional error, as distinct from
    errors leaking up from Orekit/JPype or the standard library.
    """


class OrekitDataMissingError(PropygatorError):
    """Raised when the orekit-data directory cannot be resolved.

    The message carries the download URL, the search order that was tried, and
    copy-paste-ready remedies. The condition is detected before any Orekit class
    touches the filesystem, so users never see a raw Java stack trace for
    missing data (architecture §3).
    """


class JVMAlreadyStartedError(PropygatorError):
    """Raised when :func:`propygator.init` is asked to start the JVM with
    arguments that differ from those of the already-running JVM.

    JPype starts exactly one JVM per process and cannot reconfigure it once
    started, so a second ``init()`` with different ``vmargs`` cannot be honored.
    Matching args (or no args) no-op instead of raising (architecture §10).
    """


class TLEFetchError(PropygatorError):
    """Raised when fetching a TLE from a remote source (CelesTrak) fails.

    Wraps the underlying transport failure — no route / DNS failure / connection
    refused / timeout (``requests`` ``ConnectionError`` / ``Timeout``) or an HTTP
    error status (``raise_for_status``) — as a clean, actionable message string
    rather than letting ``requests``' deep urllib3 traceback surface (architecture
    §3, the same principle as :class:`OrekitDataMissingError`). The message names the
    NORAD id and the offline escape hatch — build the TLE directly from saved lines
    via :meth:`TLE.from_strings` — and the originating ``requests`` traceback is
    suppressed (``raise ... from None``).

    Not raised for a *successful* fetch that simply returns no object for the
    requested id, a malformed response body, or an unknown ``source`` — those are
    not-found / input conditions and raise ``ValueError`` instead.
    """


class PropagationError(PropygatorError):
    """Base class for a propagation that fails inside Orekit.

    Raised (via a concrete subclass) when a propagator cannot complete — numerical
    integration giving up, or SGP4/SDP4 leaving its validity envelope. Catching
    ``PropagationError`` catches *any* propagation failure regardless of which
    propagator produced it; catch a subclass to single one out. Either way the
    underlying Orekit/Hipparchus failure is carried as a *message string* only — no
    raw Java stack trace surfaces (the same principle as
    :class:`OrekitDataMissingError`; architecture §3). Input-validation problems
    (non-inertial frame, bad ``duration`` / ``output_step``, unresolvable config
    strings) raise ``ValueError`` *before* propagation starts and are not wrapped in
    this type.
    """


class NumericalPropagationError(PropagationError):
    """Raised when :func:`propagate_numerical` fails inside Orekit.

    Wraps the underlying Orekit/Hipparchus failure — most often the integrator
    failing to converge (the adaptive step driven down against
    ``IntegratorConfig.min_step_s``, surfacing as Hipparchus' "minimal step size
    reached"). Carries the Java message as a string; no raw trace (architecture §3,
    features.md §1.1).

    When the failure leaves usable steps behind, :attr:`partial_trajectory` carries
    the :class:`~propygator.core.states.Trajectory` recovered up to the failure (the
    drag-validity addendum §6.6 "may carry the partial Trajectory" allowance, for
    advanced recovery). It is ``None`` when no usable steps were generated — and a
    drag-driven decay is *not* re-raised at all: it stops and reports
    ``termination_reason="reentry"`` (a partial ``Trajectory`` returned normally).
    """

    #: Partial trajectory recovered up to a non-re-entry failure, or ``None`` if no
    #: usable steps were generated. Set by ``propagate_numerical`` before re-raising.
    partial_trajectory: "Trajectory | None" = None


class TLEPropagationError(PropagationError):
    """Raised when :func:`propagate_tle` (SGP4/SDP4) fails inside Orekit.

    Wraps the underlying Orekit failure — typically the analytic model leaving its
    validity envelope as an orbit decays (Orekit's
    ``TOO_LARGE_ECCENTRICITY_FOR_PROPAGATION_MODEL`` symptom, a sub-surface
    semi-major axis, or an out-of-range eccentricity), carried as a message string
    only (architecture §3). Unlike :class:`NumericalPropagationError` there is
    **no** ``partial_trajectory`` attribute: SGP4 is least reliable precisely as it
    approaches decay, so 1.3 does not stop-and-report a partial — a decay raises
    cleanly rather than implying an accuracy that is not there (features.md §1.3).
    """
