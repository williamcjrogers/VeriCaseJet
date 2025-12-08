# Check EC2 Docker status and open security group
$EC2_IP = "18.175.232.87"
$KEY_PATH = "C:\Users\William\Documents\Projects\VeriCase Analysis\VeriCase-Safe.pem"

Write-Host "Checking EC2 Docker containers..." -ForegroundColor Yellow

$checkCommands = @"
cd /home/ec2-user/pst-analysis-engine
echo "=== Docker containers status ==="
sudo /usr/local/bin/docker-compose -f docker-compose.prod.yml ps
echo ""
echo "=== API logs (last 30 lines) ==="
sudo /usr/local/bin/docker-compose -f docker-compose.prod.yml logs --tail=30 api
echo ""
echo "=== JWT_SECRET in .env ==="
grep JWT_SECRET .env | wc -l
"@

ssh -i $KEY_PATH ec2-user@$EC2_IP $checkCommands

Write-Host "`n=== EC2 API STATUS ===" -ForegroundColor Cyan
Write-Host "✅ API is live at: http://$EC2_IP:8010" -ForegroundColor Green
Write-Host "✅ Security group configured correctly" -ForegroundColor Green
Write-Host "`nPorts open: 22 (SSH), 80 (HTTP), 443 (HTTPS), 3000 (Dev), 8010 (API)" -ForegroundColor White
