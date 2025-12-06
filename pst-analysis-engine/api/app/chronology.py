from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc

from .db import get_db
from .models import (
    Case,
    User,
    ChronologyItem,
    DelayEvent,
    EmailMessage,
    Programme,
    Claim,
    Project
)
from .security import current_user
from pydantic import BaseModel

router = APIRouter()

# --- Pydantic Models ---

class ChronologyItemCreate(BaseModel):
    title: str
    event_date: datetime
    event_type: str = "manual"  # notice, meeting, correspondence, site_event
    description: Optional[str] = None
    claim_id: Optional[UUID] = None
    evidence_ids: Optional[List[str]] = None
    parties_involved: Optional[List[str]] = None

class ChronologyItemUpdate(BaseModel):
    title: Optional[str] = None
    event_date: Optional[datetime] = None
    event_type: Optional[str] = None
    description: Optional[str] = None
    claim_id: Optional[UUID] = None
    evidence_ids: Optional[List[str]] = None
    parties_involved: Optional[List[str]] = None

class TimelineEvent(BaseModel):
    id: str
    date: datetime
    type: str  # chronology_item, delay_event, email, activity
    title: str
    description: Optional[str] = None
    source_id: str
    metadata: Optional[dict[str, Any]] = None

class TimelineResponse(BaseModel):
    events: List[TimelineEvent]
    total: int

# --- Endpoints ---

