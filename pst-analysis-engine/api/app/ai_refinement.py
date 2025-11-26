"""
VeriCase AI Refinement Engine
=============================
Intelligent evidence refinement using AI to:
- Cross-reference against configured project details
- Identify other projects, codes, and references
- Detect spam, newsletters, and irrelevant content
- Ask progressive questions to filter data

This is a multi-stage, conversational refinement process that
learns from each answer to ask increasingly targeted questions.
"""

import asyncio
import logging
import uuid
import json
import re
from datetime import datetime, timezone
from typing import Any, Annotated, cast
from collections import defaultdict
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_

from .db import get_db
from .security import current_user
from .models import EmailMessage, Project, Stakeholder, Keyword, User
from .ai_settings import get_ai_api_key, get_ai_model

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-refinement", tags=["ai-refinement"])

# =============================================================================
# Constants and Configuration
# =============================================================================

LATEST_MODEL_DEFAULTS = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-20250514",
    "gemini": "gemini-2.0-flash",
}

# Spam/Newsletter detection patterns
SPAM_INDICATORS = {
    "newsletter_words": [
        "unsubscribe", "newsletter", "weekly digest", "daily digest",
        "promotional", "marketing", "click here to", "view in browser",
        "email preferences", "opt-out", "manage subscription", "automated message",
        "do not reply", "no-reply", "noreply", "auto-generated"
    ],
    "spam_domains": [
        "mailchimp", "sendgrid", "constantcontact", "hubspot", "marketo",
        "salesforce", "pardot", "mailgun", "linkedin.com", "facebook.com",
        "twitter.com", "indeed.com", "glassdoor", "eventbrite", "surveymonkey"
    ],
    "automated_subjects": [
        "out of office", "automatic reply", "delivery status", "read receipt",
        "calendar invitation", "meeting request", "meeting canceled",
        "invitation:", "accepted:", "declined:", "tentative:"
    ]
}

# Construction project patterns
PROJECT_CODE_PATTERNS = [
    r'\b([A-Z]{2,5}[-/]\d{2,6})\b',  # WGL-001, PRJ/12345
    r'\b(\d{4,6}[-/][A-Z]{2,4})\b',  # 12345-WGL
    r'\bProject\s+([A-Z0-9]{3,10})\b',  # Project ABC123
    r'\bRef[:\s]+([A-Z0-9-]{4,15})\b',  # Ref: ABC-123-DEF
    r'\bJob\s+(?:No\.?|Number)?[:\s]*([A-Z0-9-]{3,12})\b',  # Job No: 12345
    r'\bContract\s+(?:No\.?)?[:\s]*([A-Z0-9-/]{3,15})\b',  # Contract No: ABC/123
    r'\bSite[:\s]+([A-Za-z0-9\s-]{3,30})\b',  # Site: Main Street
]


# =============================================================================
# Data Models
# =============================================================================

class RefinementStage(str, Enum):
    """Stages of the refinement process"""
    INITIAL_ANALYSIS = "initial_analysis"
    PROJECT_CROSS_REF = "project_cross_reference"
    SPAM_DETECTION = "spam_detection"  
    PEOPLE_VALIDATION = "people_validation"
    TOPIC_FILTERING = "topic_filtering"
    DOMAIN_QUESTIONS = "domain_questions"
    FINAL_REVIEW = "final_review"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DetectedItem(BaseModel):
    """A detected item that needs user decision"""
    id: str
    item_type: str  # project, spam, person, domain, topic
    name: str
    description: str
    sample_emails: list[dict[str, Any]] = Field(default_factory=list)
    email_count: int
    confidence: ConfidenceLevel
    ai_reasoning: str
    recommended_action: str  # exclude, include, review
    metadata: dict[str, Any] = Field(default_factory=dict)


class RefinementQuestion(BaseModel):
    """A question for the user to answer"""
    id: str
    question_text: str
    question_type: str  # yes_no, multiple_choice, multi_select, text_input
    context: str  # Why we're asking
    options: list[dict[str, Any]] = Field(default_factory=list)
    detected_items: list[DetectedItem] = Field(default_factory=list)
    priority: int = 1  # 1 = highest
    stage: RefinementStage


