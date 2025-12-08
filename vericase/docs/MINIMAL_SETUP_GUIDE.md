# VeriCase Analysis - Minimal Setup Guide

## 🚀 Quick Start (Local Development)

This guide will help you run VeriCase Analysis locally with the absolute minimum requirements.

### Prerequisites

1. **Docker Desktop** (required)
   - Download: https://www.docker.com/products/docker-desktop/
   - Ensure Docker is running

2. **Git** (you already have this ✓)

### Step 1: Navigate to Project Directory

```bash
cd "c:\Users\William\Documents\Projects\VeriCase Analysis\pst-analysis-engine"
```

### Step 2: Start All Services with Docker Compose

```bash
docker-compose up -d
```

This single command will start:
- ✅ PostgreSQL database (port 55432)
- ✅ MinIO (S3-compatible storage, ports 9002-9003)
- ✅ Redis (caching, port 6379)
- ✅ OpenSearch (search engine, port 9200)
- ✅ Apache Tika (document processing, port 9998)
- ✅ API Server (port 8010)
- ✅ Worker (background processing)

### Step 3: Initialize the Database

Wait about 30 seconds for services to start, then run:

```bash
docker-compose exec api python /code/api/apply_migrations.py
```

### Step 4: Create Admin User

```bash
docker-compose exec api python /code/api/init_admin.py
```

This creates an admin user:
- **Email**: admin@vericase.com
- **Password**: admin123 (change this after first login!)

### Step 5: Access the Application

Open your browser to:
- **Main Application**: http://localhost:8010/ui/dashboard.html
- **MinIO Console**: http://localhost:9003 (login: admin/changeme123)

---

## 🎯 Minimal AWS Setup (If You Want Cloud Deployment)

Based on your current AWS setup, you only have S3. Here's the absolute minimum:

### Current AWS Resources (Cost: ~$5-10/month)
✅ S3 Bucket: `vericase-docs-prod-526015377510`
❌ No RDS (using local PostgreSQL instead)
❌ No ElastiCache (using local Redis instead)
❌ No App Runner (deploy locally or fix the failed service)

### To Deploy to AWS (Optional):

1. **Fix App Runner Service** (if needed):
```bash
aws apprunner delete-service --service-arn arn:aws:apprunner:us-east-1:526015377510:service/VeriCase-analysis/48424463c4ca476b825692ca41a05c5e
```

2. **Deploy Fresh App Runner**:
```bash
cd "c:\Users\William\Documents\Projects\VeriCase Analysis"
.\deploy-apprunner.sh
```

---

## 📦 What's Running?

After `docker-compose up -d`, check status:

```bash
docker-compose ps
```

You should see 7 services running:
- minio (object storage)
- postgres (database)
- redis (cache)
- opensearch (search)
- tika (document processing)
- api (web server)
- worker (background jobs)

---

## 🛠️ Useful Commands

### View Logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f api
docker-compose logs -f worker
```

### Restart Services
```bash
docker-compose restart api
docker-compose restart worker
```

### Stop All Services
```bash
docker-compose down
```

### Stop and Remove All Data
```bash
docker-compose down -v
```

---

## 🔍 Troubleshooting

### Services Won't Start?
```bash
# Check Docker is running
docker ps

# Rebuild and restart
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Can't Access http://localhost:8010?
```bash
# Check API logs
docker-compose logs api

# Check if port is in use
netstat -ano | findstr :8010
```

### Database Connection Errors?
```bash
# Restart database
docker-compose restart postgres

# Check database logs
docker-compose logs postgres
```

---

## 💰 Cost Comparison

### Local Development (Docker)
- **Cost**: $0/month
- **Resources**: Uses your local machine
- **Best for**: Development, testing, demos

### Minimal AWS (Current Setup)
- **Cost**: ~$5-10/month
- **Resources**: S3 only
- **Best for**: File storage backup

### Full AWS Production
- **Cost**: $50-200+/month
- **Resources**: RDS, ElastiCache, App Runner, S3
- **Best for**: Production with high availability

---

## ✅ You're Ready!

Your minimal setup is now running. Open http://localhost:8010/ui/dashboard.html and log in with:
- Email: admin@vericase.com
- Password: admin123

**Next Steps:**
1. Change the admin password
2. Upload some PST files or documents
3. Explore the correspondence analysis features

**Need Help?**
- Check logs: `docker-compose logs -f`
- Stop everything: `docker-compose down`
- Start fresh: `docker-compose down -v && docker-compose up -d`
