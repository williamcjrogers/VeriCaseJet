# pyright: reportCallInDefaultInitializer=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""app.correspondence compatibility module.

The real Correspondence API lives under `app/correspondence/`.
`app/main.py` imports routers from `app.correspondence`, so this module must
re-export them.
"""

# Re-export the package router only.
from .correspondence.routes import router

__all__ = ["router"]
