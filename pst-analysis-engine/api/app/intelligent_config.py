"""
Intelligent Configuration API
AI-powered chatbot that guides users through system configuration
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel
import logging
from .security import current_user
from .db import get_db
from .config import settings
from .ai_models import (
    AIModelService,
    TaskComplexity,
    log_model_selection,
    query_perplexity_local,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["intelligent-config"])

try:
    DEFAULT_COMPLEXITY = TaskComplexity(
        getattr(settings, "AI_TASK_COMPLEXITY_DEFAULT", "basic").lower()
    )
except ValueError:
    DEFAULT_COMPLEXITY = TaskComplexity.BASIC


def validate_project_code_format(project_code: str) -> Tuple[bool, str]:
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
    import re
    if not re.match(r'^[A-Za-z0-9\-_\s]+$', project_code):
        return False, "Project code can only contain letters, numbers, hyphens, and underscores"
    
    return True, ""


def validate_case_number_format(case_number: str) -> Tuple[bool, str]:
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
    import re
    if not re.match(r'^[A-Za-z0-9\-_\s]+$', case_number):
        return False, "Case number can only contain letters, numbers, hyphens, and underscores"
    
    return True, ""


def format_project_code(project_code: str) -> str:
    """
    Format project code to backend expectations:
    - Uppercase
    - Replace spaces with hyphens
    - Remove special characters except hyphens and underscores
    """
    import re
    # Convert to uppercase
    formatted = project_code.upper()
    # Replace spaces with hyphens
    formatted = formatted.replace(' ', '-')
    # Remove any remaining invalid characters (keep only alphanumeric, hyphens, underscores)
    formatted = re.sub(r'[^A-Z0-9\-_]', '', formatted)
    return formatted


def format_case_number(case_number: str) -> str:
    """
    Format case number to backend expectations:
    - Uppercase
    - Replace spaces with hyphens
    - Remove special characters except hyphens and underscores
    """
    import re
    # Convert to uppercase
    formatted = case_number.upper()
    # Replace spaces with hyphens
    formatted = formatted.replace(' ', '-')
    # Remove any remaining invalid characters (keep only alphanumeric, hyphens, underscores)
    formatted = re.sub(r'[^A-Z0-9\-_]', '', formatted)
    return formatted


async def check_project_code_unique(project_code: str, db: Session) -> Tuple[bool, str]:
    """
    Check if project code is unique in database.
    Returns (is_unique, error_message)
    """
    from .models import Project
    
    existing = db.query(Project).filter(Project.project_code == project_code).first()
    if existing:
        return False, f"Project code '{project_code}' already exists. Please choose a different code."
    return True, ""


async def check_case_number_unique(case_number: str, db: Session) -> Tuple[bool, str]:
    """
    Check if case number is unique in database.
    Returns (is_unique, error_message)
    """
    from .models import Case
    
    existing = db.query(Case).filter(Case.case_number == case_number).first()
    if existing:
        return False, f"Case number '{case_number}' already exists. Please choose a different number."
    return True, ""


def has_minimum_config(config_data: Dict) -> bool:
    """Check if we have minimum required configuration"""
    has_team = bool(config_data.get('team_members') and len(config_data.get('team_members', [])) > 0)
    has_project_name = bool(config_data.get('project_name') or config_data.get('case_name'))
    # Require project_code or case_number - these are essential identifiers
    has_project_code = bool(config_data.get('project_code'))
    has_case_number = bool(config_data.get('case_number'))
    
    return has_team and has_project_name and (has_project_code or has_case_number)


def _parse_natural_language_response(
    response_text: str, 
    current_step: str, 
    config_data: Dict, 
    user_message: str
) -> Dict:
    """Parse natural language AI response and extract configuration data"""
    import re
    
    extracted = {}
    next_step = current_step
    
    # Extract team members (names, emails, roles)
    team_patterns = [
        r'(?:team member|member|person|user|stakeholder)[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
        r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s+(?:is|as|role|works as)',
        r'email[:\s]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
    ]
    
    # Extract project/case name
    name_patterns = [
        r'(?:project|case)[:\s]+["\']?([^"\'\n]+)["\']?',
        r'name[:\s]+["\']?([^"\'\n]+)["\']?'
    ]
    
    # Extract keywords
    keyword_patterns = [
        r'keyword[s]?[:\s]+([^\.\n]+)',
        r'(?:terms?|phrases?)[:\s]+([^\.\n]+)'
    ]
    
    # Check for completion signals
    completion_signals = ['complete', 'finished', 'done', 'ready', 'all set', 'configured']
    if any(signal in response_text.lower() for signal in completion_signals):
        if has_minimum_config(config_data):
            next_step = 'complete'
    
    # Determine next step based on context
    if 'team' in response_text.lower() or 'member' in response_text.lower():
        if not config_data.get('team_members'):
            next_step = 'team_building'
    elif 'project' in response_text.lower() or 'case' in response_text.lower():
        if not config_data.get('project_name') and not config_data.get('case_name'):
            next_step = 'project_setup'
    elif 'keyword' in response_text.lower() or 'term' in response_text.lower():
        next_step = 'keywords'
    
    return {
        'response': response_text,
        'extracted_data': extracted,
        'next_step': next_step,
        'quick_actions': get_default_quick_actions(next_step),
        'progress': calculate_progress(next_step, config_data),
        'is_complete': next_step == 'complete'
    }


async def _get_ai_config_response(
    prompt: str, task_complexity: TaskComplexity = DEFAULT_COMPLEXITY
) -> str:
    """Get AI response for configuration using task-aware model selection."""
    import asyncio

    if isinstance(task_complexity, str):
        try:
            task_complexity = TaskComplexity(task_complexity.lower())
        except ValueError:
            task_complexity = TaskComplexity.BASIC

    normalized_prompt = prompt.lower()
    detail_triggers = ["analyze", "analyse", "extract", "complex", "detailed", "breakdown"]
    if task_complexity == TaskComplexity.BASIC and any(
        term in normalized_prompt for term in detail_triggers
    ):
        task_complexity = TaskComplexity.MODERATE

    model_config = AIModelService.select_model("configuration", task_complexity)
    candidates = AIModelService.build_priority_queue(
        "configuration", task_complexity, model_config
    )

    errors: List[str] = []

    for candidate in candidates:
        resolved = AIModelService.resolve_model(candidate)
        if not resolved:
            continue

        provider = resolved["provider"]
        model_name = resolved["model"]
        display_name = AIModelService.display_name(candidate)

        try:
            if provider == "anthropic" and settings.CLAUDE_API_KEY:
                import anthropic

                client = anthropic.AsyncAnthropic(api_key=settings.CLAUDE_API_KEY)
                response = await client.messages.create(
                    model=model_name,
                    max_tokens=2000,
                    messages=[{"role": "user", "content": prompt}],
                )
                response_text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        response_text += block.text
                response_text = response_text or response.content[0].text
                log_model_selection("configuration", display_name, f"Anthropic:{model_name}")
                return response_text

            if provider == "openai" and settings.OPENAI_API_KEY:
                import openai

                client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
                response = await client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=2000,
                )
                response_text = response.choices[0].message.content
                log_model_selection("configuration", display_name, f"OpenAI:{model_name}")
                return response_text

            if provider == "google" and settings.GEMINI_API_KEY:
                import google.generativeai as genai

                genai.configure(api_key=settings.GEMINI_API_KEY)
                model = genai.GenerativeModel(model_name)
                response = await asyncio.to_thread(model.generate_content, prompt)
                response_text = getattr(response, "text", "") or ""
                if not response_text and getattr(response, "candidates", None):
                    parts = response.candidates[0].content.parts
                    if parts and hasattr(parts[0], "text"):
                        response_text = parts[0].text
                if response_text:
                    log_model_selection("configuration", display_name, f"Gemini:{model_name}")
                    return response_text

            if provider == "perplexity":
                response_text = await query_perplexity_local(prompt, "")
                if response_text:
                    log_model_selection("configuration", display_name, "Perplexity offline")
                    return response_text

        except Exception as exc:
            logger.warning("Model %s failed for configuration: %s", display_name, exc)
            errors.append(f"{display_name}: {exc}")

    detail = "No AI services available. Please configure at least one AI API key."
    if errors:
        detail = f"All AI services failed -> {', '.join(errors)}"
    raise HTTPException(status_code=503, detail=detail)


class ConfigMessage(BaseModel):
    message: str
    conversation_history: List[Dict[str, str]] = []
    current_step: str = "introduction"
    configuration_data: Dict[str, Any] = {}


class ConfigResponse(BaseModel):
    response: str
    next_step: Optional[str] = None
    configuration_data: Optional[Dict[str, Any]] = None
    quick_actions: Optional[List[str]] = None
    progress: Optional[int] = None
    configuration_complete: bool = False
    final_configuration: Optional[Dict[str, Any]] = None


def build_configuration_prompt(message: str, conversation_history: List[Dict], current_step: str, config_data: Dict) -> str:
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
            role = msg.get('role', 'user')
            content = msg.get('content', '')
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
    request: ConfigMessage = Body(...),
    db: Session = Depends(get_db),
    user = Depends(current_user)
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
            request.configuration_data
        )
        
        # Get AI response using available AI models
        ai_response_text = await _get_ai_config_response(prompt)
        
        # Parse AI response - it may return JSON or natural language
        import json
        import re
        
        response_text = ai_response_text
        
        # Try to extract JSON from response
        parsed = None
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text, re.DOTALL)
        
        if json_match:
            try:
                parsed = json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
        
        # If no valid JSON found, parse natural language response
        if not parsed:
            parsed = _parse_natural_language_response(
                response_text, 
                request.current_step, 
                request.configuration_data,
                request.message
            )
        
        # Merge extracted data with existing configuration
        updated_config = {**request.configuration_data}
        if 'extracted_data' in parsed:
            updated_config.update(parsed['extracted_data'])
        
        # Format and validate project_code/case_number if provided
        if updated_config.get('project_code'):
            formatted_code = format_project_code(updated_config['project_code'])
            updated_config['project_code'] = formatted_code
            # Check uniqueness
            is_unique, error_msg = await check_project_code_unique(formatted_code, db)
            if not is_unique:
                # Return error to user
                return ConfigResponse(
                    response=f"I see you want to use project code '{formatted_code}', but that code already exists. {error_msg} Please choose a different code.",
                    next_step=request.current_step,
                    configuration_data=updated_config,
                    quick_actions=['Try a different code', 'Add suffix', 'Let me suggest one'],
                    progress=calculate_progress(request.current_step, updated_config),
                    configuration_complete=False
                )
        
        if updated_config.get('case_number'):
            formatted_number = format_case_number(updated_config['case_number'])
            updated_config['case_number'] = formatted_number
            # Check uniqueness
            is_unique, error_msg = await check_case_number_unique(formatted_number, db)
            if not is_unique:
                # Return error to user
                return ConfigResponse(
                    response=f"I see you want to use case number '{formatted_number}', but that number already exists. {error_msg} Please choose a different number.",
                    next_step=request.current_step,
                    configuration_data=updated_config,
                    quick_actions=['Try a different number', 'Add suffix', 'Let me suggest one'],
                    progress=calculate_progress(request.current_step, updated_config),
                    configuration_complete=False
                )
        
        # Determine next step
        next_step = parsed.get('next_step', request.current_step)
        
        # Check if configuration is complete
        is_complete = parsed.get('is_complete', False) or (
            next_step == 'complete' and 
            has_minimum_config(updated_config)
        )
        
        # If complete, create the actual configuration
        final_config = None
        if is_complete:
            final_config = await create_configuration(updated_config, db, user)
        
        return ConfigResponse(
            response=parsed.get('response', 'I understand. Let me help you with that.'),
            next_step=next_step,
            configuration_data=updated_config,
            quick_actions=parsed.get('quick_actions', get_default_quick_actions(next_step)),
            progress=parsed.get('progress', calculate_progress(next_step, updated_config)),
            configuration_complete=is_complete,
            final_configuration=final_config
        )
        
    except Exception as e:
        logger.error(f"Error in intelligent configuration: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Configuration error: {str(e)}"
        )


def calculate_progress(step: str, config_data: Dict) -> int:
    """Calculate progress percentage based on current step and data collected"""
    step_weights = {
        'introduction': 0,
        'team_building': 25,
        'project_setup': 50,
        'keywords': 75,
        'review': 90,
        'complete': 100
    }
    
    base_progress = step_weights.get(step, 0)
    
    # Add bonus for data collected
    if config_data.get('team_members'):
        base_progress += 5
    if config_data.get('project_name') or config_data.get('case_name'):
        base_progress += 5
    if config_data.get('project_code') or config_data.get('case_number'):
        base_progress += 10  # IDs are critical
    if config_data.get('keywords'):
        base_progress += 5
    
    return min(base_progress, 100)


def get_default_quick_actions(step: str) -> List[str]:
    """Get default quick action buttons based on current step"""
    actions_map = {
        'introduction': ['I\'ll add team members', 'Show me how', 'I have a team list ready'],
        'team_building': ['Add another member', 'That\'s everyone', 'Skip for now'],
        'project_setup': ['It\'s a project', 'It\'s a case', 'I\'m not sure'],
        'id_validation': ['That looks good', 'Let me change it', 'Suggest a format'],
        'keywords': ['Add more keywords', 'That\'s enough', 'Auto-detect keywords'],
        'review': ['Continue configuration', 'Go to dashboard', 'Review setup'],
        'complete': ['Continue configuration', 'Go to dashboard', 'Review setup']
    }
    
    return actions_map.get(step, ['Continue', 'Skip', 'Help'])


async def create_configuration(config_data: Dict, db: Session, user) -> Dict[str, Any]:
    """Create the actual configuration in the database"""
    from .models import Project, Case, UserCompany, Company
    from datetime import datetime
    
    result = {
        'team_members': [],
        'project_id': None,
        'case_id': None,
        'project_code': None,
        'case_number': None
    }
    
    try:
        # Get user's company (required for Case)
        user_company = db.query(UserCompany).filter(
            UserCompany.user_id == user.id,
            UserCompany.is_primary == True
        ).first()
        
        if not user_company:
            # Create a default company if none exists
            company = Company(name="My Company")
            db.add(company)
            db.flush()
            user_company = UserCompany(
                user_id=user.id,
                company_id=company.id,
                role="admin",
                is_primary=True
            )
            db.add(user_company)
            db.flush()
        
        company_id = user_company.company_id
        
        # Create team members (if provided)
        if config_data.get('team_members'):
            # Note: In a real implementation, you'd create User records or link existing ones
            result['team_members'] = config_data['team_members']
        
        # Create project or case
        profile_type = config_data.get('profile_type', 'project')
        name = config_data.get('project_name') or config_data.get('case_name', 'Untitled')
        
        if profile_type == 'project':
            # Require project_code
            project_code = config_data.get('project_code')
            if not project_code:
                raise ValueError("Project code is required but not provided")
            
            # Final uniqueness check
            existing = db.query(Project).filter(Project.project_code == project_code).first()
            if existing:
                raise ValueError(f"Project code '{project_code}' already exists")
            
            project = Project(
                project_name=name,
                project_code=project_code,
                description=config_data.get('description', ''),
                contract_type=config_data.get('contract_type'),
                owner_user_id=user.id,
                meta={
                    'team_members': config_data.get('team_members', []),
                    'roles': config_data.get('roles', []),
                    'keywords': config_data.get('keywords', []),
                    'configured_by_ai': True
                }
            )
            db.add(project)
            db.commit()
            db.refresh(project)
            result['project_id'] = str(project.id)
            result['project_code'] = project.project_code
        else:
            # Require case_number
            case_number = config_data.get('case_number')
            if not case_number:
                raise ValueError("Case number is required but not provided")
            
            # Final uniqueness check
            existing = db.query(Case).filter(Case.case_number == case_number).first()
            if existing:
                raise ValueError(f"Case number '{case_number}' already exists")
            
            case = Case(
                name=name,
                case_number=case_number,
                description=config_data.get('description', ''),
                project_name=config_data.get('project_name'),
                contract_type=config_data.get('contract_type'),
                dispute_type=config_data.get('dispute_type'),
                owner_id=user.id,
                company_id=company_id,
                status="active"
            )
            db.add(case)
            db.commit()
            db.refresh(case)
            result['case_id'] = str(case.id)
            result['case_number'] = case.case_number
        
        logger.info(f"Created {profile_type} '{name}' ({result.get('project_code') or result.get('case_number')}) via intelligent configuration for user {user.email}")
        
    except Exception as e:
        logger.error(f"Error creating configuration: {e}", exc_info=True)
        db.rollback()
        raise
    
    return result

