import logging
import uuid
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4
from fastapi import FastAPI, Depends, HTTPException, Query, Body, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select

# Filter out favicon requests from access logs
class FaviconFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, 'args') and record.args:
            # Check if this is a favicon request in uvicorn access log
            args = record.args
            if isinstance(args, tuple) and len(args) >= 3:
                path = str(args[2]) if len(args) > 2 else ""
                if "favicon" in path.lower():
                    return False
        # Also check message
        msg = record.getMessage() if hasattr(record, 'getMessage') else str(getattr(record, 'msg', ''))
        if 'favicon' in msg.lower():
            return False
        return True

# Apply filter to uvicorn access logger
uvicorn_access_logger = logging.getLogger("uvicorn.access")
uvicorn_access_logger.addFilter(FaviconFilter())

# Import production config helper if in production
import os
if os.getenv('AWS_EXECUTION_ENV') or os.getenv('AWS_REGION'):
    from .config_production import update_production_config
    update_production_config()

from .config import settings
from .db import Base, engine, SessionLocal
from .models import (
    Document,
    DocStatus,
    User,
    ShareLink,
    Folder,
    Case,
    Company,
    UserCompany,
    UserRole,
    AppSetting,
)
from .storage import ensure_bucket, presign_put, presign_get, multipart_start, presign_part, multipart_complete, s3, get_object, put_object, delete_object
from .search import ensure_index, search as os_search, delete_document as os_delete
from .tasks import celery_app
from .security import get_db, current_user, hash_password, verify_password, sign_token
from .security_enhanced import (
    generate_token,
    is_account_locked,
    handle_failed_login,
    handle_successful_login,
    record_login_attempt,
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
from .ai_chat import router as ai_chat_router
from .admin_approval import router as admin_approval_router
from .admin_settings import router as admin_settings_router
from .intelligent_config import router as intelligent_config_router
from .cases import router as cases_router
from .simple_cases import router as simple_cases_router
from .programmes import router as programmes_router
from .correspondence import router as correspondence_router, wizard_router  # PST Analysis endpoints
from .refinement import router as refinement_router  # AI refinement wizard
from .ai_refinement import router as ai_refinement_router  # Enhanced AI refinement with intelligent questioning
from .auth_enhanced import router as auth_enhanced_router  # Enhanced authentication
from .evidence_repository import router as evidence_router  # Evidence repository
from .deep_research import router as deep_research_router  # Deep Research Agent
from .claims_module import router as claims_router  # Contentious Matters and Heads of Claim
from .dashboard_api import router as dashboard_router  # Master Dashboard API
from .enhanced_api_routes import aws_router  # AWS AI Services (Bedrock, Textract, Comprehend, etc.)
try:
    from .aws_services import get_aws_services  # AWS Services Manager
except ImportError:
    get_aws_services = None
from .phi_routes import router as phi_router  # Phi-4 AI model
from .ai_models_api import router as ai_models_router  # 2025 AI Models API

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)

CSRF_TOKEN_STORE: dict[str, str] = {}
CSRF_LOCK = RLock()
CSRF_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as e:
        logger.debug(f"Invalid UUID format: {value}")
        raise HTTPException(400, "invalid document id")


