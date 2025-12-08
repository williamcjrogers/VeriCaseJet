# Deploy from GitHub Container Registry to EC2
$EC2_IP = "18.175.232.87"
$KEY_PATH = "C:\Users\William\Documents\Projects\VeriCase Analysis\VeriCase-Safe.pem"

Write-Host "Deploying from GitHub to EC2..." -ForegroundColor Green

$deployCommands = @"
cd ~
mkdir -p pst-analysis-engine
cd pst-analysis-engine

# Create docker-compose.prod.yml
cat > docker-compose.prod.yml << 'EOF'
version: '3.8'
services:
  api:
    image: ghcr.io/williamcjrogers/vericasejet:latest
    ports:
      - "8010:8000"
    environment:
      - JWT_SECRET=c3bef73578895c08045f8848192958b2dbfaf55a57f97509553c3d5324a7d2b1
      - DATABASE_URL=postgresql://user:pass@db:5432/vericase
    restart: unless-stopped
EOF

# Pull and start
sudo /usr/local/bin/docker-compose pull
sudo /usr/local/bin/docker-compose up -d
sudo /usr/local/bin/docker-compose ps
"@

Write-Host "Connecting to EC2 and deploying..." -ForegroundColor Yellow
ssh -i $KEY_PATH ec2-user@$EC2_IP $deployCommands

Write-Host "`nDone! Now open port 8010 in AWS Console Security Group" -ForegroundColor Cyan
Write-Host "Then access: http://$EC2_IP:8010" -ForegroundColor Green
