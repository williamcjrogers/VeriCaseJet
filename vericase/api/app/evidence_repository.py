"""app.evidence_repository compatibility module.

The actual Evidence Repository router is defined in `app/evidence/routes.py`.
This module exists because `app/main.py` imports `router` from
`app.evidence_repository`.
"""

from .evidence.routes import router

__all__ = ["router"]
