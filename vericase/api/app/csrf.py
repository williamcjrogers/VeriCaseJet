import logging
import re
from threading import RLock

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

bearer = HTTPBearer(auto_error=False)

# In-memory store keyed by bearer token -> CSRF token.
# This is intentionally simple and process-local.
CSRF_TOKEN_STORE: dict[str, str] = {}
CSRF_LOCK = RLock()
CSRF_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def verify_csrf_token(
    request: Request,
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> None:
    """Verify CSRF token for state-changing requests.

    Requires valid authentication credentials and a per-bearer-token CSRF token.

    Notes:
    - The first time a bearer token is seen, we bind it to the provided CSRF token.
    - Subsequent requests must provide the same CSRF token.
    """

    if not creds:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    csrf_header = request.headers.get("X-CSRF-Token")

    if not csrf_header:
        raise HTTPException(status_code=403, detail="Missing CSRF token")

    if not CSRF_PATTERN.match(csrf_header):
        raise HTTPException(status_code=403, detail="Invalid CSRF token format")

    token = creds.credentials

    with CSRF_LOCK:
        stored = CSRF_TOKEN_STORE.get(token)
        if stored is None:
            CSRF_TOKEN_STORE[token] = csrf_header
            if len(CSRF_TOKEN_STORE) > 10000:
                # Prune oldest entry to avoid unbounded growth
                CSRF_TOKEN_STORE.pop(next(iter(CSRF_TOKEN_STORE)))
        elif stored != csrf_header:
            raise HTTPException(status_code=403, detail="CSRF token mismatch")
