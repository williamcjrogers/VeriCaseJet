"""
PST Refinement Wizard - AI-powered discovery and filtering
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Any, cast, Dict
from datetime import datetime, timezone
from collections import defaultdict
import re
import logging
from pydantic import BaseModel
import uuid

from .db import get_db
from .security import current_user
from .models import EmailMessage, Project, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/refinement", tags=["refinement"])


class DiscoveredProject(BaseModel):
    """Other project references found in emails"""

    name: str
    count: int
    email_samples: list[str]
    patterns: list[str]  # Where found: subject, body, attachments


class DiscoveredParty(BaseModel):
    """Organizations identified in emails"""

    role: str
    organization: str
    confidence: float
    email_count: int
    domain: str | None
    sample_people: list[str]


class DiscoveredPerson(BaseModel):
    """Individual people found"""

    name: str
    email: str
    organization: str | None
    role: str | None
    email_count: int
    first_seen: datetime
    last_seen: datetime


class DiscoveredTopic(BaseModel):
    """Key topics and themes"""

    topic: str
    count: int
    date_range: str
    keywords: list[str]
    urgency_indicators: int  # Count of urgent language


class DiscoveryResponse(BaseModel):
    """Complete discovery results"""

    other_projects: list[DiscoveredProject]
    parties: list[DiscoveredParty]
    people: list[DiscoveredPerson]
    topics: list[DiscoveredTopic]
    summary: dict[str, Any]


class RefinementRequest(BaseModel):
    """User's refinement choices"""

    exclude_projects: list[str]
    confirmed_parties: dict[str, str]  # role -> organization
    exclude_people: list[str]
    include_topics: list[str]
    custom_filters: dict[str, Any] | None = None


class RefinementFilter(BaseModel):
    """Stored refinement filter"""

    id: str
    project_id: str
    filter_data: dict[str, Any]
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
    limit: int = Query(1000, description="Max emails to analyze"),
):
    """
    Analyze uploaded emails to discover patterns, projects, people, and topics
    """
    # Verify project access
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    # Get email sample - filter by project_id, not case_id!
    emails = (
        db.query(EmailMessage)
        .filter(EmailMessage.project_id == project_id)
        .order_by(EmailMessage.date_sent.desc())
        .limit(limit)
        .all()
    )

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
                "start": min(
                    (e.date_sent for e in emails if e.date_sent), default=None
                ),
                "end": max((e.date_sent for e in emails if e.date_sent), default=None),
            },
        },
    }

    return DiscoveryResponse(**discovery_results)


def discover_other_projects(
    emails: list[EmailMessage], current_project: str
) -> list[DiscoveredProject]:
    """Find references to other projects"""
    project_mentions: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "samples": []}
    )
    current_project_lower = current_project.lower()

    for email in emails:
        text_to_search = f"{email.subject or ''} {email.body_text or ''}"

        for pattern in PROJECT_PATTERNS:
            matches = re.findall(pattern, text_to_search, re.IGNORECASE)
            for match in matches:
                # Clean and normalize
                project_name = match.strip()
                if (
                    len(project_name) > 3
                    and project_name.lower() != current_project_lower
                ):
                    project_mentions[project_name]["count"] += 1
                    samples = project_mentions[project_name]["samples"]
                    if isinstance(samples, list) and len(samples) < 3:
                        samples.append(email.subject or "")

    # Convert to list and sort by frequency
    discovered_projects = []
    for name, data in sorted(
        project_mentions.items(), key=lambda x: int(x[1]["count"]), reverse=True
    )[:10]:
        count_val = int(data["count"])
        samples_val = data["samples"] if isinstance(data["samples"], list) else []
        discovered_projects.append(
            DiscoveredProject(
                name=name,
                count=count_val,
                email_samples=samples_val,
                patterns=["subject", "body"],  # Simplified for now
            )
        )

    return discovered_projects


