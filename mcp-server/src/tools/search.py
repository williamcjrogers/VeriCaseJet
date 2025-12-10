"""Search and Query Tools for VeriCase - Full-text and Correspondence Search."""

import logging
from typing import Any

from mcp.types import Tool, TextContent

from ..utils.api_client import api_client, VeriCaseAPIError

logger = logging.getLogger(__name__)


class SearchTools:
    """Tools for searching documents, emails, and correspondence."""

    @staticmethod
    def get_tools() -> list[Tool]:
        """Return list of search MCP tools."""
        return [
            Tool(
                name="search_emails",
                description="Search through email correspondence using full-text search. Search by keywords, sender, recipient, date range, or attachments.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (searches subject, body, and metadata)",
                        },
                        "case_id": {
                            "type": "string",
                            "description": "Limit search to a specific case",
                        },
                        "from_address": {
                            "type": "string",
                            "description": "Filter by sender email address",
                        },
                        "to_address": {
                            "type": "string",
                            "description": "Filter by recipient email address",
                        },
                        "date_from": {
                            "type": "string",
                            "format": "date",
                            "description": "Start date for date range filter (YYYY-MM-DD)",
                        },
                        "date_to": {
                            "type": "string",
                            "format": "date",
                            "description": "End date for date range filter (YYYY-MM-DD)",
                        },
                        "has_attachments": {
                            "type": "boolean",
                            "description": "Filter to emails with attachments only",
                        },
                        "attachment_type": {
                            "type": "string",
                            "enum": ["pdf", "doc", "xls", "image", "drawing", "any"],
                            "description": "Filter by attachment type",
                        },
                        "keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Required keywords that must appear in the email",
                        },
                        "exclude_keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Keywords to exclude from results",
                        },
                        "sort_by": {
                            "type": "string",
                            "enum": ["date", "relevance", "sender"],
                            "default": "relevance",
                            "description": "How to sort results",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 50,
                            "description": "Maximum results to return",
                        },
                        "offset": {
                            "type": "integer",
                            "default": 0,
                            "description": "Offset for pagination",
                        },
                    },
                },
            ),
            Tool(
                name="search_documents",
                description="Full-text search across all documents including extracted text content.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                        "case_id": {
                            "type": "string",
                            "description": "Limit search to a specific case",
                        },
                        "document_type": {
                            "type": "string",
                            "enum": ["contract", "drawing", "invoice", "certificate", "correspondence", "expert_report", "programme", "any"],
                            "description": "Filter by document type",
                        },
                        "date_from": {
                            "type": "string",
                            "format": "date",
                            "description": "Documents dated from (YYYY-MM-DD)",
                        },
                        "date_to": {
                            "type": "string",
                            "format": "date",
                            "description": "Documents dated to (YYYY-MM-DD)",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by tags",
                        },
                        "search_content": {
                            "type": "boolean",
                            "default": True,
                            "description": "Search within document text content",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 50,
                            "description": "Maximum results",
                        },
                    },
                },
            ),
            Tool(
                name="get_email_thread",
                description="Get a complete email thread/conversation based on Message-ID, In-Reply-To, and References headers.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "email_id": {
                            "type": "string",
                            "description": "Email UUID to get thread for",
                        },
                        "thread_id": {
                            "type": "string",
                            "description": "Thread ID to retrieve",
                        },
                        "include_attachments": {
                            "type": "boolean",
                            "default": True,
                            "description": "Include attachment metadata",
                        },
                    },
                },
            ),
            Tool(
                name="get_email_details",
                description="Get full details of a specific email including headers, body, and attachments.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "email_id": {
                            "type": "string",
                            "description": "Email UUID",
                        },
                        "include_raw_headers": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include raw email headers",
                        },
                    },
                    "required": ["email_id"],
                },
            ),
            Tool(
                name="search_by_stakeholder",
                description="Find all correspondence involving a specific stakeholder (person or organization).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "stakeholder": {
                            "type": "string",
                            "description": "Name or email of the stakeholder",
                        },
                        "case_id": {
                            "type": "string",
                            "description": "Limit to specific case",
                        },
                        "role": {
                            "type": "string",
                            "enum": ["sender", "recipient", "cc", "any"],
                            "default": "any",
                            "description": "Role in the correspondence",
                        },
                        "date_from": {
                            "type": "string",
                            "format": "date",
                        },
                        "date_to": {
                            "type": "string",
                            "format": "date",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 100,
                        },
                    },
                    "required": ["stakeholder"],
                },
            ),
            Tool(
                name="get_correspondence_stats",
                description="Get statistics about correspondence including email counts by date, sender distribution, and keyword frequency.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "Case to get stats for",
                        },
                        "date_from": {
                            "type": "string",
                            "format": "date",
                        },
                        "date_to": {
                            "type": "string",
                            "format": "date",
                        },
                        "group_by": {
                            "type": "string",
                            "enum": ["day", "week", "month", "sender", "keyword"],
                            "default": "month",
                        },
                    },
                },
            ),
            Tool(
                name="find_related_emails",
                description="Find emails related to a specific email based on content similarity, thread, or stakeholders.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "email_id": {
                            "type": "string",
                            "description": "Email to find related messages for",
                        },
                        "relation_type": {
                            "type": "string",
                            "enum": ["thread", "similar_content", "same_stakeholders", "same_topic", "all"],
                            "default": "all",
                            "description": "Type of relationship to find",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 20,
                        },
                    },
                    "required": ["email_id"],
                },
            ),
            Tool(
                name="search_attachments",
                description="Search specifically for email attachments by filename, type, or content.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query for filename or content",
                        },
                        "case_id": {
                            "type": "string",
                            "description": "Limit to specific case",
                        },
                        "file_type": {
                            "type": "string",
                            "enum": ["pdf", "doc", "docx", "xls", "xlsx", "dwg", "image", "any"],
                            "description": "Filter by file type",
                        },
                        "min_size_kb": {
                            "type": "integer",
                            "description": "Minimum file size in KB",
                        },
                        "max_size_kb": {
                            "type": "integer",
                            "description": "Maximum file size in KB",
                        },
                        "date_from": {
                            "type": "string",
                            "format": "date",
                        },
                        "date_to": {
                            "type": "string",
                            "format": "date",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 50,
                        },
                    },
                },
            ),
            Tool(
                name="advanced_query",
                description="Execute an advanced query using OpenSearch query DSL for complex search requirements.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query_dsl": {
                            "type": "object",
                            "description": "OpenSearch query DSL object",
                        },
                        "index": {
                            "type": "string",
                            "enum": ["emails", "documents", "attachments", "all"],
                            "default": "all",
                            "description": "Index to search",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 50,
                        },
                    },
                    "required": ["query_dsl"],
                },
            ),
        ]

    @staticmethod
    async def handle_tool(name: str, arguments: dict) -> list[TextContent]:
        """Handle search tool calls."""
        try:
            if name == "search_emails":
                result = await SearchTools._search_emails(arguments)
            elif name == "search_documents":
                result = await SearchTools._search_documents(arguments)
            elif name == "get_email_thread":
                result = await SearchTools._get_email_thread(arguments)
            elif name == "get_email_details":
                result = await SearchTools._get_email_details(arguments["email_id"], arguments)
            elif name == "search_by_stakeholder":
                result = await SearchTools._search_by_stakeholder(arguments)
            elif name == "get_correspondence_stats":
                result = await SearchTools._get_correspondence_stats(arguments)
            elif name == "find_related_emails":
                result = await SearchTools._find_related_emails(arguments)
            elif name == "search_attachments":
                result = await SearchTools._search_attachments(arguments)
            elif name == "advanced_query":
                result = await SearchTools._advanced_query(arguments)
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            return [TextContent(type="text", text=str(result))]
        except VeriCaseAPIError as e:
            return [TextContent(type="text", text=f"API Error: {e.message}")]
        except Exception as e:
            logger.exception(f"Error handling search tool {name}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    @staticmethod
    async def _search_emails(args: dict) -> dict:
        return await api_client.post("/api/correspondence/search", data=args)

    @staticmethod
    async def _search_documents(args: dict) -> dict:
        return await api_client.post("/api/documents/search", data=args)

    @staticmethod
    async def _get_email_thread(args: dict) -> dict:
        if "thread_id" in args:
            return await api_client.get(f"/api/correspondence/threads/{args['thread_id']}")
        return await api_client.get(f"/api/correspondence/{args.get('email_id')}/thread")

    @staticmethod
    async def _get_email_details(email_id: str, args: dict) -> dict:
        params = {"include_raw_headers": args.get("include_raw_headers", False)}
        return await api_client.get(f"/api/correspondence/{email_id}", params=params)

    @staticmethod
    async def _search_by_stakeholder(args: dict) -> dict:
        return await api_client.post("/api/correspondence/stakeholder-search", data=args)

    @staticmethod
    async def _get_correspondence_stats(args: dict) -> dict:
        return await api_client.get("/api/correspondence/stats", params=args)

    @staticmethod
    async def _find_related_emails(args: dict) -> dict:
        email_id = args.pop("email_id")
        return await api_client.get(f"/api/correspondence/{email_id}/related", params=args)

    @staticmethod
    async def _search_attachments(args: dict) -> dict:
        return await api_client.post("/api/correspondence/attachments/search", data=args)

    @staticmethod
    async def _advanced_query(args: dict) -> dict:
        return await api_client.post("/api/search/advanced", data=args)
