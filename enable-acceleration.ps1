# AWS PowerShell Module
Import-Module AWSPowerShell.NetCore -ErrorAction SilentlyContinue

$buckets = @(
    "vericase-docs-526015377510",
    "vericase-kb-526015377510",
    "vericase-documents-526015377510",
    "vericase-knowledge-base-526015377510"
)

foreach ($bucket in $buckets) {
    Write-Host "Enabling Transfer Acceleration on $bucket..."
    try {
        Write-S3BucketAccelerateConfiguration -BucketName $bucket -AccelerateConfiguration_Status Enabled -Region us-east-1
        Write-Host "[OK] Enabled on $bucket" -ForegroundColor Green
    } catch {
        Write-Host "[FAIL] Failed on $bucket" -ForegroundColor Red
        Write-Host $_.Exception.Message
    }
}
