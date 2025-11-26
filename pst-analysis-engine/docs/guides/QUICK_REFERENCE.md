# VeriCase Quick Reference Guide

## 🚀 Quick Start

### Start the System
```bash
docker-compose up -d
```

### Access Points
- **Web UI**: http://localhost:8010/ui
- **API Docs**: http://localhost:8010/docs
- **MinIO Console**: http://localhost:9003 (admin/changeme123)
- **OpenSearch**: http://localhost:9200
- **PostgreSQL**: localhost:55432 (vericase/vericase)

### Default Admin Account
```
Email: admin@vericase.com
Password: admin123
```

---

## 📁 PST File Support - TL;DR

### Current Status:
- ✅ **Upload**: PST files can be uploaded
- ✅ **Storage**: Files are stored securely
- ✅ **Processing**: Emails extracted and indexed
- ✅ **Search**: Full-text search of email content
- ✅ **Preview**: Email content viewable in UI

### What This Means:
PST files are fully supported - you can:
1. Upload PST files to the system
2. Automatically extract all emails
3. Search email content and metadata
4. View individual emails
5. Organize by cases
6. Track correspondence patterns

---

## 🔍 Testing PST Upload

### Via UI:
1. Go to http://localhost:8010/ui
2. Login with your account
3. Click "Upload"
4. Select a PST file from your computer
5. Click "Start upload"
6. ✅ File will upload and process automatically
7. 📧 Emails will be extracted and searchable

### Via API:
```bash
# Get auth token
TOKEN=$(curl -s -X POST "http://localhost:8010/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@vericase.com","password":"admin123"}' \
  | jq -r '.token')

# 1. Get presigned URL
PRESIGN=$(curl -s -X POST "http://localhost:8010/uploads/presign" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"filename":"test.pst","content_type":"application/vnd.ms-outlook"}')

UPLOAD_URL=$(echo $PRESIGN | jq -r '.url')
UPLOAD_KEY=$(echo $PRESIGN | jq -r '.key')

# 2. Upload to storage
curl -X PUT "$UPLOAD_URL" \
  -H "Content-Type: application/vnd.ms-outlook" \
  --data-binary "@/path/to/your/file.pst"

# 3. Complete upload
curl -X POST "http://localhost:8010/uploads/complete" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"key\":\"$UPLOAD_KEY\",
    \"filename\":\"test.pst\",
    \"content_type\":\"application/vnd.ms-outlook\",
    \"size\":$(stat -f%z /path/to/your/file.pst)
  }"

echo "✅ PST uploaded and processing started!"
```

---

## 📊 File Type Support Reference

### Text Extraction Works:
```
✅ PST, OST (Outlook data files) - FULL SUPPORT
✅ MSG, EML (Email messages)
✅ PDF (with OCR for scanned docs)
✅ DOCX, DOC, RTF
✅ XLSX, XLS
✅ PPTX, PPT
✅ TXT, HTML, XML
✅ JPG, PNG, TIFF (via OCR)
```

### Upload & Storage Only:
```
⚠️ ZIP, RAR, 7Z (Archives)
⚠️ Executables and binary files
```

All files can be uploaded and stored - most have text extraction.

---

## 🛠️ Common Tasks

### Check Document Status:
```bash
# View logs
docker-compose logs -f worker

# Check processing queue
docker-compose exec redis redis-cli LLEN pst-processing

# View recent documents
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8010/documents/recent
```

### Verify PST Upload Worked:
```bash
# Check database
docker-compose exec postgres psql -U vericase -d vericase \
  -c "SELECT id, filename, status, size FROM documents WHERE filename LIKE '%.pst';"

# Check MinIO storage
docker-compose exec minio mc ls local/vericase-docs/

# Check OpenSearch index
curl "http://localhost:9200/emails/_search?q=*&size=5" | jq
```

### Search for PST Files:
```bash
# Search by filename
curl -G "http://localhost:8010/search" \
  --data-urlencode "q=.pst" \
  -H "Authorization: Bearer $TOKEN"

# Search email content
curl -G "http://localhost:8010/search" \
  --data-urlencode "q=contract" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 🔧 Case Management

### Create a Case:
```bash
curl -X POST "http://localhost:8010/cases" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Case #2024-001",
    "description": "Email investigation for client matter"
  }'
