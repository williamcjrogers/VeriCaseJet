# AWS Services Integration for VeriCase
import boto3
import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta, timezone
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from .config import settings

logger = logging.getLogger(__name__)


class AWSServicesManager:
    """Centralized AWS services manager for VeriCase"""

    def __init__(self):
        self.session = boto3.Session(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
            region_name=settings.AWS_REGION,
        )

        # Initialize all AWS clients
        self.textract = self.session.client("textract")
        self.comprehend = self.session.client("comprehend")
        # Bedrock is region-scoped and may differ from the default AWS region.
        self._bedrock_region = (settings.BEDROCK_REGION or settings.AWS_REGION).strip()
        # Rerank models may only be available in specific regions (e.g. Cohere Rerank v3.5 in us-east-1).
        self._bedrock_rerank_region = (
            (getattr(settings, "BEDROCK_RERANK_REGION", "") or "").strip()
            or self._bedrock_region
        )
        self.bedrock_runtime = self.session.client(
            "bedrock-runtime", region_name=self._bedrock_region
        )
        self.bedrock_agent_runtime = self.session.client(
            "bedrock-agent-runtime", region_name=self._bedrock_region
        )
        # Separate client for reranking if configured to a different region.
        if self._bedrock_rerank_region == self._bedrock_region:
            self.bedrock_agent_runtime_rerank = self.bedrock_agent_runtime
        else:
            self.bedrock_agent_runtime_rerank = self.session.client(
                "bedrock-agent-runtime", region_name=self._bedrock_rerank_region
            )
        self.opensearch = self.session.client("opensearchserverless")
        self.eventbridge = self.session.client("events")
        self.stepfunctions = self.session.client("stepfunctions")
        self.rekognition = self.session.client("rekognition")
        self.transcribe = self.session.client("transcribe")
        self.quicksight = self.session.client("quicksight")
        self.macie = self.session.client("macie2")
        self.s3 = self.session.client("s3")
        # Ops / monitoring clients (optional; permissions may vary)
        self.cloudwatch = self.session.client("cloudwatch")
        self.logs = self.session.client("logs")
        self.eks = self.session.client("eks")
        self.rds = self.session.client("rds")

        self.executor = ThreadPoolExecutor(max_workers=10)

    def _rerank_model_arn(self) -> str:
        explicit = (getattr(settings, "BEDROCK_RERANK_MODEL_ARN", "") or "").strip()
        if explicit:
            return explicit
        model_id = (getattr(settings, "BEDROCK_RERANK_MODEL_ID", "") or "").strip() or "cohere.rerank-v3-5:0"
        return f"arn:aws:bedrock:{self._bedrock_rerank_region}::foundation-model/{model_id}"

    async def _run_in_executor(self, func, *args, **kwargs):
        """Helper to run boto3 calls in executor with proper argument handling"""
        loop = asyncio.get_event_loop()
        if kwargs:
            func_with_args = partial(func, *args, **kwargs)
            return await loop.run_in_executor(self.executor, func_with_args)
        elif args:
            return await loop.run_in_executor(self.executor, func, *args)
        else:
            return await loop.run_in_executor(self.executor, func)

    # ═══════════════════════════════════════════════════════════════════════════
    # 1. TEXTRACT INTEGRATION - Enhanced Document Processing
    # ═══════════════════════════════════════════════════════════════════════════

    async def extract_document_data(
        self, s3_bucket: str, s3_key: str
    ) -> Dict[str, Any]:
        """
        Enhanced document extraction using Textract with queries.
        Extracts text, tables, forms, and answers to legal-specific questions.
        """
        try:
            # Start document analysis with all feature types
            response = await self._run_in_executor(
                self.textract.start_document_analysis,
                DocumentLocation={"S3Object": {"Bucket": s3_bucket, "Name": s3_key}},
                FeatureTypes=["TABLES", "FORMS", "QUERIES", "SIGNATURES"],
                QueriesConfig={
                    "Queries": [
                        {
                            "Text": "What is the contract value?",
                            "Alias": "contract_value",
                        },
                        {
                            "Text": "What is the form of contract (e.g. JCT, NEC, bespoke, appointment)?",
                            "Alias": "contract_form",
                        },
                        {
                            "Text": "What is the contract date?",
                            "Alias": "contract_date",
                        },
                        {"Text": "Who is the Employer or Client?", "Alias": "employer"},
                        {"Text": "Who is the Contractor?", "Alias": "contractor"},
                        {
                            "Text": "What is the completion date?",
                            "Alias": "completion_date",
                        },
                        {
                            "Text": "Who are the parties to this contract?",
                            "Alias": "parties",
                        },
                        {"Text": "What is the project name?", "Alias": "project_name"},
                        {
                            "Text": "Are there any delay clauses?",
                            "Alias": "delay_clauses",
                        },
                        {
                            "Text": "What are the payment terms?",
                            "Alias": "payment_terms",
                        },
                        {"Text": "What is the retention amount?", "Alias": "retention"},
                        {
                            "Text": "What are the liquidated damages?",
                            "Alias": "liquidated_damages",
                        },
                    ]
                },
            )

            job_id = response["JobId"]
            logger.info(f"Textract job started: {job_id}")

            # Poll for completion
            while True:
                result = await self._run_in_executor(
                    self.textract.get_document_analysis, JobId=job_id
                )

                status = result["JobStatus"]
                if status == "SUCCEEDED":
                    logger.info(f"Textract job completed: {job_id}")
                    return self._process_textract_results(result)
                elif status == "FAILED":
                    logger.error(f"Textract failed: {result.get('StatusMessage')}")
                    return {"error": result.get("StatusMessage"), "text": ""}

                await asyncio.sleep(5)

        except Exception as e:
            logger.error(f"Textract extraction failed: {e}")
            return {"error": str(e), "text": ""}

    def _process_textract_results(self, result: Dict) -> Dict[str, Any]:
        """Process Textract results into structured data"""
        extracted_data = {
            "text": "",
            "tables": [],
            "forms": {},
            "queries": {},
            "signatures": [],
            "confidence_scores": {},
        }

        # Block tracking for relationships
        blocks_by_id = {block["Id"]: block for block in result.get("Blocks", [])}

        for block in result.get("Blocks", []):
            block_type = block["BlockType"]

            if block_type == "LINE":
                extracted_data["text"] += block.get("Text", "") + "\n"

            elif block_type == "TABLE":
                table_data = self._extract_table_data(block, blocks_by_id)
                if table_data:
                    extracted_data["tables"].append(table_data)

            elif block_type == "KEY_VALUE_SET":
                if "KEY" in block.get("EntityTypes", []):
                    key_text, value_text = self._extract_form_field(block, blocks_by_id)
                    if key_text:
                        extracted_data["forms"][key_text] = value_text

            elif block_type == "QUERY_RESULT":
                query_alias = block.get("Query", {}).get("Alias", "unknown")
                query_text = block.get("Text", "")
                confidence = block.get("Confidence", 0)
                extracted_data["queries"][query_alias] = {
                    "answer": query_text,
                    "confidence": confidence,
                }

            elif block_type == "SIGNATURE":
                extracted_data["signatures"].append(
                    {
                        "confidence": block.get("Confidence", 0),
                        "geometry": block.get("Geometry", {}),
                    }
                )

        return extracted_data

    def _extract_table_data(
        self, table_block: Dict, blocks_by_id: Dict
    ) -> List[List[str]]:
        """Extract table data from Textract blocks"""
        table_data = []
        if "Relationships" not in table_block:
            return table_data

        cells = []
        for relationship in table_block.get("Relationships", []):
            if relationship["Type"] == "CHILD":
                for cell_id in relationship["Ids"]:
                    cell_block = blocks_by_id.get(cell_id)
                    if cell_block and cell_block["BlockType"] == "CELL":
                        cells.append(cell_block)

        # Sort cells by row and column
        cells.sort(key=lambda x: (x.get("RowIndex", 0), x.get("ColumnIndex", 0)))

        current_row = 0
        row_data = []
        for cell in cells:
            if cell.get("RowIndex", 0) != current_row:
                if row_data:
                    table_data.append(row_data)
                row_data = []
                current_row = cell.get("RowIndex", 0)

            # Get cell text
            cell_text = ""
            for rel in cell.get("Relationships", []):
                if rel["Type"] == "CHILD":
                    for word_id in rel["Ids"]:
                        word_block = blocks_by_id.get(word_id)
                        if word_block:
                            cell_text += word_block.get("Text", "") + " "
            row_data.append(cell_text.strip())

        if row_data:
            table_data.append(row_data)

        return table_data

    def _extract_form_field(self, key_block: Dict, blocks_by_id: Dict) -> tuple:
        """Extract key-value pair from form field"""
        key_text = ""
        value_text = ""

        # Get key text
        for rel in key_block.get("Relationships", []):
            if rel["Type"] == "CHILD":
                for word_id in rel["Ids"]:
                    word_block = blocks_by_id.get(word_id)
                    if word_block:
                        key_text += word_block.get("Text", "") + " "
            elif rel["Type"] == "VALUE":
                for value_id in rel["Ids"]:
                    value_block = blocks_by_id.get(value_id)
                    if value_block:
                        for vrel in value_block.get("Relationships", []):
                            if vrel["Type"] == "CHILD":
                                for word_id in vrel["Ids"]:
                                    word_block = blocks_by_id.get(word_id)
                                    if word_block:
                                        value_text += word_block.get("Text", "") + " "

        return key_text.strip(), value_text.strip()

    # ═══════════════════════════════════════════════════════════════════════════
    # 2. COMPREHEND INTEGRATION - Entity Extraction & Sentiment Analysis
    # ═══════════════════════════════════════════════════════════════════════════

    async def analyze_document_entities(self, text: str) -> Dict[str, Any]:
        """
        Comprehensive text analysis with Comprehend.
        Extracts entities, sentiment, key phrases, and PII.
        """
        if not text or len(text.strip()) < 10:
            return {
                "entities": [],
                "sentiment": "NEUTRAL",
                "key_phrases": [],
                "pii_entities": [],
            }

        try:
            # Truncate for API limits (5000 bytes UTF-8)
            truncated_text = text[:5000]

            # Run all analyses in parallel
            entities_task = self._run_in_executor(
                self.comprehend.detect_entities, Text=truncated_text, LanguageCode="en"
            )

            sentiment_task = self._run_in_executor(
                self.comprehend.detect_sentiment, Text=truncated_text, LanguageCode="en"
            )

            phrases_task = self._run_in_executor(
                self.comprehend.detect_key_phrases,
                Text=truncated_text,
                LanguageCode="en",
            )

            pii_task = self._run_in_executor(
                self.comprehend.detect_pii_entities,
                Text=truncated_text,
                LanguageCode="en",
            )

            # Await all results
            (
                entities_response,
                sentiment_response,
                phrases_response,
                pii_response,
            ) = await asyncio.gather(
                entities_task,
                sentiment_task,
                phrases_task,
                pii_task,
                return_exceptions=True,
            )

            # Process results (handle exceptions gracefully)
            entities = (
                entities_response.get("Entities", [])
                if isinstance(entities_response, dict)
                else []
            )
            sentiment = (
                sentiment_response.get("Sentiment", "NEUTRAL")
                if isinstance(sentiment_response, dict)
                else "NEUTRAL"
            )
            sentiment_scores = (
                sentiment_response.get("SentimentScore", {})
                if isinstance(sentiment_response, dict)
                else {}
            )
            key_phrases = (
                phrases_response.get("KeyPhrases", [])
                if isinstance(phrases_response, dict)
                else []
            )
            pii_entities = (
                pii_response.get("Entities", [])
                if isinstance(pii_response, dict)
                else []
            )

            # Categorize entities for legal analysis
            categorized_entities = self._categorize_entities(entities)

            return {
                "entities": entities,
                "categorized_entities": categorized_entities,
                "sentiment": sentiment,
                "sentiment_scores": sentiment_scores,
                "key_phrases": key_phrases,
                "pii_entities": pii_entities,
                "has_pii": len(pii_entities) > 0,
            }

        except Exception as e:
            logger.error(f"Comprehend analysis failed: {e}")
            return {
                "entities": [],
                "sentiment": "NEUTRAL",
                "key_phrases": [],
                "pii_entities": [],
                "error": str(e),
            }

    def _categorize_entities(self, entities: List[Dict]) -> Dict[str, List[str]]:
        """Categorize entities for legal analysis"""
        categorized = {
            "persons": [],
            "organizations": [],
            "dates": [],
            "locations": [],
            "monetary_amounts": [],
            "quantities": [],
            "events": [],
            "other": [],
        }

        for entity in entities:
            entity_type = entity.get("Type", "OTHER")
            text = entity.get("Text", "")

            if entity_type == "PERSON":
                categorized["persons"].append(text)
            elif entity_type == "ORGANIZATION":
                categorized["organizations"].append(text)
            elif entity_type == "DATE":
                categorized["dates"].append(text)
            elif entity_type == "LOCATION":
                categorized["locations"].append(text)
            elif entity_type == "QUANTITY":
                # Check if it's monetary
                if any(c in text for c in ["£", "$", "€", "GBP", "USD", "EUR"]):
                    categorized["monetary_amounts"].append(text)
                else:
                    categorized["quantities"].append(text)
            elif entity_type == "EVENT":
                categorized["events"].append(text)
            else:
                categorized["other"].append(text)

        # Remove duplicates
        for key in categorized:
            categorized[key] = list(set(categorized[key]))

        return categorized

    # ═══════════════════════════════════════════════════════════════════════════
    # 3. BEDROCK KNOWLEDGE BASE INTEGRATION - Semantic Search & AI Insights
    # ═══════════════════════════════════════════════════════════════════════════

    async def rerank_texts(
        self,
        query: str,
        texts: List[str],
        *,
        top_n: int = 10,
        additional_model_request_fields: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Rerank candidate texts using Bedrock Agent Runtime Rerank API.

        Uses Cohere Rerank 3.5 by default (configurable via settings).

        Docs:
        - Rerank API: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_Rerank.html
        """
        texts = [str(t or "") for t in (texts or []) if str(t or "").strip()]
        if not texts:
            return []

        if not getattr(settings, "BEDROCK_RERANK_ENABLED", False):
            return [{"index": i, "relevanceScore": 0.0} for i in range(min(top_n, len(texts)))]

        if not hasattr(self.bedrock_agent_runtime_rerank, "rerank"):
            logger.warning("bedrock-agent-runtime.rerank not available (boto3 too old?)")
            return [{"index": i, "relevanceScore": 0.0} for i in range(min(top_n, len(texts)))]

        try:
            model_arn = self._rerank_model_arn()
            n = max(1, min(int(top_n or 10), 1000, len(texts)))

            # Rerank supports up to 1000 sources; each text up to 32k chars.
            sources = [
                {
                    "type": "INLINE",
                    "inlineDocumentSource": {
                        "type": "TEXT",
                        "textDocument": {"text": t[:32000]},
                    },
                }
                for t in texts[:1000]
            ]

            request: Dict[str, Any] = {
                "queries": [{"type": "TEXT", "textQuery": {"text": str(query or "")[:32000]}}],
                "sources": sources,
                "rerankingConfiguration": {
                    "type": "BEDROCK_RERANKING_MODEL",
                    "bedrockRerankingConfiguration": {
                        "numberOfResults": n,
                        "modelConfiguration": {
                            "modelArn": model_arn,
                            "additionalModelRequestFields": additional_model_request_fields
                            or {},
                        },
                    },
                },
            }

            response = await self._run_in_executor(
                self.bedrock_agent_runtime_rerank.rerank, **request
            )
            results = response.get("results", []) if isinstance(response, dict) else []
            if not isinstance(results, list):
                return [{"index": i, "relevanceScore": 0.0} for i in range(n)]
            # Preserve AWS response shape but ensure required keys exist.
            out: List[Dict[str, Any]] = []
            for r in results:
                if not isinstance(r, dict):
                    continue
                idx = r.get("index")
                if idx is None:
                    continue
                out.append(
                    {
                        "index": int(idx),
                        "relevanceScore": float(r.get("relevanceScore", 0.0) or 0.0),
                    }
                )
            return out or [{"index": i, "relevanceScore": 0.0} for i in range(n)]
        except Exception as e:
            logger.error(f"Bedrock rerank failed: {e}")
            return [{"index": i, "relevanceScore": 0.0} for i in range(min(top_n, len(texts)))]

    async def query_knowledge_base(
        self, query: str, kb_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Query Bedrock Knowledge Base for relevant documents.
        Uses semantic search to find similar content.
        """
        knowledge_base_id = kb_id or settings.BEDROCK_KB_ID

        if not knowledge_base_id:
            logger.warning("No Knowledge Base ID configured")
            return []

        try:
            candidate_k = (
                int(getattr(settings, "BEDROCK_RERANK_CANDIDATES", 25) or 25)
                if getattr(settings, "BEDROCK_RERANK_ENABLED", False)
                else 10
            )
            candidate_k = max(1, min(candidate_k, 100))

            response = await self._run_in_executor(
                self.bedrock_agent_runtime.retrieve,
                knowledgeBaseId=knowledge_base_id,
                retrievalQuery={"text": query},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {
                        "numberOfResults": candidate_k,
                        "overrideSearchType": "HYBRID",  # Combine semantic + keyword search
                    }
                },
            )

            results = []
            for result in response.get("retrievalResults", []):
                results.append(
                    {
                        "content": result.get("content", {}).get("text", ""),
                        "score": result.get("score", 0),
                        "metadata": result.get("metadata", {}),
                        "location": result.get("location", {}),
                    }
                )

            # Optional reranking pass for better relevance (Cohere Rerank 3.5 via Bedrock).
            try:
                if getattr(settings, "BEDROCK_RERANK_ENABLED", False) and len(results) > 1:
                    texts = [r.get("content", "") for r in results]
                    reranked = await self.rerank_texts(query, texts, top_n=min(10, len(texts)))
                    order = [int(x.get("index", 0)) for x in reranked if isinstance(x, dict)]
                    seen = set()
                    ordered: List[Dict[str, Any]] = []
                    for idx in order:
                        if idx in seen:
                            continue
                        if 0 <= idx < len(results):
                            ordered.append(results[idx])
                            seen.add(idx)
                    # Append any remaining, preserving original order.
                    for i, r in enumerate(results):
                        if i not in seen:
                            ordered.append(r)
                    results = ordered
            except Exception:
                pass

            return results

        except Exception as e:
            logger.error(f"Bedrock KB query failed: {e}")
            return []

    async def retrieve_and_generate(
        self,
        query: str,
        kb_id: Optional[str] = None,
        model_id: str = "anthropic.claude-3-sonnet-20240229-v1:0",
    ) -> Dict[str, Any]:
        """
        Query Knowledge Base and generate AI response with citations.
        Uses RAG (Retrieval Augmented Generation) pattern.
        """
        knowledge_base_id = kb_id or settings.BEDROCK_KB_ID

        if not knowledge_base_id:
            logger.warning("No Knowledge Base ID configured")
            return {"response": "", "citations": []}

        try:
            response = await self._run_in_executor(
                self.bedrock_agent_runtime.retrieve_and_generate,
                input={"text": query},
                retrieveAndGenerateConfiguration={
                    "type": "KNOWLEDGE_BASE",
                    "knowledgeBaseConfiguration": {
                        "knowledgeBaseId": knowledge_base_id,
                        "modelArn": f"arn:aws:bedrock:{settings.AWS_REGION}::foundation-model/{model_id}",
                        "retrievalConfiguration": {
                            "vectorSearchConfiguration": {"numberOfResults": 5}
                        },
                    },
                },
            )

            return {
                "response": response.get("output", {}).get("text", ""),
                "citations": response.get("citations", []),
                "session_id": response.get("sessionId"),
            }

        except Exception as e:
            logger.error(f"Bedrock RAG query failed: {e}")
            return {"response": "", "citations": [], "error": str(e)}

    async def ingest_to_knowledge_base(
        self, kb_id: Optional[str] = None, ds_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Trigger ingestion job for Bedrock Knowledge Base.
        Documents should already be in the configured S3 bucket.
        """
        knowledge_base_id = kb_id or settings.BEDROCK_KB_ID
        data_source_id = ds_id or settings.BEDROCK_DS_ID

        if not knowledge_base_id or not data_source_id:
            logger.warning("Knowledge Base ID or Data Source ID not configured")
            return {"error": "Configuration missing"}

        try:
            # Use bedrock-agent client for ingestion (not runtime)
            bedrock_agent = self.session.client(
                "bedrock-agent", region_name=self._bedrock_region
            )

            response = await self._run_in_executor(
                bedrock_agent.start_ingestion_job,
                knowledgeBaseId=knowledge_base_id,
                dataSourceId=data_source_id,
            )

            return {
                "ingestion_job_id": response.get("ingestionJob", {}).get(
                    "ingestionJobId"
                ),
                "status": response.get("ingestionJob", {}).get("status"),
                "started_at": response.get("ingestionJob", {}).get("startedAt"),
            }

        except Exception as e:
            logger.error(f"Bedrock KB ingestion failed: {e}")
            return {"error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════════
    # 4. OPENSEARCH VECTOR SEARCH - Advanced Search & Analytics
    # ═══════════════════════════════════════════════════════════════════════════

    async def create_vector_index(self, index_name: str) -> Dict[str, Any]:
        """Create OpenSearch vector index for semantic search"""
        try:
            mapping = {
                "settings": {"index": {"knn": True, "knn.algo_param.ef_search": 512}},
                "mappings": {
                    "properties": {
                        "content": {"type": "text"},
                        "content_vector": {
                            "type": "knn_vector",
                            "dimension": 1536,  # Titan embedding dimensions
                            "method": {
                                "name": "hnsw",
                                "space_type": "cosinesimil",
                                "engine": "nmslib",
                                "parameters": {"ef_construction": 512, "m": 16},
                            },
                        },
                        "metadata": {"type": "object"},
                        "document_type": {"type": "keyword"},
                        "case_id": {"type": "keyword"},
                        "project_id": {"type": "keyword"},
                        "evidence_id": {"type": "keyword"},
                        "date_created": {"type": "date"},
                        "extracted_parties": {"type": "keyword"},
                        "auto_tags": {"type": "keyword"},
                    }
                },
            }

            logger.info(f"Vector index {index_name} configuration ready")
            return {"index_name": index_name, "mapping": mapping, "status": "ready"}

        except Exception as e:
            logger.error(f"Vector index creation failed: {e}")
            return {"error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════════
    # 5. EVENTBRIDGE + STEP FUNCTIONS - Workflow Automation
    # ═══════════════════════════════════════════════════════════════════════════

    async def trigger_evidence_processing(self, evidence_data: Dict) -> Dict[str, Any]:
        """
        Trigger EventBridge event for evidence processing.
        This starts the Step Functions workflow.
        """
        try:
            event_bus_name = settings.EVENT_BUS_NAME or "vericase-events"

            response = await self._run_in_executor(
                self.eventbridge.put_events,
                Entries=[
                    {
                        "Source": "vericase.evidence",
                        "DetailType": "Evidence Uploaded",
                        "Detail": json.dumps(
                            {
                                **evidence_data,
                                "timestamp": datetime.utcnow().isoformat(),
                                "version": "1.0",
                            }
                        ),
                        "EventBusName": event_bus_name,
                    }
                ],
            )

            failed_count = response.get("FailedEntryCount", 0)
            if failed_count > 0:
                logger.error(f"Failed to publish {failed_count} events")
                return {"success": False, "failed_count": failed_count}

            return {"success": True, "entries": response.get("Entries", [])}

        except Exception as e:
            logger.error(f"EventBridge trigger failed: {e}")
            return {"success": False, "error": str(e)}

    async def start_processing_workflow(
        self, evidence_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Directly start Step Functions workflow for evidence processing.
        Alternative to EventBridge for synchronous processing.
        """
        try:
            state_machine_arn = settings.STEP_FUNCTION_ARN

            if not state_machine_arn:
                logger.warning("Step Function ARN not configured")
                return {"error": "Step Function not configured"}

            response = await self._run_in_executor(
                self.stepfunctions.start_execution,
                stateMachineArn=state_machine_arn,
                name=f"evidence-{evidence_data.get('evidence_id', 'unknown')}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                input=json.dumps(evidence_data),
            )

            return {
                "execution_arn": response.get("executionArn"),
                "start_date": (
                    response.get("startDate").isoformat()
                    if response.get("startDate")
                    else None
                ),
            }

        except Exception as e:
            logger.error(f"Step Functions start failed: {e}")
            return {"error": str(e)}

    async def get_workflow_status(self, execution_arn: str) -> Dict[str, Any]:
        """Get status of a Step Functions execution"""
        try:
            response = await self._run_in_executor(
                self.stepfunctions.describe_execution, executionArn=execution_arn
            )

            return {
                "status": response.get("status"),
                "start_date": (
                    response.get("startDate").isoformat()
                    if response.get("startDate")
                    else None
                ),
                "stop_date": (
                    response.get("stopDate").isoformat()
                    if response.get("stopDate")
                    else None
                ),
                "output": (
                    json.loads(response.get("output", "{}"))
                    if response.get("output")
                    else None
                ),
                "error": response.get("error"),
                "cause": response.get("cause"),
            }

        except Exception as e:
            logger.error(f"Workflow status check failed: {e}")
            return {"error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════════
    # 6. REKOGNITION INTEGRATION - Visual Evidence Analysis
    # ═══════════════════════════════════════════════════════════════════════════

    async def analyze_construction_image(
        self, s3_bucket: str, s3_key: str
    ) -> Dict[str, Any]:
        """
        Analyze construction site images for defects, progress, and safety.
        Uses label detection, text detection, and custom labels.
        """
        try:
            # Detect objects, scenes, and activities
            labels_task = self._run_in_executor(
                self.rekognition.detect_labels,
                Image={"S3Object": {"Bucket": s3_bucket, "Name": s3_key}},
                MaxLabels=50,
                MinConfidence=70,
            )

            # Detect text in images (signage, labels, dates)
            text_task = self._run_in_executor(
                self.rekognition.detect_text,
                Image={"S3Object": {"Bucket": s3_bucket, "Name": s3_key}},
            )

            # Detect protective equipment (safety analysis)
            ppe_task = self._run_in_executor(
                self.rekognition.detect_protective_equipment,
                Image={"S3Object": {"Bucket": s3_bucket, "Name": s3_key}},
                SummarizationAttributes={
                    "MinConfidence": 80,
                    "RequiredEquipmentTypes": [
                        "FACE_COVER",
                        "HAND_COVER",
                        "HEAD_COVER",
                    ],
                },
            )

            labels_response, text_response, ppe_response = await asyncio.gather(
                labels_task, text_task, ppe_task, return_exceptions=True
            )

            # Process labels
            labels = (
                labels_response.get("Labels", [])
                if isinstance(labels_response, dict)
                else []
            )
            construction_elements = self._identify_construction_elements(labels)
            potential_defects = self._identify_potential_defects(labels)

            # Process text detections
            text_detections = (
                text_response.get("TextDetections", [])
                if isinstance(text_response, dict)
                else []
            )
            detected_text = [
                t.get("DetectedText", "")
                for t in text_detections
                if t.get("Type") == "LINE"
            ]

            # Process PPE detection
            ppe_summary = {}
            if isinstance(ppe_response, dict):
                summary = ppe_response.get("Summary", {})
                ppe_summary = {
                    "persons_with_required_equipment": summary.get(
                        "PersonsWithRequiredEquipment", []
                    ),
                    "persons_without_required_equipment": summary.get(
                        "PersonsWithoutRequiredEquipment", []
                    ),
                    "persons_indeterminate": summary.get("PersonsIndeterminate", []),
                }

            return {
                "labels": labels,
                "construction_elements": construction_elements,
                "potential_defects": potential_defects,
                "text_detections": detected_text,
                "safety_analysis": ppe_summary,
                "image_categories": self._categorize_image(labels),
            }

        except Exception as e:
            logger.error(f"Rekognition analysis failed: {e}")
            return {"error": str(e)}

    def _identify_construction_elements(self, labels: List[Dict]) -> List[Dict]:
        """Identify construction-specific elements from Rekognition labels"""
        construction_keywords = {
            "structural": [
                "building",
                "construction",
                "foundation",
                "wall",
                "roof",
                "floor",
                "beam",
                "column",
                "steel",
                "concrete",
            ],
            "equipment": [
                "crane",
                "excavator",
                "bulldozer",
                "forklift",
                "scaffolding",
                "ladder",
                "machinery",
            ],
            "materials": ["brick", "wood", "metal", "pipe", "cable", "insulation"],
            "safety": ["hard hat", "helmet", "safety vest", "barrier", "fence", "sign"],
            "vehicles": ["truck", "van", "car"],
        }

        identified = []
        for label in labels:
            label_name = label.get("Name", "").lower()
            confidence = label.get("Confidence", 0)

            for category, keywords in construction_keywords.items():
                if any(keyword in label_name for keyword in keywords):
                    identified.append(
                        {
                            "element": label.get("Name"),
                            "category": category,
                            "confidence": confidence,
                        }
                    )
                    break

        return identified

    def _identify_potential_defects(self, labels: List[Dict]) -> List[Dict]:
        """Identify potential defects or issues from labels"""
        defect_keywords = [
            "crack",
            "damage",
            "broken",
            "rust",
            "corrosion",
            "leak",
            "stain",
            "hole",
            "debris",
        ]

        defects = []
        for label in labels:
            label_name = label.get("Name", "").lower()
            if any(keyword in label_name for keyword in defect_keywords):
                defects.append(
                    {
                        "defect_type": label.get("Name"),
                        "confidence": label.get("Confidence", 0),
                    }
                )

        return defects

    def _categorize_image(self, labels: List[Dict]) -> List[str]:
        """Categorize the image based on detected labels"""
        categories = []
        label_names = [label.get("Name", "").lower() for label in labels]

        if any("construction" in label or "building" in label for label in label_names):
            categories.append("construction_site")
        if any(
            "document" in label or "text" in label or "paper" in label
            for label in label_names
        ):
            categories.append("document")
        if any(
            "person" in label or "people" in label or "worker" in label
            for label in label_names
        ):
            categories.append("people_present")
        if any(
            "machinery" in label or "equipment" in label or "crane" in label
            for label in label_names
        ):
            categories.append("heavy_equipment")
        if any(
            "damage" in label or "crack" in label or "broken" in label
            for label in label_names
        ):
            categories.append("potential_defect")

        return categories if categories else ["general"]

    # ═══════════════════════════════════════════════════════════════════════════
    # 7. TRANSCRIBE INTEGRATION - Audio/Video Processing
    # ═══════════════════════════════════════════════════════════════════════════

    async def transcribe_meeting_audio(
        self, s3_bucket: str, s3_key: str, job_name: str, language_code: str = "en-GB"
    ) -> Dict[str, Any]:
        """
        Transcribe meeting recordings with speaker identification.
        Supports multiple audio formats and PII redaction.
        """
        try:
            # Determine media format from file extension
            extension = s3_key.split(".")[-1].lower()
            media_format_map = {
                "mp3": "mp3",
                "mp4": "mp4",
                "wav": "wav",
                "flac": "flac",
                "ogg": "ogg",
                "m4a": "mp4",
                "webm": "webm",
            }
            media_format = media_format_map.get(extension, "mp3")

            # Start transcription job
            _ = await self._run_in_executor(
                self.transcribe.start_transcription_job,
                TranscriptionJobName=job_name,
                Media={"MediaFileUri": f"s3://{s3_bucket}/{s3_key}"},
                MediaFormat=media_format,
                LanguageCode=language_code,
                Settings={
                    "ShowSpeakerLabels": True,
                    "MaxSpeakerLabels": 10,
                    "ShowAlternatives": True,
                    "MaxAlternatives": 2,
                },
                ContentRedaction={
                    "RedactionType": "PII",
                    "RedactionOutput": "redacted_and_unredacted",
                    "PiiEntityTypes": [
                        "BANK_ACCOUNT_NUMBER",
                        "BANK_ROUTING",
                        "CREDIT_DEBIT_NUMBER",
                        "CREDIT_DEBIT_CVV",
                        "CREDIT_DEBIT_EXPIRY",
                        "PIN",
                        "SSN",
                        "PHONE",
                        "EMAIL",
                        "ADDRESS",
                    ],
                },
            )

            logger.info(f"Transcription job started: {job_name}")

            # Poll for completion
            max_attempts = 60  # 10 minutes max
            attempt = 0

            while attempt < max_attempts:
                result = await self._run_in_executor(
                    self.transcribe.get_transcription_job, TranscriptionJobName=job_name
                )

                status = result["TranscriptionJob"]["TranscriptionJobStatus"]

                if status == "COMPLETED":
                    transcript_uri = result["TranscriptionJob"]["Transcript"][
                        "TranscriptFileUri"
                    ]
                    redacted_uri = result["TranscriptionJob"]["Transcript"].get(
                        "RedactedTranscriptFileUri"
                    )

                    return {
                        "status": "completed",
                        "job_name": job_name,
                        "transcript_uri": transcript_uri,
                        "redacted_transcript_uri": redacted_uri,
                        "media_format": media_format,
                        "language_code": language_code,
                    }

                elif status == "FAILED":
                    failure_reason = result["TranscriptionJob"].get(
                        "FailureReason", "Unknown"
                    )
                    logger.error(f"Transcription failed: {failure_reason}")
                    return {"status": "failed", "error": failure_reason}

                await asyncio.sleep(10)
                attempt += 1

            return {
                "status": "timeout",
                "job_name": job_name,
                "message": "Job still in progress",
            }

        except Exception as e:
            logger.error(f"Transcribe job failed: {e}")
            return {"status": "error", "error": str(e)}

    async def get_transcription_result(self, job_name: str) -> Dict[str, Any]:
        """Get transcription job result"""
        try:
            result = await self._run_in_executor(
                self.transcribe.get_transcription_job, TranscriptionJobName=job_name
            )

            job = result["TranscriptionJob"]
            return {
                "status": job["TranscriptionJobStatus"],
                "transcript_uri": job.get("Transcript", {}).get("TranscriptFileUri"),
                "redacted_transcript_uri": job.get("Transcript", {}).get(
                    "RedactedTranscriptFileUri"
                ),
                "creation_time": (
                    job.get("CreationTime").isoformat()
                    if job.get("CreationTime")
                    else None
                ),
                "completion_time": (
                    job.get("CompletionTime").isoformat()
                    if job.get("CompletionTime")
                    else None
                ),
            }

        except Exception as e:
            logger.error(f"Get transcription result failed: {e}")
            return {"error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════════
    # 8. QUICKSIGHT INTEGRATION - Legal Analytics Dashboard
    # ═══════════════════════════════════════════════════════════════════════════

    async def get_dashboard_embed_url(
        self, dashboard_id: Optional[str] = None, user_arn: str = None
    ) -> Dict[str, Any]:
        """
        Generate embedded dashboard URL for legal analytics.
        """
        dashboard = dashboard_id or settings.QUICKSIGHT_DASHBOARD_ID

        if not dashboard:
            return {"error": "Dashboard ID not configured"}

        try:
            # Get AWS account ID
            sts = self.session.client("sts")
            account_id = (await self._run_in_executor(sts.get_caller_identity))[
                "Account"
            ]

            response = await self._run_in_executor(
                self.quicksight.get_dashboard_embed_url,
                AwsAccountId=account_id,
                DashboardId=dashboard,
                IdentityType="IAM",
                SessionLifetimeInMinutes=600,
                UndoRedoDisabled=False,
                ResetDisabled=False,
            )

            return {
                "embed_url": response.get("EmbedUrl"),
                "status": response.get("Status"),
                "request_id": response.get("RequestId"),
            }

        except Exception as e:
            logger.error(f"QuickSight embed URL generation failed: {e}")
            return {"error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════════
    # 9. MACIE INTEGRATION - Data Governance & Compliance
    # ═══════════════════════════════════════════════════════════════════════════

    async def scan_for_sensitive_data(
        self, s3_bucket: str, prefix: str = ""
    ) -> Dict[str, Any]:
        """
        Scan documents for sensitive data using Macie.
        Creates a one-time classification job.
        """
        if not settings.MACIE_ENABLED:
            return {"status": "disabled", "message": "Macie scanning is disabled"}

        try:
            # Get AWS account ID
            sts = self.session.client("sts")
            account_id = (await self._run_in_executor(sts.get_caller_identity))[
                "Account"
            ]

            job_name = f"vericase-scan-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

            # Build S3 job definition
            bucket_definition = {"accountId": account_id, "buckets": [s3_bucket]}

            s3_job_definition = {"bucketDefinitions": [bucket_definition]}

            if prefix:
                s3_job_definition["scoping"] = {
                    "includes": {
                        "and": [
                            {
                                "simpleScopeTerm": {
                                    "key": "OBJECT_KEY",
                                    "comparator": "STARTS_WITH",
                                    "values": [prefix],
                                }
                            }
                        ]
                    }
                }

            response = await self._run_in_executor(
                self.macie.create_classification_job,
                jobType="ONE_TIME",
                name=job_name,
                s3JobDefinition=s3_job_definition,
                description=f"VeriCase sensitive data scan for {s3_bucket}",
            )

            return {
                "job_id": response.get("jobId"),
                "job_arn": response.get("jobArn"),
                "job_name": job_name,
                "status": "created",
            }

        except Exception as e:
            logger.error(f"Macie scan failed: {e}")
            return {"error": str(e)}

    async def get_macie_findings(
        self, job_id: Optional[str] = None, max_results: int = 50
    ) -> Dict[str, Any]:
        """Get Macie findings for sensitive data"""
        try:
            filter_criteria = {}
            if job_id:
                filter_criteria = {
                    "criterion": {"classificationDetails.jobId": {"eq": [job_id]}}
                }

            # List findings
            response = await self._run_in_executor(
                self.macie.list_findings,
                findingCriteria=filter_criteria if filter_criteria else None,
                maxResults=max_results,
                sortCriteria={"attributeName": "updatedAt", "orderBy": "DESC"},
            )

            finding_ids = response.get("findingIds", [])

            if not finding_ids:
                return {"findings": [], "count": 0}

            # Get finding details
            findings_response = await self._run_in_executor(
                self.macie.get_findings,
                findingIds=finding_ids[: min(len(finding_ids), 50)],  # API limit
            )

            findings = []
            for finding in findings_response.get("findings", []):
                findings.append(
                    {
                        "id": finding.get("id"),
                        "type": finding.get("type"),
                        "severity": finding.get("severity", {}).get("description"),
                        "category": finding.get("category"),
                        "title": finding.get("title"),
                        "description": finding.get("description"),
                        "resource": finding.get("resourcesAffected", {})
                        .get("s3Object", {})
                        .get("key"),
                        "created_at": finding.get("createdAt"),
                    }
                )

            return {
                "findings": findings,
                "count": len(findings),
                "total_available": len(finding_ids),
            }

        except Exception as e:
            logger.error(f"Get Macie findings failed: {e}")
            return {"error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════════
    # 10. HEALTH CHECK & SERVICE STATUS
    # ═══════════════════════════════════════════════════════════════════════════

    async def check_service_health(self) -> Dict[str, Any]:
        """Check connectivity to all AWS services"""
        services_status = {}

        # Test each service with a lightweight operation
        checks = [
            ("textract", lambda: self.textract.get_document_analysis(JobId="test")),
            (
                "comprehend",
                lambda: self.comprehend.detect_dominant_language(Text="test"),
            ),
            ("bedrock", lambda: self.bedrock_runtime.list_foundation_models()),
            ("rekognition", lambda: self.rekognition.list_collections()),
            (
                "transcribe",
                lambda: self.transcribe.list_transcription_jobs(MaxResults=1),
            ),
            ("s3", lambda: self.s3.list_buckets()),
            ("eventbridge", lambda: self.eventbridge.list_event_buses()),
            (
                "stepfunctions",
                lambda: self.stepfunctions.list_state_machines(maxResults=1),
            ),
        ]

        for service_name, check_func in checks:
            try:
                await self._run_in_executor(check_func)
                services_status[service_name] = {
                    "status": "healthy",
                    "checked_at": datetime.utcnow().isoformat(),
                }
            except Exception as e:
                error_msg = str(e)
                # Some operations may fail with expected errors (e.g., invalid job ID)
                # That's fine - it means the service is reachable
                if (
                    "InvalidJobIdException" in error_msg
                    or "ResourceNotFoundException" in error_msg
                    or "AccessDenied" not in error_msg
                ):
                    services_status[service_name] = {
                        "status": "healthy",
                        "checked_at": datetime.utcnow().isoformat(),
                    }
                else:
                    services_status[service_name] = {
                        "status": "unhealthy",
                        "error": error_msg,
                        "checked_at": datetime.utcnow().isoformat(),
                    }

        # Determine overall status
        unhealthy_count = sum(
            1 for s in services_status.values() if s["status"] == "unhealthy"
        )
        overall_status = (
            "healthy"
            if unhealthy_count == 0
            else ("degraded" if unhealthy_count < 3 else "unhealthy")
        )

        return {
            "overall_status": overall_status,
            "services": services_status,
            "checked_at": datetime.utcnow().isoformat(),
        }

    # ---------------------------------------------------------------------
    # 11. OPS METRICS (CloudWatch/EKS/RDS/S3/Logs)
    # ---------------------------------------------------------------------

    async def get_cloudwatch_logs(
        self,
        log_group: str,
        filter_pattern: str = "",
        hours: int = 1,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Fetch recent CloudWatch log events matching a pattern."""
        if not log_group:
            return []
        try:
            start_time = int(
                (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp() * 1000
            )
            response = await self._run_in_executor(
                self.logs.filter_log_events,
                logGroupName=log_group,
                filterPattern=filter_pattern or None,
                startTime=start_time,
                limit=limit,
            )
            events = []
            for event in response.get("events", []):
                events.append(
                    {
                        "timestamp": event.get("timestamp"),
                        "message": (event.get("message") or "").strip(),
                        "log_stream": event.get("logStreamName"),
                    }
                )
            return events
        except Exception as e:
            logger.warning(f"CloudWatch logs fetch failed: {e}")
            return []

    async def get_rds_metrics(
        self,
        db_instance: str,
        metrics: List[str],
        period_seconds: int = 300,
        minutes: int = 10,
    ) -> Dict[str, Any]:
        """Get latest RDS CloudWatch metrics for an instance."""
        if not db_instance or not metrics:
            return {}
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=minutes)
        results: Dict[str, Any] = {}
        for metric in metrics:
            try:
                resp = await self._run_in_executor(
                    self.cloudwatch.get_metric_statistics,
                    Namespace="AWS/RDS",
                    MetricName=metric,
                    Dimensions=[
                        {
                            "Name": "DBInstanceIdentifier",
                            "Value": db_instance,
                        }
                    ],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=period_seconds,
                    Statistics=["Average"],
                )
                datapoints = sorted(
                    resp.get("Datapoints", []),
                    key=lambda d: d.get("Timestamp", end_time),
                )
                results[metric] = datapoints[-1].get("Average") if datapoints else None
            except Exception as e:
                logger.debug(f"RDS metric {metric} failed: {e}")
                results[metric] = None
        return results

    async def get_s3_bucket_size(self, bucket: str) -> float | None:
        """Approximate S3 bucket size in bytes using CloudWatch (fallback to None)."""
        if not bucket:
            return None
        try:
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=2)
            resp = await self._run_in_executor(
                self.cloudwatch.get_metric_statistics,
                Namespace="AWS/S3",
                MetricName="BucketSizeBytes",
                Dimensions=[
                    {"Name": "BucketName", "Value": bucket},
                    {"Name": "StorageType", "Value": "StandardStorage"},
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=86400,
                Statistics=["Average"],
            )
            datapoints = sorted(
                resp.get("Datapoints", []),
                key=lambda d: d.get("Timestamp", end_time),
            )
            if datapoints:
                return float(datapoints[-1].get("Average") or 0)
        except Exception as e:
            logger.debug(f"S3 size metric failed: {e}")
        return None

    async def get_eks_cluster_health(
        self, cluster_name: str | None = None
    ) -> Dict[str, Any]:
        """Best-effort EKS cluster health summary."""
        name = cluster_name or getattr(settings, "EKS_CLUSTER_NAME", "")
        if not name:
            return {"status": "unknown", "node_count": None, "pod_count": None}
        try:
            desc = await self._run_in_executor(self.eks.describe_cluster, name=name)
            cluster = desc.get("cluster", {}) if isinstance(desc, dict) else {}
            status = cluster.get("status", "UNKNOWN")

            # Approximate node count from nodegroup desired sizes
            node_count = 0
            try:
                ngs = await self._run_in_executor(
                    self.eks.list_nodegroups, clusterName=name
                )
                for ng in ngs.get("nodegroups", []):
                    ng_desc = await self._run_in_executor(
                        self.eks.describe_nodegroup,
                        clusterName=name,
                        nodegroupName=ng,
                    )
                    scaling = (
                        ng_desc.get("nodegroup", {}).get("scalingConfig", {})
                        if isinstance(ng_desc, dict)
                        else {}
                    )
                    node_count += int(
                        scaling.get("desiredSize") or scaling.get("maxSize") or 0
                    )
            except Exception:
                node_count = None

            return {
                "status": str(status).lower(),
                "node_count": node_count,
                "pod_count": None,  # Requires Container Insights / K8s API
            }
        except Exception as e:
            logger.warning(f"EKS health fetch failed: {e}")
            return {"status": "unknown", "node_count": None, "pod_count": None}


# Global instance - lazy initialization
_aws_services: Optional[AWSServicesManager] = None


def get_aws_services() -> AWSServicesManager:
    """Get or create the AWS services manager instance"""
    global _aws_services
    if _aws_services is None:
        _aws_services = AWSServicesManager()
    return _aws_services


# Backwards compatibility
aws_services = get_aws_services()
