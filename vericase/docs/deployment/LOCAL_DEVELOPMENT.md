# VeriCase Local Development - Quick Start

## 🚀 5-Minute Setup

### Prerequisites

- Docker Desktop (Windows 11) with 8GB+ RAM
- Git
- PowerShell

### Start Everything

```powershell
# Navigate to project
cd "c:\Users\William\Documents\Projects\main\vericase"

# Start all services
docker-compose up -d

# Wait ~30 seconds, then check health
.\scripts\dev.ps1 health
```

### Access Your App

- **Dashboard**: http://localhost:8010/ui/dashboard.html
- **Workspace Hub**: http://localhost:8010/ui/workspace-hub.html
- **API Docs**: http://localhost:8010/docs
- **MinIO Console**: http://localhost:9003 (admin/changeme123)

### Workspace “Start / Continue analysis” (new)

In the **Workspace Hub → open a workspace → Purpose tab**, you’ll see a **Start / Continue analysis** card.

- It runs **Purpose refresh + keyword rescan** as a single background job (with a progress bar).
- Make sure **worker + redis** are running (`docker-compose ps`), otherwise jobs will stay queued.

---

## ⚡ Hot Reload - Edit & See Changes Instantly

### Backend (FastAPI) - AUTO RELOAD ✅

**Changes automatically reload - no rebuild needed!**

1. Edit any file in `api/app/` (e.g., `correspondence.py`)
2. Save the file
3. Refresh your browser
4. **Changes are live!** (takes ~1 second)

**Watch logs to see reload:**

```powershell
docker-compose logs -f api
# You'll see: "Reloading..." when you save a file
```

### UI (Static HTML) - FAST ITERATION ✅

- Edit files in `ui/*.html`
- Served at http://localhost:8010/ui/
- Refresh browser to see changes

### Worker (Celery) - Manual Restart

Changes to `worker_app/*.py` need a restart:

```powershell
docker-compose restart worker
```

---

## 📝 Common Commands

Use the helper script for easy management:

```powershell
# Start everything
.\scripts\dev.ps1 start

# Stop everything
.\scripts\dev.ps1 stop

# Restart a service
.\scripts\dev.ps1 restart api

# View logs
.\scripts\dev.ps1 logs api

# Check status
.\scripts\dev.ps1 status

# Health check
.\scripts\dev.ps1 health

# Reset database (deletes all data!)
.\scripts\dev.ps1 reset-db
```

Or use docker-compose directly:

```powershell
# Start
docker-compose up -d

# Stop
docker-compose down

# View all logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f api
docker-compose logs -f worker

# Restart specific service
docker-compose restart api

# See running services
docker-compose ps

# Reset everything (deletes volumes!)
docker-compose down -v
docker-compose up -d
```

---

## 🔧 Your Development Workflow

### The Fast Way (Now)

1. **Edit code** in VS Code
2. **Save file** (Ctrl+S)
3. **Refresh browser** (F5)
4. **See changes** (1 second!)
5. Test locally until it works
6. **Commit & push** when ready
7. GitHub Actions deploys to EKS

### The Old Way (Slow)

~~1. Edit code~~
~~2. Commit & push to GitHub~~
~~3. Wait 10+ minutes for CI/CD~~
~~4. Deploy to EKS~~
~~5. Test and find bugs~~
~~6. Repeat...~~

**You just saved 10+ minutes per iteration!** 🎉

---

## 🐛 Troubleshooting

### Port Already in Use

```powershell
# Find what's using port 8010
netstat -ano | findstr :8010

# Kill the process
taskkill /PID <PID> /F

# Or stop docker-compose
docker-compose down
```

### Database Connection Errors

```powershell
# Check if PostgreSQL is running
docker-compose ps postgres

# Restart database
docker-compose restart postgres

# Reset database completely
docker-compose down -v
docker-compose up -d
```

### Services Won't Start

```powershell
# Check Docker Desktop is running
# Check you have enough RAM (8GB+)

# See what failed
docker-compose ps

# Check logs for errors
docker-compose logs postgres
docker-compose logs api
docker-compose logs worker
```

### Hot Reload Not Working

```powershell
# Verify volume mounts
docker-compose config

# Restart the API
docker-compose restart api

# Check if file is actually mounted
docker-compose exec api ls -la /code/app/
```

### MinIO Access Denied

```powershell
# Login to MinIO console: http://localhost:9003
# Username: admin (or minioadmin)
# Password: changeme123 (or minioadmin)

# Check bucket exists
# Should see "vericase-docs" bucket
```

---

## 📂 What's Running?

When you run `docker-compose up -d`, you start:

| Service        | Purpose                 | Port       | Status Check               |
| -------------- | ----------------------- | ---------- | -------------------------- |
| **api**        | FastAPI backend         | 8010       | http://localhost:8010/docs |
| **worker**     | Celery background tasks | -          | docker-compose logs worker |
| **postgres**   | PostgreSQL database     | 54321      | docker-compose ps postgres |
| **redis**      | Cache & message queue   | 6379       | docker-compose ps redis    |
| **opensearch** | Search engine           | 9200       | http://localhost:9200      |
| **minio**      | S3-compatible storage   | 9002, 9003 | http://localhost:9003      |
| **tika**       | Document extraction     | 9998       | docker-compose ps tika     |

---

## 🧪 Testing Before Deploy

1. Make changes locally
2. Test at http://localhost:8010
3. Check logs: `docker-compose logs -f api`
4. Verify everything works
5. **Only commit when it works**
6. GitHub Actions handles the rest

---

## 🎯 Quick Tips

- **Save time**: Test locally before pushing
- **Watch logs**: `docker-compose logs -f api` shows reload messages
- **Fast restart**: `docker-compose restart api` (5 seconds)
- **Fresh start**: `docker-compose down -v && docker-compose up -d` (30 seconds)
- **Shell access**: `docker-compose exec api bash`
- **Database access**: `docker-compose exec postgres psql -U vericase -d vericase`

---

## 📊 Services Overview

```
                    ┌─────────────────┐
                    │   Your Browser  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  API (FastAPI)  │ :8010
                    │  Hot Reload ✅  │
                    └────┬──┬──┬──┬───┘
                         │  │  │  │
         ┌───────────────┘  │  │  └──────────────┐
         │                  │  │                 │
    ┌────▼─────┐   ┌───────▼──▼───────┐   ┌────▼──────┐
    │PostgreSQL│   │  Redis + Celery  │   │  MinIO    │
    │  :54321  │   │     :6379        │   │ :9002/03  │
    └──────────┘   └─────────┬────────┘   └───────────┘
                             │
                       ┌─────▼─────┐
                       │  Worker   │
                       │ (Celery)  │
                       └───────────┘
```

---

## 🆘 Need Help?

1. Check logs: `docker-compose logs -f api`
2. Check status: `docker-compose ps`
3. Check health: `.\scripts\dev.ps1 health`
4. Reset everything: `docker-compose down -v && docker-compose up -d`
5. Check Docker Desktop has enough resources (8GB+ RAM)

---

## 🎉 You're All Set!

You now have a **lightning-fast local development environment**:

- ✅ Edit code → See changes in 1 second
- ✅ No more waiting for CI/CD
- ✅ Test everything locally first
- ✅ Commit only when it works
- ✅ Save 10+ minutes per iteration

**Happy coding!** 🚀
