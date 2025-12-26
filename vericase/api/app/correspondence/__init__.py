# pyright: reportCallInDefaultInitializer=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""Correspondence package.

This package holds the PST/correspondence API routers and services.

Note: There is also an `app/correspondence.py` compatibility module that re-exports
routers for legacy imports.
"""

from .utils import (
    _parse_pst_status_filter,
    build_correspondence_visibility_filter,
    compute_correspondence_exclusion,
)

# `router` pulls in the full FastAPI routing stack (and downstream deps like
# OpenSearch client wiring). Keep it as a best-effort import so callers can
# import lightweight helpers from this package without requiring all optional
# runtime services.
try:
    from .routes import router  # type: ignore
except ImportError:  # pragma: no cover
    router = None  # type: ignore

__all__ = [
    "router",
    "_parse_pst_status_filter",
    "build_correspondence_visibility_filter",
    "compute_correspondence_exclusion",
]
