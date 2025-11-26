# VeriCase PST Analysis - Quick Start Guide

## Setup (First Time Only)

1. **Run the startup script:**
   ```bash
   STARTUP.bat
   ```

   This will:
   - Stop any existing containers
   - Start all services (API, Worker, Database, etc.)
   - Install required dependencies
   - Show you the login credentials

2. **Wait 15 seconds** for services to initialize

## Login

**URL:** http://localhost:8010/ui/login.html

**Credentials:**
- Email: `admin@veri-case.com`
- Password: `admin123`

## Upload PST Files

1. After login, go to: http://localhost:8010/ui/correspondence-enterprise.html?projectId=46ef3de3-f296-48a9-b6cc-c3bd80484c51

2. Click "Upload PST" button

3. Select your PST file

4. Wait for processing (watch the worker logs)

5. Refresh the page to see emails appear

## Features

✅ **SigParser Email Threading** - AI-powered email conversation detection
✅ **Full Email Bodies** - Complete HTML and plain text
✅ **Attachment Extraction** - All attachments with preview URLs
✅ **Thread Grouping** - Smart conversation threading
✅ **AG Grid** - Professional email list view

## Architecture

- **API** (port 8010): FastAPI backend
- **Worker** (Celery): PST processing with SigParser
- **PostgreSQL** (port 55432): Email storage
- **MinIO** (port 9002/9003): S3-compatible file storage
- **OpenSearch** (port 9200): Full-text search
- **Redis** (port 6379): Task queue

## Current Status

- ✅ 284 emails extracted from your PST
- ✅ 261 attachments
- ✅ 65 conversation threads identified
- ✅ SigParser integration active
- ✅ Project created: `46ef3de3-f296-48a9-b6cc-c3bd80484c51`

## Troubleshooting

### No emails showing?
1. Hard refresh browser: `Ctrl + Shift + R`
2. Check browser console for errors (F12)
3. Verify emails in database:
   ```bash
   docker-compose exec -T postgres psql -U vericase -d vericase -c "SELECT COUNT(*) FROM email_messages WHERE project_id = '46ef3de3-f296-48a9-b6cc-c3bd80484c51';"
   ```

### Worker not processing?
```bash
docker-compose logs -f worker
```

### Restart everything:
```bash
docker-compose down
docker-compose up -d
```

## Stop Services

```bash
docker-compose down
```
