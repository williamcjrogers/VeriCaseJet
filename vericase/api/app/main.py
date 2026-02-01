import logging
import uuid
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Query, Body, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select, text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse as StarletteRedirect
import os


# Filter out favicon requests from access logs
class FaviconFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, "args") and record.args:
            # Check if this is a favicon request in uvicorn access log
            args = record.args
            if isinstance(args, tuple) and len(args) >= 3:
                path = str(args[2]) if len(args) > 2 else ""
                if "favicon" in path.lower():
                    return False
        # Also check message
        msg = (
            record.getMessage()
            if hasattr(record, "getMessage")
            else str(getattr(record, "msg", ""))
        )
        if "favicon" in msg.lower():
            return False
        return True


# Apply filter to uvicorn access logger
uvicorn_access_logger = logging.getLogger("uvicorn.access")
uvicorn_access_logger.addFilter(FaviconFilter())

# Import production config helper if in production
if os.getenv("AWS_EXECUTION_ENV") or os.getenv("AWS_REGION"):
    from .config_production import update_production_config

    update_production_config()

from .config import settings
from .db import Base, engine
from .models import (
    Document,
    User,
    ShareLink,
    Folder,
    UserRole,
)
from .storage import (
    presign_get,
    get_object,
    put_object,
    delete_object,
)
from .search import delete_document as os_delete
from .security import get_db, current_user, hash_password, verify_password, sign_token
from .security_enhanced import (
    generate_token,
    is_account_locked,
    handle_failed_login,
    handle_successful_login,
)
from .watermark import build_watermarked_pdf, normalize_watermark_text
from .email_service import email_service
from pydantic import BaseModel
from .users import router as users_router
from .sharing import router as sharing_router
from .favorites import router as favorites_router
from .versioning import router as versioning_router
from .ai_intelligence import router as ai_router
from .ai_orchestrator import router as orchestrator_router
from .ai_chat import router as ai_chat_router  # AI Chat with multi-model research
from .admin_approval import (
    router as admin_approval_router,
)  # Admin user approval system
from .admin_settings import router as admin_settings_router  # Admin settings management
from .deployment_tools import router as deployment_router  # SSH deployment tools
from .intelligent_config import router as intelligent_config_router
from .cases import router as cases_router
from .simple_cases import router as simple_cases_router
from .programmes import router as programmes_router
from .correspondence.routes import (
    router as correspondence_router,
)  # PST analysis endpoints
from .ai_refinement import (
    router as ai_refinement_router,
)  # Enhanced AI refinement with intelligent questioning
from .auth_enhanced import router as auth_enhanced_router  # Enhanced authentication
from .evidence_repository import router as evidence_router  # Evidence repository
from .ocr_feedback import router as ocr_feedback_router  # OCR feedback
from .vericase_analysis import (
    router as vericase_analysis_router,
)  # VeriCase Analysis (flagship orchestrator)
from .vericase_rebuttal import (
    router as vericase_rebuttal_router,
)  # VeriCase Rebuttal (opposing document rebuttal)
from .claims_module import (
    router as claims_router,
)  # Contentious Matters and Heads of Claim
from .dashboard_api import router as dashboard_router  # Master Dashboard API
from .timeline import router as timeline_router  # Project Timeline (Event + Chronology)
from .forensics import router as forensics_router  # DEP anchors + verification
from .bundle_manifest import router as bundle_router  # Bundle MVP (manifest + hashes)
from .delay_analysis import router as delay_analysis_router  # Delay Analysis AI agents
from .collaboration import router as collaboration_router  # Collaboration features
from .workspace_collaboration import (
    router as workspace_router,
)  # Workspace collaboration hub
from .workspace_config import (
    router as workspace_config_router,
)  # Workspace config (stakeholders/keywords)
from .workspaces import router as workspaces_router  # Workspaces API
from .enhanced_api_routes import (
    aws_router,
)  # AWS AI Services (Bedrock, Textract, Comprehend, etc.)
from .ai_models_api import router as ai_models_router  # 2025 AI Models API
from .ai_optimization import (
    router as ai_optimization_router,
)  # AI Optimization Tracking
from .routers.caselaw import router as caselaw_router  # Case Law Intelligence
from .routers.lex import router as lex_router  # Lex legislation/caselaw API
from .routers.contract_intelligence import (
    router as contract_intelligence_router,
)  # Contract Intelligence API
from .chronology_builder import (
    router as chronology_builder_router,
)  # Chronology Builder
from .jobs import router as jobs_router  # Job status + progress (Celery)
from .upload_routes import router as upload_router  # Upload + admin PST endpoints
from .document_routes import router as document_router  # Document CRUD + search
from .startup import startup as _startup_handler  # Startup logic

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)

