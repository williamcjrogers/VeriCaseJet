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

Write-Host "`n=== Next Steps ===" -ForegroundColor Green
Write-Host "If local test works but external doesn't, you need to:" -ForegroundColor Yellow
Write-Host "1. Open port 8010 in EC2 Security Group (already done)" -ForegroundColor White
Write-Host "2. Check if EC2 firewall allows it: sudo iptables -L" -ForegroundColor White
Write-Host "`nIf it works, access VeriCase at: http://$EC2_IP:8010/login.html" -ForegroundColor Green
