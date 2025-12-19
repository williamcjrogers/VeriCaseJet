import logging
import time
from opensearchpy import OpenSearch, RequestsHttpConnection
from opensearchpy.exceptions import NotFoundError
from .config import settings

logger = logging.getLogger(__name__)


_EMAIL_INDEX_MAPPING_UPDATED = False


class _OpenSearchClient:
    """Thread-safe OpenSearch client singleton"""

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls._create_client()
        return cls._instance

    @staticmethod
    def _create_client():
        try:
            opensearch_user = getattr(settings, "OPENSEARCH_USER", "admin")
            opensearch_pass = getattr(settings, "OPENSEARCH_PASSWORD", "admin")

            return OpenSearch(
                hosts=[
                    {"host": settings.OPENSEARCH_HOST, "port": settings.OPENSEARCH_PORT}
                ],
                http_auth=(
                    (opensearch_user, opensearch_pass) if opensearch_user else None
                ),
                http_compress=True,
                use_ssl=settings.OPENSEARCH_USE_SSL,
                verify_certs=settings.OPENSEARCH_VERIFY_CERTS,
                connection_class=RequestsHttpConnection,
            )
        except Exception as e:
            logger.error(f"Failed to create OpenSearch client: {e}")
            raise


def client():
    return _OpenSearchClient.get_instance()


def ensure_index():
    body = {
        "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}},
        "mappings": {
            "properties": {
                "id": {"type": "keyword"},
                "filename": {"type": "text"},
                "title": {"type": "text"},
                "path": {"type": "keyword"},
                "owner": {"type": "keyword"},
                "content_type": {"type": "keyword"},
                "uploaded_at": {"type": "date"},
                "metadata": {"type": "object", "enabled": True},
                "text": {"type": "text", "analyzer": "english"},
            }
        },
    }
    # Wait for OpenSearch to be reachable and ensure index
    # In AWS mode, make this non-blocking to allow API to start even if OpenSearch is temporarily unavailable
    deadline = time.time() + 15  # Shorter timeout for faster startup
    last_err = None
    while time.time() < deadline:
        try:
            c = client()
            if not c.indices.exists(index=settings.OPENSEARCH_INDEX):
                c.indices.create(index=settings.OPENSEARCH_INDEX, body=body)
            logger.info("OpenSearch index '%s' is ready", settings.OPENSEARCH_INDEX)
            return
        except Exception as e:
            last_err = e
            time.sleep(1)

    # Log warning but don't crash - search features will be unavailable until OpenSearch is accessible
    if last_err:
        logger.warning(
            "Failed to initialize OpenSearch index (search will be unavailable): %s",
            last_err,
        )
        logger.warning(
            "API will start anyway - OpenSearch features disabled until connectivity is restored"
        )


def index_document(doc):
    body = {
        "id": str(doc["id"]),
        "filename": doc["filename"],
        "title": doc.get("title"),
        "path": doc.get("path"),
        "owner": doc.get("owner_user_id"),
        "content_type": doc.get("content_type"),
        "uploaded_at": doc.get("created_at"),
        "metadata": doc.get("metadata", {}),
        "text": doc.get("text", ""),
    }
    client().index(
        index=settings.OPENSEARCH_INDEX, id=str(doc["id"]), body=body, refresh=True
    )


def search(
    query: str, size: int = 25, path_prefix: str | None = None, owner: str | None = None
):
    must = [
        {
            "multi_match": {
                "query": query,
                "fields": ["text^3", "filename", "title", "metadata.*"],
            }
        }
    ]
    if path_prefix:
        must.append({"prefix": {"path": path_prefix}})
    if owner:
        must.append({"term": {"owner": owner}})
    dsl = {
        "size": size,
        "query": {"bool": {"must": must}},
        "highlight": {
            "fields": {
                "text": {
                    "fragment_size": 200,
                    "number_of_fragments": 3,
                    "no_match_size": 200,
                }
            },
            "max_analyzed_offset": 1000000,
        },
    }
    try:
        return client().search(index=settings.OPENSEARCH_INDEX, body=dsl)
    except Exception as e:
        logger.warning(
            "Search with highlighting failed, retrying without highlights: %s", e
        )
        # Retry without highlighting if it fails
        dsl_no_highlight = {"size": size, "query": {"bool": {"must": must}}}
        return client().search(index=settings.OPENSEARCH_INDEX, body=dsl_no_highlight)


def delete_document(doc_id: str):
    try:
        client().delete(index=settings.OPENSEARCH_INDEX, id=doc_id, ignore=[404])
    except NotFoundError:
        return
    except Exception:
        logger.exception("Failed to delete document %s from OpenSearch", doc_id)


