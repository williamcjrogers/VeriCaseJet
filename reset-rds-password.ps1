# Reset RDS Password
$DB_INSTANCE = "database-1"
$REGION = "eu-west-2"
$NEW_PASSWORD = "Sunnyday8?!"

Write-Host "=== Resetting RDS Password ===" -ForegroundColor Green
Write-Host ""
Write-Host "Database: $DB_INSTANCE" -ForegroundColor Cyan
Write-Host "Region: $REGION" -ForegroundColor Cyan
Write-Host "New Password: $NEW_PASSWORD" -ForegroundColor Cyan
Write-Host ""

Write-Host "Resetting password..." -ForegroundColor Yellow

aws rds modify-db-instance `
  --db-instance-identifier $DB_INSTANCE `
  --master-user-password $NEW_PASSWORD `
  --region $REGION `
  --apply-immediately

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "✓ Password reset initiated!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Wait 2-3 minutes for the change to apply, then redeploy App Runner:" -ForegroundColor Yellow
    Write-Host "aws apprunner start-deployment --service-arn arn:aws:apprunner:eu-west-2:526015377510:service/VeriCase-api/92edc88957f0476fab92a10457b9fe0f --region eu-west-2" -ForegroundColor White
} else {
    Write-Host ""
    Write-Host "✗ Failed to reset password" -ForegroundColor Red
    Write-Host "Try resetting via AWS Console instead:" -ForegroundColor Yellow
    Write-Host "https://eu-west-2.console.aws.amazon.com/rds/" -ForegroundColor Cyan
}
