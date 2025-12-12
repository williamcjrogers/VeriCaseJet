"""
Intelligent Configuration API
AI-powered chatbot that guides users through system configuration
"""

import asyncio
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Annotated, Any, Callable, TypeGuard, cast
from pydantic import BaseModel, Field
import logging
import re

from .security import current_user
from .db import get_db
from .models import User
from .config import settings
from .ai_models import (
    AIModelService,
    TaskComplexity,
    log_model_selection,
)
from .ai_runtime import complete_chat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["intelligent-config"])


def _determine_default_complexity() -> TaskComplexity:
    """Return default task complexity from settings."""
    try:
        default_value = getattr(settings, "AI_TASK_COMPLEXITY_DEFAULT", "basic").lower()
        return TaskComplexity(default_value)
    except ValueError:
        return TaskComplexity.BASIC


DEFAULT_COMPLEXITY: TaskComplexity = _determine_default_complexity()


def _is_list_of_dicts(value: object) -> TypeGuard[list[dict[str, Any]]]:
    """Runtime check ensuring value is a list of dicts."""
    if not isinstance(value, list):
        return False
    value_list = cast(list[object], value)
    return all(isinstance(item, dict) for item in value_list)


TEAM_PATTERNS = [
    r"(?:team member|member|person|user|stakeholder)[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
    r"([A-Z][a-z]+\s+[A-Z][a-z]+)\s+(?:is|as|role|works as)",
    r"email[:\s]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
]

NAME_PATTERNS = [
    r'(?:project|case)[:\s]+["\']?([^"\'\n]+)["\']?',
    r'name[:\s]+["\']?([^"\'\n]+)["\']?',
]

KEYWORD_PATTERNS = [
    r"keyword[s]?[:\s]+([^\.\n]+)",
    r"(?:terms?|phrases?)[:\s]+([^\.\n]+)",
]

COMPLETION_SIGNALS = ["complete", "finished", "done", "ready", "all set", "configured"]

DETAIL_TRIGGERS = ["analyze", "analyse", "extract", "complex", "detailed", "breakdown"]


def validate_project_code_format(project_code: str) -> tuple[bool, str]:
    """
    Validate project code format.
    Returns (is_valid, error_message)
    Project codes should be alphanumeric with hyphens/underscores, max 100 chars
    """
    if not project_code:
        return False, "Project code cannot be empty"

    if len(project_code) > 100:
        return False, "Project code must be 100 characters or less"

    # Allow alphanumeric, hyphens, underscores, spaces (but recommend no spaces)
    if not re.match(r"^[A-Za-z0-9\-_\s]+$", project_code):
        return (
            False,
            "Project code can only contain letters, numbers, hyphens, and underscores",
        )

    return True, ""


def validate_case_number_format(case_number: str) -> tuple[bool, str]:
    """
    Validate case number format.
    Returns (is_valid, error_message)
    Case numbers should be alphanumeric with hyphens/underscores, max 100 chars
    """
    if not case_number:
        return False, "Case number cannot be empty"

    if len(case_number) > 100:
        return False, "Case number must be 100 characters or less"

    # Allow alphanumeric, hyphens, underscores, spaces (but recommend no spaces)
    if not re.match(r"^[A-Za-z0-9\-_\s]+$", case_number):
        return (
            False,
            "Case number can only contain letters, numbers, hyphens, and underscores",
        )

    return True, ""


def format_project_code(project_code: str) -> str:
    """
    Format project code to backend expectations:
    - Uppercase
    - Replace spaces with hyphens
    - Remove special characters except hyphens and underscores
    """
    # Convert to uppercase
    formatted = project_code.upper()
    # Replace spaces with hyphens
    formatted = formatted.replace(" ", "-")
    # Remove any remaining invalid characters (keep only alphanumeric, hyphens, underscores)
    formatted = re.sub(r"[^A-Z0-9\-_]", "", formatted)
    return formatted


