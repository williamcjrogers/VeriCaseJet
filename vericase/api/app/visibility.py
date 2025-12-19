"""Visibility helpers for evidence items.

This module centralizes the "excluded/hidden" convention used across:
- Correspondence Enterprise UI (server-side grid)
- AI retrieval / evidence context building
- OpenSearch indexing / reindex scripts

Core principle: if an email is excluded/hidden (spam, other_project, not_relevant, etc.),
it must not be used for AI context or retrieval unless a human explicitly restores it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, or_


def build_email_visibility_filter(email_model: Any):
    """Return a SQLAlchemy filter for *visible* email rows.

    Rules (mirrors Correspondence Enterprise defaults):
    - meta.spam.user_override == 'visible'  -> always show
    - meta.spam.user_override == 'hidden'   -> always hide
    - otherwise:
        - meta.status is NULL or 'active'
        - meta.is_hidden is NULL or != 'true'

    Notes:
    - Production stores `meta` as Postgres JSON (not JSONB). Use ->/->> operators.
    - We intentionally do NOT rely on `meta['excluded']` because older rows may not
      have it, and `is_hidden`/`status` are the canonical visibility controls.
    """

    status_field = email_model.meta["status"].as_string()
    hidden_field = email_model.meta["is_hidden"].as_string()
    override_field = email_model.meta.op("->")("spam").op("->>")("user_override")

    return or_(
        override_field == "visible",
        and_(
            or_(override_field.is_(None), override_field != "hidden"),
            or_(status_field.is_(None), status_field == "active"),
            or_(hidden_field.is_(None), hidden_field != "true"),
        ),
    )


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return False


def is_email_visible_meta(meta: dict[str, Any] | None) -> bool:
    """Pure-Python check for whether an email meta payload is visible.

    Used in places where we have the EmailMessage object already and want to avoid
    indexing or processing excluded content (e.g., OpenSearch indexing).
    """

    if not meta or not isinstance(meta, dict):
        return True

    spam = meta.get("spam")
    user_override: str | None = None
    if isinstance(spam, dict):
        user_override = spam.get("user_override")

    if user_override == "visible":
        return True
    if user_override == "hidden":
        return False

    status = meta.get("status")
    if status not in (None, "", "active"):
        return False

    # Canonical hidden flag.
    if _truthy(meta.get("is_hidden")):
        return False

    # Backward-compatible / belt-and-suspenders.
    if _truthy(meta.get("excluded")):
        return False

    return True
