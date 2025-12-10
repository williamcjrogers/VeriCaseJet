"""Azad MCP Server - Main Entry Point for VeriCase Integration."""

import asyncio
import logging
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    Resource,
    ResourceTemplate,
)

from .tools import (
    DocumentTools,
    CaseTools,
    AITools,
    SearchTools,
    TimelineTools,
    PSTTools,
    EvidenceTools,
)
from .utils.config import settings
from .utils.api_client import api_client

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# Initialize MCP Server
server = Server("azad-mcp-server")


# Tool name to handler mapping
TOOL_HANDLERS = {
    # Document tools
    "list_documents": DocumentTools,
    "get_document": DocumentTools,
    "get_document_content": DocumentTools,
    "create_folder": DocumentTools,
    "move_document": DocumentTools,
    "update_document_metadata": DocumentTools,
    "get_presigned_upload_url": DocumentTools,
    "list_recent_documents": DocumentTools,
    "get_document_versions": DocumentTools,
    "delete_document": DocumentTools,
    # Case tools
    "list_cases": CaseTools,
    "get_case": CaseTools,
    "create_case": CaseTools,
    "update_case": CaseTools,
    "get_heads_of_claim": CaseTools,
    "add_head_of_claim": CaseTools,
    "get_case_issues": CaseTools,
    "create_issue": CaseTools,
    "get_case_team": CaseTools,
    "add_case_team_member": CaseTools,
    "get_case_statistics": CaseTools,
    "get_case_deadlines": CaseTools,
    # AI tools
    "deep_analysis": AITools,
    "evidence_assistant": AITools,
    "generate_claim_narrative": AITools,
    "analyze_delay_causation": AITools,
    "extract_key_facts": AITools,
    "compare_documents": AITools,
    "get_ai_health": AITools,
    "get_ai_analytics": AITools,
    "semantic_search": AITools,
    "summarize_emails": AITools,
    # Search tools
    "search_emails": SearchTools,
    "search_documents": SearchTools,
    "get_email_thread": SearchTools,
    "get_email_details": SearchTools,
    "search_by_stakeholder": SearchTools,
    "get_correspondence_stats": SearchTools,
    "find_related_emails": SearchTools,
    "search_attachments": SearchTools,
    "advanced_query": SearchTools,
    # Timeline tools
    "get_chronology": TimelineTools,
    "add_chronology_event": TimelineTools,
    "update_chronology_event": TimelineTools,
    "delete_chronology_event": TimelineTools,
    "generate_chronology_from_emails": TimelineTools,
    "get_delay_analysis": TimelineTools,
    "get_critical_path_events": TimelineTools,
    "export_chronology": TimelineTools,
    "link_evidence_to_event": TimelineTools,
    "get_timeline_gaps": TimelineTools,
    # PST tools
    "upload_pst": PSTTools,
    "process_pst": PSTTools,
    "get_pst_status": PSTTools,
    "list_pst_files": PSTTools,
    "get_pst_statistics": PSTTools,
    "get_pst_folders": PSTTools,
    "reprocess_pst": PSTTools,
    "get_pst_errors": PSTTools,
    "cancel_pst_processing": PSTTools,
    "verify_pst_integrity": PSTTools,
    # Evidence tools
    "link_evidence": EvidenceTools,
    "get_evidence_links": EvidenceTools,
    "update_evidence_link": EvidenceTools,
    "remove_evidence_link": EvidenceTools,
    "find_related_evidence": EvidenceTools,
    "get_evidence_summary": EvidenceTools,
    "bulk_link_evidence": EvidenceTools,
    "suggest_evidence_links": EvidenceTools,
    "export_evidence_bundle": EvidenceTools,
    "get_evidence_chain": EvidenceTools,
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools from all tool modules."""
    tools = []
    tools.extend(DocumentTools.get_tools())
    tools.extend(CaseTools.get_tools())
    if settings.enable_ai_tools:
        tools.extend(AITools.get_tools())
    tools.extend(SearchTools.get_tools())
    tools.extend(TimelineTools.get_tools())
    if settings.enable_pst_tools:
        tools.extend(PSTTools.get_tools())
    tools.extend(EvidenceTools.get_tools())
    logger.info(f"Listing {len(tools)} available tools")
    return tools


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Route tool calls to appropriate handlers."""
    logger.info(f"Tool call: {name} with arguments: {arguments}")

    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        logger.warning(f"Unknown tool requested: {name}")
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    try:
        result = await handler.handle_tool(name, arguments)
        logger.info(f"Tool {name} completed successfully")
        return result
    except Exception as e:
        logger.exception(f"Error executing tool {name}")
        return [TextContent(type="text", text=f"Error executing {name}: {str(e)}")]


@server.list_prompts()
async def list_prompts() -> list[Prompt]:
    """List available prompt templates."""
    return [
        Prompt(
            name="analyze_case",
            description="Analyze a construction dispute case and provide strategic recommendations",
            arguments=[
                PromptArgument(
                    name="case_id",
                    description="The UUID of the case to analyze",
                    required=True,
                ),
            ],
        ),
        Prompt(
            name="search_evidence",
            description="Search for evidence related to a specific topic or issue",
            arguments=[
                PromptArgument(
                    name="query",
                    description="What to search for",
                    required=True,
                ),
                PromptArgument(
                    name="case_id",
                    description="Optional case to limit search to",
                    required=False,
                ),
            ],
        ),
        Prompt(
            name="draft_claim",
            description="Draft a claim narrative for a specific claim type",
            arguments=[
                PromptArgument(
                    name="case_id",
                    description="The case UUID",
                    required=True,
                ),
                PromptArgument(
                    name="claim_type",
                    description="Type of claim (delay, defects, variations, etc.)",
                    required=True,
                ),
            ],
        ),
        Prompt(
            name="analyze_timeline",
            description="Analyze the project timeline for delays and issues",
            arguments=[
                PromptArgument(
                    name="case_id",
                    description="The case UUID",
                    required=True,
                ),
            ],
        ),
    ]


@server.get_prompt()
async def get_prompt(name: str, arguments: dict | None) -> GetPromptResult:
    """Get a specific prompt template with arguments filled in."""
    args = arguments or {}

    if name == "analyze_case":
        case_id = args.get("case_id", "")
        return GetPromptResult(
            description=f"Analyze case {case_id}",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"""Analyze the construction dispute case with ID: {case_id}

Please provide:
1. Case overview and key facts
2. Identification of main legal issues
3. Assessment of evidence strength
4. Strategic recommendations
5. Risk analysis

Use the available tools to gather case details, evidence, timeline, and correspondence.""",
                    ),
                ),
            ],
        )

    elif name == "search_evidence":
        query = args.get("query", "")
        case_id = args.get("case_id", "")
        case_context = f" within case {case_id}" if case_id else ""
        return GetPromptResult(
            description=f"Search for: {query}",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"""Search for evidence related to: {query}{case_context}

Use search_emails, search_documents, and semantic_search tools to find relevant evidence.
For each piece of evidence found, summarize its relevance and key facts.""",
                    ),
                ),
            ],
        )

    elif name == "draft_claim":
        case_id = args.get("case_id", "")
        claim_type = args.get("claim_type", "delay")
        return GetPromptResult(
            description=f"Draft {claim_type} claim for case {case_id}",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"""Draft a {claim_type} claim narrative for case {case_id}.

Use the following approach:
1. Get case details and heads of claim
2. Review linked evidence for this claim type
3. Analyze the timeline of relevant events
4. Use generate_claim_narrative to create the initial draft
5. Review and refine the narrative based on evidence

The claim should follow UK construction dispute best practices.""",
                    ),
                ),
            ],
        )

    elif name == "analyze_timeline":
        case_id = args.get("case_id", "")
        return GetPromptResult(
            description=f"Analyze timeline for case {case_id}",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"""Analyze the project timeline for case {case_id}.

Use these tools:
1. get_chronology - to get all timeline events
2. get_delay_analysis - to identify delays
3. get_critical_path_events - to find critical path impacts
4. get_timeline_gaps - to identify missing information

Provide:
- Summary of key milestones and dates
- Identified delays with responsible parties
- Critical path analysis
- Gaps in the chronology that need investigation""",
                    ),
                ),
            ],
        )

    raise ValueError(f"Unknown prompt: {name}")


