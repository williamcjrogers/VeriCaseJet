"""
Enhanced API routes with AWS services integration
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Dict, Any
import logging

from .security import current_user
from .models import User

logger = logging.getLogger(__name__)

# Create router
aws_router = APIRouter(prefix="/api/v1/aws", tags=["AWS Services"])

# Try to import AWS services
try:
    from .aws_services import get_aws_services
    AWS_AVAILABLE = True
except ImportError:
    AWS_AVAILABLE = False
    logger.warning("AWS services not available - install boto3 and configure credentials")

@aws_router.get("/health")
async def aws_health_check():
    """Check AWS services health"""
    if not AWS_AVAILABLE:
        return {
            "status": "unavailable",
            "message": "AWS services not configured",
            "services": {}
        }
    
    try:
        aws = get_aws_services()
        health = await aws.check_service_health()
        return health
    except Exception as e:
        logger.error(f"AWS health check failed: {e}")
        return {
            "status": "error",
            "message": str(e),
            "services": {}
        }

@aws_router.get("/semantic-search")
async def semantic_search(
    q: str = Query(..., description="Search query"),
    limit: int = Query(10, ge=1, le=50),
    user: User = Depends(current_user)
):
    """Semantic search using Bedrock Knowledge Base"""
    if not AWS_AVAILABLE:
        raise HTTPException(503, "AWS services not available")
    
    try:
        aws = get_aws_services()
        results = await aws.query_knowledge_base(q)
        
        # Limit results
        limited_results = results[:limit] if results else []
        
        return {
            "query": q,
            "results": limited_results,
            "count": len(limited_results),
            "total_available": len(results) if results else 0
        }
    except Exception as e:
        logger.error(f"Semantic search failed: {e}")
        raise HTTPException(500, f"Search failed: {str(e)}")

@aws_router.post("/analyze-document")
async def analyze_document(
    payload: Dict[str, Any],
    user: User = Depends(current_user)
):
    """Analyze document with AWS AI services"""
    if not AWS_AVAILABLE:
        raise HTTPException(503, "AWS services not available")
    
    s3_bucket = payload.get("s3_bucket")
    s3_key = payload.get("s3_key")
    
    if not s3_bucket or not s3_key:
        raise HTTPException(400, "s3_bucket and s3_key required")
    
    try:
        aws = get_aws_services()
        
        # Extract document data with Textract
        textract_data = await aws.extract_document_data(s3_bucket, s3_key)
        
        # Analyze with Comprehend
        text = textract_data.get('text', '')
        comprehend_analysis = await aws.analyze_document_entities(text)
        
        return {
            "message": "Audio transcription started",
            "evidence_id": evidence_id,
            "estimated_time": "5-15 minutes",
        }
    except Exception as e:
        logger.error(f"Audio transcription failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@aws_router.get("/services/status")
async def get_aws_services_status() -> dict[str, str | dict[str, dict[str, bool | str]]]:
    """Get status of all AWS services integration"""
    try:
        now = datetime.now(timezone.utc).isoformat()
        status: dict[str, dict[str, bool | str]] = {
            "textract": {"available": True, "last_check": now},
            "comprehend": {"available": True, "last_check": now},
            "bedrock": {"available": True, "last_check": now},
            "rekognition": {"available": True, "last_check": now},
            "transcribe": {"available": True, "last_check": now},
            "opensearch": {"available": True, "last_check": now},
            "eventbridge": {"available": True, "last_check": now},
            "stepfunctions": {"available": True, "last_check": now},
            "quicksight": {"available": True, "last_check": now},
            "macie": {"available": True, "last_check": now},
        }
    
    try:
        aws = get_aws_services()
        status = await aws.check_service_health()
        return {
            "aws_available": True,
            **status
        }
    except Exception as e:
        logger.error(f"Services status check failed: {e}")
        return {
            "aws_available": True,
            "status": "error",
            "message": str(e)
        }
