"""
Contract Upload Service
Handles contract PDF upload, extraction via Textract, analysis via Bedrock, and vectorization
"""

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..aws_services import aws_services
from ..config import settings
from ..storage import presign_put
from .embeddings import embedding_service
from .models import (
    CIContractClause,
    ContractType,
    ExtractedContractClause,
    UploadedContract,
)
from .vector_store import vector_store

logger = logging.getLogger(__name__)


class ContractUploadService:
    """Service for processing uploaded contract documents"""

    # Bedrock model for contract analysis
    ANALYSIS_MODEL = "anthropic.claude-3-5-sonnet-20241022-v2:0"

    async def initialize_upload(
        self,
        db: Session,
        filename: str,
        file_size: int,
        contract_type_id: int,
        project_id: Optional[str] = None,
        case_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Initialize contract upload and return presigned URL"""

        # Validate contract type exists
        contract_type = (
            db.query(ContractType)
            .filter(ContractType.id == contract_type_id, ContractType.is_active == True)
            .first()
        )

        if not contract_type:
            raise ValueError(f"Invalid contract type ID: {contract_type_id}")

        # Generate unique upload ID and S3 key
        upload_id = str(uuid.uuid4())
        s3_key = f"contracts/{upload_id}/{filename}"

        # Create upload record
        uploaded_contract = UploadedContract(
            project_id=uuid.UUID(project_id) if project_id else None,
            case_id=uuid.UUID(case_id) if case_id else None,
            contract_type_id=contract_type_id,
            filename=filename,
            s3_key=s3_key,
            file_size=file_size,
            status="pending",
            uploaded_by=uuid.UUID(user_id) if user_id else None,
        )

        db.add(uploaded_contract)
        db.commit()
        db.refresh(uploaded_contract)

        # Generate presigned PUT URL
        upload_url = presign_put(s3_key, "application/pdf")

        return {
            "upload_id": uploaded_contract.id,
            "upload_url": upload_url,
            "s3_key": s3_key,
            "contract_type": contract_type.name,
        }

    async def process_contract(
        self,
        db: Session,
        upload_id: int,
    ) -> Dict[str, Any]:
        """Process an uploaded contract: extract, analyze, and vectorize"""

        # Get upload record
        uploaded_contract = (
            db.query(UploadedContract).filter(UploadedContract.id == upload_id).first()
        )

        if not uploaded_contract:
            raise ValueError(f"Upload not found: {upload_id}")

        try:
            # Update status to processing
            uploaded_contract.status = "processing"
            uploaded_contract.progress_percent = 5
            db.commit()

            # Step 1: Extract text using Textract (0-30%)
            extracted_data = await self._extract_document(
                uploaded_contract.s3_key, db, uploaded_contract
            )

            # Step 2: Analyze with LLM to identify clauses (30-60%)
            clauses = await self._analyze_clauses(
                extracted_data,
                uploaded_contract.contract_type_id,
                db,
                uploaded_contract,
            )

            # Step 3: Generate embeddings and store in vector DB (60-90%)
            await self._vectorize_clauses(clauses, uploaded_contract, db)

            # Step 4: Match to standard clauses (90-100%)
            await self._match_standard_clauses(uploaded_contract, db)

            # Mark complete
            uploaded_contract.status = "completed"
            uploaded_contract.progress_percent = 100
            uploaded_contract.processed_at = datetime.utcnow()
            db.commit()

            return {
                "status": "completed",
                "upload_id": upload_id,
                "total_clauses": uploaded_contract.total_clauses,
                "extracted_metadata": uploaded_contract.extracted_metadata,
            }

        except Exception as e:
            logger.error(f"Contract processing failed: {e}")
            uploaded_contract.status = "failed"
            uploaded_contract.error_message = str(e)
            db.commit()
            raise

    async def _extract_document(
        self,
        s3_key: str,
        db: Session,
        uploaded_contract: UploadedContract,
    ) -> Dict[str, Any]:
        """Extract text and metadata from PDF using Textract"""

        uploaded_contract.progress_percent = 10
        db.commit()

        # Use existing Textract integration
        extracted_data = await aws_services.extract_document_data(
            s3_bucket=settings.MINIO_BUCKET, s3_key=s3_key
        )

        if extracted_data.get("error"):
            raise Exception(f"Textract extraction failed: {extracted_data['error']}")

        # Store extracted text and metadata
        uploaded_contract.extracted_text = extracted_data.get("text", "")
        uploaded_contract.extracted_metadata = {
            "queries": extracted_data.get("queries", {}),
            "forms": extracted_data.get("forms", {}),
            "tables_count": len(extracted_data.get("tables", [])),
            "signatures_count": len(extracted_data.get("signatures", [])),
        }
        uploaded_contract.progress_percent = 30
        db.commit()

        return extracted_data

    async def _analyze_clauses(
        self,
        extracted_data: Dict[str, Any],
        contract_type_id: int,
        db: Session,
        uploaded_contract: UploadedContract,
    ) -> List[Dict[str, Any]]:
        """Use Bedrock LLM to identify and analyze clauses"""

        uploaded_contract.progress_percent = 35
        db.commit()

        text = extracted_data.get("text", "")

        # Get contract type for context
        contract_type = (
            db.query(ContractType).filter(ContractType.id == contract_type_id).first()
        )

        # Build analysis prompt
        prompt = self._build_clause_analysis_prompt(text, contract_type.name)

        # Call Bedrock
        response = await self._invoke_bedrock(prompt)

        # Parse LLM response to extract clauses
        clauses = self._parse_clause_response(response)

        # Store clauses in database
        for clause_data in clauses:
            extracted_clause = ExtractedContractClause(
                uploaded_contract_id=uploaded_contract.id,
                clause_number=clause_data.get("clause_number"),
                clause_title=clause_data.get("title"),
                clause_text=clause_data.get("text", ""),
                page_number=clause_data.get("page_number"),
                risk_level=clause_data.get("risk_level"),
                entitlement_types=clause_data.get("entitlement_types", []),
                keywords=clause_data.get("keywords", []),
                confidence_score=clause_data.get("confidence", 0.8),
            )
            db.add(extracted_clause)

        uploaded_contract.progress_percent = 60
        uploaded_contract.total_clauses = len(clauses)
        uploaded_contract.analysis_result = {"clauses_identified": len(clauses)}
        db.commit()

        return clauses

    def _build_clause_analysis_prompt(self, text: str, contract_type: str) -> str:
        """Build prompt for clause extraction"""
        # Truncate text to avoid token limits
        max_chars = 80000
        truncated_text = text[:max_chars] if len(text) > max_chars else text

        return f"""You are an expert construction contract analyst specializing in {contract_type} contracts.

Analyze the following contract document and extract all significant contractual clauses. Focus on:
- Extension of time clauses
- Variations and changes
- Payment terms
- Delay and disruption provisions
- Termination clauses
- Risk allocation provisions
- Notice requirements
- Limitation of liability

For each clause, provide:
1. clause_number - The clause reference number (e.g., "2.26.3", "Section 5.1", "Clause 12")
2. title - A descriptive title for the clause
3. text - The key provisions (first 500 characters if long)
4. risk_level - One of: low, medium, high, critical
5. entitlement_types - List from: time_extension, cost_recovery, variation, termination, payment, compliance, notice
6. keywords - 3-5 relevant search keywords

Respond ONLY with a valid JSON array of clause objects. No other text.

Example format:
[
  {{
    "clause_number": "2.26.3",
    "title": "Extension of Time for Adverse Weather",
    "text": "The Contractor shall be entitled to an extension...",
    "risk_level": "medium",
    "entitlement_types": ["time_extension"],
    "keywords": ["weather", "extension", "delay"]
  }}
]

CONTRACT TEXT:
{truncated_text}

JSON RESPONSE:"""

    async def _invoke_bedrock(self, prompt: str) -> str:
        """Invoke Bedrock Claude model"""

        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 8000,
            "messages": [{"role": "user", "content": prompt}],
        }

        try:
            response = await aws_services._run_in_executor(
                aws_services.bedrock_runtime.invoke_model,
                modelId=self.ANALYSIS_MODEL,
                body=json.dumps(body),
            )

            response_body = json.loads(response["body"].read())
            return response_body["content"][0]["text"]

        except Exception as e:
            logger.error(f"Bedrock invocation failed: {e}")
            raise Exception(f"AI analysis failed: {str(e)}")

    def _parse_clause_response(self, response: str) -> List[Dict[str, Any]]:
        """Parse LLM response into structured clause data"""
        try:
            # Try to extract JSON from response
            json_match = re.search(r"\[.*\]", response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return []
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM clause response as JSON: {e}")
            return []

    async def _vectorize_clauses(
        self,
        clauses: List[Dict[str, Any]],
        uploaded_contract: UploadedContract,
        db: Session,
    ):
        """Generate embeddings and store in vector database"""

        uploaded_contract.progress_percent = 65
        db.commit()

        # Get extracted clauses from database
        extracted_clauses = (
            db.query(ExtractedContractClause)
            .filter(
                ExtractedContractClause.uploaded_contract_id == uploaded_contract.id
            )
            .all()
        )

        if not extracted_clauses:
            uploaded_contract.progress_percent = 90
            db.commit()
            return

        # Prepare texts for embedding
        texts = []
        payloads = []
        ids = []

        for clause in extracted_clauses:
            # Create rich text for embedding
            text = f"{clause.clause_title or ''}\n{clause.clause_text}\nKeywords: {', '.join(clause.keywords or [])}"
            texts.append(text)

            payloads.append(
                {
                    "entity_type": "uploaded_clause",
                    "entity_id": clause.id,
                    "clause_number": clause.clause_number,
                    "contract_id": uploaded_contract.id,
                    "contract_type_id": uploaded_contract.contract_type_id,
                    "risk_level": clause.risk_level,
                    "filename": uploaded_contract.filename,
                }
            )

            vector_id = f"uploaded_clause_{clause.id}"
            ids.append(vector_id)
            clause.vector_id = vector_id

        if texts:
            # Generate embeddings
            embeddings = await embedding_service.generate_embeddings(texts)

            # Store in vector database
            await vector_store.upsert_vectors(embeddings, payloads, ids)

        uploaded_contract.progress_percent = 90
        uploaded_contract.processed_clauses = len(extracted_clauses)
        db.commit()

    async def _match_standard_clauses(
        self,
        uploaded_contract: UploadedContract,
        db: Session,
    ):
        """Match extracted clauses to standard clause definitions"""

        # Get standard clauses for this contract type
        standard_clauses = (
            db.query(CIContractClause)
            .filter(
                CIContractClause.contract_type_id == uploaded_contract.contract_type_id
            )
            .all()
        )

        if not standard_clauses:
            return

        # Get extracted clauses
        extracted_clauses = (
            db.query(ExtractedContractClause)
            .filter(
                ExtractedContractClause.uploaded_contract_id == uploaded_contract.id
            )
            .all()
        )

        # For each extracted clause, find best matching standard clause
        for extracted in extracted_clauses:
            best_match = None
            best_score = 0.0

            for standard in standard_clauses:
                score = self._calculate_match_score(extracted, standard)
                if score > best_score and score > 0.3:
                    best_score = score
                    best_match = standard

            if best_match:
                extracted.matched_standard_clause_id = best_match.id
                extracted.match_score = best_score

        db.commit()

    def _calculate_match_score(
        self,
        extracted: ExtractedContractClause,
        standard: CIContractClause,
    ) -> float:
        """Calculate similarity score between extracted and standard clause"""
        score = 0.0

        # Clause number match (exact or partial)
        if extracted.clause_number and standard.clause_number:
            if extracted.clause_number == standard.clause_number:
                score += 0.5
            elif extracted.clause_number.startswith(
                standard.clause_number.split(".")[0]
            ):
                score += 0.2

        # Keyword overlap
        extracted_keywords = set(k.lower() for k in (extracted.keywords or []))
        standard_keywords = set(k.lower() for k in (standard.keywords or []))

        if extracted_keywords and standard_keywords:
            overlap = len(extracted_keywords & standard_keywords)
            total = len(extracted_keywords | standard_keywords)
            if total > 0:
                score += 0.3 * (overlap / total)

        # Risk level match
        if extracted.risk_level == standard.risk_level:
            score += 0.2

        return min(score, 1.0)

    async def get_upload_status(
        self,
        db: Session,
        upload_id: int,
    ) -> Dict[str, Any]:
        """Get processing status for an uploaded contract"""

        uploaded_contract = (
            db.query(UploadedContract).filter(UploadedContract.id == upload_id).first()
        )

        if not uploaded_contract:
            raise ValueError(f"Upload not found: {upload_id}")

        return {
            "upload_id": uploaded_contract.id,
            "status": uploaded_contract.status,
            "progress_percent": uploaded_contract.progress_percent,
            "total_clauses": uploaded_contract.total_clauses,
            "processed_clauses": uploaded_contract.processed_clauses,
            "error_message": uploaded_contract.error_message,
            "extracted_metadata": uploaded_contract.extracted_metadata,
            "filename": uploaded_contract.filename,
            "created_at": (
                uploaded_contract.created_at.isoformat()
                if uploaded_contract.created_at
                else None
            ),
            "processed_at": (
                uploaded_contract.processed_at.isoformat()
                if uploaded_contract.processed_at
                else None
            ),
        }

    async def get_extracted_clauses(
        self,
        db: Session,
        upload_id: int,
    ) -> List[Dict[str, Any]]:
        """Get extracted clauses for an uploaded contract"""

        clauses = (
            db.query(ExtractedContractClause)
            .filter(ExtractedContractClause.uploaded_contract_id == upload_id)
            .all()
        )

        return [
            {
                "id": c.id,
                "clause_number": c.clause_number,
                "title": c.clause_title,
                "text": (
                    c.clause_text[:500] + "..."
                    if len(c.clause_text or "") > 500
                    else c.clause_text
                ),
                "full_text": c.clause_text,
                "risk_level": c.risk_level,
                "entitlement_types": c.entitlement_types,
                "keywords": c.keywords,
                "confidence_score": c.confidence_score,
                "matched_standard_clause_id": c.matched_standard_clause_id,
                "match_score": c.match_score,
            }
            for c in clauses
        ]


# Singleton instance
contract_upload_service = ContractUploadService()
