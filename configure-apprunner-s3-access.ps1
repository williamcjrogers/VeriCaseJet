# Configure S3 access for App Runner service
# PowerShell version

# Variables
$SERVICE_NAME = "VeriCase-api"
$REGION = "eu-west-2"
$S3_BUCKET = "vericase-data"

Write-Host "=== Configuring S3 Access for App Runner ===" -ForegroundColor Green

# Step 1: Get the App Runner service ARN
Write-Host "Finding App Runner service ARN..."
$SERVICE_ARN = aws apprunner list-services --region $REGION --query "ServiceSummaryList[?ServiceName=='$SERVICE_NAME'].ServiceArn" --output text

if ([string]::IsNullOrEmpty($SERVICE_ARN)) {
    Write-Host "Error: Could not find App Runner service $SERVICE_NAME" -ForegroundColor Red
    exit 1
}
Write-Host "Service ARN: $SERVICE_ARN"

# Step 2: Get the IAM role associated with the App Runner service
Write-Host "Finding IAM role for App Runner service..."
$ROLE_ARN = aws apprunner describe-service --service-arn $SERVICE_ARN --region $REGION --query "Service.InstanceConfiguration.InstanceRoleArn" --output text

if ([string]::IsNullOrEmpty($ROLE_ARN) -or $ROLE_ARN -eq "None") {
    Write-Host "Warning: No instance role found. App Runner is using the default service-linked role." -ForegroundColor Yellow
    
    # For App Runner, we need to create an instance role
    Write-Host "Creating instance role for App Runner..."
    
    # First, create the trust policy
    $TRUST_POLICY = @'
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "tasks.apprunner.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }
    ]
}
'@
    
    $ROLE_NAME = "VeriCaseAppRunnerInstanceRole"
    
    # Create the role
    aws iam create-role --role-name $ROLE_NAME --assume-role-policy-document $TRUST_POLICY --description "Instance role for VeriCase App Runner" 2>$null
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Role might already exist, continuing..." -ForegroundColor Yellow
    }
    
    $ACCOUNT_ID = aws sts get-caller-identity --query Account --output text
    $ROLE_ARN = "arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
    
    Write-Host "You'll need to update your App Runner service to use this role: $ROLE_ARN" -ForegroundColor Yellow
} else {
    # Extract role name from ARN
    $ROLE_NAME = ($ROLE_ARN -split '/')[-1]
}

Write-Host "IAM Role Name: $ROLE_NAME"

# Step 3: Create S3 access policy
$POLICY_NAME = "VeriCaseS3AccessPolicy"
$POLICY_DOCUMENT = @"
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:ListBucket",
                "s3:GetBucketLocation",
                "s3:GetBucketVersioning"
            ],
            "Resource": [
                "arn:aws:s3:::$S3_BUCKET",
                "arn:aws:s3:::$S3_BUCKET/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:ListAllMyBuckets",
                "s3:GetBucketLocation"
            ],
            "Resource": "*"
        }
    ]
}
"@

Write-Host "Creating IAM policy for S3 access..."
# Create the policy (this might fail if it already exists)
$POLICY_OUTPUT = aws iam create-policy --policy-name $POLICY_NAME --policy-document $POLICY_DOCUMENT --description "S3 access policy for VeriCase App Runner" 2>&1

if ($LASTEXITCODE -eq 0) {
    $POLICY_ARN = ($POLICY_OUTPUT | ConvertFrom-Json).Policy.Arn
    Write-Host "Created new policy: $POLICY_ARN"
} else {
    Write-Host "Policy might already exist, getting existing policy ARN..."
    $ACCOUNT_ID = aws sts get-caller-identity --query Account --output text
    $POLICY_ARN = "arn:aws:iam::${ACCOUNT_ID}:policy/$POLICY_NAME"
}

Write-Host "Policy ARN: $POLICY_ARN"

# Step 4: Attach the policy to the role
Write-Host "Attaching policy to IAM role..."
aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$POLICY_ARN"

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Successfully attached S3 access policy to role" -ForegroundColor Green
    
    if ($ROLE_ARN -like "*VeriCaseAppRunnerInstanceRole*") {
        Write-Host ""
        Write-Host "⚠️  IMPORTANT: You need to update your App Runner service configuration:" -ForegroundColor Yellow
        Write-Host "   1. Go to App Runner console" -ForegroundColor Yellow
        Write-Host "   2. Select your service (VeriCase-api)" -ForegroundColor Yellow
        Write-Host "   3. Click 'Update service'" -ForegroundColor Yellow
        Write-Host "   4. Go to 'Security' section" -ForegroundColor Yellow
        Write-Host "   5. Set 'Instance role' to: $ROLE_NAME" -ForegroundColor Yellow
        Write-Host "   6. Deploy the changes" -ForegroundColor Yellow
    }
} else {
    Write-Host "❌ Failed to attach policy. Check error messages above." -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Next Steps ===" -ForegroundColor Green
Write-Host "1. If using a new role, update App Runner service configuration"
Write-Host "2. The service will automatically use the new permissions"
Write-Host "3. Check App Runner logs to verify S3 access is working"
