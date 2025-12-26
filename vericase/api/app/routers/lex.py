from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..integrations.lex_api import LEX_OPERATIONS, LexAPIError, lex_client
from ..models import User
from ..security import get_current_user

router = APIRouter(prefix="/api/lex", tags=["lex"])


class LexOperationRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] | None = None


async def _call_lex(
    operation: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> Any:
    try:
        return await lex_client.request(operation, params=params, json_body=body)
    except LexAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/operations")
async def list_lex_operations(
    current_user: User = Depends(get_current_user),
):
    return {"operations": sorted(LEX_OPERATIONS)}


@router.get("/health")
async def lex_health(
    current_user: User = Depends(get_current_user),
):
    return await _call_lex("health_check_healthcheck_get")


@router.get("/stats")
async def lex_stats(
    current_user: User = Depends(get_current_user),
):
    return await _call_lex("get_live_stats_api_stats_get")


@router.post("/operations/{operation}")
async def call_lex_operation(
    operation: str,
    request: LexOperationRequest,
    current_user: User = Depends(get_current_user),
):
    if operation not in LEX_OPERATIONS:
        raise HTTPException(status_code=404, detail="Unsupported Lex operation")
    return await _call_lex(
        operation,
        params=request.params or None,
        body=request.body,
    )
