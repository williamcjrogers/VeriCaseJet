# Deploy from Docker Hub
$EC2_IP = "18.130.216.34"
$KEY_PATH = "C:\Users\William\Documents\Projects\VeriCase Analysis\VeriCase-Safe.pem"

Write-Host "Pulling latest image and restarting on EC2..." -ForegroundColor Yellow

ssh -i $KEY_PATH ec2-user@$EC2_IP "cd ~/vericase && sudo docker-compose pull && sudo docker-compose up -d"

Write-Host "`nDeployment complete!" -ForegroundColor Green
Start-Sleep -Seconds 3
curl http://18.130.216.34:8010/health