# Shared CSRF verifier (also used by other routers).
from .csrf import verify_csrf_token
from .trace_context import reset_trace_context, set_trace_context


def _parse_uuid(value: str) -> uuid.UUID:
    """Parse a string as UUID, raising HTTPException(400) on bad input."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        logger.debug(f"Invalid UUID format: {value}")
        raise HTTPException(400, "invalid document id")


app = FastAPI(
    title="VeriCase Docs API", version="0.3.9"
)  # Updated 2025-11-12 added AWS Secrets Manager for AI keys

# Optional OpenTelemetry tracing (disabled by default)
try:
    from .tracing import (
        setup_tracing,
        instrument_fastapi,
        instrument_requests,
        instrument_sqlalchemy,
    )

    if setup_tracing("vericase-api"):
        instrument_fastapi(app)
        instrument_requests()
        instrument_sqlalchemy(engine)
except Exception:
    # Tracing should never block API startup.
    pass


# Custom HTTPS Redirect Middleware that excludes health checks
# Standard HTTPSRedirectMiddleware breaks Kubernetes liveness/readiness probes
class HTTPSRedirectExcludeHealthMiddleware(BaseHTTPMiddleware):
    """HTTPS redirect that excludes health check endpoints for Kubernetes probes"""

    # Paths that should NOT be redirected (used by K8s probes internally over HTTP)
    EXCLUDED_PATHS = {"/health", "/healthz", "/ready", "/readyz", "/livez"}

    async def dispatch(self, request, call_next):
        # Skip redirect for health endpoints (K8s probes use HTTP internally)
        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)

        # Check X-Forwarded-Proto header (set by ALB)
        forwarded_proto = request.headers.get("x-forwarded-proto", "")

        # If already HTTPS or behind ALB with HTTPS, don't redirect
        if forwarded_proto == "https" or request.url.scheme == "https":
            return await call_next(request)

        # Only redirect external requests (not internal K8s traffic)
        # ALB sets X-Forwarded-For, K8s probes don't
        if "x-forwarded-for" in request.headers:
            # External request via ALB - redirect to HTTPS
            https_url = request.url.replace(scheme="https")
            return StarletteRedirect(url=str(https_url), status_code=307)

        # Internal request (K8s probe or pod-to-pod) - allow HTTP
        return await call_next(request)


# Security Middleware
# Only enable HTTPS redirect in actual AWS production environments
# AWS_EXECUTION_ENV is set by Lambda/AppRunner, USE_AWS_SERVICES=true is explicit production flag
# NOTE: AWS_REGION is NOT used as a trigger since it's just a configuration value for local testing
if os.getenv("AWS_EXECUTION_ENV") or os.getenv("USE_AWS_SERVICES") == "true":
    # Use custom middleware that excludes health endpoints
    app.add_middleware(HTTPSRedirectExcludeHealthMiddleware)
    logger.info("[STARTUP] HTTPS Redirect Middleware enabled (health checks excluded)")
    # Trust headers from AWS Load Balancer
    # Note: Uvicorn proxy_headers=True handles X-Forwarded-Proto, but this ensures redirect

    # Restrict Host header if domain is known (optional, good for security)
    # app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*.elb.amazonaws.com", "vericase.yourdomain.com", "localhost"])
else:
    logger.info("[STARTUP] HTTPS Redirect Middleware DISABLED (local development mode)")

# Startup Event: Run Migrations


# Mount UI BEFORE routers (order matters in FastAPI!)
_here = Path(__file__).resolve()
_base_dir = _here.parent.parent  # /code or repo/api
_ui_candidates = [
    _base_dir / "ui",
    _base_dir.parent / "ui",
]
logger.info(f"[STARTUP] Looking for UI directory. Candidates: {_ui_candidates}")

UI_DIR = next((c for c in _ui_candidates if c.exists()), None)
# Mount assets directory for static files (logos, images, etc.)
_assets_candidates = [
    _base_dir / "assets",
    _base_dir.parent / "assets",
]
ASSETS_DIR = next((c for c in _assets_candidates if c.exists()), None)
if ASSETS_DIR:
    logger.info(f"[STARTUP] [OK] Assets directory found: {ASSETS_DIR}")
    logger.info(f"[OK] Assets directory found and mounting at /assets: {ASSETS_DIR}")
    try:
        assets_path = ASSETS_DIR.resolve()
        app.mount(
            "/assets",
            StaticFiles(directory=str(assets_path), check_dir=False),
            name="static_assets",
        )
        logger.info("[STARTUP] [OK] Assets mount complete at /assets")
    except Exception as e:
        logger.error(f"Failed to mount assets: {e}")
        logger.error(f"[STARTUP] [ERROR] Failed to mount assets: {e}")
else:
    logger.warning("[STARTUP] [WARNING] Assets directory not found")

if UI_DIR:
    logger.info(f"[STARTUP] [OK] UI directory found: {UI_DIR}")
    logger.info(f"[OK] UI directory found and mounting at /ui: {UI_DIR}")
    try:
        # Ensure the path is absolute
        ui_path = UI_DIR.resolve()
        logger.info(f"[STARTUP] Resolving to absolute path: {ui_path}")

        # Mount with explicit settings - try with check_dir=False first
        app.mount(
            "/ui",
            StaticFiles(directory=str(ui_path), html=True, check_dir=False),
            name="static_ui",
        )

        logger.info("[OK] UI mount complete")
        logger.info("[STARTUP] [OK] UI mount complete at /ui")
    except Exception as e:
        logger.error(f"Failed to mount UI: {e}")
        logger.error(f"[STARTUP] [ERROR] Failed to mount UI: {e}")
        import traceback

        traceback.print_exc()
else:
    logger.warning(
        "UI directory not found in candidates %s; /ui mount disabled", _ui_candidates
    )
    logger.warning("[STARTUP] [WARNING] UI directory not found")

# Include routers
app.include_router(users_router)
app.include_router(sharing_router)
app.include_router(favorites_router)
app.include_router(versioning_router)
app.include_router(jobs_router)  # Job status + progress (Celery)
app.include_router(ai_router)
app.include_router(orchestrator_router)
app.include_router(ai_chat_router)  # AI Chat with multi-model research
app.include_router(admin_approval_router)  # Admin user approval system
app.include_router(admin_settings_router)  # Admin settings management
app.include_router(deployment_router)  # SSH deployment tools
app.include_router(intelligent_config_router)  # Intelligent AI-powered configuration
# NOTE: wizard_router is no longer exported from correspondence; wizard endpoints
# are served via the main router.
app.include_router(simple_cases_router)  # Registered first: serves GET/POST/DELETE /api/cases (with auth on mutating endpoints)
app.include_router(cases_router)  # Provides PUT /api/cases/{id}, evidence, issues, claims, documents sub-endpoints
app.include_router(programmes_router)
app.include_router(correspondence_router)  # PST Analysis & email correspondence
app.include_router(
    ai_refinement_router
)  # Enhanced AI refinement with intelligent questioning
app.include_router(auth_enhanced_router)  # Enhanced authentication endpoints
app.include_router(evidence_router)  # Evidence repository
app.include_router(ocr_feedback_router)  # OCR feedback
app.include_router(
    vericase_analysis_router
)  # VeriCase Analysis (flagship orchestrator)
app.include_router(vericase_rebuttal_router)  # VeriCase Rebuttal
app.include_router(claims_router)  # Contentious Matters and Heads of Claim
app.include_router(dashboard_router)  # Master Dashboard API
app.include_router(aws_router)  # AWS AI Services (Bedrock, Textract, Comprehend, etc.)
app.include_router(ai_models_router)  # 2025 AI Models API
app.include_router(timeline_router)  # Project Timeline (Event + Chronology)
app.include_router(forensics_router)  # Forensic spans (DEP)
app.include_router(bundle_router)  # Bundle manifest export
app.include_router(delay_analysis_router)  # Delay Analysis AI agents
app.include_router(
    collaboration_router
)  # Collaboration features (comments, annotations, activity)
app.include_router(workspace_router)  # Workspace collaboration hub
app.include_router(workspace_config_router)  # Workspace config (stakeholders/keywords)
app.include_router(workspaces_router)  # Workspaces API
app.include_router(ai_optimization_router)  # AI Optimization Tracking
app.include_router(caselaw_router)  # Case Law Intelligence
app.include_router(lex_router)  # Lex legislation/caselaw API
app.include_router(contract_intelligence_router)  # Contract Intelligence API
app.include_router(chronology_builder_router)  # Chronology Builder
app.include_router(upload_router)  # Upload + admin PST endpoints
app.include_router(document_router)  # Document CRUD + search

origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
if origins:
    wildcard = "*" in origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if wildcard else origins,
        # Credentials cannot be used with wildcard origins. Most UI calls use
        # Authorization headers, not cookies, so disabling credentials here
        # preserves functionality while avoiding an insecure CORS config.
        allow_credentials=False if wildcard else True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# GZip compression for responses > 500 bytes (significant bandwidth savings for large JSON responses)
app.add_middleware(GZipMiddleware, minimum_size=500)


# Request-scoped trace context (chain_id/run_id) for forensic logging and replay
@app.middleware("http")
async def trace_request_context(request: Request, call_next):
    incoming_chain_id = request.headers.get("x-chain-id") or request.headers.get(
        "x-request-id"
    )
    chain_id = incoming_chain_id or str(uuid4())
    run_id = request.headers.get("x-run-id")

    tokens = set_trace_context(chain_id=chain_id, run_id=run_id)
    try:
        response = await call_next(request)
    finally:
        reset_trace_context(tokens)

    response.headers.setdefault("X-Chain-ID", chain_id)
    if run_id:
        response.headers.setdefault("X-Run-ID", run_id)
    return response


# Custom middleware for HTTP caching headers on static assets
@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    """Add HTTP cache headers for static assets to reduce network requests"""
    response = await call_next(request)
    path = request.url.path

    # Cache static assets (CSS, JS, images, fonts) for 1 hour
    if any(
        path.endswith(ext) for ext in [".css", ".js", ".woff", ".woff2", ".ttf", ".eot"]
    ):
        response.headers["Cache-Control"] = "public, max-age=3600, immutable"
    elif any(
        path.endswith(ext)
        for ext in [".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp"]
    ):
        response.headers["Cache-Control"] = (
            "public, max-age=86400"  # 24 hours for images
        )
    elif path.startswith("/ui/") and path.endswith(".html"):
        # HTML pages should revalidate more often
        # In development, set to 0 to avoid caching issues
        cache_age = 0 if os.getenv("ENVIRONMENT") != "production" else 300
        response.headers["Cache-Control"] = (
            f"public, max-age={cache_age}, must-revalidate"
        )

    return response


@app.get("/", include_in_schema=False)
def redirect_to_ui():
    return RedirectResponse(url="/ui/login.html")


@app.get("/login.html", include_in_schema=False)
@app.get("/login", include_in_schema=False)
def redirect_to_login():
    return RedirectResponse(url="/ui/login.html")


@app.get("/wizard.html", include_in_schema=False)
@app.get("/wizard", include_in_schema=False)
def redirect_to_wizard():
    return RedirectResponse(url="/ui/wizard.html")


@app.get("/dashboard.html", include_in_schema=False)
@app.get("/dashboard", include_in_schema=False)
def redirect_to_dashboard():
    return RedirectResponse(url="/ui/dashboard.html")


@app.get("/master-dashboard.html", include_in_schema=False)
@app.get("/master-dashboard", include_in_schema=False)
@app.get("/home", include_in_schema=False)
def redirect_to_master_dashboard():
    return RedirectResponse(url="/ui/master-dashboard.html")


@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
def chrome_devtools_appspecific():
    return Response(content="{}", media_type="application/json")


@app.get("/{page}.html", include_in_schema=False)
def redirect_ui_html(page: str):
    if not UI_DIR:
        raise HTTPException(status_code=404, detail="UI not available")
    target = UI_DIR / f"{page}.html"
    if target.exists():
        return RedirectResponse(url=f"/ui/{page}.html")
    raise HTTPException(status_code=404, detail="Page not found")


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {"status": "healthy", "version": app.version}


@app.get("/debug/ui")
async def debug_ui(user: User = Depends(current_user)):
    """Debug endpoint to check UI mount status"""
    import os

    # Never expose debug endpoints publicly in production.
    if (
        os.getenv("ENVIRONMENT", "").lower() == "production"
        and os.getenv("ENABLE_DEBUG_ENDPOINTS", "").lower()
        not in {"1", "true", "yes", "on"}
    ):
        raise HTTPException(status_code=404, detail="Not found")

    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")

    # Get all mounted apps
    mounted_apps = []
    for route in app.routes:
        route_info = {
            "path": getattr(route, "path", "N/A"),
            "name": getattr(route, "name", "N/A"),
            "type": type(route).__name__,
        }
        if hasattr(route, "app") and hasattr(route.app, "directory"):
            route_info["directory"] = str(route.app.directory)
        mounted_apps.append(route_info)

    ui_info = {
        "ui_dir_found": UI_DIR is not None,
        "ui_dir_path": str(UI_DIR) if UI_DIR else None,
        "ui_dir_resolved": str(UI_DIR.resolve()) if UI_DIR else None,
        "candidates_checked": [str(c) for c in _ui_candidates],
        "candidates_exist": [c.exists() for c in _ui_candidates],
        "mounted_routes": mounted_apps,
        "static_file_mounts": [r for r in mounted_apps if r["type"] == "Mount"],
    }

    if UI_DIR and UI_DIR.exists():
        ui_info["files_in_ui_dir"] = sorted(os.listdir(UI_DIR))[:20]
        # Check if wizard.html exists
        wizard_path = UI_DIR / "wizard.html"
        ui_info["wizard_exists"] = wizard_path.exists()

    return ui_info


@app.get("/debug/auth")
async def debug_auth(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Debug endpoint to check auth setup"""
    import os

    # Never expose debug endpoints publicly in production.
    if (
        os.getenv("ENVIRONMENT", "").lower() == "production"
        and os.getenv("ENABLE_DEBUG_ENDPOINTS", "").lower()
        not in {"1", "true", "yes", "on"}
    ):
        raise HTTPException(status_code=404, detail="Not found")

    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        # Check for new admin account first, fall back to old
        admin = db.query(User).filter(User.email == "admin@veri-case.com").first()
        if not admin:
            admin = db.query(User).filter(User.email == "admin@vericase.com").first()
        user_count = db.query(User).count()

        result = {
            "admin_exists": admin is not None,
            "admin_email": admin.email if admin else None,
            "admin_active": admin.is_active if admin else None,
            "admin_verified": admin.email_verified if admin else None,
            "total_users": user_count,
            "tables_exist": True,
            "admin_password_hash": (
                admin.password_hash[:20] + "..."
                if admin and admin.password_hash
                else None
            ),
        }

        # Check if admin user needs to be created
        if not admin and os.getenv("ADMIN_EMAIL") and os.getenv("ADMIN_PASSWORD"):
            result["admin_should_be_created"] = True
            result["admin_email_env"] = os.getenv("ADMIN_EMAIL")

        return result
    except Exception as e:
        return {"error": str(e), "tables_exist": False}


