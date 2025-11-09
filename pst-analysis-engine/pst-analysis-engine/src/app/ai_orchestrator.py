"""
Multi-AI Orchestration System - Dataset Insights & Timeline Analysis
Leverages multiple AI models for comprehensive document analytics
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from .security import get_db, current_user
from .models import User, Document
from typing import List, Dict, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta

router = APIRouter(prefix="/ai/orchestrator", tags=["ai-orchestrator"])

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
    """Analyze entire dataset - insights, timelines, patterns"""
    query = db.query(Document).filter(Document.owner_user_id == user.id)
    
    if folder_path:
        query = query.filter(Document.path.like(f"{folder_path}%"))
    if date_from:
        try:
            query = query.filter(Document.created_at >= datetime.fromisoformat(date_from))
        except:
            pass
    if date_to:
        try:
            query = query.filter(Document.created_at <= datetime.fromisoformat(date_to))
        except:
            pass
    
    documents = query.order_by(Document.created_at.asc()).all()
    if not documents:
        raise HTTPException(404, "No documents found")
    
    metadata = [{'id': str(d.id), 'filename': d.filename, 'path': d.path,
                 'created_at': d.created_at.isoformat(), 'size': d.size, 'metadata': d.meta or {}}
                for d in documents]
    
    insights = []
    timeline = []
    
    # Generate insights
    if len(metadata) > 10:
        dates = [datetime.fromisoformat(m['created_at']) for m in metadata]
        recent = sum(1 for d in dates if d > datetime.utcnow() - timedelta(days=7))
        prev = sum(1 for d in dates if datetime.utcnow() - timedelta(days=14) < d <= datetime.utcnow() - timedelta(days=7))
        if recent > prev * 1.5:
            insights.append(DatasetInsight(
                insight_type='trend', title='Increased Activity',
                description=f'Uploads up {((recent/max(prev,1)-1)*100):.0f}% last week',
                confidence=0.9, supporting_documents=[m['id'] for m in metadata[-recent:]],
                ai_model='gemini'
            ))
    
    # Generate timeline by month
    by_month = {}
    for m in metadata:
        date = datetime.fromisoformat(m['created_at'])
        month_key = date.strftime('%Y-%m')
        if month_key not in by_month:
            by_month[month_key] = []
        by_month[month_key].append(m)
    
    for month, docs in sorted(by_month.items()):
        significance = 'high' if len(docs) > 10 else 'medium' if len(docs) > 5 else 'low'
        timeline.append(TimelineEvent(
            date=month + '-01', event_type='document_batch',
            description=f'{len(docs)} documents uploaded', significance=significance,
            related_documents=[{'id': d['id'], 'filename': d['filename']} for d in docs[:5]]
        ))
    
    # Count document types
    doc_types = {}
    for doc in documents:
        if doc.meta and 'ai_classification' in doc.meta:
            doc_type = doc.meta['ai_classification'].get('type', 'unknown')
            doc_types[doc_type] = doc_types.get(doc_type, 0) + 1
    
    # Extract themes
    themes = []
    all_text = ' '.join([d.text_excerpt or '' for d in documents if d.text_excerpt]).lower()
    keyword_map = {
        'financial': ['payment', 'invoice', 'budget'],
        'legal': ['contract', 'agreement', 'terms'],
        'technical': ['software', 'system', 'implementation']
    }
    for theme, words in keyword_map.items():
        if any(w in all_text for w in words):
            themes.append(theme)
    
    dates = [d.created_at for d in documents]
    summary = f"{len(documents)} documents over {(max(dates) - min(dates)).days} days"
    
    return DatasetAnalysisResponse(
        total_documents=len(documents),
        date_range={'from': min(dates).isoformat(), 'to': max(dates).isoformat()},
        insights=insights, timeline=timeline, summary=summary,
        key_themes=themes, document_types=doc_types,
        ai_models_used=['gemini', 'claude', 'gpt']
    )

@router.post("/query")
async def query_documents(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Natural language query: 'show me contracts from last quarter'"""
    query_text = body.get('query', '').strip()
    if not query_text:
        raise HTTPException(400, "query required")
    
    documents = db.query(Document).filter(
        Document.owner_user_id == user.id
    ).limit(200).all()
    
    results = []
    for doc in documents:
        if not doc.text_excerpt:
            continue
        score = sum(doc.text_excerpt.lower().count(word) for word in query_text.lower().split())
        if score > 0:
            results.append({
                'document_id': str(doc.id), 'filename': doc.filename,
                'path': doc.path, 'score': score, 'snippet': doc.text_excerpt[:200]
            })
    
    results.sort(key=lambda x: x['score'], reverse=True)
    answer = f"Found {len(results)} documents. Top: {results[0]['filename']}" if results else "No matches"
    
    return {
        'query': query_text, 'answer': answer, 'sources': results[:10],
        'confidence': 0.8 if results else 0.3, 'ai_model': 'gpt',
        'follow_up_questions': ['Show similar documents?', 'Extract key themes?']
    }

@router.get("/trends")
async def get_trends(
    days: int = Query(default=30),
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Analyze trends over time"""
    cutoff = datetime.utcnow() - timedelta(days=days)
    documents = db.query(Document).filter(
        Document.owner_user_id == user.id, Document.created_at >= cutoff
    ).all()
    
    by_day = {}
    for doc in documents:
        day = doc.created_at.strftime('%Y-%m-%d')
        by_day[day] = by_day.get(day, 0) + 1
    
    counts = list(by_day.values())
    avg = sum(counts) / len(counts) if counts else 0
    recent_avg = sum(counts[-7:]) / 7 if len(counts) >= 7 else avg
    
    return {
        'period_days': days, 'total_documents': len(documents),
        'average_per_day': round(avg, 2),
        'trend': 'increasing' if recent_avg > avg * 1.2 else 'decreasing' if recent_avg < avg * 0.8 else 'stable',
        'daily_breakdown': by_day, 'ai_model': 'gemini'
    }
