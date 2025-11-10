import logging
import time
from functools import lru_cache
from html import escape
from typing import Optional, Dict, Any, MutableMapping
from opensearchpy import OpenSearch, RequestsHttpConnection  # type: ignore[import-not-found]
from opensearchpy.exceptions import NotFoundError  # type: ignore[import-not-found]
from .config import settings

logger = logging.getLogger(__name__)

CACHE_TTL = 300  # 5 minutes cache for search results
HIGHLIGHT_PRE = "__HIGHLIGHT_START__"
HIGHLIGHT_POST = "__HIGHLIGHT_END__"


class _SearchResultCache:
    """Simple TTL cache for search responses."""

    def __init__(self, ttl: int, max_entries: int = 100) -> None:
        self.ttl = ttl
        self.max_entries = max_entries
        self._store: Dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if not entry:
            return None
        value, timestamp = entry
        if time.time() - timestamp >= self.ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (value, time.time())
        if len(self._store) > self.max_entries:
            # Remove oldest entries
            sorted_items = sorted(self._store.items(), key=lambda item: item[1][1])
            for old_key, _ in sorted_items[: max(1, self.max_entries // 5)]:
                self._store.pop(old_key, None)


@lru_cache(maxsize=1)
def _cache_manager() -> _SearchResultCache:
    return _SearchResultCache(ttl=CACHE_TTL, max_entries=100)

def client():
    """Get or create OpenSearch client with connection pooling"""
    return _client_singleton()


@lru_cache(maxsize=1)
def _client_singleton() -> OpenSearch:
    try:
        instance = OpenSearch(
            hosts=[{"host": settings.OPENSEARCH_HOST, "port": settings.OPENSEARCH_PORT}],
            http_auth=('admin', 'admin'),
            http_compress=True,
            use_ssl=settings.OPENSEARCH_USE_SSL,
            verify_certs=settings.OPENSEARCH_VERIFY_CERTS,
            connection_class=RequestsHttpConnection,
            maxsize=25,
            max_retries=3,
            retry_on_timeout=True,
            timeout=30
        )
        logger.info("OpenSearch client created with connection pooling")
        return instance
    except Exception as exc:
        logger.error("Failed to create OpenSearch client: %s", exc)
        raise

def _get_cache_key(query: str, size: int, path_prefix: Optional[str], owner: Optional[str]) -> str:
    """Generate cache key for search results"""
    return f"{query}:{size}:{path_prefix}:{owner}"

def _get_cached_result(cache_key: str) -> Optional[Any]:
    """Get cached search result if not expired"""
    return _cache_manager().get(cache_key)

def _set_cached_result(cache_key: str, result: Any):
    """Cache search result with timestamp"""
    _cache_manager().set(cache_key, result)

def _sanitize_highlights(result: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Escape highlight fragments to prevent unintended HTML rendering."""
    hits_container = result.get("hits")
    if not isinstance(hits_container, dict):
        return result
    hits = hits_container.get("hits") or []
    if not isinstance(hits, list):
        return result
    for hit in hits:
        highlight = hit.get("highlight")
        if not isinstance(highlight, dict):
            continue
        for field, fragments in highlight.items():
            if not isinstance(fragments, list):
                continue
            safe_fragments = []
            for fragment in fragments:
                safe = escape(fragment or "", quote=False)
                safe = safe.replace(HIGHLIGHT_PRE, "<mark>").replace(HIGHLIGHT_POST, "</mark>")
                safe_fragments.append(safe)
            highlight[field] = safe_fragments
    return result


def ensure_index():
    """
    Ensure OpenSearch index exists with proper schema.
    
    Non-blocking: Will log warning and continue if OpenSearch is unavailable,
    allowing the API to start even when search is temporarily down.
    """
    index_body = {
        "settings": {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 0
            }
        },
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
                "text": {"type": "text", "analyzer": "english"}
            }
        }
    }
    
    # Wait for OpenSearch to be reachable and ensure index
    # In AWS mode, make this non-blocking to allow API to start even if OpenSearch is temporarily unavailable
    deadline = time.time() + 15  # Shorter timeout for faster startup
    last_err = None
    
    while time.time() < deadline:
        try:
            c = client()
            if not c.indices.exists(settings.OPENSEARCH_INDEX):
                c.indices.create(index=settings.OPENSEARCH_INDEX, body=index_body)
            logger.info("OpenSearch index '%s' is ready", settings.OPENSEARCH_INDEX)
            return
        except Exception as e:
            last_err = e
            time.sleep(1)
    
    # Log warning but don't crash - search features will be unavailable until OpenSearch is accessible
    if last_err:
        logger.warning("Failed to initialize OpenSearch index (search will be unavailable): %s", last_err)
        logger.warning("API will start anyway - OpenSearch features disabled until connectivity is restored")
def index_document(doc):
    """Index a document in OpenSearch for full-text search"""
    try:
        body = {
            "id": str(doc["id"]),
            "filename": doc["filename"],
            "title": doc.get("title"),
            "path": doc.get("path"),
            "owner": doc.get("owner_user_id"),
            "content_type": doc.get("content_type"),
            "uploaded_at": doc.get("created_at"),
            "metadata": doc.get("metadata", {}),
            "text": doc.get("text", "")
        }
        client().index(
            index=settings.OPENSEARCH_INDEX,
            id=str(doc["id"]),
            body=body,
            refresh=True
        )
        logger.debug(f"Indexed document {doc['id']}")
    except Exception as e:
        logger.error(f"Failed to index document {doc.get('id')}: {e}")
        raise
def search(query: str, size: int=25, path_prefix: str|None=None, owner: str|None=None):
    """Search documents with caching for performance"""
    # Check cache first
    cache_key = _get_cache_key(query, size, path_prefix, owner)
    cached_result = _get_cached_result(cache_key)
    if cached_result is not None:
        logger.debug(f"Returning cached search result for query: {query}")
        return cached_result
    
    # Build query
    must = [
        {
            "multi_match": {
                "query": query,
                "fields": ["text^3", "filename", "title", "metadata.*"]
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
            "pre_tags": [HIGHLIGHT_PRE],
            "post_tags": [HIGHLIGHT_POST],
            "fields": {
                "text": {
                    "fragment_size": 200,
                    "number_of_fragments": 3,
                    "no_match_size": 200
                }
            },
            "max_analyzed_offset": 1000000
        }
    }
    
    # Execute search with error handling
    try:
        raw_result = client().search(index=settings.OPENSEARCH_INDEX, body=dsl)
        result = _sanitize_highlights(raw_result)
        # Cache successful result
        _set_cached_result(cache_key, result)
        return result
    except Exception as e:
        logger.warning("Search with highlighting failed, retrying without highlights: %s", e)
        # Retry without highlighting if it fails
        try:
            dsl_no_highlight = {"size": size, "query": {"bool": {"must": must}}}
            raw_result = client().search(index=settings.OPENSEARCH_INDEX, body=dsl_no_highlight)
            result = _sanitize_highlights(raw_result)
            # Cache successful result
            _set_cached_result(cache_key, result)
            return result
        except Exception as retry_error:
            logger.error(f"Search failed completely: {retry_error}")
            # Return empty result instead of crashing
            return {"hits": {"total": {"value": 0}, "hits": []}}

def delete_document(doc_id: str):
    """Delete a document from the OpenSearch index"""
    try:
        client().delete(index=settings.OPENSEARCH_INDEX, id=doc_id, ignore=[404])
        logger.debug(f"Deleted document {doc_id} from search index")
    except NotFoundError:
        logger.debug(f"Document {doc_id} not found in search index (already deleted)")
        return
    except Exception as e:
        logger.exception("Failed to delete document %s from OpenSearch", doc_id)
        # Don't raise - allow document deletion to proceed even if search index update fails
