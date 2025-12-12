<!-- Copilot / AI agent instructions for VeriCaseJet -->

# Copilot Instructions — VeriCaseJet

## Big picture

- Primary deployable is the Docker stack under `vericase/` (see `vericase/docker-compose.yml` and `vericase/docker-compose.prod.yml`).
- Core services: FastAPI API (`vericase/api/`), Celery worker (`vericase/worker_app/`), Postgres, Redis, MinIO (S3-compatible), OpenSearch, and Apache Tika.
- UI has two forms:
  - Production static UI: `vericase/ui/` (served via the API container; mounted in compose).

## Local dev (recommended)

- From `vericase/`: `docker compose up -d --build` (or `docker-compose up -d --build` depending on your Docker install).
- Main entrypoints:
  - UI: `http://localhost:8010/ui/dashboard.html`
  - API docs: `http://localhost:8010/docs`
  - MinIO console (dev compose): `http://localhost:9003`

## Migrations

- Alembic config is `vericase/api/alembic.ini` (migration scripts live under `vericase/api/app/alembic/`).
- Repo docs indicate containers run `alembic upgrade head` on startup with a fallback to `vericase/api/apply_migrations.py`.

## Conventions / where to look

- Backend app code lives under `vericase/api/app/`.
- Default settings seeding script: `vericase/api/init_settings.py`.
- “App runner” diagnostic startup (used in some deployments): `vericase/api/app_runner_start.py`.
- Ops/deploy scripts live in `vericase/ops/` (see `vericase/ops/README.md`).

## Tests

- Python tests live in `tests/` (run from repo root with `pytest`).

## Don’t change lightly

- `vericase/docker-compose.prod.yml`, `vericase/k8s/`, `vericase/nginx/`, and existing Alembic history under `vericase/api/app/alembic/versions/`.