app.on_event("startup")(_startup_handler)


# AI Status endpoint (4 providers: OpenAI, Anthropic, Gemini, Bedrock)
@app.get("/api/ai/status")
def get_ai_status(user=Depends(current_user)):
    """Check which AI services are available"""
    status = {
        "openai": bool(settings.OPENAI_API_KEY),
        "anthropic": bool(settings.CLAUDE_API_KEY),
        "gemini": bool(settings.GEMINI_API_KEY),
        "bedrock": bool(getattr(settings, "BEDROCK_ENABLED", False)),
        "any_available": False,
    }
    status["any_available"] = any(
        [
            status["openai"],
            status["anthropic"],
            status["gemini"],
            status["bedrock"],
        ]
    )
    return status


# Auth
@app.post("/api/auth/register")
@app.post("/auth/signup")  # Keep old endpoint for compatibility
def signup(payload: dict = Body(...), db: Session = Depends(get_db)):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    display_name = (
        payload.get("display_name") or payload.get("full_name") or ""
    ).strip()
    requires_approval = True  # Always require admin approval

    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "email already registered")

    # Generate verification token
    verification_token = generate_token()

    # Create user with pending approval status
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name or None,
        verification_token=verification_token,
        email_verified=False,
        is_active=not requires_approval,  # Inactive until admin approves
        role=UserRole.USER,  # Default role, admin can change
    )

    # Store additional signup info in meta
    _ = {
        "first_name": payload.get("first_name"),
        "last_name": payload.get("last_name"),
        "company": payload.get("company"),
        "role_description": payload.get("role"),
        "signup_reason": payload.get("reason"),
        "signup_date": datetime.now(timezone.utc).isoformat(),
        "approval_status": "pending" if requires_approval else "auto_approved",
    }

    db.add(user)
    db.commit()

    # Send notification emails
    try:
        # Email to user
        email_service.send_verification_email(
            to_email=email,
            user_name=display_name or email.split("@")[0],
            verification_token=verification_token,
        )

        # Email to admin if approval required
        if requires_approval:
            # Get admin users
            admins = (
                db.query(User)
                .filter(User.role == UserRole.ADMIN, User.is_active == True)
                .all()
            )
            for admin in admins:
                try:
                    email_service.send_approval_notification(
                        admin_email=admin.email,
                        new_user_email=email,
                        new_user_name=display_name,
                        company=payload.get("company", "Unknown"),
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to send approval notification to {admin.email}: {e}"
                    )
    except Exception as e:
        logger.error(f"Failed to send emails: {e}")

    # Return success message (no token if approval required)
    if requires_approval:
        return {
            "message": "Registration successful! Your account is pending admin approval. You will receive an email once approved.",
            "approval_required": True,
            "email": email,
        }
    else:
        token = sign_token(str(user.id), user.email)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": str(user.id),
                "email": user.email,
                "display_name": display_name,
                "full_name": display_name,
                "email_verified": False,
            },
            "message": "Registration successful. Please check your email to verify your account.",
        }



