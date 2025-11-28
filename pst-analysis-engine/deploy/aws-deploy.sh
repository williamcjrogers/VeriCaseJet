#!/bin/bash
# VeriCase AWS EC2 Deployment Script
# Run this on a fresh Ubuntu 22.04 EC2 instance (t3.large or larger)

set -e

echo "=========================================="
echo "  VeriCase Production Deployment Script"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration - EDIT THESE VALUES
GITHUB_REPO="https://github.com/williamcjrogers/VeriCaseJet.git"
APP_DIR="/opt/vericase"
DOMAIN="your-domain.com"  # Optional: your domain name

# Prompt for secrets if not set
if [ -z "$DB_PASSWORD" ]; then
    DB_PASSWORD=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 24)
    echo -e "${YELLOW}Generated DB_PASSWORD: $DB_PASSWORD${NC}"
fi

if [ -z "$MINIO_ACCESS_KEY" ]; then
    MINIO_ACCESS_KEY=$(openssl rand -base64 16 | tr -dc 'a-zA-Z0-9' | head -c 16)
    echo -e "${YELLOW}Generated MINIO_ACCESS_KEY: $MINIO_ACCESS_KEY${NC}"
fi

if [ -z "$MINIO_SECRET_KEY" ]; then
    MINIO_SECRET_KEY=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
    echo -e "${YELLOW}Generated MINIO_SECRET_KEY: $MINIO_SECRET_KEY${NC}"
fi

if [ -z "$SECRET_KEY" ]; then
    SECRET_KEY=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
    echo -e "${YELLOW}Generated SECRET_KEY: $SECRET_KEY${NC}"
fi

echo ""
echo -e "${GREEN}Step 1: Updating system...${NC}"
sudo apt update && sudo apt upgrade -y

echo ""
echo -e "${GREEN}Step 2: Installing Docker...${NC}"
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker $USER
fi

echo ""
echo -e "${GREEN}Step 3: Installing Docker Compose...${NC}"
if ! command -v docker-compose &> /dev/null; then
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
fi

echo ""
echo -e "${GREEN}Step 4: Cloning repository...${NC}"
sudo mkdir -p $APP_DIR
sudo chown $USER:$USER $APP_DIR
cd $APP_DIR

if [ -d "VeriCaseJet" ]; then
    cd VeriCaseJet
    git pull
else
    git clone $GITHUB_REPO
    cd VeriCaseJet
fi

cd pst-analysis-engine

echo ""
echo -e "${GREEN}Step 5: Setting up environment file...${NC}"

# Check if .env.production exists, use it
if [ -f ".env.production" ]; then
    echo -e "${GREEN}Found .env.production - using existing config${NC}"
    cp .env.production .env
    echo -e "${YELLOW}IMPORTANT: Verify all values in .env are correct for your AWS setup${NC}"
else
    echo -e "${YELLOW}No .env.production found - creating template${NC}"
    cat > .env << EOF
# AWS mode flag
USE_AWS_SERVICES=true

# AWS S3 settings
AWS_STORAGE_BUCKET_NAME=vericase-data
S3_BUCKET_NAME=vericase-data
AWS_S3_REGION_NAME=eu-west-2
AWS_REGION=eu-west-2

# Database - UPDATE WITH YOUR RDS ENDPOINT
DATABASE_URL=postgresql://user:password@your-rds-endpoint:5432/vericase

# OpenSearch - UPDATE WITH YOUR OPENSEARCH ENDPOINT
OPENSEARCH_HOST=https://your-opensearch-endpoint
OPENSEARCH_PORT=443
OPENSEARCH_USE_SSL=true
OPENSEARCH_VERIFY_CERTS=true
OPENSEARCH_INDEX=emails

# Redis - UPDATE WITH YOUR ELASTICACHE ENDPOINT
REDIS_URL=redis://your-elasticache-endpoint:6379/0
CELERY_QUEUE=pst-processing

# Tika - UPDATE IF DEPLOYING TIKA
TIKA_URL=http://your-tika-url:9998

# API settings
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=https://your-domain.com
JWT_SECRET=$(openssl rand -base64 48)
JWT_ISSUER=vericase-pst-analysis
JWT_EXPIRE_MIN=7200

# Admin
ADMIN_EMAIL=admin@vericase.com
ADMIN_PASSWORD=CHANGE_THIS_PASSWORD

# AI API Keys - ADD YOUR KEYS
CLAUDE_API_KEY=
OPENAI_API_KEY=
GEMINI_API_KEY=

# Python
PYTHONUNBUFFERED=1
DEV_NO_AUTH=false
EOF
fi

echo ""
echo -e "${GREEN}Step 6: Starting services with Docker Compose...${NC}"
sudo docker-compose -f docker-compose.prod.yml pull
sudo docker-compose -f docker-compose.prod.yml up -d

echo ""
echo -e "${GREEN}Step 7: Waiting for services to be healthy...${NC}"
sleep 30

echo ""
echo -e "${GREEN}Step 8: Checking service status...${NC}"
sudo docker-compose -f docker-compose.prod.yml ps

echo ""
echo "=========================================="
echo -e "${GREEN}  DEPLOYMENT COMPLETE!${NC}"
echo "=========================================="
echo ""
echo "Your VeriCase instance is now running!"
echo ""
echo "Access URLs:"
echo "  - API:      http://$(curl -s ifconfig.me):8010"
echo "  - MinIO:    http://$(curl -s ifconfig.me):9001"
echo "  - Flower:   http://$(curl -s ifconfig.me):5555"
echo ""
echo "Credentials saved to: $APP_DIR/VeriCaseJet/pst-analysis-engine/.env"
echo ""
echo -e "${YELLOW}IMPORTANT: Update ANTHROPIC_API_KEY in .env file!${NC}"
echo ""
echo "Commands:"
echo "  View logs:     cd $APP_DIR/VeriCaseJet/pst-analysis-engine && sudo docker-compose -f docker-compose.prod.yml logs -f"
echo "  Restart:       cd $APP_DIR/VeriCaseJet/pst-analysis-engine && sudo docker-compose -f docker-compose.prod.yml restart"
echo "  Stop:          cd $APP_DIR/VeriCaseJet/pst-analysis-engine && sudo docker-compose -f docker-compose.prod.yml down"
echo ""

