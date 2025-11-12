# Update App Runner service to use the instance role
$SERVICE_NAME = "VeriCase-api"
$REGION = "eu-west-2"
$ROLE_NAME = "VeriCaseAppRunnerInstanceRole"

Write-Host "=== Updating App Runner Instance Role ===" -ForegroundColor Green

# Get service ARN
$SERVICE_ARN = aws apprunner list-services --region $REGION --query "ServiceSummaryList[?ServiceName=='$SERVICE_NAME'].ServiceArn" --output text

if ([string]::IsNullOrEmpty($SERVICE_ARN)) {
    Write-Host "Error: Could not find App Runner service $SERVICE_NAME" -ForegroundColor Red
    exit 1
}

Write-Host "Service ARN: $SERVICE_ARN"

# Get role ARN
$ACCOUNT_ID = aws sts get-caller-identity --query Account --output text
$ROLE_ARN = "arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

Write-Host "Role ARN: $ROLE_ARN"

# Update the service
Write-Host "`nUpdating App Runner service configuration..."
Write-Host "This will require manual steps in the AWS Console:" -ForegroundColor Yellow
Write-Host ""
Write-Host "1. Go to: https://eu-west-2.console.aws.amazon.com/apprunner/" -ForegroundColor Cyan
Write-Host "2. Click on 'VeriCase-api'" -ForegroundColor Cyan
Write-Host "3. Click 'Update service'" -ForegroundColor Cyan
Write-Host "4. Go to 'Security' section" -ForegroundColor Cyan
Write-Host "5. Change 'Instance role' to: VeriCaseAppRunnerInstanceRole" -ForegroundColor Cyan
Write-Host "6. Click 'Save and deploy'" -ForegroundColor Cyan
Write-Host ""
Write-Host "This will fix S3 access and apply all the latest code changes!" -ForegroundColor Green

# Alternative: Trigger deployment via CLI
Write-Host "`nAlternatively, after updating the role in console, you can trigger deployment:" -ForegroundColor Yellow
Write-Host "aws apprunner start-deployment --service-arn $SERVICE_ARN --region $REGION" -ForegroundColor White
