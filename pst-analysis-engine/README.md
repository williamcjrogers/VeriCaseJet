# VeriCase Analysis Platform

**Forensic-grade PST email analysis and legal dispute intelligence.**

![Status](https://img.shields.io/badge/Status-Active_Development-green)
![Docker](https://img.shields.io/badge/Deployment-Docker_Compose-blue)
![Python](https://img.shields.io/badge/Python-3.11-yellow)

---

## ⚡ **NEW: Ultra-Fast Local Development**

**Stop waiting for CI/CD!** Test locally in 2 minutes or develop with instant hot-reload:

- **📖 [QUICK_START.md](QUICK_START.md)** - Pull from Docker Hub and run in 2 minutes
- **📖 [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md)** - Full local dev guide with hot reload

```powershell
# Pull latest from Docker Hub (fastest)
.\scripts\dev.ps1 pull
.\scripts\dev.ps1 start -Hub

# OR build locally with hot reload
.\scripts\dev.ps1 start
```

**Time saved:** From 10+ minutes per iteration to 1 second! 🚀

---

## 🚨 Forensic Architecture Warning

*Read this before touching the code. This project has been aggressively cleaned, and this document is the single source of truth.*

### 1. The "Real" Application

The active application lives entirely within this `pst-analysis-engine/` directory.

| Component  | Location      | Description                                          |
|------------|---------------|------------------------------------------------------|
| **API**    | `api/app/`    | FastAPI backend. The brain of the system.            |
| **Worker** | `worker_app/` | Celery tasks for PST extraction.                     |
| **UI**     | `ui/`         | Static HTML/JS. Served by the API at `/ui`.          |
| **Config** | `.env`        | **Required.** Copy from `.env.example`.              |

### 2. Known Structural Issues (Now Resolved)

This project previously suffered from duplicated "zombie" directories, multiple startup scripts, and orphaned code. These have been removed. The canonical entry point is `docker-compose up`. Do not re-introduce wrapper scripts or alternate startup methods.

---

## 🚀 Quick Start (The Only Way)

**Prerequisites:** Docker Desktop (allocate 8GB+ RAM).

### 1. Configure Environment

In this directory (`pst-analysis-engine/`):
```
cp env.example .env
```

**Critical:** Edit `.env` and set `JWT_SECRET`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, and `AG_GRID_LICENSE_KEY`. The application will not seed an admin user without these values.

### 2. Start System

We use standard Docker Compose. No wrapper scripts are needed.

```
docker-compose up -d --build
```

### 3. Access

| Service      | URL                                      | Credentials                               |
|--------------|------------------------------------------|-------------------------------------------|
| **Dashboard**| http://localhost:8010/ui/dashboard.html  | Defined in `.env`                         |
| **API Docs** | http://localhost:8010/docs               | Public                                    |
| **MinIO**    | http://localhost:9001                    | `minioadmin` / `minioadmin` (Change in `.env`!) |

---

## 🛠️ Operational Commands

### View Logs
```
# Follow all logs
docker-compose logs -f

# Follow a specific service (e.g., the worker)
docker-compose logs -f worker
```

### Reset Database (Destructive)

Wipes all data and starts fresh.
```
docker-compose down -v
docker-compose up -d
```

### Shell Access
```
# Access the API container
docker-compose exec api bash

# Access the Database
docker-compose exec postgres psql -U vericase -d vericase
```

### Clean Slate (delete all local data)

Need the next run to behave like the very first one (no prior uploads, evidence, or database files)? Run the reset script from the repository root:

```powershell
pwsh ops/setup/reset_local_state.ps1
# add -SkipDocker if containers are already stopped
```

```bash
# macOS / Linux
./ops/setup/reset_local_state.sh
```

The script:

- runs `docker-compose down -v` inside `pst-analysis-engine/`
- deletes `pst-analysis-engine/data`, `uploads`, `evidence`, and `vericase.db`

After it finishes, the next `docker-compose up` starts completely fresh.

---

## ⚠️ Critical Maintenance Notes

### AG-Grid License

The AG-Grid Enterprise license key is loaded from the `AG_GRID_LICENSE_KEY` environment variable. It is served by the backend and fetched by the UI at runtime. **Do not hardcode it in the HTML.**

### Admin Bootstrap

The admin account is created only when `ADMIN_EMAIL` and `ADMIN_PASSWORD` are set. Empty values skip creation to prevent shipping known credentials.

### Database Migrations

Migrations are managed by Alembic. After modifying `api/app/models.py`, generate a new migration:

```
docker-compose exec api alembic revision --autogenerate -m "Your migration description"
docker-compose exec api alembic upgrade head
```

---

## 🧱 Architecture & Data Flow

1. **Upload:** Browser requests a presigned URL → uploads PST to MinIO.
2. **Queue:** API records the upload and pushes a task into Redis.
3. **Process:** Celery worker ingests PST via `libpff`, extracts emails, threads, and attachments.
4. **Index:** Structured data stored in PostgreSQL + OpenSearch; binaries in MinIO.
5. **Analyze:** UI queries API for search, timelines, AI summaries, and correspondence browsing.

---

## 📂 Directory Reference

```
api/             FastAPI application (routers, models, services)
worker_app/      Celery worker entrypoints and task orchestration
worker/          Worker Dockerfile + runtime config
ui/              Static HTML/JS UI served from /ui
docs/            Consolidated guides, deployment runbooks, architecture notes
ops/             Deployment and utility scripts (PowerShell, Bash, Python)
_logs/           Historical fix logs and forensic notes (archived)
docker-compose.yml  Complete local stack definition
requirements.txt     Unified dependency list (API + worker + dev tools)
```

---

## 🧪 Testing

```
# API / shared tests
docker-compose exec api pytest

# Worker-specific tests (if defined)
docker-compose exec worker pytest
```

---

## 🔐 Security Checklist

- Rotate `JWT_SECRET`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, and all data-store credentials before any deployment.
- Enable HTTPS termination at your ingress (App Runner, ALB, or reverse proxy).
- Configure IAM policies per `docs/deployment/DEPLOYMENT-SECURITY-CHECKLIST.md`.
- Review `ops/` scripts before running to ensure they reflect your environment.

---

## 📚 Additional Documentation

- Setup Guide: `docs/guides/EASY_SETUP.md`
- Developer Guide: `docs/guides/START_HERE.md`
- Deployment Guides: `docs/deployment/`
- Architecture Overview: `docs/VERICASE_ARCHITECTURE.md`

---

## ✅ Status

- **Docker stack:** Verified (API, Worker, PostgreSQL, Redis, OpenSearch, MinIO, Tika)
- **PST processing:** Production-ready (libpff pipeline)
- **AI integrations:** Feature-flagged, requires valid API keys
- **UI:** Served statically via FastAPI `/ui`

---

## 📄 License

Proprietary © VeriCase / Quantum Construction Solutions (see LICENSE).
