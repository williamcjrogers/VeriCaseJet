### VeriCase — Development Guidelines (Project-Specific)

Last verified: 2025-12-08

This document captures build, configuration, testing, and code-quality specifics for this repository, focused on the active application in `vericase/`. It assumes an experienced developer and omits generic material.

#### Components overview (source of truth)

- Backend/API: `vericase/api/app` (FastAPI). Exposed via Docker Compose on http://localhost:8010
- Worker: `vericase/worker_app` (Celery). Tasks names are rooted under `worker_app.worker.*` and are referenced from API routes.
- UI (served by API): `vericase/ui` (static HTML/CSS/JS). This repository intentionally does not use Vite/React.

Key configs:

- `vericase/docker-compose.yml` — canonical local runtime. Avoid wrapper scripts; use Compose directly.
- `vericase/.env` — required. Copy from `.env.example` and set secrets before starting.
- `vericase/pyrightconfig.json` — Based Pyright typing setup with two execution environments (`api/app`, `worker_app`).
- `vericase/pyproject.toml` — centralizes Black, Ruff, Pylint, and Based Pyright options.

---

### Build and configuration

Backend/Worker (Dockerized, recommended):

1. In `vericase/`, create `.env` from the example:
   - Windows PowerShell: `Copy-Item .env.example .env`
   - Bash: `cp .env.example .env`
2. Set at minimum in `.env`:
   - `JWT_SECRET` (non-empty)
   - `ADMIN_EMAIL`, `ADMIN_PASSWORD`
   - `AG_GRID_LICENSE_KEY` (UI requires this to fully enable AG Grid Enterprise)
3. Start services:
   - `docker-compose up -d --build`
4. Access:
   - API Docs: http://localhost:8010/docs
   - Dashboard: http://localhost:8010/ui/dashboard.html (credentials from `.env`)

Frontend:

- Not used. UI changes are made directly in `vericase/ui/*.html`.

Local Python (non-Docker) notes:

- If you choose to run tools/tests locally, use Python 3.11 (matches `pyrightconfig.json`).
- Unified deps (API + worker + dev tools) live in `vericase/requirements.txt`. Typical flow:
  - `cd vericase`
  - `python -m venv .venv; .\.venv\Scripts\Activate.ps1` (Windows) or `source .venv/bin/activate`
  - `pip install -r requirements.txt`

---

### Testing

There are two test runners in use:

- Standard library `unittest` (always available) — safe for quick, isolated tests.
- `pytest` (configured in `setup.cfg`, used when dependencies are installed) — test discovery under `tests/`, pattern `test_*.py`.

Important project-specific notes:

- The `tests/` directory may contain heavyweight/integration tests (DB, Celery). When running ad-hoc checks, select a filename pattern to avoid pulling in everything.
- `setup.cfg` includes pytest config, but you are not required to use pytest for simple checks.

Guidelines for adding new tests

- `unittest` quick checks:
  - Place files under `vericase/tests/`, name them with a unique prefix to target them via `-p` (e.g., `fast_*` or `unit_*`).
  - Execute with: `python -m unittest discover -s vericase/tests -p "unit_*.py"`
- `pytest` suite (after `pip install -r requirements.txt`):
  - Write tests under `vericase/tests/` following `test_*.py` naming.
  - Run the full suite: `pytest -q`
  - Selective: `pytest -q tests/test_file.py::TestClass::test_case`

---

### Code style, quality, and static analysis

Centralized in `vericase/pyproject.toml` and `pyrightconfig.json`:

- Black (`[tool.black]`)
  - `line-length = 88`
  - Standard include/exclude; rely on pyproject discovery.
  - Usage: `black .` (run from `vericase/`).
- Ruff (`[tool.ruff]`, `[tool.ruff.lint]`)
  - Project-specific ignores: `E712`, `E402`; per-file ignores for `tests/test_models_migration.py` and a couple API modules.
  - Usage: `ruff check .` and `ruff check --fix .`
- Based Pyright (`[tool.basedpyright]` in `pyproject.toml` and `pyrightconfig.json`)
  - Type checking mode: `basic`.
  - Includes: `api/app`, `worker_app` (note: not a typical `src/` layout).
  - Usage (if installed): `basedpyright` or `pyright` in `vericase/`.
- Pylint (`[tool.pylint]`)
  - Ignores virtualenv/caches by default.

Conventions and pitfalls:

- Import paths: tooling is configured to treat `api/app` and `worker_app` as roots. In editors, add those to `PYTHONPATH` if running locally outside Docker.
- Celery task names are stable API: `worker_app.worker.ocr_and_index`, `worker_app.worker.process_pst_file`. Changing names requires updating both worker definitions and API call sites.
- Static UI is served from `vericase/ui`.

---

### Operational helpers

Common Docker workflows (in `vericase/`):

- Tail logs: `docker-compose logs -f` or service-specific `docker-compose logs -f worker`
- Reset state (destructive): `docker-compose down -v` then `docker-compose up -d`
- Container shells:
  - API: `docker-compose exec api bash`
  - Postgres: `docker-compose exec postgres psql -U vericase -d vericase`

---

### Appendix — What was validated for this guideline

- Confirmed presence of key configs: `docker-compose.yml`, `.env.example`, `pyproject.toml`, `pyrightconfig.json`, `setup.cfg`.
- Folder structure reorganized from `pst-analysis-engine/` to `vericase/` on 2025-12-08.
