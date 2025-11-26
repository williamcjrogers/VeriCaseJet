# VeriCase Production Deployment Checklist

## Pre-Deployment

### 1. Environment Configuration
- [ ] Copy `env.production.example` to `.env`
- [ ] Generate secure JWT secret: `openssl rand -hex 64`
- [ ] Generate secure passwords for all services: `openssl rand -base64 32`
- [ ] Configure production database URL (PostgreSQL)
- [ ] Configure object storage (MinIO or AWS S3)
- [ ] Set appropriate CORS origins for your domain
- [ ] Configure AI API keys (if using AI features)

### 2. Database
- [ ] Run all migrations: `python api/apply_migrations.py`
- [ ] Create database backup before deployment
- [ ] Verify all tables are created correctly
- [ ] Set up regular backup schedule

### 3. Infrastructure Requirements
- [ ] PostgreSQL 13+ (minimum 4GB RAM, 100GB storage)
- [ ] Redis 6+ (minimum 2GB RAM)
- [ ] OpenSearch 2+ (minimum 8GB RAM)
- [ ] Apache Tika server
- [ ] MinIO or AWS S3 bucket
- [ ] Docker & Docker Compose installed
- [ ] Minimum 16GB RAM for host server
- [ ] SSL certificates for HTTPS

### 4. Security
- [ ] Change all default passwords
- [ ] Enable HTTPS/SSL for all services
- [ ] Configure firewall rules:
  - Port 8010 (API)
  - Port 443 (HTTPS)
  - Block all other external ports
- [ ] Set up VPN for admin access
- [ ] Enable authentication for OpenSearch
- [ ] Configure secure headers in nginx/proxy

## Deployment Steps

### 1. Initial Deployment (Windows)
```powershell
# Clone repository
git clone https://github.com/your-repo/vericase.git
cd vericase

# Create .env file
copy env.production.example .env
# Edit .env with your values

# Run deployment
.\deploy.ps1
```

### 2. Initial Deployment (Linux)
```bash
# Clone repository
git clone https://github.com/your-repo/vericase.git
cd vericase

# Create .env file
cp env.production.example .env
# Edit .env with your values

# Run deployment
chmod +x deploy.sh
./deploy.sh
```

### 3. Verify Deployment
- [ ] Check all containers are running: `docker ps`
- [ ] Verify API health: `curl http://localhost:8010/health`
- [ ] Test UI access: `http://localhost:8010/ui/wizard.html`
- [ ] Check logs: `docker-compose logs -f api`
- [ ] Run diagnostics: `.\diagnose.ps1` (Windows)

### 4. Post-Deployment Configuration
- [ ] Create admin user account
- [ ] Configure email settings
- [ ] Set up monitoring (Grafana/Prometheus)
- [ ] Configure log aggregation
- [ ] Set up alerts for errors

## Production Configuration

### 1. Performance Tuning
```yaml
# docker-compose.prod.yml adjustments
services:
  postgres:
    environment:
      POSTGRES_MAX_CONNECTIONS: 200
      POSTGRES_SHARED_BUFFERS: 2GB
      POSTGRES_EFFECTIVE_CACHE_SIZE: 6GB
      POSTGRES_WORK_MEM: 16MB

  redis:
    command: redis-server --maxmemory 4gb --maxmemory-policy allkeys-lru

  api:
    environment:
      GUNICORN_WORKERS: 4
      GUNICORN_THREADS: 2
    deploy:
      replicas: 2

  worker:
    environment:
      CELERY_CONCURRENCY: 8
    deploy:
      replicas: 3
```

### 2. Storage Configuration
- [ ] Configure S3 lifecycle policies for old PST files
- [ ] Set up storage quotas per user/company
- [ ] Configure backup retention (30 days recommended)
- [ ] Enable S3 versioning for PST files

### 3. Monitoring Setup
- [ ] Install monitoring stack:
  ```bash
  docker-compose -f docker-compose.monitoring.yml up -d
  ```
- [ ] Configure alerts for:
  - High CPU/memory usage
  - Failed PST processing jobs
  - Database connection errors
  - Storage space warnings
  - API error rates

## Maintenance

### Daily Tasks
- [ ] Check system health dashboard
- [ ] Review error logs
- [ ] Monitor storage usage
- [ ] Check processing queue status

### Weekly Tasks
- [ ] Test backups restoration
- [ ] Review security logs
- [ ] Update virus definitions
- [ ] Check for security updates

### Monthly Tasks
- [ ] Full system backup
- [ ] Performance analysis
- [ ] Security audit
- [ ] Update documentation

## Troubleshooting

### Common Issues

1. **PST Processing Failures**
   ```bash
   # Check worker logs
   docker-compose logs -f worker
   
   # Restart workers
   docker-compose restart worker beat
   ```

2. **Database Connection Issues**
   ```bash
   # Check postgres logs
   docker-compose logs postgres
   
   # Test connection
   docker exec -it vericase-postgres psql -U vericase -d vericase
   ```

3. **Storage Issues**
   ```bash
   # Check MinIO/S3
   docker-compose logs minio
   
   # Verify bucket access
   aws s3 ls s3://vericase-files/
   ```

## Scaling

### Horizontal Scaling
1. **API Servers**: Add more API replicas behind load balancer
2. **Workers**: Increase worker replicas for PST processing
3. **Database**: Set up read replicas for PostgreSQL
4. **Cache**: Use Redis cluster for high availability

### Vertical Scaling
1. **PST Processing**: Increase worker memory for large files
2. **Database**: Upgrade to larger instance for better performance
3. **OpenSearch**: Add more nodes for better search performance

## Security Hardening

### Network Security
```nginx
# nginx.conf example
server {
    listen 443 ssl http2;
    server_name vericase.yourdomain.com;

    ssl_certificate /etc/ssl/certs/vericase.crt;
    ssl_certificate_key /etc/ssl/private/vericase.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Content-Security-Policy "default-src 'self';" always;

    location / {
        proxy_pass http://localhost:8010;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Application Security
- [ ] Enable rate limiting on API endpoints
- [ ] Configure CORS properly
- [ ] Use environment-specific secrets
- [ ] Enable audit logging
- [ ] Regular security scans

## Support

For production support:
- Documentation: `/docs`
- Logs location: `/var/log/vericase/`
- Support email: support@vericase.com
- Emergency contact: +1-xxx-xxx-xxxx
