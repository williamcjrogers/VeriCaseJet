"""Case Management Tools for VeriCase - Construction Disputes and Claims."""

import logging
from typing import Any

from mcp.types import Tool, TextContent

from ..utils.api_client import api_client, VeriCaseAPIError

logger = logging.getLogger(__name__)


class CaseTools:
    """Tools for managing construction dispute cases and claims."""

    @staticmethod
    def get_tools() -> list[Tool]:
        """Return list of case management MCP tools."""
        return [
            Tool(
                name="list_cases",
                description="List all construction dispute cases with optional filtering by status, date range, or claim type. Returns case summaries including project name, parties involved, claim value, and current status.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["active", "pending", "resolved", "archived"],
                            "description": "Filter by case status",
                        },
                        "claim_type": {
                            "type": "string",
                            "enum": ["delay", "defects", "variations", "eot", "loss_and_expense", "final_account"],
                            "description": "Filter by type of claim",
                        },
                        "search": {
                            "type": "string",
                            "description": "Search term to filter cases by name or reference",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 50,
                            "description": "Maximum results to return",
                        },
                    },
                },
            ),
            Tool(
                name="get_case",
                description="Get detailed information about a specific case including project details, parties, contract information, timeline, heads of claim, and linked evidence.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "The UUID of the case to retrieve",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
            Tool(
                name="create_case",
                description="Create a new construction dispute case with project details, parties, and contract information.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Case/Project name",
                        },
                        "reference": {
                            "type": "string",
                            "description": "Internal case reference number",
                        },
                        "description": {
                            "type": "string",
                            "description": "Brief description of the dispute",
                        },
                        "contract_type": {
                            "type": "string",
                            "enum": ["JCT", "NEC", "FIDIC", "Bespoke", "Other"],
                            "description": "Type of construction contract",
                        },
                        "contract_value": {
                            "type": "number",
                            "description": "Original contract value in GBP",
                        },
                        "claim_value": {
                            "type": "number",
                            "description": "Estimated claim value in GBP",
                        },
                        "employer": {
                            "type": "string",
                            "description": "Name of the employer/client",
                        },
                        "contractor": {
                            "type": "string",
                            "description": "Name of the main contractor",
                        },
                        "contract_start_date": {
                            "type": "string",
                            "format": "date",
                            "description": "Contract commencement date (YYYY-MM-DD)",
                        },
                        "contract_completion_date": {
                            "type": "string",
                            "format": "date",
                            "description": "Contractual completion date (YYYY-MM-DD)",
                        },
                        "actual_completion_date": {
                            "type": "string",
                            "format": "date",
                            "description": "Actual/projected completion date (YYYY-MM-DD)",
                        },
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="update_case",
                description="Update case details including status, claim values, dates, or other metadata.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "UUID of the case to update",
                        },
                        "name": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["active", "pending", "resolved", "archived"],
                        },
                        "description": {"type": "string"},
                        "claim_value": {"type": "number"},
                        "actual_completion_date": {
                            "type": "string",
                            "format": "date",
                        },
                        "notes": {"type": "string"},
                    },
                    "required": ["case_id"],
                },
            ),
            Tool(
                name="get_heads_of_claim",
                description="Get the heads of claim for a case - the structured breakdown of claimed amounts by category (delay damages, loss and expense, variations, etc.).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "UUID of the case",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
            Tool(
                name="add_head_of_claim",
                description="Add a new head of claim to a case with category, amount, and supporting description.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "UUID of the case",
                        },
                        "category": {
                            "type": "string",
                            "enum": [
                                "preliminaries",
                                "delay_damages",
                                "prolongation",
                                "disruption",
                                "variations",
                                "loss_and_expense",
                                "interest",
                                "professional_fees",
                                "other",
                            ],
                            "description": "Category of the claim head",
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of the claimed amount",
                        },
                        "amount": {
                            "type": "number",
                            "description": "Claimed amount in GBP",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["draft", "submitted", "agreed", "disputed", "withdrawn"],
                            "default": "draft",
                        },
                    },
                    "required": ["case_id", "category", "amount"],
                },
            ),
            Tool(
                name="get_case_issues",
                description="Get the legal issues identified for a case - key disputes around liability, causation, and quantum that need to be resolved.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "UUID of the case",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
            Tool(
                name="create_issue",
                description="Create a new legal issue for a case to track specific disputes or questions that need resolution.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "UUID of the case",
                        },
                        "title": {
                            "type": "string",
                            "description": "Title of the issue",
                        },
                        "description": {
                            "type": "string",
                            "description": "Detailed description of the issue",
                        },
                        "issue_type": {
                            "type": "string",
                            "enum": ["liability", "causation", "quantum", "procedural", "factual"],
                            "description": "Type of legal issue",
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["critical", "high", "medium", "low"],
                            "default": "medium",
                        },
                    },
                    "required": ["case_id", "title", "issue_type"],
                },
            ),
            Tool(
                name="get_case_team",
                description="Get the team members assigned to a case with their roles and permissions.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "UUID of the case",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
            Tool(
                name="add_case_team_member",
                description="Add a user to a case team with a specific role.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "UUID of the case",
                        },
                        "user_id": {
                            "type": "string",
                            "description": "UUID of the user to add",
                        },
                        "role": {
                            "type": "string",
                            "enum": ["lead", "expert", "solicitor", "barrister", "analyst", "viewer"],
                            "description": "Role of the team member",
                        },
                    },
                    "required": ["case_id", "user_id", "role"],
                },
            ),
            Tool(
                name="get_case_statistics",
                description="Get statistics and analytics for a case including document counts, email counts, timeline coverage, and claim breakdown.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "UUID of the case",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
            Tool(
                name="get_case_deadlines",
                description="Get important deadlines for a case including contractual dates, procedural dates, and key milestones.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "UUID of the case",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
        ]

    @staticmethod
    async def handle_tool(name: str, arguments: dict) -> list[TextContent]:
        """Handle case management tool calls."""
        try:
            if name == "list_cases":
                result = await CaseTools._list_cases(arguments)
            elif name == "get_case":
                result = await CaseTools._get_case(arguments["case_id"])
            elif name == "create_case":
                result = await CaseTools._create_case(arguments)
            elif name == "update_case":
                result = await CaseTools._update_case(arguments)
            elif name == "get_heads_of_claim":
                result = await CaseTools._get_heads_of_claim(arguments["case_id"])
            elif name == "add_head_of_claim":
                result = await CaseTools._add_head_of_claim(arguments)
            elif name == "get_case_issues":
                result = await CaseTools._get_case_issues(arguments["case_id"])
            elif name == "create_issue":
                result = await CaseTools._create_issue(arguments)
            elif name == "get_case_team":
                result = await CaseTools._get_case_team(arguments["case_id"])
            elif name == "add_case_team_member":
                result = await CaseTools._add_case_team_member(arguments)
            elif name == "get_case_statistics":
                result = await CaseTools._get_case_statistics(arguments["case_id"])
            elif name == "get_case_deadlines":
                result = await CaseTools._get_case_deadlines(arguments["case_id"])
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            return [TextContent(type="text", text=str(result))]
        except VeriCaseAPIError as e:
            return [TextContent(type="text", text=f"API Error: {e.message}")]
        except Exception as e:
            logger.exception(f"Error handling case tool {name}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    @staticmethod
    async def _list_cases(args: dict) -> dict:
        params = {k: v for k, v in args.items() if v is not None}
        return await api_client.get("/api/cases", params=params)

    @staticmethod
    async def _get_case(case_id: str) -> dict:
        return await api_client.get(f"/api/cases/{case_id}")

    @staticmethod
    async def _create_case(args: dict) -> dict:
        return await api_client.post("/api/cases", data=args)

    @staticmethod
    async def _update_case(args: dict) -> dict:
        case_id = args.pop("case_id")
        return await api_client.patch(f"/api/cases/{case_id}", data=args)

    @staticmethod
    async def _get_heads_of_claim(case_id: str) -> dict:
        return await api_client.get(f"/api/cases/{case_id}/heads-of-claim")

    @staticmethod
    async def _add_head_of_claim(args: dict) -> dict:
        case_id = args.pop("case_id")
        return await api_client.post(f"/api/cases/{case_id}/heads-of-claim", data=args)

    @staticmethod
    async def _get_case_issues(case_id: str) -> dict:
        return await api_client.get(f"/api/cases/{case_id}/issues")

    @staticmethod
    async def _create_issue(args: dict) -> dict:
        case_id = args.pop("case_id")
        return await api_client.post(f"/api/cases/{case_id}/issues", data=args)

    @staticmethod
    async def _get_case_team(case_id: str) -> dict:
        return await api_client.get(f"/api/cases/{case_id}/team")

    @staticmethod
    async def _add_case_team_member(args: dict) -> dict:
        case_id = args.pop("case_id")
        return await api_client.post(f"/api/cases/{case_id}/team", data=args)

    @staticmethod
    async def _get_case_statistics(case_id: str) -> dict:
        return await api_client.get(f"/api/cases/{case_id}/statistics")

    @staticmethod
    async def _get_case_deadlines(case_id: str) -> dict:
        return await api_client.get(f"/api/cases/{case_id}/deadlines")
