"""
Smart Document Processor - AWS-Enhanced Document Analysis
Auto-extracts parties, dates, entities, and classifies documents using AWS AI services
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from uuid import UUID
import boto3
from sqlalchemy.orm import Session

from .config import settings
from .models import Document, Case, Stakeholder
from .db import SessionLocal

logger = logging.getLogger(__name__)


class SmartDocumentProcessor:
    """Enhanced document processor using AWS Textract and Comprehend"""

    def __init__(self):
        self.textract = boto3.client("textract", region_name=settings.AWS_REGION)
        self.comprehend = boto3.client("comprehend", region_name=settings.AWS_REGION)

    async def process_document(
        self,
        document_id: str,
        s3_bucket: str,
        s3_key: str,
        case_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Comprehensive document processing pipeline

        Returns:
            dict: Processing results with extracted entities, dates, etc.
        """
        logger.info(f"Starting smart processing for document {document_id}")

        results = {
            "document_id": document_id,
            "status": "processing",
            "extracted_text": "",
            "entities": {},
            "dates": [],
            "tables": [],
            "document_type": "unknown",
            "confidence": 0.0,
        }

        try:
            # Step 1: Extract text with Textract
            logger.info("Step 1: Extracting text with Textract...")
            textract_result = await self._extract_text_textract(s3_bucket, s3_key)
            results["extracted_text"] = textract_result["text"]
            results["tables"] = textract_result.get("tables", [])
            results["confidence"] = textract_result.get("confidence", 0.0)

            # Step 2: Entity extraction with Comprehend
            logger.info("Step 2: Extracting entities with Comprehend...")
            entities = await self._extract_entities(results["extracted_text"])
            results["entities"] = entities

            # Step 3: Extract dates
            logger.info("Step 3: Extracting key dates...")
            results["dates"] = entities.get("dates", [])

            # Step 4: Classify document
            logger.info("Step 4: Classifying document type...")
            results["document_type"] = await self._classify_document(
                results["extracted_text"]
            )

            # Step 5: Detect PII for redaction
            logger.info("Step 5: Detecting PII...")
            pii = await self._detect_pii(results["extracted_text"])
            results["pii_detected"] = len(pii) > 0
            results["pii_locations"] = pii

            # Step 6: Auto-populate case if provided
            if case_id:
                logger.info(f"Step 6: Auto-populating case {case_id}...")
                await self._auto_populate_case(case_id, document_id, results)

            results["status"] = "completed"
            logger.info(f"Smart processing completed for document {document_id}")

        except Exception as e:
            logger.error(f"Error in smart document processing: {e}", exc_info=True)
            results["status"] = "error"
            results["error"] = str(e)

        return results

    async def _extract_text_textract(self, bucket: str, key: str) -> Dict[str, Any]:
        """Extract text and tables using AWS Textract"""
        try:
            # Start Textract analysis
            response = self.textract.start_document_analysis(
                DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}},
                FeatureTypes=["TABLES", "FORMS"],
            )

            job_id = response["JobId"]
            logger.info(f"Textract job started: {job_id}")

            # Wait for completion (in production, use async or webhook)
            import time

            while True:
                response = self.textract.get_document_analysis(JobId=job_id)
                status = response["JobStatus"]

                if status == "SUCCEEDED":
                    break
                elif status == "FAILED":
                    raise Exception(
                        f"Textract job failed: {response.get('StatusMessage')}"
                    )

                time.sleep(2)

            # Extract text and tables
            text_blocks = []
            tables = []
            confidence_scores = []

            for block in response.get("Blocks", []):
                if block["BlockType"] == "LINE":
                    text_blocks.append(block["Text"])
                    confidence_scores.append(block.get("Confidence", 0))
                elif block["BlockType"] == "TABLE":
                    tables.append(self._parse_table(block, response["Blocks"]))

            full_text = "\n".join(text_blocks)
            avg_confidence = (
                sum(confidence_scores) / len(confidence_scores)
                if confidence_scores
                else 0
            )

            return {
                "text": full_text,
                "tables": tables,
                "confidence": avg_confidence,
                "job_id": job_id,
            }

        except Exception as e:
            logger.error(f"Textract extraction failed: {e}")
            raise

    def _parse_table(self, table_block: dict, all_blocks: list) -> Dict[str, Any]:
        """Parse table structure from Textract blocks"""
        # Simplified table parsing - expand as needed
        return {
            "id": table_block["Id"],
            "rows": table_block.get("RowCount", 0),
            "columns": table_block.get("ColumnCount", 0),
        }

    async def _extract_entities(self, text: str) -> Dict[str, List[Dict]]:
        """Extract entities using AWS Comprehend"""
        if not text or len(text) < 10:
            return {"persons": [], "organizations": [], "dates": [], "locations": []}

        try:
            # Limit text to 5000 bytes for Comprehend
            text_sample = text[:5000]

            # Detect entities
            response = self.comprehend.detect_entities(
                Text=text_sample, LanguageCode="en"
            )

            # Categorize entities
            entities = {
                "persons": [],
                "organizations": [],
                "dates": [],
                "locations": [],
                "other": [],
            }

            for entity in response.get("Entities", []):
                entity_data = {
                    "text": entity["Text"],
                    "type": entity["Type"],
                    "score": entity["Score"],
                    "begin_offset": entity["BeginOffset"],
                    "end_offset": entity["EndOffset"],
                }

                entity_type = entity["Type"]
                if entity_type == "PERSON":
                    entities["persons"].append(entity_data)
                elif entity_type == "ORGANIZATION":
                    entities["organizations"].append(entity_data)
                elif entity_type == "DATE":
                    entities["dates"].append(entity_data)
                elif entity_type == "LOCATION":
                    entities["locations"].append(entity_data)
                else:
                    entities["other"].append(entity_data)

            logger.info(f"Extracted {len(response.get('Entities', []))} entities")
            return entities

        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            return {"persons": [], "organizations": [], "dates": [], "locations": []}

    async def _classify_document(self, text: str) -> str:
        """Classify document type based on content"""
        if not text:
            return "unknown"

        # Simple keyword-based classification (can be enhanced with custom model)
        text_lower = text.lower()

        if any(
            word in text_lower for word in ["contract", "agreement", "parties agree"]
        ):
            return "contract"
        elif any(word in text_lower for word in ["invoice", "payment", "total due"]):
            return "invoice"
        elif any(word in text_lower for word in ["email", "from:", "to:", "subject:"]):
            return "correspondence"
        elif any(
            word in text_lower
            for word in ["claim", "damages", "plaintiff", "defendant"]
        ):
            return "legal_document"
        elif any(word in text_lower for word in ["schedule", "timeline", "programme"]):
            return "schedule"
        else:
            return "general_document"

    async def _detect_pii(self, text: str) -> List[Dict]:
        """Detect personally identifiable information"""
        if not text or len(text) < 10:
            return []

        try:
            text_sample = text[:5000]

            response = self.comprehend.detect_pii_entities(
                Text=text_sample, LanguageCode="en"
            )

            pii_entities = []
            for entity in response.get("Entities", []):
                pii_entities.append(
                    {
                        "type": entity["Type"],
                        "score": entity["Score"],
                        "begin_offset": entity["BeginOffset"],
                        "end_offset": entity["EndOffset"],
                    }
                )

            if pii_entities:
                logger.warning(f"Detected {len(pii_entities)} PII entities")

            return pii_entities

        except Exception as e:
            logger.error(f"PII detection failed: {e}")
            return []

    async def _auto_populate_case(
        self, case_id: str, document_id: str, results: Dict[str, Any]
    ):
        """Auto-populate case with extracted information"""
        db = SessionLocal()
        try:
            case = db.get(Case, UUID(case_id))
            if not case:
                logger.warning(f"Case {case_id} not found")
                return

            # Add stakeholders from extracted organizations and persons
            for org in results["entities"].get("organizations", [])[
                :5
            ]:  # Limit to top 5
                self._add_stakeholder_if_not_exists(
                    db, case_id, org["text"], "organization", org["score"]
                )

            for person in results["entities"].get("persons", [])[
                :10
            ]:  # Limit to top 10
                self._add_stakeholder_if_not_exists(
                    db, case_id, person["text"], "person", person["score"]
                )

            # Update document metadata
            document = db.get(Document, UUID(document_id))
            if document:
                document.meta = {
                    **(document.meta or {}),
                    "smart_processing": {
                        "processed_at": datetime.now().isoformat(),
                        "document_type": results["document_type"],
                        "confidence": results["confidence"],
                        "entities_found": {
                            "persons": len(results["entities"].get("persons", [])),
                            "organizations": len(
                                results["entities"].get("organizations", [])
                            ),
                            "dates": len(results["dates"]),
                            "locations": len(results["entities"].get("locations", [])),
                        },
                        "pii_detected": results.get("pii_detected", False),
                        "tables_found": len(results.get("tables", [])),
                    },
                }

                # Update text excerpt
                if results["extracted_text"]:
                    document.text_excerpt = results["extracted_text"][:5000]

            db.commit()
            logger.info(
                f"Auto-populated case {case_id} with document {document_id} data"
            )

        except Exception as e:
            logger.error(f"Error auto-populating case: {e}")
            db.rollback()
        finally:
            db.close()

    def _add_stakeholder_if_not_exists(
        self,
        db: Session,
        case_id: str,
        name: str,
        stakeholder_type: str,
        confidence: float,
    ):
        """Add stakeholder to case if not already exists"""
        try:
            # Check if stakeholder already exists
            existing = (
                db.query(Stakeholder)
                .filter(
                    Stakeholder.case_id == UUID(case_id),
                    Stakeholder.name.ilike(name.strip()),
                )
                .first()
            )

            if not existing and confidence > 0.7:  # Only add high-confidence entities
                stakeholder = Stakeholder(
                    case_id=UUID(case_id),
                    name=name.strip(),
                    role=stakeholder_type,
                    meta={"auto_extracted": True, "confidence": confidence},
                )
                db.add(stakeholder)
                logger.info(f"Added stakeholder: {name} ({stakeholder_type})")

        except Exception as e:
            logger.error(f"Error adding stakeholder: {e}")


# Global processor instance
smart_processor = SmartDocumentProcessor()


async def process_document_smart(
    document_id: str, s3_bucket: str, s3_key: str, case_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Process document with smart extraction and analysis

    Usage:
        result = await process_document_smart(doc_id, bucket, key, case_id)
    """
    return await smart_processor.process_document(
        document_id, s3_bucket, s3_key, case_id
    )
