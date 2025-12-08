# Database Migrations

This directory contains PostgreSQL migration files for the VeriCase Analysis database.

## Migration Order

Migrations are applied in chronological order by filename. Each migration is designed to be idempotent (safe to run multiple times).

## PyCharm/DataGrip SQL Inspection Warnings

You may see SQL inspection warnings in your IDE. **These are false positives** and can be safely ignored:

### Common Warnings & Why They're Safe

1. **"Unable to resolve table 'users'"**
   - ✓ The `users` table is created in `20240101_initial_schema.sql`
   - ✓ Later migrations reference it correctly
   - ❌ PyCharm doesn't track cross-file dependencies

2. **"Unknown database function 'gen_random_uuid'"**
   - ✓ This function comes from PostgreSQL's `pgcrypto` extension
   - ✓ Installed by: `CREATE EXTENSION IF NOT EXISTS "pgcrypto"`
   - ❌ PyCharm doesn't load extension functions

3. **"Unable to resolve column 'id'"**
   - ✓ Columns exist after migrations run in order
   - ❌ PyCharm analyzes each file independently

4. **"Missing column alias" / "VALUES clause cardinality"**
   - ✓ SQL is valid PostgreSQL syntax
   - ❌ PyCharm's SQL parser is conservative

## Running Migrations

### Development (Docker)
```bash
docker-compose up postgres
# Migrations run automatically on API startup
```

### Manual Execution
```bash
psql -h localhost -p 55432 -U vericase -d vericase -f 20240101_initial_schema.sql
# Continue with other migrations in order...
```

## Migration Best Practices

1. **Always use IF NOT EXISTS** for tables, columns, indexes
2. **Always use IF EXISTS** for checks before drops
3. **Use DO blocks** for complex conditional logic
4. **Add comments** explaining the purpose
5. **Test migrations** on a copy of production data

## Verifying Migration Success

```sql
-- Check tables exist
\dt

-- Check columns in users table
\d users

-- Check extensions loaded
\dx

-- Verify data
SELECT COUNT(*) FROM users;
```

## Troubleshooting

If migrations fail:
1. Check PostgreSQL logs: `docker logs pst-analysis-engine-postgres-1`
2. Verify database connection: `psql -h localhost -p 55432 -U vericase`
3. Check migration order: migrations must run sequentially
4. Look for actual errors (not IDE warnings)

## IDE Configuration

To reduce false warnings in PyCharm/DataGrip:

1. **Set SQL Dialect**: Right-click migrations folder → SQL Dialect → PostgreSQL
2. **Configure Data Source**: Add PostgreSQL connection to populate schema
3. **Disable Inspections**: Settings → Editor → Inspections → SQL → Uncheck overly strict rules
4. **Or ignore**: These warnings don't affect migration execution

## Schema Changes

When adding new migrations:
- Use format: `YYYYMMDD_description.sql`
- Make migrations idempotent with IF EXISTS/IF NOT EXISTS
- Test with fresh database first
- Document purpose in migration file header
