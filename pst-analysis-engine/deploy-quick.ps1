#!/usr/bin/env pwsh
# Quick deploy to EC2 - run this after pushing to GitHub

Write-Host "🚀 Deploying VeriCase to EC2..." -ForegroundColor Cyan

ssh ec2-user@35.179.167.235 @"
cd ~/vericase
echo '📥 Pulling latest code...'
git pull origin main
echo '🐳 Pulling Docker images...'
docker-compose pull
echo '🔄 Restarting services...'
docker-compose down
docker-compose up -d
echo '✅ Deployment complete!'
docker-compose ps
"@

Write-Host ""
Write-Host "✅ VeriCase deployed successfully!" -ForegroundColor Green
Write-Host "🌐 Access at: http://35.179.167.235:8010" -ForegroundColor Yellow
