"""
Deterministic email threading with evidence-grade link attribution.

This module builds parent-child links using a strict precedence hierarchy:
1) In-Reply-To
2) References (last resolvable ID)
3) Quoted-anchor hash
4) Subject key + participant overlap + time window
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from .models import EmailMessage, EmailThreadLink

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================


@dataclass(frozen=True)
class ThreadingConfig:
    time_window_hours: int = 36
    quoted_anchor_lines: int = 6
    subject_numeric_token_len: int = 4
    allow_conversation_index: bool = False


@dataclass
class ThreadingStats:
    emails_total: int = 0
    links_created: int = 0
    threads_identified: int = 0
    orphans: int = 0
    ambiguous: int = 0


@dataclass
class ThreadNode:
    email_id: uuid.UUID
    message_id: str | None
    message_id_norm: str | None
    in_reply_to_norm: str | None
    references_norm: list[str]
    subject_key: str | None
    participants: set[str]
    date_sent: datetime | None
    conversation_index: str | None
    body_anchor_hash: str | None
    quoted_anchor_hash: str | None
    sender: str | None
    raw_subject: str | None


@dataclass
class ThreadLinkDecision:
    parent_email_id: uuid.UUID | None
    methods: list[str]
    evidence: dict[str, Any]
    confidence: float
    alternatives: list[dict[str, Any]]


# =============================================================================
# Normalization helpers
# =============================================================================


_SUBJECT_PREFIX_RE = re.compile(
    r"^\s*(?:re|fw|fwd|aw|sv|wg|tr|fs)\s*:\s*", re.IGNORECASE
)

_HEADER_LINE_RE = re.compile(
    r"^(from|sent|to|cc|bcc|subject|date)\s*:\s*", re.IGNORECASE
)

_REPLY_SPLIT_RE = re.compile(
    r"(?mi)^\s*>?\s*On .+ wrote:"
    r"|^\s*>?\s*From:\s"
    r"|^\s*>?\s*Sent:\s"
    r"|^\s*>?\s*To:\s"
    r"|^\s*>?\s*Cc:\s"
    r"|^\s*>?\s*Bcc:\s"
    r"|^\s*>?\s*Subject:\s"
    r"|^\s*>?\s*Date:\s"
    r"|^-----Original Message-----"
    r"|^----- Forwarded message -----"
    r"|^Begin forwarded message",
)


def _normalize_message_id(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"<([^>]+)>", text)
    if match:
        text = match.group(1)
    text = text.strip().strip("<>").strip()
    return text.lower() or None


def _parse_references(value: Any) -> list[str]:
    if not value:
        return []
    text = str(value)
    tokens = re.findall(r"<([^>]+)>", text)
    if not tokens:
        tokens = re.split(r"[,\s]+", text)
    refs: list[str] = []
    for token in tokens:
        ref = _normalize_message_id(token)
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def _normalize_subject(subject: str | None, numeric_len: int) -> str | None:
    if not subject:
        return None
    s = subject.strip()
    if not s:
        return None
    # Remove leading bracketed tags like [EXTERNAL] or [CAUTION]
    s = re.sub(r"^\s*\[[^\]]{0,80}\]\s*", "", s)
    # Strip common reply/forward prefixes iteratively
    while True:
        new_s = _SUBJECT_PREFIX_RE.sub("", s)
        if new_s == s:
            break
        s = new_s
    s = s.strip()
    if not s:
        return None
    # Remove long numeric tokens (ticket/contract refs)
    if numeric_len > 0:
        s = re.sub(rf"\b\d{{{numeric_len},}}\b", "", s)
    # Normalize punctuation/whitespace
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s or None


def _normalize_text_for_hash(text: str) -> str:
    normalized = text.replace("\x00", " ").replace("\u0000", " ")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[^\S\n]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return normalized


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_body_anchor(text: str | None, max_lines: int) -> str | None:
    if not text:
        return None
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _HEADER_LINE_RE.match(stripped):
            continue
        if stripped.startswith(">"):
            stripped = stripped.lstrip(">").strip()
        if stripped:
            lines.append(stripped)
        if len(lines) >= max_lines:
            break
    if not lines:
        return None
    return "\n".join(lines)


def _extract_quoted_anchor(text: str | None, max_lines: int) -> str | None:
    if not text:
        return None
    anchor_text = None
    match = _REPLY_SPLIT_RE.search(text)
    if match:
        anchor_text = text[match.start() :]
    else:
        quoted_lines = [
            line for line in text.splitlines() if line.lstrip().startswith(">")
        ]
        if quoted_lines:
            anchor_text = "\n".join(quoted_lines)

    if not anchor_text:
        return None

    lines = []
    for line in anchor_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _HEADER_LINE_RE.match(stripped):
            continue
        if stripped.startswith(">"):
            stripped = stripped.lstrip(">").strip()
        if stripped:
            lines.append(stripped)
        if len(lines) >= max_lines:
            break
    if not lines:
        return None
    return "\n".join(lines)


def _participants_from_email(email: EmailMessage) -> set[str]:
    participants: set[str] = set()
    sender = (email.sender_email or "").strip().lower()
    if sender:
        participants.add(sender)
    for field in ("recipients_to", "recipients_cc", "recipients_bcc"):
        values = getattr(email, field, None)
        if values:
            for value in values:
                if value:
                    participants.add(str(value).strip().lower())
    return participants


def _email_timestamp(email: EmailMessage) -> datetime | None:
    return email.date_sent or email.date_received


def _is_forward_subject(subject: str | None) -> bool:
    if not subject:
        return False
    return bool(re.match(r"^\s*(?:fw|fwd)\s*:", subject, re.IGNORECASE))


# =============================================================================
# Threading engine
# =============================================================================


def build_email_threads(
    db: Session,
    *,
    case_id: uuid.UUID | str | None = None,
    project_id: uuid.UUID | str | None = None,
    config: ThreadingConfig | None = None,
    run_id: str | None = None,
) -> ThreadingStats:
    if not case_id and not project_id:
        return ThreadingStats()

    cfg = config or ThreadingConfig()

    case_uuid = _to_uuid(case_id)
    project_uuid = _to_uuid(project_id)

    query = db.query(EmailMessage)
    if case_uuid:
        query = query.filter(EmailMessage.case_id == case_uuid)
    if project_uuid:
        query = query.filter(EmailMessage.project_id == project_uuid)

    emails = query.all()
    stats = ThreadingStats(emails_total=len(emails))
    if not emails:
        return stats

    nodes = _build_nodes(emails, cfg)
    nodes_by_id = {node.email_id: node for node in nodes}

    indexes = _build_indexes(nodes)
    decisions = _select_parents(nodes, nodes_by_id, indexes, cfg)

    thread_groups = _assign_thread_groups(nodes_by_id, decisions)
    stats.threads_identified = len(thread_groups)

    updates: list[dict[str, Any]] = []
    link_rows: list[EmailThreadLink] = []

    for node in nodes:
        decision = decisions.get(node.email_id)
        parent_id = decision.parent_email_id if decision else None
        parent_msg_id = None
        if parent_id and parent_id in nodes_by_id:
            parent_msg_id = nodes_by_id[parent_id].message_id
            if not parent_msg_id:
                parent_msg_id = str(parent_id)

        thread_group_id = thread_groups.get(node.email_id)
        thread_id = thread_group_id

        updates.append(
            {
                "id": node.email_id,
                "thread_group_id": thread_group_id,
                "thread_id": thread_id,
                "parent_message_id": parent_msg_id,
            }
        )

        if decision and decision.parent_email_id:
            link_rows.append(
                EmailThreadLink(
                    child_email_id=node.email_id,
                    parent_email_id=decision.parent_email_id,
                    methods=decision.methods,
                    evidence=decision.evidence,
                    confidence=decision.confidence,
                    alternatives=decision.alternatives,
                    run_id=run_id,
                )
            )

    _apply_thread_positions(nodes_by_id, updates)

    email_ids = [node.email_id for node in nodes]
    if email_ids:
        db.query(EmailThreadLink).filter(
            EmailThreadLink.child_email_id.in_(email_ids)
        ).delete(synchronize_session=False)

    if updates:
        db.bulk_update_mappings(EmailMessage, updates)
    if link_rows:
        db.bulk_save_objects(link_rows)

    db.commit()

    stats.links_created = len(link_rows)
    stats.orphans = sum(
        1
        for node in nodes
        if not decisions.get(node.email_id)
        or not decisions.get(node.email_id).parent_email_id
    )
    stats.ambiguous = sum(
        1
        for decision in decisions.values()
        if decision.alternatives and not decision.parent_email_id
    )
    return stats


def _build_nodes(
    emails: Iterable[EmailMessage], cfg: ThreadingConfig
) -> list[ThreadNode]:
    nodes: list[ThreadNode] = []
    for email in emails:
        message_id_norm = _normalize_message_id(email.message_id)
        in_reply_to_norm = _normalize_message_id(email.in_reply_to)
        references_norm = _parse_references(email.email_references)
        subject_key = _normalize_subject(email.subject, cfg.subject_numeric_token_len)
        participants = _participants_from_email(email)
        date_sent = _email_timestamp(email)
        body_anchor = _extract_body_anchor(
            email.body_text_clean, cfg.quoted_anchor_lines
        )
        quoted_anchor = _extract_quoted_anchor(email.body_text, cfg.quoted_anchor_lines)
        body_anchor_hash = (
            _hash_text(_normalize_text_for_hash(body_anchor)) if body_anchor else None
        )
        quoted_anchor_hash = (
            _hash_text(_normalize_text_for_hash(quoted_anchor))
            if quoted_anchor
            else None
        )

        nodes.append(
            ThreadNode(
                email_id=email.id,
                message_id=email.message_id,
                message_id_norm=message_id_norm,
                in_reply_to_norm=in_reply_to_norm,
                references_norm=references_norm,
                subject_key=subject_key,
                participants=participants,
                date_sent=date_sent,
                conversation_index=email.conversation_index,
                body_anchor_hash=body_anchor_hash,
                quoted_anchor_hash=quoted_anchor_hash,
                sender=(
                    (email.sender_email or "").lower() if email.sender_email else None
                ),
                raw_subject=email.subject,
            )
        )
    return nodes


def _build_indexes(nodes: Iterable[ThreadNode]) -> dict[str, Any]:
    message_id_index: dict[str, list[ThreadNode]] = {}
    subject_index: dict[str, list[ThreadNode]] = {}
    anchor_index: dict[str, list[ThreadNode]] = {}
    conv_index: dict[str, list[ThreadNode]] = {}

    for node in nodes:
        if node.message_id_norm:
            message_id_index.setdefault(node.message_id_norm, []).append(node)
        if node.subject_key:
            subject_index.setdefault(node.subject_key, []).append(node)
        if node.body_anchor_hash:
            anchor_index.setdefault(node.body_anchor_hash, []).append(node)
        if node.conversation_index:
            conv_index.setdefault(node.conversation_index, []).append(node)

    # Sort subject buckets by date for deterministic selection
    for key in subject_index:
        subject_index[key].sort(
            key=lambda n: n.date_sent or datetime.min.replace(tzinfo=timezone.utc)
        )

    return {
        "message_id": message_id_index,
        "subject": subject_index,
        "anchor": anchor_index,
        "conversation_index": conv_index,
    }


def _select_parents(
    nodes: Iterable[ThreadNode],
    nodes_by_id: dict[uuid.UUID, ThreadNode],
    indexes: dict[str, Any],
    cfg: ThreadingConfig,
) -> dict[uuid.UUID, ThreadLinkDecision]:
    decisions: dict[uuid.UUID, ThreadLinkDecision] = {}

    for node in nodes:
        decision = _select_parent_for_node(node, nodes_by_id, indexes, cfg)
        decisions[node.email_id] = decision

    return decisions


def _select_parent_for_node(
    node: ThreadNode,
    nodes_by_id: dict[uuid.UUID, ThreadNode],
    indexes: dict[str, Any],
    cfg: ThreadingConfig,
) -> ThreadLinkDecision:
    alternatives: list[dict[str, Any]] = []

    # Priority 1: In-Reply-To
    if node.in_reply_to_norm:
        candidates = indexes["message_id"].get(node.in_reply_to_norm, [])
        decision = _resolve_candidates(
            node,
            candidates,
            method="InReplyTo",
            alternatives=alternatives,
        )
        if decision:
            return decision

    # Priority 2: References (last resolvable)
    if node.references_norm:
        for ref_id in reversed(node.references_norm):
            candidates = indexes["message_id"].get(ref_id, [])
            decision = _resolve_candidates(
                node,
                candidates,
                method="References",
                alternatives=alternatives,
            )
            if decision:
                return decision

    # Priority 3: Quoted anchor hash
    if node.quoted_anchor_hash:
        candidates = indexes["anchor"].get(node.quoted_anchor_hash, [])
        decision = _resolve_candidates(
            node,
            candidates,
            method="QuotedHash",
            alternatives=alternatives,
        )
        if decision:
            return decision

    # Priority 4: Subject key + participants + time window
    if node.subject_key and not _is_forward_subject(node.raw_subject):
        candidates = indexes["subject"].get(node.subject_key, [])
        decision = _resolve_subject_window(node, candidates, cfg, alternatives)
        if decision:
            return decision

    return ThreadLinkDecision(
        parent_email_id=None,
        methods=[],
        evidence={},
        confidence=0.0,
        alternatives=alternatives,
    )


def _resolve_candidates(
    node: ThreadNode,
    candidates: list[ThreadNode],
    *,
    method: str,
    alternatives: list[dict[str, Any]],
) -> ThreadLinkDecision | None:
    if not candidates:
        return None

    if len(candidates) == 1:
        parent = candidates[0]
        return ThreadLinkDecision(
            parent_email_id=parent.email_id,
            methods=[method],
            evidence=_build_evidence(node, parent, method),
            confidence=_confidence_for_method(method),
            alternatives=alternatives,
        )

    # Multiple candidates: try disambiguation via timestamp proximity
    best = _closest_parent_by_time(node, candidates)
    if best:
        alternatives.extend(
            _alternatives_from_candidates(
                candidates, chosen_id=best.email_id, reason="duplicate_message_id"
            )
        )
        return ThreadLinkDecision(
            parent_email_id=best.email_id,
            methods=[method, "DisambiguatedByTime"],
            evidence=_build_evidence(
                node, best, method, extra={"disambiguation": "time"}
            ),
            confidence=max(_confidence_for_method(method) - 0.08, 0.0),
            alternatives=alternatives,
        )

    alternatives.extend(
        _alternatives_from_candidates(
            candidates, chosen_id=None, reason="duplicate_message_id"
        )
    )
    return None


def _resolve_subject_window(
    node: ThreadNode,
    candidates: list[ThreadNode],
    cfg: ThreadingConfig,
    alternatives: list[dict[str, Any]],
) -> ThreadLinkDecision | None:
    if not candidates:
        return None
    if not node.date_sent:
        return None

    window = timedelta(hours=cfg.time_window_hours)
    best: ThreadNode | None = None
    best_delta: timedelta | None = None

    for cand in candidates:
        if not cand.date_sent:
            continue
        if cand.email_id == node.email_id:
            continue
        if cand.date_sent > node.date_sent:
            continue
        if not (node.participants & cand.participants):
            continue
        delta = node.date_sent - cand.date_sent
        if delta > window:
            continue
        if best is None or delta < (best_delta or window):
            best = cand
            best_delta = delta

    if not best:
        return None

    alternatives.extend(
        _alternatives_from_candidates(
            candidates, chosen_id=best.email_id, reason="subject_window"
        )
    )
    evidence = _build_evidence(node, best, "SubjectWindow")
    evidence["time_delta_hours"] = (
        best_delta.total_seconds() / 3600 if best_delta else None
    )
    evidence["participants_overlap"] = sorted(node.participants & best.participants)
    return ThreadLinkDecision(
        parent_email_id=best.email_id,
        methods=["SubjectWindow"],
        evidence=evidence,
        confidence=_confidence_for_method("SubjectWindow"),
        alternatives=alternatives,
    )


def _closest_parent_by_time(
    node: ThreadNode, candidates: list[ThreadNode]
) -> ThreadNode | None:
    if not node.date_sent:
        return None
    best = None
    best_delta = None
    for cand in candidates:
        if not cand.date_sent:
            continue
        if cand.date_sent > node.date_sent:
            continue
        delta = node.date_sent - cand.date_sent
        if best is None or delta < best_delta:
            best = cand
            best_delta = delta
    return best


def _build_evidence(
    node: ThreadNode,
    parent: ThreadNode,
    method: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = {
        "method": method,
        "in_reply_to": node.in_reply_to_norm,
        "references": node.references_norm,
        "quoted_hash": node.quoted_anchor_hash,
        "subject_key": node.subject_key,
        "parent_message_id": parent.message_id,
        "parent_email_id": str(parent.email_id),
    }
    if node.date_sent and parent.date_sent:
        evidence["time_delta_hours"] = (
            node.date_sent - parent.date_sent
        ).total_seconds() / 3600
    if extra:
        evidence.update(extra)
    return evidence


def _confidence_for_method(method: str) -> float:
    return {
        "InReplyTo": 0.98,
        "References": 0.96,
        "QuotedHash": 0.85,
        "SubjectWindow": 0.6,
    }.get(method, 0.5)


def _alternatives_from_candidates(
    candidates: list[ThreadNode],
    *,
    chosen_id: uuid.UUID | None,
    reason: str,
) -> list[dict[str, Any]]:
    alternatives = []
    for cand in candidates:
        if chosen_id and cand.email_id == chosen_id:
            continue
        alternatives.append(
            {
                "candidate_email_id": str(cand.email_id),
                "candidate_message_id": cand.message_id,
                "reason": reason,
            }
        )
    return alternatives


def _assign_thread_groups(
    nodes_by_id: dict[uuid.UUID, ThreadNode],
    decisions: dict[uuid.UUID, ThreadLinkDecision],
) -> dict[uuid.UUID, str]:
    root_cache: dict[uuid.UUID, uuid.UUID] = {}

    def _root_for(node_id: uuid.UUID) -> uuid.UUID:
        if node_id in root_cache:
            return root_cache[node_id]
        decision = decisions.get(node_id)
        if not decision or not decision.parent_email_id:
            root_cache[node_id] = node_id
            return node_id
        parent_id = decision.parent_email_id
        if parent_id == node_id:
            root_cache[node_id] = node_id
            return node_id
        root_id = _root_for(parent_id)
        root_cache[node_id] = root_id
        return root_id

    thread_ids: dict[uuid.UUID, str] = {}
    for node_id in nodes_by_id:
        root_id = _root_for(node_id)
        if root_id not in thread_ids:
            thread_ids[root_id] = _make_thread_group_id(nodes_by_id[root_id])
    return {node_id: thread_ids[_root_for(node_id)] for node_id in nodes_by_id}


def _make_thread_group_id(root: ThreadNode) -> str:
    key = root.message_id_norm or root.message_id or ""
    if not key:
        key = root.subject_key or ""
    if not key:
        key = str(root.email_id)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"thread_{digest[:32]}"


def _apply_thread_positions(
    nodes_by_id: dict[uuid.UUID, ThreadNode],
    updates: list[dict[str, Any]],
) -> None:
    grouped: dict[str, list[ThreadNode]] = {}
    update_map: dict[uuid.UUID, dict[str, Any]] = {
        update["id"]: update for update in updates
    }
    thread_group_ids: dict[uuid.UUID, str] = {
        update_id: update_data["thread_group_id"]
        for update_id, update_data in update_map.items()
    }
    for node in nodes_by_id.values():
        group_id = thread_group_ids.get(node.email_id)
        if not group_id:
            continue
        grouped.setdefault(group_id, []).append(node)

    for group_id, items in grouped.items():
        items.sort(
            key=lambda n: n.date_sent or datetime.min.replace(tzinfo=timezone.utc)
        )
        for idx, node in enumerate(items):
            update = update_map.get(node.email_id)
            if update is not None:
                update["thread_position"] = idx
                update["thread_path"] = f"{idx:06d}"


def _to_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if not value:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None
