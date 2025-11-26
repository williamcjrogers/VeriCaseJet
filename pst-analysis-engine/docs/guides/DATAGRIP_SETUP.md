# DataGrip Setup Guide for VeriCase

## 🗄️ Database Management with DataGrip

DataGrip is your dedicated database IDE - more powerful than PyCharm's database tools.

---

## 🚀 Quick Setup

### 1. Open DataGrip

### 2. Add PostgreSQL Connection
```
File → New → Data Source → PostgreSQL

Connection Settings:
  Name: VeriCase Production
  Host: localhost
  Port: 55432
  Database: vericase
  User: vericase
  Password: vericase
  
Advanced:
  ☑️ Auto-reconnect
  ☑️ Keep connection alive
  
Test Connection → Should succeed
Click OK
```

### 3. Add Redis Connection (Optional)
```
File → New → Data Source → Redis

Connection Settings:
  Name: VeriCase Redis
  Host: localhost
  Port: 6379
  Database: 0
  
Test Connection → Should succeed
```

---

## 🔍 Key Features

### ✅ Schema Comparison (Catches Model/DB Mismatches)

**Compare Database to Models:**
```
1. Right-click database → Compare With...
2. Select: Another Database or DDL Script
3. Choose: pst-analysis-engine/api/app/models.py
4. DataGrip shows differences:
   
   Example:
   ⚠️ models.py defines: is_admin (Boolean)
   ✅ Database has: role (ENUM: ADMIN, EDITOR, VIEWER)
   
5. Generate migration SQL:
   → Right-click difference
   → Generate Script
   → Save to: api/migrations/YYYYMMDD_fix_schema.sql
```

### ✅ Query Console (Better than psql)

**Run Complex Queries:**
```sql
-- Find all admin users
SELECT u.email, u.role, u.last_login_at,
       COUNT(DISTINCT p.id) as project_count,
       COUNT(DISTINCT c.id) as case_count
FROM users u
LEFT JOIN projects p ON p.owner_user_id = u.id
LEFT JOIN cases c ON c.owner_id = u.id
WHERE u.role = 'ADMIN'
GROUP BY u.id, u.email, u.role, u.last_login_at;

-- Ctrl+Enter to run
-- Results appear with formatting
-- Export to CSV/JSON/Excel
```

### ✅ Data Editor (Edit Tables Directly)

**Edit Data Inline:**
```
1. Double-click table (e.g., "users")
2. Data editor opens
3. Edit cells directly
4. Press Ctrl+Enter to commit
5. Changes saved to database
```

### ✅ ER Diagram (Visualize Schema)

**Generate Diagram:**
```
1. Right-click database
2. Diagrams → Show Visualization
3. DataGrip generates ER diagram:
   - Shows all 32 tables
   - Foreign key relationships
   - Indexes
   - Constraints
4. Export as PNG/PDF
```

---

## 🎯 Common Tasks

### View All PST Files
```sql
SELECT 
    pf.id,
    pf.filename,
    pf.file_size / 1024 / 1024 as size_mb,
    pf.processing_status,
    pf.total_emails,
    pf.created_at,
    u.email as uploaded_by,
    p.project_name
FROM pst_files pf
JOIN users u ON pf.uploaded_by = u.id
LEFT JOIN projects p ON pf.project_id = p.id
ORDER BY pf.created_at DESC
LIMIT 20;
```

### Check Email Processing Stats
```sql
SELECT 
    COUNT(*) as total_emails,
    COUNT(DISTINCT sender_email) as unique_senders,
    COUNT(DISTINCT CASE WHEN has_attachments THEN id END) as emails_with_attachments,
    MIN(date_sent) as earliest_email,
    MAX(date_sent) as latest_email
FROM email_messages;
```

### Find Orphaned Records
```sql
-- PST files without projects
SELECT pf.* 
FROM pst_files pf
LEFT JOIN projects p ON pf.project_id = p.id
WHERE pf.project_id IS NOT NULL 
  AND p.id IS NULL;
```