def format_case_number(case_number: str) -> str:
    """
    Format case number to backend expectations:
    - Uppercase
    - Replace spaces with hyphens
    - Remove special characters except hyphens and underscores
    """
    # Convert to uppercase
    formatted = case_number.upper()
    # Replace spaces with hyphens
    formatted = formatted.replace(" ", "-")
    # Remove any remaining invalid characters (keep only alphanumeric, hyphens, underscores)
    formatted = re.sub(r"[^A-Z0-9\-_]", "", formatted)
    return formatted


async def check_project_code_unique(project_code: str, db: Session) -> tuple[bool, str]:
    """
    Check if project code is unique in database.
    Returns (is_unique, error_message)
    """
    from .models import Project

    existing = db.query(Project).filter(Project.project_code == project_code).first()
    if existing:
        return (
            False,
            f"Project code '{project_code}' already exists. Please choose a different code.",
        )
    return True, ""


async def check_case_number_unique(case_number: str, db: Session) -> tuple[bool, str]:
    """
    Check if case number is unique in database.
    Returns (is_unique, error_message)
    """
    from .models import Case

    existing = db.query(Case).filter(Case.case_number == case_number).first()
    if existing:
        return (
            False,
            f"Case number '{case_number}' already exists. Please choose a different number.",
        )
    return True, ""


def has_minimum_config(config_data: dict[str, Any]) -> bool:
    """Check if we have minimum required configuration"""
    team_members = cast(list[Any] | None, config_data.get("team_members"))
    has_team = bool(team_members and len(team_members) > 0)
    has_project_name = bool(
        config_data.get("project_name") or config_data.get("case_name")
    )
    # Require project_code or case_number - these are essential identifiers
    # Must be non-empty strings
    project_code = config_data.get("project_code")
    case_number = config_data.get("case_number")
    has_project_code = isinstance(project_code, str) and bool(project_code.strip())
    has_case_number = isinstance(case_number, str) and bool(case_number.strip())

    return has_team and has_project_name and (has_project_code or has_case_number)


def _parse_natural_language_response(
    response_text: str,
    current_step: str,
    config_data: dict[str, Any],
) -> dict[str, Any]:
    """Parse natural language AI response and extract configuration data"""
    extracted: dict[str, Any] = {}
    next_step = current_step

    def _extract_matches(patterns: list[str]) -> list[str]:
        matches: list[str] = []
        for pattern in patterns:
            for match in re.finditer(pattern, response_text, re.IGNORECASE):
                for group in match.groups():
                    if group:
                        matches.append(group.strip())
        return matches

    team_matches = _extract_matches(TEAM_PATTERNS)
    if team_matches and not config_data.get("team_members"):
        extracted["team_members"] = [{"name": name} for name in team_matches]

    name_match = None
    for pattern in NAME_PATTERNS:
        match = re.search(pattern, response_text, re.IGNORECASE)
        if match:
            name_match = match.group(1).strip()
            break
    if name_match:
        if "project" in response_text.lower():
            extracted.setdefault("project_name", name_match)
        else:
            extracted.setdefault("case_name", name_match)

    keyword_matches = _extract_matches(KEYWORD_PATTERNS)
    if keyword_matches and not config_data.get("keywords"):
        normalized_keywords = [
            keyword.strip(" ,.;")
            for fragment in keyword_matches
            for keyword in fragment.split(",")
            if keyword.strip(" ,.;")
        ]
        if normalized_keywords:
            extracted["keywords"] = normalized_keywords

    if any(signal in response_text.lower() for signal in COMPLETION_SIGNALS):
        if has_minimum_config(config_data):
            next_step = "complete"

    # Determine next step based on context
    if "team" in response_text.lower() or "member" in response_text.lower():
        if not config_data.get("team_members"):
            next_step = "team_building"
    elif "project" in response_text.lower() or "case" in response_text.lower():
        if not config_data.get("project_name") and not config_data.get("case_name"):
            next_step = "project_setup"
    elif "keyword" in response_text.lower() or "term" in response_text.lower():
        next_step = "keywords"

    return {
        "response": response_text,
        "extracted_data": extracted,
        "next_step": next_step,
        "quick_actions": get_default_quick_actions(next_step),
        "progress": calculate_progress(next_step, config_data),
        "is_complete": next_step == "complete",
    }


