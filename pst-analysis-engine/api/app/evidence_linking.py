"""
Evidence Linking Engine
Intelligent linking between evidence items and correspondence
"""

import re
import uuid
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func

from .models import (
    EvidenceItem, EvidenceCorrespondenceLink, EvidenceRelation,
    EmailMessage, EmailAttachment, Stakeholder, Keyword,
    Case, Project, User
)

logger = logging.getLogger(__name__)


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class LinkSuggestion:
    """A suggested link between evidence and correspondence"""
    email_id: str
    email_subject: Optional[str]
    email_sender: Optional[str]
    email_date: Optional[datetime]
    link_type: str
    confidence: int  # 0-100
    method: str  # How the link was detected
    context: Optional[str] = None  # Why we think they're linked


@dataclass
class ClassificationResult:
    """Result of evidence type classification"""
    evidence_type: str
    document_category: Optional[str]
    confidence: int
    method: str
    extracted_data: Dict[str, Any]


# ============================================================================
# CLASSIFICATION PATTERNS
# ============================================================================

# File extension to evidence type mapping
FILE_TYPE_MAPPING = {
    # Drawings
    'dwg': 'drawing',
    'dxf': 'drawing',
    'dgn': 'drawing',
    'rvt': 'drawing',
    'ifc': 'drawing',
    
    # Images (often photos)
    'jpg': 'photo',
    'jpeg': 'photo',
    'png': 'photo',
    'tif': 'photo',
    'tiff': 'photo',
    'heic': 'photo',
    
    # Programmes
    'mpp': 'programme',
    'pp': 'programme',
    'xer': 'programme',
    'xml': None,  # Could be programme or other
    
    # Generic documents
    'pdf': None,
    'doc': None,
    'docx': None,
    'xls': None,
    'xlsx': None,
}

# Filename patterns for classification
FILENAME_PATTERNS = [
    # Drawings
    (r'(drawing|drg|dwg|plan|elevation|section|detail)[_\-\s]?\d*', 'drawing', 70),
    (r'(ga|general\s*arrangement)', 'drawing', 60),
    (r'(sk|sketch)[_\-\s]?\d+', 'drawing', 50),
    
    # Contracts and variations
    (r'(contract|agreement|deed)', 'contract', 80),
    (r'(variation|vo|change\s*order|co)[_\-\s]?\d+', 'variation', 80),
    (r'(amendment|addendum)', 'contract', 60),
    
    # Financial
    (r'(invoice|inv)[_\-\s]?\d+', 'invoice', 85),
    (r'(payment\s*(cert|certificate|application))', 'payment_certificate', 80),
    (r'(valuation)[_\-\s]?\d+', 'payment_certificate', 70),
    (r'(ipc|interim\s*payment)', 'payment_certificate', 75),
    
    # Notices
    (r'(notice)[_\-\s]?\d*', 'notice', 60),
    (r'(eot|extension\s*of\s*time)', 'eot_notice', 85),
    (r'(delay\s*notice|dn)[_\-\s]?\d*', 'delay_notice', 80),
    (r'(ew|early\s*warning)', 'notice', 70),
    
    # Instructions
    (r'(site\s*instruction|si)[_\-\s]?\d+', 'site_instruction', 85),
    (r'(ai|architect.*instruction)', 'site_instruction', 75),
    (r'(rfi|request\s*for\s*information)[_\-\s]?\d*', 'rfi', 85),
    
    # Meeting minutes
    (r'(minutes|mom|meeting\s*notes)', 'meeting_minutes', 80),
    (r'(progress\s*meeting)', 'meeting_minutes', 70),
    
    # Reports
    (r'(progress\s*report|pr)[_\-\s]?\d*', 'progress_report', 75),
    (r'(expert\s*report|witness\s*statement)', 'expert_report', 80),
    (r'(quality|qa|qc)\s*(report|record)', 'quality_record', 70),
    
    # Claims
    (r'(claim)[_\-\s]?\d*', 'claim', 70),
    
    # Letters
    (r'(letter|correspondence)', 'letter', 50),
    
    # Specifications
    (r'(spec|specification)', 'specification', 75),
]

