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
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import sqlalchemy as sa
from sqlalchemy.orm import Session, load_only

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
    allow_conversation_index: bool = True
    # Thread-path encoding controls.
    # We store thread_path primarily for deterministic ordering. It must be bounded to avoid
    # DB truncation failures (some deployments still have VARCHAR(64) from legacy schemas).
    # Encoding is base36 with fixed width per thread-group (computed dynamically).
    thread_path_max_len: int | None = None


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
    content_hash: str | None
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


def _normalize_conversation_index(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    text = re.sub(r"\s+", "", text)
    return text.lower() or None


def _conversation_index_root(value: str | None) -> str | None:
    if not value:
        return None
    text = _normalize_conversation_index(value)
    if not text:
        return None
    return text[:44] if len(text) >= 44 else text


def _conversation_index_parent(value: str | None) -> str | None:
    text = _normalize_conversation_index(value)
    if not text:
        return None
    # Root conversation index is 44 chars; each child adds 10 chars
    # If <= 44, this is a root with no parent
    if len(text) <= 44:
        return None
    # Strip the last 10-char child segment to get the parent
    return text[:-10]


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


def _node_sort_key(node: ThreadNode) -> tuple[datetime, str, str]:
    timestamp = node.date_sent or datetime.min.replace(tzinfo=timezone.utc)
    message_key = node.message_id_norm or node.message_id or ""
    return (timestamp, message_key, str(node.email_id))


# =============================================================================
# Threading engine
# =============================================================================


def build_email_threads(
    db: Session,
    *,
    case_id: uuid.UUID | str | None = None,
    project_id: uuid.UUID | str | None = None,
    pst_file_id: uuid.UUID | str | None = None,
    config: ThreadingConfig | None = None,
    run_id: str | None = None,
) -> ThreadingStats:
    if not case_id and not project_id and not pst_file_id:
        return ThreadingStats()

    cfg = config or ThreadingConfig()

    case_uuid = _to_uuid(case_id)
    project_uuid = _to_uuid(project_id)
    pst_uuid = _to_uuid(pst_file_id)

    # Default thread_path_max_len from the database column (if VARCHAR); leave as None for TEXT.
    # ThreadingConfig is frozen, so compute and (optionally) replace.
    if cfg.thread_path_max_len is None:
        try:
            result = db.execute(
                sa.text(
                    """
                    SELECT character_maximum_length
                    FROM information_schema.columns
                    WHERE table_name = 'email_messages'
                      AND column_name = 'thread_path'
                    """
                )
            )
            length = result.scalar()
            if length:
                cfg = replace(cfg, thread_path_max_len=int(length))
        except Exception:
            # Best-effort only; do not block threading.
            # Be conservative: legacy schemas used VARCHAR(64) which will hard-fail on overflow.
            cfg = replace(cfg, thread_path_max_len=64)

    query = db.query(EmailMessage).options(
        load_only(
            EmailMessage.id,
            EmailMessage.message_id,
            EmailMessage.in_reply_to,
            EmailMessage.email_references,
            EmailMessage.conversation_index,
            EmailMessage.subject,
            EmailMessage.sender_email,
            EmailMessage.recipients_to,
            EmailMessage.recipients_cc,
            EmailMessage.recipients_bcc,
            EmailMessage.date_sent,
            EmailMessage.date_received,
            EmailMessage.content_hash,
            EmailMessage.body_text_clean,
            EmailMessage.body_text,
        )
    )
    if case_uuid:
        query = query.filter(EmailMessage.case_id == case_uuid)
    if project_uuid:
        query = query.filter(EmailMessage.project_id == project_uuid)
    if pst_uuid:
        query = query.filter(EmailMessage.pst_file_id == pst_uuid)

    emails = query.all()
    stats = ThreadingStats(emails_total=len(emails))
    if not emails:
        return stats

    nodes = _build_nodes(emails, cfg)
    nodes_by_id = {node.email_id: node for node in nodes}

    indexes = _build_indexes(nodes)
    decisions = _select_parents(nodes, nodes_by_id, indexes, cfg)

    cycles_broken = _break_parent_cycles(nodes_by_id, decisions)
    if cycles_broken:
        logger.warning(
            "Email threading cycle(s) detected and broken: %s", cycles_broken
        )

    thread_groups = _assign_thread_groups(nodes_by_id, decisions)
    stats.threads_identified = len(set(thread_groups.values()))

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

    _apply_thread_positions(
        nodes_by_id,
        updates,
        decisions,
        thread_path_max_len=cfg.thread_path_max_len,
    )

    try:
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
    except Exception:
        db.rollback()
        raise

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
        conversation_index = _normalize_conversation_index(email.conversation_index)
        content_hash = email.content_hash
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
                conversation_index=conversation_index,
                content_hash=content_hash,
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
        subject_index[key].sort(key=_node_sort_key)

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

    # Priority 3: Outlook ConversationIndex (when present)
    if cfg.allow_conversation_index and node.conversation_index:
        parent_index = _conversation_index_parent(node.conversation_index)
        if parent_index:
            candidates = indexes["conversation_index"].get(parent_index, [])
            decision = _resolve_candidates(
                node,
                candidates,
                method="ConversationIndex",
                alternatives=alternatives,
            )
            if decision:
                return decision

    # Priority 4: Quoted anchor hash
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

    # Priority 5: Subject key + participants + time window
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
        elif best_delta is not None and delta == best_delta:
            if _node_sort_key(cand) < _node_sort_key(best):
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
        if (
            best is None
            or delta < best_delta
            or (
                best_delta is not None
                and delta == best_delta
                and _node_sort_key(cand) < _node_sort_key(best)
            )
        ):
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
        "conversation_index": node.conversation_index,
        "parent_conversation_index": parent.conversation_index,
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
        "ConversationIndex": 0.9,
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
    parent_map: dict[uuid.UUID, uuid.UUID] = {}
    for node_id, decision in decisions.items():
        parent_id = decision.parent_email_id if decision else None
        if (
            parent_id
            and parent_id != node_id
            and parent_id in nodes_by_id
            and node_id in nodes_by_id
        ):
            parent_map[node_id] = parent_id

    root_cache: dict[uuid.UUID, uuid.UUID] = {}

    def _root_for(node_id: uuid.UUID) -> uuid.UUID:
        cached = root_cache.get(node_id)
        if cached is not None:
            return cached

        chain: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()
        current = node_id
        root: uuid.UUID | None = None

        while True:
            cached = root_cache.get(current)
            if cached is not None:
                root = cached
                break

            if current in seen:
                # Defensive: cycles should have been broken, but never recurse forever.
                root = min(seen, key=lambda cid: _node_sort_key(nodes_by_id[cid]))
                break

            seen.add(current)
            chain.append(current)

            parent_id = parent_map.get(current)
            if not parent_id:
                root = current
                break
            current = parent_id

        for cid in chain:
            root_cache[cid] = root
        return root

    thread_ids: dict[uuid.UUID, str] = {}
    for node in sorted(nodes_by_id.values(), key=_node_sort_key):
        root_id = _root_for(node.email_id)
        if root_id not in thread_ids:
            thread_ids[root_id] = _make_thread_group_id(nodes_by_id[root_id])

    return {node_id: thread_ids[_root_for(node_id)] for node_id in nodes_by_id}


def _make_thread_group_id(root: ThreadNode) -> str:
    key = root.message_id_norm or root.message_id
    if not key and root.conversation_index:
        key = _conversation_index_root(root.conversation_index)
    if not key and root.content_hash:
        key = f"content:{root.content_hash}"
    if not key:
        key = root.subject_key
    if not key:
        participant_key = (
            ",".join(sorted(root.participants)) if root.participants else ""
        )
        date_key = root.date_sent.isoformat() if root.date_sent else ""
        sender_key = root.sender or ""
        composite = "|".join([p for p in [sender_key, participant_key, date_key] if p])
        key = composite or None
    if not key:
        key = str(root.email_id)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"thread_{digest[:32]}"


_BASE36_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def _base36_fixed(value: int, width: int) -> str:
    if value < 0:
        raise ValueError("base36 value must be >= 0")
    if width <= 0:
        raise ValueError("base36 width must be >= 1")
    if value == 0:
        return "0".rjust(width, "0")
    digits: list[str] = []
    v = value
    while v:
        v, rem = divmod(v, 36)
        digits.append(_BASE36_ALPHABET[rem])
    encoded = "".join(reversed(digits))
    if len(encoded) >= width:
        # If it doesn't fit, keep it unpadded (still deterministic); callers should ensure
        # a group-wide width that is sufficient for all indexes.
        return encoded
    return encoded.rjust(width, "0")


def _thread_path_compact(
    segments: list[int],
    *,
    width: int,
    max_len: int | None,
) -> str:
    path = "".join(_base36_fixed(seg, width) for seg in segments)
    if max_len is None or len(path) <= max_len:
        return path
    digest = hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]
    # Keep a stable prefix for sort locality, then add a deterministic suffix.
    keep = max(0, max_len - (1 + len(digest)))
    return f"{path[:keep]}~{digest}"


