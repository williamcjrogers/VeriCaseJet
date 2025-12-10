"""Timeline and Chronology Tools for VeriCase - Construction Delay Analysis."""

import logging
from typing import Any

from mcp.types import Tool, TextContent

from ..utils.api_client import api_client, VeriCaseAPIError

logger = logging.getLogger(__name__)


class TimelineTools:
    """Tools for managing case timelines, chronologies, and delay analysis."""

    @staticmethod
    def get_tools() -> list[Tool]:
        """Return list of timeline MCP tools."""
        return [
            Tool(
                name="get_chronology",
                description="Get the chronology of events for a case. Returns a timeline of all significant events with dates, descriptions, and linked evidence.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "Case UUID to get chronology for",
                        },
                        "date_from": {
                            "type": "string",
                            "format": "date",
                            "description": "Filter events from this date",
                        },
                        "date_to": {
                            "type": "string",
                            "format": "date",
                            "description": "Filter events to this date",
                        },
                        "event_types": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": [
                                    "contract",
                                    "instruction",
                                    "notice",
                                    "delay_event",
                                    "milestone",
                                    "correspondence",
                                    "meeting",
                                    "site_event",
                                    "payment",
                                    "claim",
                                ],
                            },
                            "description": "Filter by event types",
                        },
                        "include_evidence": {
                            "type": "boolean",
                            "default": True,
                            "description": "Include linked evidence for each event",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
            Tool(
                name="add_chronology_event",
                description="Add a new event to the case chronology. Events can be linked to evidence documents.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "Case UUID",
                        },
                        "date": {
                            "type": "string",
                            "format": "date",
                            "description": "Date of the event (YYYY-MM-DD)",
                        },
                        "title": {
                            "type": "string",
                            "description": "Event title/headline",
                        },
                        "description": {
                            "type": "string",
                            "description": "Detailed description of the event",
                        },
                        "event_type": {
                            "type": "string",
                            "enum": [
                                "contract",
                                "instruction",
                                "notice",
                                "delay_event",
                                "milestone",
                                "correspondence",
                                "meeting",
                                "site_event",
                                "payment",
                                "claim",
                            ],
                            "description": "Type of event",
                        },
                        "as_planned_date": {
                            "type": "string",
                            "format": "date",
                            "description": "Original planned date (for delay analysis)",
                        },
                        "as_built_date": {
                            "type": "string",
                            "format": "date",
                            "description": "Actual date achieved (for delay analysis)",
                        },
                        "responsible_party": {
                            "type": "string",
                            "description": "Party responsible for the event",
                        },
                        "evidence_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "UUIDs of linked evidence documents",
                        },
                        "impact": {
                            "type": "string",
                            "enum": ["critical", "significant", "minor", "none"],
                            "description": "Impact assessment",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tags for categorization",
                        },
                    },
                    "required": ["case_id", "date", "title", "event_type"],
                },
            ),
            Tool(
                name="update_chronology_event",
                description="Update an existing chronology event.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "event_id": {
                            "type": "string",
                            "description": "Event UUID to update",
                        },
                        "date": {"type": "string", "format": "date"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "event_type": {"type": "string"},
                        "as_planned_date": {"type": "string", "format": "date"},
                        "as_built_date": {"type": "string", "format": "date"},
                        "responsible_party": {"type": "string"},
                        "impact": {"type": "string"},
                        "evidence_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["event_id"],
                },
            ),
            Tool(
                name="delete_chronology_event",
                description="Delete an event from the chronology.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "event_id": {
                            "type": "string",
                            "description": "Event UUID to delete",
                        },
                    },
                    "required": ["event_id"],
                },
            ),
            Tool(
                name="generate_chronology_from_emails",
                description="Auto-generate chronology events from email correspondence. Uses AI to identify significant events and dates from email content.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "Case to generate chronology for",
                        },
                        "date_from": {
                            "type": "string",
                            "format": "date",
                            "description": "Start date for email analysis",
                        },
                        "date_to": {
                            "type": "string",
                            "format": "date",
                            "description": "End date for email analysis",
                        },
                        "event_types_to_detect": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Types of events to look for",
                        },
                        "auto_link_evidence": {
                            "type": "boolean",
                            "default": True,
                            "description": "Automatically link source emails as evidence",
                        },
                        "review_mode": {
                            "type": "boolean",
                            "default": True,
                            "description": "Create as draft for review before finalizing",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
            Tool(
                name="get_delay_analysis",
                description="Get delay analysis comparing as-planned vs as-built dates. Calculates delay periods and identifies responsible parties.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "Case UUID for delay analysis",
                        },
                        "analysis_method": {
                            "type": "string",
                            "enum": [
                                "as_planned_vs_as_built",
                                "impacted_as_planned",
                                "collapsed_as_built",
                                "windows_analysis",
                            ],
                            "default": "as_planned_vs_as_built",
                            "description": "Delay analysis methodology",
                        },
                        "include_concurrent_delays": {
                            "type": "boolean",
                            "default": True,
                            "description": "Identify concurrent delays",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
            Tool(
                name="get_critical_path_events",
                description="Get events on the critical path that affected project completion. Essential for delay claims.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "Case UUID",
                        },
                        "baseline_programme": {
                            "type": "string",
                            "description": "Document ID of baseline programme (optional)",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
            Tool(
                name="export_chronology",
                description="Export the chronology in various formats for reporting or legal submissions.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "Case UUID",
                        },
                        "format": {
                            "type": "string",
                            "enum": ["pdf", "excel", "word", "json", "csv"],
                            "default": "pdf",
                            "description": "Export format",
                        },
                        "include_evidence_refs": {
                            "type": "boolean",
                            "default": True,
                            "description": "Include evidence references",
                        },
                        "date_from": {
                            "type": "string",
                            "format": "date",
                        },
                        "date_to": {
                            "type": "string",
                            "format": "date",
                        },
                        "event_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by event types",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
            Tool(
                name="link_evidence_to_event",
                description="Link evidence documents to a chronology event.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "event_id": {
                            "type": "string",
                            "description": "Chronology event UUID",
                        },
                        "evidence_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Document UUIDs to link",
                        },
                    },
                    "required": ["event_id", "evidence_ids"],
                },
            ),
            Tool(
                name="get_timeline_gaps",
                description="Identify gaps in the chronology where events may be missing. Useful for ensuring complete timeline coverage.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "Case UUID",
                        },
                        "min_gap_days": {
                            "type": "integer",
                            "default": 30,
                            "description": "Minimum gap in days to flag",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
        ]

    @staticmethod
    async def handle_tool(name: str, arguments: dict) -> list[TextContent]:
        """Handle timeline tool calls."""
        try:
            if name == "get_chronology":
                result = await TimelineTools._get_chronology(arguments)
            elif name == "add_chronology_event":
                result = await TimelineTools._add_chronology_event(arguments)
            elif name == "update_chronology_event":
                result = await TimelineTools._update_chronology_event(arguments)
            elif name == "delete_chronology_event":
                result = await TimelineTools._delete_chronology_event(arguments["event_id"])
            elif name == "generate_chronology_from_emails":
                result = await TimelineTools._generate_chronology_from_emails(arguments)
            elif name == "get_delay_analysis":
                result = await TimelineTools._get_delay_analysis(arguments)
            elif name == "get_critical_path_events":
                result = await TimelineTools._get_critical_path_events(arguments)
            elif name == "export_chronology":
                result = await TimelineTools._export_chronology(arguments)
            elif name == "link_evidence_to_event":
                result = await TimelineTools._link_evidence_to_event(arguments)
            elif name == "get_timeline_gaps":
                result = await TimelineTools._get_timeline_gaps(arguments)
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            return [TextContent(type="text", text=str(result))]
        except VeriCaseAPIError as e:
            return [TextContent(type="text", text=f"API Error: {e.message}")]
        except Exception as e:
            logger.exception(f"Error handling timeline tool {name}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    @staticmethod
    async def _get_chronology(args: dict) -> dict:
        case_id = args.pop("case_id")
        return await api_client.get(f"/api/cases/{case_id}/chronology", params=args)

    @staticmethod
    async def _add_chronology_event(args: dict) -> dict:
        case_id = args.pop("case_id")
        return await api_client.post(f"/api/cases/{case_id}/chronology", data=args)

    @staticmethod
    async def _update_chronology_event(args: dict) -> dict:
        event_id = args.pop("event_id")
        return await api_client.patch(f"/api/chronology/{event_id}", data=args)

    @staticmethod
    async def _delete_chronology_event(event_id: str) -> dict:
        return await api_client.delete(f"/api/chronology/{event_id}")

    @staticmethod
    async def _generate_chronology_from_emails(args: dict) -> dict:
        case_id = args.pop("case_id")
        return await api_client.post(f"/api/cases/{case_id}/chronology/generate", data=args)

    @staticmethod
    async def _get_delay_analysis(args: dict) -> dict:
        case_id = args.pop("case_id")
        return await api_client.get(f"/api/cases/{case_id}/delay-analysis", params=args)

    @staticmethod
    async def _get_critical_path_events(args: dict) -> dict:
        case_id = args.pop("case_id")
        return await api_client.get(f"/api/cases/{case_id}/critical-path", params=args)

    @staticmethod
    async def _export_chronology(args: dict) -> dict:
        case_id = args.pop("case_id")
        return await api_client.post(f"/api/cases/{case_id}/chronology/export", data=args)

    @staticmethod
    async def _link_evidence_to_event(args: dict) -> dict:
        event_id = args.pop("event_id")
        return await api_client.post(f"/api/chronology/{event_id}/evidence", data=args)

    @staticmethod
    async def _get_timeline_gaps(args: dict) -> dict:
        case_id = args.pop("case_id")
        return await api_client.get(f"/api/cases/{case_id}/chronology/gaps", params=args)
