# pyright: reportMissingTypeStubs=false, reportDeprecated=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportUnnecessaryIsInstance=false
"""
AI-Powered Document Intelligence
Provides smart classification, metadata extraction, and content insights
"""

import logging
import uuid
import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel

from .db import get_db
from .security import current_user
from .models import User, Document
from .ai_runtime import complete_chat
from .ai_settings import get_ai_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai-intelligence"])


class DocumentClassification(BaseModel):
    document_type: str  # Invoice, Contract, Report, Email, etc.
    confidence: float
    suggested_folder: str
    extracted_metadata: Dict
    key_entities: List[Dict]
    summary: Optional[str] = None
    tags: List[str]


class DocumentInsights(BaseModel):
    document_id: str
    classification: DocumentClassification
    compliance_flags: List[str]
    contains_pii: bool
    language: str
    page_count: Optional[int] = None


# Document type patterns for classification
DOCUMENT_PATTERNS = {
    "invoice": {
        "keywords": [
            "invoice",
            "bill",
            "amount due",
            "payment terms",
            "invoice number",
            "total amount",
        ],
        "patterns": [r"invoice\s*#?\s*\d+", r"total\s*amount", r"due\s*date"],
        "folder": "Finance/Invoices",
    },
    "contract": {
        "keywords": [
            "agreement",
            "contract",
            "terms and conditions",
            "party",
            "whereas",
            "hereby",
        ],
        "patterns": [r"this\s+agreement", r"effective\s+date", r"witnesseth"],
        "folder": "Legal/Contracts",
    },
    "report": {
        "keywords": [
            "executive summary",
            "findings",
            "recommendations",
            "analysis",
            "conclusion",
        ],
        "patterns": [r"executive\s+summary", r"table\s+of\s+contents"],
        "folder": "Reports",
    },
    "email": {
        "keywords": ["from:", "to:", "subject:", "re:", "dear", "best regards"],
        "patterns": [r"from:\s*\S+@\S+", r"subject:", r"sent:"],
        "folder": "Correspondence/Email",
    },
    "memo": {
        "keywords": ["memo", "memorandum", "to:", "from:", "date:", "re:"],
        "patterns": [r"memorandum", r"to:\s*\w+", r"from:\s*\w+"],
        "folder": "Internal/Memos",
    },
    "presentation": {
        "keywords": ["slide", "presentation", "agenda", "overview"],
        "patterns": [r"slide\s+\d+", r"presentation"],
        "folder": "Presentations",
    },
}

# PII patterns
PII_PATTERNS = {
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "phone": r"\b(\+\d{1,2}\s?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b",
    "date_of_birth": r"\b\d{1,2}/\d{1,2}/\d{4}\b",
}


async def classify_document(
    text: str, filename: str, db: Session
) -> DocumentClassification:
    """
    Classify document based on content analysis using LLM
    """
    if not text or not isinstance(text, str):
        logger.warning("Invalid text input for classification")
        return DocumentClassification(
            document_type="other",
            confidence=0.0,
            suggested_folder="General",
            extracted_metadata={},
            key_entities=[],
            summary=None,
            tags=[],
        )

    # Use LLM for classification
    prompt = f"""Classify this document and extract metadata.
    
    Filename: {filename}
    Content: {text[:3000]}
    
    Return JSON with:
    - document_type (e.g. Invoice, Contract, Letter, Report, Drawing, Meeting Minutes)
    - confidence (0.0-1.0)
    - suggested_folder (e.g. Commercial/Invoices, Legal/Contracts, Technical/Drawings)
    - summary (1-2 sentences)
    - tags (list of strings)
    - metadata (key-value pairs like date, amount, parties)
    """

    try:
        api_key = get_ai_api_key("openai", db) or get_ai_api_key("anthropic", db)
        if not api_key:
            # Fallback to regex if no AI key
            return _classify_document_regex(text, filename)

        provider = "openai" if get_ai_api_key("openai", db) else "anthropic"
        model = "gpt-4o-mini" if provider == "openai" else "claude-3-haiku-20240307"

        response = await complete_chat(
            provider=provider,
            model_id=model,
            prompt=prompt,
            system_prompt="You are a document classifier for a construction project management system.",
            db=db,
            max_tokens=1000,
        )

        # Parse JSON
        json_str = response
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0]

        data = json.loads(json_str.strip())

        # Extract entities separately or use what we got
        entities = await extract_entities(text, db)

        return DocumentClassification(
            document_type=data.get("document_type", "other"),
            confidence=data.get("confidence", 0.5),
            suggested_folder=data.get("suggested_folder", "General"),
            extracted_metadata=data.get("metadata", {}),
            key_entities=entities,
            summary=data.get("summary"),
            tags=data.get("tags", []),
        )

    except Exception as e:
        logger.error(f"AI classification failed: {e}")
        return _classify_document_regex(text, filename)