```

### Assign Document to Case:
```bash
curl -X POST "http://localhost:8010/cases/{case_id}/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"document_id": 123}'
```

### View Case Documents:
```bash
curl "http://localhost:8010/cases/{case_id}/documents" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 🔍 Advanced Search

### Search with Filters:
```bash
# Date range
curl -G "http://localhost:8010/search" \
  --data-urlencode "q=contract" \
  --data-urlencode "from_date=2024-01-01" \
  --data-urlencode "to_date=2024-12-31" \
  -H "Authorization: Bearer $TOKEN"

# By sender
curl -G "http://localhost:8010/search" \
  --data-urlencode "q=from:john@example.com" \
  -H "Authorization: Bearer $TOKEN"

# By subject
curl -G "http://localhost:8010/search" \
  --data-urlencode "q=subject:settlement" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 👥 User Management

### Create New User:
```bash
curl -X POST "http://localhost:8010/auth/signup" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "SecurePassword123!"
  }'
```

### Login:
```bash
curl -X POST "http://localhost:8010/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "SecurePassword123!"
  }'
```

---

## 🚨 Troubleshooting

### System Not Starting:
```bash
# Check Docker daemon
docker ps

# View all service logs
docker-compose logs

# Restart services
docker-compose down
docker-compose up -d
```

### PST Processing Stuck:
```bash
# Check worker status
docker-compose logs worker

# Check Celery queue
docker-compose exec redis redis-cli LLEN pst-processing

# Restart worker
docker-compose restart worker
```

### Database Connection Issues:
```bash
# Test connection
docker-compose exec postgres psql -U vericase -d vericase -c "SELECT 1;"

# Check environment variables
docker-compose exec api env | grep DATABASE

# Restart database
docker-compose restart postgres
```

### Storage Issues:
```bash
# Check MinIO health
curl http://localhost:9002/minio/health/live

# View MinIO logs
docker-compose logs minio

# Access MinIO console
# Open http://localhost:9003 in browser
```

### Search Not Working:
```bash
# Check OpenSearch health
curl http://localhost:9200/_cluster/health

# View indices
curl http://localhost:9200/_cat/indices

# Check index mapping
curl http://localhost:9200/emails/_mapping
```

---

## 📈 Performance Tips

### Docker Resources:
Ensure Docker has adequate resources:
- **RAM**: 8GB minimum, 16GB recommended
- **CPU**: 4+ cores recommended
- **Disk**: SSD strongly recommended

### Large PST Files:
For PST files > 2GB:
1. Increase worker timeout in docker-compose.yml
2. Monitor memory usage: `docker stats`
3. Process one large file at a time

### Optimize Search:
```bash
# Refresh index
curl -X POST "http://localhost:9200/emails/_refresh"

# Check index size
curl "http://localhost:9200/_cat/indices/emails?v"
```

---

## 🔐 Security Checklist

### Production Deployment:
- [ ] Change `JWT_SECRET` to a secure random string
- [ ] Update MinIO credentials
- [ ] Change PostgreSQL password
- [ ] Enable HTTPS/TLS
- [ ] Configure firewall rules
- [ ] Set up backup strategy
- [ ] Enable audit logging
- [ ] Review CORS settings

---

## 📞 Quick Commands Reference

```bash
# Start system
docker-compose up -d

# Stop system
docker-compose down

# View logs
docker-compose logs -f [service_name]

# Restart service
docker-compose restart [service_name]

# Shell access
docker-compose exec [service_name] bash

# Database shell
docker-compose exec postgres psql -U vericase -d vericase

# Redis CLI
docker-compose exec redis redis-cli

# View running containers
docker-compose ps

# Remove all data (CAUTION!)
docker-compose down -v
```

---

## 📚 Additional Resources

- **API Documentation**: http://localhost:8010/docs
- **Full README**: See README.md in project root
- **Configuration**: See .env.example for all options

---

**Current System Status**: Check with `docker-compose ps`
**PST Upload Status**: ✅ Fully supported with email extraction
**Next Steps**: Upload your first PST file and start searching! 🚀