class RefinementAnswer(BaseModel):
    """User's answer to a question"""
    question_id: str
    answer_value: Any  # depends on question_type
    selected_items: list[str] = Field(default_factory=list)  # IDs of items to exclude/include
    notes: str | None = None


class RefinementSession(BaseModel):
    """Complete refinement session state"""
    id: str
    project_id: str
    user_id: str
    status: str = "active"  # active, completed, cancelled
    current_stage: RefinementStage = RefinementStage.INITIAL_ANALYSIS
    questions_asked: list[RefinementQuestion] = Field(default_factory=list)
    answers_received: list[RefinementAnswer] = Field(default_factory=list)
    analysis_results: dict[str, Any] = Field(default_factory=dict)
    exclusion_rules: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AnalysisRequest(BaseModel):
    """Request to start AI analysis"""
    project_id: str
    include_spam_detection: bool = True
    include_project_detection: bool = True
    max_emails_to_analyze: int = 2000


class AnalysisResponse(BaseModel):
    """Response from AI analysis"""
    session_id: str
    status: str
    message: str
    next_questions: list[RefinementQuestion] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


# In-memory session store (production: use Redis)
_refinement_sessions: dict[str, RefinementSession] = {}


# =============================================================================
# AI Engine Class
# =============================================================================

class AIRefinementEngine:
    """
    AI-powered refinement engine that analyzes emails and generates
    intelligent questions for the user.
    """
    
    def __init__(self, db: Session, project: Project):
        self.db = db
        self.project = project
        self.openai_key = get_ai_api_key('openai', db)
        self.anthropic_key = get_ai_api_key('anthropic', db)
        self.gemini_key = get_ai_api_key('gemini', db)
        self.openai_model = get_ai_model('openai', db)
        self.anthropic_model = get_ai_model('anthropic', db)
        
        # Build project context from configuration
        self.project_context = self._build_project_context()
    
    def _build_project_context(self) -> dict[str, Any]:
        """Build comprehensive project context from configuration"""
        context = {
            "project_name": self.project.project_name,
            "project_code": self.project.project_code,
            "aliases": [],
            "site_address": None,
            "include_domains": [],
            "exclude_people": [],
            "project_terms": [],
            "exclude_keywords": [],
            "stakeholders": [],
            "keywords": [],
        }
        
        # Parse project fields
        if self.project.project_aliases:
            context["aliases"] = [a.strip() for a in self.project.project_aliases.split(',') if a.strip()]
        
        if self.project.site_address:
            context["site_address"] = self.project.site_address
        
        if self.project.include_domains:
            context["include_domains"] = [d.strip() for d in self.project.include_domains.split(',') if d.strip()]
        
        if self.project.exclude_people:
            context["exclude_people"] = [p.strip() for p in self.project.exclude_people.split(',') if p.strip()]
        
        if self.project.project_terms:
            context["project_terms"] = [t.strip() for t in self.project.project_terms.split(',') if t.strip()]
        
        if self.project.exclude_keywords:
            context["exclude_keywords"] = [k.strip() for k in self.project.exclude_keywords.split(',') if k.strip()]
        
        # Get configured stakeholders
        stakeholders = self.db.query(Stakeholder).filter(
            Stakeholder.project_id == str(self.project.id)
        ).all()
        context["stakeholders"] = [
            {"name": s.name, "role": s.role, "email": s.email, "organization": s.organization}
            for s in stakeholders
        ]
        
        # Get configured keywords
        keywords = self.db.query(Keyword).filter(
            Keyword.project_id == str(self.project.id)
        ).all()
        context["keywords"] = [
            {"keyword": k.keyword_name, "variations": k.variations}
            for k in keywords
        ]
        
        return context
    
    async def _call_llm(self, prompt: str, system_prompt: str = "") -> str:
        """Call the best available LLM"""
        # Prefer Anthropic for analysis tasks
        if self.anthropic_key:
            return await self._call_anthropic(prompt, system_prompt)
        
        if self.openai_key:
            return await self._call_openai(prompt, system_prompt)
        
        if self.gemini_key:
            return await self._call_gemini(prompt, system_prompt)
        
        raise HTTPException(500, "No AI providers configured. Please add API keys in Admin Settings.")
    
    async def _call_openai(self, prompt: str, system_prompt: str = "") -> str:
        import openai
        client = openai.AsyncOpenAI(api_key=self.openai_key)
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = await client.chat.completions.create(
            model=self.openai_model or LATEST_MODEL_DEFAULTS["openai"],
            messages=messages,
            max_tokens=4000,
            temperature=0.2
        )
        return response.choices[0].message.content or ""
    
    async def _call_anthropic(self, prompt: str, system_prompt: str = "") -> str:
        import anthropic
        
        def sync_call():
            client = anthropic.Anthropic(api_key=self.anthropic_key)
            response = client.messages.create(
                model=self.anthropic_model or LATEST_MODEL_DEFAULTS["anthropic"],
                max_tokens=4000,
                system=system_prompt or "You are an expert legal analyst specializing in construction disputes and e-discovery.",
                messages=[{"role": "user", "content": prompt}]
            )
            text = ""
            for block in response.content:
                text_piece = getattr(block, "text", "")
                if text_piece:
                    text += str(text_piece)
            return text
        
        return await asyncio.to_thread(sync_call)
    
    async def _call_gemini(self, prompt: str, system_prompt: str = "") -> str:
        import google.generativeai as genai
        genai.configure(api_key=self.gemini_key)
        
        model = genai.GenerativeModel(LATEST_MODEL_DEFAULTS["gemini"])
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        response = await asyncio.to_thread(model.generate_content, full_prompt)
        return str(getattr(response, "text", ""))
    
    async def analyze_for_other_projects(
        self, 
        emails: list[EmailMessage]
    ) -> list[DetectedItem]:
        """
        Use AI to intelligently detect references to other projects
        that don't match the configured project.
        """
        # Extract potential project references using patterns
        project_refs: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "count": 0, "samples": [], "sources": set()
        })
        
        # Build list of known project identifiers to ignore
        known_identifiers = {self.project.project_name.lower(), self.project.project_code.lower()}
        for alias in self.project_context["aliases"]:
            known_identifiers.add(alias.lower())
        
        # Extract references from emails
        for email in emails:
            text = f"{email.subject or ''} {email.body_text or ''}"
            
            for pattern in PROJECT_CODE_PATTERNS:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    ref = match.strip()
                    if len(ref) >= 3 and ref.lower() not in known_identifiers:
                        project_refs[ref]["count"] += 1
                        if len(project_refs[ref]["samples"]) < 3:
                            project_refs[ref]["samples"].append({
                                "subject": email.subject,
                                "date": email.date_sent.isoformat() if email.date_sent else None,
                                "sender": email.sender_email
                            })
        
        # Filter to significant references
        significant_refs = {
            ref: data for ref, data in project_refs.items() 
            if data["count"] >= 3
        }
        
        if not significant_refs:
            return []
        
        # Use AI to analyze these references
        refs_summary = json.dumps({
            ref: {"count": data["count"], "samples": data["samples"][:2]}
            for ref, data in list(significant_refs.items())[:20]
        }, indent=2)
        
        system_prompt = """You are an expert at analyzing construction project correspondence.
Your task is to identify references to OTHER projects that are NOT the main project being analyzed.

You must distinguish between:
- References to OTHER separate projects (should be flagged for exclusion)
- Sub-projects or phases of the MAIN project (should NOT be flagged)
- Generic reference codes that aren't projects (invoice numbers, PO numbers, etc.)"""

        prompt = f"""Analyze these potential project references found in emails.

MAIN PROJECT CONTEXT:
- Project Name: {self.project.project_name}
- Project Code: {self.project.project_code}
- Aliases: {', '.join(self.project_context['aliases']) or 'None'}
- Site Address: {self.project_context['site_address'] or 'Not specified'}
- Key Terms: {', '.join(self.project_context['project_terms']) or 'None'}

DETECTED REFERENCES:
{refs_summary}

For each reference, determine:
1. Is this a DIFFERENT project (not a sub-project or phase of {self.project.project_name})?
2. How confident are you? (high/medium/low)
3. Why do you think this?

Output JSON array:
[
  {{
    "reference": "the code or name",
    "is_other_project": true/false,
    "confidence": "high/medium/low",
    "reasoning": "explanation",
    "recommended_action": "exclude" or "keep" or "review"
  }}
]

Only include references that appear to be OTHER projects (is_other_project: true).
"""

        response = await self._call_llm(prompt, system_prompt)
        
        # Parse AI response
        detected_items = []
        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
            
            ai_results = json.loads(json_str.strip())
            
            for result in ai_results:
                if result.get("is_other_project"):
                    ref = result["reference"]
                    ref_data = significant_refs.get(ref, {"count": 0, "samples": []})
                    
                    detected_items.append(DetectedItem(
                        id=f"proj_{uuid.uuid4().hex[:8]}",
                        item_type="other_project",
                        name=ref,
                        description=f"Project reference '{ref}' found {ref_data['count']} times",
                        sample_emails=ref_data["samples"],
                        email_count=ref_data["count"],
                        confidence=ConfidenceLevel(result.get("confidence", "medium")),
                        ai_reasoning=result.get("reasoning", ""),
                        recommended_action=result.get("recommended_action", "review"),
                        metadata={"pattern_matches": ref_data}
                    ))
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse AI response for project detection: {e}")
        
        return detected_items
    
    async def analyze_for_spam(
        self, 
        emails: list[EmailMessage]
    ) -> list[DetectedItem]:
        """
        Detect spam, newsletters, automated messages, and irrelevant content.
        """
        spam_candidates: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "count": 0, 
            "samples": [], 
            "reasons": set(),
            "domain": None,
            "sender": None
        })
        
        for email in emails:
            spam_score = 0
            reasons = set()
            
            subject_lower = (email.subject or "").lower()
            body_lower = (email.body_text or "").lower()
            sender_email = (email.sender_email or "").lower()
            sender_domain = sender_email.split('@')[-1] if '@' in sender_email else ""
            
            # Check newsletter/unsubscribe indicators
            for word in SPAM_INDICATORS["newsletter_words"]:
                if word in body_lower or word in subject_lower:
                    spam_score += 2
                    reasons.add(f"Contains '{word}'")
            
            # Check spam domains
            for domain in SPAM_INDICATORS["spam_domains"]:
                if domain in sender_domain or domain in sender_email:
                    spam_score += 3
                    reasons.add(f"From marketing/social domain: {domain}")
            
            # Check automated subjects
            for pattern in SPAM_INDICATORS["automated_subjects"]:
                if pattern in subject_lower:
                    spam_score += 2
                    reasons.add(f"Automated message: '{pattern}'")
            
            # Check for HTML-heavy content with minimal text (typical of newsletters)
            if email.body_html and len(email.body_html) > 5000:
                body_text_len = len(email.body_text or "")
                if body_text_len < 500:
                    spam_score += 1
                    reasons.add("HTML-heavy with minimal text content")
            
            # Group by sender domain for bulk detection
            if spam_score >= 2:
                key = sender_domain or sender_email
                spam_candidates[key]["count"] += 1
                spam_candidates[key]["reasons"].update(reasons)
                spam_candidates[key]["domain"] = sender_domain
                spam_candidates[key]["sender"] = email.sender_name or sender_email
                if len(spam_candidates[key]["samples"]) < 3:
                    spam_candidates[key]["samples"].append({
                        "subject": email.subject,
                        "date": email.date_sent.isoformat() if email.date_sent else None,
                        "sender": sender_email
                    })
        
        # Convert to detected items
        detected_items = []
        for key, data in sorted(spam_candidates.items(), key=lambda x: x[1]["count"], reverse=True):
            if data["count"] >= 2:  # At least 2 emails to consider bulk
                confidence = ConfidenceLevel.HIGH if data["count"] >= 5 else ConfidenceLevel.MEDIUM
                
                detected_items.append(DetectedItem(
                    id=f"spam_{uuid.uuid4().hex[:8]}",
                    item_type="spam_newsletter",
                    name=data["sender"] or key,
                    description=f"Potential spam/newsletter from {key} ({data['count']} emails)",
                    sample_emails=data["samples"],
                    email_count=data["count"],
                    confidence=confidence,
                    ai_reasoning=f"Detected indicators: {', '.join(list(data['reasons'])[:3])}",
                    recommended_action="exclude" if data["count"] >= 5 else "review",
                    metadata={
                        "domain": data["domain"],
                        "reasons": list(data["reasons"])
                    }
                ))
        
        return detected_items[:20]  # Top 20 spam candidates
    
    async def analyze_domains_and_people(
        self, 
        emails: list[EmailMessage]
    ) -> tuple[list[DetectedItem], list[DetectedItem]]:
        """
        Analyze email domains and people, cross-referencing with project config.
        """
        domain_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "count": 0, "people": set(), "first_seen": None, "last_seen": None
        })
        
        known_domains = set(d.lower() for d in self.project_context["include_domains"])
        excluded_people = set(p.lower() for p in self.project_context["exclude_people"])
        known_stakeholder_emails = set(
            s["email"].lower() for s in self.project_context["stakeholders"] 
            if s.get("email")
        )
        
        for email in emails:
            sender_email = (email.sender_email or "").lower()
            if '@' not in sender_email:
                continue
            
            domain = sender_email.split('@')[-1]
            sender_name = email.sender_name or sender_email.split('@')[0]
            
            domain_stats[domain]["count"] += 1
            domain_stats[domain]["people"].add(sender_name)
            
            if email.date_sent:
                if not domain_stats[domain]["first_seen"] or email.date_sent < domain_stats[domain]["first_seen"]:
                    domain_stats[domain]["first_seen"] = email.date_sent
                if not domain_stats[domain]["last_seen"] or email.date_sent > domain_stats[domain]["last_seen"]:
                    domain_stats[domain]["last_seen"] = email.date_sent
        
        # Identify unknown domains (not in project config)
        unknown_domains = []
        for domain, stats in sorted(domain_stats.items(), key=lambda x: x[1]["count"], reverse=True):
            if domain not in known_domains and stats["count"] >= 3:
                # Check if any stakeholders are from this domain
                is_stakeholder_domain = any(
                    domain in s.get("email", "").lower() 
                    for s in self.project_context["stakeholders"]
                )
                
                if not is_stakeholder_domain:
                    unknown_domains.append(DetectedItem(
                        id=f"domain_{uuid.uuid4().hex[:8]}",
                        item_type="unknown_domain",
                        name=domain,
                        description=f"Unknown domain with {stats['count']} emails from {len(stats['people'])} people",
                        sample_emails=[],
                        email_count=stats["count"],
                        confidence=ConfidenceLevel.MEDIUM,
                        ai_reasoning=f"Domain not in project configuration. People: {', '.join(list(stats['people'])[:5])}",
                        recommended_action="review",
                        metadata={
                            "people": list(stats["people"]),
                            "first_seen": stats["first_seen"].isoformat() if stats["first_seen"] else None,
                            "last_seen": stats["last_seen"].isoformat() if stats["last_seen"] else None
                        }
                    ))
        
        # Identify high-volume senders not in stakeholders
        people_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "count": 0, "domain": None
        })
        
        for email in emails:
            sender_email = (email.sender_email or "").lower()
            if sender_email and sender_email not in known_stakeholder_emails:
                people_stats[sender_email]["count"] += 1
                people_stats[sender_email]["name"] = email.sender_name
                if '@' in sender_email:
                    people_stats[sender_email]["domain"] = sender_email.split('@')[-1]
        
        unknown_people = []
        for email_addr, stats in sorted(people_stats.items(), key=lambda x: x[1]["count"], reverse=True)[:30]:
            if stats["count"] >= 5:
                # Check if this person should be excluded
                is_excluded = any(
                    excl.lower() in email_addr or excl.lower() in (stats.get("name", "").lower())
                    for excl in excluded_people
                )
                
                unknown_people.append(DetectedItem(
                    id=f"person_{uuid.uuid4().hex[:8]}",
                    item_type="unknown_person",
                    name=stats.get("name") or email_addr,
                    description=f"Sender with {stats['count']} emails, not in stakeholder list",
                    sample_emails=[],
                    email_count=stats["count"],
                    confidence=ConfidenceLevel.MEDIUM,
                    ai_reasoning=f"Email: {email_addr}, Domain: {stats.get('domain')}",
                    recommended_action="exclude" if is_excluded else "review",
                    metadata={
                        "email": email_addr,
                        "domain": stats.get("domain"),
                        "pre_excluded": is_excluded
                    }
                ))
        
        return unknown_domains[:15], unknown_people[:20]
    
    async def generate_intelligent_questions(
        self,
        session: RefinementSession,
        detected_projects: list[DetectedItem],
        detected_spam: list[DetectedItem],
        detected_domains: list[DetectedItem],
        detected_people: list[DetectedItem],
        total_emails: int
    ) -> list[RefinementQuestion]:
        """
        Generate a set of intelligent questions based on the analysis.
        """
        questions = []
        
        # Question 1: Project cross-references
        if detected_projects:
            questions.append(RefinementQuestion(
                id=f"q_{uuid.uuid4().hex[:8]}",
                question_text=f"I found references to {len(detected_projects)} other projects in the emails. These appear to be separate from '{self.project.project_name}'. Should I exclude emails that primarily relate to these other projects?",
                question_type="multi_select",
                context=f"Your project is '{self.project.project_name}' (code: {self.project.project_code}). The AI detected what appear to be references to other, unrelated projects. Excluding these will help focus your analysis on relevant correspondence only.",
                options=[
                    {"value": "exclude_all", "label": "Exclude all emails mentioning other projects"},
                    {"value": "select_individual", "label": "Let me review and select which to exclude"},
                    {"value": "keep_all", "label": "Keep all emails (these might be related)"}
                ],
                detected_items=detected_projects,
                priority=1,
                stage=RefinementStage.PROJECT_CROSS_REF
            ))
        
        # Question 2: Spam and newsletters
        if detected_spam:
            total_spam_count = sum(item.email_count for item in detected_spam)
            questions.append(RefinementQuestion(
                id=f"q_{uuid.uuid4().hex[:8]}",
                question_text=f"I identified {total_spam_count} emails that appear to be spam, newsletters, or automated messages from {len(detected_spam)} sources. Should I exclude these?",
                question_type="multi_select",
                context="These emails contain unsubscribe links, marketing language, or come from automated systems. They're unlikely to be relevant to your construction dispute analysis.",
                options=[
                    {"value": "exclude_all", "label": f"Exclude all {total_spam_count} spam/newsletter emails"},
                    {"value": "select_individual", "label": "Let me review each source"},
                    {"value": "keep_all", "label": "Keep all (I need to review these manually)"}
                ],
                detected_items=detected_spam,
                priority=2,
                stage=RefinementStage.SPAM_DETECTION
            ))
        
        # Question 3: Unknown domains
        if detected_domains:
            questions.append(RefinementQuestion(
                id=f"q_{uuid.uuid4().hex[:8]}",
                question_text=f"I found emails from {len(detected_domains)} domains that aren't in your project configuration. Can you tell me which of these are relevant parties?",
                question_type="multi_select",
                context="Understanding who the key parties are helps filter out irrelevant correspondence. Mark domains that should be INCLUDED in your analysis.",
                options=[
                    {"value": "add_to_project", "label": "Add selected domains to project stakeholders"},
                    {"value": "exclude_selected", "label": "Exclude emails from unselected domains"},
                    {"value": "review_later", "label": "Skip for now, I'll review later"}
                ],
                detected_items=detected_domains,
                priority=3,
                stage=RefinementStage.DOMAIN_QUESTIONS
            ))
        
        # Question 4: High-volume unknown senders
        high_volume_unknown = [p for p in detected_people if p.email_count >= 10]
        if high_volume_unknown:
            questions.append(RefinementQuestion(
                id=f"q_{uuid.uuid4().hex[:8]}",
                question_text=f"These {len(high_volume_unknown)} people sent many emails but aren't in your stakeholder list. Who are they?",
                question_type="categorize",
                context="Identifying who these people are helps understand the correspondence structure. You can categorize them by their role.",
                options=[
                    {"value": "client", "label": "Client/Employer"},
                    {"value": "contractor", "label": "Main Contractor"},
                    {"value": "subcontractor", "label": "Subcontractor"},
                    {"value": "consultant", "label": "Consultant/Professional"},
                    {"value": "exclude", "label": "Not relevant - exclude"},
                    {"value": "unknown", "label": "I don't know"}
                ],
                detected_items=high_volume_unknown,
                priority=4,
                stage=RefinementStage.PEOPLE_VALIDATION
            ))
        
        # Question 5: Date range validation
        questions.append(RefinementQuestion(
            id=f"q_{uuid.uuid4().hex[:8]}",
            question_text="What date range should I focus on for this analysis?",
            question_type="date_range",
            context=f"You have {total_emails} emails. Narrowing the date range can help focus on the most relevant period of the dispute.",
            options=[
                {"value": "all", "label": "Analyze all dates"},
                {"value": "custom", "label": "Set custom date range"},
                {"value": "last_year", "label": "Last 12 months only"},
                {"value": "last_2_years", "label": "Last 2 years"}
            ],
            detected_items=[],
            priority=5,
            stage=RefinementStage.DOMAIN_QUESTIONS
        ))
        
        return questions