# Content patterns for classification (applied to extracted text)
CONTENT_PATTERNS = [
    # JCT specific
    (r'(relevant\s*event|clause\s*2\.29)', 'jct_relevant_event', 75),
    (r'(extension\s*of\s*time|clause\s*2\.28)', 'jct_extension_time', 70),
    (r'(loss\s*and\s*expense|clause\s*4\.23)', 'jct_loss_expense', 70),
    
    # NEC specific
    (r'(compensation\s*event|ce\s*\d+)', 'nec_compensation_event', 75),
    (r'(early\s*warning|ew\s*\d+)', 'nec_early_warning', 75),
    
    # General construction
    (r'(critical\s*path|float|delay\s*analysis)', 'technical', 60),
    (r'(defect|snag|punch\s*list)', 'quality_record', 65),
]

# Reference number patterns
REFERENCE_PATTERNS = [
    (r'\b(DRG|DRAWING)[_\-\s]?(\d+[A-Z]?)\b', 'drawing_ref'),
    (r'\b(VI|VO|VARIATION)[_\-\s]?(\d+)\b', 'variation_ref'),
    (r'\b(SI|SITE\s*INSTRUCTION)[_\-\s]?(\d+)\b', 'site_instruction_ref'),
    (r'\b(RFI)[_\-\s]?(\d+)\b', 'rfi_ref'),
    (r'\b(INV|INVOICE)[_\-\s]?(\d+)\b', 'invoice_ref'),
    (r'\b(IPC|PAY\s*APP)[_\-\s]?(\d+)\b', 'payment_ref'),
    (r'\b(PR|PROGRESS\s*REPORT)[_\-\s]?(\d+)\b', 'report_ref'),
    (r'\b(MOM|MINUTES)[_\-\s]?(\d+)\b', 'meeting_ref'),
]

# Amount patterns
AMOUNT_PATTERNS = [
    (r'£\s*([\d,]+(?:\.\d{2})?)', 'GBP'),
    (r'\$\s*([\d,]+(?:\.\d{2})?)', 'USD'),
    (r'€\s*([\d,]+(?:\.\d{2})?)', 'EUR'),
    (r'([\d,]+(?:\.\d{2})?)\s*(?:pounds|GBP)', 'GBP'),
]

# Date patterns
DATE_PATTERNS = [
    r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})\b',
    r'\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{2,4})\b',
]


# ============================================================================
# CLASSIFICATION ENGINE
# ============================================================================

class EvidenceClassifier:
    """Classifies evidence items based on filename and content"""
    
    def classify(
        self,
        filename: str,
        file_type: Optional[str] = None,
        extracted_text: Optional[str] = None
    ) -> ClassificationResult:
        """
        Classify an evidence item
        Returns evidence type, category, and extracted metadata
        """
        evidence_type = 'other'
        document_category = None
        confidence = 0
        method = 'default'
        extracted_data: Dict[str, Any] = {
            'references': [],
            'amounts': [],
            'dates': [],
            'parties': []
        }
        
        filename_lower = filename.lower()
        
        # 1. Check file extension first
        if file_type and file_type.lower() in FILE_TYPE_MAPPING:
            mapped_type = FILE_TYPE_MAPPING[file_type.lower()]
            if mapped_type:
                evidence_type = mapped_type
                confidence = 40
                method = 'file_extension'
        
        # 2. Check filename patterns
        for pattern, ptype, pconf in FILENAME_PATTERNS:
            if re.search(pattern, filename_lower, re.IGNORECASE):
                if pconf > confidence:
                    evidence_type = ptype
                    confidence = pconf
                    method = 'filename_pattern'
                break
        
        # 3. Check content patterns if we have extracted text
        if extracted_text:
            text_lower = extracted_text.lower()
            
            for pattern, cat, pconf in CONTENT_PATTERNS:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    document_category = cat
                    if pconf > confidence:
                        confidence = pconf
                        method = 'content_pattern'
                    break
            
            # 4. Extract references
            for pattern, ref_type in REFERENCE_PATTERNS:
                matches = re.findall(pattern, extracted_text, re.IGNORECASE)
                for match in matches:
                    ref = f"{match[0]}-{match[1]}" if isinstance(match, tuple) else match
                    extracted_data['references'].append({
                        'reference': ref.upper(),
                        'type': ref_type,
                        'confidence': 80
                    })
            
            # 5. Extract amounts
            for pattern, currency in AMOUNT_PATTERNS:
                matches = re.findall(pattern, extracted_text, re.IGNORECASE)
                for match in matches:
                    amount_str = match.replace(',', '')
                    try:
                        amount = float(amount_str)
                        extracted_data['amounts'].append({
                            'amount': amount,
                            'currency': currency,
                            'confidence': 70
                        })
                    except ValueError:
                        pass
        
        return ClassificationResult(
            evidence_type=evidence_type,
            document_category=document_category,
            confidence=confidence,
            method=method,
            extracted_data=extracted_data
        )


