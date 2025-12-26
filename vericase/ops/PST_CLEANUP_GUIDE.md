# PST File Cleanup Guide

This guide explains how to clear pending and failed PST files from VeriCase.

## Quick Start

### Option 1: Using the API (Recommended)

```powershell
# Preview what would be deleted (dry-run)
.\vericase\ops\clear-pst-files.ps1 -ProjectId "your-project-id"

# Actually delete failed and stuck PSTs
.\vericase\ops\clear-pst-files.ps1 -ProjectId "your-project-id" -Apply

# Or for a specific case
.\vericase\ops\clear-pst-files.ps1 -CaseId "your-case-id" -Apply
```

### Option 2: Direct Database Access

```bash
# Preview
python vericase/ops/clear-pst-files.py --project-id "your-project-id"

# Actually delete
python vericase/ops/clear-pst-files.py --project-id "your-project-id" --apply
```

## Authentication Setup

### For API Method (PowerShell script)

Create a token file at `~/.vericase-token`:

1. Login to VeriCase UI
2. Open browser console (F12)
3. Run: `localStorage.getItem('token')`
4. Save the token to `~/.vericase-token`

Or on Windows PowerShell:
```powershell
"your-jwt-token-here" | Out-File -FilePath "$HOME\.vericase-token" -NoNewline
```

### For Database Method (Python script)

Set the DATABASE_URL environment variable or use the default:
```bash
export DATABASE_URL="postgresql://user:pass@host:5432/vericase"
```

Or pass it via command line:
```bash
python clear-pst-files.py --database-url "postgresql://..." --apply
```

## What Gets Deleted

The cleanup process removes:
- ✅ PST file records from `pst_files` table
- ✅ All related email messages from `email_messages` table
- ✅ All related email attachments from `email_attachments` table
- ✅ All related evidence items from `evidence_items` table
- ❌ S3 objects (files remain in storage)

## Cleanup Criteria

By default, the scripts delete PST files that are:

1. **Failed** - processing_status = 'failed'
2. **Stuck** - processing/queued for more than 1 hour (configurable)
3. **Duplicates** - same filename and size, no emails extracted

### Filter Options

#### PowerShell Script

```powershell
# Only delete failed PSTs
.\clear-pst-files.ps1 -ProjectId "id" -IncludeStuck $false -IncludeDuplicates $false -Apply

# Change stuck threshold to 2 hours
.\clear-pst-files.ps1 -ProjectId "id" -StuckHours 2.0 -Apply

# Delete by filename pattern
# (Note: Use the API directly for this)
```

#### Python Script

```bash
# Only delete pending PSTs
python clear-pst-files.py --status pending --apply

# Only delete failed PSTs
python clear-pst-files.py --status failed --apply

# Change stuck threshold to 2 hours
python clear-pst-files.py --stuck-hours 2.0 --apply
```

## Manual API Call

You can also call the API directly:

```bash
curl -X POST http://localhost:8010/api/admin/cleanup-pst \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "your-project-id",
    "stuck_hours": 1.0,
    "include_failed": true,
    "include_stuck": true,
    "include_duplicates": true,
    "apply": false
  }'
```

Set `"apply": true` to actually delete (instead of dry-run).

## Manual Database Query

To see pending/failed PSTs directly:

```sql
-- List all pending and failed PST files
SELECT 
    id,
    filename,
    processing_status,
    uploaded_at,
    processing_started_at,
    total_emails,
    processed_emails,
    error_message
FROM pst_files
WHERE processing_status IN ('pending', 'failed')
   OR (processing_status IN ('processing', 'queued') 
       AND processing_started_at < NOW() - INTERVAL '1 hour')
ORDER BY uploaded_at DESC;

-- Count related records
SELECT 
    p.id,
    p.filename,
    p.processing_status,
    COUNT(DISTINCT e.id) as email_count,
    COUNT(DISTINCT a.id) as attachment_count
FROM pst_files p
LEFT JOIN email_messages e ON e.pst_file_id = p.id
LEFT JOIN email_attachments a ON a.email_message_id = e.id
WHERE p.processing_status IN ('pending', 'failed')
GROUP BY p.id, p.filename, p.processing_status;
```

## Troubleshooting

### "Authentication failed"
- Check your token is valid
- Make sure you're logged in as an admin (@vericase.com email)

### "Access denied"
- Admin access required
- Only @vericase.com emails can run cleanup

### "Connection refused"
- Check the API URL (default: http://localhost:8010)
- Make sure VeriCase services are running:
  ```bash
  cd vericase
  docker compose ps
  ```

### Database connection fails
- Check DATABASE_URL is correct
- Verify PostgreSQL is running:
  ```bash
  docker compose ps postgres
  ```

## Best Practices

1. **Always dry-run first** - Preview what will be deleted before applying
2. **Backup before cleanup** - Consider backing up the database first
3. **Check S3 separately** - Cleanup only removes DB records, not S3 files
4. **Monitor processing** - After cleanup, monitor if new uploads succeed

## S3 Cleanup

To clean up orphaned S3 objects after database cleanup, use AWS CLI:

```bash
# List PST files in S3
aws s3 ls s3://your-bucket/pst/ --recursive

# Delete specific PST file
aws s3 rm s3://your-bucket/pst/filename.pst

# Or use MinIO client for local dev
mc ls local/vericase/pst/
mc rm local/vericase/pst/filename.pst
```

## See Also

- Main deployment guide: `vericase/README.md`
- API documentation: `http://localhost:8010/docs`
- Database schema: `vericase/api/app/models.py`