def search_emails(
    query: str,
    size: int = 25,
    case_id: str | None = None,
    project_id: str | None = None,
    sender: str | None = None,
    recipient: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    has_attachments: bool | None = None,
):
    """
    Full-text search for emails with advanced filtering.
    """
    must = [
        {
            "multi_match": {
                "query": query,
                "fields": [
                    "subject^3",
                    "body^2",
                    "sender_name",
                    "sender_email",
                    "recipients",
                ],
            }
        }
    ]

    if case_id:
        must.append({"term": {"case_id": case_id}})
    if project_id:
        must.append({"term": {"project_id": project_id}})
    if sender:
        must.append(
            {
                "bool": {
                    "should": [
                        {"match": {"sender_email": sender}},
                        {"match": {"sender_name": sender}},
                    ]
                }
            }
        )
    if recipient:
        must.append({"match": {"recipients": recipient}})

    if date_from or date_to:
        range_filter = {}
        if date_from:
            range_filter["gte"] = date_from
        if date_to:
            range_filter["lte"] = date_to
        must.append({"range": {"date_sent": range_filter}})

    if has_attachments is not None:
        must.append({"term": {"has_attachments": has_attachments}})

    dsl = {
        "size": size,
        "query": {"bool": {"must": must}},
        "highlight": {
            "fields": {
                "subject": {},
                "body": {
                    "fragment_size": 150,
                    "number_of_fragments": 3,
                    "no_match_size": 150,
                },
            }
        },
        "sort": [{"date_sent": {"order": "desc"}}],
    }

    try:
        return client().search(index="emails", body=dsl)
    except Exception as e:
        logger.error(f"Email search failed: {e}")
        # Fallback to simple search if complex query fails
        try:
            simple_dsl = {
                "size": size,
                "query": {
                    "multi_match": {"query": query, "fields": ["subject", "body"]}
                },
            }
            return client().search(index="emails", body=simple_dsl)
        except Exception as e2:
            logger.error(f"Fallback email search failed: {e2}")
            raise


# ========================================
# EMAIL INDEXING FOR PST ANALYSIS
# ========================================


def index_email_in_opensearch(
    *,
    email_id: str,
    subject: str,
    body_text: str,
    sender_email: str,
    sender_name: str,
    recipients: list,
    case_id: str | None = None,
    project_id: str | None = None,
    thread_id: str | None = None,
    thread_group_id: str | None = None,
    message_id: str | None = None,
    date_sent: str | None = None,
    has_attachments: bool = False,
    matched_stakeholders: list | None = None,
    matched_keywords: list | None = None,
    body_text_clean: str | None = None,
    content_hash: str | None = None,
):
    """Index email message for full-text search"""
    try:
        email_index = "emails"

        # Ensure emails index exists
        c = client()
        if not c.indices.exists(index=email_index):
            c.indices.create(
                index=email_index,
                body={
                    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                    "mappings": {
                        "properties": {
                            "id": {"type": "keyword"},
                            "case_id": {"type": "keyword"},
                            "project_id": {"type": "keyword"},
                            "type": {"type": "keyword"},
                            "thread_id": {"type": "keyword"},
                            "thread_group_id": {"type": "keyword"},
                            "message_id": {"type": "keyword"},
                            "subject": {"type": "text", "analyzer": "english"},
                            "body": {"type": "text", "analyzer": "english"},
                            "body_clean": {"type": "text", "analyzer": "english"},
                            "sender_email": {"type": "keyword"},
                            "sender_name": {"type": "text"},
                            "recipients": {"type": "keyword"},
                            "date_sent": {"type": "date"},
                            "has_attachments": {"type": "boolean"},
                            "matched_stakeholders": {"type": "keyword"},
                            "matched_keywords": {"type": "keyword"},
                            "content_hash": {"type": "keyword"},
                        }
                    },
                },
            )
        else:
            # Backwards-compatible schema evolution: add missing fields if index already exists.
            # IMPORTANT: Avoid doing this for every single email; it can be costly during reindex.
            global _EMAIL_INDEX_MAPPING_UPDATED
            if not _EMAIL_INDEX_MAPPING_UPDATED:
                try:
                    c.indices.put_mapping(
                        index=email_index,
                        body={
                            "properties": {
                                "project_id": {"type": "keyword"},
                                "thread_id": {"type": "keyword"},
                                "thread_group_id": {"type": "keyword"},
                                "message_id": {"type": "keyword"},
                            }
                        },
                    )
                except Exception as e:
                    logger.debug("Failed to update emails index mapping: %s", e)
                _EMAIL_INDEX_MAPPING_UPDATED = True

        recipients_norm: list[str] = []
        if recipients:
            seen: set[str] = set()
            for r in recipients:
                val: str | None = None
                if isinstance(r, str):
                    val = r
                elif isinstance(r, dict):
                    # Support both {"email": ...} and other common keys.
                    val = r.get("email") or r.get("address") or r.get("value")
                if not val:
                    continue
                v = val.strip().lower()
                if not v:
                    continue
                if v in seen:
                    continue
                seen.add(v)
                recipients_norm.append(v)

        doc = {
            "id": email_id,
            "case_id": case_id,
            "project_id": project_id,
            "type": "email",
            "thread_id": thread_id,
            "thread_group_id": thread_group_id,
            "message_id": message_id,
            "subject": subject,
            "body": body_text[:50000] if body_text else "",
            "body_clean": (body_text_clean or body_text or "")[:50000],
            "sender_email": sender_email,
            "sender_name": sender_name,
            "recipients": recipients_norm,
            "date_sent": date_sent,
            "has_attachments": has_attachments,
            "matched_stakeholders": matched_stakeholders or [],
            "matched_keywords": matched_keywords or [],
            "content_hash": content_hash,
        }

        c.index(index=email_index, id=email_id, body=doc)

    except Exception as e:
        logger.error(f"Failed to index email {email_id}: {e}")
