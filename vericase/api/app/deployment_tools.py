from __future__ import annotations

"""
SSH-based deployment management.
Allows admins to deploy to staging/production and view server status.

SECURITY: Guarded behind ENABLE_SSH_DEPLOYMENT env var. Disabled by default.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Annotated, Any

import asyncssh
from fastapi import APIRouter, Depends, HTTPException

from .config import settings
from .models import User, UserRole
from .security import current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["deployment-tools"])

_SSH_DEPLOYMENT_ENABLED = os.getenv("ENABLE_SSH_DEPLOYMENT", "").lower() in {
    "1",
    "true",
    "yes",
}


def _require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    """Ensure user is an admin and SSH deployment is enabled."""
    if not _SSH_DEPLOYMENT_ENABLED:
        raise HTTPException(
            status_code=404,
            detail="Not found",
        )
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


AdminDep = Annotated[User, Depends(_require_admin)]


async def _run_remote(conn: asyncssh.SSHClientConnection, cmd: str) -> str:
    result = await conn.run(cmd, check=False)
    output = (result.stdout or result.stderr or "").strip()
    if result.exit_status != 0:
        raise RuntimeError(output or f"Command failed: {cmd}")
    return output


@router.post("/deploy/{environment}")
async def deploy_to_environment(environment: str, admin: AdminDep) -> dict[str, Any]:
    """Deploy to staging or production via SSH."""
    if environment not in ("staging", "production"):
        raise HTTPException(status_code=400, detail="Invalid environment")

    if environment == "staging":
        host = settings.STAGING_HOST
        key_path = settings.STAGING_KEY_PATH
    else:
        host = settings.PRODUCTION_HOST
        key_path = settings.PRODUCTION_KEY_PATH

    if not host or not key_path:
        raise HTTPException(
            status_code=400,
            detail="Deployment host/key not configured for this environment",
        )

    deployment_log: list[str] = []
    status = "failed"

    try:
        async with asyncssh.connect(
            host,
            username="ubuntu",
            client_keys=[key_path],
            known_hosts=None,  # manage host keys outside app
        ) as conn:
            deployment_log.append("Creating database backup...")
            deployment_log.append(
                await _run_remote(conn, "pg_dump vericase > /tmp/backup.sql || true")
            )

            deployment_log.append("Pulling latest code...")
            deployment_log.append(
                await _run_remote(conn, "cd /opt/vericase && git pull origin main")
            )

            deployment_log.append("Building Docker images...")
            deployment_log.append(
                await _run_remote(conn, "cd /opt/vericase && docker-compose build")
            )

            deployment_log.append("Running database migrations...")
            deployment_log.append(
                await _run_remote(
                    conn,
                    "cd /opt/vericase && docker-compose run --rm api alembic upgrade head",
                )
            )

            deployment_log.append("Restarting services...")
            deployment_log.append(
                await _run_remote(conn, "cd /opt/vericase && docker-compose up -d")
            )

            deployment_log.append("Running health check...")
            await asyncio.sleep(10)
            try:
                await _run_remote(conn, "curl -fsS http://localhost:8000/health")
                deployment_log.append("Deployment successful!")
                status = "success"
            except Exception as exc:
                deployment_log.append(f"Health check failed: {exc} - rolling back")
                await _run_remote(
                    conn,
                    "cd /opt/vericase && git reset --hard HEAD~1 && docker-compose up -d",
                )
                status = "failed"

    except Exception as e:
        logger.exception("Deployment failed: %s", e)
        deployment_log.append(f"Deployment failed: {e}")

    return {
        "environment": environment,
        "status": status,
        "log": deployment_log,
        "timestamp": datetime.now(timezone.utc),
        "triggered_by": str(admin.id),
    }


@router.get("/server-status")
async def get_server_status(admin: AdminDep) -> dict[str, Any]:
    """Get status of staging and production servers via SSH."""
    servers: dict[str, Any] = {}

    for env in ("staging", "production"):
        host = settings.STAGING_HOST if env == "staging" else settings.PRODUCTION_HOST
        key_path = (
            settings.STAGING_KEY_PATH
            if env == "staging"
            else settings.PRODUCTION_KEY_PATH
        )

        if not host or not key_path:
            servers[env] = {"error": "host/key not configured"}
            continue

        try:
            async with asyncssh.connect(
                host,
                username="ubuntu",
                client_keys=[key_path],
                known_hosts=None,
            ) as conn:
                uptime = await _run_remote(conn, "uptime")
                disk = await _run_remote(conn, "df -h / | tail -1")
                docker_ps = await _run_remote(
                    conn, 'docker ps --format "{{.Names}}: {{.Status}}"'
                )
                servers[env] = {
                    "uptime": uptime.strip(),
                    "disk_usage": disk.strip(),
                    "containers": [c for c in docker_ps.split("\n") if c.strip()],
                }
        except Exception as exc:
            servers[env] = {"error": str(exc)}

    return servers