async def _get_ai_config_response(
    prompt: str, task_complexity: TaskComplexity = DEFAULT_COMPLEXITY
) -> str:
    """Get AI response for configuration using task-aware model selection."""

    if isinstance(task_complexity, str):
        try:
            task_complexity = TaskComplexity(task_complexity.lower())
        except ValueError:
            task_complexity = TaskComplexity.BASIC

    normalized_prompt = prompt.lower()
    if task_complexity == TaskComplexity.BASIC and any(
        term in normalized_prompt for term in DETAIL_TRIGGERS
    ):
        task_complexity = TaskComplexity.MODERATE

    model_config = AIModelService.select_model("configuration", task_complexity)
    candidates = AIModelService.build_priority_queue(
        "configuration", task_complexity, model_config
    )

    errors: list[str] = []

    for candidate in candidates:
        resolved = AIModelService.resolve_model(candidate)
        if not resolved:
            continue

        provider = resolved["provider"]
        model_name = resolved["model"]
        display_name = AIModelService.display_name(candidate)

        try:
            if provider == "anthropic" and settings.CLAUDE_API_KEY:
                response_text = await complete_chat(
                    provider="anthropic",
                    model_id=model_name,
                    prompt=prompt,
                    api_key=settings.CLAUDE_API_KEY,
                    max_tokens=2000,
                    temperature=0.3,
                )
                log_model_selection(
                    "configuration", display_name, f"Anthropic:{model_name}"
                )
                return response_text

            if provider == "openai" and settings.OPENAI_API_KEY:
                response_text = await complete_chat(
                    provider="openai",
                    model_id=model_name,
                    prompt=prompt,
                    api_key=settings.OPENAI_API_KEY,
                    max_tokens=2000,
                    temperature=0.3,
                )
                log_model_selection(
                    "configuration", display_name, f"OpenAI:{model_name}"
                )
                return response_text

            if provider in ("gemini", "google") and settings.GEMINI_API_KEY:
                response_text = await complete_chat(
                    provider="gemini",
                    model_id=model_name,
                    prompt=prompt,
                    api_key=settings.GEMINI_API_KEY,
                    max_tokens=2000,
                    temperature=0.3,
                )
                if response_text:
                    log_model_selection(
                        "configuration", display_name, f"Gemini:{model_name}"
                    )
                    return response_text

        except Exception as exc:
            logger.warning("Model %s failed for configuration: %s", display_name, exc)
            errors.append(f"{display_name}: {exc}")

    detail = "No AI services available. Please configure at least one AI API key."
    if errors:
        # Limit error messages to prevent overly long HTTP responses and excessive detail
        safe_errors: list[str] = []
        for err in errors[:3]:  # Only include first 3 errors
            # Remove provider prefix and truncate to safe length
            msg = err.split(":", 1)[-1].strip() if ":" in err else str(err)
            if len(msg) > 50:
                msg = msg[:50] + "..."
            safe_errors.append(msg)
        detail = f"All AI services failed -> {', '.join(safe_errors)}"
    raise HTTPException(status_code=503, detail=detail)


class ConfigMessage(BaseModel):
    message: str
    conversation_history: list[dict[str, str]] = Field(default_factory=list)
    current_step: str = "introduction"
    configuration_data: dict[str, Any] = Field(default_factory=dict)


class ConfigResponse(BaseModel):
    response: str
    next_step: str | None = None
    configuration_data: dict[str, Any] | None = None
    quick_actions: list[str] | None = None
    progress: int | None = None
    configuration_complete: bool = False
    final_configuration: dict[str, Any] | None = None


