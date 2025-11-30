#!/bin/bash
# Quick deploy to EC2 - run this after pushing to GitHub

echo "🚀 Deploying VeriCase to EC2..."

ssh ec2-user@35.179.167.235 << 'ENDSSH'
cd ~/vericase
echo "📥 Pulling latest code..."
git pull origin main
echo "🐳 Pulling Docker images..."
docker-compose pull
echo "🔄 Restarting services..."
docker-compose down
docker-compose up -d
echo "✅ Deployment complete!"
docker-compose ps
ENDSSH

echo ""
echo "✅ VeriCase deployed successfully!"
echo "🌐 Access at: http://35.179.167.235:8010"
