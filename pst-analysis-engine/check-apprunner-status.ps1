# Check AWS App Runner deployment status
$ErrorActionPreference = "Continue"

Write-Host "=== VeriCase App Runner Status ===" -ForegroundColor Cyan

# Get App Runner service details
Write-Host "`n[1/4] Fetching App Runner service..." -ForegroundColor Yellow
$service = aws apprunner list-services --region eu-west-2 --query "ServiceSummaryList[?ServiceName=='VeriCase-api']" --output json | ConvertFrom-Json

if (-not $service -or $service.Count -eq 0) {
    Write-Host "✗ VeriCase-api service not found" -ForegroundColor Red
    Write-Host "`nAll App Runner services:" -ForegroundColor Yellow
    aws apprunner list-services --region eu-west-2 --output table
    exit 1
}

$serviceArn = $service[0].ServiceArn
$serviceUrl = $service[0].ServiceUrl
$status = $service[0].Status

Write-Host "✓ Service found" -ForegroundColor Green
Write-Host "  ARN: $serviceArn" -ForegroundColor White
Write-Host "  URL: https://$serviceUrl" -ForegroundColor White
Write-Host "  Status: $status" -ForegroundColor $(if ($status -eq "RUNNING") { "Green" } else { "Yellow" })

# Get detailed service info
Write-Host "`n[2/4] Getting deployment details..." -ForegroundColor Yellow
$details = aws apprunner describe-service --service-arn $serviceArn --region eu-west-2 --output json | ConvertFrom-Json

$autoDeployEnabled = $details.Service.SourceConfiguration.AutoDeploymentsEnabled
$repoUrl = $details.Service.SourceConfiguration.CodeRepository.RepositoryUrl
$branch = $details.Service.SourceConfiguration.CodeRepository.SourceCodeVersion.Value
$lastDeployment = $details.Service.ServiceId

Write-Host "  Auto-Deploy: $(if ($autoDeployEnabled) { '✓ ENABLED' } else { '✗ DISABLED' })" -ForegroundColor $(if ($autoDeployEnabled) { "Green" } else { "Red" })
Write-Host "  Repository: $repoUrl" -ForegroundColor White
Write-Host "  Branch: $branch" -ForegroundColor White

# Check recent operations
Write-Host "`n[3/4] Checking recent operations..." -ForegroundColor Yellow
$operations = aws apprunner list-operations --service-arn $serviceArn --region eu-west-2 --max-results 5 --output json | ConvertFrom-Json

if ($operations.OperationSummaryList.Count -gt 0) {
    Write-Host "  Recent operations:" -ForegroundColor White
    foreach ($op in $operations.OperationSummaryList) {
        $color = switch ($op.Status) {
            "SUCCEEDED" { "Green" }
            "IN_PROGRESS" { "Yellow" }
            "FAILED" { "Red" }
            default { "White" }
        }
        $time = $op.StartedAt
        Write-Host "    [$time] $($op.Type): $($op.Status)" -ForegroundColor $color
    }
} else {
    Write-Host "  No recent operations" -ForegroundColor Gray
}

# Test endpoint
Write-Host "`n[4/4] Testing application..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "https://$serviceUrl/health" -TimeoutSec 10 -UseBasicParsing
    Write-Host "  ✓ Health check passed: $($response.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Health check failed: $($_.Exception.Message)" -ForegroundColor Red
}

# Summary
Write-Host "`n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray
Write-Host "`n📋 Summary:" -ForegroundColor Cyan
Write-Host "  Service Status: $status"
Write-Host "  Application URL: https://$serviceUrl" -ForegroundColor White
Write-Host "  Login URL: https://$serviceUrl/login.html" -ForegroundColor White

if ($status -ne "RUNNING") {
    Write-Host "`n⚠️  Service is not running!" -ForegroundColor Yellow
    Write-Host "  To start deployment:" -ForegroundColor White
    Write-Host "  aws apprunner start-deployment --service-arn $serviceArn --region eu-west-2" -ForegroundColor Gray
}

Write-Host "`n🔧 Useful Commands:" -ForegroundColor Cyan
Write-Host "  View logs: aws logs tail /aws/apprunner/VeriCase-api/$lastDeployment/application --follow --region eu-west-2" -ForegroundColor Gray
Write-Host "  Force deploy: aws apprunner start-deployment --service-arn $serviceArn --region eu-west-2" -ForegroundColor Gray
Write-Host "  Pause service: aws apprunner pause-service --service-arn $serviceArn --region eu-west-2" -ForegroundColor Gray

Write-Host "`n✅ Check complete!" -ForegroundColor Green
