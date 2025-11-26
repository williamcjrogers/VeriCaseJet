# 🚀 VeriCase - Complete Setup & Run Guide

## ✅ What You Have

A fully-configured VeriCase PST Analysis system with:
- ✅ FastAPI backend
- ✅ Celery worker for PST processing
- ✅ PostgreSQL database
- ✅ Redis message queue
- ✅ OpenSearch for full-text search
- ✅ MinIO for S3-compatible storage
- ✅ Apache Tika for document processing

## 🎯 Two Ways to Run

### Option 1: Docker (Recommended - Easiest)

**Requirements:**
- Docker Desktop installed
- 8GB RAM for Docker
- Windows 10/11 or Linux/Mac

**Start with one command:**
```cmd
START_DOCKER.bat
```

**What it does:**
- Starts all 7 services in containers
- No Python installation needed
- No dependency management needed
- Everything just works!

**Access at:** http://localhost:8010

---

### Option 2: Local Python (For Development)

**Requirements:**
- Python 3.11+
- PostgreSQL 15
- Redis 7
- OpenSearch 2.10
- MinIO (or use Docker for these services)

**Setup:**
```cmd
# 1. Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 3. Start infrastructure services (Docker)
docker compose up -d postgres redis opensearch minio tika

# 4. Run database migrations
cd api
python apply_migrations.py

# 5. Start API server
cd ..
uvicorn api.app.main:app --host 0.0.0.0 --port 8000

# 6. Start worker (new terminal)
celery -A worker_app.worker worker --loglevel=info
```

---

## 🏃 Quick Start (Docker)

### Step 1: Install Docker Desktop

**Download:** https://www.docker.com/products/docker-desktop/

1. Install Docker Desktop
2. Start Docker Desktop
3. Wait for "Docker Desktop is running" status

### Step 2: Start VeriCase

**Windows:**
```cmd
START_DOCKER.bat
```

**Linux/Mac:**
```bash
chmod +x START_DOCKER.sh
./START_DOCKER.sh
```

### Step 3: Wait for Services

Services take ~30 seconds to start. You'll see:
```
✓ postgres
✓ redis
✓ opensearch
✓ minio
✓ tika
✓ api
✓ worker
```

### Step 4: Access Application

Open browser to: **http://localhost:8010**

**Login:**
- Email: `admin@vericase.com`
- Password: `admin123`

---

## 📦 What's Running

| Service | Port | Purpose |
|---------|------|---------|
| API | 8010 | Main application |
| PostgreSQL | 55432 | Database |
| Redis | 6379 | Message queue |
| OpenSearch | 9200 | Search engine |
| MinIO | 9002 | S3 storage |
| MinIO Console | 9003 | Storage UI |
| Tika | 9998 | Document processor |

---

## 🔧 Common Commands

### View all logs:
```bash
docker compose logs -f
```

### View specific service:
```bash
docker compose logs -f api
docker compose logs -f worker
```

### Restart a service:
```bash
docker compose restart api
```

### Stop everything:
```bash
docker compose down
```

### Check status:
```bash
docker compose ps
```

### Start fresh (removes all data):
```bash
docker compose down -v
docker compose up -d
```

---

## 🐛 Troubleshooting

### "Docker is not running"
1. Open Docker Desktop
2. Wait for green status
3. Try again

### "Port already in use"
```bash
# Find what's using port 8010
netstat -ano | findstr "8010"

# Kill the process (replace PID)
taskkill /PID <pid> /F

# Or change port in docker-compose.yml
ports: ["8011:8000"]  # Use 8011 instead
```

### "Services won't start"
```bash
# Check Docker resources
# Docker Desktop → Settings → Resources
# Ensure: 4 CPUs, 8GB RAM

# View error logs
docker compose logs
```

### Database connection errors
```bash
# Verify PostgreSQL is running
docker compose ps postgres

# Connect to database
docker exec -it pst-analysis-engine-postgres-1 psql -U vericase -d vericase

# Check tables
\dt
```

### Worker not processing
```bash
# Check worker logs
docker compose logs -f worker

# Restart worker
docker compose restart worker
```

---

## 🎨 Development Workflow

### Edit Code
Files are mounted as volumes - changes reflect immediately:
- `api/app/*` - API code (auto-reload enabled)
- `worker_app/*` - Worker code
- `ui/*` - Frontend files

### Run Tests
```bash
docker compose exec api pytest
```

### Format Code
```bash
# Windows
.\format.ps1

# Fix issues automatically
.\format.ps1 -Fix
```

### Database Migrations
```bash
# Create migration
docker compose exec api alembic revision --autogenerate -m "description"

# Apply migrations
docker compose exec api alembic upgrade head
```

---

## 📝 Configuration

Edit `.env` file to customize:

```env
# Database
DATABASE_URL=postgresql+psycopg2://vericase:vericase@postgres:5432/vericase

# Storage
MINIO_ACCESS_KEY=admin
MINIO_SECRET_KEY=changeme123
MINIO_BUCKET=vericase-docs

# API
JWT_SECRET=your-secret-key-here
CORS_ORIGINS=http://localhost:8010

# AI (optional)
GEMINI_API_KEY=your-key
CLAUDE_API_KEY=your-key
OPENAI_API_KEY=your-key
```

**⚠️ Never commit real credentials to git!**

---

## 🎯 Usage Flow

1. **Login** → http://localhost:8010/ui/login.html
2. **Dashboard** → View projects/cases
3. **Upload PST** → Background worker processes
4. **View Emails** → Search and filter correspondence
5. **Extract Attachments** → Download evidence documents

---

## 📚 Additional Resources

- **Docker Guide**: `DOCKER_QUICKSTART.md`
- **Full Docs**: `README.md`
- **PyCharm Setup**: `README_PYCHARM.md`
- **Database**: `DATAGRIP_SETUP.md`
- **Frontend**: `WEBSTORM_SETUP.md`

---

## ✅ Quick Health Check

After starting, verify everything works:

```bash
# 1. Check all services running
docker compose ps

# 2. Test API
curl http://localhost:8010/health

# 3. Test MinIO
curl http://localhost:9002/minio/health/live

# 4. Test OpenSearch
curl http://localhost:9200

# 5. Test database
docker exec pst-analysis-engine-postgres-1 pg_isready -U vericase
```

---

## 🎉 You're Ready!

VeriCase is configured and ready to run. Just execute:

```cmd
START_DOCKER.bat
```

Then open: **http://localhost:8010**

Questions? Check the documentation files or error logs.

**Happy analyzing! 🚀**

