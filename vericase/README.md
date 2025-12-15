# VeriCase

**Forensic-grade PST email analysis and legal dispute intelligence.**

![Status](https://img.shields.io/badge/Status-Production-green)
![Docker](https://img.shields.io/badge/Deployment-Docker_Compose-blue)
![Python](https://img.shields.io/badge/Python-3.11-yellow)

---

## Quick Start

**Prerequisites:** Docker Desktop (allocate 8GB+ RAM).

### 1. Configure Environment

```bash
cd vericase
cp .env.example .env
```

Edit `.env` and set `JWT_SECRET`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, and `AG_GRID_LICENSE_KEY`.

### 2. Start System

```bash
docker-compose up -d --build
```

### 3. Access

| Service       | URL                                     | Credentials                 |
| ------------- | --------------------------------------- | --------------------------- |
| **Dashboard** | http://localhost:8010/ui/dashboard.html | Defined in `.env`           |
| **API Docs**  | http://localhost:8010/docs              | Public                      |
| **MinIO**     | http://localhost:9001                   | `minioadmin` / `minioadmin` |

---

## Project Structure

```
vericase/
├── api/             # FastAPI backend
│   ├── app/         # Application code
│   ├── migrations/  # Database migrations
│   └── Dockerfile
├── worker_app/      # Celery background workers
├── ui/              # Production static UI (HTML/CSS/JS)
├── ops/             # Operations scripts
├── k8s/             # Kubernetes deployment configs
├── docs/            # All documentation
├── docker-compose.yml       # Local development
└── docker-compose.prod.yml  # Production deployment
```

---

## Operational Commands

### View Logs

```bash
docker-compose logs -f          # All logs
docker-compose logs -f worker   # Specific service
```

### Reset Database (Destructive)

```bash
docker-compose down -v
docker-compose up -d
```

### Shell Access

```bash
docker-compose exec api bash
docker-compose exec postgres psql -U vericase -d vericase
```

---

## Tracing (optional)

Tracing is **off by default**. To enable OpenTelemetry tracing for both the API and worker:

- Set in `vericase/.env`:
  - `OTEL_TRACING_ENABLED=true`
  - `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` (OTLP/HTTP)
  - Optional: `OTEL_SERVICE_NAME=vericase-api` (override per-container if desired)

If you use **AI Toolkit** tracing, start its local collector from VS Code Command Palette:

- `ai-mlstudio.tracing.open`

If `OTEL_EXPORTER_OTLP_ENDPOINT` is not set, spans fall back to console output.

---

## Database Migrations

VeriCase uses **Alembic** to manage database schema changes.

- Containers run `alembic upgrade head` on startup (with a legacy fallback to `/code/apply_migrations.py` if Alembic is unavailable).
- For manual migrations in Docker Compose, run:
  ```bash
  docker-compose -f docker-compose.prod.yml run --rm api alembic upgrade head
  ```

The initial Alembic revision (`0001_vericase_baseline`) is a no-op baseline used to mark the current schema.

---

## Architecture & Data Flow

1. **Upload:** Browser requests presigned URL → uploads PST to MinIO
2. **Queue:** API records upload and pushes task into Redis
3. **Process:** Celery worker ingests PST via `libpff`, extracts emails/attachments
4. **Index:** Structured data stored in PostgreSQL + OpenSearch; binaries in MinIO
5. **Analyze:** UI queries API for search, timelines, AI summaries

---

## Documentation

- [AI Full Power Mode](docs/AI_FULLPOWER.md) — Enable all 6 AI providers + features
- [AI Configuration Guide](docs/AI_CONFIGURATION_GUIDE.md) — Per-provider setup
- [AI Key Management](AI_KEY_MANAGEMENT.md) — Secrets Manager & rotation
- [Deployment Guide](docs/deployment/DEPLOYMENT.md)
- [Local Development](docs/deployment/LOCAL_DEVELOPMENT.md)
- [AWS Setup](docs/aws/AWS_SETUP_GUIDE.md)
- [Security Guide](docs/security/SECURITY.md)

---

## Operations Scripts

All scripts are in `ops/`:

| Script                         | Purpose                 |
| ------------------------------ | ----------------------- |
| `deploy.sh` / `deploy.ps1`     | Deploy to local/EC2/EKS |
| `diagnose.sh` / `diagnose.ps1` | Run diagnostics         |
| `setup-aws.sh`                 | Configure AWS services  |
| `reset-db.sh`                  | Reset database          |

---

## Security Checklist

- Rotate `JWT_SECRET`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` before deployment
- Enable HTTPS termination at your ingress (ALB, Nginx, etc.)
- Review `ops/` scripts before running

---

## Status

- **Docker stack:** Production-ready
- **PST processing:** Production-ready (libpff pipeline)
- **AI integrations:** Feature-flagged, requires valid API keys
- **Deployment:** EKS (primary), EC2 (backup)

---

## License

Proprietary © VeriCase / Quantum Construction Solutions
