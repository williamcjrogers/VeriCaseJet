"""
PST Refinement Wizard - AI-powered discovery and filtering
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct, case
from typing import List, Dict, Optional, Any
from datetime import datetime
from collections import defaultdict
import re
import logging
from pydantic import BaseModel
import uuid

from .database import get_db
from .auth import current_user
from .models import (
    EmailMessage, Project, Case, Stakeholder, Keyword, 
    EmailAttachment, User, PSTFile
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/refinement", tags=["refinement"])

class DiscoveredProject(BaseModel):
    """Other project references found in emails"""
    name: str
    count: int
    email_samples: List[str]
    patterns: List[str]  # Where found: subject, body, attachments

class DiscoveredParty(BaseModel):
    """Organizations identified in emails"""
    role: str
    organization: str
    confidence: float
    email_count: int
    domain: Optional[str]
    sample_people: List[str]

class DiscoveredPerson(BaseModel):
    """Individual people found"""
    name: str
    email: str
    organization: Optional[str]
    role: Optional[str]
    email_count: int
    first_seen: datetime
    last_seen: datetime

class DiscoveredTopic(BaseModel):
    """Key topics and themes"""
    topic: str
    count: int
    date_range: str
    keywords: List[str]
    urgency_indicators: int  # Count of urgent language

class DiscoveryResponse(BaseModel):
    """Complete discovery results"""
    other_projects: List[DiscoveredProject]
    parties: List[DiscoveredParty]
    people: List[DiscoveredPerson]
    topics: List[DiscoveredTopic]
    summary: Dict[str, Any]

class RefinementRequest(BaseModel):
    """User's refinement choices"""
    exclude_projects: List[str]
    confirmed_parties: Dict[str, str]  # role -> organization
    exclude_people: List[str]
    include_topics: List[str]
    custom_filters: Optional[Dict[str, Any]] = {}

class RefinementFilter(BaseModel):
    """Stored refinement filter"""
    id: str
    project_id: str
    filter_data: Dict[str, Any]
    created_at: datetime
    created_by: str
    is_active: bool = True

# Pattern matching for project references
PROJECT_PATTERNS = [
    r"(?:project|scheme|site|development)[\s:]+([A-Za-z0-9\s\-&]+)",
    r"(?:re|regarding|ref)[\s:]+([A-Za-z0-9\s\-&]+)",
    r"([A-Z]{2,}[\s\-]\d{2,})",  # Project codes like "WGL-001"
]

# Common construction roles
ROLE_PATTERNS = {
    "Employer's Agent": ["employer's agent", "ea", "contract administrator"],
    "Project Manager": ["project manager", "pm", "project lead"],
    "Architect": ["architect", "architectural", "design team"],
    "Engineer": ["engineer", "structural", "m&e", "mep"],
    "Contractor": ["contractor", "builder", "construction"],
    "Council": ["council", "local authority", "planning"],
    "Client": ["client", "employer", "owner"],
}

@router.get("/{project_id}/discover", response_model=DiscoveryResponse)
async def discover_evidence_patterns(
    project_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    limit: int = Query(1000, description="Max emails to analyze")
):
    """
    Analyze uploaded emails to discover patterns, projects, people, and topics
    """
    # Verify project access
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    
    # Get email sample
    emails = db.query(EmailMessage).filter(
        EmailMessage.case_id == project_id
    ).order_by(EmailMessage.date_sent.desc()).limit(limit).all()
    
    if not emails:
        raise HTTPException(400, "No emails found to analyze")
    
    discovery_results = {
        "other_projects": discover_other_projects(emails, project.project_name),
        "parties": discover_parties(emails, db),
        "people": discover_people(emails),
        "topics": discover_topics(emails, db),
        "summary": {
            "total_emails_analyzed": len(emails),
            "date_range": {
                "start": min(e.date_sent for e in emails if e.date_sent),
                "end": max(e.date_sent for e in emails if e.date_sent)
            }
        }
    }
    
    return DiscoveryResponse(**discovery_results)


def discover_other_projects(emails: List[EmailMessage], current_project: str) -> List[DiscoveredProject]:
    """Find references to other projects"""
    project_mentions = defaultdict(lambda: {"count": 0, "samples": []})
    current_project_lower = current_project.lower()
    
    for email in emails:
        text_to_search = f"{email.subject or ''} {email.body_text or ''}"
        
        for pattern in PROJECT_PATTERNS:
            matches = re.findall(pattern, text_to_search, re.IGNORECASE)
            for match in matches:
                # Clean and normalize
                project_name = match.strip()
                if len(project_name) > 3 and project_name.lower() != current_project_lower:
                    project_mentions[project_name]["count"] += 1
                    if len(project_mentions[project_name]["samples"]) < 3:
                        project_mentions[project_name]["samples"].append(email.subject)
    
    # Convert to list and sort by frequency
    discovered_projects = []
    for name, data in sorted(project_mentions.items(), key=lambda x: x[1]["count"], reverse=True)[:10]:
        discovered_projects.append(DiscoveredProject(
            name=name,
            count=data["count"],
            email_samples=data["samples"],
            patterns=["subject", "body"]  # Simplified for now
        ))
    
    return discovered_projects


