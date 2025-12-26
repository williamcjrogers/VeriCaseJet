from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import get_db
from .models import ChronologyItem, EvidenceItem, EvidenceSpan, User
from .security import get_current_user
from .storage import presign_get, put_object
from .trace_context import ensure_chain_id, get_trace_context

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

router = APIRouter(prefix="/api/bundles", tags=["bundles"])


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_json(obj: Any) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


class BundleManifestRequest(BaseModel):
    case_id: str
    chronology_ids: list[str] | None = None
    include_quotes: bool = True


class BundleManifestResponse(BaseModel):
    bundle_id: str
    manifest_sha256: str
    manifest_key: str
    hashes_key: str
    manifest_url: str
    hashes_url: str


def _uuid_or_400(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid {field}")


@router.post("/manifest", response_model=BundleManifestResponse)
def create_bundle_manifest(
    payload: BundleManifestRequest, db: DbSession, user: CurrentUser  # noqa: ARG001
) -> BundleManifestResponse:
    case_uuid = _uuid_or_400(payload.case_id, "case_id")

    query = db.query(ChronologyItem).filter(ChronologyItem.case_id == case_uuid)
    if payload.chronology_ids:
        ids = [_uuid_or_400(i, "chronology_id") for i in payload.chronology_ids]
        query = query.filter(ChronologyItem.id.in_(ids))
    items = query.order_by(ChronologyItem.event_date.asc()).all()

    chain_id = ensure_chain_id(get_trace_context().chain_id)
    bundle_id = chain_id

    evidence_items_by_id: dict[str, EvidenceItem] = {}
    spans_by_uri: dict[str, EvidenceSpan] = {}

    def resolve_evidence_ref(ref: str) -> dict[str, Any]:
        if isinstance(ref, str) and ref.startswith("dep://"):
            span = spans_by_uri.get(ref)
            if span is None:
                span = (
                    db.query(EvidenceSpan).filter(EvidenceSpan.dep_uri == ref).first()
                )
                if span:
                    spans_by_uri[ref] = span
            if not span:
                return {"type": "dep", "dep_uri": ref, "status": "missing"}

            out = {
                "type": "dep",
                "dep_uri": span.dep_uri,
                "start_offset": span.start_offset,
                "end_offset": span.end_offset,
                "span_hash": span.span_hash,
                "normalized_text_hash": span.normalized_text_hash,
            }
            if payload.include_quotes:
                out["quote"] = span.quote
            return out

        # EvidenceItem UUID (best-effort)
        try:
            evidence_uuid = uuid.UUID(str(ref))
        except Exception:
            return {"type": "ref", "ref": str(ref), "status": "unparsed"}

        key = str(evidence_uuid)
        item = evidence_items_by_id.get(key)
        if item is None:
            item = (
                db.query(EvidenceItem).filter(EvidenceItem.id == evidence_uuid).first()
            )
            if item:
                evidence_items_by_id[key] = item
        if not item:
            return {"type": "evidence_item", "id": key, "status": "missing"}

        return {
            "type": "evidence_item",
            "id": str(item.id),
            "filename": item.filename,
            "file_hash": item.file_hash,
            "s3_bucket": item.s3_bucket,
            "s3_key": item.s3_key,
            "normalized_text_hash": item.normalized_text_hash,
        }

    manifest: dict[str, Any] = {
        "schema": "bundle_manifest.v1",
        "case_id": str(case_uuid),
        "bundle_id": bundle_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chronology": [
            {
                "chronology_item_id": str(it.id),
                "event_date": it.event_date.isoformat(),
                "title": it.title,
                "description": it.description,
                "evidence": [resolve_evidence_ref(r) for r in (it.evidence_ids or [])],
            }
            for it in items
        ],
    }

    manifest_bytes = _stable_json(manifest)
    manifest_sha256 = _sha256_hex(manifest_bytes)

    hashes_lines: list[str] = [
        f"manifest_sha256={manifest_sha256}",
        f"bundle_id={bundle_id}",
        f"case_id={case_uuid}",
    ]

    for dep_uri, span in sorted(spans_by_uri.items()):
        hashes_lines.append(f"dep_uri={dep_uri}")
        hashes_lines.append(f"  span_hash={span.span_hash}")
        hashes_lines.append(f"  normalized_text_hash={span.normalized_text_hash}")

    for eid, item in sorted(evidence_items_by_id.items()):
        hashes_lines.append(f"evidence_item_id={eid}")
        hashes_lines.append(f"  file_hash={item.file_hash}")
        if item.normalized_text_hash:
            hashes_lines.append(f"  normalized_text_hash={item.normalized_text_hash}")

    hashes_bytes = ("\n".join(hashes_lines) + "\n").encode("utf-8")

    prefix = f"bundle_mvp/{case_uuid}/{bundle_id}"
    manifest_key = f"{prefix}/bundle_manifest.json"
    hashes_key = f"{prefix}/hashes.txt"

    put_object(manifest_key, manifest_bytes, "application/json")
    put_object(hashes_key, hashes_bytes, "text/plain")

    return BundleManifestResponse(
        bundle_id=bundle_id,
        manifest_sha256=manifest_sha256,
        manifest_key=manifest_key,
        hashes_key=hashes_key,
        manifest_url=presign_get(
            manifest_key, expires=3600, response_disposition="attachment"
        ),
        hashes_url=presign_get(
            hashes_key, expires=3600, response_disposition="attachment"
        ),
    )