def discover_parties(emails: list[EmailMessage], db: Session) -> list[DiscoveredParty]:
    """Identify organizations and their roles"""
    domain_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "people": set()}
    )

    # Analyze sender domains
    for email in emails:
        sender_email_val = str(email.sender_email) if email.sender_email else None
        if sender_email_val:
            domain = sender_email_val.split("@")[-1].lower()
            domain_stats[domain]["count"] += 1
            sender_name_val = str(email.sender_name) if email.sender_name else None
            if sender_name_val:
                people_set = domain_stats[domain]["people"]
                if isinstance(people_set, set):
                    people_set.add(sender_name_val)

    # Try to match domains to roles
    discovered_parties = []
    for domain, stats in sorted(
        domain_stats.items(), key=lambda x: int(x[1]["count"]), reverse=True
    )[:20]:
        count_val = int(stats["count"])
        if count_val < 5:  # Minimum threshold
            continue

        # Infer organization from domain
        org_name = infer_organization_from_domain(domain)

        # Try to match role based on email content
        role = infer_role_from_content(emails, domain)

        people_set = stats["people"] if isinstance(stats["people"], set) else set()
        discovered_parties.append(
            DiscoveredParty(
                role=role or "Unknown",
                organization=org_name,
                confidence=min(0.95, count_val / 100),  # Simple confidence score
                email_count=count_val,
                domain=domain,
                sample_people=list(people_set)[:5],
            )
        )

    return discovered_parties


def discover_people(emails: list[EmailMessage]) -> list[DiscoveredPerson]:
    """Extract individual people and their details"""
    # Use None as sentinel; will be replaced with actual email dates
    people_map: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "first_seen": None, "last_seen": None, "domains": set()}
    )

    for email in emails:
        sender_email_val = str(email.sender_email) if email.sender_email else None
        sender_name_val = str(email.sender_name) if email.sender_name else None
        if sender_email_val and sender_name_val:
            key = (sender_name_val, sender_email_val)
            people_map[key]["count"] += 1
            domains_set = people_map[key]["domains"]
            if isinstance(domains_set, set):
                domains_set.add(sender_email_val.split("@")[-1])

            date_sent_val = email.date_sent
            if date_sent_val and isinstance(date_sent_val, datetime):
                first_seen_val = people_map[key]["first_seen"]
                last_seen_val = people_map[key]["last_seen"]
                if first_seen_val is None or (
                    isinstance(first_seen_val, datetime)
                    and date_sent_val < first_seen_val
                ):
                    people_map[key]["first_seen"] = date_sent_val
                if last_seen_val is None or (
                    isinstance(last_seen_val, datetime)
                    and date_sent_val > last_seen_val
                ):
                    people_map[key]["last_seen"] = date_sent_val

    # Convert to list
    discovered_people = []
    for (name, email_addr), stats in sorted(
        people_map.items(), key=lambda x: int(x[1]["count"]), reverse=True
    )[:50]:
        domain = email_addr.split("@")[-1]
        count_val = int(stats["count"])
        # Use actual dates from emails or current UTC time as fallback
        first_seen_val = (
            stats["first_seen"]
            if isinstance(stats["first_seen"], datetime)
            else datetime.now(timezone.utc)
        )
        last_seen_val = (
            stats["last_seen"]
            if isinstance(stats["last_seen"], datetime)
            else datetime.now(timezone.utc)
        )
        discovered_people.append(
            DiscoveredPerson(
                name=name,
                email=email_addr,
                organization=infer_organization_from_domain(domain),
                role=None,  # Could enhance with title extraction
                email_count=count_val,
                first_seen=first_seen_val,
                last_seen=last_seen_val,
            )
        )

    return discovered_people


def discover_topics(emails: list[EmailMessage], db: Session) -> list[DiscoveredTopic]:
    """Identify key topics and themes"""
    # Common construction dispute topics
    topic_keywords = {
        "Delay & EOT": [
            "delay",
            "eot",
            "extension of time",
            "programme",
            "critical path",
            "float",
        ],
        "Variations": [
            "variation",
            "change order",
            "instruction",
            "additional work",
            "scope change",
        ],
        "Payment": [
            "payment",
            "invoice",
            "valuation",
            "application",
            "certificate",
            "retention",
        ],
        "Quality/Defects": [
            "defect",
            "snag",
            "quality",
            "remedial",
            "making good",
            "punch list",
        ],
        "Design Issues": [
            "design",
            "drawing",
            "specification",
            "RFI",
            "clash",
            "coordination",
        ],
        "H&S Incidents": [
            "accident",
            "incident",
            "safety",
            "injury",
            "near miss",
            "hse",
        ],
    }

    topic_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "count": 0,
            "keywords_found": set(),
            "date_range": {"start": None, "end": None},
            "urgency": 0,
        }
    )

    urgency_words = ["urgent", "immediate", "asap", "critical", "deadline", "overdue"]

    for email in emails:
        process_email_topics(email, topic_stats, topic_keywords, urgency_words)

    # Convert to response format
    return build_topic_responses(topic_stats)