def discover_parties(emails: List[EmailMessage], db: Session) -> List[DiscoveredParty]:
    """Identify organizations and their roles"""
    domain_stats = defaultdict(lambda: {"count": 0, "people": set()})
    
    # Analyze sender domains
    for email in emails:
        if email.sender_email:
            domain = email.sender_email.split('@')[-1].lower()
            domain_stats[domain]["count"] += 1
            if email.sender_name:
                domain_stats[domain]["people"].add(email.sender_name)
    
    # Try to match domains to roles
    discovered_parties = []
    for domain, stats in sorted(domain_stats.items(), key=lambda x: x[1]["count"], reverse=True)[:20]:
        if stats["count"] < 5:  # Minimum threshold
            continue
            
        # Infer organization from domain
        org_name = infer_organization_from_domain(domain)
        
        # Try to match role based on email content
        role = infer_role_from_content(emails, domain)
        
        discovered_parties.append(DiscoveredParty(
            role=role or "Unknown",
            organization=org_name,
            confidence=min(0.95, stats["count"] / 100),  # Simple confidence score
            email_count=stats["count"],
            domain=domain,
            sample_people=list(stats["people"])[:5]
        ))
    
    return discovered_parties


def discover_people(emails: List[EmailMessage]) -> List[DiscoveredPerson]:
    """Extract individual people and their details"""
    people_map = defaultdict(lambda: {
        "count": 0, 
        "first_seen": datetime.now(), 
        "last_seen": datetime.now(),
        "domains": set()
    })
    
    for email in emails:
        if email.sender_email and email.sender_name:
            key = (email.sender_name, email.sender_email)
            people_map[key]["count"] += 1
            people_map[key]["domains"].add(email.sender_email.split('@')[-1])
            
            if email.date_sent:
                people_map[key]["first_seen"] = min(people_map[key]["first_seen"], email.date_sent)
                people_map[key]["last_seen"] = max(people_map[key]["last_seen"], email.date_sent)
    
    # Convert to list
    discovered_people = []
    for (name, email_addr), stats in sorted(people_map.items(), key=lambda x: x[1]["count"], reverse=True)[:50]:
        domain = email_addr.split('@')[-1]
        discovered_people.append(DiscoveredPerson(
            name=name,
            email=email_addr,
            organization=infer_organization_from_domain(domain),
            role=None,  # Could enhance with title extraction
            email_count=stats["count"],
            first_seen=stats["first_seen"],
            last_seen=stats["last_seen"]
        ))
    
    return discovered_people


def discover_topics(emails: List[EmailMessage], db: Session) -> List[DiscoveredTopic]:
    """Identify key topics and themes"""
    # Common construction dispute topics
    topic_keywords = {
        "Delay & EOT": ["delay", "eot", "extension of time", "programme", "critical path", "float"],
        "Variations": ["variation", "change order", "instruction", "additional work", "scope change"],
        "Payment": ["payment", "invoice", "valuation", "application", "certificate", "retention"],
        "Quality/Defects": ["defect", "snag", "quality", "remedial", "making good", "punch list"],
        "Design Issues": ["design", "drawing", "specification", "RFI", "clash", "coordination"],
        "H&S Incidents": ["accident", "incident", "safety", "injury", "near miss", "hse"],
    }
    
    topic_stats = defaultdict(lambda: {
        "count": 0, 
        "keywords_found": set(),
        "date_range": {"start": None, "end": None},
        "urgency": 0
    })
    
    urgency_words = ["urgent", "immediate", "asap", "critical", "deadline", "overdue"]
    
    for email in emails:
        text_to_search = f"{email.subject or ''} {email.body_text or ''}".lower()
        
        # Check urgency
        urgency_count = sum(1 for word in urgency_words if word in text_to_search)
        
        # Match topics
        for topic, keywords in topic_keywords.items():
            matched = False
            for keyword in keywords:
                if keyword in text_to_search:
                    matched = True
                    topic_stats[topic]["keywords_found"].add(keyword)
            
            if matched:
                topic_stats[topic]["count"] += 1
                topic_stats[topic]["urgency"] += urgency_count
                
                if email.date_sent:
                    if topic_stats[topic]["date_range"]["start"] is None:
                        topic_stats[topic]["date_range"]["start"] = email.date_sent
                        topic_stats[topic]["date_range"]["end"] = email.date_sent
                    else:
                        topic_stats[topic]["date_range"]["start"] = min(
                            topic_stats[topic]["date_range"]["start"], email.date_sent
                        )
                        topic_stats[topic]["date_range"]["end"] = max(
                            topic_stats[topic]["date_range"]["end"], email.date_sent
                        )
    
    # Convert to response format
    discovered_topics = []
    for topic, stats in sorted(topic_stats.items(), key=lambda x: x[1]["count"], reverse=True):
        if stats["count"] > 0:
            date_range = "Unknown"
            if stats["date_range"]["start"]:
                start = stats["date_range"]["start"].strftime("%b %Y")
                end = stats["date_range"]["end"].strftime("%b %Y")
                date_range = f"{start} - {end}"
            
            discovered_topics.append(DiscoveredTopic(
                topic=topic,
                count=stats["count"],
                date_range=date_range,
                keywords=list(stats["keywords_found"]),
                urgency_indicators=stats["urgency"]
            ))
    
    return discovered_topics


