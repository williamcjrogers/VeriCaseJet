"""
Deterministic email deduplication with evidence-grade decision logging.

Deduplication tiers (strict order):
  A) Message-ID exact match
  B) Strict content hash
  C) Relaxed content hash
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session, load_only

from .models import EmailAttachment, EmailMessage, EmailDedupeDecision

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DedupeConfig:
    quoted_anchor_lines: int = 6


@dataclass
class DedupeStats:
    emails_total: int = 0
    duplicates_found: int = 0
    groups_matched: int = 0
    decisions_recorded: int = 0


@dataclass
class EmailFingerprint:
    email_id: uuid.UUID
    message_id_norm: str | None
    strict_hash: str | None
    relaxed_hash: str | None
    quoted_hash: str | None
    attachments: list[str]
    body_len: int
    has_body: bool
    has_attachments: bool
    date_sent: datetime | None


_SUBJECT_PREFIX_RE = re.compile(
    r"^\s*(?:re|fw|fwd|aw|sv|wg|tr|fs)\s*:\s*", re.IGNORECASE
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

_SIGNATURE_SPLIT_RE = re.compile(
    r"(?mi)^\s*(--|__+|sent from my|sent via|kind regards|best regards|regards|thanks|thank you)\b"
)

_DISCLAIMER_RE = re.compile(
    r"(?i)(caution:\s*external email|confidential|disclaimer|legal notice|do not click links)"
)


def dedupe_emails(
    db: Session,
    *,
    case_id: uuid.UUID | str | None = None,
    project_id: uuid.UUID | str | None = None,
    pst_file_id: uuid.UUID | str | None = None,
    config: DedupeConfig | None = None,
    run_id: str | None = None,
) -> DedupeStats:
    case_uuid = _to_uuid(case_id)
    project_uuid = _to_uuid(project_id)
    pst_uuid = _to_uuid(pst_file_id)
    query = db.query(EmailMessage).options(
        load_only(
            EmailMessage.id,
            EmailMessage.message_id,
            EmailMessage.subject,
            EmailMessage.sender_email,
            EmailMessage.sender_name,
            EmailMessage.recipients_to,
            EmailMessage.recipients_cc,
            EmailMessage.recipients_bcc,
            EmailMessage.date_sent,
            EmailMessage.date_received,
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
    stats = DedupeStats(emails_total=len(emails))
    if not emails:
        return stats

    email_ids = [email.id for email in emails]
    attachments_map = _load_attachment_hashes(db, email_ids)
    cfg = config or DedupeConfig()

    # Reset prior dedupe flags and decisions for this scope
    db.query(EmailDedupeDecision).filter(
        EmailDedupeDecision.loser_email_id.in_(email_ids)
        | EmailDedupeDecision.winner_email_id.in_(email_ids)
    ).delete(synchronize_session=False)
    db.query(EmailMessage).filter(EmailMessage.id.in_(email_ids)).update(
        {
            EmailMessage.is_duplicate: False,
            EmailMessage.canonical_email_id: None,
            EmailMessage.dedupe_level: None,
        },
        synchronize_session=False,
    )

    fingerprints: dict[uuid.UUID, EmailFingerprint] = {}
    message_id_index: dict[str, list[uuid.UUID]] = {}
    strict_index: dict[str, list[uuid.UUID]] = {}
    relaxed_index: dict[str, list[uuid.UUID]] = {}

    for email in emails:
        attachments = attachments_map.get(email.id, [])
        fp = _fingerprint_email(email, attachments, cfg)
        fingerprints[email.id] = fp
        if fp.message_id_norm:
            message_id_index.setdefault(fp.message_id_norm, []).append(email.id)
        if fp.strict_hash:
            strict_index.setdefault(fp.strict_hash, []).append(email.id)
        if fp.relaxed_hash:
            relaxed_index.setdefault(fp.relaxed_hash, []).append(email.id)

    decisions: list[EmailDedupeDecision] = []
    updates: list[dict[str, Any]] = []
    marked_duplicates: set[uuid.UUID] = set()

    def _mark_group(ids: list[uuid.UUID], level: str, match_key: str) -> None:
        nonlocal decisions, updates, marked_duplicates, stats
        if len(ids) < 2:
            return
        winner_id, ranks = _select_winner(ids, emails, attachments_map, fingerprints)
        if not winner_id:
            return
        stats.groups_matched += 1
        for loser_id in ids:
            if loser_id == winner_id or loser_id in marked_duplicates:
                continue
            fp = fingerprints[loser_id]
            alternatives = [
                {
                    "candidate_email_id": str(candidate_id),
                    "reason": "duplicate_group",
                }
                for candidate_id in ids
                if candidate_id != loser_id
            ]
            decisions.append(
                EmailDedupeDecision(
                    winner_email_id=winner_id,
                    loser_email_id=loser_id,
                    level=level,
                    match_type=match_key,
                    strict_hash=fp.strict_hash,
                    relaxed_hash=fp.relaxed_hash,
                    quoted_hash=fp.quoted_hash,
                    evidence={
                        "winner_rank": ranks.get(winner_id),
                        "loser_rank": ranks.get(loser_id),
                    },
                    alternatives=alternatives,
                    run_id=run_id,
                )
            )
            updates.append(
                {
                    "id": loser_id,
                    "is_duplicate": True,
                    "canonical_email_id": winner_id,
                    "dedupe_level": level,
                }
            )
            marked_duplicates.add(loser_id)
            stats.duplicates_found += 1

    # Level A: Message-ID duplicates
    for message_id, ids in message_id_index.items():
        active_ids = [eid for eid in ids if eid not in marked_duplicates]
        _mark_group(active_ids, "A", "message_id")

    # Level B: Strict hash duplicates
    for strict_hash, ids in strict_index.items():
        active_ids = [eid for eid in ids if eid not in marked_duplicates]
        _mark_group(active_ids, "B", "strict_hash")

    # Level C: Relaxed hash duplicates
    for relaxed_hash, ids in relaxed_index.items():
        active_ids = [eid for eid in ids if eid not in marked_duplicates]
        _mark_group(active_ids, "C", "relaxed_hash")

    if updates:
        db.bulk_update_mappings(EmailMessage, updates)
    if decisions:
        db.bulk_save_objects(decisions)
    db.commit()

    stats.decisions_recorded = len(decisions)
    return stats


def _load_attachment_hashes(
    db: Session, email_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    if not email_ids:
        return {}
    rows = (
        db.query(EmailAttachment.email_message_id, EmailAttachment.attachment_hash)
        .filter(EmailAttachment.email_message_id.in_(email_ids))
        .all()
    )
    attachments: dict[uuid.UUID, list[str]] = {}
    for email_id, attachment_hash in rows:
        if not email_id or not attachment_hash:
            continue
        attachments.setdefault(email_id, []).append(str(attachment_hash))
    for key in attachments:
        attachments[key] = sorted(set(attachments[key]))
    return attachments


def _fingerprint_email(
    email: EmailMessage, attachments: list[str], cfg: DedupeConfig
) -> EmailFingerprint:
    message_id_norm = _normalize_message_id(email.message_id)
    subject_key = _normalize_subject(email.subject)
    body_clean = email.body_text_clean or ""
    body_clean = _normalize_text(body_clean)
    relaxed_body = _normalize_text(_strip_signature(body_clean))
    quoted_hash = _hash_text(
        _extract_quoted_anchor(email.body_text, cfg.quoted_anchor_lines)
    )

    strict_hash = _hash_payload(
        {
            "body": body_clean,
            "from": _norm_addr(email.sender_email),
            "to": _norm_list(email.recipients_to),
            "cc": _norm_list(email.recipients_cc),
            "bcc": _norm_list(email.recipients_bcc),
            "subject": subject_key or "",
            "date": _format_dt(email.date_sent),
            "attachments": attachments,
        }
    )
    relaxed_hash = _hash_payload(
        {
            "body": relaxed_body,
            "from": _norm_addr(email.sender_email),
            "to": _norm_list(email.recipients_to),
            "cc": _norm_list(email.recipients_cc),
            "bcc": _norm_list(email.recipients_bcc),
            "subject": subject_key or "",
            "attachments": attachments,
        }
    )

    return EmailFingerprint(
        email_id=email.id,
        message_id_norm=message_id_norm,
        strict_hash=strict_hash,
        relaxed_hash=relaxed_hash,
        quoted_hash=quoted_hash,
        attachments=attachments,
        body_len=len(body_clean),
        has_body=bool(body_clean),
        has_attachments=bool(attachments),
        date_sent=email.date_sent,
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


def _normalize_subject(subject: str | None) -> str | None:
    if not subject:
        return None
    s = subject.strip()
    if not s:
        return None
    s = re.sub(r"^\s*\[[^\]]{0,80}\]\s*", "", s)
    while True:
        new_s = _SUBJECT_PREFIX_RE.sub("", s)
        if new_s == s:
            break
        s = new_s
    s = s.strip()
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s or None


def _normalize_text(text: str) -> str:
    cleaned = text.replace("\x00", " ").replace("\u0000", " ")
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _DISCLAIMER_RE.sub(" ", cleaned)
    cleaned = re.sub(r"[^\S\n]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


def _strip_signature(text: str) -> str:
    if not text:
        return text
    parts = _SIGNATURE_SPLIT_RE.split(text, maxsplit=1)
    return parts[0].strip() if parts else text


def _extract_quoted_anchor(text: str | None, max_lines: int) -> str:
    if not text:
        return ""
    match = _REPLY_SPLIT_RE.search(text)
    if match:
        block = text[match.start() :]
    else:
        quoted_lines = [
            line for line in text.splitlines() if line.lstrip().startswith(">")
        ]
        block = "\n".join(quoted_lines)
    if not block:
        return ""
    lines = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(">"):
            stripped = stripped.lstrip(">").strip()
        if stripped:
            lines.append(stripped)
        if len(lines) >= max_lines:
            break
    return "\n".join(lines)


def _hash_text(text: str) -> str | None:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_payload(payload: dict[str, Any]) -> str | None:
    try:
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _norm_addr(value: str | None) -> str:
    return (value or "").strip().lower()


def _norm_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    cleaned = [str(v).strip().lower() for v in values if v]
    return sorted(set(cleaned))


def _format_dt(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _select_winner(
    ids: list[uuid.UUID],
    emails: Iterable[EmailMessage],
    attachments_map: dict[uuid.UUID, list[str]],
    fingerprints: dict[uuid.UUID, EmailFingerprint],
) -> tuple[uuid.UUID | None, dict[uuid.UUID, tuple]]:
    email_map = {email.id: email for email in emails}
    ranks: dict[uuid.UUID, tuple] = {}
    for email_id in ids:
        email = email_map.get(email_id)
        fp = fingerprints.get(email_id)
        if not email or not fp:
            continue
        attachments = attachments_map.get(email_id, [])
        date_key = email.date_sent or datetime.max
        if date_key.tzinfo is None:
            date_key = date_key.replace(tzinfo=timezone.utc)
        date_score = (
            date_key.timestamp()
            if date_key != datetime.max.replace(tzinfo=timezone.utc)
            else float("inf")
        )
        rank = (
            1 if fp.has_body else 0,
            fp.body_len,
            1 if fp.has_attachments else 0,
            len(attachments),
            1 if fp.message_id_norm else 0,
            date_score,
            str(email.id),
        )
        ranks[email_id] = rank
    if not ranks:
        return None, {}
    winner_id = min(
        ranks,
        key=lambda eid: (
            -ranks[eid][0],
            -ranks[eid][1],
            -ranks[eid][2],
            -ranks[eid][3],
            -ranks[eid][4],
            ranks[eid][5],
            ranks[eid][6],
        ),
    )
    return winner_id, ranks


def _to_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if not value:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None
