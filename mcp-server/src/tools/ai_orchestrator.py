"""AI Orchestration Tools for VeriCase - Multi-Model Analysis and Research."""

import logging
from typing import Any

from mcp.types import Tool, TextContent

from ..utils.api_client import api_client, VeriCaseAPIError

logger = logging.getLogger(__name__)


class AITools:
    """Tools for AI-powered analysis, research, and evidence intelligence."""

    @staticmethod
    def get_tools() -> list[Tool]:
        """Return list of AI orchestration MCP tools."""
        return [
            Tool(
                name="deep_analysis",
                description="Perform deep AI analysis on documents or evidence using multi-model orchestration. Analyzes content across multiple AI providers (Claude, GPT, Gemini, Bedrock) and synthesizes results for comprehensive insights.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The analysis question or research query",
                        },
                        "document_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of document UUIDs to analyze",
                        },
                        "case_id": {
                            "type": "string",
                            "description": "Case UUID to scope the analysis (optional)",
                        },
                        "analysis_type": {
                            "type": "string",
                            "enum": [
                                "summarize",
                                "extract_facts",
                                "identify_issues",
                                "analyze_causation",
                                "timeline_analysis",
                                "quantum_analysis",
                                "compare_documents",
                                "custom",
                            ],
                            "description": "Type of analysis to perform",
                        },
                        "use_thinking_mode": {
                            "type": "boolean",
                            "default": False,
                            "description": "Enable extended reasoning for complex analysis",
                        },
                        "models": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["claude", "gpt", "gemini", "bedrock"],
                            },
                            "description": "Specific AI models to use (defaults to all available)",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="evidence_assistant",
                description="Conversational AI assistant for evidence analysis. Ask questions about documents, emails, or case materials and get intelligent responses with source citations.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Your question or request about the evidence",
                        },
                        "case_id": {
                            "type": "string",
                            "description": "Case UUID to scope the conversation",
                        },
                        "context_document_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific documents to use as context",
                        },
                        "conversation_id": {
                            "type": "string",
                            "description": "Conversation ID for multi-turn dialogue",
                        },
                    },
                    "required": ["message"],
                },
            ),
            Tool(
                name="generate_claim_narrative",
                description="Generate a professional claim narrative from evidence. Creates structured claim documentation following construction dispute best practices.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "Case UUID to generate narrative for",
                        },
                        "claim_type": {
                            "type": "string",
                            "enum": ["delay", "disruption", "variations", "loss_and_expense", "defects"],
                            "description": "Type of claim narrative to generate",
                        },
                        "include_chronology": {
                            "type": "boolean",
                            "default": True,
                            "description": "Include timeline of events",
                        },
                        "include_quantum": {
                            "type": "boolean",
                            "default": True,
                            "description": "Include quantum/cost analysis",
                        },
                        "style": {
                            "type": "string",
                            "enum": ["formal", "executive_summary", "detailed", "scott_schedule"],
                            "default": "formal",
                            "description": "Writing style for the narrative",
                        },
                    },
                    "required": ["case_id", "claim_type"],
                },
            ),
            Tool(
                name="analyze_delay_causation",
                description="AI-powered delay and causation analysis. Identifies critical path impacts, concurrent delays, and employer/contractor responsibility allocation.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "Case UUID for delay analysis",
                        },
                        "delay_events": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {"type": "string"},
                                    "start_date": {"type": "string"},
                                    "end_date": {"type": "string"},
                                    "responsible_party": {"type": "string"},
                                },
                            },
                            "description": "List of delay events to analyze",
                        },
                        "method": {
                            "type": "string",
                            "enum": ["as_planned_vs_as_built", "impacted_as_planned", "collapsed_as_built", "time_impact"],
                            "default": "as_planned_vs_as_built",
                            "description": "Delay analysis methodology",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
            Tool(
                name="extract_key_facts",
                description="Extract key facts from documents using AI. Identifies dates, amounts, parties, contractual terms, and other critical information.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "document_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Documents to extract facts from",
                        },
                        "fact_types": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": [
                                    "dates",
                                    "amounts",
                                    "parties",
                                    "obligations",
                                    "notices",
                                    "variations",
                                    "defects",
                                    "instructions",
                                ],
                            },
                            "description": "Types of facts to extract",
                        },
                        "output_format": {
                            "type": "string",
                            "enum": ["json", "table", "narrative"],
                            "default": "json",
                            "description": "Format for extracted facts",
                        },
                    },
                    "required": ["document_ids"],
                },
            ),
            Tool(
                name="compare_documents",
                description="AI-powered document comparison. Identifies differences, contradictions, and correlations between documents.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "document_id_1": {
                            "type": "string",
                            "description": "First document to compare",
                        },
                        "document_id_2": {
                            "type": "string",
                            "description": "Second document to compare",
                        },
                        "comparison_focus": {
                            "type": "string",
                            "enum": ["full", "dates", "amounts", "terms", "contradictions"],
                            "default": "full",
                            "description": "Focus area for comparison",
                        },
                    },
                    "required": ["document_id_1", "document_id_2"],
                },
            ),
            Tool(
                name="get_ai_health",
                description="Check the health and availability of AI providers. Returns status, latency, and cost information for each configured model.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="get_ai_analytics",
                description="Get AI usage analytics including cost tracking, model performance, and usage statistics.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "period": {
                            "type": "string",
                            "enum": ["day", "week", "month", "all"],
                            "default": "week",
                            "description": "Time period for analytics",
                        },
                        "group_by": {
                            "type": "string",
                            "enum": ["model", "function", "user", "case"],
                            "default": "model",
                            "description": "How to group the analytics",
                        },
                    },
                },
            ),
            Tool(
                name="semantic_search",
                description="Perform semantic search across documents and emails using AI embeddings. Find conceptually similar content even when keywords don't match.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language search query",
                        },
                        "case_id": {
                            "type": "string",
                            "description": "Limit search to a specific case",
                        },
                        "content_types": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["documents", "emails", "attachments"],
                            },
                            "description": "Types of content to search",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 20,
                            "description": "Maximum results to return",
                        },
                        "similarity_threshold": {
                            "type": "number",
                            "default": 0.7,
                            "description": "Minimum similarity score (0-1)",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="summarize_emails",
                description="Generate AI summaries of email threads or correspondence. Extracts key points, action items, and decisions from email chains.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "email_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Email UUIDs to summarize",
                        },
                        "thread_id": {
                            "type": "string",
                            "description": "Thread ID to summarize entire thread",
                        },
                        "summary_type": {
                            "type": "string",
                            "enum": ["brief", "detailed", "action_items", "decisions", "timeline"],
                            "default": "detailed",
                            "description": "Type of summary to generate",
                        },
                    },
                },
            ),
        ]

    @staticmethod
    async def handle_tool(name: str, arguments: dict) -> list[TextContent]:
        """Handle AI tool calls."""
        try:
            if name == "deep_analysis":
                result = await AITools._deep_analysis(arguments)
            elif name == "evidence_assistant":
                result = await AITools._evidence_assistant(arguments)
            elif name == "generate_claim_narrative":
                result = await AITools._generate_claim_narrative(arguments)
            elif name == "analyze_delay_causation":
                result = await AITools._analyze_delay_causation(arguments)
            elif name == "extract_key_facts":
                result = await AITools._extract_key_facts(arguments)
            elif name == "compare_documents":
                result = await AITools._compare_documents(arguments)
            elif name == "get_ai_health":
                result = await AITools._get_ai_health()
            elif name == "get_ai_analytics":
                result = await AITools._get_ai_analytics(arguments)
            elif name == "semantic_search":
                result = await AITools._semantic_search(arguments)
            elif name == "summarize_emails":
                result = await AITools._summarize_emails(arguments)
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            return [TextContent(type="text", text=str(result))]
        except VeriCaseAPIError as e:
            return [TextContent(type="text", text=f"API Error: {e.message}")]
        except Exception as e:
            logger.exception(f"Error handling AI tool {name}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    @staticmethod
    async def _deep_analysis(args: dict) -> dict:
        return await api_client.post("/api/ai-chat/research", data=args)

    @staticmethod
    async def _evidence_assistant(args: dict) -> dict:
        return await api_client.post("/api/ai-chat/message", data=args)

    @staticmethod
    async def _generate_claim_narrative(args: dict) -> dict:
        case_id = args.pop("case_id")
        return await api_client.post(f"/api/ai/cases/{case_id}/narrative", data=args)

    @staticmethod
    async def _analyze_delay_causation(args: dict) -> dict:
        case_id = args.pop("case_id")
        return await api_client.post(f"/api/ai/cases/{case_id}/delay-analysis", data=args)

    @staticmethod
    async def _extract_key_facts(args: dict) -> dict:
        return await api_client.post("/api/ai/extract-facts", data=args)

    @staticmethod
    async def _compare_documents(args: dict) -> dict:
        return await api_client.post("/api/ai/compare", data=args)

    @staticmethod
    async def _get_ai_health() -> dict:
        return await api_client.get("/api/ai/orchestrator/health")

    @staticmethod
    async def _get_ai_analytics(args: dict) -> dict:
        return await api_client.get("/api/ai/analytics", params=args)

    @staticmethod
    async def _semantic_search(args: dict) -> dict:
        return await api_client.post("/api/ai/semantic-search", data=args)

    @staticmethod
    async def _summarize_emails(args: dict) -> dict:
        return await api_client.post("/api/ai/summarize-emails", data=args)
