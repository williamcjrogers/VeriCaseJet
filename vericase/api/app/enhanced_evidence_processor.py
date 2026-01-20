# Enhanced Evidence Processor with AWS Services Integration
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from .aws_services import get_aws_services
from .config import settings
from .models import EvidenceItem, EmailMessage, Case
from .storage import get_object

from .evidence.text_extract import extract_text_from_bytes, tika_url_candidates

import httpx

logger = logging.getLogger(__name__)


class EnhancedEvidenceProcessor:
    """Enhanced evidence processor using all AWS services"""

    def __init__(self):
        self.aws = get_aws_services()
        self.knowledge_base_id = settings.BEDROCK_KB_ID or "VERICASE-KB-001"
        self.data_source_id = settings.BEDROCK_DS_ID or "VERICASE-DS-001"

    async def process_evidence_item(
        self, evidence_id: str, db: Session
    ) -> Dict[str, Any]:
        """Complete evidence processing pipeline using all AWS services"""
        evidence: EvidenceItem | None = None
        try:
            # Get evidence item
            evidence = (
                db.query(EvidenceItem).filter(EvidenceItem.id == evidence_id).first()
            )
            if not evidence:
                return {"error": "Evidence not found"}

            logger.info(f"Processing evidence: {evidence.filename}")

            # Step 1: Text extraction (Textract for PDFs/images; robust fallback for DOCX/XLSX/etc).
            file_bytes = b""
            try:
                file_bytes = get_object(evidence.s3_key, bucket=evidence.s3_bucket)
            except Exception as e:
                logger.warning("Could not download object for extraction: %s", e)

            ext = ""
            try:
                if evidence.filename and "." in evidence.filename:
                    ext = evidence.filename.rsplit(".", 1)[-1].lower()
            except Exception:
                ext = ""

            mime = (evidence.mime_type or "").lower().strip()
            textract_supported = ext in {
                "pdf",
                "png",
                "jpg",
                "jpeg",
                "tif",
                "tiff",
            } or mime in {
                "application/pdf",
                "image/png",
                "image/jpeg",
                "image/tiff",
            }

            textract_data: Dict[str, Any] = {
                "text": "",
                "tables": [],
                "forms": {},
                "queries": {},
                "signatures": [],
                "confidence_scores": {},
            }

            if textract_supported:
                textract_data = await self.aws.extract_document_data(
                    evidence.s3_bucket, evidence.s3_key
                )

            # Fallback extraction for non-Textract docs (or Textract failures)
            fallback_text = ""
            if file_bytes:
                fallback_text = extract_text_from_bytes(
                    file_bytes, filename=evidence.filename, mime_type=evidence.mime_type
                )

            if not (textract_data.get("text") or "").strip():
                if fallback_text.strip():
                    textract_data["text"] = fallback_text
                    textract_data["extraction_method"] = "local"
                else:
                    # Try Apache Tika for legacy formats (.doc/.xls/etc) or as a last resort.
                    tika_text = await self._extract_text_with_tika(
                        file_bytes,
                        filename=evidence.filename,
                        mime_type=evidence.mime_type,
                    )
                    if tika_text.strip():
                        textract_data["text"] = tika_text
                        textract_data["extraction_method"] = "tika"

            # Step 2: Comprehensive text analysis with Comprehend
            full_text = textract_data.get("text", evidence.extracted_text or "")
            comprehend_analysis = await self.aws.analyze_document_entities(full_text)

            # Step 3: Image analysis if applicable
            image_analysis = {}
            if evidence.mime_type and evidence.mime_type.startswith("image/"):
                image_analysis = await self.aws.analyze_construction_image(
                    evidence.s3_bucket, evidence.s3_key
                )

            # Step 4: Update evidence with enhanced metadata
            enhanced_metadata = {
                "textract_data": textract_data,
                "comprehend_analysis": comprehend_analysis,
                "image_analysis": image_analysis,
                "processing_timestamp": datetime.utcnow().isoformat(),
                "aws_services_used": ["textract", "comprehend", "rekognition"],
            }

            # Update evidence item
            evidence.extracted_metadata = enhanced_metadata
            evidence.extracted_text = full_text
            evidence.processing_status = "ready"
            evidence.processing_error = None
            evidence.ocr_completed = True
            evidence.ai_analyzed = True
            evidence.processed_at = datetime.utcnow()

            # Extract and update entities
            entities = comprehend_analysis.get("entities", [])
            evidence.extracted_parties = [
                e["Text"] for e in entities if e["Type"] == "PERSON"
            ]
            evidence.extracted_dates = [
                e["Text"] for e in entities if e["Type"] == "DATE"
            ]
            evidence.extracted_amounts = [
                e["Text"]
                for e in entities
                if e["Type"] in ["QUANTITY", "OTHER"]
                and any(c in e["Text"] for c in ["£", "$", "€"])
            ]

            # Auto-classify document type
            evidence.evidence_type = self._classify_document_type(
                textract_data, comprehend_analysis
            )
            evidence.classification_confidence = (
                self._calculate_classification_confidence(
                    textract_data, comprehend_analysis
                )
            )

            # Generate auto-tags
            evidence.auto_tags = self._generate_auto_tags(
                textract_data, comprehend_analysis, image_analysis
            )

            db.commit()

            # Step 5: Ingest into Bedrock Knowledge Base
            await self._ingest_to_knowledge_base(evidence, enhanced_metadata)

            # Step 6: Trigger workflow events
            await self.aws.trigger_evidence_processing(
                {
                    "evidence_id": str(evidence.id),
                    "case_id": str(evidence.case_id) if evidence.case_id else None,
                    "project_id": (
                        str(evidence.project_id) if evidence.project_id else None
                    ),
                    "processing_complete": True,
                    "metadata": enhanced_metadata,
                }
            )

            return {
                "success": True,
                "evidence_id": str(evidence.id),
                "enhanced_metadata": enhanced_metadata,
                "auto_classification": evidence.evidence_type,
                "entities_extracted": len(entities),
            }

        except Exception as e:
            logger.error(f"Enhanced evidence processing failed: {e}")
            try:
                if evidence is not None:
                    evidence.processing_status = "error"
                    evidence.processing_error = str(e)
                    db.commit()
            except Exception as persist_exc:
                logger.warning(
                    f"Failed to persist evidence processing error for {evidence_id}: {persist_exc}"
                )
            return {"error": str(e)}

    async def _extract_text_with_tika(
        self,
        content: bytes,
        *,
        filename: str | None = None,
        mime_type: str | None = None,
    ) -> str:
        """Try Apache Tika for broad format coverage (DOC/XLS/PPT/etc)."""
        if not content:
            return ""

        # Avoid sending huge payloads to Tika in-process (uploads are capped at 50MB anyway).
        max_bytes = 60 * 1024 * 1024
        if len(content) > max_bytes:
            return ""

        preferred = getattr(settings, "TIKA_URL", None) or "http://tika:9998"
        for base in tika_url_candidates(preferred):
            try:
                headers = {}
                if mime_type:
                    headers["Content-Type"] = mime_type
                # Preserve filename when possible (helps some parsers)
                if filename:
                    headers["X-Tika-OCRLanguage"] = "eng"
                    headers["X-File-Name"] = filename

                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.put(
                        f"{base}/tika", content=content, headers=headers
                    )
                    if r.status_code == 200:
                        return (r.text or "").strip()
            except Exception:
                continue
        return ""

    async def process_email_thread(self, thread_id: str, db: Session) -> Dict[str, Any]:
        """Process entire email thread with sentiment analysis"""
        try:
            emails = (
                db.query(EmailMessage).filter(EmailMessage.thread_id == thread_id).all()
            )

            thread_analysis = {
                "thread_id": thread_id,
                "email_count": len(emails),
                "sentiment_progression": [],
                "key_entities": set(),
                "escalation_detected": False,
                "summary": "",
            }

            for email in emails:
                if email.body_text:
                    # Analyze each email
                    analysis = await self.aws.analyze_document_entities(
                        email.body_text[:5000]
                    )

                    sentiment = analysis.get("sentiment", "NEUTRAL")
                    sentiment_scores = analysis.get("sentiment_scores", {})

                    thread_analysis["sentiment_progression"].append(
                        {
                            "email_id": str(email.id),
                            "date": (
                                email.date_sent.isoformat() if email.date_sent else None
                            ),
                            "sentiment": sentiment,
                            "sentiment_scores": sentiment_scores,
                        }
                    )

                    # Collect entities
                    for entity in analysis.get("entities", []):
                        thread_analysis["key_entities"].add(entity["Text"])

            # Detect escalation (sentiment getting more negative)
            sentiments = [
                s["sentiment"] for s in thread_analysis["sentiment_progression"]
            ]
            negative_count = sentiments.count("NEGATIVE")
            if negative_count > len(sentiments) * 0.3:  # More than 30% negative
                thread_analysis["escalation_detected"] = True

            thread_analysis["key_entities"] = list(thread_analysis["key_entities"])

            return thread_analysis

        except Exception as e:
            logger.error(f"Email thread processing failed: {e}")
            return {"error": str(e)}

    async def process_audio_evidence(
        self, s3_bucket: str, s3_key: str, evidence_id: str
    ) -> Dict[str, Any]:
        """Process audio/video evidence with transcription"""
        try:
            job_name = (
                f"vericase-{evidence_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            )

            # Transcribe audio
            transcription_result = await self.aws.transcribe_meeting_audio(
                s3_bucket, s3_key, job_name
            )

            if transcription_result.get("transcript_uri"):
                # Download and analyze transcript
                # This would fetch the transcript from S3 and analyze it
                transcript_text = "Transcript would be fetched here"  # Placeholder

                # Analyze transcript with Comprehend
                analysis = await self.aws.analyze_document_entities(transcript_text)

                return {
                    "transcription_job": job_name,
                    "transcript_uri": transcription_result["transcript_uri"],
                    "analysis": analysis,
                    "speakers_detected": True,  # From Transcribe speaker labels
                    "key_topics": analysis.get("key_phrases", []),
                }

            return {"error": "Transcription failed"}

        except Exception as e:
            logger.error(f"Audio evidence processing failed: {e}")
            return {"error": str(e)}

    async def semantic_search(
        self, query: str, case_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Semantic search across all evidence using Bedrock KB"""
        try:
            # Query Bedrock Knowledge Base
            kb_results = await self.aws.query_knowledge_base(
                query, self.knowledge_base_id
            )

            # Enhance results with case context if provided
            enhanced_results = []
            for result in kb_results:
                enhanced_result = {
                    "content": result.get("content", {}).get("text", ""),
                    "score": result.get("score", 0),
                    "metadata": result.get("metadata", {}),
                    "source": result.get("location", {}),
                }

                # Add case relevance if case_id provided
                if case_id:
                    enhanced_result["case_relevance"] = self._calculate_case_relevance(
                        enhanced_result, case_id
                    )

                enhanced_results.append(enhanced_result)

            return enhanced_results

        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return []

    async def generate_case_insights(self, case_id: str, db: Session) -> Dict[str, Any]:
        """Generate AI-powered case insights using all evidence"""
        try:
            case = db.query(Case).filter(Case.id == case_id).first()
            if not case:
                return {"error": "Case not found"}

            # Get all evidence for case
            evidence_items = (
                db.query(EvidenceItem).filter(EvidenceItem.case_id == case_id).all()
            )

            insights = {
                "case_id": case_id,
                "case_name": case.name,
                "total_evidence": len(evidence_items),
                "evidence_timeline": [],
                "key_entities": {},
                "sentiment_analysis": {},
                "missing_evidence_periods": [],
                "risk_factors": [],
                "strengths": [],
                "recommendations": [],
            }

            # Analyze evidence timeline
            for evidence in evidence_items:
                if evidence.document_date:
                    insights["evidence_timeline"].append(
                        {
                            "date": evidence.document_date.isoformat(),
                            "type": evidence.evidence_type,
                            "filename": evidence.filename,
                            "confidence": evidence.classification_confidence,
                        }
                    )

            # Sort timeline
            insights["evidence_timeline"].sort(key=lambda x: x["date"])

            # Aggregate entities across all evidence
            entity_counts = {}
            for evidence in evidence_items:
                if evidence.extracted_parties:
                    for party in evidence.extracted_parties:
                        entity_counts[party] = entity_counts.get(party, 0) + 1

            insights["key_entities"] = dict(
                sorted(entity_counts.items(), key=lambda x: x[1], reverse=True)[:20]
            )

            # Generate AI recommendations using Bedrock
            recommendations_query = f"""
            Based on the evidence collected for case "{case.name}" ({case.dispute_type}), 
            what are the key legal strategies and potential risks?
            Evidence includes: {len(evidence_items)} documents spanning {len(insights["evidence_timeline"])} time periods.
            Key parties: {list(insights["key_entities"].keys())[:5]}
            """

            ai_recommendations = await self.aws.query_knowledge_base(
                recommendations_query, self.knowledge_base_id
            )

            insights["ai_recommendations"] = [
                r.get("content", {}).get("text", "") for r in ai_recommendations[:3]
            ]

            return insights

        except Exception as e:
            logger.error(f"Case insights generation failed: {e}")
            return {"error": str(e)}

    def _classify_document_type(
        self, textract_data: Dict, comprehend_analysis: Dict
    ) -> str:
        """Classify document type based on extracted data"""
        text = textract_data.get("text", "").lower()

        # Contract / appointment indicators (not only standard forms like JCT/NEC)
        if any(
            word in text
            for word in [
                "contract",
                "agreement",
                "terms",
                "conditions",
                "appointment",
                "terms of engagement",
                "professional services",
                "consultancy",
                "collateral warranty",
                "warranty",
                "deed",
                "novation",
                "letter of intent",
                "loi",
            ]
        ):
            return "contract"

        # Invoice indicators
        if any(word in text for word in ["invoice", "payment", "amount due", "total"]):
            return "invoice"

        # Drawing indicators
        if any(word in text for word in ["drawing", "plan", "elevation", "section"]):
            return "drawing"

        # Email indicators
        if any(word in text for word in ["from:", "to:", "subject:", "sent:"]):
            return "email"

        # Meeting minutes
        if any(
            word in text for word in ["minutes", "meeting", "attendees", "action items"]
        ):
            return "meeting_minutes"

        # Default
        return "other"

    def _calculate_classification_confidence(
        self, textract_data: Dict, comprehend_analysis: Dict
    ) -> int:
        """Calculate confidence score for document classification"""
        confidence = 50  # Base confidence

        # Boost confidence based on structured data found
        if textract_data.get("tables"):
            confidence += 20
        if textract_data.get("forms"):
            confidence += 15
        if textract_data.get("queries"):
            confidence += 10

        # Boost based on entity detection
        entities = comprehend_analysis.get("entities", [])
        if len(entities) > 5:
            confidence += 15

        return min(confidence, 100)

    def _generate_auto_tags(
        self, textract_data: Dict, comprehend_analysis: Dict, image_analysis: Dict
    ) -> List[str]:
        """Generate automatic tags based on analysis results"""
        tags = []

        # Tags from text content
        text = textract_data.get("text", "").lower()

        # Construction-specific tags
        construction_terms = {
            "delay": ["delay", "behind schedule", "late", "overrun"],
            "variation": ["variation", "change order", "additional work"],
            "defect": ["defect", "defective", "fault", "repair"],
            "payment": ["payment", "invoice", "cost", "price"],
            "safety": ["safety", "accident", "incident", "hazard"],
            "quality": ["quality", "specification", "standard", "compliance"],
        }

        for tag, terms in construction_terms.items():
            if any(term in text for term in terms):
                tags.append(tag)

        # Tags from entities
        entities = comprehend_analysis.get("entities", [])
        for entity in entities:
            if entity["Type"] == "ORGANIZATION":
                tags.append(f"org:{entity['Text']}")
            elif entity["Type"] == "LOCATION":
                tags.append(f"location:{entity['Text']}")

        # Tags from image analysis
        if image_analysis.get("construction_elements"):
            tags.extend(
                [
                    f"visual:{element}"
                    for element in image_analysis["construction_elements"][:5]
                ]
            )

        return list(set(tags))  # Remove duplicates

    async def _ingest_to_knowledge_base(self, evidence: EvidenceItem, metadata: Dict):
        """Ingest evidence into Bedrock Knowledge Base"""
        try:
            workspace_id = None
            try:
                if isinstance(evidence.meta, dict):
                    workspace_id = evidence.meta.get("workspace_id")
            except Exception:
                workspace_id = None

            # Prepare document for ingestion
            document_data = {
                "id": str(evidence.id),
                "title": evidence.title or evidence.filename,
                "content": evidence.extracted_text or "",
                "metadata": {
                    "workspace_id": workspace_id,
                    "case_id": str(evidence.case_id) if evidence.case_id else None,
                    "project_id": (
                        str(evidence.project_id) if evidence.project_id else None
                    ),
                    "evidence_type": evidence.evidence_type,
                    "document_date": (
                        evidence.document_date.isoformat()
                        if evidence.document_date
                        else None
                    ),
                    "filename": evidence.filename,
                    "s3_location": f"{evidence.s3_bucket}/{evidence.s3_key}",
                    "auto_tags": evidence.auto_tags,
                    "extracted_parties": evidence.extracted_parties,
                    "processing_metadata": metadata,
                },
            }

            # This would typically upload to S3 in the format expected by Bedrock KB
            logger.info(f"Prepared evidence {evidence.id} for Bedrock KB ingestion")
            logger.debug(
                "Bedrock KB document prepared: id=%s title=%s s3=%s",
                document_data.get("id"),
                document_data.get("title"),
                document_data.get("metadata", {}).get("s3_location"),
            )

            # Trigger ingestion job
            await self.aws.ingest_to_knowledge_base(
                kb_id=self.knowledge_base_id,
                ds_id=self.data_source_id,
            )

        except Exception as e:
            logger.error(f"Knowledge base ingestion failed: {e}")

    def _calculate_case_relevance(self, result: Dict, case_id: str) -> float:
        """Calculate relevance score for case-specific results"""
        base_score = result.get("score", 0)
        metadata = result.get("metadata", {})

        # Boost score if directly related to case
        if metadata.get("case_id") == case_id:
            return min(base_score * 1.5, 1.0)

        return base_score


# Global instance
enhanced_processor = EnhancedEvidenceProcessor()