def _classify_document_regex(text: str, filename: str) -> DocumentClassification:
    """Fallback regex classification"""
    text_lower = text.lower()
    scores = {}

    # Score each document type
    for doc_type, patterns in DOCUMENT_PATTERNS.items():
        score = 0
        # Keyword matching
        for keyword in patterns["keywords"]:
            if keyword in text_lower:
                score += 2
        # Regex pattern matching
        for pattern in patterns["patterns"]:
            try:
                if re.search(pattern, text_lower):
                    score += 3
            except re.error:
                continue
        scores[doc_type] = score

    # Get best match
    if not scores or max(scores.values()) == 0:
        doc_type = "other"
        confidence = 0.3
        suggested_folder = "General"
    else:
        doc_type = max(scores, key=lambda k: scores[k])
        max_score = scores[doc_type]
        confidence = min(0.95, max_score / 10)
        suggested_folder = DOCUMENT_PATTERNS[doc_type]["folder"]

    return DocumentClassification(
        document_type=doc_type,
        confidence=confidence,
        suggested_folder=suggested_folder,
        extracted_metadata=extract_metadata(text),
        key_entities=[],  # Regex entity extraction is weak
        summary=generate_summary(text),
        tags=generate_tags(text, doc_type),
    )


def extract_metadata(text: str) -> Dict:
    """Extract structured metadata from text"""
    if not text or not isinstance(text, str):
        return {}

    metadata = {}

    # Extract dates
    date_patterns = [
        r"\b\d{1,2}/\d{1,2}/\d{4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b",
    ]
    dates = []
    for pattern in date_patterns:
        try:
            dates.extend(re.findall(pattern, text, re.IGNORECASE))
        except re.error:
            continue
    if dates:
        metadata["dates"] = dates[:5]

    # Extract amounts
    try:
        amounts = re.findall(r"\$\s*[\d,]+\.?\d*", text)
        if amounts:
            metadata["amounts"] = amounts[:5]
    except re.error:
        pass

    # Extract email addresses
    try:
        emails = re.findall(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", text
        )
        if emails:
            metadata["emails"] = list(set(emails))[:5]
    except re.error:
        pass

    # Extract phone numbers
    try:
        phones = re.findall(
            r"\b(\+\d{1,2}\s?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b", text
        )
        if phones:
            metadata["phone_numbers"] = phones[:3]
    except re.error:
        pass

    return metadata


async def extract_entities(text: str, db: Session) -> List[Dict]:
    """Extract named entities using LLM"""
    if not text or not isinstance(text, str):
        return []

    try:
        api_key = get_ai_api_key("openai", db) or get_ai_api_key("anthropic", db)
        if not api_key:
            return []

        prompt = f"""Extract named entities from this text.
        Return JSON list of objects with 'text', 'type' (PERSON, ORG, LOC, DATE), and 'mentions' (count).
        
        Text: {text[:2000]}
        """

        provider = "openai" if get_ai_api_key("openai", db) else "anthropic"
        model = "gpt-4o-mini" if provider == "openai" else "claude-3-haiku-20240307"

        response = await complete_chat(
            provider=provider,
            model_id=model,
            prompt=prompt,
            system_prompt="You are a Named Entity Recognition system.",
            db=db,
            max_tokens=1000,
        )

        json_str = response
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0]

        data = json.loads(json_str.strip())
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "entities" in data:
            return data["entities"]

        return []

    except Exception as e:
        logger.warning(f"Entity extraction failed: {e}")
        return []


