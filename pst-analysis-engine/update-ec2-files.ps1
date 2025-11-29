# Update EC2 with latest changes
$EC2_IP = "18.130.216.34"
$KEY_PATH = "VeriCase-Safe.pem"

Write-Host "Updating EC2 files..." -ForegroundColor Green

# Copy updated admin-settings.html
scp -i $KEY_PATH ui/admin-settings.html ubuntu@${EC2_IP}:/home/ubuntu/pst-analysis-engine/ui/admin-settings.html

# Copy test script
scp -i $KEY_PATH test_all_ai_keys.py ubuntu@${EC2_IP}:/home/ubuntu/pst-analysis-engine/test_all_ai_keys.py

Write-Host "Files updated on EC2!" -ForegroundColor Green
Write-Host "Admin settings: http://${EC2_IP}:8010/ui/admin-settings.html" -ForegroundColor Cyan