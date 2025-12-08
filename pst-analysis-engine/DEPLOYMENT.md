# VeriCase EC2 Deployment Guide

## GitHub Actions Automated Deployment

The deployment is fully automated through GitHub Actions. When you push to `main`, the following happens:

1. **Build & Push** (`docker-publish.yml`) - Builds the Docker image and pushes to Docker Hub
2. **Deploy to EC2** (`deploy-ec2.yml`) - Automatically triggered after successful build:
   - Copies `docker-compose-s3.yml` to EC2
   - Copies migration files to EC2
   - Pulls latest Docker images
   - Restarts containers
   - Runs database migrations
   - Verifies deployment

## Required GitHub Secrets

You need to configure the following secrets in your GitHub repository:

### 1. `DOCKERHUB_USERNAME`
Your Docker Hub username: `wcjrogers`

### 2. `DOCKERHUB_TOKEN`
Your Docker Hub access token (not password). Generate at:
https://hub.docker.com/settings/security

### 3. `EC2_SSH_KEY` ⚠️ NEW - Required for deployment
The contents of your `VeriCase-Safe.pem` file.

**To add this secret:**
1. Go to your GitHub repo → Settings → Secrets and variables → Actions
2. Click "New repository secret"
3. Name: `EC2_SSH_KEY`
4. Value: Paste the entire contents of `VeriCase-Safe.pem` including:
   ```
   -----BEGIN RSA PRIVATE KEY-----
   ... (your key content) ...
   -----END RSA PRIVATE KEY-----
   ```
5. Click "Add secret"

## Manual Deployment

If you need to deploy manually:

```bash
# SSH to EC2
ssh -i "VeriCase-Safe.pem" ec2-user@18.175.232.87

# Navigate to deployment directory
cd ~/vericase

# Pull latest images
sudo docker-compose pull

# Restart with new images
sudo docker-compose down
sudo docker-compose up -d

# Check status
sudo docker-compose ps
sudo docker logs vericase-worker-1 --tail 50
```

## Running Migrations Manually

```bash
# Copy migration file to EC2
scp -i "VeriCase-Safe.pem" pst-analysis-engine/api/migrations/*.sql ec2-user@18.175.232.87:~/vericase/migrations/

# SSH and run migration
ssh -i "VeriCase-Safe.pem" ec2-user@18.175.232.87
cd ~/vericase
cat migrations/20251130_fix_file_type_column.sql | sudo docker exec -i vericase-db-1 psql -U vericase -d vericase
```

## Troubleshooting

### Check container logs
```bash
sudo docker logs vericase-api-1 --tail 100
sudo docker logs vericase-worker-1 --tail 100
```

### Check database
```bash
sudo docker exec -it vericase-db-1 psql -U vericase -d vericase
```

### Restart specific service
```bash
sudo docker-compose restart worker
sudo docker-compose restart api
```

## EC2 Instance Details

- **IP Address:** 18.175.232.87
- **Region:** eu-west-2 (London)
- **User:** ec2-user
- **Deploy Path:** ~/vericase
- **API Port:** 8010

