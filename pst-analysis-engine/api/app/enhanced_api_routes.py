# Enhanced API Routes with AWS Services Integration
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
import logging

from .db import get_db
from .models import EvidenceItem
from .enhanced_evidence_processor import enhanced_processor
from .aws_services import get_aws_services
from .config import settings

logger = logging.getLogger(__name__)

# Create router for enhanced AWS-powered endpoints
aws_router = APIRouter(prefix="/api/v1/aws", tags=["AWS Services"])


@aws_router.post("/evidence/{evidence_id}/process")
async def process_evidence_with_aws(
    evidence_id: str,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)]
):
    """Process evidence using all AWS services"""
    try:
        background_tasks.add_task(enhanced_processor.process_evidence_item, evidence_id, db)
        return {
            "message": "Evidence processing started",
            "evidence_id": evidence_id,
            "services": ["textract", "comprehend", "rekognition", "bedrock"]
        }
    except Exception as e:
        logger.error(f"Evidence processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@aws_router.post("/search/semantic")
async def semantic_search(
    query: Annotated[str, Query(description="Natural language search query")],
    case_id: Annotated[str | None, Query(description="Filter by case ID")] = None,
    limit: Annotated[int, Query(description="Maximum results to return")] = 10
):
    """Semantic search using Bedrock Knowledge Base"""
    try:
        results = await enhanced_processor.semantic_search(query, case_id)
        return {
            "query": query,
            "case_id": case_id,
            "results_count": len(results),
            "results": results[:limit]
        }
    except Exception as e:
        logger.error(f"Semantic search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@aws_router.get("/case/{case_id}/insights")
async def get_case_insights(
    case_id: str,
    db: Annotated[Session, Depends(get_db)]
):
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
    db: Annotated[Session, Depends(get_db)]
):
    """Transcribe audio/video evidence"""
    try:
        evidence = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_id).first()
        if not evidence:
            raise HTTPException(status_code=404, detail="Evidence not found")
        
        if not evidence.mime_type or not evidence.mime_type.startswith(('audio/', 'video/')):
            raise HTTPException(status_code=400, detail="Evidence is not audio/video")
        
        background_tasks.add_task(
            enhanced_processor.process_audio_evidence,
            evidence.s3_bucket, evidence.s3_key, evidence_id
        )
        
        return {
            "message": "Audio transcription started",
            "evidence_id": evidence_id,
            "estimated_time": "5-15 minutes"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Audio transcription failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@aws_router.get("/services/status")
async def get_aws_services_status():
    """Get real-time status of all AWS services integration"""
    try:
        aws_svc = get_aws_services()
        health_status = await aws_svc.check_service_health()
        return health_status
    except Exception as e:
        logger.error(f"Service status check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@aws_router.post("/image/{evidence_id}/analyze")
async def analyze_image_evidence(
    evidence_id: str,
    db: Annotated[Session, Depends(get_db)]
):
    """Analyze image evidence using Rekognition"""
    try:
        evidence = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_id).first()
        if not evidence:
            raise HTTPException(status_code=404, detail="Evidence not found")
        
        if not evidence.mime_type or not evidence.mime_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="Evidence is not an image")
        
        aws_svc = get_aws_services()
        analysis = await aws_svc.analyze_construction_image(
            evidence.s3_bucket,
            evidence.s3_key
        )
        
        return {
            "evidence_id": evidence_id,
            "analysis": analysis,
            "services_used": ["rekognition"]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Image analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@aws_router.post("/search/rag")
async def rag_search(
    query: Annotated[str, Query(description="Natural language question")],
    case_id: Annotated[str | None, Query(description="Filter by case ID")] = None
):
    """
    Retrieval Augmented Generation search.
    Queries Knowledge Base and generates AI response with citations.
    """
    try:
        aws_svc = get_aws_services()
        result = await aws_svc.retrieve_and_generate(query)
        
        return {
            "query": query,
            "case_id": case_id,
            "response": result.get('response', ''),
            "citations": result.get('citations', []),
            "session_id": result.get('session_id')
        }
    except Exception as e:
        logger.error(f"RAG search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@aws_router.post("/workflow/start")
async def start_evidence_workflow(
    evidence_id: str,
    s3_bucket: str,
    s3_key: str
):
    """Start Step Functions evidence processing workflow"""
    try:
        aws_svc = get_aws_services()
        result = await aws_svc.start_processing_workflow({
            'evidence_id': evidence_id,
            's3_bucket': s3_bucket,
            's3_key': s3_key
        })
        
        if 'error' in result:
            raise HTTPException(status_code=500, detail=result['error'])
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Workflow start failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@aws_router.get("/workflow/{execution_arn}/status")
async def get_workflow_status(execution_arn: str):
    """Get status of a Step Functions workflow execution"""
    try:
        aws_svc = get_aws_services()
        result = await aws_svc.get_workflow_status(execution_arn)
        
        if 'error' in result:
            raise HTTPException(status_code=500, detail=result['error'])
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Workflow status check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@aws_router.post("/knowledge-base/ingest")
async def trigger_kb_ingestion():
    """Trigger Bedrock Knowledge Base ingestion job"""
    try:
        aws_svc = get_aws_services()
        result = await aws_svc.ingest_to_knowledge_base()
        
        if 'error' in result:
            raise HTTPException(status_code=500, detail=result['error'])
        
        return {
            "message": "Ingestion job started",
            **result
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"KB ingestion trigger failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@aws_router.get("/transcription/{job_name}/status")
async def get_transcription_status(job_name: str):
    """Get status of a transcription job"""
    try:
        aws_svc = get_aws_services()
        result = await aws_svc.get_transcription_result(job_name)
        
        if 'error' in result:
            raise HTTPException(status_code=500, detail=result['error'])
        
        return result
    except Exception as e:
        logger.error(f"Transcription status check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@aws_router.post("/compliance/scan")
async def scan_for_sensitive_data(
    s3_bucket: Annotated[str, Query(description="S3 bucket to scan")],
    prefix: Annotated[str, Query(description="Object key prefix to scan")] = ""
):
    """
    Scan S3 bucket for sensitive data using Macie.
    Creates a one-time classification job.
    """
    try:
        if not settings.MACIE_ENABLED:
            raise HTTPException(status_code=400, detail="Macie scanning is not enabled")
        
        aws_svc = get_aws_services()
        result = await aws_svc.scan_for_sensitive_data(s3_bucket, prefix)
        
        if 'error' in result:
            raise HTTPException(status_code=500, detail=result['error'])
        
        return {
            "message": "Macie scan job created",
            **result
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Macie scan failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@aws_router.get("/compliance/findings")
async def get_compliance_findings(
    job_id: Annotated[str | None, Query(description="Filter by job ID")] = None,
    max_results: Annotated[int, Query(description="Maximum results to return")] = 50
):
    """Get Macie findings for sensitive data"""
    try:
        if not settings.MACIE_ENABLED:
            raise HTTPException(status_code=400, detail="Macie scanning is not enabled")
        
        aws_svc = get_aws_services()
        result = await aws_svc.get_macie_findings(job_id, max_results)
        
        if 'error' in result:
            raise HTTPException(status_code=500, detail=result['error'])
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get findings failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@aws_router.get("/dashboard/embed-url")
async def get_dashboard_embed_url():
    """Get QuickSight dashboard embed URL"""
    try:
        aws_svc = get_aws_services()
        result = await aws_svc.get_dashboard_embed_url()
        
        if 'error' in result:
            raise HTTPException(status_code=500, detail=result['error'])
        
        return result
    except Exception as e:
        logger.error(f"Dashboard embed URL generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
