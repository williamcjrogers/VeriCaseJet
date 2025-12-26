"""
VeriCase Case Law Agent
Interacts with Amazon Bedrock Agents to provide legal research assistance.
"""

import logging
from typing import Any, Dict, List

from botocore.exceptions import ClientError

from .aws_services import aws_services
from .config import settings

logger = logging.getLogger(__name__)


class CaseLawAgent:
    """
    Client for the VeriCase Case Law Bedrock Agent.
    Handles chat interactions, session management, and citation parsing.
    """

    def __init__(self):
        self.aws = aws_services
        self.client = self.aws.bedrock_agent_runtime
        self.agent_id = settings.BEDROCK_AGENT_ID
        self.agent_alias_id = settings.BEDROCK_AGENT_ALIAS_ID or "TSTALIASID"

    async def chat(
        self, query: str, session_id: str, enable_trace: bool = False
    ) -> Dict[str, Any]:
        """
        Send a message to the Case Law Agent.
        """
        if not self.agent_id:
            logger.warning("BEDROCK_AGENT_ID not set. Returning mock response.")
            return self._mock_response(query)

        try:
            response = await self.aws._run_in_executor(
                self.client.invoke_agent,
                agentId=self.agent_id,
                agentAliasId=self.agent_alias_id,
                sessionId=session_id,
                inputText=query,
                enableTrace=enable_trace,
            )

            completion = ""
            citations = []
            trace_info = []

            # Process the streaming response
            for event in response.get("completion") or []:
                if "chunk" in event:
                    chunk = event["chunk"]
                    chunk_bytes = chunk.get("bytes")
                    if chunk_bytes:
                        completion += chunk_bytes.decode("utf-8")

                    # Extract citations if available in attribution
                    if "attribution" in chunk:
                        citations.extend(self._parse_citations(chunk["attribution"]))

                elif "trace" in event and enable_trace:
                    trace_info.append(event["trace"])

            return {
                "response": completion,
                "citations": citations,
                "session_id": session_id,
                "trace": trace_info if enable_trace else None,
            }

        except ClientError as e:
            logger.error(f"Bedrock Agent invocation failed: {e}")
            return {"error": str(e)}

    def _parse_citations(self, attribution: Dict) -> List[Dict[str, Any]]:
        """Parse citations from Bedrock attribution"""
        citations = []
        for citation in attribution.get("citations", []):
            for ref in citation.get("retrievedReferences", []):
                citations.append(
                    {
                        "content": ref.get("content", {}).get("text"),
                        "location": ref.get("location", {}),
                        "metadata": ref.get("metadata", {}),
                    }
                )
        return citations

    def _mock_response(self, query: str) -> Dict[str, Any]:
        """Mock response for development"""
        return {
            "response": f"This is a simulated response from the Case Law Agent for query: '{query}'. \n\nBased on *Construction Co v Developer* [2023], delay damages are applicable.",
            "citations": [
                {
                    "content": "Paragraph 45: The court held that...",
                    "location": {
                        "s3Location": {
                            "uri": "s3://vericase-caselaw-curated/2023_EWHC_123.json"
                        }
                    },
                    "metadata": {"citation": "[2023] EWHC 123 (TCC)"},
                }
            ],
            "session_id": "mock-session",
        }

    async def search_knowledge_base(
        self, query: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Direct semantic search against the Case Law Knowledge Base.
        Useful for 'Find Similar Cases' features.
        """
        kb_id = settings.BEDROCK_KB_ID
        if not kb_id:
            return []

        try:
            response = await self.aws._run_in_executor(
                self.client.retrieve,
                knowledgeBaseId=kb_id,
                retrievalQuery={"text": query},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {
                        "numberOfResults": max(1, limit),
                        "overrideSearchType": "HYBRID",
                    }
                },
            )

            results = []
            for result in response.get("retrievalResults", []):
                results.append(
                    {
                        "content": result.get("content", {}).get("text"),
                        "score": result.get("score"),
                        "metadata": result.get("metadata"),
                        "location": result.get("location"),
                    }
                )
            return results

        except ClientError as e:
            logger.error(f"KB Retrieval failed: {e}")
            return []


# Singleton instance
caselaw_agent = CaseLawAgent()
