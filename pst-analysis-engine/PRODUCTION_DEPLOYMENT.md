# VeriCase Production Deployment Guide

## Overview

This guide covers deploying VeriCase Analysis as a production-ready system using Docker containers and orchestration.

## Architecture

The production system consists of:

- **API Service**: FastAPI application serving REST endpoints
- **Worker Service**: Celery workers for PST processing and background tasks
- **PostgreSQL**: Primary database for case data
- **MinIO/S3**: Object storage for PST files and attachments
- **Redis**: Task queue and caching layer
- **OpenSearch**: Full-text search for emails and documents
- **Apache Tika**: Document parsing and OCR
- **Flower**: Celery task monitoring (optional)

## Prerequisites

- Docker 20.10+ and Docker Compose 2.0+
- 16GB+ RAM (32GB recommended for large PST processing)
- 100GB+ available disk space
- Ports available: 8010, 9000, 9001, 5432, 6379, 9200, 9998, 5555

## Quick Start

### 1. Clone and Configure

```bash
git clone https://github.com/your-org/vericase-analysis.git
cd vericase-analysis/pst-analysis-engine

# Copy environment template
cp .env.example .env

# Edit .env with your settings
nano .env
```

### 2. Deploy with Docker Compose

**Linux/macOS:**
```bash
chmod +x deploy.sh
./deploy.sh
```

**Windows:**
```powershell
.\deploy.ps1
```

**Manual deployment:**
```bash
# Build images
docker-compose -f docker-compose.prod.yml build

# Start services
docker-compose -f docker-compose.prod.yml up -d

# Check status
docker-compose -f docker-compose.prod.yml ps
```

### 3. Verify Deployment

- API Health: http://localhost:8010/health
- UI: http://localhost:8010/ui/
- MinIO Console: http://localhost:9001
- Flower (Celery monitoring): http://localhost:5555

## Configuration

### Environment Variables

Key variables in `.env`:

```bash
# Database
DB_USER=vericase
DB_PASSWORD=secure_password_here
DB_NAME=vericase

# Object Storage
MINIO_ACCESS_KEY=vericase_access
MINIO_SECRET_KEY=secure_secret_here
MINIO_BUCKET=vericase-files

# Security
JWT_SECRET_KEY=your_jwt_secret_here
JWT_ALGORITHM=HS256

# Celery
CELERY_QUEUE=vericase
CELERY_PST_QUEUE=pst_processing

# Optional: AI Services
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-...
```

### Resource Limits

Edit `docker-compose.prod.yml` to adjust resource limits:

```yaml
services:
  worker:
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 8G
        reservations:
          cpus: '2'
          memory: 4G
```

## Scaling

### Horizontal Scaling

Scale workers for large PST processing loads:

```bash
# Scale to 5 workers
docker-compose -f docker-compose.prod.yml up -d --scale worker=5

# Check worker status
docker-compose -f docker-compose.prod.yml exec flower curl http://localhost:5555/api/workers
```

### Dedicated PST Processing Workers

For heavy PST processing, run dedicated workers:

```bash
# Start PST-specific workers
docker-compose -f docker-compose.prod.yml run -d \
  --name pst-worker-1 \
  worker celery -A worker_app.worker worker \
  --loglevel=INFO --concurrency=2 -Q pst_processing
```

## Monitoring

### Health Checks

Monitor service health:

```bash
# API health
curl http://localhost:8010/health

# Database connections
docker-compose -f docker-compose.prod.yml exec postgres \
  psql -U vericase -c "SELECT count(*) FROM pg_stat_activity;"

# Redis info
docker-compose -f docker-compose.prod.yml exec redis redis-cli INFO
```

### Logs

View logs for troubleshooting:

```bash
# All services
docker-compose -f docker-compose.prod.yml logs -f

# Specific service
docker-compose -f docker-compose.prod.yml logs -f api

# Worker errors
docker-compose -f docker-compose.prod.yml logs -f worker | grep ERROR
```

### Metrics

Access Flower for Celery metrics:
- URL: http://localhost:5555
- Monitor task queues, success/failure rates, worker utilization

## Backup and Recovery

### Database Backup

```bash
# Backup
docker-compose -f docker-compose.prod.yml exec postgres \
  pg_dump -U vericase vericase > backup_$(date +%Y%m%d).sql

# Restore
docker-compose -f docker-compose.prod.yml exec -T postgres \
  psql -U vericase vericase < backup_20240109.sql
```

### S3/MinIO Backup

```bash
# Sync to external S3
docker-compose -f docker-compose.prod.yml exec minio \
  mc mirror local/vericase-files s3/backup-bucket
```

## Security Hardening

### 1. Use Strong Passwords

Generate secure passwords:
```bash
openssl rand -base64 32  # For DB_PASSWORD
openssl rand -base64 64  # For JWT_SECRET_KEY
```

### 2. Enable HTTPS

Use a reverse proxy (nginx/traefik) with SSL:

```nginx
server {
    listen 443 ssl;
    server_name vericase.yourdomain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8010;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 3. Firewall Rules

Restrict access to internal services:

```bash
# Only allow API port externally
sudo ufw allow 8010/tcp
sudo ufw deny 5432/tcp  # Block direct PostgreSQL access
sudo ufw deny 6379/tcp  # Block direct Redis access
```

### 4. Regular Updates

```bash
# Update base images
docker-compose -f docker-compose.prod.yml pull
docker-compose -f docker-compose.prod.yml up -d
```

## Troubleshooting

### Common Issues

1. **PST Processing Fails**
   - Check worker logs: `docker-compose logs -f worker`
   - Verify libpff installation in worker container
   - Ensure sufficient memory for large PST files

2. **Database Connection Errors**
   - Verify PostgreSQL is running: `docker-compose ps postgres`
   - Check credentials in .env match docker-compose.yml
   - Review connection string in logs

3. **S3/MinIO Upload Failures**
   - Check MinIO is accessible: `curl http://localhost:9000`
   - Verify bucket exists and credentials are correct
   - Check disk space for MinIO volume

### Debug Mode

Enable debug logging:

```bash
# In .env
LOG_LEVEL=DEBUG

# Restart services
docker-compose -f docker-compose.prod.yml restart api worker
```

## Performance Tuning

### PostgreSQL Optimization

Add to `docker-compose.prod.yml`:

```yaml
postgres:
  command: >
    -c shared_buffers=2GB
    -c effective_cache_size=6GB
    -c maintenance_work_mem=512MB
    -c work_mem=32MB
    -c max_connections=200
```

### Redis Optimization

```yaml
redis:
  command: >
    redis-server
    --maxmemory 4gb
    --maxmemory-policy allkeys-lru
    --appendonly yes
```

### Worker Concurrency

Adjust based on CPU cores:

```yaml
worker:
  command: ["celery", "-A", "worker_app.worker", "worker", 
            "--loglevel=INFO", "--concurrency=8"]  # 2x CPU cores
```

## Maintenance

### Regular Tasks

1. **Clean up old processing jobs** (weekly):
   ```sql
   DELETE FROM processing_jobs 
   WHERE status = 'completed' 
   AND created_at < NOW() - INTERVAL '30 days';
   ```

2. **Vacuum database** (monthly):
   ```bash
   docker-compose exec postgres vacuumdb -U vericase -z vericase
   ```

3. **Clear Redis cache** (as needed):
   ```bash
   docker-compose exec redis redis-cli FLUSHDB
   ```

## Support

For issues or questions:
- Documentation: [Link to docs]
- Issue Tracker: [GitHub Issues]
- Email: support@vericase.com