def build_configuration_prompt(
    message: str,
    conversation_history: list[dict[str, str]],
    current_step: str,
    config_data: dict[str, Any],
) -> str:
    """Build a comprehensive prompt for AI to understand configuration needs"""

    prompt = """You are an intelligent configuration assistant for VeriCase, a legal case management and evidence analysis system.

Your role is to guide users through setting up their system by:
1. Understanding their team composition
2. Identifying project/case details
3. Extracting relevant keywords and terms
4. Setting up roles and permissions
5. Configuring deadlines and important dates

Current conversation context:
"""

    # Add conversation history
    if conversation_history:
        prompt += "\nConversation so far:\n"
        for msg in conversation_history[-10:]:  # Last 10 messages for context
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt += f"{role.upper()}: {content}\n"

    prompt += f"\nCurrent step: {current_step}\n"

    if config_data:
        prompt += f"\nConfiguration data collected so far:\n{config_data}\n"

    prompt += f"\nUser's latest message: {message}\n\n"

    # Step-specific instructions
    if current_step == "introduction":
        prompt += """You should:
- Greet the user warmly
- Explain that you'll help them configure the basics first
- Emphasize that the system will work immediately after basics are configured, even before evidence upload
- Mention that the Refinement Wizard will assist after evidence upload with data-driven questions
- Note that users can come back to configure more anytime
- Start by asking about their team composition
- Be conversational and friendly
- Focus on essentials: team members and project/case name
"""
    elif current_step == "team_building":
        prompt += """You should:
- Ask about team members (names, roles, email addresses)
- Understand the organizational structure
- Identify key stakeholders
- Extract roles like: Main Contractor, Council, Project Manager, Client, etc.
- Focus on getting at least 2-3 key team members (minimum viable configuration)
- Once you have basic team info, move to project/case setup
- Don't over-complicate - basics first, details can come later
"""
    elif current_step == "project_setup":
        prompt += """You should:
- Ask about the project/case name (essential - minimum requirement)
- CRITICAL: Ask for the project code (for projects) or case number (for cases) - this is REQUIRED
- Explain that project codes/case numbers are unique identifiers (like "PROJ-2024-001" or "CASE-ABC-123")
- Guide users on proper formatting: uppercase letters, numbers, hyphens/underscores, max 100 characters
- If user provides an ID, validate the format and suggest improvements if needed
- Understand if it's a project (discovery) or case (formal dispute)
- Optionally extract relevant keywords and terms (nice to have, not required for basics)
- Optionally identify contract types, standards (FIDIC, JCT, etc.) - can be done later
- Optionally ask about important dates and deadlines - can be done later
- Once you have project/case name AND project_code/case_number AND basic team, you have minimum configuration
- Offer to continue with more details OR proceed to dashboard
"""
    elif current_step == "keywords":
        prompt += """You should:
- Extract legal/contractual terms
- Identify relevant events (delays, variations, etc.)
- Understand the nature of disputes/issues
- Compile a comprehensive keyword list
"""
    elif current_step == "review":
        prompt += """You should:
- Summarize all configuration data collected
- Explain that basics are complete and system is ready to use
- Mention that configuration can work before evidence upload
- Explain that Refinement Wizard will assist after evidence upload with specific, data-driven questions
- Note that users can come back to configure more anytime
- Explain benefits of configuring more now (better initial analysis, accurate keyword matching, improved threading)
- Give examples: "If we configure contract types now, emails will be categorized correctly immediately"
- Explain that Refinement AI will prompt with direct queries once data is uploaded
- Emphasize the two wizards work together
- Offer choice: continue configuration OR go to dashboard/upload evidence
- Prepare to create the configuration if user wants to proceed
"""

    prompt += """
IMPORTANT: Focus on basics first. Minimum configuration REQUIRES:
- At least 1-2 team members (with names and ideally roles)
- Project or case name
- Project code (for projects) OR case number (for cases) - THIS IS REQUIRED

Project codes and case numbers:
- Must be unique identifiers (like "PROJ-2024-001", "CASE-ABC-123", "PROJECT-ALPHA")
- Format: uppercase letters, numbers, hyphens, underscores
- Max 100 characters
- No spaces (use hyphens instead)
- Examples: "PROJ-2024-001", "CASE-DELAY-001", "ALPHA-TOWER"

When extracting project_code or case_number from user input:
- Normalize to uppercase
- Replace spaces with hyphens
- Remove special characters except hyphens and underscores
- Validate format and suggest improvements if needed
- Check for uniqueness (inform user if it already exists)

Once you have minimum configuration (team + name + code/number), set is_complete to true and offer the user a choice to:
1. Continue with more configuration (keywords, dates, contract types, etc.)
2. Go to dashboard and upload evidence

Respond in a natural, conversational way. Extract any configuration data you can identify from the user's message.
Format your response as JSON with:
- response: Your conversational reply
- extracted_data: Any configuration data you extracted (team members, keywords, project_name, case_name, project_code, case_number, etc.)
- next_step: The next step in the process (introduction, team_building, project_setup, id_validation, keywords, review, complete)
- quick_actions: Suggested quick reply buttons (max 3)
- progress: Progress percentage (0-100)
- is_complete: Whether minimum configuration is complete (true when you have team + project/case name + project_code/case_number)

When is_complete is true, your response should:
- Summarize what's been configured (including the project code or case number)
- Confirm the formatted ID that will be used
- Explain system is ready to use before evidence upload
- Mention Refinement Wizard will assist after upload
- Note users can come back anytime
- Explain benefits of more configuration upfront
- Give examples of what upfront config helps with
- Explain Refinement AI will prompt with specific queries once data is uploaded
- Offer choice: continue config OR go to dashboard

Be helpful, ask clarifying questions when needed, and make the process feel natural and conversational.
"""

    return prompt


