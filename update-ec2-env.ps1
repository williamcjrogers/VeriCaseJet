# Update EC2 .env file to enable Secrets Manager loading
# Run this script to SSH into EC2 and update the environment

$EC2_IP = "18.130.216.34"
$PEM_FILE = "VeriCase-Safe.pem"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Update EC2 Environment for AI Keys" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if PEM file exists
if (-not (Test-Path $PEM_FILE)) {
    Write-Host "[ERROR] PEM file not found: $PEM_FILE" -ForegroundColor Red
    Write-Host "Please ensure the PEM file is in the current directory" -ForegroundColor Yellow
    exit 1
}

Write-Host "Connecting to EC2 at $EC2_IP..." -ForegroundColor Yellow
Write-Host ""

# Commands to run on EC2
$commands = @"
cd /home/ec2-user/VeriCaseJet/pst-analysis-engine

# Backup current .env
cp .env .env.backup.\$(date +%Y%m%d_%H%M%S)

# Add AWS region and Secrets Manager config if not present
grep -q 'AWS_REGION=' .env || echo 'AWS_REGION=eu-west-2' >> .env
grep -q 'AWS_SECRETS_MANAGER_AI_KEYS=' .env || echo 'AWS_SECRETS_MANAGER_AI_KEYS=vericase/ai-api-keys' >> .env

# Show current AI-related env vars
echo ""
echo "=== Current AI Configuration ==="
grep -E '(API_KEY|AWS_REGION|AWS_SECRETS)' .env

# Restart the containers
echo ""
echo "=== Restarting Docker containers ==="
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml pull
docker-compose -f docker-compose.prod.yml up -d

# Wait and check health
echo ""
echo "=== Waiting for API to start ==="
sleep 10
curl -s http://localhost:8010/health
echo ""
curl -s http://localhost:8010/api/ai/status
echo ""
"@

Write-Host "Commands to run on EC2:" -ForegroundColor Gray
Write-Host $commands -ForegroundColor DarkGray
Write-Host ""

# SSH and run commands
Write-Host "Executing on EC2..." -ForegroundColor Yellow
ssh -i $PEM_FILE -o StrictHostKeyChecking=no ec2-user@$EC2_IP $commands

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Done! Check the AI status output above." -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
