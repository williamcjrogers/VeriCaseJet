# VeriCase Operations Scripts

Consolidated operations scripts for deploying and managing VeriCase.

## Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `deploy.sh` / `deploy.ps1` | Deploy application | `./ops/deploy.sh [local\|ec2\|eks]` |
| `diagnose.sh` / `diagnose.ps1` | Run diagnostics | `./ops/diagnose.sh [local\|ec2\|aws\|all]` |
| `setup-ssh.ps1` | Prime SSH config + known_hosts (Windows) | `powershell -ExecutionPolicy Bypass -File .\\ops\\setup-ssh.ps1` |
| `setup-aws.sh` | Configure AWS services | `./ops/setup-aws.sh [minimal\|standard\|full]` |
| `ec2-bootstrap.sh` | EC2 UserData script | Paste into EC2 launch wizard |
| `reset-db.sh` | Reset database | `./ops/reset-db.sh [local\|ec2]` |

## Quick Start

### Local Development
```bash
# Deploy locally with Docker
./ops/deploy.sh local

# Check status
./ops/diagnose.sh local
```

### EC2 Deployment
```bash
# Deploy to EC2
export SSH_KEY_PATH=~/.ssh/VeriCase-Safe.pem
./ops/deploy.sh ec2

# Check EC2 status
./ops/diagnose.sh ec2
```

### Windows SSH bootstrap (recommended)
```powershell
powershell -ExecutionPolicy Bypass -File .\ops\setup-ssh.ps1
```

### EKS Deployment
```bash
# Deploy to Kubernetes
./ops/deploy.sh eks

# Check all services
./ops/diagnose.sh all
```

### AWS Setup
```bash
# Minimal setup (~$1/month) - just S3
./ops/setup-aws.sh minimal

# Standard setup (~$5/month) - S3 + Secrets
./ops/setup-aws.sh standard

# Full setup (~$200/month) - everything
./ops/setup-aws.sh full

# Check current AWS resources
./ops/setup-aws.sh status
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SSH_KEY_PATH` | Path to EC2 SSH key | `~/.ssh/VeriCase-Safe.pem` |
| `AWS_REGION` | AWS region | `eu-west-2` |

### Actual AWS Resources

| Resource | Value |
|----------|-------|
| Account ID | `526015377510` |
| Region | `eu-west-2` |
| EC2 (Production) | `18.175.232.87` |
| EKS Cluster | `vericase-cluster` |
| RDS | `database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com` |
| Redis | `master.vericase-redis-simple.dbbgbx.euw2.cache.amazonaws.com` |
| S3 Bucket | `vericase-docs` |
| Secrets | `vericase/ai-api-keys` |

## Troubleshooting

### API not responding
```bash
# Check logs
docker-compose -f docker-compose.prod.yml logs api

# Restart API
docker-compose -f docker-compose.prod.yml restart api
```

### Database issues
```bash
# Check database connection
docker-compose -f docker-compose.prod.yml exec postgres pg_isready

# Reset database (WARNING: deletes data!)
./ops/reset-db.sh local
```

### AWS credentials
```bash
# Verify credentials
aws sts get-caller-identity

# Configure credentials
aws configure
```