def build_topic_responses(
    topic_stats: dict[str, dict[str, Any]]
) -> list[DiscoveredTopic]:
    """Convert topic statistics into response format"""
    discovered_topics = []
    for topic, stats in sorted(
        topic_stats.items(), key=lambda x: int(x[1]["count"]), reverse=True
    ):
        count_val = int(stats["count"])
        if count_val > 0:
            date_range = format_date_range(stats["date_range"])
            keywords_set = (
                stats["keywords_found"]
                if isinstance(stats["keywords_found"], set)
                else set()
            )
            urgency_val = int(stats["urgency"])
            discovered_topics.append(
                DiscoveredTopic(
                    topic=topic,
                    count=count_val,
                    date_range=date_range,
                    keywords=list(keywords_set),
                    urgency_indicators=urgency_val,
                )
            )
    return discovered_topics


def format_date_range(date_range_dict: Any) -> str:
    """Format date range for display"""
    if not isinstance(date_range_dict, dict):
        return "Unknown"
    start_val = date_range_dict.get("start")
    end_val = date_range_dict.get("end")
    if isinstance(start_val, datetime) and isinstance(end_val, datetime):
        start = start_val.strftime("%b %Y")
        end = end_val.strftime("%b %Y")
        return f"{start} - {end}"
    return "Unknown"


def process_email_topics(
    email: EmailMessage,
    topic_stats: dict[str, dict[str, Any]],
    topic_keywords: dict[str, list[str]],
    urgency_words: list[str],
) -> None:
    subject_val = str(email.subject) if email.subject else ""
    body_val = str(email.body_text) if email.body_text else ""
    text_to_search = f"{subject_val} {body_val}".lower()

    # Check urgency
    urgency_count = sum(1 for word in urgency_words if word in text_to_search)

    # Match topics
    for topic, keywords in topic_keywords.items():
        matched = False
        for keyword in keywords:
            if keyword in text_to_search:
                matched = True
                keywords_set = topic_stats[topic]["keywords_found"]
                if isinstance(keywords_set, set):
                    keywords_set.add(keyword)

        if matched:
            topic_stats[topic]["count"] += 1
            topic_stats[topic]["urgency"] += urgency_count

            date_sent_val = email.date_sent
            if date_sent_val and isinstance(date_sent_val, datetime):
                update_topic_dates(topic_stats[topic], date_sent_val)


def update_topic_dates(stats: dict[str, Any], date: datetime) -> None:
    date_range = stats["date_range"]
    if isinstance(date_range, dict):
        if date_range["start"] is None:
            date_range["start"] = date
            date_range["end"] = date
        else:
            start_val = date_range["start"]
            end_val = date_range["end"]
            if isinstance(start_val, datetime):
                date_range["start"] = min(start_val, date)
            if isinstance(end_val, datetime):
                date_range["end"] = max(end_val, date)


def infer_organization_from_domain(domain: str) -> str:
    """Try to infer organization name from email domain"""
    # Remove common suffixes
    org_name = (
        domain.replace(".com", "")
        .replace(".co.uk", "")
        .replace(".org", "")
        .replace(".gov.uk", "")
    )

    # Handle common patterns
    if "council" in domain or "gov" in domain:
        parts = org_name.split(".")
        if len(parts) > 1:
            return "{parts[0].title()} Council"

    # Capitalize parts
    parts = org_name.split(".")
    if len(parts) > 1:
        return " ".join(p.title() for p in parts)

    return org_name.title()


