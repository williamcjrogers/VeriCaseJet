#!/bin/bash
set -e

echo "=== VeriCase Startup ==="

echo "Waiting for Postgres to accept connections..."
python - <<'PY'
import os
import sys
import time

import psycopg2

database_url = os.getenv("DATABASE_URL", "")
if database_url.startswith("postgresql+psycopg2://"):
  database_url = database_url.replace("postgresql+psycopg2://", "postgresql://", 1)

deadline = time.time() + int(os.getenv("DB_WAIT_SECONDS", "60"))
last_error = None

while time.time() < deadline:
  try:
    conn = psycopg2.connect(database_url)
    conn.close()
    print("Postgres is ready.")
    sys.exit(0)
  except Exception as exc:
    last_error = exc
    time.sleep(2)

print(f"Postgres did not become ready in time: {last_error}")
sys.exit(1)
PY

echo "Running migrations..."

# Run Alembic migrations first (handles incremental schema changes)
set +e
alembic upgrade head
alembic_status=$?
set -e

if [ "$alembic_status" -ne 0 ]; then
  echo "Alembic migrations failed with exit code $alembic_status (may be expected on fresh DB)"
fi

# Always run legacy SQL migrations to ensure base tables exist
# This is safe because all CREATE statements use IF NOT EXISTS
if [ "${SKIP_SQL_MIGRATIONS:-false}" = "true" ]; then
  echo "Skipping legacy SQL migrations (SKIP_SQL_MIGRATIONS=true)"
elif [ -f "/code/apply_migrations.py" ]; then
  echo "Applying SQL migrations to ensure all tables exist..."
  python /code/apply_migrations.py || echo "Warning: Some SQL migrations may have had issues (usually harmless)"
fi

if [ "${SKIP_SQL_MIGRATIONS:-false}" = "true" ]; then
  echo "Creating/resetting admin user (async, SKIP_SQL_MIGRATIONS=true)..."
  (python -m app.reset_admin || echo "Warning: Could not reset admin user") &
else
  echo "Creating/resetting admin user..."
  python -m app.reset_admin || echo "Warning: Could not reset admin user"
fi

