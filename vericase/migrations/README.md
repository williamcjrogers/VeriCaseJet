# Programme Indexes Migration

This migration creates two indexes to improve query performance on the `programmes` table:

- `idx_programmes_case_id` on `case_id`
- `idx_programmes_document_id` on `document_id`

The SQL uses `CREATE INDEX IF NOT EXISTS`, so it is idempotent and safe to run multiple times.


## Files

- `migrations/add_programme_indexes.sql`


## Prerequisites

- PostgreSQL connection string (libpq format), e.g. `postgresql://user:pass@host:5432/dbname`
- Appropriate network access and credentials to your database

Note: If your environment variable is in SQLAlchemy format (e.g. `postgresql+psycopg2://...`), convert it to libpq format by removing `+psycopg2` when using `psql`.


## Option A: Run with psql

```bash
# If DATABASE_URL is in SQLAlchemy format, convert it first:
DB_URL_PSQL="${DATABASE_URL/postgresql+psycopg2:/postgresql:}"

psql "$DB_URL_PSQL" -f migrations/add_programme_indexes.sql
```


## Option B: Run from Docker (psql inside container)

If you have a running PostgreSQL container, exec into it and run the script. Replace placeholders with your container name, user, and database:

```bash
docker exec -i <postgres_container_name> \
  psql -U <db_user> -d <db_name> -f /path/inside/container/add_programme_indexes.sql
```

If the script is only on the host, you can pipe it:

```bash
docker exec -i <postgres_container_name> psql "postgresql://<user>:<pass>@localhost:5432/<db>" < migrations/add_programme_indexes.sql
```


## Option C: Run via Python + SQLAlchemy

```bash
python - <<'PY'
import os
from sqlalchemy import create_engine, text

db_url = os.getenv("DATABASE_URL", "").replace("postgresql+psycopg2://", "postgresql://", 1)
sql = open("migrations/add_programme_indexes.sql", "r", encoding="utf-8").read()

engine = create_engine(db_url, future=True)
with engine.connect() as conn:
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            conn.execute(text(s))
    conn.commit()
print("Indexes created (IF NOT EXISTS).")
PY
```


## Verification

```sql
-- In psql
\d programmes
-- or
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'programmes';
```

You should see:

- `idx_programmes_case_id`
- `idx_programmes_document_id`

# Database Migrations

This directory contains SQL migration scripts for the PST Analysis Engine database.

## Running Migrations

### Using psql (PostgreSQL)
```bash
psql -U your_username -d your_database -f migrations/add_programme_indexes.sql
```

### Using Docker
```bash
docker exec -i postgres_container psql -U postgres -d vericase < migrations/add_programme_indexes.sql
```

### Using Python/SQLAlchemy
```python
from sqlalchemy import text
from app.db import engine

with engine.connect() as conn:
    with open('migrations/add_programme_indexes.sql', 'r') as f:
        conn.execute(text(f.read()))
    conn.commit()
```

## Migration Files

- `add_programme_indexes.sql` - Adds performance indexes on programmes.case_id and programmes.document_id
