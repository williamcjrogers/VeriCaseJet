# VeriCase EC2 Complete Fix Script
# Automatically diagnoses and fixes EC2 deployment issues

param(
    [string]$InstanceName = "VeriCase",
    [string]$KeyPath = "C:\Users\William\Documents\Projects\VeriCase Analysis\VeriCase-Safe.pem"
)

$ErrorActionPreference = "Continue"
Write-Host "=== VeriCase EC2 Complete Fix ===" -ForegroundColor Cyan

# Step 1: Find EC2 Instance
Write-Host "`n[1/6] Finding EC2 instance..." -ForegroundColor Yellow
$instance = aws ec2 describe-instances `
    --filters "Name=tag:Name,Values=$InstanceName" "Name=instance-state-name,Values=running" `
    --query "Reservations[0].Instances[0].[InstanceId,PublicIpAddress,SecurityGroups[0].GroupId,State.Name]" `
    --output json | ConvertFrom-Json

if (-not $instance -or $instance.Count -lt 4) {
    Write-Host "✗ EC2 instance not found or not running" -ForegroundColor Red
    Write-Host "Searching for any running instances..." -ForegroundColor Yellow
    aws ec2 describe-instances --filters "Name=instance-state-name,Values=running" --query "Reservations[].Instances[].[InstanceId,Tags[?Key=='Name'].Value|[0],PublicIpAddress,State.Name]" --output table
    exit 1
}

$instanceId = $instance[0]
$publicIp = $instance[1]
$sgId = $instance[2]
$state = $instance[3]

Write-Host "✓ Found instance: $instanceId" -ForegroundColor Green
Write-Host "  Public IP: $publicIp" -ForegroundColor White
Write-Host "  Security Group: $sgId" -ForegroundColor White
Write-Host "  State: $state" -ForegroundColor White

# Step 2: Check Security Group Rules
Write-Host "`n[2/6] Checking security group rules..." -ForegroundColor Yellow
$sgRules = aws ec2 describe-security-groups --group-ids $sgId --query "SecurityGroups[0].IpPermissions[?FromPort==``8010`` || FromPort==``8000``]" --output json | ConvertFrom-Json

$port8010Open = $sgRules | Where-Object { $_.FromPort -eq 8010 }
$port8000Open = $sgRules | Where-Object { $_.FromPort -eq 8000 }

if (-not $port8010Open) {
    Write-Host "  Opening port 8010..." -ForegroundColor Yellow
    aws ec2 authorize-security-group-ingress --group-id $sgId --protocol tcp --port 8010 --cidr 0.0.0.0/0 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ Port 8010 opened" -ForegroundColor Green
    } else {
        Write-Host "  ℹ Port 8010 already open or failed" -ForegroundColor Gray
    }
} else {
    Write-Host "  ✓ Port 8010 already open" -ForegroundColor Green
}

if (-not $port8000Open) {
    Write-Host "  Opening port 8000..." -ForegroundColor Yellow
    aws ec2 authorize-security-group-ingress --group-id $sgId --protocol tcp --port 8000 --cidr 0.0.0.0/0 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ Port 8000 opened" -ForegroundColor Green
    } else {
        Write-Host "  ℹ Port 8000 already open or failed" -ForegroundColor Gray
    }
} else {
    Write-Host "  ✓ Port 8000 already open" -ForegroundColor Green
}

# Step 3: Check SSH Key
Write-Host "`n[3/6] Checking SSH key..." -ForegroundColor Yellow
if (Test-Path $KeyPath) {
    Write-Host "✓ SSH key found: $KeyPath" -ForegroundColor Green
} else {
    Write-Host "✗ SSH key not found: $KeyPath" -ForegroundColor Red
    Write-Host "Please provide correct path to .pem file" -ForegroundColor Yellow
    exit 1
}

# Step 4: Check Docker on EC2
Write-Host "`n[4/6] Checking Docker containers on EC2..." -ForegroundColor Yellow
$dockerCheck = @"
cd /home/ec2-user/pst-analysis-engine 2>/dev/null || cd ~/vericase 2>/dev/null || cd ~ || exit 1
echo "Current directory: `$(pwd)"
echo ""
echo "=== Docker Compose Status ==="
if command -v docker-compose &> /dev/null; then
    sudo docker-compose ps 2>/dev/null || sudo /usr/local/bin/docker-compose ps 2>/dev/null || echo "docker-compose not found"
elif command -v docker &> /dev/null; then
    sudo docker compose ps 2>/dev/null || echo "docker compose not available"
else
    echo "Docker not installed"
fi
echo ""
echo "=== Running Containers ==="
sudo docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "Cannot list containers"
"@

$sshResult = ssh -i $KeyPath -o StrictHostKeyChecking=no -o ConnectTimeout=10 ec2-user@$publicIp $dockerCheck 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host $sshResult
} else {
    Write-Host "✗ SSH connection failed" -ForegroundColor Red
    Write-Host $sshResult -ForegroundColor Red
    Write-Host "`nTroubleshooting:" -ForegroundColor Yellow
    Write-Host "1. Check if EC2 instance is running" -ForegroundColor White
    Write-Host "2. Verify SSH key permissions (should be read-only)" -ForegroundColor White
    Write-Host "3. Check security group allows SSH (port 22)" -ForegroundColor White
    exit 1
}

# Step 5: Test API Endpoints
Write-Host "`n[5/6] Testing API endpoints..." -ForegroundColor Yellow

Write-Host "  Testing http://${publicIp}:8010/health" -ForegroundColor White
try {
    $response = Invoke-WebRequest -Uri "http://${publicIp}:8010/health" -TimeoutSec 5 -UseBasicParsing
    Write-Host "  ✓ Port 8010 responding: $($response.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Port 8010 not responding: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "  Testing http://${publicIp}:8000/health" -ForegroundColor White
try {
    $response = Invoke-WebRequest -Uri "http://${publicIp}:8000/health" -TimeoutSec 5 -UseBasicParsing
    Write-Host "  ✓ Port 8000 responding: $($response.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Port 8000 not responding: $($_.Exception.Message)" -ForegroundColor Red
}

# Step 6: Summary and Next Steps
Write-Host "`n[6/6] Summary" -ForegroundColor Yellow
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray

Write-Host "`n📋 EC2 Instance Details:" -ForegroundColor Cyan
Write-Host "  Instance ID: $instanceId"
Write-Host "  Public IP: $publicIp"
Write-Host "  Security Group: $sgId"

Write-Host "`n🌐 Access URLs:" -ForegroundColor Cyan
Write-Host "  Main App: http://${publicIp}:8010" -ForegroundColor White
Write-Host "  API: http://${publicIp}:8000" -ForegroundColor White
Write-Host "  Login: http://${publicIp}:8010/login.html" -ForegroundColor White

Write-Host "`n🔧 Quick Commands:" -ForegroundColor Cyan
Write-Host "  SSH: ssh -i `"$KeyPath`" ec2-user@$publicIp" -ForegroundColor White
Write-Host "  Logs: ssh -i `"$KeyPath`" ec2-user@$publicIp 'sudo docker logs vericase-api'" -ForegroundColor White
Write-Host "  Restart: ssh -i `"$KeyPath`" ec2-user@$publicIp 'cd ~/vericase && sudo docker-compose restart'" -ForegroundColor White

Write-Host "`n✅ Script complete!" -ForegroundColor Green
