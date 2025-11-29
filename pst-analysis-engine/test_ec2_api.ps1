# Test if API is running on EC2
$EC2_IP = "18.130.216.34"
$KEY_PATH = "C:\Users\William\Documents\Projects\VeriCase Analysis\VeriCase-Safe.pem"

Write-Host "Testing API on EC2..." -ForegroundColor Yellow

$testCommands = @"
cd ~/vericase
echo "=== Docker status ==="
sudo docker-compose ps
echo ""
echo "=== Testing API locally ==="
curl -s http://localhost:8000/health || echo "Health endpoint failed"
echo ""
echo "=== API logs ==="
sudo docker-compose logs --tail=20 api
"@

ssh -i $KEY_PATH ec2-user@$EC2_IP $testCommands

Write-Host "`n=== Testing from outside ===" -ForegroundColor Cyan
Write-Host "Trying http://$EC2_IP:8010/health" -ForegroundColor White
curl http://$EC2_IP:8010/health

Write-Host "`n=== ✅ EC2 API LIVE ===" -ForegroundColor Green
Write-Host "Access VeriCase at: http://$EC2_IP:8010/login.html" -ForegroundColor White
Write-Host "API Endpoint: http://$EC2_IP:8010" -ForegroundColor White