@router.get("/api/cases/{case_id}/chronology", response_model=List[dict])
def get_chronology_items(
    case_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Get manual chronology items for a case"""
    items = db.query(ChronologyItem).filter(ChronologyItem.case_id == case_id).order_by(ChronologyItem.event_date).all()
    return [
        {
            "id": str(item.id),
            "event_date": item.event_date,
            "title": item.title,
            "description": item.description,
            "event_type": item.event_type,
            "evidence_ids": item.evidence_ids,
            "parties_involved": item.parties_involved,
            "claim_id": str(item.claim_id) if item.claim_id else None
        }
        for item in items
    ]

@router.post("/api/cases/{case_id}/chronology", response_model=dict)
def create_chronology_item(
    case_id: UUID,
    item: ChronologyItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Create a new chronology item manually"""
    # Verify case access
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    
    # TODO: Check user permissions for this case

    new_item = ChronologyItem(
        case_id=case_id,
        title=item.title,
        event_date=item.event_date,
        event_type=item.event_type,
        description=item.description,
        claim_id=item.claim_id,
        evidence_ids=item.evidence_ids,
        parties_involved=item.parties_involved
    )
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    
    return {"id": str(new_item.id), "message": "Chronology item created"}

@router.delete("/api/cases/{case_id}/chronology/{item_id}")
def delete_chronology_item(
    case_id: UUID,
    item_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    item = db.query(ChronologyItem).filter(
        ChronologyItem.id == item_id, 
        ChronologyItem.case_id == case_id
    ).first()
    
    if not item:
        raise HTTPException(404, "Item not found")
        
    db.delete(item)
    db.commit()
    return {"message": "Item deleted"}

class ImportRequest(BaseModel):
    source_type: str  # programme, delay_event, email
    source_id: Optional[str] = None # specific item or None for all
    date_range_start: Optional[datetime] = None
    date_range_end: Optional[datetime] = None

@router.post("/api/cases/{case_id}/chronology/import", response_model=dict)
def import_chronology_items(
    case_id: UUID,
    request: ImportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """
    Import items from other modules into the persistent Chronology.
    Allows users to 'pin' events to the chronology for editing.
    """
    imported_count = 0
    
    if request.source_type == "programme":
        programmes = db.query(Programme).filter(Programme.case_id == case_id).all()
        for prog in programmes:
            if not prog.activities: continue
            for activity in prog.activities:
                if not isinstance(activity, dict): continue
                
                # Filter logic (e.g. milestones only)
                if not (activity.get("is_milestone") or activity.get("is_critical")):
                    continue
                    
                start = activity.get("start_date")
                if not start: continue
                try:
                    event_date = datetime.fromisoformat(start.replace("Z", "+00:00"))
                except: continue
                
                # Create item
                title = activity.get("name") or "Unnamed Milestone"
                # Check duplicate (simple check)
                exists = db.query(ChronologyItem).filter(
                    ChronologyItem.case_id == case_id,
                    ChronologyItem.title == title,
                    ChronologyItem.event_date == event_date
                ).first()
                
                if not exists:
                    new_item = ChronologyItem(
                        case_id=case_id,
                        title=title,
                        event_date=event_date,
                        event_type="milestone",
                        description=f"Imported from Programme: {prog.programme_name}",
                        parties_involved=[]
                    )
                    db.add(new_item)
                    imported_count += 1

    elif request.source_type == "delay_event":
        delays = db.query(DelayEvent).filter(DelayEvent.case_id == case_id).all()
        for delay in delays:
            event_date = delay.actual_start or delay.planned_start or delay.created_at
            if not event_date: continue
            
            title = f"Delay: {delay.activity_name}"
            exists = db.query(ChronologyItem).filter(
                ChronologyItem.case_id == case_id,
                ChronologyItem.title == title,
                ChronologyItem.event_date == event_date
            ).first()
            
            if not exists:
                new_item = ChronologyItem(
                    case_id=case_id,
                    title=title,
                    event_date=event_date,
                    event_type="delay",
                    description=delay.description,
                    claim_id=delay.id # Linking delay event as claim_id might not be strictly correct but useful reference
                )
                db.add(new_item)
                imported_count += 1

    elif request.source_type == "email":
        # Import high importance emails
        emails = db.query(EmailMessage).filter(
            EmailMessage.case_id == case_id,
            EmailMessage.importance == 'high'
        ).limit(50).all()
        
        for email in emails:
            if not email.date_sent: continue
            title = email.subject or "No Subject"
            
            exists = db.query(ChronologyItem).filter(
                ChronologyItem.case_id == case_id,
                ChronologyItem.title == title,
                ChronologyItem.event_date == email.date_sent
            ).first()
            
            if not exists:
                new_item = ChronologyItem(
                    case_id=case_id,
                    title=title,
                    event_date=email.date_sent,
                    event_type="correspondence",
                    description=f"From: {email.sender_name}\n\n{email.body_preview or ''}",
                    evidence_ids=[str(email.id)] # Store ID in evidence_ids list
                )
                db.add(new_item)
                imported_count += 1

    db.commit()
    return {"message": f"Imported {imported_count} items into chronology"}

@router.get("/api/cases/{case_id}/timeline", response_model=TimelineResponse)
def get_full_timeline(
    case_id: UUID,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    include_emails: bool = False,
    include_programme: bool = True,
    limit: int = 500,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """
    Aggregate all events for a visual timeline.
    Includes: Manual Chronology Items, Delay Events, Programme Activities, Key Emails.
    """
    timeline_events = []

    # 1. Manual Chronology Items
    chrono_query = db.query(ChronologyItem).filter(ChronologyItem.case_id == case_id)
    if start_date:
        chrono_query = chrono_query.filter(ChronologyItem.event_date >= start_date)
    if end_date:
        chrono_query = chrono_query.filter(ChronologyItem.event_date <= end_date)
    
    chrono_items = chrono_query.limit(limit).all()
    for item in chrono_items:
        timeline_events.append(TimelineEvent(
            id=str(item.id),
            date=item.event_date,
            type="chronology_item",
            title=item.title,
            description=item.description,
            source_id=str(item.id),
            metadata={"event_type": item.event_type}
        ))

    # 2. Delay Events
    delay_query = db.query(DelayEvent).filter(DelayEvent.case_id == case_id)
    # Filter by actual_start or planned_start
    # Simplifying to use actual_start or created_at if null
    delay_events = delay_query.limit(limit).all()
    for delay in delay_events:
        event_date = delay.actual_start or delay.planned_start or delay.created_at
        if not event_date:
            continue
            
        if start_date and event_date < start_date: continue
        if end_date and event_date > end_date: continue

        timeline_events.append(TimelineEvent(
            id=str(delay.id),
            date=event_date,
            type="delay_event",
            title=f"Delay: {delay.activity_name or 'Unknown Activity'}",
            description=delay.description or f"Delay of {delay.delay_days} days",
            source_id=str(delay.id),
            metadata={
                "delay_days": delay.delay_days,
                "delay_type": delay.delay_type,
                "cause": delay.delay_cause
            }
        ))

    # 3. Programme Activities (Simplified)
    if include_programme:
        # Get active programmes for the case
        programmes = db.query(Programme).filter(Programme.case_id == case_id).all()
        for prog in programmes:
            if not prog.activities:
                continue
            
            # This could be heavy, so maybe limit or filter for milestones only?
            # For now, let's just grab Milestones or Critical Path items
            for activity in prog.activities:
                if not isinstance(activity, dict): continue
                
                # Check if it's a milestone or critical
                is_milestone = activity.get("is_milestone")
                is_critical = activity.get("is_critical")
                
                if not (is_milestone or is_critical):
                    continue

                start = activity.get("start_date")
                finish = activity.get("finish_date")
                
                # Parse date
                try:
                    dt_str = start or finish
                    if not dt_str: continue
                    act_date = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                except:
                    continue
                
                if start_date and act_date < start_date: continue
                if end_date and act_date > end_date: continue

                timeline_events.append(TimelineEvent(
                    id=f"prog_{prog.id}_{activity.get('id')}",
                    date=act_date,
                    type="milestone" if is_milestone else "critical_activity",
                    title=activity.get("name") or "Unnamed Activity",
                    description=f"Programme: {prog.programme_name}",
                    source_id=str(prog.id),
                    metadata={
                        "activity_id": activity.get("id"),
                        "programme_type": prog.programme_type
                    }
                ))

    # 4. Emails (if requested)
    if include_emails:
        email_query = db.query(EmailMessage).filter(
            EmailMessage.case_id == case_id,
            EmailMessage.importance == 'high'  # Only high importance by default
        )
        if start_date:
            email_query = email_query.filter(EmailMessage.date_sent >= start_date)
        if end_date:
            email_query = email_query.filter(EmailMessage.date_sent <= end_date)
            
        emails = email_query.limit(100).all() # Hard limit to prevent flooding
        for email in emails:
            if not email.date_sent: continue
            
            timeline_events.append(TimelineEvent(
                id=str(email.id),
                date=email.date_sent,
                type="email",
                title=f"Email: {email.subject[:50] if email.subject else 'No Subject'}",
                description=f"From: {email.sender_name or email.sender_email}",
                source_id=str(email.id),
                metadata={
                    "has_attachments": email.has_attachments,
                    "importance": email.importance
                }
            ))

    # Sort all events by date
    timeline_events.sort(key=lambda x: x.date)

    return TimelineResponse(
        events=timeline_events,
        total=len(timeline_events)
    )

