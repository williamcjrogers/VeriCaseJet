"""
AI-Powered Spam/Filter for replacing legacy Regex filter.
Uses the configured 'ai_filter' tool from AI Settings.
"""

from __future__ import annotations
import logging
import asyncio
from typing import TypedDict
from sqlalchemy.orm import Session
from .ai_settings import AISettings
from .ai_runtime import complete_chat

logger = logging.getLogger(__name__)


class SpamResult(TypedDict):
    is_spam: bool
    score: int
    category: str | None
    is_hidden: bool
    explanation: str | None
    extracted_entity: str | None  # For identifying specific projects or entities


OTHER_PROJECTS_LIST = [
    "Abbey Road",
    "Peabody",
    "Merrick Place",
    "Southall",
    "Oxlow Lane",
    "Dagenham",
    "BeFirst",
    "Roxwell Road",
    "Kings Crescent",
    "Peckham Library",
    "Flaxyard",
    "Loxford",
    "Seven Kings",
    "Redbridge Living",
    "Frank Towell Court",
    "Lisson Arches",
    "Beaulieu Park",
    "Chelmsford",
    "Islay Wharf",
    "Victory Place",
    "Earlham Grove",
    "Canons Park",
    "Rayners Lane",
    "Clapham Park",
    "MTVH",
    "Osier Way",
    "Pocket Living",
    "Moreland Gardens",
    "Buckland",
    "South Thames College",
    "Robert Whyte House",
    "Bromley",
    "Camley Street",
    "LSA",
    "Honeywell",
    "Becontree",
    "Honeypot",
]


async def classify_email_ai(
    subject: str,
    sender: str,
    body_preview: str,
    db: Session,
) -> SpamResult:
    """
    Classify email using AI Filter tool configuration.
    """
    try:
        # Load tool config
        config = AISettings.get_tool_config("ai_filter", db)

        if not config or not config.get("enabled", True):
            # If disabled, return safe default
            return {
                "is_spam": False,
                "score": 0,
                "category": None,
                "is_hidden": False,
                "explanation": "AI Filter disabled",
                "extracted_entity": None,
            }

        provider = config.get("provider", "gemini")
        model = config.get("model", "gemini-2.5-flash-lite")
        temperature = config.get("temperature", 0.0)

        # Truncate body to avoid excessive tokens
        safe_body = (body_preview or "")[:1000]
        projects_str = ", ".join(OTHER_PROJECTS_LIST)

        system_prompt = (
            "You are an AI Email Classifier for a legal case management system (Project: Welbourne). "
            "Your task is to identify SPAM, MARKETING, NEWSLETTERS, and UNRELATED PROJECT communications. "
            f"If the email explicitly discusses one of the following unrelated projects, categorize as 'other_projects' and set 'extracted_entity' to the project name: {projects_str}. "
            'Return a JSON object with: { "is_spam": boolean, "score": int (0-100), "category": string, "explanation": string, "extracted_entity": string|null }.'
            "Categories: marketing, newsletter, spam, notification, other_projects, legitimate."
        )

        user_prompt = f"Sender: {sender}\nSubject: {subject}\nBody Snippet: {safe_body}"

        response_text = await complete_chat(
            provider=provider,
            model_id=model,
            prompt=user_prompt,
            system_prompt=system_prompt,
            db=db,
            temperature=temperature,
            max_tokens=200,
            task_type="classification",
            function_name="ai_spam_filter",
        )

        # Parse JSON from response
        import json

        clean_text = response_text.replace("```json", "").replace("```", "").strip()
        # Handle cases where AI might add extra text
        if "{" in clean_text:
            clean_text = clean_text[clean_text.find("{") : clean_text.rfind("}") + 1]

        data = json.loads(clean_text)

        is_spam = data.get("is_spam", False)
        score = data.get("score", 0)
        category = data.get("category")
        extracted_entity = data.get("extracted_entity")

        # Determine if should be hidden
        # Typically high score spam is hidden. other_projects are also usually hidden/filed away.
        is_hidden = (is_spam and score > 75) or (category == "other_projects")

        return {
            "is_spam": is_spam,
            "score": score,
            "category": category,
            "is_hidden": is_hidden,
            "explanation": data.get("explanation"),
            "extracted_entity": extracted_entity,
        }

    except Exception as e:
        logger.error(f"AI Filter failed: {e}")
        # Fail safe - do not hide valid emails
        return {
            "is_spam": False,
            "score": 0,
            "category": None,
            "is_hidden": False,
            "explanation": f"Error: {e}",
            "extracted_entity": None,
        }


def classify_email_ai_sync(
    subject: str,
    sender: str,
    body_preview: str,
    db: Session,
) -> SpamResult:
    """
    Synchronous wrapper for classify_email_ai.
    """
    try:
        # Check for existing loop
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            # If we are already in a loop, we can't block it with run_until_complete.
            # But we are in a sync function. This usually means we are in a thread called from async?
            # Or we are in a sync validation context.
            # Ideally we use a new loop in a thread, but that's heavy.
            # For simplicity in this context (PST processing is typically blocking/threaded),
            # we try to run it.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run, classify_email_ai(subject, sender, body_preview, db)
                ).result()
        else:
            return loop.run_until_complete(
                classify_email_ai(subject, sender, body_preview, db)
            )

    except Exception as e:
        logger.error(f"Sync AI Filter wrapper failed: {e}")
        return {
            "is_spam": False,
            "score": 0,
            "category": None,
            "is_hidden": False,
            "explanation": f"Sync Error: {e}",
        }
