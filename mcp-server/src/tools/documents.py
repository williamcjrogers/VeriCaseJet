"""Document and File Management Tools for VeriCase."""

import logging
from typing import Any, Optional

from mcp.types import Tool, TextContent

from ..utils.api_client import api_client, VeriCaseAPIError

logger = logging.getLogger(__name__)


class DocumentTools:
    """Tools for managing documents and files in VeriCase."""

    @staticmethod
    def get_tools() -> list[Tool]:
        """Return list of document-related MCP tools."""
        return [
            Tool(
                name="list_documents",
                description="List all documents in the system with optional filtering. Returns document metadata including name, type, size, upload date, and status.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "folder_id": {
                            "type": "string",
                            "description": "Filter by folder ID (UUID)",
                        },
                        "document_type": {
                            "type": "string",
                            "description": "Filter by document type (e.g., 'contract', 'drawing', 'invoice', 'expert_report', 'correspondence')",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "processing", "ready", "error"],
                            "description": "Filter by processing status",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 50,
                            "description": "Maximum number of documents to return",
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
                name="get_document",
                description="Get detailed information about a specific document including metadata, text excerpt, processing status, and linked evidence.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "The UUID of the document to retrieve",
                        },
                    },
                    "required": ["document_id"],
                },
            ),
            Tool(
                name="get_document_content",
                description="Get the extracted text content of a document. Useful for analyzing document contents, searching for specific information, or preparing evidence summaries.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "The UUID of the document",
                        },
                        "max_chars": {
                            "type": "integer",
                            "default": 10000,
                            "description": "Maximum characters to return (default 10000)",
                        },
                    },
                    "required": ["document_id"],
                },
            ),
            Tool(
                name="create_folder",
                description="Create a new folder to organize documents. Folders can be nested for hierarchical organization.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of the folder",
                        },
                        "parent_folder_id": {
                            "type": "string",
                            "description": "Parent folder UUID for nested folders (optional)",
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of the folder's purpose",
                        },
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="move_document",
                description="Move a document to a different folder for organization.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "UUID of the document to move",
                        },
                        "target_folder_id": {
                            "type": "string",
                            "description": "UUID of the destination folder",
                        },
                    },
                    "required": ["document_id", "target_folder_id"],
                },
            ),
            Tool(
                name="update_document_metadata",
                description="Update document metadata such as tags, description, document type, or custom fields.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "UUID of the document to update",
                        },
                        "name": {
                            "type": "string",
                            "description": "New document name",
                        },
                        "description": {
                            "type": "string",
                            "description": "Document description",
                        },
                        "document_type": {
                            "type": "string",
                            "description": "Document type classification",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of tags for categorization",
                        },
                        "metadata": {
                            "type": "object",
                            "description": "Custom metadata key-value pairs",
                        },
                    },
                    "required": ["document_id"],
                },
            ),
            Tool(
                name="get_presigned_upload_url",
                description="Get a presigned S3 URL for uploading a new document. Use this to initiate document uploads.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Name of the file to upload",
                        },
                        "content_type": {
                            "type": "string",
                            "description": "MIME type of the file (e.g., 'application/pdf', 'image/png')",
                        },
                        "folder_id": {
                            "type": "string",
                            "description": "Optional folder to upload to",
                        },
                    },
                    "required": ["filename", "content_type"],
                },
            ),
            Tool(
                name="list_recent_documents",
                description="Get a list of recently accessed or modified documents for quick access.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "default": 20,
                            "description": "Number of recent documents to return",
                        },
                    },
                },
            ),
            Tool(
                name="get_document_versions",
                description="Get version history of a document showing all previous versions with timestamps and changes.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "UUID of the document",
                        },
                    },
                    "required": ["document_id"],
                },
            ),
            Tool(
                name="delete_document",
                description="Delete a document from the system. This performs a soft delete, preserving the document for audit purposes.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "UUID of the document to delete",
                        },
                    },
                    "required": ["document_id"],
                },
            ),
        ]

    @staticmethod
    async def handle_tool(name: str, arguments: dict) -> list[TextContent]:
        """Handle document tool calls."""
        try:
            if name == "list_documents":
                result = await DocumentTools._list_documents(arguments)
            elif name == "get_document":
                result = await DocumentTools._get_document(arguments["document_id"])
            elif name == "get_document_content":
                result = await DocumentTools._get_document_content(
                    arguments["document_id"],
                    arguments.get("max_chars", 10000),
                )
            elif name == "create_folder":
                result = await DocumentTools._create_folder(arguments)
            elif name == "move_document":
                result = await DocumentTools._move_document(
                    arguments["document_id"],
                    arguments["target_folder_id"],
                )
            elif name == "update_document_metadata":
                result = await DocumentTools._update_document_metadata(arguments)
            elif name == "get_presigned_upload_url":
                result = await DocumentTools._get_presigned_upload_url(arguments)
            elif name == "list_recent_documents":
                result = await DocumentTools._list_recent_documents(
                    arguments.get("limit", 20)
                )
            elif name == "get_document_versions":
                result = await DocumentTools._get_document_versions(
                    arguments["document_id"]
                )
            elif name == "delete_document":
                result = await DocumentTools._delete_document(arguments["document_id"])
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            return [TextContent(type="text", text=str(result))]
        except VeriCaseAPIError as e:
            return [TextContent(type="text", text=f"API Error: {e.message}")]
        except Exception as e:
            logger.exception(f"Error handling document tool {name}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    @staticmethod
    async def _list_documents(args: dict) -> dict:
        params = {k: v for k, v in args.items() if v is not None}
        return await api_client.get("/api/documents", params=params)

    @staticmethod
    async def _get_document(document_id: str) -> dict:
        return await api_client.get(f"/api/documents/{document_id}")

    @staticmethod
    async def _get_document_content(document_id: str, max_chars: int) -> dict:
        result = await api_client.get(f"/api/documents/{document_id}/content")
        if isinstance(result, dict) and "content" in result:
            result["content"] = result["content"][:max_chars]
        return result

    @staticmethod
    async def _create_folder(args: dict) -> dict:
        return await api_client.post("/api/folders", data=args)

    @staticmethod
    async def _move_document(document_id: str, target_folder_id: str) -> dict:
        return await api_client.patch(
            f"/api/documents/{document_id}",
            data={"folder_id": target_folder_id},
        )

    @staticmethod
    async def _update_document_metadata(args: dict) -> dict:
        document_id = args.pop("document_id")
        return await api_client.patch(f"/api/documents/{document_id}", data=args)

    @staticmethod
    async def _get_presigned_upload_url(args: dict) -> dict:
        return await api_client.post("/api/documents/presign", data=args)

    @staticmethod
    async def _list_recent_documents(limit: int) -> dict:
        return await api_client.get("/api/documents/recent", params={"limit": limit})

    @staticmethod
    async def _get_document_versions(document_id: str) -> dict:
        return await api_client.get(f"/api/documents/{document_id}/versions")

    @staticmethod
    async def _delete_document(document_id: str) -> dict:
        return await api_client.delete(f"/api/documents/{document_id}")