# =============================================================================
# API Endpoints
# =============================================================================

@router.post("/analyze", response_model=AnalysisResponse)
async def start_ai_analysis(
    request: AnalysisRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)]
):
    """
    Start AI-powered analysis of project emails.
    Returns a session ID and first set of questions.
    """
    # Verify project
    project = db.query(Project).filter_by(id=request.project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    
    # Create session
    session_id = str(uuid.uuid4())
    session = RefinementSession(
        id=session_id,
        project_id=request.project_id,
        user_id=str(user.id),
        status="analyzing"
    )
    _refinement_sessions[session_id] = session
    
    # Get emails for analysis
    emails = db.query(EmailMessage).filter(
        EmailMessage.project_id == request.project_id
    ).order_by(EmailMessage.date_sent.desc()).limit(request.max_emails_to_analyze).all()
    
    if not emails:
        raise HTTPException(400, "No emails found in project")
    
    # Run AI analysis
    engine = AIRefinementEngine(db, project)
    
    try:
        # Run analysis tasks
        detected_projects = []
        detected_spam = []
        detected_domains = []
        detected_people = []
        
        if request.include_project_detection:
            detected_projects = await engine.analyze_for_other_projects(emails)
        
        if request.include_spam_detection:
            detected_spam = await engine.analyze_for_spam(emails)
        
        detected_domains, detected_people = await engine.analyze_domains_and_people(emails)
        
        # Generate questions
        questions = await engine.generate_intelligent_questions(
            session,
            detected_projects,
            detected_spam,
            detected_domains,
            detected_people,
            len(emails)
        )
        
        # Update session
        session.analysis_results = {
            "total_emails": len(emails),
            "detected_projects": [p.model_dump() for p in detected_projects],
            "detected_spam": [s.model_dump() for s in detected_spam],
            "detected_domains": [d.model_dump() for d in detected_domains],
            "detected_people": [p.model_dump() for p in detected_people],
        }
        session.questions_asked = questions
        session.status = "awaiting_answers"
        session.current_stage = RefinementStage.PROJECT_CROSS_REF if detected_projects else RefinementStage.SPAM_DETECTION
        
        return AnalysisResponse(
            session_id=session_id,
            status="ready",
            message=f"Analysis complete. Analyzed {len(emails)} emails and generated {len(questions)} questions.",
            next_questions=questions,
            summary={
                "total_emails": len(emails),
                "other_projects_found": len(detected_projects),
                "spam_sources_found": len(detected_spam),
                "unknown_domains": len(detected_domains),
                "unknown_people": len(detected_people),
            }
        )
        
    except Exception as e:
        logger.exception(f"AI analysis failed: {e}")
        session.status = "failed"
        raise HTTPException(500, f"Analysis failed: {str(e)}")


@router.post("/answer")
async def submit_answer(
    answer: RefinementAnswer,
    session_id: str = Query(..., description="Session ID"),
    user: Annotated[User, Depends(current_user)] = None,
    db: Annotated[Session, Depends(get_db)] = None
):
    """
    Submit an answer to a refinement question.
    Returns the next question or final summary.
    """
    session = _refinement_sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    
    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")
    
    # Record answer
    session.answers_received.append(answer)
    session.updated_at = datetime.now(timezone.utc)
    
    # Process answer and build exclusion rules
    question = next((q for q in session.questions_asked if q.id == answer.question_id), None)
    if question:
        if question.stage == RefinementStage.PROJECT_CROSS_REF:
            if answer.answer_value == "exclude_all":
                session.exclusion_rules["exclude_project_refs"] = [
                    item.name for item in question.detected_items
                ]
            elif answer.answer_value == "select_individual":
                session.exclusion_rules["exclude_project_refs"] = answer.selected_items
        
        elif question.stage == RefinementStage.SPAM_DETECTION:
            if answer.answer_value == "exclude_all":
                session.exclusion_rules["exclude_spam_domains"] = [
                    item.metadata.get("domain") for item in question.detected_items
                    if item.metadata.get("domain")
                ]
            elif answer.answer_value == "select_individual":
                session.exclusion_rules["exclude_spam_domains"] = answer.selected_items
    
    # Find next unanswered question
    answered_ids = {a.question_id for a in session.answers_received}
    remaining = [q for q in session.questions_asked if q.id not in answered_ids]
    
    if remaining:
        return {
            "status": "more_questions",
            "next_question": remaining[0],
            "questions_remaining": len(remaining),
            "progress": len(session.answers_received) / len(session.questions_asked)
        }
    else:
        session.status = "ready_to_apply"
        return {
            "status": "complete",
            "message": "All questions answered. Ready to apply refinement.",
            "exclusion_rules": session.exclusion_rules,
            "summary": session.analysis_results
        }


@router.post("/{session_id}/apply")
async def apply_refinement(
    session_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)]
):
    """
    Apply the refinement rules to exclude emails.
    """
    session = _refinement_sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    
    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")
    
    # Get project
    project = db.query(Project).filter_by(id=session.project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    
    # Apply exclusion rules
    excluded_count = 0
    rules = session.exclusion_rules
    
    emails = db.query(EmailMessage).filter(
        EmailMessage.project_id == session.project_id
    ).all()
    
    for email in emails:
        should_exclude = False
        exclude_reason = None
        
        # Check project references
        if rules.get("exclude_project_refs"):
            text = f"{email.subject or ''} {email.body_text or ''}".lower()
            for ref in rules["exclude_project_refs"]:
                if ref.lower() in text:
                    should_exclude = True
                    exclude_reason = f"other_project:{ref}"
                    break
        
        # Check spam domains
        if not should_exclude and rules.get("exclude_spam_domains"):
            sender_domain = (email.sender_email or "").split('@')[-1].lower()
            if sender_domain in [d.lower() for d in rules["exclude_spam_domains"]]:
                should_exclude = True
                exclude_reason = f"spam:{sender_domain}"
        
        # Check excluded people
        if not should_exclude and rules.get("exclude_people"):
            sender = (email.sender_email or "").lower()
            if sender in [p.lower() for p in rules["exclude_people"]]:
                should_exclude = True
                exclude_reason = f"excluded_person:{sender}"
        
        if should_exclude:
            meta = dict(email.meta) if email.meta else {}
            meta["ai_excluded"] = True
            meta["ai_exclude_reason"] = exclude_reason
            meta["ai_exclude_session"] = session_id
            email.meta = meta
            excluded_count += 1
    
    # Save refinement to project
    project_meta = dict(project.meta) if project.meta else {}
    project_meta["ai_refinement"] = {
        "session_id": session_id,
        "rules": rules,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "excluded_count": excluded_count
    }
    project.meta = project_meta
    
    db.commit()
    
    session.status = "applied"
    
    return {
        "success": True,
        "session_id": session_id,
        "excluded_count": excluded_count,
        "total_emails": len(emails),
        "remaining_emails": len(emails) - excluded_count
    }


@router.get("/session/{session_id}")
async def get_session_status(
    session_id: str,
    user: Annotated[User, Depends(current_user)]
):
    """Get the current status of a refinement session"""
    session = _refinement_sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    
    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")
    
    return {
        "session_id": session.id,
        "status": session.status,
        "current_stage": session.current_stage.value,
        "questions_total": len(session.questions_asked),
        "questions_answered": len(session.answers_received),
        "analysis_summary": session.analysis_results.get("summary", {}),
        "exclusion_rules": session.exclusion_rules
    }


@router.delete("/session/{session_id}")
async def cancel_session(
    session_id: str,
    user: Annotated[User, Depends(current_user)]
):
    """Cancel a refinement session"""
    session = _refinement_sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    
    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")
    
    session.status = "cancelled"
    del _refinement_sessions[session_id]
    
    return {"success": True, "message": "Session cancelled"}

