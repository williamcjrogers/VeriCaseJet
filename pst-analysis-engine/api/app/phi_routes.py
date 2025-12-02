"""Phi-4 API routes for VeriCase"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import json
import logging

from .phi_client import phi_client
from .auth import get_current_user_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/phi", tags=["Phi-4 AI"])


class ChatRequest(BaseModel):
    message: str
    context: Optional[str] = None
    stream: bool = False


class DocumentAnalysisRequest(BaseModel):
    content: str
    analysis_type: str = "summary"  # summary, entities, legal_analysis, timeline


class ChatResponse(BaseModel):
    response: str
    model: str = "phi4"
    available: bool


@router.get("/status")
async def phi_status():
    """Check Phi-4 service status"""
    available = await phi_client.is_available()
    return {
        "service": "phi4",
        "available": available,
        "endpoint": phi_client.endpoint if available else None,
        "model": phi_client.model if available else None,
    }


@router.post("/chat", response_model=ChatResponse)
async def chat_with_phi(
    request: ChatRequest, current_user_email: str = Depends(get_current_user_email)
):
    """Chat with Phi-4 model"""
    try:
        if request.stream:
            # Return streaming response
            async def generate():
                yield "data: " + json.dumps({"type": "start", "model": "phi4"}) + "\n\n"
                try:
                    async for chunk in phi_client.stream_chat(
                        request.message, request.context
                    ):
                        yield "data: " + json.dumps(
                            {"type": "chunk", "content": chunk}
                        ) + "\n\n"
                    yield "data: " + json.dumps({"type": "end"}) + "\n\n"
                except Exception as e:
                    yield "data: " + json.dumps(
                        {"type": "error", "error": str(e)}
                    ) + "\n\n"

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        else:
            # Regular response
            response = await phi_client.chat(request.message, request.context)
            return ChatResponse(response=response, model="phi4", available=True)

    except Exception as e:
        logger.error(f"Phi-4 chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze")
async def analyze_document(
    request: DocumentAnalysisRequest,
    current_user_email: str = Depends(get_current_user_email),
):
    """Analyze document with Phi-4"""
    try:
        result = await phi_client.analyze_document(
            request.content, request.analysis_type
        )
        return result

    except Exception as e:
        logger.error(f"Phi-4 analysis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/legal-insight")
async def legal_insight(
    request: ChatRequest, current_user_email: str = Depends(get_current_user_email)
):
    """Get legal insights using Phi-4"""
    legal_prompt = f"""As a legal AI assistant, analyze this query and provide insights:

Query: {request.message}

Context: {request.context or 'No additional context provided'}

Please provide:
1. Key legal considerations
2. Potential risks or issues
3. Recommended actions
4. Relevant legal principles

Response:"""

    try:
        response = await phi_client.chat(legal_prompt)
        return {
            "insight": response,
            "model": "phi4",
            "query": request.message,
            "type": "legal_analysis",
        }

    except Exception as e:
        logger.error(f"Phi-4 legal insight error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models")
async def available_models():
    """List available Phi models"""
    try:
        available = await phi_client.is_available()
        if available:
            return {
                "models": [
                    {
                        "name": "phi4:latest",
                        "description": "Microsoft Phi-4 - Fast, efficient reasoning",
                        "capabilities": ["chat", "analysis", "reasoning", "code"],
                        "cost": "free (self-hosted)",
                        "speed": "fast",
                    }
                ],
                "default": "phi4:latest",
            }
        else:
            return {"models": [], "error": "Phi-4 service not available"}

    except Exception as e:
        logger.error(f"Error listing Phi models: {e}")
        raise HTTPException(status_code=500, detail=str(e))
