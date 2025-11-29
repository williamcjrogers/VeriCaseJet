# Deploy by building on EC2
$EC2_IP = "18.130.216.34"
$KEY_PATH = "C:\Users\William\Documents\Projects\VeriCase Analysis\VeriCase-Safe.pem"

Write-Host "Copying files to EC2..." -ForegroundColor Yellow

# Copy essential files
scp -i $KEY_PATH -r api ec2-user@${EC2_IP}:/tmp/
scp -i $KEY_PATH -r ui ec2-user@${EC2_IP}:/tmp/
scp -i $KEY_PATH Dockerfile ec2-user@${EC2_IP}:/tmp/
scp -i $KEY_PATH requirements.txt ec2-user@${EC2_IP}:/tmp/

Write-Host "Building and running on EC2..." -ForegroundColor Yellow

$buildCommands = @"
cd /tmp
sudo docker build -t vericase-api .

# Create simple docker-compose
mkdir -p ~/vericase
cd ~/vericase

cat > docker-compose.yml << 'EOF'
services:
  db:
    image: postgres:15-alpine
    environment:
      - POSTGRES_USER=vericase
      - POSTGRES_PASSWORD=vericase123
      - POSTGRES_DB=vericase
    volumes:
      - postgres-data:/var/lib/postgresql/data
    restart: unless-stopped

  api:
    image: vericase-api
    ports:
      - "8010:8000"
    depends_on:
      - db
    environment:
      - JWT_SECRET=c3bef73578895c08045f8848192958b2dbfaf55a57f97509553c3d5324a7d2b1
      - DEV_NO_AUTH=true
      - DATABASE_URL=postgresql://vericase:vericase123@db:5432/vericase
      - USE_AWS_SERVICES=false
      - MINIO_ACCESS_KEY=admin
      - MINIO_SECRET_KEY=admin123
      - MINIO_ENDPOINT=http://localhost:9000
      - MINIO_BUCKET=vericase
    restart: unless-stopped

volumes:
  postgres-data:
EOF

sudo docker-compose up -d
sleep 5
sudo docker-compose ps
sudo docker-compose logs api
"@

ssh -i $KEY_PATH ec2-user@$EC2_IP $buildCommands

Write-Host "`nTesting API..." -ForegroundColor Green
Start-Sleep -Seconds 2
curl http://18.130.216.34:8010/health
