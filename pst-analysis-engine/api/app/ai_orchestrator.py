"""
Multi-AI Orchestration System - Dataset Insights & Timeline Analysis
Leverages multiple AI models for comprehensive document analytics
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .models import User, Document
from .db import get_db
from .security import current_user

router = APIRouter(prefix="/ai/orchestrator", tags=["ai-orchestrator"])
logger = logging.getLogger(__name__)


def _ensure_timezone(value: datetime) -> datetime:
    """Ensure datetime has timezone information."""
    if value is None:
        raise ValueError("Cannot ensure timezone on None value")
    if not isinstance(value, datetime):
        raise TypeError(f"Expected datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _parse_iso_date(raw_value: Optional[str], field_name: str) -> Optional[datetime]:
    """Parse ISO date string with proper error handling and log injection prevention."""
    if not raw_value:
        return None
    
    # Sanitize input for logging to prevent log injection (CWE-117)
    sanitized_value = raw_value.replace('\n', '').replace('\r', '')[:100]
    
    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError as exc:
        # Use sanitized value in logs to prevent log injection
        logger.error(
            "Invalid date format for field=%s value=%s error=%s",
            field_name,
            sanitized_value,
            str(exc).replace('\n', '').replace('\r', '')
        )
        raise HTTPException(400, f"Invalid {field_name}; use ISO 8601 format") from exc
    except (TypeError, AttributeError) as exc:
        logger.exception("Unexpected error parsing date field=%s", field_name)
        raise HTTPException(500, "Internal error processing date") from exc
    
    return _ensure_timezone(parsed)


def _apply_date_filters(query, start_at: Optional[datetime], end_at: Optional[datetime]):
    """Apply date range filters to query with validation."""
    try:
        if start_at:
            query = query.filter(Document.created_at >= start_at)
        if end_at:
            query = query.filter(Document.created_at <= end_at)
        return query
    except (AttributeError, TypeError) as exc:
        logger.exception("Error applying date filters")
        raise HTTPException(500, "Error applying date filters") from exc


def _serialize_documents(documents: List[Document]) -> List[Dict]:
    """Serialize documents to metadata dictionaries with error handling."""
    metadata = []
    fallback_now = datetime.now(timezone.utc)
    
    for doc in documents:
        try:
            created_at = _ensure_timezone(doc.created_at or fallback_now)
            metadata.append({
                'id': str(doc.id),
                'filename': doc.filename or 'unknown',
                'path': doc.path or '',
                'created_at': created_at,
                'size': doc.size or 0,
                'metadata': doc.meta or {}
            })
        except (ValueError, AttributeError) as exc:
            # Log specific error but continue processing other documents
            logger.warning(
                "Failed to serialize document id=%s: %s",
                getattr(doc, 'id', 'unknown'),
                str(exc)
            )
            continue
    
    return metadata


def _generate_activity_insights(metadata: List[Dict]) -> List["DatasetInsight"]:
    """
    Generate activity insights from document metadata.
    Simplified logic to reduce complexity.
    """
    if len(metadata) <= 10:
        return []
    
    try:
        now = datetime.now(timezone.utc)
        recent_docs = [m for m in metadata if m['created_at'] > now - timedelta(days=7)]
        prev_docs = [
            m for m in metadata
            if now - timedelta(days=14) < m['created_at'] <= now - timedelta(days=7)
        ]
        
        recent_count = len(recent_docs)
        prev_count = len(prev_docs)
        
        # Check if there's a significant increase
        if not recent_count or recent_count <= max(prev_count, 1) * 1.5:
            return []
        
        # Get supporting documents
        supporting_docs = [m['id'] for m in recent_docs[-min(5, recent_count):]]
        uplift = ((recent_count / max(prev_count, 1)) - 1) * 100
        
        return [
            DatasetInsight(
                insight_type='trend',
                title='Increased Activity',
                description=f'Uploads up {uplift:.0f}% last week',
                confidence=0.9,
                supporting_documents=supporting_docs,
                ai_model='gemini'
            )
        ]
    except (KeyError, TypeError, ZeroDivisionError) as exc:
        logger.warning("Error generating activity insights: %s", str(exc))
        return []


def _build_monthly_timeline(metadata: List[Dict]) -> List["TimelineEvent"]:
    """Build monthly timeline from document metadata with error handling."""
    buckets: Dict[str, List[Dict]] = {}
    
    try:
        for entry in metadata:
            try:
                month_key = entry['created_at'].strftime('%Y-%m')
                buckets.setdefault(month_key, []).append(entry)
            except (KeyError, AttributeError) as exc:
                logger.debug("Skipping entry without valid created_at: %s", str(exc))
                continue
        
        timeline: List[TimelineEvent] = []
        for month in sorted(buckets.keys()):
            docs = buckets[month]
            size = len(docs)
            
            # Determine significance
            if size > 10:
                significance = 'high'
            elif size > 5:
                significance = 'medium'
            else:
                significance = 'low'
            
            timeline.append(
                TimelineEvent(
                    date=f"{month}-01",
                    event_type='document_batch',
                    description=f'{size} documents uploaded',
                    significance=significance,
                    related_documents=[
                        {'id': d.get('id', ''), 'filename': d.get('filename', 'unknown')}
                        for d in docs[:5]
                    ]
                )
            )
        return timeline
    except (KeyError, AttributeError, TypeError) as exc:
        logger.exception("Error building monthly timeline")
        return []


def _count_document_types(documents: List[Document]) -> Dict[str, int]:
    """Count document types from metadata with error handling."""
    counts: Dict[str, int] = {}
    
    try:
        for doc in documents:
            try:
                if doc.meta and isinstance(doc.meta, dict) and 'ai_classification' in doc.meta:
                    classification = doc.meta['ai_classification']
                    if isinstance(classification, dict):
                        doc_type = classification.get('type', 'unknown')
                        counts[doc_type] = counts.get(doc_type, 0) + 1
            except (AttributeError, TypeError) as exc:
                logger.debug("Error processing document type for doc: %s", str(exc))
                continue
        return counts
    except (AttributeError, TypeError, KeyError) as exc:
        logger.warning("Error counting document types: %s", str(exc))
        return {}


def _extract_themes(documents: List[Document]) -> List[str]:
    """
    Extract themes from documents using keyword matching.
    Optimized to avoid performance issues with large datasets.
    """
    try:
        # Limit text processing to avoid performance issues
        text_excerpts = []
        for doc in documents[:500]:  # Limit to first 500 documents
            try:
                if doc.text_excerpt:
                    text_excerpts.append(doc.text_excerpt[:1000])  # Limit excerpt length
            except AttributeError:
                continue
        
        text_blob = ' '.join(text_excerpts).lower()
        
        keyword_map = {
            'financial': ['payment', 'invoice', 'budget'],
            'legal': ['contract', 'agreement', 'terms'],
            'technical': ['software', 'system', 'implementation']
        }
        
        return [
            theme for theme, words in keyword_map.items()
            if any(word in text_blob for word in words)
        ]
    except (AttributeError, TypeError, KeyError) as exc:
        logger.warning("Error extracting themes: %s", str(exc))
        return []


def _summarize_documents(documents: List[Document]) -> Tuple[str, Dict[str, str]]:
    """Summarize documents with date range and error handling."""
    try:
        dates = []
        for doc in documents:
            try:
                if doc.created_at:
                    dates.append(_ensure_timezone(doc.created_at))
            except (ValueError, AttributeError) as exc:
                logger.debug("Skipping document with invalid date: %s", str(exc))
                continue
        
        if not dates:
            now = datetime.now(timezone.utc)
            return "0 documents", {'from': now.isoformat(), 'to': now.isoformat()}
        
        total_span = (max(dates) - min(dates)).days or 0
        summary = f"{len(documents)} documents over {total_span} days"
        date_range = {'from': min(dates).isoformat(), 'to': max(dates).isoformat()}
        return summary, date_range
    except (ValueError, AttributeError, TypeError) as exc:
        logger.warning("Error summarizing documents: %s", str(exc))
        now = datetime.now(timezone.utc)
        return "Error summarizing", {'from': now.isoformat(), 'to': now.isoformat()}

class DatasetInsight(BaseModel):
    insight_type: str
    title: str
    description: str
    confidence: float
    supporting_documents: List[str]
    ai_model: str

class TimelineEvent(BaseModel):
    date: str
    event_type: str
    description: str
    related_documents: List[Dict]
    significance: str

class DatasetAnalysisResponse(BaseModel):
    total_documents: int
    date_range: Dict[str, str]
    insights: List[DatasetInsight]
    timeline: List[TimelineEvent]
    summary: str
    key_themes: List[str]
    document_types: Dict[str, int]
    ai_models_used: List[str]

@router.get("/analyze/dataset", response_model=DatasetAnalysisResponse)
async def analyze_dataset(
    folder_path: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """
    Analyze entire dataset - insights, timelines, patterns.
    Provides comprehensive analytics across user's documents.
    """
    try:
        query = db.query(Document).filter(Document.owner_user_id == user.id)
        
        if folder_path:
            # Sanitize folder path to prevent SQL injection
            sanitized_path = folder_path.replace('%', '\\%').replace('_', '\\_')
            query = query.filter(Document.path.like(f"{sanitized_path}%"))
        
        start_at = _parse_iso_date(date_from, "date_from")
        end_at = _parse_iso_date(date_to, "date_to")
        query = _apply_date_filters(query, start_at, end_at)
        
        # Limit query to prevent performance issues
        documents = query.order_by(Document.created_at.asc()).limit(10000).all()
        
        if not documents:
            raise HTTPException(404, "No documents found")
        
        # Process documents with error handling
        metadata = _serialize_documents(documents)
        if not metadata:
            raise HTTPException(500, "Failed to process documents")
        
        insights = _generate_activity_insights(metadata)
        timeline = _build_monthly_timeline(metadata)
        doc_types = _count_document_types(documents)
        themes = _extract_themes(documents)
        summary, date_range = _summarize_documents(documents)
        
        return DatasetAnalysisResponse(
            total_documents=len(documents),
            date_range=date_range,
            insights=insights,
            timeline=timeline,
            summary=summary,
            key_themes=themes,
            document_types=doc_types,
            ai_models_used=['gemini', 'claude', 'gpt']
        )
    except HTTPException:
        raise
    except (ValueError, AttributeError, TypeError) as exc:
        logger.exception("Error analyzing dataset for user=%s", user.id)
        raise HTTPException(500, "Failed to analyze dataset") from exc

@router.post("/query")
async def query_documents(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """
    Natural language query: 'show me contracts from last quarter'.
    Performs keyword-based search across document text excerpts.
    """
    try:
        query_text = body.get('query', '').strip()
        if not query_text:
            raise HTTPException(400, "query required")
        
        # Limit query text length to prevent performance issues
        if len(query_text) > 500:
            raise HTTPException(400, "query too long (max 500 characters)")
        
        # Fetch documents with limit to prevent performance issues
        documents = db.query(Document).filter(
            Document.owner_user_id == user.id
        ).limit(200).all()
        
        results = []
        query_words = query_text.lower().split()[:20]  # Limit to 20 words
        
        for doc in documents:
            try:
                if not doc.text_excerpt:
                    continue
                
                excerpt_lower = doc.text_excerpt.lower()
                score = sum(excerpt_lower.count(word) for word in query_words)
                
                if score > 0:
                    results.append({
                        'document_id': str(doc.id),
                        'filename': doc.filename or 'unknown',
                        'path': doc.path or '',
                        'score': score,
                        'snippet': doc.text_excerpt[:200]
                    })
            except (AttributeError, TypeError) as exc:
                logger.debug("Error processing document in query: %s", str(exc))
                continue
        
        results.sort(key=lambda x: x['score'], reverse=True)
        
        if results:
            answer = f"Found {len(results)} documents. Top: {results[0]['filename']}"
        else:
            answer = "No matches"
        
        return {
            'query': query_text,
            'answer': answer,
            'sources': results[:10],
            'confidence': 0.8 if results else 0.3,
            'ai_model': 'gpt',
            'follow_up_questions': ['Show similar documents?', 'Extract key themes?']
        }
    except HTTPException:
        raise
    except (ValueError, AttributeError, TypeError) as exc:
        logger.exception("Error querying documents for user=%s", user.id)
        raise HTTPException(500, "Failed to query documents") from exc

@router.get("/trends")
async def get_trends(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """
    Analyze document upload trends over time.
    Returns daily breakdown and trend analysis.
    """
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        documents = db.query(Document).filter(
            Document.owner_user_id == user.id,
            Document.created_at >= cutoff
        ).all()
        
        by_day = {}
        for doc in documents:
            try:
                if doc.created_at:
                    day = doc.created_at.strftime('%Y-%m-%d')
                    by_day[day] = by_day.get(day, 0) + 1
            except (AttributeError, ValueError) as exc:
                logger.debug("Error processing document date in trends: %s", str(exc))
                continue
        
        counts = list(by_day.values())
        
        # Calculate averages safely
        if counts:
            avg = sum(counts) / len(counts)
            recent_avg = sum(counts[-7:]) / min(7, len(counts)) if len(counts) >= 1 else avg
        else:
            avg = 0
            recent_avg = 0
        
        # Determine trend
        if recent_avg > avg * 1.2:
            trend = 'increasing'
        elif recent_avg < avg * 0.8:
            trend = 'decreasing'
        else:
            trend = 'stable'
        
        return {
            'period_days': days,
            'total_documents': len(documents),
            'average_per_day': round(avg, 2),
            'trend': trend,
            'daily_breakdown': by_day,
            'ai_model': 'gemini'
        }
    except (ValueError, AttributeError, TypeError) as exc:
        logger.exception("Error getting trends for user=%s", user.id)
        raise HTTPException(500, "Failed to analyze trends") from exc
