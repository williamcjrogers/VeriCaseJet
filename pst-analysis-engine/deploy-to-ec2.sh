#!/bin/bash
# Deploy VeriCase to EC2 instance

set -e

EC2_HOST="${1:-your-ec2-ip}"
KEY_FILE="${2:-~/.ssh/your-key.pem}"

echo "Deploying to $EC2_HOST..."

# Copy files to EC2
rsync -avz --exclude 'node_modules' --exclude '__pycache__' --exclude '.git' \
  -e "ssh -i $KEY_FILE" \
  ./ ubuntu@$EC2_HOST:/opt/vericase/

# Copy production env
scp -i $KEY_FILE .env.production ubuntu@$EC2_HOST:/opt/vericase/.env

# Deploy on EC2
ssh -i $KEY_FILE ubuntu@$EC2_HOST << 'EOF'
cd /opt/vericase
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml pull
docker-compose -f docker-compose.prod.yml up -d --build
docker-compose -f docker-compose.prod.yml ps
EOF

echo "Deployment complete! Access at http://$EC2_HOST:8010"