@router.post("/intelligent-config", response_model=ConfigResponse)
async def intelligent_configuration(
    request: Annotated[ConfigMessage, Body(...)],
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    """
    AI-powered intelligent configuration endpoint.
    Uses AI to understand user needs and guide them through system setup.
    """
    try:
        # Build comprehensive prompt
        prompt = build_configuration_prompt(
            request.message,
            request.conversation_history,
            request.current_step,
            request.configuration_data,
        )

        # Get AI response using available AI models
        ai_response_text = await _get_ai_config_response(prompt)

        # Parse AI response - it may return JSON or natural language
        import json
        import re

        response_text = ai_response_text

        # Try to extract JSON from response
        parsed: dict[str, Any] | None = None
        json_match = re.search(
            r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", response_text, re.DOTALL
        )

        if json_match:
            try:
                parsed_candidate: object = json.loads(json_match.group(0))
                if isinstance(parsed_candidate, dict):
                    parsed = parsed_candidate
            except json.JSONDecodeError:
                pass

        # If no valid JSON found, parse natural language response
        if parsed is None:
            parsed = _parse_natural_language_response(
                response_text,
                request.current_step,
                request.configuration_data,
            )

        # Merge extracted data with existing configuration
        updated_config: dict[str, Any] = {**request.configuration_data}
        extracted_data = parsed.get("extracted_data")
        if isinstance(extracted_data, dict):
            updated_config.update(cast(dict[str, Any], extracted_data))

        # Format project_code/case_number if provided (uniqueness will be checked during creation)
        project_code_value = updated_config.get("project_code")
        if isinstance(project_code_value, str):
            formatted_code = format_project_code(project_code_value)
            updated_config["project_code"] = formatted_code

        case_number_value = updated_config.get("case_number")
        if isinstance(case_number_value, str):
            formatted_number = format_case_number(case_number_value)
            updated_config["case_number"] = formatted_number

        next_step_value = parsed.get("next_step")
        if isinstance(next_step_value, str):
            next_step = next_step_value
        else:
            next_step = request.current_step

        # Check if configuration is complete
        parsed_is_complete = parsed.get("is_complete")
        is_complete_flag = (
            parsed_is_complete if isinstance(parsed_is_complete, bool) else False
        )
        is_complete = is_complete_flag or (
            next_step == "complete" and has_minimum_config(updated_config)
        )

        # If complete, create the actual configuration
        final_config: dict[str, Any] | None = None
        if is_complete:
            final_config = await create_configuration(updated_config, db, user)

        response_value = parsed.get("response")
        if not isinstance(response_value, str):
            response_value = "I understand. Let me help you with that."

        quick_actions_field = parsed.get("quick_actions")
        if isinstance(quick_actions_field, list):
            quick_actions_value: list[str] = []
            for action_obj in cast(list[object], quick_actions_field):
                if isinstance(action_obj, str):
                    quick_actions_value.append(action_obj)
            if not quick_actions_value:
                quick_actions_value = get_default_quick_actions(next_step)
        else:
            quick_actions_value = get_default_quick_actions(next_step)

        progress_value = parsed.get("progress")
        if not isinstance(progress_value, int):
            progress_value = calculate_progress(next_step, updated_config)

        return ConfigResponse(
            response=response_value,
            next_step=next_step,
            configuration_data=updated_config,
            quick_actions=quick_actions_value,
            progress=progress_value,
            configuration_complete=is_complete,
            final_configuration=final_config,
        )

    except Exception as e:
        logger.error(f"Error in intelligent configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Configuration error: {str(e)}")


def calculate_progress(step: str, config_data: dict[str, Any]) -> int:
    """Calculate progress percentage based on current step and data collected"""
    step_weights = {
        "introduction": 0,
        "team_building": 25,
        "project_setup": 50,
        "keywords": 75,
        "review": 90,
        "complete": 100,
    }

    base_progress = step_weights.get(step, 0)

    # Add bonus for data collected
    team_members_value = config_data.get("team_members")
    if isinstance(team_members_value, list) and team_members_value:
        base_progress += 5
    if isinstance(config_data.get("project_name"), str) or isinstance(
        config_data.get("case_name"), str
    ):
        base_progress += 5
    if isinstance(config_data.get("project_code"), str) or isinstance(
        config_data.get("case_number"), str
    ):
        base_progress += 10  # IDs are critical
    keywords_value = config_data.get("keywords")
    if isinstance(keywords_value, list) and keywords_value:
        base_progress += 5

    return min(base_progress, 100)


def get_default_quick_actions(step: str) -> list[str]:
    """Get default quick action buttons based on current step"""
    actions_map = {
        "introduction": [
            "I'll add team members",
            "Show me how",
            "I have a team list ready",
        ],
        "team_building": ["Add another member", "That's everyone", "Skip for now"],
        "project_setup": ["It's a project", "It's a case", "I'm not sure"],
        "id_validation": ["That looks good", "Let me change it", "Suggest a format"],
        "keywords": ["Add more keywords", "That's enough", "Auto-detect keywords"],
        "review": ["Continue configuration", "Go to dashboard", "Review setup"],
        "complete": ["Continue configuration", "Go to dashboard", "Review setup"],
    }

    return actions_map.get(step, ["Continue", "Skip", "Help"])


async def create_configuration(
    config_data: dict[str, Any],
    db: Session,
    user: User,
) -> dict[str, Any]:
    """Create the actual configuration in the database"""
    from .models import Project, Case, UserCompany, Company

    result: dict[str, Any] = {
        "team_members": [],
        "project_id": None,
        "case_id": None,
        "project_code": None,
        "case_number": None,
    }

    try:
        # Get user's company (required for Case)
        user_company = (
            db.query(UserCompany)
            .filter(UserCompany.user_id == user.id, UserCompany.is_primary == True)
            .first()
        )

        if not user_company:
            # Create a default company if none exists
            company = Company(company_name="My Company")
            db.add(company)
            db.flush()
            user_company = UserCompany(
                user_id=user.id, company_id=company.id, role="admin", is_primary=True
            )
            db.add(user_company)
            db.flush()

        company_id = user_company.company_id

        # Create team members (if provided)
        team_members_raw = config_data.get("team_members")
        team_members_value: list[dict[str, Any]] | None = None
        if _is_list_of_dicts(team_members_raw):
            if team_members_raw:
                team_members_value = team_members_raw
        if team_members_value:
            # Note: In a real implementation, you'd create User records or link existing ones
            result["team_members"] = team_members_value

        # Create project or case
        profile_type_raw = config_data.get("profile_type")
        profile_type = (
            profile_type_raw
            if isinstance(profile_type_raw, str) and profile_type_raw
            else "project"
        )
        project_name_raw = config_data.get("project_name")
        project_name_value = (
            project_name_raw if isinstance(project_name_raw, str) else None
        )
        case_name_raw = config_data.get("case_name")
        case_name_value = case_name_raw if isinstance(case_name_raw, str) else None
        resolved_name = (
            project_name_value
            if isinstance(project_name_value, str) and project_name_value
            else case_name_value
        )
        name = (
            resolved_name
            if isinstance(resolved_name, str) and resolved_name
            else "Untitled"
        )

        if profile_type == "project":
            # Require project_code
            project_code_raw = config_data.get("project_code")
            project_code = (
                project_code_raw
                if isinstance(project_code_raw, str) and project_code_raw
                else None
            )
            if not project_code:
                raise ValueError("Project code is required but not provided")

            # Final uniqueness check
            existing = (
                db.query(Project).filter(Project.project_code == project_code).first()
            )
            if existing:
                raise ValueError(f"Project code '{project_code}' already exists")

            roles_value = config_data.get("roles")
            keywords_value = config_data.get("keywords")
            contract_type_value = config_data.get("contract_type")
            contract_type_str = (
                contract_type_value if isinstance(contract_type_value, str) else None
            )
            desc_raw: object = config_data.get("description", "")
            description_str = str(desc_raw) if desc_raw else ""
            project = Project(
                project_name=name,
                project_code=project_code,
                description=description_str,
                contract_type=contract_type_str,
                owner_user_id=user.id,
                meta={
                    "team_members": team_members_value or [],
                    "roles": roles_value if isinstance(roles_value, list) else [],
                    "keywords": (
                        keywords_value if isinstance(keywords_value, list) else []
                    ),
                    "configured_by_ai": True,
                },
            )
            db.add(project)
            db.commit()
            db.refresh(project)
            result["project_id"] = str(project.id)
            result["project_code"] = project.project_code
        else:
            # Require case_number
            case_number_raw = config_data.get("case_number")
            case_number = (
                case_number_raw
                if isinstance(case_number_raw, str) and case_number_raw
                else None
            )
            if not case_number:
                raise ValueError("Case number is required but not provided")

            # Final uniqueness check
            existing = db.query(Case).filter(Case.case_number == case_number).first()
            if existing:
                raise ValueError(f"Case number '{case_number}' already exists")

            contract_type_value = config_data.get("contract_type")
            dispute_type_value = config_data.get("dispute_type")
            case_desc_raw: object = config_data.get("description", "")
            case_description_str = str(case_desc_raw) if case_desc_raw else ""
            case = Case(
                name=name,
                case_number=case_number,
                description=case_description_str,
                project_name=(
                    project_name_value if isinstance(project_name_value, str) else None
                ),
                contract_type=(
                    contract_type_value
                    if isinstance(contract_type_value, str)
                    else None
                ),
                dispute_type=(
                    dispute_type_value if isinstance(dispute_type_value, str) else None
                ),
                owner_id=user.id,
                company_id=company_id,
                status="active",
            )
            db.add(case)
            db.commit()
            db.refresh(case)
            result["case_id"] = str(case.id)
            result["case_number"] = case.case_number

        logger.info(
            f"Created {profile_type} '{name}' ({result.get('project_code') or result.get('case_number')}) via intelligent configuration for user {user.email}"
        )

    except Exception as e:
        logger.error(f"Error creating configuration: {e}", exc_info=True)
        db.rollback()
        raise

    return result