# Legacy /api/auth/login removed — use /api/auth/login-secure (auth_enhanced.py)


@app.get("/api/auth/me")
def get_current_user_info(
    creds: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)
):
    user = current_user(creds, db)
    display_name = getattr(user, "display_name", None) or ""
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": display_name,
        "full_name": display_name,
    }


# Projects/Cases
## Project and Case endpoints are implemented across two routers:
## - simple_cases.py: GET/POST/DELETE /api/cases, projects, intel (auth required on mutating case endpoints)
## - cases.py: PUT /api/cases/{id}, evidence, issues, claims, documents sub-endpoints (auth required)


# Uploads, Documents, and Search are now served by upload_routes and document_routes routers.


# Share links
@app.post("/shares")
def create_share(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    doc_id = body.get("document_id")
    hours = int(body.get("hours") or 24)
    if not doc_id:
        raise HTTPException(400, "document_id required")
    doc = db.get(Document, _parse_uuid(doc_id))
    if not doc:
        raise HTTPException(404, "document not found")
    if hours < 1:
        hours = 1
    if hours > 168:
        hours = 168
    password = body.get("password")
    password_hash = None
    if password:
        password = password.strip()
        if len(password) < 4 or len(password) > 128:
            raise HTTPException(
                400, "password length must be between 4 and 128 characters"
            )
        password_hash = hash_password(password)
    token = uuid.uuid4().hex
    expires = datetime.now(timezone.utc) + timedelta(hours=hours)
    share = ShareLink(
        token=token,
        document_id=doc.id,
        created_by=user.id,
        expires_at=expires,
        password_hash=password_hash,
    )
    db.add(share)
    db.commit()
    return {
        "token": token,
        "expires_at": expires,
        "requires_password": bool(password_hash),
    }


@app.get("/shares/{token}")
def resolve_share(
    token: str,
    password: str | None = Query(default=None),
    watermark: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    share = (
        db.query(ShareLink)
        .options(joinedload(ShareLink.document))
        .filter(ShareLink.token == token, ShareLink.expires_at > now)
        .first()
    )
    if not share:
        raise HTTPException(404, "invalid or expired")
    if share.password_hash:
        if not password or not verify_password(password, share.password_hash):
            raise HTTPException(401, "password required")
    document = share.document
    if not document:
        raise HTTPException(500, "document missing")
    if watermark:
        sanitized = normalize_watermark_text(watermark)
        if not sanitized:
            raise HTTPException(400, "watermark must contain printable characters")
        content_type = (document.content_type or "").lower()
        filename = document.filename or ""
        if "pdf" not in content_type and not filename.lower().endswith(".pdf"):
            raise HTTPException(400, "watermark supported for PDFs only")
        try:
            original_bytes = get_object(document.s3_key)
            stamped = build_watermarked_pdf(original_bytes, sanitized)
            temp_key = f"shares/{token}/watermarked/{uuid4()}.pdf"
            put_object(temp_key, stamped, "application/pdf")
            url = presign_get(temp_key, 300)
            return {"url": url, "filename": filename, "content_type": "application/pdf"}
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Failed to create watermarked PDF for share %s", token)
            raise HTTPException(500, "unable to generate watermark") from exc
    url = presign_get(document.s3_key, 300)
    return {
        "url": url,
        "filename": document.filename,
        "content_type": document.content_type,
    }


# Folder Management
from .folders import (
    validate_folder_path,
    get_parent_path,
    get_folder_name,
    create_folder_record,
    rename_folder_and_docs,
    delete_folder_and_docs,
)


class FolderInfo(BaseModel):
    path: str
    name: str
    parent_path: str | None = None
    is_empty: bool
    document_count: int
    created_at: datetime | None = None


class FolderListResponse(BaseModel):
    folders: list[FolderInfo]


@app.post("/folders")
def create_folder(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf_token),
):
    """Create a new empty folder"""
    path = body.get("path", "").strip()
    path = validate_folder_path(path)
    folder = create_folder_record(db, path, user.id)
    db.commit()
    db.refresh(folder)
    return {
        "path": folder.path,
        "name": folder.name,
        "parent_path": folder.parent_path,
        "created": True,
        "created_at": folder.created_at,
    }


@app.patch("/folders")
def rename_folder(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf_token),
):
    """Rename a folder and update all document paths"""
    old_path = body.get("old_path", "").strip()
    new_path = body.get("new_path", "").strip()

    # Support both new_name (for simple rename) and new_path (for full path change)
    if not old_path:
        raise HTTPException(400, "old_path is required")

    if not new_path:
        new_name = body.get("new_name", "").strip()
        if not new_name:
            raise HTTPException(400, "either new_path or new_name is required")
        parent = get_parent_path(old_path)
        new_path = f"{parent}/{new_name}" if parent else new_name

    old_path = validate_folder_path(old_path)
    new_path = validate_folder_path(new_path)

    try:
        documents_updated = rename_folder_and_docs(
            db, user.id, old_path, new_path.split("/")[-1]
        )
        db.commit()
        return {
            "old_path": old_path,
            "new_path": new_path,
            "documents_updated": documents_updated,
            "success": True,
        }
    except Exception as e:
        db.rollback()
        logger.exception("Failed to rename folder")
        raise HTTPException(500, f"failed to rename folder: {str(e)}")


