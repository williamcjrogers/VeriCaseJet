# Check if Secrets Manager is working on EC2
$EC2_IP = "18.130.216.34"
$KEY_PATH = "VeriCase-Safe.pem"

Write-Host "Checking Secrets Manager status on EC2..." -ForegroundColor Green

# Check if the environment variable is set
Write-Host "`n1. Checking environment configuration:" -ForegroundColor Yellow
ssh -i $KEY_PATH ubuntu@${EC2_IP} "grep AWS_SECRETS_MANAGER_AI_KEYS /home/ubuntu/pst-analysis-engine/.env.production"

# Check if the application can access secrets
Write-Host "`n2. Testing secrets access:" -ForegroundColor Yellow
ssh -i $KEY_PATH ubuntu@${EC2_IP} "cd /home/ubuntu/pst-analysis-engine && python3 -c 'import boto3; client = boto3.client(\"secretsmanager\", region_name=\"eu-west-2\"); print(\"Secrets Manager accessible:\", bool(client.list_secrets()))'"

# Check application logs for secrets loading
Write-Host "`n3. Checking application logs:" -ForegroundColor Yellow
ssh -i $KEY_PATH ubuntu@${EC2_IP} "cd /home/ubuntu/pst-analysis-engine && sudo docker-compose logs api | grep -i 'secret\|key' | tail -5"

Write-Host "`n4. Test the admin interface at:" -ForegroundColor Cyan
Write-Host "   http://${EC2_IP}:8010/ui/admin-settings.html" -ForegroundColor Cyan
Write-Host "   Click 'Refresh Status' to see if keys are loaded" -ForegroundColor Cyan