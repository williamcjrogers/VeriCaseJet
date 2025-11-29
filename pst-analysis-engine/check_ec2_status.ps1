# Check EC2 Docker status and open security group
$EC2_IP = "18.130.216.34"
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

Write-Host "`n=== SECURITY GROUP FIX ===" -ForegroundColor Cyan
Write-Host "Go to AWS Console and add these inbound rules to your security group:" -ForegroundColor Yellow
Write-Host "1. Type: Custom TCP, Port: 8010, Source: 0.0.0.0/0 (or your IP)" -ForegroundColor White
Write-Host "2. Type: Custom TCP, Port: 8000, Source: 0.0.0.0/0 (or your IP)" -ForegroundColor White
Write-Host "`nOr run this AWS CLI command:" -ForegroundColor Yellow
Write-Host "aws ec2 authorize-security-group-ingress --group-id sg-XXXXX --protocol tcp --port 8010 --cidr 0.0.0.0/0" -ForegroundColor White
