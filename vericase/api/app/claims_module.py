"""
Contentious Matters and Heads of Claim Module - Aggregator

Thin router that includes all claims sub-modules under the
/api/claims prefix.  Each sub-module defines its own endpoints
with relative paths (e.g. "/matters", "/heads-of-claim/{id}").

Sub-modules:
  claims_matters  - Contentious Matter CRUD + statistics
  claims_heads    - Heads of Claim CRUD + team members + evidence comments
  claims_links    - Item Links + Comments
  claims_ai       - AI collaboration, reactions, pinning, read/unread, notifications
"""

from fastapi import APIRouter

from .claims_matters import router as matters_router
from .claims_heads import router as heads_router
from .claims_links import router as links_router
from .claims_ai import router as ai_router

router = APIRouter(prefix="/api/claims", tags=["claims"])

router.include_router(matters_router)
router.include_router(heads_router)
router.include_router(links_router)
router.include_router(ai_router)
