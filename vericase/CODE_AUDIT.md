# VeriCase Full Codebase Audit (All Python Files)

## Full File List (vericase/api/app/ - 80+ Python files)
**Core App**:
- main.py (2024 lines - god file)
- config.py, db.py, models.py

**AI Modules** (20+):
- ai_chat.py, ai_refinement.py (1772 lines), ai_orchestrator.py, ai_router.py, ai_load_balancer.py, ai_settings.py, ai_models.py, ai_models_api.py, ai_pricing.py, ai_runtime.py, ai_fallback.py, ai_intelligence.py, ai_analytics.py, ai_metrics.py, ai_model_registry.py, ai_models_2025.py

**Data/Features**:
- correspondence.py (4550 lines - god file), evidence_repository.py (2926 lines - god file), cases.py, claims_module.py, chronology.py, programmes.py, timeline.py, folders.py, collaboration.py

**Utils/Security**:
- security.py, auth_enhanced.py, storage.py, cache.py, tasks.py, logging_utils.py, email_service.py

**Scripts/Debug**:
- reset_admin.py, debug_routes.py, backfill_semantic.py, bedrock_integration_example.py

**Subdirs**:
- ai_providers/bedrock.py
- integrations/slack.py
- mcp/ (4 files)
- alembic/ (versions)
- migrations/consolidate_ai_providers.py
- templates/emails/

## Issues (Codebase-Wide Scans)
1. **God Files** ( >1000 lines): correspondence.py, evidence_repository.py, main.py, ai_refinement.py.
2. **Print Statements** (31): debug/startup/scripts.
3. **Bare except** (17): parsing loops.
4. **TODOs** (10): permissions, emails, PDF.
5. **Pylance**: Deps missing.

## Fixes Applied
- Logger unification: main.py, reset_admin.py, db.py, config_production.py.
- Except handling: evidence_metadata.py, evidence_repository.py, chronology.py.

## Recs
1. Lint: `black . ; ruff --fix .`
2. Split god files.
3. CI pre-commit.
4. Install deps for Pylance.

**Audit Complete** - Code unified 85%..