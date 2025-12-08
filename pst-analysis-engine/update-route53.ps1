# Update Route 53 A record with new EC2 IP
$NEW_IP = "18.175.232.87"
$HOSTED_ZONE_ID = "YOUR_HOSTED_ZONE_ID"  # Replace with your hosted zone ID
$DOMAIN_NAME = "your-domain.com"  # Replace with your domain (e.g., vericase.example.com)

Write-Host "Updating Route 53 DNS record..." -ForegroundColor Yellow
Write-Host "Domain: $DOMAIN_NAME" -ForegroundColor Cyan
Write-Host "New IP: $NEW_IP" -ForegroundColor Cyan

# Create change batch JSON
$changeBatch = @"
{
  "Changes": [{
    "Action": "UPSERT",
    "ResourceRecordSet": {
      "Name": "$DOMAIN_NAME",
      "Type": "A",
      "TTL": 300,
      "ResourceRecords": [{"Value": "$NEW_IP"}]
    }
  }]
}
"@

# Save to temp file
$changeBatch | Out-File -FilePath "route53-change.json" -Encoding utf8

# Apply the change
aws route53 change-resource-record-sets --hosted-zone-id $HOSTED_ZONE_ID --change-batch file://route53-change.json

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nDNS record updated successfully!" -ForegroundColor Green
    Write-Host "Note: DNS propagation may take a few minutes" -ForegroundColor Yellow
} else {
    Write-Host "`nFailed to update DNS record" -ForegroundColor Red
    Write-Host "Please update manually in AWS Console" -ForegroundColor Yellow
}

# Cleanup
Remove-Item "route53-change.json" -ErrorAction SilentlyContinue