# ============================================================================
# LINKING ENGINE
# ============================================================================

class EvidenceLinkingEngine:
    """
    Intelligently links evidence items to correspondence (emails)
    Uses multiple strategies with confidence scoring
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.classifier = EvidenceClassifier()
    
    def find_correspondence_links(
        self,
        evidence_item: EvidenceItem,
        case_id: Optional[uuid.UUID] = None,
        project_id: Optional[uuid.UUID] = None,
        max_results: int = 20
    ) -> List[LinkSuggestion]:
        """
        Find correspondence (emails) that may be related to this evidence item
        Returns list of suggestions sorted by confidence
        """
        suggestions: List[LinkSuggestion] = []
        
        # Determine scope (case, project, or all)
        scope_case_id = case_id or evidence_item.case_id
        scope_project_id = project_id or evidence_item.project_id
        
        # 1. Direct attachment link (if evidence came from email)
        if evidence_item.source_email_id:
            email = self.db.query(EmailMessage).filter(
                EmailMessage.id == evidence_item.source_email_id
            ).first()
            if email:
                suggestions.append(LinkSuggestion(
                    email_id=str(email.id),
                    email_subject=email.subject,
                    email_sender=email.sender_email,
                    email_date=email.date_sent,
                    link_type='attachment',
                    confidence=100,
                    method='direct_attachment',
                    context='This file was extracted as an attachment from this email'
                ))
        
        # 2. Filename mention matching
        filename_suggestions = self._find_by_filename_mention(
            evidence_item.filename,
            scope_case_id,
            scope_project_id
        )
        suggestions.extend(filename_suggestions)
        
        # 3. Reference number matching
        if evidence_item.extracted_references:
            ref_suggestions = self._find_by_references(
                evidence_item.extracted_references,
                scope_case_id,
                scope_project_id
            )
            suggestions.extend(ref_suggestions)
        
        # 4. Date proximity matching
        if evidence_item.document_date:
            date_suggestions = self._find_by_date_proximity(
                evidence_item.document_date,
                scope_case_id,
                scope_project_id,
                days_range=7
            )
            suggestions.extend(date_suggestions)
        
        # 5. Party/stakeholder matching
        if evidence_item.extracted_parties or evidence_item.author:
            party_suggestions = self._find_by_parties(
                evidence_item.extracted_parties or [],
                evidence_item.author,
                scope_case_id,
                scope_project_id
            )
            suggestions.extend(party_suggestions)
        
        # Deduplicate by email_id, keeping highest confidence
        seen: Dict[str, LinkSuggestion] = {}
        for s in suggestions:
            if s.email_id not in seen or s.confidence > seen[s.email_id].confidence:
                seen[s.email_id] = s
        
        # Sort by confidence descending
        result = sorted(seen.values(), key=lambda x: x.confidence, reverse=True)
        
        return result[:max_results]
    
    def _find_by_filename_mention(
        self,
        filename: str,
        case_id: Optional[uuid.UUID],
        project_id: Optional[uuid.UUID]
    ) -> List[LinkSuggestion]:
        """Find emails that mention this filename in subject or body"""
        suggestions = []
        
        # Clean filename for search
        name_parts = re.split(r'[_\-\s\.]+', filename.lower())
        name_parts = [p for p in name_parts if len(p) > 2]
        
        if not name_parts:
            return suggestions
        
        # Build query
        query = self.db.query(EmailMessage)
        
        if case_id:
            query = query.filter(EmailMessage.case_id == case_id)
        elif project_id:
            query = query.filter(EmailMessage.project_id == project_id)
        
        # Search for filename (without extension) in subject and body
        filename_base = filename.rsplit('.', 1)[0] if '.' in filename else filename
        search_term = f"%{filename_base}%"
        
        emails = query.filter(
            or_(
                EmailMessage.subject.ilike(search_term),
                EmailMessage.body_text.ilike(search_term)
            )
        ).limit(10).all()
        
        for email in emails:
            # Calculate confidence based on match quality
            confidence = 50
            context = None
            
            if email.subject and filename_base.lower() in email.subject.lower():
                confidence = 75
                context = f"Filename '{filename_base}' mentioned in email subject"
            elif email.body_text and filename_base.lower() in email.body_text.lower():
                confidence = 60
                context = f"Filename '{filename_base}' mentioned in email body"
            
            suggestions.append(LinkSuggestion(
                email_id=str(email.id),
                email_subject=email.subject,
                email_sender=email.sender_email,
                email_date=email.date_sent,
                link_type='mentioned',
                confidence=confidence,
                method='filename_mention',
                context=context
            ))
        
        return suggestions
    
    def _find_by_references(
        self,
        references: List[Dict[str, Any]],
        case_id: Optional[uuid.UUID],
        project_id: Optional[uuid.UUID]
    ) -> List[LinkSuggestion]:
        """Find emails that mention the same reference numbers"""
        suggestions = []
        
        if not references:
            return suggestions
        
        query = self.db.query(EmailMessage)
        
        if case_id:
            query = query.filter(EmailMessage.case_id == case_id)
        elif project_id:
            query = query.filter(EmailMessage.project_id == project_id)
        
        for ref_data in references[:5]:  # Limit to top 5 references
            ref = ref_data.get('reference', '')
            if not ref:
                continue
            
            search_term = f"%{ref}%"
            emails = query.filter(
                or_(
                    EmailMessage.subject.ilike(search_term),
                    EmailMessage.body_text.ilike(search_term)
                )
            ).limit(5).all()
            
            for email in emails:
                suggestions.append(LinkSuggestion(
                    email_id=str(email.id),
                    email_subject=email.subject,
                    email_sender=email.sender_email,
                    email_date=email.date_sent,
                    link_type='references',
                    confidence=70,
                    method='reference_match',
                    context=f"Reference '{ref}' appears in both document and email"
                ))
        
        return suggestions
    
    def _find_by_date_proximity(
        self,
        doc_date: datetime,
        case_id: Optional[uuid.UUID],
        project_id: Optional[uuid.UUID],
        days_range: int = 7
    ) -> List[LinkSuggestion]:
        """Find emails sent within N days of document date"""
        suggestions = []
        
        date_from = doc_date - timedelta(days=days_range)
        date_to = doc_date + timedelta(days=days_range)
        
        query = self.db.query(EmailMessage).filter(
            and_(
                EmailMessage.date_sent >= date_from,
                EmailMessage.date_sent <= date_to
            )
        )
        
        if case_id:
            query = query.filter(EmailMessage.case_id == case_id)
        elif project_id:
            query = query.filter(EmailMessage.project_id == project_id)
        
        emails = query.order_by(EmailMessage.date_sent).limit(10).all()
        
        for email in emails:
            if not email.date_sent:
                continue
            
            # Calculate confidence based on date proximity
            days_diff = abs((email.date_sent.date() - doc_date.date()).days)
            confidence = max(30, 60 - (days_diff * 5))  # Closer = higher confidence
            
            suggestions.append(LinkSuggestion(
                email_id=str(email.id),
                email_subject=email.subject,
                email_sender=email.sender_email,
                email_date=email.date_sent,
                link_type='related',
                confidence=confidence,
                method='date_proximity',
                context=f"Email sent {days_diff} day(s) from document date"
            ))
        
        return suggestions
    
    def _find_by_parties(
        self,
        parties: List[Dict[str, Any]],
        author: Optional[str],
        case_id: Optional[uuid.UUID],
        project_id: Optional[uuid.UUID]
    ) -> List[LinkSuggestion]:
        """Find emails involving the same parties as the document"""
        suggestions = []
        
        # Collect party names/emails
        party_terms = []
        
        for party in parties:
            name = party.get('name', '')
            if name and len(name) > 2:
                party_terms.append(name.lower())
        
        if author:
            party_terms.append(author.lower())
        
        if not party_terms:
            return suggestions
        
        query = self.db.query(EmailMessage)
        
        if case_id:
            query = query.filter(EmailMessage.case_id == case_id)
        elif project_id:
            query = query.filter(EmailMessage.project_id == project_id)
        
        # Search for party names in sender/recipients
        for term in party_terms[:3]:  # Limit to top 3 parties
            search_term = f"%{term}%"
            emails = query.filter(
                or_(
                    EmailMessage.sender_email.ilike(search_term),
                    EmailMessage.sender_name.ilike(search_term)
                )
            ).limit(5).all()
            
            for email in emails:
                suggestions.append(LinkSuggestion(
                    email_id=str(email.id),
                    email_subject=email.subject,
                    email_sender=email.sender_email,
                    email_date=email.date_sent,
                    link_type='related',
                    confidence=45,
                    method='party_match',
                    context=f"Document author/party '{term}' matches email sender"
                ))
        
        return suggestions
    
    def find_duplicate_evidence(
        self,
        file_hash: str,
        exclude_id: Optional[uuid.UUID] = None
    ) -> List[EvidenceItem]:
        """Find evidence items with the same file hash (duplicates)"""
        query = self.db.query(EvidenceItem).filter(
            EvidenceItem.file_hash == file_hash
        )
        
        if exclude_id:
            query = query.filter(EvidenceItem.id != exclude_id)
        
        return query.all()
    
    def find_related_evidence(
        self,
        evidence_item: EvidenceItem,
        max_results: int = 10
    ) -> List[Tuple[EvidenceItem, str, int]]:
        """
        Find related evidence items based on:
        - Same references
        - Similar filenames
        - Same date
        Returns list of (item, relation_type, confidence)
        """
        related = []
        
        # 1. Find items with same references
        if evidence_item.extracted_references:
            for ref_data in evidence_item.extracted_references:
                ref = ref_data.get('reference', '')
                if not ref:
                    continue
                
                items = self.db.query(EvidenceItem).filter(
                    and_(
                        EvidenceItem.id != evidence_item.id,
                        EvidenceItem.extracted_references.contains([{'reference': ref}])
                    )
                ).limit(5).all()
                
                for item in items:
                    related.append((item, 'references', 70))
        
        # 2. Find items with similar filenames
        filename_base = evidence_item.filename.rsplit('.', 1)[0]
        if len(filename_base) > 4:
            similar = self.db.query(EvidenceItem).filter(
                and_(
                    EvidenceItem.id != evidence_item.id,
                    EvidenceItem.filename.ilike(f"%{filename_base[:10]}%")
                )
            ).limit(5).all()
            
            for item in similar:
                related.append((item, 'related', 40))
        
        # 3. Find items with same document date
        if evidence_item.document_date:
            same_date = self.db.query(EvidenceItem).filter(
                and_(
                    EvidenceItem.id != evidence_item.id,
                    EvidenceItem.document_date == evidence_item.document_date
                )
            ).limit(5).all()
            
            for item in same_date:
                related.append((item, 'related', 30))
        
        # Deduplicate
        seen = set()
        result = []
        for item, rel_type, conf in related:
            if item.id not in seen:
                seen.add(item.id)
                result.append((item, rel_type, conf))
        
        # Sort by confidence
        result.sort(key=lambda x: x[2], reverse=True)
        
        return result[:max_results]
    
    def auto_link_evidence(
        self,
        evidence_item: EvidenceItem,
        user_id: uuid.UUID,
        confidence_threshold: int = 70
    ) -> List[EvidenceCorrespondenceLink]:
        """
        Automatically create links for high-confidence suggestions
        Returns list of created links
        """
        suggestions = self.find_correspondence_links(evidence_item)
        created_links = []
        
        for suggestion in suggestions:
            if suggestion.confidence < confidence_threshold:
                continue
            
            # Check if link already exists
            existing = self.db.query(EvidenceCorrespondenceLink).filter(
                and_(
                    EvidenceCorrespondenceLink.evidence_item_id == evidence_item.id,
                    EvidenceCorrespondenceLink.email_message_id == uuid.UUID(suggestion.email_id)
                )
            ).first()
            
            if existing:
                continue
            
            # Create link
            link = EvidenceCorrespondenceLink(
                evidence_item_id=evidence_item.id,
                email_message_id=uuid.UUID(suggestion.email_id),
                link_type=suggestion.link_type,
                link_confidence=suggestion.confidence,
                link_method=suggestion.method,
                context_snippet=suggestion.context,
                is_auto_linked=True,
                is_verified=False,
                linked_by=user_id
            )
            
            self.db.add(link)
            created_links.append(link)
        
        if created_links:
            self.db.commit()
            logger.info(f"Auto-created {len(created_links)} links for evidence {evidence_item.id}")
        
        return created_links
    
    def classify_and_enrich(
        self,
        evidence_item: EvidenceItem
    ) -> Dict[str, Any]:
        """
        Classify evidence type and extract metadata
        Updates the evidence item in-place
        """
        result = self.classifier.classify(
            filename=evidence_item.filename,
            file_type=evidence_item.file_type,
            extracted_text=evidence_item.extracted_text
        )
        
        # Update evidence item
        if result.confidence > (evidence_item.classification_confidence or 0):
            evidence_item.evidence_type = result.evidence_type
            evidence_item.document_category = result.document_category
            evidence_item.classification_confidence = result.confidence
            evidence_item.classification_method = result.method
        
        # Add extracted data
        if result.extracted_data.get('references'):
            evidence_item.extracted_references = (
                (evidence_item.extracted_references or []) + 
                result.extracted_data['references']
            )
        
        if result.extracted_data.get('amounts'):
            evidence_item.extracted_amounts = (
                (evidence_item.extracted_amounts or []) + 
                result.extracted_data['amounts']
            )
        
        evidence_item.ai_analyzed = True
        
        return {
            'evidence_type': result.evidence_type,
            'document_category': result.document_category,
            'confidence': result.confidence,
            'method': result.method,
            'extracted_data': result.extracted_data
        }


# ============================================================================
# BATCH PROCESSING
# ============================================================================

def process_evidence_batch(
    db: Session,
    evidence_ids: List[uuid.UUID],
    user_id: uuid.UUID,
    auto_link: bool = True,
    classify: bool = True
) -> Dict[str, Any]:
    """
    Process a batch of evidence items
    - Classify each item
    - Auto-link to correspondence
    - Find duplicates and relations
    """
    engine = EvidenceLinkingEngine(db)
    
    results = {
        'processed': 0,
        'classified': 0,
        'links_created': 0,
        'duplicates_found': 0,
        'errors': []
    }
    
    for evidence_id in evidence_ids:
        try:
            item = db.query(EvidenceItem).filter(
                EvidenceItem.id == evidence_id
            ).first()
            
            if not item:
                results['errors'].append(f"Evidence {evidence_id} not found")
                continue
            
            # Classify
            if classify:
                engine.classify_and_enrich(item)
                results['classified'] += 1
            
            # Auto-link
            if auto_link:
                links = engine.auto_link_evidence(item, user_id)
                results['links_created'] += len(links)
            
            # Check for duplicates
            duplicates = engine.find_duplicate_evidence(
                item.file_hash,
                exclude_id=item.id
            )
            if duplicates:
                item.is_duplicate = True
                item.duplicate_of_id = duplicates[0].id
                results['duplicates_found'] += 1
            
            item.processing_status = 'ready'
            results['processed'] += 1
            
        except Exception as e:
            results['errors'].append(f"Error processing {evidence_id}: {str(e)}")
            logger.exception(f"Error processing evidence {evidence_id}")
    
    db.commit()
    
    return results

