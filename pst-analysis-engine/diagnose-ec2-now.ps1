# Quick EC2 Diagnosis
$EC2_IP = "18.175.232.87"
$KEY = "C:\Users\William\Documents\Projects\VeriCase Analysis\VeriCase-Safe.pem"

Write-Host "=== EC2 Docker Status ===" -ForegroundColor Cyan

$cmd = @"
echo "=== Docker Containers ==="
sudo docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
echo ""
echo "=== Docker Compose Status ==="
cd /home/ec2-user/pst-analysis-engine 2>/dev/null && sudo docker-compose ps || cd ~/vericase 2>/dev/null && sudo docker-compose ps || echo "No compose found"
echo ""
echo "=== API Logs (last 20) ==="
sudo docker logs vericase-api --tail 20 2>/dev/null || sudo docker logs pst-analysis-engine-api-1 --tail 20 2>/dev/null || echo "No API container"
"@

ssh -i $KEY -o StrictHostKeyChecking=no ec2-user@$EC2_IP $cmd
