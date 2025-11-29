# Open ports 8000 and 8010 in EC2 security group
$INSTANCE_ID = "i-0ade6dff1811bdbcb"

Write-Host "Finding security group for instance $INSTANCE_ID..." -ForegroundColor Yellow

# Get security group ID
$sgId = aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' --output text

if ($sgId) {
    Write-Host "Security Group: $sgId" -ForegroundColor Green
    
    Write-Host "`nOpening port 8010..." -ForegroundColor Yellow
    aws ec2 authorize-security-group-ingress --group-id $sgId --protocol tcp --port 8010 --cidr 0.0.0.0/0 2>$null
    
    Write-Host "Opening port 8000..." -ForegroundColor Yellow
    aws ec2 authorize-security-group-ingress --group-id $sgId --protocol tcp --port 8000 --cidr 0.0.0.0/0 2>$null
    
    Write-Host "`nPorts opened! Testing connection..." -ForegroundColor Green
    Start-Sleep -Seconds 2
    curl http://18.130.216.34:8010/health
} else {
    Write-Host "ERROR: Could not find security group. Please open ports manually in AWS Console." -ForegroundColor Red
}
