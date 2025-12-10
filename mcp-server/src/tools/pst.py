"""PST File Processing Tools for VeriCase - Forensic Email Archive Management."""

import logging
from typing import Any

from mcp.types import Tool, TextContent

from ..utils.api_client import api_client, VeriCaseAPIError

logger = logging.getLogger(__name__)


class PSTTools:
    """Tools for processing and managing PST email archives."""

    @staticmethod
    def get_tools() -> list[Tool]:
        """Return list of PST processing MCP tools."""
        return [
            Tool(
                name="upload_pst",
                description="Initiate a PST file upload. Returns a presigned URL for uploading the PST file to secure storage.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Name of the PST file",
                        },
                        "case_id": {
                            "type": "string",
                            "description": "Case UUID to associate the PST with",
                        },
                        "file_size_bytes": {
                            "type": "integer",
                            "description": "Size of the PST file in bytes",
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of the PST contents (e.g., 'Project Manager emails 2020-2023')",
                        },
                        "custodian": {
                            "type": "string",
                            "description": "Name of the email custodian/owner",
                        },
                    },
                    "required": ["filename", "case_id"],
                },
            ),
            Tool(
                name="process_pst",
                description="Start processing an uploaded PST file. Extracts emails, attachments, and metadata for indexing.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pst_id": {
                            "type": "string",
                            "description": "UUID of the uploaded PST file",
                        },
                        "extract_attachments": {
                            "type": "boolean",
                            "default": True,
                            "description": "Extract and store email attachments",
                        },
                        "ocr_attachments": {
                            "type": "boolean",
                            "default": True,
                            "description": "Perform OCR on image/PDF attachments",
                        },
                        "index_content": {
                            "type": "boolean",
                            "default": True,
                            "description": "Index email content for full-text search",
                        },
                        "deduplicate": {
                            "type": "boolean",
                            "default": True,
                            "description": "Deduplicate attachments by SHA-256 hash",
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["low", "normal", "high"],
                            "default": "normal",
                            "description": "Processing priority",
                        },
                    },
                    "required": ["pst_id"],
                },
            ),
            Tool(
                name="get_pst_status",
                description="Get the processing status of a PST file including progress, email count, and any errors.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pst_id": {
                            "type": "string",
                            "description": "UUID of the PST file",
                        },
                    },
                    "required": ["pst_id"],
                },
            ),
            Tool(
                name="list_pst_files",
                description="List all PST files in the system with their processing status.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "Filter by case UUID",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "processing", "completed", "error"],
                            "description": "Filter by processing status",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 50,
                        },
                    },
                },
            ),
            Tool(
                name="get_pst_statistics",
                description="Get detailed statistics about a processed PST file including email counts, date ranges, top senders/recipients, and attachment breakdown.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pst_id": {
                            "type": "string",
                            "description": "UUID of the PST file",
                        },
                    },
                    "required": ["pst_id"],
                },
            ),
            Tool(
                name="get_pst_folders",
                description="Get the folder structure from a PST file (Inbox, Sent Items, custom folders, etc.).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pst_id": {
                            "type": "string",
                            "description": "UUID of the PST file",
                        },
                    },
                    "required": ["pst_id"],
                },
            ),
            Tool(
                name="reprocess_pst",
                description="Reprocess a PST file with different settings. Useful for re-extracting with OCR or different deduplication options.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pst_id": {
                            "type": "string",
                            "description": "UUID of the PST file to reprocess",
                        },
                        "extract_attachments": {"type": "boolean", "default": True},
                        "ocr_attachments": {"type": "boolean", "default": True},
                        "force_reindex": {
                            "type": "boolean",
                            "default": False,
                            "description": "Force reindexing even if already indexed",
                        },
                    },
                    "required": ["pst_id"],
                },
            ),
            Tool(
                name="get_pst_errors",
                description="Get any errors encountered during PST processing for troubleshooting.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pst_id": {
                            "type": "string",
                            "description": "UUID of the PST file",
                        },
                    },
                    "required": ["pst_id"],
                },
            ),
            Tool(
                name="cancel_pst_processing",
                description="Cancel an in-progress PST processing job.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pst_id": {
                            "type": "string",
                            "description": "UUID of the PST file",
                        },
                    },
                    "required": ["pst_id"],
                },
            ),
            Tool(
                name="verify_pst_integrity",
                description="Verify the forensic integrity of a PST file by checking hash values and chain of custody.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pst_id": {
                            "type": "string",
                            "description": "UUID of the PST file",
                        },
                    },
                    "required": ["pst_id"],
                },
            ),
        ]

    @staticmethod
    async def handle_tool(name: str, arguments: dict) -> list[TextContent]:
        """Handle PST tool calls."""
        try:
            if name == "upload_pst":
                result = await PSTTools._upload_pst(arguments)
            elif name == "process_pst":
                result = await PSTTools._process_pst(arguments)
            elif name == "get_pst_status":
                result = await PSTTools._get_pst_status(arguments["pst_id"])
            elif name == "list_pst_files":
                result = await PSTTools._list_pst_files(arguments)
            elif name == "get_pst_statistics":
                result = await PSTTools._get_pst_statistics(arguments["pst_id"])
            elif name == "get_pst_folders":
                result = await PSTTools._get_pst_folders(arguments["pst_id"])
            elif name == "reprocess_pst":
                result = await PSTTools._reprocess_pst(arguments)
            elif name == "get_pst_errors":
                result = await PSTTools._get_pst_errors(arguments["pst_id"])
            elif name == "cancel_pst_processing":
                result = await PSTTools._cancel_pst_processing(arguments["pst_id"])
            elif name == "verify_pst_integrity":
                result = await PSTTools._verify_pst_integrity(arguments["pst_id"])
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            return [TextContent(type="text", text=str(result))]
        except VeriCaseAPIError as e:
            return [TextContent(type="text", text=f"API Error: {e.message}")]
        except Exception as e:
            logger.exception(f"Error handling PST tool {name}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    @staticmethod
    async def _upload_pst(args: dict) -> dict:
        return await api_client.post("/api/pst/upload", data=args)

    @staticmethod
    async def _process_pst(args: dict) -> dict:
        pst_id = args.pop("pst_id")
        return await api_client.post(f"/api/pst/{pst_id}/process", data=args)

    @staticmethod
    async def _get_pst_status(pst_id: str) -> dict:
        return await api_client.get(f"/api/pst/{pst_id}/status")

    @staticmethod
    async def _list_pst_files(args: dict) -> dict:
        return await api_client.get("/api/pst", params=args)

    @staticmethod
    async def _get_pst_statistics(pst_id: str) -> dict:
        return await api_client.get(f"/api/pst/{pst_id}/statistics")

    @staticmethod
    async def _get_pst_folders(pst_id: str) -> dict:
        return await api_client.get(f"/api/pst/{pst_id}/folders")

    @staticmethod
    async def _reprocess_pst(args: dict) -> dict:
        pst_id = args.pop("pst_id")
        return await api_client.post(f"/api/pst/{pst_id}/reprocess", data=args)

    @staticmethod
    async def _get_pst_errors(pst_id: str) -> dict:
        return await api_client.get(f"/api/pst/{pst_id}/errors")

    @staticmethod
    async def _cancel_pst_processing(pst_id: str) -> dict:
        return await api_client.post(f"/api/pst/{pst_id}/cancel")

    @staticmethod
    async def _verify_pst_integrity(pst_id: str) -> dict:
        return await api_client.get(f"/api/pst/{pst_id}/integrity")
