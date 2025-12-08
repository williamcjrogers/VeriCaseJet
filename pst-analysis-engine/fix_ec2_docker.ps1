# Fix EC2 Docker crash loop
$EC2_IP = "18.175.232.87"
$KEY_PATH = "C:\Users\William\Documents\Projects\VeriCase Analysis\VeriCase-Safe.pem"

Write-Host "Fixing EC2 Docker..." -ForegroundColor Yellow

$fixCommands = @"
# Stop everything
cd /home/ec2-user/pst-analysis-engine 2>/dev/null || cd ~
sudo /usr/local/bin/docker-compose -f docker-compose.prod.yml down 2>/dev/null || true
sudo docker stop `$(sudo docker ps -aq) 2>/dev/null || true

# Create minimal working setup
mkdir -p ~/vericase
cd ~/vericase

cat > docker-compose.yml << 'EOF'
version: '3.8'
services:
  api:
    image: ghcr.io/williamcjrogers/vericasejet:latest
    ports:
      - "8010:8000"
    environment:
      - JWT_SECRET=c3bef73578895c08045f8848192958b2dbfaf55a57f97509553c3d5324a7d2b1
      - DEV_NO_AUTH=true
    restart: unless-stopped
EOF

# Start fresh
sudo docker pull ghcr.io/williamcjrogers/vericasejet:latest
sudo docker-compose up -d
sleep 5
sudo docker-compose ps
sudo docker-compose logs --tail=20 api
"@

ssh -i $KEY_PATH ec2-user@$EC2_IP $fixCommands

Write-Host "`nTesting..." -ForegroundColor Green
Start-Sleep -Seconds 3
curl http://18.175.232.87:8010/health