def infer_organization_from_domain(domain: str) -> str:
    """Try to infer organization name from email domain"""
    # Remove common suffixes
    org_name = domain.replace('.com', '').replace('.co.uk', '').replace('.org', '').replace('.gov.uk', '')
    
    # Handle common patterns
    if 'council' in domain or 'gov' in domain:
        parts = org_name.split('.')
        if len(parts) > 1:
            return f"{parts[0].title()} Council"
    
    # Capitalize parts
    parts = org_name.split('.')
    if len(parts) > 1:
        return ' '.join(p.title() for p in parts)
    
    return org_name.title()


def infer_role_from_content(emails: List[EmailMessage], domain: str) -> Optional[str]:
    """Try to determine organization's role from email content"""
    # Simple heuristic based on domain patterns
    domain_lower = domain.lower()
    
    if 'council' in domain_lower or 'gov' in domain_lower:
        return "Council/Authority"
    elif any(arch in domain_lower for arch in ['architect', 'design', 'bdp', 'foster']):
        return "Architect"
    elif any(eng in domain_lower for eng in ['arup', 'wsp', 'engineer', 'structural']):
        return "Engineer"
    elif any(pm in domain_lower for pm in ['pm', 'gleeds', 'faithful']):
        return "Project Manager"
    
    # Could enhance with content analysis
    return None


@router.post("/{project_id}/apply-refinement")
async def apply_refinement(
    project_id: str,
    refinement: RefinementRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """
    Apply user's refinement choices to filter emails
    """
    # Verify project access
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    
    # Create refinement filter record
    filter_id = str(uuid.uuid4())
    filter_data = {
        "exclude_projects": refinement.exclude_projects,
        "confirmed_parties": refinement.confirmed_parties,
        "exclude_people": refinement.exclude_people,
        "include_topics": refinement.include_topics,
        "custom_filters": refinement.custom_filters,
        "applied_at": datetime.now().isoformat()
    }
    
    # In production, we'd store this in a refinement_filters table
    # For now, we'll update the project metadata
    if not project.metadata:
        project.metadata = {}
    
    project.metadata["active_refinement"] = filter_data
    db.commit()
    
    # Apply filters to emails (mark excluded ones)
    excluded_count = 0
    
    # Get all emails for the project
    emails = db.query(EmailMessage).filter(
        EmailMessage.case_id == project_id
    ).all()
    
    for email in emails:
        should_exclude = False
        
        # Check if email mentions excluded projects
        email_text = f"{email.subject or ''} {email.body_text or ''}".lower()
        for excluded_project in refinement.exclude_projects:
            if excluded_project.lower() in email_text:
                should_exclude = True
                break
        
        # Check if from excluded people
        if not should_exclude and email.sender_email:
            for excluded_person in refinement.exclude_people:
                if excluded_person.lower() in email.sender_email.lower():
                    should_exclude = True
                    break
        
        # Update email metadata
        if should_exclude:
            if not email.metadata:
                email.metadata = {}
            email.metadata["excluded_by_refinement"] = filter_id
            excluded_count += 1
    
    db.commit()
    
    return {
        "success": True,
        "filter_id": filter_id,
        "stats": {
            "total_emails": len(emails),
            "excluded_emails": excluded_count,
            "remaining_emails": len(emails) - excluded_count
        }
    }


@router.get("/{project_id}/active-filters")
async def get_active_filters(
    project_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """Get currently active refinement filters"""
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    
    if project.metadata and "active_refinement" in project.metadata:
        return {
            "has_active_filter": True,
            "filter": project.metadata["active_refinement"]
        }
    
    return {"has_active_filter": False}


@router.delete("/{project_id}/clear-filters")
async def clear_refinement_filters(
    project_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """Remove all refinement filters"""
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    
    # Clear project metadata
    if project.metadata and "active_refinement" in project.metadata:
        del project.metadata["active_refinement"]
    
    # Clear email exclusions
    emails = db.query(EmailMessage).filter(
        EmailMessage.case_id == project_id
    ).all()
    
    cleared_count = 0
    for email in emails:
        if email.metadata and "excluded_by_refinement" in email.metadata:
            del email.metadata["excluded_by_refinement"]
            cleared_count += 1
    
    db.commit()
    
    return {
        "success": True,
        "emails_restored": cleared_count
    }
