# Security Incident Response - AWS Account Check Script
# This script automates checking for unauthorized AWS activity

Write-Host "========================================" -ForegroundColor Red
Write-Host "AWS SECURITY INCIDENT RESPONSE CHECK" -ForegroundColor Red
Write-Host "========================================" -ForegroundColor Red
Write-Host ""

$regions = @(
    "us-east-1",
    "us-east-2", 
    "us-west-1",
    "us-west-2",
    "eu-west-1",
    "eu-west-2",
    "eu-central-1",
    "ap-southeast-1",
    "ap-southeast-2",
    "ap-northeast-1"
)

# Check 1: List all IAM users
Write-Host "=== CHECK 1: IAM Users ===" -ForegroundColor Yellow
Write-Host "Listing all IAM users..."
try {
    aws iam list-users --query 'Users[*].[UserName,CreateDate]' --output table
} catch {
    Write-Host "Error checking IAM users: $_" -ForegroundColor Red
}
Write-Host ""

# Check 2: Check policies attached to VericaseDocsAdmin
Write-Host "=== CHECK 2: VericaseDocsAdmin Policies ===" -ForegroundColor Yellow
Write-Host "Checking policies attached to VericaseDocsAdmin..."
try {
    Write-Host "Attached managed policies:"
    aws iam list-attached-user-policies --user-name VericaseDocsAdmin --output table
    Write-Host ""
    Write-Host "Inline policies:"
    aws iam list-user-policies --user-name VericaseDocsAdmin --output table
} catch {
    Write-Host "Error checking user policies: $_" -ForegroundColor Red
}
Write-Host ""

# Check 3: Check access keys for VericaseDocsAdmin
Write-Host "=== CHECK 3: Access Keys ===" -ForegroundColor Yellow
Write-Host "Listing access keys for VericaseDocsAdmin..."
try {
    $keys = aws iam list-access-keys --user-name VericaseDocsAdmin --output json | ConvertFrom-Json
    foreach ($key in $keys.AccessKeyMetadata) {
        $keyId = $key.AccessKeyId
        $status = $key.Status
        $created = $key.CreateDate
        
        if ($keyId -eq "AKIAXU6HVWBTKU4CVBUA") {
            Write-Host "⚠️  EXPOSED KEY FOUND: $keyId (Status: $status, Created: $created)" -ForegroundColor Red
        } else {
            Write-Host "✓  Key: $keyId (Status: $status, Created: $created)" -ForegroundColor Green
        }
    }
} catch {
    Write-Host "Error checking access keys: $_" -ForegroundColor Red
}
Write-Host ""

# Check 4: EC2 instances across regions
Write-Host "=== CHECK 4: EC2 Instances Across Regions ===" -ForegroundColor Yellow
$totalInstances = 0
foreach ($region in $regions) {
    Write-Host "Checking region: $region..." -NoNewline
    try {
        $instances = aws ec2 describe-instances --region $region --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,State.Name,LaunchTime]' --output json 2>$null | ConvertFrom-Json
        $count = 0
        if ($instances) {
            foreach ($reservation in $instances) {
                $count += $reservation.Count
            }
        }
        
        if ($count -gt 0) {
            Write-Host " FOUND $count instances!" -ForegroundColor Red
            aws ec2 describe-instances --region $region --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,State.Name,LaunchTime]' --output table
            $totalInstances += $count
        } else {
            Write-Host " No instances" -ForegroundColor Green
        }
    } catch {
        Write-Host " Error" -ForegroundColor Yellow
    }
}
Write-Host "Total EC2 instances found: $totalInstances" -ForegroundColor $(if ($totalInstances -gt 0) { "Red" } else { "Green" })
Write-Host ""

# Check 5: Lambda functions across regions
Write-Host "=== CHECK 5: Lambda Functions Across Regions ===" -ForegroundColor Yellow
$totalFunctions = 0
foreach ($region in $regions) {
    Write-Host "Checking region: $region..." -NoNewline
    try {
        $functions = aws lambda list-functions --region $region --output json 2>$null | ConvertFrom-Json
        $count = $functions.Functions.Count
        
        if ($count -gt 0) {
            Write-Host " FOUND $count functions!" -ForegroundColor Yellow
            foreach ($func in $functions.Functions) {
                Write-Host "  - $($func.FunctionName) (Runtime: $($func.Runtime), Last Modified: $($func.LastModified))"
            }
            $totalFunctions += $count
        } else {
            Write-Host " No functions" -ForegroundColor Green
        }
    } catch {
        Write-Host " Error" -ForegroundColor Yellow
    }
}
Write-Host "Total Lambda functions found: $totalFunctions"
Write-Host ""