def verify_csrf_token(
    request: Request,
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> None:
    if not creds:
        # TEMPORARY: Allow requests without auth header while login is disabled
        return

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


class DocumentSummary(BaseModel):
    id: str
    filename: str
    path: str | None = None
    status: str
    size: int
    content_type: str | None = None
    title: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class DocumentListResponse(BaseModel):
    total: int
    items: list[DocumentSummary]


class PathListResponse(BaseModel):
    paths: list[str]
app = FastAPI(title="VeriCase Docs API", version="0.3.9")  # Updated 2025-11-12 added AWS Secrets Manager for AI keys

# Mount UI BEFORE routers (order matters in FastAPI!)
_here = Path(__file__).resolve()
_base_dir = _here.parent.parent  # /code or repo/api
_ui_candidates = [
    _base_dir / "ui",
    _base_dir.parent / "ui",
]
print(f"[STARTUP] Looking for UI directory. Candidates: {_ui_candidates}")
logger.info(f"Looking for UI directory. Candidates: {_ui_candidates}")
UI_DIR = next((c for c in _ui_candidates if c.exists()), None)
if UI_DIR:
    print(f"[STARTUP] [OK] UI directory found: {UI_DIR}")
    logger.info(f"[OK] UI directory found and mounting at /ui: {UI_DIR}")
    try:
        # Ensure the path is absolute
        ui_path = UI_DIR.resolve()
        print(f"[STARTUP] Resolving to absolute path: {ui_path}")
        
        # Mount with explicit settings - try with check_dir=False first
        app.mount("/ui", StaticFiles(directory=str(ui_path), html=True, check_dir=False), name="static_ui")
        
        logger.info(f"[OK] UI mount complete")
        print(f"[STARTUP] [OK] UI mount complete at /ui")
    except Exception as e:
        logger.error(f"Failed to mount UI: {e}")
        print(f"[STARTUP] [ERROR] Failed to mount UI: {e}")
        import traceback
        traceback.print_exc()
else:
    logger.warning("UI directory not found in candidates %s; /ui mount disabled", _ui_candidates)
    print(f"[STARTUP] [WARNING] UI directory not found")

# Include routers
app.include_router(users_router)
app.include_router(sharing_router)
app.include_router(favorites_router)
app.include_router(versioning_router)
app.include_router(ai_router)
app.include_router(orchestrator_router)
app.include_router(ai_chat_router)  # AI Chat with multi-model research
app.include_router(admin_approval_router)  # Admin user approval system
app.include_router(admin_settings_router)  # Admin settings management
app.include_router(intelligent_config_router)  # Intelligent AI-powered configuration
app.include_router(wizard_router)  # Wizard endpoints (must come early for /api/projects, /api/cases)
app.include_router(simple_cases_router)  # Must come BEFORE cases_router to match first
app.include_router(cases_router)
app.include_router(programmes_router)
app.include_router(correspondence_router)  # PST Analysis & email correspondence
app.include_router(refinement_router)  # AI refinement wizard endpoints
app.include_router(ai_refinement_router)  # Enhanced AI refinement with intelligent questioning
app.include_router(auth_enhanced_router)  # Enhanced authentication endpoints
app.include_router(evidence_router)  # Evidence repository
app.include_router(deep_research_router)  # Deep Research Agent
app.include_router(claims_router)  # Contentious Matters and Heads of Claim
app.include_router(dashboard_router)  # Master Dashboard API
app.include_router(aws_router)  # AWS AI Services (Bedrock, Textract, Comprehend, etc.)
app.include_router(phi_router)  # Phi-4 AI model
app.include_router(ai_models_router)  # 2025 AI Models API

# Import and include unified router
from .correspondence import unified_router
app.include_router(unified_router)  # Unified endpoints for both projects and cases

origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# GZip compression for responses > 500 bytes (significant bandwidth savings for large JSON responses)
app.add_middleware(GZipMiddleware, minimum_size=500)


# Custom middleware for HTTP caching headers on static assets
@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    """Add HTTP cache headers for static assets to reduce network requests"""
    response = await call_next(request)
    path = request.url.path
    
    # Cache static assets (CSS, JS, images, fonts) for 1 hour
    if any(path.endswith(ext) for ext in ['.css', '.js', '.woff', '.woff2', '.ttf', '.eot']):
        response.headers['Cache-Control'] = 'public, max-age=3600, immutable'
    elif any(path.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp']):
        response.headers['Cache-Control'] = 'public, max-age=86400'  # 24 hours for images
    elif path.startswith('/ui/') and path.endswith('.html'):
        # HTML pages should revalidate more often
        response.headers['Cache-Control'] = 'public, max-age=300, must-revalidate'  # 5 minutes
    
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

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {"status": "healthy", "version": app.version}

@app.get("/debug/ui")
async def debug_ui():
    """Debug endpoint to check UI mount status"""
    import os
    
    # Get all mounted apps
    mounted_apps = []
    for route in app.routes:
        route_info = {
            "path": getattr(route, 'path', 'N/A'),
            "name": getattr(route, 'name', 'N/A'),
            "type": type(route).__name__
        }
        if hasattr(route, 'app') and hasattr(route.app, 'directory'):
            route_info["directory"] = str(route.app.directory)
        mounted_apps.append(route_info)
    
    ui_info = {
        "ui_dir_found": UI_DIR is not None,
        "ui_dir_path": str(UI_DIR) if UI_DIR else None,
        "ui_dir_resolved": str(UI_DIR.resolve()) if UI_DIR else None,
        "candidates_checked": [str(c) for c in _ui_candidates],
        "candidates_exist": [c.exists() for c in _ui_candidates],
        "mounted_routes": mounted_apps,
        "static_file_mounts": [r for r in mounted_apps if r['type'] == 'Mount'],
    }
    
    if UI_DIR and UI_DIR.exists():
        ui_info["files_in_ui_dir"] = sorted(os.listdir(UI_DIR))[:20]
        # Check if wizard.html exists
        wizard_path = UI_DIR / "wizard.html"
        ui_info["wizard_exists"] = wizard_path.exists()
        
    return ui_info

@app.get("/debug/auth")
async def debug_auth(db: Session = Depends(get_db)):
    """Debug endpoint to check auth setup"""
    try:
        admin = db.query(User).filter(User.email == "admin@veri-case.com").first()
        user_count = db.query(User).count()
        
        result = {
            "admin_exists": admin is not None,
            "admin_email": admin.email if admin else None,
            "admin_active": admin.is_active if admin else None,
            "admin_verified": admin.email_verified if admin else None,
            "total_users": user_count,
            "tables_exist": True,
            "admin_password_hash": admin.password_hash[:20] + "..." if admin and admin.password_hash else None
        }
        
        # Check if admin user needs to be created
        if not admin and os.getenv('ADMIN_EMAIL') and os.getenv('ADMIN_PASSWORD'):
            result["admin_should_be_created"] = True
            result["admin_email_env"] = os.getenv('ADMIN_EMAIL')
            
        return result
    except Exception as e:
        return {
            "error": str(e),
            "tables_exist": False
        }

def _populate_ai_settings_from_env(force_update: bool = False):
    """
    Populate AI settings in database from environment variables.
    This ensures Admin Settings UI shows the configured API keys.
    
    Args:
        force_update: If True, update existing settings even if they have values.
                     Used after loading from AWS Secrets Manager.
    """
    db = SessionLocal()
    try:
        # Map of database setting keys to environment variable names and descriptions
        ai_settings_map = {
            'openai_api_key': {
                'env_var': 'OPENAI_API_KEY',
                'config_attr': 'OPENAI_API_KEY',
                'description': 'OpenAI API key for GPT models',
                'is_api_key': True
            },
            'anthropic_api_key': {
                'env_var': 'CLAUDE_API_KEY',
                'config_attr': 'CLAUDE_API_KEY', 
                'description': 'Anthropic API key for Claude models',
                'is_api_key': True
            },
            'gemini_api_key': {
                'env_var': 'GEMINI_API_KEY',
                'config_attr': 'GEMINI_API_KEY',
                'description': 'Google API key for Gemini models',
                'is_api_key': True
            },
            'grok_api_key': {
                'env_var': 'GROK_API_KEY',
                'config_attr': 'GROK_API_KEY',
                'description': 'xAI API key for Grok models',
                'is_api_key': True
            },
            'perplexity_api_key': {
                'env_var': 'PERPLEXITY_API_KEY',
                'config_attr': 'PERPLEXITY_API_KEY',
                'description': 'Perplexity API key for Sonar models',
                'is_api_key': True
            },
            # Default models - Updated 2025
            'openai_model': {
                'default': 'gpt-5.1',
                'description': 'Default OpenAI model'
            },
            'anthropic_model': {
                'default': 'claude-sonnet-4.5',
                'description': 'Default Anthropic model'
            },
            'gemini_model': {
                'default': 'gemini-3.0-pro',
                'description': 'Default Gemini model'
            },
            'grok_model': {
                'default': 'grok-4.1',
                'description': 'Default Grok model'
            },
            'perplexity_model': {
                'default': 'sonar-pro',
                'description': 'Default Perplexity model'
            },
            # Default provider
            'ai_default_provider': {
                'default': 'anthropic',
                'description': 'Default AI provider to use'
            },
        }
        
        populated_count = 0
        
        for key, config in ai_settings_map.items():
            # Check if setting already exists
            existing = db.query(AppSetting).filter(AppSetting.key == key).first()
            
            # Skip if setting exists and has value (unless force_update for API keys)
            if existing and existing.value:
                if not force_update:
                    continue
                # Only force update API keys, not model defaults
                if not config.get('is_api_key'):
                    continue
            
            # Get value from environment or config
            value = None
            
            if 'env_var' in config:
                # Try environment variable first
                value = os.getenv(config['env_var'])
                
                # Fall back to config settings
                if not value and 'config_attr' in config:
                    value = getattr(settings, config['config_attr'], None)
            elif 'default' in config:
                # Use default value for model settings
                value = config['default']
            
            if value:
                if existing:
                    # Update existing setting
                    if existing.value != value:
                        existing.value = value
                        logger.info(f"Updated AI setting: {key}")
                        populated_count += 1
                else:
                    # Create new setting
                    new_setting = AppSetting(
                        key=key,
                        value=value,
                        description=config.get('description', '')
                    )
                    db.add(new_setting)
                    logger.info(f"Created AI setting: {key}")
                    populated_count += 1
        
        if populated_count > 0:
            db.commit()
            logger.info(f"Populated {populated_count} AI settings from environment")
        else:
            logger.debug("AI settings already configured, no changes needed")
            
    except Exception as e:
        logger.error(f"Error populating AI settings: {e}")
        db.rollback()
        raise
    finally:
        db.close()


@app.on_event("startup")
def startup():
    logger.info("Starting VeriCase API...")
    
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created")
    except Exception as e:
        logger.warning(f"Database initialization skipped: {e}")
    
    logger.info("Startup complete")

# AI Status endpoint
@app.get("/api/ai/status")
def get_ai_status(user = Depends(current_user)):
    """Check which AI services are available"""
    status = {
        "openai": bool(settings.OPENAI_API_KEY),
        "anthropic": bool(settings.CLAUDE_API_KEY),
        "gemini": bool(settings.GEMINI_API_KEY),
        "grok": bool(getattr(settings, 'GROK_API_KEY', None)),
        "perplexity": bool(getattr(settings, 'PERPLEXITY_API_KEY', None)),
        "any_available": False
    }
    status["any_available"] = any([status["openai"], status["anthropic"], status["gemini"], status["grok"], status["perplexity"]])
    return status

# Auth
@app.post("/api/auth/register")
@app.post("/auth/signup")  # Keep old endpoint for compatibility
def signup(payload: dict = Body(...), db: Session = Depends(get_db)):
    email=(payload.get("email") or "").strip().lower()
    password=payload.get("password") or ""
    display_name = (payload.get("display_name") or payload.get("full_name") or "").strip()
    requires_approval = payload.get("requires_approval", True)  # Default to requiring approval
    
    if db.query(User).filter(User.email==email).first():
        raise HTTPException(409,"email already registered")
    
    # Generate verification token
    verification_token = generate_token()
    
    # Create user with pending approval status
    user=User(
        email=email, 
        password_hash=hash_password(password), 
        display_name=display_name or None,
        verification_token=verification_token,
        email_verified=False,
        is_active=not requires_approval,  # Inactive until admin approves
        role=UserRole.VIEWER  # Default role, admin can change
    )
    
    # Store additional signup info in meta
    user_meta = {
        'first_name': payload.get('first_name'),
        'last_name': payload.get('last_name'),
        'company': payload.get('company'),
        'role_description': payload.get('role'),
        'signup_reason': payload.get('reason'),
        'signup_date': datetime.now(timezone.utc).isoformat(),
        'approval_status': 'pending' if requires_approval else 'auto_approved'
    }
    
    db.add(user)
    db.commit()
    
    # Send notification emails
    try:
        # Email to user
        email_service.send_verification_email(
            to_email=email,
            user_name=display_name or email.split('@')[0],
            verification_token=verification_token
        )
        
        # Email to admin if approval required
        if requires_approval:
            # Get admin users
            admins = db.query(User).filter(User.role == UserRole.ADMIN, User.is_active == True).all()
            for admin in admins:
                try:
                    email_service.send_approval_notification(
                        admin_email=admin.email,
                        new_user_email=email,
                        new_user_name=display_name,
                        company=payload.get('company', 'Unknown')
                    )
                except Exception as e:
                    logger.warning(f"Failed to send approval notification to {admin.email}: {e}")
    except Exception as e:
        logger.error(f"Failed to send emails: {e}")
    
    # Return success message (no token if approval required)
    if requires_approval:
        return {
            "message": "Registration successful! Your account is pending admin approval. You will receive an email once approved.",
            "approval_required": True,
            "email": email
        }
    else:
        token=sign_token(str(user.id), user.email)
        return {
            "access_token": token, 
            "token_type": "bearer", 
            "user": {
                "id": str(user.id),
                "email": user.email,
                "display_name": display_name,
                "full_name": display_name,
                "email_verified": False
            },
            "message": "Registration successful. Please check your email to verify your account."
        }

@app.post("/api/auth/login")
@app.post("/auth/login")  # Keep old endpoint for compatibility
def login(payload: dict = Body(...), db: Session = Depends(get_db)):
    try:
        email = (payload.get("email") or "").strip().lower()
        password = payload.get("password") or ""
        
        if not email or not password:
            raise HTTPException(status_code=400, detail="Email and password required")
        
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        # Check if account is locked
        if is_account_locked(user):
            remaining_minutes = int((user.locked_until - datetime.now(timezone.utc)).total_seconds() / 60)
            raise HTTPException(
                status_code=403,
                detail=f"Account is locked. Try again in {remaining_minutes} minutes."
            )
        
        # Verify password with error handling
        try:
            password_valid = verify_password(password, user.password_hash)
        except Exception as e:
            logger.error(f"Password verification error for {email}: {e}")
            handle_failed_login(user, db)
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        if not password_valid:
            handle_failed_login(user, db)
            attempts_remaining = 5 - (user.failed_login_attempts or 0)
            raise HTTPException(
                status_code=401,
                detail=f"Invalid credentials. {attempts_remaining} attempts remaining."
            )
        
        # Reset failed attempts on success
        handle_successful_login(user, db)
        
        # Update last login
        try:
            user.last_login_at = datetime.now()
            db.commit()
        except (ValueError, TypeError, AttributeError) as e:
            logger.debug(f"Non-critical error updating last_login_at: {e}")
        
        token = sign_token(str(user.id), user.email)
        display_name = getattr(user, "display_name", None) or ""
        
        return {
            "access_token": token, 
            "token_type": "bearer", 
            "user": {
                "id": str(user.id),
                "email": user.email,
                "display_name": display_name,
                "full_name": display_name
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Login failed")

@app.get("/api/auth/me")
def get_current_user_info(creds: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)):
    user = current_user(creds, db)
    display_name = getattr(user, "display_name", None) or ""
    return {"id":str(user.id),"email":user.email,"display_name":display_name,"full_name":display_name}

# Projects/Cases
def get_or_create_test_user(db: Session) -> User:
    """TEMPORARY: always provide a test user so wizard can run without auth."""
    user = db.query(User).filter(User.email == "test@vericase.com").first()
    if user:
        return user

    user = User(
        email="test@vericase.com",
        password_hash=hash_password("test123"),
        role=UserRole.VIEWER,
        is_active=True,
        email_verified=True,
        display_name="Test User"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/api/projects")
@app.post("/api/cases")
def create_case(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    # user = get_or_create_test_user(db)
    
    # Get or create company for this user
    user_company = db.query(UserCompany).filter(UserCompany.user_id == user.id, UserCompany.is_primary.is_(True)).first()
    if user_company:
        company = user_company.company
    else:
        # Create new company
        company = Company(name=payload.get("company_name") or "My Company")
        db.add(company)
        db.flush()
        # Link user to company
        user_company = UserCompany(user_id=user.id, company_id=company.id, role="admin", is_primary=True)
        db.add(user_company)
        db.flush()
    
    # Extract case data from wizard payload
    details = payload.get("details", {})
    stakeholders = payload.get("stakeholders", {})
    
    case = Case(
        case_number=details.get("projectCode") or f"CASE-{uuid4().hex[:8].upper()}",
        name=details.get("projectName") or "Untitled Case",
        description=details.get("description") or "",
        project_name=details.get("projectName"),
        contract_type=payload.get("contractType") or stakeholders.get("contractType"),
        status="active",
        owner_id=user.id,
        company_id=company.id
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    
    return {
        "id": str(case.id),
        "case_number": case.case_number,
        "name": case.name,
        "status": case.status
    }

# Uploads (presign and complete)
@app.post("/uploads/init")
def init_upload(
    body: dict = Body(...),
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf_token),
):
    """Initialize file upload - returns upload_id and presigned URL"""
    filename=body.get("filename"); ct=body.get("content_type") or "application/octet-stream"
    size=int(body.get("size") or 0)
    
    # Generate unique upload ID and S3 key
    upload_id = str(uuid4())
    s3_key = f"uploads/{user.id}/{upload_id}/{filename}"
    
    # Get presigned PUT URL
    upload_url = presign_put(s3_key, ct)
    
    return {
        "upload_id": upload_id,
        "upload_url": upload_url,
        "s3_key": s3_key
    }

@app.post("/uploads/presign")
def presign_upload(
    body: dict = Body(...),
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf_token),
):
    filename=body.get("filename"); ct=body.get("content_type") or "application/octet-stream"
    path=(body.get("path") or "").strip().strip("/")
    key=f"{path + '/' if path else ''}{uuid.uuid4()}/{filename}"
    url=presign_put(key, ct); return {"key":key, "url":url}
@app.post("/uploads/complete")
def complete_upload(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf_token),
):
    # Support both new (upload_id) and legacy (key) formats
    upload_id = body.get("upload_id")
    filename = body.get("filename") or "file"
    
    if upload_id:
        # New format: construct key from upload_id
        key = f"uploads/{user.id}/{upload_id}/{filename}"
    else:
        # Legacy format: use provided key
        key = body.get("key")
    
    ct = body.get("content_type") or "application/octet-stream"
    size = int(body.get("size") or 0)
    title = body.get("title")
    path = body.get("path")
    
    # Set empty paths to None so they're treated consistently
    if path == "":
        path = None
    
    # Extract profile info for PST processing
    profile_type = body.get("profile_type") or body.get("profileType")
    profile_id = body.get("profile_id") or body.get("profileId")
    
    # Build metadata
    meta = {}
    if profile_type and profile_id:
        meta["profile_type"] = profile_type
        meta["profile_id"] = profile_id
        meta["uploaded_by"] = str(user.id)
    
    doc=Document(
        filename=filename, 
        path=path, 
        content_type=ct, 
        size=size, 
        bucket=settings.MINIO_BUCKET, 
        s3_key=key, 
        title=title, 
        status=DocStatus.NEW, 
        owner_user_id=user.id,
        meta=meta if meta else None
    )
    db.add(doc); db.commit(); 
    
    # Check if PST file - trigger PST processor instead of OCR
    if filename.lower().endswith('.pst'):
        # For PST files, pass placeholder case_id so worker recognizes it as project upload
        case_id = "00000000-0000-0000-0000-000000000000"
        company_id = body.get("company_id", "")
        
        celery_app.send_task(
            "worker_app.worker.process_pst_file", 
            args=[str(doc.id), case_id, company_id]
        )
        return {"id": str(doc.id), "status":"PROCESSING_PST", "message": "PST file queued for extraction"}
    else:
        # Queue OCR and AI classification for other files
        celery_app.send_task("worker_app.worker.ocr_and_index", args=[str(doc.id)])
        return {"id": str(doc.id), "status":"QUEUED", "ai_enabled": True}

@app.post("/uploads/multipart/start")
def multipart_start_ep(
    body: dict = Body(...),
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf_token),
):
    filename=body.get("filename"); ct=body.get("content_type") or "application/octet-stream"
    path=(body.get("path") or "").strip().strip("/"); key=f"{path + '/' if path else ''}{uuid.uuid4()}/{filename}"
    upload_id=multipart_start(key, ct); return {"key":key, "uploadId": upload_id}
@app.get("/uploads/multipart/part")
def multipart_part_url(key: str, uploadId: str, partNumber: int, user: User = Depends(current_user)):
    return {"url": presign_part(key, uploadId, partNumber)}
@app.post("/uploads/multipart/complete")
def multipart_complete_ep(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf_token),
):
    key=body["key"]; upload_id=body["uploadId"]; parts=body["parts"]; multipart_complete(key, upload_id, parts)
    filename=body.get("filename") or "file"; ct=body.get("content_type") or "application/octet-stream"
    size=int(body.get("size") or 0); title=body.get("title"); path=body.get("path")
    # Set empty paths to None so they're treated consistently
    if path == "":
        path = None
    
    doc=Document(
        filename=filename, 
        path=path, 
        content_type=ct, 
        size=size, 
        bucket=settings.MINIO_BUCKET, 
        s3_key=key, 
        title=title, 
        status=DocStatus.NEW, 
        owner_user_id=user.id
    )
    db.add(doc); db.commit(); celery_app.send_task("worker_app.worker.ocr_and_index", args=[str(doc.id)])
    return {"id": str(doc.id), "status":"QUEUED"}


@app.get("/documents", response_model=DocumentListResponse)
def list_documents(
    path_prefix: str | None = Query(default=None),
    exact_folder: bool = Query(default=False),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    # Admin sees all documents except other users' private documents
    if user.role == UserRole.ADMIN:
        # Start with all documents
        query = db.query(Document)
        # Then filter out private documents from other users
        from sqlalchemy import or_, and_
        query = query.filter(
            or_(
                Document.path.is_(None),  # Documents with no path
                ~Document.path.like('private/%'),  # Not in private folder
                and_(Document.path.like('private/%'), Document.owner_user_id == user.id)  # Or it's admin's own private folder
            )
        )
    else:
        # Regular users see only their own documents
        query = db.query(Document).filter(Document.owner_user_id == user.id)
    if path_prefix is not None:
        if path_prefix == "":
            # Empty string means root - show documents with no path or empty path
            query = query.filter((Document.path == None) | (Document.path == ""))
        else:
            safe_path = path_prefix.strip().strip("/")
            if safe_path:
                if exact_folder:
                    # Match exact folder only, not subfolders
                    query = query.filter(Document.path == safe_path)
                else:
                    # Match folder and all subfolders
                    like_pattern = f"{safe_path}/%"
                    query = query.filter(
                        (Document.path == safe_path) | (Document.path.like(like_pattern))
                    )
    if status:
        try:
            status_enum = DocStatus(status.upper())
        except ValueError:
            raise HTTPException(400, "invalid status value")
        query = query.filter(Document.status == status_enum)
    total = query.count()
    docs = query.order_by(Document.created_at.desc()).offset(offset).limit(limit).all()
    items = [
        DocumentSummary(
            id=str(doc.id),
            filename=doc.filename,
            path=doc.path,
            status=doc.status.value if doc.status else DocStatus.NEW.value,
            size=doc.size or 0,
            content_type=doc.content_type,
            title=doc.title,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )
        for doc in docs
    ]
    return DocumentListResponse(total=total, items=items)


@app.get("/documents/paths", response_model=PathListResponse)
def list_paths(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    paths = (
        db.query(Document.path)
        .filter(Document.owner_user_id == user.id, Document.path.isnot(None))
        .distinct().all()
    )
    path_values = sorted(
        p[0]
        for p in paths
        if p[0]
    )
    return PathListResponse(paths=path_values)

@app.get("/documents/recent", response_model=DocumentListResponse)
def get_recent_documents(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get recently accessed or created documents"""
    try:
        from datetime import datetime, timedelta
        
        # Get documents accessed in last 30 days, or fall back to recently created
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        
        # Try to get recently accessed first
        recent_query = db.query(Document).filter(
            Document.owner_user_id == user.id,
            Document.last_accessed_at.isnot(None),
            Document.last_accessed_at >= thirty_days_ago
        ).order_by(Document.last_accessed_at.desc())
        
        recent_docs = recent_query.limit(limit).all()
        
        # If not enough recently accessed, add recently created
        if len(recent_docs) < limit:
            created_query = db.query(Document).filter(
                Document.owner_user_id == user.id
            ).order_by(Document.created_at.desc())
            
            created_docs = created_query.limit(limit - len(recent_docs)).all()
            
            # Merge and deduplicate
            seen_ids = {doc.id for doc in recent_docs}
            for doc in created_docs:
                if doc.id not in seen_ids:
                    recent_docs.append(doc)
                    seen_ids.add(doc.id)
    except Exception as e:
        import logging
        logging.error(f"Database error in get_recent_documents: {e}")
        raise HTTPException(500, "Failed to fetch recent documents")
    
    items = [
        DocumentSummary(
            id=str(doc.id),
            filename=doc.filename,
            path=doc.path,
            status=doc.status.value if doc.status else DocStatus.NEW.value,
            size=doc.size or 0,
            content_type=doc.content_type,
            title=doc.title,
            created_at=doc.created_at,
            updated_at=doc.updated_at or doc.created_at,
        )
        for doc in recent_docs
    ]
    
    return DocumentListResponse(total=len(items), items=items)

# Documents
@app.get("/documents/{doc_id}")
def get_document(doc_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc=db.get(Document, _parse_uuid(doc_id))
    if not doc:
        raise HTTPException(404,"not found")
    return {"id":str(doc.id),"filename":doc.filename,"path":doc.path,"status":doc.status.value,
            "content_type":doc.content_type,"size":doc.size,"bucket":doc.bucket,"s3_key":doc.s3_key,
            "title":doc.title,"metadata":doc.meta,"text_excerpt":(doc.text_excerpt or "")[:1000],
            "created_at":doc.created_at,"updated_at":doc.updated_at}
@app.get("/documents/{doc_id}/signed_url")
def get_signed_url(doc_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc=db.get(Document, _parse_uuid(doc_id))
    if not doc:
        raise HTTPException(404,"not found")
    return {"url": presign_get(doc.s3_key, 300), "filename": doc.filename, "content_type": doc.content_type}


@app.patch("/documents/{doc_id}")
def update_document(
    doc_id: str,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf_token),
):
    """Update document metadata (path, title, etc.)"""
    try:
        doc = db.get(Document, _parse_uuid(doc_id))
        if not doc or doc.owner_user_id != user.id:
            raise HTTPException(404, "not found")
        
        if "path" in body:
            new_path = body["path"]
            if new_path == "":
                new_path = None
            doc.path = new_path
        
        if "title" in body:
            doc.title = body["title"]
        
        if "filename" in body:
            doc.filename = body["filename"]
        
        doc.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(doc)
        
        return {
            "id": str(doc.id),
            "filename": doc.filename,
            "path": doc.path,
            "title": doc.title,
            "updated_at": doc.updated_at
        }
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.error(f"Error updating document: {e}")
        db.rollback()
        raise HTTPException(500, "Failed to update document")

@app.delete("/documents/{doc_id}", status_code=204)
def delete_document_endpoint(
    doc_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf_token),
):
    doc = db.get(Document, _parse_uuid(doc_id))
    if not doc or doc.owner_user_id != user.id:
        raise HTTPException(404, "not found")
    try:
        delete_object(doc.s3_key)
    except Exception:
        logger.exception("Failed to delete object %s from storage", doc.s3_key)
    try:
        os_delete(str(doc.id))
    except Exception:
        logger.exception("Failed to delete document %s from search index", doc.id)
    db.delete(doc)
    db.commit()
    return Response(status_code=204)
# Search
@app.get("/search")
def search(q: str = Query(..., min_length=1, max_length=500), path_prefix: str | None = None, user: User = Depends(current_user)):
    try:
        res=os_search(q, size=25, path_prefix=path_prefix); hits=[]
        for h in res.get("hits",{}).get("hits",[]):
            src=h.get("_source",{})
            hits.append({"id":src.get("id"),"filename":src.get("filename"),"title":src.get("title"),
                         "path":src.get("path"),"content_type":src.get("content_type"),"score":h.get("_score"),
                         "snippet":" ... ".join(h.get("highlight",{}).get("text", src.get("text","")[:200:])) if h.get("highlight") else None})
        return {"count": len(hits), "hits": hits}
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(500, "Search failed")
# Share links
@app.post("/shares")
def create_share(body: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc_id=body.get("document_id"); hours=int(body.get("hours") or 24)
    if not doc_id:
        raise HTTPException(400, "document_id required")
    doc=db.get(Document, _parse_uuid(doc_id))
    if not doc:
        raise HTTPException(404,"document not found")
    if hours < 1:
        hours = 1
    if hours > 168:
        hours = 168
    password = body.get("password")
    password_hash = None
    if password:
        password = password.strip()
        if len(password) < 4 or len(password) > 128:
            raise HTTPException(400, "password length must be between 4 and 128 characters")
        password_hash = hash_password(password)
    token=uuid.uuid4().hex; expires=datetime.now(timezone.utc) + timedelta(hours=hours)
    share=ShareLink(token=token, document_id=doc.id, created_by=user.id, expires_at=expires, password_hash=password_hash); db.add(share); db.commit()
    return {"token": token, "expires_at": expires, "requires_password": bool(password_hash)}
@app.get("/shares/{token}")
def resolve_share(token: str, password: str | None = Query(default=None), watermark: str | None = Query(default=None), db: Session = Depends(get_db)):
    now=datetime.now(timezone.utc)
    share=db.query(ShareLink).options(joinedload(ShareLink.document)).filter(ShareLink.token==token, ShareLink.expires_at>now).first()
    if not share: raise HTTPException(404,"invalid or expired")
    if share.password_hash:
        if not password or not verify_password(password, share.password_hash):
            raise HTTPException(401,"password required")
    document = share.document
    if not document:
        raise HTTPException(500,"document missing")
    if watermark:
        sanitized = normalize_watermark_text(watermark)
        if not sanitized:
            raise HTTPException(400,"watermark must contain printable characters")
        content_type = (document.content_type or "").lower()
        filename = (document.filename or "")
        if "pdf" not in content_type and not filename.lower().endswith(".pdf"):
            raise HTTPException(400,"watermark supported for PDFs only")
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
            raise HTTPException(500,"unable to generate watermark") from exc
    url=presign_get(document.s3_key, 300)
    return {"url": url, "filename": document.filename, "content_type": document.content_type}

# Folder Management
from .folders import validate_folder_path, get_parent_path, get_folder_name, create_folder_record, rename_folder_and_docs, delete_folder_and_docs

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
    return {"path": folder.path, "name": folder.name, "parent_path": folder.parent_path, "created": True, "created_at": folder.created_at}

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
        documents_updated = rename_folder_and_docs(db, user.id, old_path, new_path.split('/')[-1])
        db.commit()
        return {"old_path": old_path, "new_path": new_path, "documents_updated": documents_updated, "success": True}
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
    if not path: raise HTTPException(400, "path is required")
    path = validate_folder_path(path)
    try:
        documents_deleted, files_removed = delete_folder_and_docs(db, user.id, path, recursive, delete_object, os_delete, logger)
        db.commit()
        return {"deleted": True, "path": path, "documents_deleted": documents_deleted, "files_removed": files_removed}
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
        doc_paths = [(path, owner_id) for path, owner_id in doc_paths 
                     if not path.startswith('private/') or owner_id == user.id]
        # Convert back to tuple format
        doc_paths = [(path,) for path, _ in doc_paths]
        
        empty_folders_stmt = select(Folder)
        empty_folders = db.execute(empty_folders_stmt).scalars().all()
        # Filter out private folders from other users
        empty_folders = [f for f in empty_folders 
                        if not f.path.startswith('private/') or f.owner_user_id == user.id]
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
        if not path: continue
        parts = path.split("/")
        for i in range(len(parts)):
            folder_path = "/".join(parts[:i+1])
            if folder_path not in folder_map:
                folder_map[folder_path] = {"path": folder_path, "name": get_folder_name(folder_path), "parent_path": get_parent_path(folder_path), "document_count": 0, "is_empty": False, "created_at": None}
    for (path,) in doc_paths:
        if path and path in folder_map: folder_map[path]["document_count"] += 1
    for folder in empty_folders:
        if folder.path not in folder_map:
            folder_map[folder.path] = {"path": folder.path, "name": folder.name, "parent_path": folder.parent_path, "document_count": 0, "is_empty": True, "created_at": folder.created_at}
        else:
            folder_map[folder.path]["created_at"] = folder.created_at
    for folder_path in folder_map:
        if folder_map[folder_path]["document_count"] == 0: folder_map[folder_path]["is_empty"] = True
    folders = [FolderInfo(**f) for f in folder_map.values()]
    folders.sort(key=lambda f: f.path)
    return FolderListResponse(folders=folders)

# Utility routes
@app.get("/ui/", include_in_schema=False)
async def ui_root():
    """Redirect /ui/ to wizard"""
    return RedirectResponse(url="/ui/wizard.html")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Serve favicon from assets"""
    import os
    # Try to find the logo file in UI assets
    for ui_path in [Path("/code/ui"), Path("/ui"), Path("ui")]:
        favicon_path = ui_path / "assets" / "LOGOTOBEUSED.png"
        if favicon_path.exists():
            return FileResponse(
                str(favicon_path),
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=604800"}  # Cache for 1 week
            )
    # Fallback: return transparent 1x1 PNG
    transparent_png = bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D,
        0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
        0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4, 0x89, 0x00, 0x00, 0x00,
        0x0A, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9C, 0x63, 0x00, 0x01, 0x00, 0x00,
        0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x49,
        0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82
    ])
    return Response(
        content=transparent_png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=604800"}
    )
