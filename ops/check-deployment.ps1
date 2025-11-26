# Quick script to check VeriCase App Runner deployment status
# Run this every minute or so to see progress

$SERVICE_ARN = "arn:aws:apprunner:eu-west-2:526015377510:service/VeriCase-api/92edc88957f0476fab92a10457b9fe0f"
$REGION = "eu-west-2"
$APP_URL = "https://nb3ywvmyf2.eu-west-2.awsapprunner.com"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "VeriCase Deployment Status Check" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# Get service status
Write-Host "Checking service status..." -ForegroundColor Yellow
$status = aws apprunner describe-service --service-arn $SERVICE_ARN --region $REGION --query "Service.Status" --output text

Write-Host "`n📊 Current Status: " -NoNewline
if ($status -eq "RUNNING") {
    Write-Host "$status ✅" -ForegroundColor Green
    Write-Host "`n🎉 DEPLOYMENT COMPLETE!`n" -ForegroundColor Green
    Write-Host "Your application is now running at:" -ForegroundColor Green
    Write-Host "   $APP_URL`n" -ForegroundColor White
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "   1. Open browser: $APP_URL" -ForegroundColor White
    Write-Host "   2. Test login with: admin@veri-case.com / Sunnyday8?!" -ForegroundColor White
    Write-Host "   3. Try creating a project/case" -ForegroundColor White
    Write-Host "`n   To view logs:" -ForegroundColor White
    Write-Host "   aws logs tail /aws/apprunner/VeriCase-api/92edc88957f0476fab92a10457b9fe0f/application --follow --region eu-west-2`n" -ForegroundColor Gray
} 
elseif ($status -eq "OPERATION_IN_PROGRESS") {
    Write-Host "$status 🔄" -ForegroundColor Yellow
    Write-Host "`n⏳ Deployment in progress... Check again in 2-3 minutes.`n" -ForegroundColor Yellow
}
else {
    Write-Host "$status ⚠️" -ForegroundColor Red
    Write-Host "`nCheck AWS Console for details:" -ForegroundColor Red
    Write-Host "https://eu-west-2.console.aws.amazon.com/apprunner/home?region=eu-west-2#/services`n" -ForegroundColor White
}

Write-Host "========================================`n" -ForegroundColor Cyan