echo "Syncing AI settings from environment/Secrets Manager..."
if [ "${SKIP_SQL_MIGRATIONS:-false}" = "true" ]; then
  (python -c "
import os
import sys
sys.path.insert(0, '/code')

# First load keys from Secrets Manager to environment
try:
    from app.config_production import load_ai_keys_from_secrets_manager
    load_ai_keys_from_secrets_manager()
except Exception as e:
    print(f'Note: Could not load from Secrets Manager: {e}')

# Then sync to database
try:
    from app.db import SessionLocal
    from app.models import AppSetting
    
    # Optimal models per provider
    AI_MODELS = {
        'openai': ('gpt-4o', 'OpenAI GPT-4o'),
        'anthropic': ('claude-sonnet-4-20250514', 'Claude Sonnet 4'),
        'gemini': ('gemini-2.0-flash', 'Gemini 2.0 Flash'),
        'bedrock': ('amazon.nova-pro-v1:0', 'Amazon Nova Pro'),
        'xai': ('grok-3', 'xAI Grok 3'),
        'perplexity': ('sonar-pro', 'Perplexity Sonar Pro'),
    }
    
    ENV_KEYS = {
        'OPENAI_API_KEY': 'openai_api_key',
        'CLAUDE_API_KEY': 'anthropic_api_key', 
        'GEMINI_API_KEY': 'gemini_api_key',
        'XAI_API_KEY': 'xai_api_key',
        'PERPLEXITY_API_KEY': 'perplexity_api_key',
    }
    
    db = SessionLocal()
    synced = 0
    
    # Sync API keys from env to database
    for env_var, setting_key in ENV_KEYS.items():
        val = os.environ.get(env_var, '').strip()
        if val:
            existing = db.query(AppSetting).filter(AppSetting.key == setting_key).first()
            if not existing:
                db.add(AppSetting(key=setting_key, value=val, description=f'From {env_var}'))
                synced += 1
                print(f'✓ Synced {setting_key}')
            elif not existing.value:
                existing.value = val
                synced += 1
    
    # Set/correct optimal models for configured providers
    for provider, (model, desc) in AI_MODELS.items():
        key_name = f'{provider}_api_key'
        has_key = db.query(AppSetting).filter(AppSetting.key == key_name, AppSetting.value.isnot(None)).first()
        if has_key or (provider == 'bedrock' and os.environ.get('BEDROCK_ENABLED') == 'true'):
            model_key = f'{provider}_model'
            existing = db.query(AppSetting).filter(AppSetting.key == model_key).first()
            if not existing:
                db.add(AppSetting(key=model_key, value=model, description=desc))
                synced += 1
                print(f'✓ Set {provider} model: {model}')
            elif existing.value != model:
                old_val = existing.value
                existing.value = model
                synced += 1
                print(f'✓ Fixed {provider} model: {old_val} -> {model}')
    
    # Set default provider if not set
    if not db.query(AppSetting).filter(AppSetting.key == 'ai_default_provider').first():
        db.add(AppSetting(key='ai_default_provider', value='gemini', description='Default AI provider'))
        synced += 1
    
    db.commit()
    db.close()
    print(f'AI settings sync complete ({synced} updates)')
except Exception as e:
    print(f'Warning: AI settings sync failed: {e}')
" || echo "Warning: AI settings sync encountered issues") &
else
  python -c "
import os
import sys
sys.path.insert(0, '/code')

# First load keys from Secrets Manager to environment
try:
    from app.config_production import load_ai_keys_from_secrets_manager
    load_ai_keys_from_secrets_manager()
except Exception as e:
    print(f'Note: Could not load from Secrets Manager: {e}')

# Then sync to database
try:
    from app.db import SessionLocal
    from app.models import AppSetting
    
    # Optimal models per provider
    AI_MODELS = {
        'openai': ('gpt-4o', 'OpenAI GPT-4o'),
        'anthropic': ('claude-sonnet-4-20250514', 'Claude Sonnet 4'),
        'gemini': ('gemini-2.0-flash', 'Gemini 2.0 Flash'),
        'bedrock': ('amazon.nova-pro-v1:0', 'Amazon Nova Pro'),
        'xai': ('grok-3', 'xAI Grok 3'),
        'perplexity': ('sonar-pro', 'Perplexity Sonar Pro'),
    }
    
    ENV_KEYS = {
        'OPENAI_API_KEY': 'openai_api_key',
        'CLAUDE_API_KEY': 'anthropic_api_key', 
        'GEMINI_API_KEY': 'gemini_api_key',
        'XAI_API_KEY': 'xai_api_key',
        'PERPLEXITY_API_KEY': 'perplexity_api_key',
    }
    
    db = SessionLocal()
    synced = 0
    
    # Sync API keys from env to database
    for env_var, setting_key in ENV_KEYS.items():
        val = os.environ.get(env_var, '').strip()
        if val:
            existing = db.query(AppSetting).filter(AppSetting.key == setting_key).first()
            if not existing:
                db.add(AppSetting(key=setting_key, value=val, description=f'From {env_var}'))
                synced += 1
                print(f'✓ Synced {setting_key}')
            elif not existing.value:
                existing.value = val
                synced += 1
    
    # Set/correct optimal models for configured providers
    for provider, (model, desc) in AI_MODELS.items():
        key_name = f'{provider}_api_key'
        has_key = db.query(AppSetting).filter(AppSetting.key == key_name, AppSetting.value.isnot(None)).first()
        if has_key or (provider == 'bedrock' and os.environ.get('BEDROCK_ENABLED') == 'true'):
            model_key = f'{provider}_model'
            existing = db.query(AppSetting).filter(AppSetting.key == model_key).first()
            if not existing:
                db.add(AppSetting(key=model_key, value=model, description=desc))
                synced += 1
                print(f'✓ Set {provider} model: {model}')
            elif existing.value != model:
                old_val = existing.value
                existing.value = model
                synced += 1
                print(f'✓ Fixed {provider} model: {old_val} -> {model}')
    
    # Set default provider if not set
    if not db.query(AppSetting).filter(AppSetting.key == 'ai_default_provider').first():
        db.add(AppSetting(key='ai_default_provider', value='gemini', description='Default AI provider'))
        synced += 1
    
    db.commit()
    db.close()
    print(f'AI settings sync complete ({synced} updates)')
except Exception as e:
    print(f'Warning: AI settings sync failed: {e}')
" || echo "Warning: AI settings sync encountered issues"
fi

echo "Starting Uvicorn..."
# Use exec to replace shell with uvicorn process
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips '*'