def generate_tags(text: str, doc_type: str) -> List[str]:
    """Generate relevant tags for the document"""
    if not text or not isinstance(text, str):
        return [doc_type] if doc_type else []

    tags = [doc_type] if doc_type else []

    # Add tags based on keywords
    tag_keywords = {
        "urgent": ["urgent", "asap", "immediate"],
        "confidential": ["confidential", "private", "restricted"],
        "draft": ["draft", "preliminary", "work in progress"],
        "final": ["final", "approved", "signed"],
        "financial": ["payment", "invoice", "budget", "cost"],
        "legal": ["contract", "agreement", "terms", "liability"],
    }

    text_lower = text.lower()
    for tag, keywords in tag_keywords.items():
        if any(kw in text_lower for kw in keywords):
            tags.append(tag)

    return list(set(tags))[:8]  # Max 8 tags


def generate_summary(text: str, max_sentences: int = 2) -> str:
    """Generate a simple extractive summary"""
    if not text or not isinstance(text, str):
        return "No summary available"

    try:
        # Split into sentences
        sentences = re.split(r"[.!?]+", text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

        if not sentences:
            return "No summary available"

        # Take first N sentences as summary
        summary = ". ".join(sentences[:max_sentences])
        if len(summary) > 500:
            summary = summary[:497] + "..."

        return summary
    except Exception as e:
        logger.warning("Error generating summary: %s", str(e))
        return "No summary available"


def detect_pii(text: str) -> tuple[bool, List[str]]:
    """Detect presence of PII in document"""
    if not text or not isinstance(text, str):
        return False, []

    found_pii = []
    for pii_type, pattern in PII_PATTERNS.items():
        try:
            if re.search(pattern, text):
                found_pii.append(pii_type)
        except re.error:
            continue

    return len(found_pii) > 0, found_pii


def detect_compliance_issues(text: str, doc_type: str) -> List[str]:
    """Flag potential compliance issues"""
    if not text or not isinstance(text, str):
        return []

    flags = []
    has_pii, pii_types = detect_pii(text)
    if has_pii:
        flags.append(f"Contains PII: {', '.join(pii_types)}")

    # Check for confidential markers
    try:
        if re.search(
            r"\bconfidential\b|\bprivate\b|\brestricted\b", text, re.IGNORECASE
        ):
            flags.append("Marked as confidential")
    except re.error:
        pass

    # Check for missing dates on time-sensitive docs
    try:
        if doc_type in ["contract", "invoice"] and not re.search(
            r"\d{1,2}/\d{1,2}/\d{4}", text
        ):
            flags.append("Missing date information")
    except re.error:
        pass

    return flags


@router.post("/classify/{document_id}")
async def classify_document_endpoint(
    document_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """
    Classify a document and extract insights
    Uses AI to determine document type, suggest folders, extract metadata
    """
    try:
        doc_uuid = uuid.UUID(document_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "invalid document id")

    document = db.get(Document, doc_uuid)
    if not document or document.owner_user_id != user.id:
        raise HTTPException(404, "document not found")

    # Get document text (from text_excerpt or OCR result)
    text = document.text_excerpt or ""

    if not text or len(text) < 50:
        raise HTTPException(
            400,
            "document text not available or too short - OCR may still be processing",
        )

    # Perform classification
    classification = await classify_document(text, document.filename, db)

    # Detect compliance issues
    compliance_flags = detect_compliance_issues(text, classification.document_type)

    # Detect PII
    has_pii, pii_types = detect_pii(text)

    # Detect language (simple heuristic)
    language = detect_language(text)

    # Store classification in document metadata
    if not document.meta:
        document.meta = {}

    document.meta["ai_classification"] = {
        "type": classification.document_type,
        "confidence": classification.confidence,
        "suggested_folder": classification.suggested_folder,
        "tags": classification.tags,
        "classified_at": datetime.now(timezone.utc).isoformat(),
        "contains_pii": has_pii,
        "pii_types": pii_types,
        "compliance_flags": compliance_flags,
    }

    db.commit()

    insights = DocumentInsights(
        document_id=str(document.id),
        classification=classification,
        compliance_flags=compliance_flags,
        contains_pii=has_pii,
        language=language,
    )

    return insights


@router.get("/insights/{document_id}")
async def get_document_insights(
    document_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Get AI insights for a document"""
    try:
        doc_uuid = uuid.UUID(document_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "invalid document id")

    document = db.get(Document, doc_uuid)
    if not document or document.owner_user_id != user.id:
        raise HTTPException(404, "document not found")

    if not document.meta or "ai_classification" not in document.meta:
        # Classification not yet done
        raise HTTPException(
            404, "document not yet classified - use POST /ai/classify/{id} first"
        )

    return document.meta["ai_classification"]


@router.post("/suggest-folder/{document_id}")
async def suggest_folder(
    document_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Get AI suggestion for best folder placement"""
    try:
        doc_uuid = uuid.UUID(document_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "invalid document id")

    document = db.get(Document, doc_uuid)
    if not document or document.owner_user_id != user.id:
        raise HTTPException(404, "document not found")

    text = document.text_excerpt or ""
    if not text:
        return {
            "suggested_folder": "General",
            "confidence": 0.0,
            "reason": "No text content available",
        }

    classification = await classify_document(text, document.filename, db)

    return {
        "suggested_folder": classification.suggested_folder,
        "confidence": classification.confidence,
        "document_type": classification.document_type,
        "reason": f"Detected as {classification.document_type} document",
    }


@router.post("/auto-tag/{document_id}")
async def auto_tag_document(
    document_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Automatically generate and apply tags to document"""
    try:
        doc_uuid = uuid.UUID(document_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "invalid document id")

    document = db.get(Document, doc_uuid)
    if not document or document.owner_user_id != user.id:
        raise HTTPException(404, "document not found")

    text = document.text_excerpt or ""
    if not text:
        raise HTTPException(400, "No text content available")

    classification = await classify_document(text, document.filename, db)

    # Store tags in metadata
    if not document.meta:
        document.meta = {}

    document.meta["tags"] = classification.tags
    document.meta["auto_tagged_at"] = datetime.now(timezone.utc).isoformat()

    db.commit()

    return {
        "tags": classification.tags,
        "message": f"Applied {len(classification.tags)} tags",
    }


@router.get("/search/semantic")
async def semantic_search(
    query: str,
    limit: int = 10,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """
    Semantic search - find documents by meaning, not just keywords
    Returns similar documents even if exact words don't match
    """
    # In production, would use embeddings and vector similarity
    # For now, use enhanced keyword matching with synonyms

    # Expand query with synonyms
    synonym_map = {
        "contract": ["agreement", "terms", "deal"],
        "invoice": ["bill", "receipt", "payment"],
        "report": ["analysis", "findings", "summary"],
        "urgent": ["asap", "immediate", "priority"],
        "confidential": ["private", "restricted", "sensitive"],
    }

    expanded_terms = [query]
    for word in query.lower().split():
        if word in synonym_map:
            expanded_terms.extend(synonym_map[word])

    # Pre-lowercase terms once for performance
    expanded_terms_lower = [term.lower() for term in expanded_terms]

    docs = (
        db.query(Document)
        .filter(Document.owner_user_id == user.id, Document.text_excerpt.isnot(None))
        .limit(100)
        .all()
    )

    results = []
    for doc in docs:
        if not doc.text_excerpt:
            continue
        text_lower = doc.text_excerpt.lower()
        score = sum(text_lower.count(term) * 2 for term in expanded_terms_lower)

        if score > 0:
            results.append(
                {
                    "document_id": str(doc.id),
                    "filename": doc.filename,
                    "path": doc.path,
                    "score": score,
                    "snippet": doc.text_excerpt[:200] if doc.text_excerpt else None,
                }
            )

    # Sort by relevance
    results.sort(key=lambda x: x["score"], reverse=True)

    return {
        "query": query,
        "expanded_to": expanded_terms,
        "count": len(results[:limit]),
        "results": results[:limit],
    }


def detect_language(text: str) -> str:
    """Simple language detection"""
    if not text or not isinstance(text, str):
        return "unknown"

    # Very basic - would use langdetect or similar in production
    sample = text[:500].lower()

    # Common words in different languages
    if any(word in sample for word in ["the", "and", "is", "are", "was", "were"]):
        return "en"
    elif any(word in sample for word in ["le", "la", "les", "et", "est"]):
        return "fr"
    elif any(word in sample for word in ["der", "die", "das", "und", "ist"]):
        return "de"
    elif any(word in sample for word in ["el", "la", "los", "las", "y", "es"]):
        return "es"

    return "unknown"


@router.post("/batch-classify")
async def batch_classify_documents(
    document_ids: List[str],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Classify multiple documents in batch"""
    results = []

    for doc_id in document_ids[:100]:  # Limit to 100 at a time
        try:
            doc_uuid = uuid.UUID(doc_id)
            document = db.get(Document, doc_uuid)

            if not document or document.owner_user_id != user.id:
                continue

            text = document.text_excerpt or ""
            if len(text) < 50:
                continue

            classification = await classify_document(text, document.filename, db)

            # Store in metadata
            if not document.meta:
                document.meta = {}

            document.meta["ai_classification"] = {
                "type": classification.document_type,
                "confidence": classification.confidence,
                "suggested_folder": classification.suggested_folder,
                "tags": classification.tags,
                "classified_at": datetime.now(timezone.utc).isoformat(),
            }

            results.append(
                {
                    "document_id": doc_id,
                    "type": classification.document_type,
                    "confidence": classification.confidence,
                    "suggested_folder": classification.suggested_folder,
                }
            )

        except (ValueError, AttributeError, TypeError):
            logger.error("Failed to classify document in batch")
            continue
        except Exception:
            logger.error("Unexpected error classifying document")
            continue

    db.commit()

    return {"classified": len(results), "results": results}


# ============================================================================
# AG Grid AI Filter Query (AI Toolkit Integration)
# ============================================================================


class GridQueryRequest(BaseModel):
    """Request to translate natural language into AG Grid filter expression"""

    query: str
    grid_columns: Optional[List[Dict]] = None  # Optional column schema override


class GridFilterExpression(BaseModel):
    """AG Grid compatible filter expression"""

    filterType: str  # 'text', 'number', 'date', 'set'
    type: Optional[str] = None  # 'contains', 'equals', 'greaterThan', etc.
    filter: Optional[str] = None
    filterTo: Optional[str] = None
    values: Optional[List[str]] = None  # For set filters
    operator: Optional[str] = None  # 'AND' or 'OR'
    condition1: Optional[Dict] = None
    condition2: Optional[Dict] = None


class GridQueryResponse(BaseModel):
    """Response with AG Grid filter model"""

    success: bool
    filter_model: Dict[str, Dict]  # { columnField: filterExpression }
    explanation: str
    raw_query: str


# Column schema for the correspondence grid
CORRESPONDENCE_GRID_SCHEMA = {
    "columns": [
        {
            "field": "email_date",
            "headerName": "Date",
            "type": "date",
            "description": "Email sent date/time",
        },
        {
            "field": "email_from",
            "headerName": "From",
            "type": "text",
            "description": "Sender email address",
        },
        {
            "field": "email_to",
            "headerName": "To",
            "type": "text",
            "description": "Primary recipient email addresses",
        },
        {
            "field": "email_cc",
            "headerName": "Cc",
            "type": "text",
            "description": "CC recipient email addresses",
        },
        {
            "field": "email_subject",
            "headerName": "Subject",
            "type": "text",
            "description": "Email subject line",
        },
        {
            "field": "body_text_clean",
            "headerName": "Body",
            "type": "text",
            "description": "Email body content",
        },
        {
            "field": "matched_keywords",
            "headerName": "Keywords",
            "type": "set",
            "description": "Matched keywords/tags",
        },
        {
            "field": "pst_filename",
            "headerName": "PST File",
            "type": "text",
            "description": "Source PST file name",
        },
        {
            "field": "notes",
            "headerName": "Notes",
            "type": "text",
            "description": "Internal notes",
        },
        {
            "field": "has_attachments",
            "headerName": "Has Attachments",
            "type": "boolean",
            "description": "Whether email has attachments",
        },
        {
            "field": "programme_activity",
            "headerName": "Programme Activity",
            "type": "text",
            "description": "Mapped programme activity",
        },
    ]
}


GRID_FILTER_PROMPT = """You are an AG Grid filter expression generator for a legal correspondence management system.

Given a natural language query, generate a valid AG Grid filterModel object.

AVAILABLE COLUMNS:
{columns_json}

AG GRID FILTER TYPES:
- Text filters: {{ "filterType": "text", "type": "contains|equals|notContains|startsWith|endsWith", "filter": "value" }}
- Date filters: {{ "filterType": "date", "type": "equals|greaterThan|lessThan|inRange", "dateFrom": "YYYY-MM-DD", "dateTo": "YYYY-MM-DD" }}
- Number filters: {{ "filterType": "number", "type": "equals|greaterThan|lessThan|inRange", "filter": 123, "filterTo": 456 }}
- Set filters: {{ "filterType": "set", "values": ["value1", "value2"] }}
- Boolean: {{ "filterType": "boolean", "filter": true }}

COMBINING CONDITIONS on same column:
{{ "filterType": "text", "operator": "AND", "condition1": {{...}}, "condition2": {{...}} }}

EXAMPLES:
Query: "emails from john@example.com in 2024"
Response: {{
  "email_from": {{ "filterType": "text", "type": "contains", "filter": "john@example.com" }},
  "email_date": {{ "filterType": "date", "type": "inRange", "dateFrom": "2024-01-01", "dateTo": "2024-12-31" }}
}}

Query: "emails about construction delays with attachments"
Response: {{
  "email_subject": {{ "filterType": "text", "operator": "OR", "condition1": {{ "filterType": "text", "type": "contains", "filter": "construction" }}, "condition2": {{ "filterType": "text", "type": "contains", "filter": "delay" }} }},
  "has_attachments": {{ "filterType": "boolean", "filter": true }}
}}

Query: "emails to contractor mentioning payment"
Response: {{
  "email_to": {{ "filterType": "text", "type": "contains", "filter": "contractor" }},
  "body_text_clean": {{ "filterType": "text", "type": "contains", "filter": "payment" }}
}}

USER QUERY: {user_query}

Respond with ONLY a valid JSON object (no markdown, no explanation). The JSON should be the filterModel to apply."""


@router.post("/grid-query", response_model=GridQueryResponse)
async def ai_grid_query(
    request: GridQueryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """
    Translate natural language query into AG Grid filter expression.

    Uses AWS Bedrock (Claude) to understand the query and generate
    appropriate AG Grid filterModel compatible with the correspondence grid.

    This endpoint ONLY receives column schema, NOT actual email data.
    """
    try:
        # Use provided columns or default schema
        columns = request.grid_columns or CORRESPONDENCE_GRID_SCHEMA["columns"]
        columns_json = json.dumps(columns, indent=2)

        # Build the prompt
        prompt = GRID_FILTER_PROMPT.format(
            columns_json=columns_json, user_query=request.query
        )

        # Call AI to generate filter expression
        response = await complete_chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="You are a filter expression generator. Output only valid JSON.",
            db=db,
            temperature=0.1,  # Low temperature for consistent output
            max_tokens=1000,
        )

        # Parse the response
        response_text = response.strip()

        # Clean up markdown code blocks if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        try:
            filter_model = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse AI filter response: {e}")
            return GridQueryResponse(
                success=False,
                filter_model={},
                explanation=f"Could not parse filter expression: {str(e)}",
                raw_query=request.query,
            )

        # Validate column fields exist
        valid_fields = {col["field"] for col in columns}
        filtered_model = {k: v for k, v in filter_model.items() if k in valid_fields}

        if not filtered_model:
            return GridQueryResponse(
                success=False,
                filter_model={},
                explanation="No valid filters could be generated for your query. Try being more specific about which fields to filter.",
                raw_query=request.query,
            )

        # Generate human-readable explanation
        explanation_parts = []
        for field, expr in filtered_model.items():
            col_name = next(
                (c["headerName"] for c in columns if c["field"] == field), field
            )
            filter_type = expr.get("type", expr.get("filterType", "filter"))
            filter_val = expr.get(
                "filter", expr.get("dateFrom", expr.get("values", ""))
            )
            explanation_parts.append(f"{col_name}: {filter_type} '{filter_val}'")

        explanation = "Filtering by: " + ", ".join(explanation_parts)

        return GridQueryResponse(
            success=True,
            filter_model=filtered_model,
            explanation=explanation,
            raw_query=request.query,
        )

    except Exception as e:
        logger.error(f"AI grid query failed: {e}")
        return GridQueryResponse(
            success=False,
            filter_model={},
            explanation=f"AI query failed: {str(e)}",
            raw_query=request.query,
        )
