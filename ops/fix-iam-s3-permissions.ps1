# Fix IAM Role S3 Permissions for VeriCase Upload
Write-Host "Adding S3 permissions to VeriCaseAppRunnerInstanceRole..." -ForegroundColor Cyan

$policyDocument = @"
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:DeleteObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::vericase-docs-prod-526015377510",
                "arn:aws:s3:::vericase-docs-prod-526015377510/*"
            ]
        }
    ]
}
"@

Write-Host "Policy to add:" -ForegroundColor Yellow
Write-Host $policyDocument

try {
    # Create/update inline policy
    aws iam put-role-policy `
        --role-name VeriCaseAppRunnerInstanceRole `
        --policy-name S3BucketAccess `
        --policy-document $policyDocument `
        --region eu-west-2
    
    Write-Host "`n✓ SUCCESS - S3 permissions added to IAM Role!" -ForegroundColor Green
    Write-Host "`nThe IAM Role can now:" -ForegroundColor White
    Write-Host "  - Upload files to S3 (s3:PutObject)" -ForegroundColor White
    Write-Host "  - Download files from S3 (s3:GetObject)" -ForegroundColor White
    Write-Host "  - List bucket contents (s3:ListBucket)" -ForegroundColor White
    Write-Host "  - Delete objects (s3:DeleteObject)" -ForegroundColor White
    
    Write-Host "`nNOW TRY UPLOAD AGAIN!" -ForegroundColor Green
    Write-Host "1. Clear browser cache (Ctrl+Shift+Delete)" -ForegroundColor Yellow
    Write-Host "2. Hard refresh (Ctrl+Shift+R)" -ForegroundColor Yellow
    Write-Host "3. Upload a file" -ForegroundColor Yellow
    
} catch {
    Write-Host "`n✗ FAILED - $_" -ForegroundColor Red
    Write-Host "`nTry manually in AWS Console:" -ForegroundColor Yellow
    Write-Host "1. Go to IAM → Roles → VeriCaseAppRunnerInstanceRole" -ForegroundColor White
    Write-Host "2. Add inline policy with S3 permissions above" -ForegroundColor White
}

Write-Host "`nPress Enter to exit..."
Read-Host
