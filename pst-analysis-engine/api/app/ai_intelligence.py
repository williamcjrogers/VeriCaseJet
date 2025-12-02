# pyright: reportMissingTypeStubs=false, reportDeprecatedType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportUnnecessaryIsInstance=false
"""
AI-Powered Document Intelligence
Provides smart classification, metadata extraction, and content insights
"""
import logging
import uuid
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel

from .db import get_db
from .security import current_user
from .models import User, Document

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


def classify_document(text: str, filename: str) -> DocumentClassification:
    """
    Classify document based on content analysis
    Uses pattern matching and keyword analysis
    In production, would use ML model
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
        # Normalize confidence to 0-1 range
        confidence = min(0.95, max_score / 10)
        suggested_folder = DOCUMENT_PATTERNS[doc_type]["folder"]

    # Extract metadata
    metadata = extract_metadata(text)

    # Extract entities
    entities = extract_entities(text)

    # Generate tags
    tags = generate_tags(text, doc_type)

    # Generate summary (first 2 sentences)
    summary = generate_summary(text)

    return DocumentClassification(
        document_type=doc_type,
        confidence=confidence,
        suggested_folder=suggested_folder,
        extracted_metadata=metadata,
        key_entities=entities,
        summary=summary,
        tags=tags,
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


def extract_entities(text: str) -> List[Dict]:
    """Extract named entities (people, organizations, locations)"""
    if not text or not isinstance(text, str):
        return []

    try:
        capitalized = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", text)
    except re.error:
        return []

    common_words = {
        "The",
        "This",
        "That",
        "These",
        "Those",
        "A",
        "An",
        "And",
        "Or",
        "But",
    }
    potential_entities = [w for w in capitalized if w not in common_words]

    from collections import Counter

    entity_counts = Counter(potential_entities)

    entities = []
    for entity, count in entity_counts.most_common(10):
        entities.append({"text": entity, "type": "UNKNOWN", "mentions": count})

    return entities


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
    classification = classify_document(text, document.filename)

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

    classification = classify_document(text, document.filename)

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

    classification = classify_document(text, document.filename)

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

            classification = classify_document(text, document.filename)

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
