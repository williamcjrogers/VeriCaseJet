# Restart application to load new secrets
$EC2_IP = "18.130.216.34"
$KEY_PATH = "VeriCase-Safe.pem"

Write-Host "Restarting application to load new API keys..." -ForegroundColor Green

# Restart the application
ssh -i $KEY_PATH ubuntu@${EC2_IP} "cd /home/ubuntu/pst-analysis-engine && sudo docker-compose restart"

Write-Host "Application restarted! New keys should be loaded." -ForegroundColor Green
Write-Host "Test at: http://${EC2_IP}:8010/ui/admin-settings.html" -ForegroundColor Cyan