"""propygator-specific exception types.

Defined in ``core/`` (the innermost layer) so every subpackage can raise and
catch them without violating the inward dependency rule (architecture §7), and
re-exported from the top-level package namespace for user convenience.
"""

from __future__ import annotations


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


class PropagationError(PropygatorError):
    """Raised when a numerical propagation fails inside Orekit.

    Wraps the underlying Orekit/Hipparchus failure — most often the integrator
    failing to converge (the adaptive step driven down against
    ``IntegratorConfig.min_step_s``) — and carries the Java exception's *message*
    as a string. No raw Java stack trace surfaces to the caller (the same
    principle as :class:`OrekitDataMissingError`; architecture §3, features.md
    §1.1). Input-validation problems (non-inertial frame, bad ``duration`` /
    ``output_step``, unresolvable config strings) raise ``ValueError`` *before*
    integration starts and are not wrapped in this type.
    """
