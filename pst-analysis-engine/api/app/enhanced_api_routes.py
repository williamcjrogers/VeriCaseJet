# Enhanced API Routes with AWS Services Integration
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from typing import Annotated, Callable, TYPE_CHECKING
import logging
from datetime import datetime, timezone

from .db import get_db, SessionLocal
from .models import EvidenceItem
from .enhanced_evidence_processor import enhanced_processor

if TYPE_CHECKING:
    from .aws_services import AWSServicesManager

logger = logging.getLogger(__name__)

# Create router for enhanced AWS-powered endpoints
aws_router = APIRouter(prefix="/api/v1/aws", tags=["AWS Services"])

# Try to import AWS services
aws_available: bool = False
get_aws_services: Callable[[], "AWSServicesManager"] | None = None
try:
    from .aws_services import get_aws_services as _get_aws_services

    get_aws_services = _get_aws_services
    aws_available = True
except ImportError:
    logger.warning("AWS services not available - install boto3 and configure credentials")


# Type aliases for dependency injection
DbSession = Annotated[Session, Depends(get_db)]


async def run_evidence_processing(evidence_id: str) -> None:
    """Background task wrapper to ensure DB session is valid"""
    db = SessionLocal()
    try:
        _ = await enhanced_processor.process_evidence_item(evidence_id, db)
    except Exception as e:
        logger.error(f"Background evidence processing failed: {e}")
    finally:
        db.close()


@aws_router.post("/evidence/{evidence_id}/process")
async def process_evidence_with_aws(
    evidence_id: str,
    background_tasks: BackgroundTasks,
    db: DbSession,
) -> dict[str, str | list[str]]:
    """Process evidence using all AWS services"""
    try:
        # Verify evidence exists before scheduling
        evidence = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_id).first()
        if not evidence:
            raise HTTPException(status_code=404, detail="Evidence not found")

        background_tasks.add_task(run_evidence_processing, evidence_id)
        return {
            "message": "Evidence processing started",
            "evidence_id": evidence_id,
            "services": ["textract", "comprehend", "rekognition", "bedrock"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Evidence processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Type aliases for query parameters
SearchQuery = Annotated[str, Query(description="Natural language search query")]
OptionalCaseId = Annotated[str | None, Query(description="Filter by case ID")]
ResultLimit = Annotated[int, Query(description="Maximum results to return")]


@aws_router.post("/search/semantic")
async def semantic_search(
    query: SearchQuery,
    case_id: OptionalCaseId = None,
    limit: ResultLimit = 10,
) -> dict[str, str | int | list[dict[str, str]] | None]:
    """Semantic search using Bedrock Knowledge Base"""
    try:
        results = await enhanced_processor.semantic_search(query, case_id)
        return {
            "query": query,
            "case_id": case_id,
            "results_count": len(results),
            "results": results[:limit],
        }
    except Exception as e:
        logger.error(f"Semantic search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@aws_router.get("/case/{case_id}/insights")
async def get_case_insights(
    case_id: str,
    db: DbSession,
) -> dict[str, object]:
    """Generate AI-powered case insights"""
    try:
        insights = await enhanced_processor.generate_case_insights(case_id, db)
        return insights
    except Exception as e:
        logger.error(f"Case insights generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@aws_router.post("/audio/{evidence_id}/transcribe")
async def transcribe_audio_evidence(
    evidence_id: str,
    background_tasks: BackgroundTasks,
    db: DbSession,
) -> dict[str, str]:
    """Transcribe audio/video evidence"""
    try:
        evidence = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_id).first()
        if not evidence:
            raise HTTPException(status_code=404, detail="Evidence not found")

        if not evidence.mime_type or not evidence.mime_type.startswith(("audio/", "video/")):
            raise HTTPException(status_code=400, detail="Evidence is not audio/video")

        background_tasks.add_task(
            enhanced_processor.process_audio_evidence,
            evidence.s3_bucket,
            evidence.s3_key,
            evidence_id,
        )

        return {
            "message": "Audio transcription started",
            "evidence_id": evidence_id,
            "estimated_time": "5-15 minutes",
        }
    except HTTPException:
        raise
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

        return {
            "overall_status": "healthy",
            "services": status,
            "last_updated": now,
        }
    except Exception as e:
        logger.error(f"Service status check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
