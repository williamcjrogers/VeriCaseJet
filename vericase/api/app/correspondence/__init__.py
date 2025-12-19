# pyright: reportCallInDefaultInitializer=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""Correspondence package.

This package holds the PST/correspondence API routers and services.

Note: There is also an `app/correspondence.py` compatibility module that re-exports
routers for legacy imports.
"""

from .routes import router

__all__ = ["router"]