@app.delete("/folders")
def delete_folder(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf_token),
):
    """Delete a folder and optionally its contents"""
    path = body.get("path", "").strip()
    recursive = body.get("recursive", False)
    if not path:
        raise HTTPException(400, "path is required")
    path = validate_folder_path(path)
    try:
        documents_deleted, files_removed = delete_folder_and_docs(
            db, user.id, path, recursive, delete_object, os_delete, logger
        )
        db.commit()
        return {
            "deleted": True,
            "path": path,
            "documents_deleted": documents_deleted,
            "files_removed": files_removed,
        }
    except Exception as e:
        db.rollback()
        logger.exception("Failed to delete folder")
        raise HTTPException(500, f"failed to delete folder: {str(e)}")


@app.get("/folders", response_model=FolderListResponse)
def list_folders(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """List all folders with metadata including document counts"""
    # Admin sees all folders except other users' private folders
    if user.role == UserRole.ADMIN:
        doc_paths_stmt = (
            select(Document.path, Document.owner_user_id)
            .where(Document.path.isnot(None))
            .distinct()
        )
        doc_paths = db.execute(doc_paths_stmt).all()
        # Filter out private folders from other users
        doc_paths = [
            (path, owner_id)
            for path, owner_id in doc_paths
            if not path.startswith("private/") or owner_id == user.id
        ]
        # Convert back to tuple format
        doc_paths = [(path,) for path, _ in doc_paths]

        empty_folders_stmt = select(Folder)
        empty_folders = db.execute(empty_folders_stmt).scalars().all()
        # Filter out private folders from other users
        empty_folders = [
            f
            for f in empty_folders
            if not f.path.startswith("private/") or f.owner_user_id == user.id
        ]
    else:
        doc_paths_stmt = (
            select(Document.path)
            .where(Document.owner_user_id == user.id, Document.path.isnot(None))
            .distinct()
        )
        doc_paths = db.execute(doc_paths_stmt).all()
        empty_folders_stmt = select(Folder).where(Folder.owner_user_id == user.id)
        empty_folders = db.execute(empty_folders_stmt).scalars().all()
    folder_map = {}
    for (path,) in doc_paths:
        if not path:
            continue
        parts = path.split("/")
        for i in range(len(parts)):
            folder_path = "/".join(parts[: i + 1])
            if folder_path not in folder_map:
                folder_map[folder_path] = {
                    "path": folder_path,
                    "name": get_folder_name(folder_path),
                    "parent_path": get_parent_path(folder_path),
                    "document_count": 0,
                    "is_empty": True,
                    "created_at": None,
                }
    for (path,) in doc_paths:
        if path and path in folder_map:
            folder_map[path]["document_count"] += 1
    for folder in empty_folders:
        if folder.path not in folder_map:
            folder_map[folder.path] = {
                "path": folder.path,
                "name": folder.name,
                "parent_path": folder.parent_path,
                "document_count": 0,
                "is_empty": True,
                "created_at": folder.created_at,
            }
        elif not folder_map[folder.path]["created_at"]:
            folder_map[folder.path]["created_at"] = folder.created_at
    outcomes = [FolderInfo(**v) for k, v in folder_map.items() if v["is_empty"]]
    outcomes.sort(key=lambda f: f.path)
    return FolderListResponse(folders=outcomes)


# Utility routes
@app.get("/ui/", include_in_schema=False)
async def ui_root():
    """Redirect /ui/ to wizard"""
    return RedirectResponse(url="/ui/wizard.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Serve favicon from assets"""
    # Try to find the logo file in UI assets
    for ui_path in [Path("/code/ui"), Path("/ui"), Path("ui")]:
        favicon_path = ui_path / "assets" / "LOGOTOBEUSED.png"
        if favicon_path.exists():
            return FileResponse(
                str(favicon_path),
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=604800"},  # Cache for 1 week
            )
    # Fallback: return transparent 1x1 PNG
    transparent_png = bytes(
        [
            0x89,
            0x50,
            0x4E,
            0x47,
            0x0D,
            0x0A,
            0x1A,
            0x0A,
            0x00,
            0x00,
            0x00,
            0x0D,
            0x49,
            0x48,
            0x44,
            0x52,
            0x00,
            0x00,
            0x00,
            0x01,
            0x00,
            0x00,
            0x00,
            0x01,
            0x08,
            0x06,
            0x00,
            0x00,
            0x00,
            0x1F,
            0x15,
            0xC4,
            0x89,
            0x00,
            0x00,
            0x00,
            0x0A,
            0x49,
            0x44,
            0x41,
            0x54,
            0x78,
            0x9C,
            0x63,
            0x00,
            0x01,
            0x00,
            0x00,
            0x05,
            0x00,
            0x01,
            0x0D,
            0x0A,
            0x2D,
            0xB4,
            0x00,
            0x00,
            0x00,
            0x00,
            0x49,
            0x45,
            0x4E,
            0x44,
            0xAE,
            0x42,
            0x60,
            0x82,
        ]
    )
    return Response(
        content=transparent_png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=604800"},
    )