# Check 6: S3 buckets
Write-Host "=== CHECK 6: S3 Buckets ===" -ForegroundColor Yellow
Write-Host "Listing all S3 buckets..."
try {
    aws s3 ls
} catch {
    Write-Host "Error listing S3 buckets: $_" -ForegroundColor Red
}
Write-Host ""

# Check 7: Spot instance requests
Write-Host "=== CHECK 7: EC2 Spot Instance Requests ===" -ForegroundColor Yellow
$totalSpotRequests = 0
foreach ($region in $regions) {
    Write-Host "Checking region: $region..." -NoNewline
    try {
        $spots = aws ec2 describe-spot-instance-requests --region $region --output json 2>$null | ConvertFrom-Json
        $count = $spots.SpotInstanceRequests.Count
        
        if ($count -gt 0) {
            Write-Host " FOUND $count spot requests!" -ForegroundColor Red
            $totalSpotRequests += $count
        } else {
            Write-Host " No spot requests" -ForegroundColor Green
        }
    } catch {
        Write-Host " Error" -ForegroundColor Yellow
    }
}
Write-Host "Total spot requests found: $totalSpotRequests" -ForegroundColor $(if ($totalSpotRequests -gt 0) { "Red" } else { "Green" })
Write-Host ""

# Check 8: Recent CloudTrail events for VericaseDocsAdmin
Write-Host "=== CHECK 8: Recent CloudTrail Events ===" -ForegroundColor Yellow
Write-Host "Fetching recent CloudTrail events for VericaseDocsAdmin (last 24 hours)..."
try {
    $startTime = (Get-Date).AddDays(-1).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $events = aws cloudtrail lookup-events --lookup-attributes AttributeKey=Username,AttributeValue=VericaseDocsAdmin --start-time $startTime --max-results 50 --output json | ConvertFrom-Json
    
    Write-Host "Found $($events.Events.Count) events in the last 24 hours"
    
    if ($events.Events.Count -gt 0) {
        Write-Host ""
        Write-Host "Sample of recent events:"
        $events.Events | Select-Object -First 10 | ForEach-Object {
            $event = $_ | ConvertFrom-Json
            Write-Host "  [$($_.EventTime)] $($_.EventName) - $($_.EventSource)"
        }
    }
} catch {
    Write-Host "Error fetching CloudTrail events: $_" -ForegroundColor Red
    Write-Host "You may need to check CloudTrail manually in the AWS Console" -ForegroundColor Yellow
}
Write-Host ""

# Summary
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "SUMMARY" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Total EC2 Instances: $totalInstances" -ForegroundColor $(if ($totalInstances -gt 0) { "Red" } else { "Green" })
Write-Host "Total Lambda Functions: $totalFunctions" -ForegroundColor $(if ($totalFunctions -gt 5) { "Yellow" } else { "Green" })
Write-Host "Total Spot Requests: $totalSpotRequests" -ForegroundColor $(if ($totalSpotRequests -gt 0) { "Red" } else { "Green" })
Write-Host ""

Write-Host "NEXT STEPS:" -ForegroundColor Yellow
Write-Host "1. Review SECURITY_INCIDENT_RESPONSE.md for full remediation steps" -ForegroundColor White
Write-Host "2. Immediately revoke compromised credentials (GitHub PAT, Qdrant key, DB password)" -ForegroundColor White
Write-Host "3. Rotate AWS access keys" -ForegroundColor White
Write-Host "4. Check AWS billing console for unexpected charges" -ForegroundColor White
Write-Host "5. Remove sensitive files from git history" -ForegroundColor White
Write-Host "6. Respond to AWS Support Case #176679531900745" -ForegroundColor White
Write-Host ""
Write-Host "For detailed instructions, see: SECURITY_INCIDENT_RESPONSE.md" -ForegroundColor Cyan
