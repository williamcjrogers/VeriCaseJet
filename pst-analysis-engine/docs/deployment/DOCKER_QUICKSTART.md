# VeriCase Docker Quick Start

## ✅ Prerequisites

- **Docker Desktop** installed and running
- At least 8GB RAM allocated to Docker
- Ports available: 8010, 9002, 9003, 9200, 9998, 55432, 6379

## 🚀 Quick Start

### Windows:
```cmd
START_DOCKER.bat
```

### Linux/Mac:
```bash
chmod +x START_DOCKER.sh
./START_DOCKER.sh
```

## 📦 What Gets Started

The system starts 6 Docker containers:

1. **API** - FastAPI backend (port 8010)
2. **Worker** - Celery background processor
3. **PostgreSQL** - Database (port 55432)
4. **Redis** - Message queue (port 6379)
5. **OpenSearch** - Search engine (port 9200)
6. **MinIO** - S3-compatible storage (ports 9002, 9003)
7. **Apache Tika** - Document processor (port 9998)

## 🌐 Access Points

After starting (wait ~30 seconds for all services):

- **Main Application**: http://localhost:8010
- **Login Page**: http://localhost:8010/ui/login.html
- **Dashboard**: http://localhost:8010/ui/dashboard.html
- **MinIO Console**: http://localhost:9003

### Default Credentials

**Application:**
- Email: `admin@vericase.com`
- Password: `admin123`

**MinIO:**
- Username: `admin`
- Password: `changeme123`

## 📊 Useful Commands

### View logs (all services):
```bash
docker compose logs -f
```

### View logs (specific service):
```bash
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f postgres
```

### Restart a service:
```bash
docker compose restart api
docker compose restart worker
```

### Stop all services:
```bash
docker compose down
```

### Stop and remove all data:
```bash
docker compose down -v
```

### Check service status:
```bash
docker compose ps
```

## 🐛 Troubleshooting

### Services won't start:
```bash
# Check Docker is running
docker info

# Check for port conflicts
netstat -ano | findstr "8010"
netstat -ano | findstr "9200"

# View error logs
docker compose logs
```

### Reset everything:
```bash
# Stop and remove all containers and volumes
docker compose down -v

# Start fresh
docker compose up -d
```

### Database issues:
```bash
# Connect to database
docker exec -it pst-analysis-engine-postgres-1 psql -U vericase -d vericase

# Inside psql:
\dt          # List tables
\du          # List users
\q           # Quit
```

### Storage issues:
```bash
# Check MinIO
docker exec -it pst-analysis-engine-minio-1 mc alias set local http://localhost:9000 admin changeme123
docker exec -it pst-analysis-engine-minio-1 mc ls local
```

## 🔧 Configuration

Edit `.env` file to customize:
- Database credentials
- S3/MinIO settings
- API keys for AI features
- CORS origins
- JWT secrets

**Important:** Never commit real credentials to git!

## 📝 First Time Setup

1. Start services: `START_DOCKER.bat` or `./START_DOCKER.sh`
2. Wait 30 seconds for all services to initialize
3. Open http://localhost:8010/ui/login.html
4. Login with admin@vericase.com / admin123
5. Start using the application!

## 🎯 What's Next?

- Upload PST files for email extraction
- Create projects/cases
- Manage stakeholders
- Search correspondence
- Extract attachments

See `README.md` for full documentation.

