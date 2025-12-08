# Fix EC2 to use Secrets Manager for AI keys
$EC2_IP = "18.175.232.87"
$KEY_PATH = "VeriCase-Safe.pem"

Write-Host "Configuring EC2 to use Secrets Manager..." -ForegroundColor Green

# Add secrets manager config to .env.production
ssh -i $KEY_PATH ubuntu@${EC2_IP} "echo 'AWS_SECRETS_MANAGER_AI_KEYS=vericase/api-keys' >> /home/ubuntu/pst-analysis-engine/.env.production"

# Restart the application
ssh -i $KEY_PATH ubuntu@${EC2_IP} "cd /home/ubuntu/pst-analysis-engine && sudo docker-compose restart"

Write-Host "EC2 now configured to use Secrets Manager for AI keys!" -ForegroundColor Green