def _apply_thread_positions(
    nodes_by_id: dict[uuid.UUID, ThreadNode],
    updates: list[dict[str, Any]],
    decisions: dict[uuid.UUID, ThreadLinkDecision],
    *,
    thread_path_max_len: int | None,
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
        items_sorted = sorted(items, key=_node_sort_key)
        for idx, node in enumerate(items_sorted):
            update = update_map.get(node.email_id)
            if update is not None:
                update["thread_position"] = idx

        items_by_id = {node.email_id: node for node in items}
        children: dict[uuid.UUID, list[ThreadNode]] = {
            node.email_id: [] for node in items
        }
        roots: list[ThreadNode] = []
        for node in items:
            decision = decisions.get(node.email_id)
            parent_id = decision.parent_email_id if decision else None
            if parent_id and parent_id in items_by_id and parent_id != node.email_id:
                children[parent_id].append(node)
            else:
                roots.append(node)

        roots.sort(key=_node_sort_key)
        for key in children:
            children[key].sort(key=_node_sort_key)

        # Compute a fixed base36 width for this group, so lexical ordering is preserved.
        # Width is derived from the maximum sibling index (roots/children) in this group.
        max_index = 0
        if roots:
            max_index = max(max_index, len(roots) - 1)
        for node_id, kids in children.items():
            if kids:
                max_index = max(max_index, len(kids) - 1)
        width = 1
        while 36**width <= max_index:
            width += 1
        width = max(width, 1)

        max_len = thread_path_max_len

        for idx, root in enumerate(roots):
            stack: list[tuple[ThreadNode, list[int]]] = [(root, [idx])]
            while stack:
                node, segments = stack.pop()
                update = update_map.get(node.email_id)
                if update is not None:
                    update["thread_path"] = _thread_path_compact(
                        segments, width=width, max_len=max_len
                    )
                node_children = children.get(node.email_id, [])
                # Stack is LIFO; push in reverse for stable left-to-right traversal.
                for child_idx, child in reversed(list(enumerate(node_children))):
                    stack.append((child, [*segments, child_idx]))


def _break_parent_cycles(
    nodes_by_id: dict[uuid.UUID, ThreadNode],
    decisions: dict[uuid.UUID, ThreadLinkDecision],
) -> int:
    """Break cycles in the parent pointer graph deterministically.

    Threading should produce a forest (each node has 0..1 parent). Certain
    heuristic links can accidentally create cycles (A->B and B->A). Cycles
    make downstream processing non-terminating and are not valid thread
    structures, so we break them in a stable, explainable way.
    """

    parent_map: dict[uuid.UUID, uuid.UUID] = {}
    for node_id, decision in decisions.items():
        parent_id = decision.parent_email_id if decision else None
        if (
            parent_id
            and parent_id != node_id
            and parent_id in nodes_by_id
            and node_id in nodes_by_id
        ):
            parent_map[node_id] = parent_id

    state: dict[uuid.UUID, int] = {}  # 0=unvisited, 1=visiting, 2=done
    cycles_broken = 0

    ordered_nodes = sorted(nodes_by_id.values(), key=_node_sort_key)
    for node in ordered_nodes:
        start_id = node.email_id
        if state.get(start_id, 0) != 0:
            continue

        path: list[uuid.UUID] = []
        index: dict[uuid.UUID, int] = {}
        current = start_id

        while True:
            st = state.get(current, 0)
            if st == 2:
                break
            if st == 1:
                if current in index:
                    cycle = path[index[current] :]
                    if cycle:
                        root_id = min(
                            cycle, key=lambda cid: _node_sort_key(nodes_by_id[cid])
                        )
                        decision = decisions.get(root_id)
                        if decision and decision.parent_email_id:
                            old_parent = decision.parent_email_id
                            decisions[root_id] = ThreadLinkDecision(
                                parent_email_id=None,
                                methods=list(decision.methods) + ["CycleBreak"],
                                evidence={
                                    **(decision.evidence or {}),
                                    "cycle_break": {
                                        "removed_parent_email_id": str(old_parent),
                                        "cycle_email_ids": [str(cid) for cid in cycle],
                                    },
                                },
                                confidence=0.0,
                                alternatives=list(decision.alternatives),
                            )
                            parent_map.pop(root_id, None)
                            cycles_broken += 1
                break

            state[current] = 1
            index[current] = len(path)
            path.append(current)

            parent_id = parent_map.get(current)
            if not parent_id:
                break
            current = parent_id

        for cid in path:
            state[cid] = 2

    return cycles_broken


def _to_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if not value:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None
