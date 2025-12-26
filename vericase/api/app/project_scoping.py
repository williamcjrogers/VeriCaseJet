"""Project/case scoping helpers for PST ingestion.

Goal: deterministically block "other project" emails during PST processing so
attachments from unrelated work cannot leak into the current case/project.

This module is intentionally lightweight (no external deps) and provides both:
- a pure-Python matcher (unit testable)
- a DB-backed builder to derive known project/case names
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import uuid
from typing import Any, Iterable


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _normalize_phrase(value: str) -> str:
    """Lowercase + replace non-alphanumerics with single spaces."""

    cleaned = _NON_ALNUM_RE.sub(" ", value.lower()).strip()
    cleaned = " ".join(cleaned.split())
    return cleaned


def _normalize_text(value: str | None) -> str:
    if not value:
        return " "
    phrase = _normalize_phrase(value)
    return f" {phrase} " if phrase else " "


def _iter_nonempty(values: Iterable[str | None]) -> Iterable[str]:
    for v in values:
        if not v:
            continue
        s = str(v).strip()
        if s:
            yield s


@dataclass(frozen=True)
class ScopeMatcher:
    """Detect whether an email appears to belong to a different project/case."""

    current_terms: tuple[str, ...]
    other_terms: tuple[tuple[str, str], ...]  # (normalized_term, label)

    @classmethod
    def from_labels(
        cls,
        current_labels: Iterable[str | None],
        other_labels: Iterable[str | None],
    ) -> "ScopeMatcher":
        current_norm = {
            _normalize_phrase(v) for v in _iter_nonempty(current_labels) if v
        }
        current_norm = {v for v in current_norm if v}

        other_map: dict[str, str] = {}
        for label in _iter_nonempty(other_labels):
            term = _normalize_phrase(label)
            if not term or term in current_norm:
                continue
            other_map.setdefault(term, label)

        # Match longer phrases first to reduce accidental substring matches.
        other_sorted = sorted(
            other_map.items(), key=lambda kv: len(kv[0]), reverse=True
        )

        return cls(
            current_terms=tuple(sorted(current_norm, key=len, reverse=True)),
            other_terms=tuple(other_sorted),
        )

    def detect_other_project(
        self,
        subject: str | None,
        folder_path: str | None = None,
        body_preview: str | None = None,
        *,
        allow_current_terms: bool = True,
    ) -> str | None:
        """Return the matched other-project label, if any."""

        haystack = (
            _normalize_text(subject)
            + _normalize_text(folder_path)
            + _normalize_text(body_preview)
        )

        # If the current project is mentioned anywhere, do not exclude.
        if allow_current_terms:
            for term in self.current_terms:
                if f" {term} " in haystack:
                    return None

        for term, label in self.other_terms:
            if f" {term} " in haystack:
                return label

        return None


def build_scope_matcher(
    db: Any,
    *,
    case_id: str | uuid.UUID | None = None,
    project_id: str | uuid.UUID | None = None,
) -> ScopeMatcher:
    """Build a ScopeMatcher from the known cases/projects in the database."""

    from .models import Case, Project

    case_uuid = None
    project_uuid = None
    try:
        if case_id:
            case_uuid = (
                case_id if isinstance(case_id, uuid.UUID) else uuid.UUID(str(case_id))
            )
    except Exception:
        case_uuid = None
    try:
        if project_id:
            project_uuid = (
                project_id
                if isinstance(project_id, uuid.UUID)
                else uuid.UUID(str(project_id))
            )
    except Exception:
        project_uuid = None

    current_labels: list[str] = []
    if case_uuid:
        case = db.query(Case).filter(Case.id == case_uuid).first()
        if case:
            current_labels.extend(
                list(
                    _iter_nonempty(
                        [
                            case.name,
                            case.project_name,
                            case.case_number,
                            case.case_id_custom,
                        ]
                    )
                )
            )
            if getattr(case, "project_id", None):
                project_uuid = project_uuid or case.project_id

    if project_uuid:
        project = db.query(Project).filter(Project.id == project_uuid).first()
        if project:
            current_labels.extend(
                list(
                    _iter_nonempty(
                        [
                            getattr(project, "project_name", None),
                            getattr(project, "name", None),
                            getattr(project, "project_code", None),
                        ]
                    )
                )
            )

    other_labels: list[str] = []
    try:
        for row in db.query(Project).all():
            other_labels.extend(
                list(
                    _iter_nonempty(
                        [
                            getattr(row, "project_name", None),
                            getattr(row, "name", None),
                            getattr(row, "project_code", None),
                        ]
                    )
                )
            )
    except Exception:
        pass
    try:
        for row in db.query(Case).all():
            other_labels.extend(
                list(
                    _iter_nonempty(
                        [
                            row.name,
                            row.project_name,
                            row.case_number,
                            row.case_id_custom,
                        ]
                    )
                )
            )
    except Exception:
        pass

    return ScopeMatcher.from_labels(
        current_labels=current_labels, other_labels=other_labels
    )