### Performance Analysis
```sql
-- Slow queries
SELECT 
    query,
    calls,
    total_time,
    mean_time,
    max_time
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 20;
```

---

## 🔧 Advanced Features

### 1. Schema Migration Generator

**Auto-generate migrations:**
```
1. Make changes to models.py in PyCharm
2. In DataGrip: Compare With → models.py
3. DataGrip shows differences
4. Right-click → Generate Migration Script
5. Review SQL:
   ALTER TABLE users ADD COLUMN new_field VARCHAR(255);
6. Save to: api/migrations/20251119_add_new_field.sql
```

### 2. Data Export/Import

**Export data:**
```
Right-click table → Export Data
→ Format: CSV, JSON, SQL, Excel
→ Choose columns
→ Apply filters
→ Export
```

**Import data:**
```
Right-click table → Import Data
→ Select file (CSV, JSON, SQL)
→ Map columns
→ Preview changes
→ Import
```

### 3. Query History

**Access all queries:**
```
View → Tool Windows → Query History
→ See all queries you've run
→ Re-run with one click
→ Export history
```

### 4. Local History (Time Machine)

**Undo database changes:**
```
Right-click database → Local History → Show History
→ See all schema changes
→ Revert if needed
```

---

## 🎯 Database Maintenance Tasks

### Vacuum & Analyze
```sql
-- Run monthly for performance
VACUUM ANALYZE;

-- Check table sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

### Index Analysis
```sql
-- Find missing indexes
SELECT 
    schemaname,
    tablename,
    attname,
    n_distinct,
    correlation
FROM pg_stats
WHERE schemaname = 'public'
  AND n_distinct > 100
  AND correlation < 0.1
ORDER BY n_distinct DESC;
```

### Connection Monitoring
```sql
-- Active connections
SELECT 
    pid,
    usename,
    application_name,
    client_addr,
    state,
    query,
    state_change
FROM pg_stat_activity
WHERE datname = 'vericase'
ORDER BY state_change DESC;
```

---

## 💡 Tips for VeriCase Specifically

### 1. Monitor PST Processing
```sql
-- Create a live query (refreshes automatically)
SELECT 
    filename,
    processing_status,
    total_emails,
    processed_emails,
    ROUND(processed_emails::numeric / NULLIF(total_emails, 0) * 100, 2) as progress_pct,
    created_at
FROM pst_files
WHERE processing_status IN ('queued', 'processing')
ORDER BY created_at DESC;

-- Right-click → Execute → Auto-refresh every 5 seconds
```

### 2. Email Search Performance
```sql
-- Check if indexes are being used
EXPLAIN ANALYZE
SELECT * FROM email_messages
WHERE sender_email ILIKE '%@example.com%'
  AND date_sent > '2024-01-01';
  
-- If slow, DataGrip suggests indexes
```

### 3. Backup Database
```
Right-click database → SQL Scripts → Dump Data to File
→ Format: SQL
→ Include: Schema + Data
→ Save as: backups/vericase_backup_20251119.sql
```

---

## 🆘 Common Issues

### "Connection refused"
```
1. Ensure Docker Compose is running:
   docker-compose ps
   
2. Check PostgreSQL is up:
   docker logs pst-analysis-engine-postgres-1
   
3. Verify port 55432 is open:
   netstat -ano | findstr :55432
```

### "Too many connections"
```sql
-- Check connection limit
SHOW max_connections;

-- Kill idle connections
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle'
  AND state_change < NOW() - INTERVAL '1 hour';
```

### "Slow queries"
```
DataGrip → Console → Enable Query Profiler
→ See execution time for each query
→ Optimize slow ones
```

---

## 🎯 Next Steps

1. ☐ Open DataGrip
2. ☐ Add VeriCase PostgreSQL connection
3. ☐ Run schema comparison
4. ☐ Generate ER diagram
5. ☐ Set up query console
6. ☐ Create backup schedule

**DataGrip is now your database command center!**

