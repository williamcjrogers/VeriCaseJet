#!/bin/bash
# EC2 User Data Script - Paste this when launching EC2 instance
# This runs automatically on first boot

exec > >(tee /var/log/vericase-deploy.log) 2>&1

echo "Starting VeriCase deployment..."

# Update system
apt update && apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker ubuntu

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Install git
apt install -y git

# Create app directory
mkdir -p /opt/vericase
cd /opt/vericase

# Clone repository
git clone https://github.com/williamcjrogers/VeriCaseJet.git
cd VeriCaseJet/pst-analysis-engine

# Generate secure passwords
DB_PASSWORD=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 24)
MINIO_ACCESS_KEY=$(openssl rand -base64 16 | tr -dc 'a-zA-Z0-9' | head -c 16)
MINIO_SECRET_KEY=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
SECRET_KEY=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)

# Create .env file
cat > .env << EOF
DB_USER=vericase
DB_PASSWORD=$DB_PASSWORD
DB_NAME=vericase
MINIO_ACCESS_KEY=$MINIO_ACCESS_KEY
MINIO_SECRET_KEY=$MINIO_SECRET_KEY
S3_ENDPOINT=http://localhost:9000
S3_BUCKET=vericase-files
SECRET_KEY=$SECRET_KEY
JWT_SECRET=$SECRET_KEY
ANTHROPIC_API_KEY=REPLACE_WITH_YOUR_KEY
APP_ENV=production
LOG_LEVEL=INFO
EOF

# Save credentials for user
cat > /home/ubuntu/vericase-credentials.txt << EOF
VeriCase Credentials
====================
Database Password: $DB_PASSWORD
MinIO Access Key: $MINIO_ACCESS_KEY
MinIO Secret Key: $MINIO_SECRET_KEY
Secret Key: $SECRET_KEY

IMPORTANT: Add your ANTHROPIC_API_KEY to /opt/vericase/VeriCaseJet/pst-analysis-engine/.env

Access:
- API: http://YOUR_IP:8010
- MinIO Console: http://YOUR_IP:9001
- Flower (Celery): http://YOUR_IP:5555
EOF
chown ubuntu:ubuntu /home/ubuntu/vericase-credentials.txt

# Set permissions
chown -R ubuntu:ubuntu /opt/vericase

# Start services
docker-compose -f docker-compose.prod.yml up -d

echo "VeriCase deployment complete!"