def infer_role_from_content(emails: list[EmailMessage], domain: str) -> str | None:
    """Try to determine organization's role from email content"""
    # Simple heuristic based on domain patterns
    domain_lower = domain.lower()

    if "council" in domain_lower or "gov" in domain_lower:
        return "Council/Authority"
    elif any(arch in domain_lower for arch in ["architect", "design", "bdp", "foster"]):
        return "Architect"
    elif any(eng in domain_lower for eng in ["arup", "wsp", "engineer", "structural"]):
        return "Engineer"
    elif any(pm in domain_lower for pm in ["pm", "gleeds", "faithful"]):
        return "Project Manager"

    # Could enhance with content analysis
    return None


@router.post("/{project_id}/apply-refinement")
async def apply_refinement(
    project_id: str,
    refinement: RefinementRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """
    Apply user's refinement choices to filter emails
    """
    # Verify project access
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    # Create refinement filter record with timezone-aware timestamp
    filter_id = str(uuid.uuid4())
    applied_at_utc = datetime.now(timezone.utc)
    filter_data = {
        "exclude_projects": refinement.exclude_projects,
        "confirmed_parties": refinement.confirmed_parties,
        "exclude_people": refinement.exclude_people,
        "include_topics": refinement.include_topics,
        "custom_filters": refinement.custom_filters,
        "applied_at": applied_at_utc.isoformat(),
    }

    # In production, we'd store this in a refinement_filters table
    # For now, we'll update the project metadata
    meta_val: dict = (
        cast(Dict[str, Any], project.meta).copy()
        if (project.meta and isinstance(project.meta, dict))
        else {}
    )
    meta_val["active_refinement"] = filter_data
    project.meta = meta_val
    db.commit()

    # Apply filters to emails (mark excluded ones)
    excluded_count = 0

    # Get all emails for the project
    emails = db.query(EmailMessage).filter(EmailMessage.project_id == project_id).all()

    for email in emails:
        should_exclude = False

        # Check if email mentions excluded projects
        subject_val = str(email.subject) if email.subject else ""
        body_val = str(email.body_text) if email.body_text else ""
        email_text = f"{subject_val} {body_val}".lower()
        for excluded_project in refinement.exclude_projects:
            if excluded_project.lower() in email_text:
                should_exclude = True
                break

        # Check if from excluded people
        sender_email_val = str(email.sender_email) if email.sender_email else None
        if not should_exclude and sender_email_val:
            for excluded_person in refinement.exclude_people:
                if excluded_person.lower() in sender_email_val.lower():
                    should_exclude = True
                    break

        # Update email metadata
        if should_exclude:
            email_meta: dict = (
                cast(Dict[str, Any], email.meta).copy()
                if (email.meta and isinstance(email.meta, dict))
                else {}
            )
            email_meta["excluded_by_refinement"] = filter_id
            email.meta = email_meta
            excluded_count += 1

    db.commit()

    return {
        "success": True,
        "filter_id": filter_id,
        "stats": {
            "total_emails": len(emails),
            "excluded_emails": excluded_count,
            "remaining_emails": len(emails) - excluded_count,
        },
    }


@router.get("/{project_id}/active-filters")
async def get_active_filters(
    project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    """Get currently active refinement filters"""
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    meta_val = project.meta.copy() if project.meta else {}
    if meta_val and "active_refinement" in meta_val:
        return {"has_active_filter": True, "filter": meta_val["active_refinement"]}

    return {"has_active_filter": False}


@router.delete("/{project_id}/clear-filters")
async def clear_refinement_filters(
    project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    """Remove all refinement filters"""
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    # Clear project metadata
    meta_val = (
        cast(Dict[str, Any], project.meta).copy()
        if (project.meta and isinstance(project.meta, dict))
        else {}
    )
    if meta_val and "active_refinement" in meta_val:
        del meta_val["active_refinement"]
        project.meta = meta_val

    # Clear email exclusions
    emails = db.query(EmailMessage).filter(EmailMessage.project_id == project_id).all()

    cleared_count = 0
    for email in emails:
        email_meta = (
            cast(Dict[str, Any], email.meta).copy()
            if (email.meta and isinstance(email.meta, dict))
            else {}
        )
        if email_meta and "excluded_by_refinement" in email_meta:
            del email_meta["excluded_by_refinement"]
            email.meta = email_meta
            cleared_count += 1

    db.commit()

    return {"success": True, "emails_restored": cleared_count}
