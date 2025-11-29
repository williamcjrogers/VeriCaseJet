# Fix EC2 .env file via SSH
$EC2_IP = "18.130.216.34"
$KEY_PATH = "C:\Users\William\Documents\Projects\VeriCase Analysis\VeriCase-Safe.pem"

# Commands to run on EC2
$commands = @"
cd /home/ec2-user/pst-analysis-engine
sed -i '/JWT_SECRET/d' .env
echo 'JWT_SECRET=c3bef73578895c08045f8848192958b2dbfaf55a57f97509553c3d5324a7d2b1' >> .env
grep JWT_SECRET .env
sudo /usr/local/bin/docker-compose -f docker-compose.prod.yml restart api worker beat
"@

Write-Host "Connecting to EC2 to fix .env file..." -ForegroundColor Yellow

# Try SSH connection
ssh -i $KEY_PATH ec2-user@$EC2_IP $commands

Write-Host "`nDone! Check if API is running:" -ForegroundColor Green
Write-Host "curl http://$EC2_IP:8010/health" -ForegroundColor Cyan
