# Restart API with verbose logging
$EC2_IP = "18.130.216.34"
$KEY_PATH = "C:\Users\William\Documents\Projects\VeriCase Analysis\VeriCase-Safe.pem"

Write-Host "Restarting API and watching logs..." -ForegroundColor Yellow

$restartCommands = @"
cd ~/vericase
echo "Restarting API container..."
sudo docker-compose restart api
echo "Waiting 10 seconds..."
sleep 10
echo ""
echo "=== Full API logs ==="
sudo docker-compose logs api
echo ""
echo "=== Testing endpoints ==="
curl -s http://localhost:8000/ || echo "Root failed"
curl -s http://localhost:8000/health || echo "Health failed"
curl -s http://localhost:8000/docs || echo "Docs failed"
"@

ssh -i $KEY_PATH ec2-user@$EC2_IP $restartCommands

Write-Host "`nIf you see 'Application startup complete', try:" -ForegroundColor Green
Write-Host "http://$EC2_IP:8010/login.html" -ForegroundColor Cyan