@server.list_resources()
async def list_resources() -> list[Resource]:
    """List available resources."""
    return [
        Resource(
            uri="vericase://health",
            name="API Health Status",
            description="Current health status of the VeriCase API",
            mimeType="application/json",
        ),
    ]


@server.list_resource_templates()
async def list_resource_templates() -> list[ResourceTemplate]:
    """List available resource templates."""
    return [
        ResourceTemplate(
            uriTemplate="vericase://cases/{case_id}",
            name="Case Details",
            description="Get details for a specific case",
            mimeType="application/json",
        ),
        ResourceTemplate(
            uriTemplate="vericase://documents/{document_id}",
            name="Document Details",
            description="Get details for a specific document",
            mimeType="application/json",
        ),
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    """Read a resource by URI."""
    import json

    if uri == "vericase://health":
        try:
            health = await api_client.health_check()
            return json.dumps(health, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    if uri.startswith("vericase://cases/"):
        case_id = uri.replace("vericase://cases/", "")
        try:
            case = await api_client.get(f"/api/cases/{case_id}")
            return json.dumps(case, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})

    if uri.startswith("vericase://documents/"):
        document_id = uri.replace("vericase://documents/", "")
        try:
            doc = await api_client.get(f"/api/documents/{document_id}")
            return json.dumps(doc, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})

    raise ValueError(f"Unknown resource: {uri}")


async def run_server():
    """Run the MCP server."""
    logger.info("Starting Azad MCP Server for VeriCase")
    logger.info(f"API URL: {settings.api_base_url}")
    logger.info(f"AI Tools: {'enabled' if settings.enable_ai_tools else 'disabled'}")
    logger.info(f"PST Tools: {'enabled' if settings.enable_pst_tools else 'disabled'}")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main():
    """Main entry point."""
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.exception("Server error")
        sys.exit(1)


if __name__ == "__main__":
    main()
