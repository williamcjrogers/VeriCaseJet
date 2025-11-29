# Check API status after PostgreSQL deployment
$EC2_IP = "18.130.216.34"
$KEY_PATH = "C:\Users\William\Documents\Projects\VeriCase Analysis\VeriCase-Safe.pem"

Write-Host "Checking API status on EC2..." -ForegroundColor Yellow

$checkCommands = @"
cd ~/vericase
echo "=== Container Status ==="
sudo docker-compose ps
echo ""
echo "=== API Logs (last 50 lines) ==="
sudo docker-compose logs --tail=50 api
echo ""
echo "=== Database Logs ==="
sudo docker-compose logs --tail=20 db
echo ""
echo "=== Test API locally ==="
sleep 5
curl -v http://localhost:8000/health 2>&1 | head -20
"@

ssh -i $KEY_PATH ec2-user@$EC2_IP $checkCommands

Write-Host "`n=== If API is working locally ===" -ForegroundColor Green
Write-Host "Access VeriCase at: http://$EC2_IP:8010/login.html" -ForegroundColor Cyan
