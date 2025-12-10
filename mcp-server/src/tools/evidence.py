"""Evidence Linking and Management Tools for VeriCase."""

import logging
from typing import Any

from mcp.types import Tool, TextContent

from ..utils.api_client import api_client, VeriCaseAPIError

logger = logging.getLogger(__name__)


class EvidenceTools:
    """Tools for linking evidence to cases, issues, and claims."""

    @staticmethod
    def get_tools() -> list[Tool]:
        """Return list of evidence linking MCP tools."""
        return [
            Tool(
                name="link_evidence",
                description="Link a document or email to a case issue as supporting evidence. Creates a traceable connection between evidence and legal issues.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "UUID of the document/email to link",
                        },
                        "case_id": {
                            "type": "string",
                            "description": "UUID of the case",
                        },
                        "issue_id": {
                            "type": "string",
                            "description": "UUID of the specific issue to link to (optional)",
                        },
                        "claim_id": {
                            "type": "string",
                            "description": "UUID of the claim to link to (optional)",
                        },
                        "relevance": {
                            "type": "string",
                            "enum": ["primary", "supporting", "contextual", "rebuttal"],
                            "default": "supporting",
                            "description": "How relevant this evidence is to the issue",
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of why this evidence is relevant",
                        },
                        "key_facts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Key facts this evidence establishes",
                        },
                        "page_references": {
                            "type": "string",
                            "description": "Specific page/paragraph references within the document",
                        },
                    },
                    "required": ["document_id", "case_id"],
                },
            ),
            Tool(
                name="get_evidence_links",
                description="Get all evidence linked to a case, issue, or claim.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "Filter by case UUID",
                        },
                        "issue_id": {
                            "type": "string",
                            "description": "Filter by issue UUID",
                        },
                        "claim_id": {
                            "type": "string",
                            "description": "Filter by claim UUID",
                        },
                        "relevance": {
                            "type": "string",
                            "enum": ["primary", "supporting", "contextual", "rebuttal"],
                            "description": "Filter by relevance level",
                        },
                        "include_document_details": {
                            "type": "boolean",
                            "default": True,
                            "description": "Include full document metadata",
                        },
                    },
                },
            ),
            Tool(
                name="update_evidence_link",
                description="Update an existing evidence link's relevance, description, or key facts.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "link_id": {
                            "type": "string",
                            "description": "UUID of the evidence link to update",
                        },
                        "relevance": {
                            "type": "string",
                            "enum": ["primary", "supporting", "contextual", "rebuttal"],
                        },
                        "description": {"type": "string"},
                        "key_facts": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "page_references": {"type": "string"},
                    },
                    "required": ["link_id"],
                },
            ),
            Tool(
                name="remove_evidence_link",
                description="Remove an evidence link (does not delete the document).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "link_id": {
                            "type": "string",
                            "description": "UUID of the evidence link to remove",
                        },
                    },
                    "required": ["link_id"],
                },
            ),
            Tool(
                name="find_related_evidence",
                description="Find documents that may be related to existing evidence based on content similarity, dates, or stakeholders.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Document to find related evidence for",
                        },
                        "case_id": {
                            "type": "string",
                            "description": "Limit search to a specific case",
                        },
                        "relation_types": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["similar_content", "same_date_range", "same_stakeholders", "same_topic", "referenced"],
                            },
                            "description": "Types of relationships to find",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 20,
                        },
                    },
                    "required": ["document_id"],
                },
            ),
            Tool(
                name="get_evidence_summary",
                description="Get a summary of all evidence for a case organized by issue or claim.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "Case UUID to summarize evidence for",
                        },
                        "group_by": {
                            "type": "string",
                            "enum": ["issue", "claim", "document_type", "date", "relevance"],
                            "default": "issue",
                            "description": "How to group the evidence summary",
                        },
                        "include_gaps": {
                            "type": "boolean",
                            "default": True,
                            "description": "Identify issues/claims lacking evidence",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
            Tool(
                name="bulk_link_evidence",
                description="Link multiple documents to a case/issue at once.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "document_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of document UUIDs to link",
                        },
                        "case_id": {
                            "type": "string",
                            "description": "Case UUID",
                        },
                        "issue_id": {
                            "type": "string",
                            "description": "Issue UUID (optional)",
                        },
                        "relevance": {
                            "type": "string",
                            "enum": ["primary", "supporting", "contextual", "rebuttal"],
                            "default": "supporting",
                        },
                        "description": {
                            "type": "string",
                            "description": "Shared description for all links",
                        },
                    },
                    "required": ["document_ids", "case_id"],
                },
            ),
            Tool(
                name="suggest_evidence_links",
                description="Use AI to suggest potential evidence links for unlinked documents in a case.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "Case UUID to analyze",
                        },
                        "document_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific documents to analyze (optional, analyzes all unlinked if not provided)",
                        },
                        "confidence_threshold": {
                            "type": "number",
                            "default": 0.7,
                            "description": "Minimum confidence score for suggestions (0-1)",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
            Tool(
                name="export_evidence_bundle",
                description="Export all evidence for a case/issue as a bundle with index and cross-references.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "Case UUID",
                        },
                        "issue_id": {
                            "type": "string",
                            "description": "Optional: limit to specific issue",
                        },
                        "format": {
                            "type": "string",
                            "enum": ["pdf_bundle", "zip", "index_only"],
                            "default": "pdf_bundle",
                            "description": "Export format",
                        },
                        "include_metadata": {
                            "type": "boolean",
                            "default": True,
                            "description": "Include document metadata in export",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
            Tool(
                name="get_evidence_chain",
                description="Get the chain of evidence showing how documents relate to each other and to issues/claims.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "Case UUID",
                        },
                        "start_document_id": {
                            "type": "string",
                            "description": "Optional: start chain from specific document",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
        ]

    @staticmethod
    async def handle_tool(name: str, arguments: dict) -> list[TextContent]:
        """Handle evidence tool calls."""
        try:
            if name == "link_evidence":
                result = await EvidenceTools._link_evidence(arguments)
            elif name == "get_evidence_links":
                result = await EvidenceTools._get_evidence_links(arguments)
            elif name == "update_evidence_link":
                result = await EvidenceTools._update_evidence_link(arguments)
            elif name == "remove_evidence_link":
                result = await EvidenceTools._remove_evidence_link(arguments["link_id"])
            elif name == "find_related_evidence":
                result = await EvidenceTools._find_related_evidence(arguments)
            elif name == "get_evidence_summary":
                result = await EvidenceTools._get_evidence_summary(arguments)
            elif name == "bulk_link_evidence":
                result = await EvidenceTools._bulk_link_evidence(arguments)
            elif name == "suggest_evidence_links":
                result = await EvidenceTools._suggest_evidence_links(arguments)
            elif name == "export_evidence_bundle":
                result = await EvidenceTools._export_evidence_bundle(arguments)
            elif name == "get_evidence_chain":
                result = await EvidenceTools._get_evidence_chain(arguments)
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            return [TextContent(type="text", text=str(result))]
        except VeriCaseAPIError as e:
            return [TextContent(type="text", text=f"API Error: {e.message}")]
        except Exception as e:
            logger.exception(f"Error handling evidence tool {name}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    @staticmethod
    async def _link_evidence(args: dict) -> dict:
        return await api_client.post("/api/evidence/link", data=args)

    @staticmethod
    async def _get_evidence_links(args: dict) -> dict:
        return await api_client.get("/api/evidence/links", params=args)

    @staticmethod
    async def _update_evidence_link(args: dict) -> dict:
        link_id = args.pop("link_id")
        return await api_client.patch(f"/api/evidence/links/{link_id}", data=args)

    @staticmethod
    async def _remove_evidence_link(link_id: str) -> dict:
        return await api_client.delete(f"/api/evidence/links/{link_id}")

    @staticmethod
    async def _find_related_evidence(args: dict) -> dict:
        document_id = args.pop("document_id")
        return await api_client.get(f"/api/evidence/{document_id}/related", params=args)

    @staticmethod
    async def _get_evidence_summary(args: dict) -> dict:
        case_id = args.pop("case_id")
        return await api_client.get(f"/api/cases/{case_id}/evidence/summary", params=args)

    @staticmethod
    async def _bulk_link_evidence(args: dict) -> dict:
        return await api_client.post("/api/evidence/bulk-link", data=args)

    @staticmethod
    async def _suggest_evidence_links(args: dict) -> dict:
        case_id = args.pop("case_id")
        return await api_client.post(f"/api/cases/{case_id}/evidence/suggest", data=args)

    @staticmethod
    async def _export_evidence_bundle(args: dict) -> dict:
        case_id = args.pop("case_id")
        return await api_client.post(f"/api/cases/{case_id}/evidence/export", data=args)

    @staticmethod
    async def _get_evidence_chain(args: dict) -> dict:
        case_id = args.pop("case_id")
        return await api_client.get(f"/api/cases/{case_id}/evidence/chain", params=args)
