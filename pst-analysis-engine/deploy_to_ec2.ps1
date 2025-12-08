# Deploy VeriCase to EC2
$EC2_IP = "18.175.232.87"
$KEY_PATH = "C:\Users\William\Documents\Projects\VeriCase Analysis\VeriCase-Safe.pem"

Write-Host "Deploying to EC2: $EC2_IP" -ForegroundColor Green

# Create deployment package
Write-Host "`n1. Creating deployment package..." -ForegroundColor Yellow
$excludeDirs = @('.git', '.venv', 'venv', '__pycache__', 'node_modules', 'uploads', 'data', 'evidence', '.ruff_cache')
$tempZip = "$env:TEMP\vericase-deploy.zip"
if (Test-Path $tempZip) { Remove-Item $tempZip }

# Copy to EC2
Write-Host "`n2. Copying files to EC2..." -ForegroundColor Yellow
scp -i $KEY_PATH -r api ui worker docker-compose.prod.yml .env.production ec2-user@${EC2_IP}:/tmp/vericase/

# Setup on EC2
Write-Host "`n3. Setting up on EC2..." -ForegroundColor Yellow
$setupCommands = @"
sudo mkdir -p /home/ec2-user/pst-analysis-engine
sudo mv /tmp/vericase/* /home/ec2-user/pst-analysis-engine/
cd /home/ec2-user/pst-analysis-engine
cp .env.production .env
echo 'JWT_SECRET=c3bef73578895c08045f8848192958b2dbfaf55a57f97509553c3d5324a7d2b1' >> .env
sudo /usr/local/bin/docker-compose -f docker-compose.prod.yml up -d
sudo /usr/local/bin/docker-compose -f docker-compose.prod.yml ps
"@

ssh -i $KEY_PATH ec2-user@$EC2_IP $setupCommands

Write-Host "`n4. Opening security group ports..." -ForegroundColor Yellow
Write-Host "Go to AWS Console > EC2 > Security Groups" -ForegroundColor Cyan
Write-Host "Add inbound rules: TCP 8010, TCP 8000 from 0.0.0.0/0" -ForegroundColor White

Write-Host "`nDeployment complete! Access at: http://$EC2_IP:8010" -ForegroundColor Green
