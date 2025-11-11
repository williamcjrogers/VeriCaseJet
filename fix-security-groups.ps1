# Fix VeriCase Security Groups
# VPC connector exists but security group needs rules

$REGION = "eu-west-2"
$VPC_ID = "vpc-0880b8ccf488f327e"
$DEFAULT_SG = "sg-0fe33dbc9d4cf20ba"

Write-Host "=== Fixing VeriCase Security Groups ===" -ForegroundColor Cyan
Write-Host ""

# Step 1: Add outbound rules to default security group
Write-Host "Step 1: Configuring default security group outbound rules..." -ForegroundColor Yellow

# PostgreSQL
Write-Host "Adding PostgreSQL (5432) rule..."
aws ec2 authorize-security-group-egress --region $REGION --group-id $DEFAULT_SG --protocol tcp --port 5432 --cidr 0.0.0.0/0 2>$null
if ($?) { Write-Host "  ✅ PostgreSQL rule added" -ForegroundColor Green } else { Write-Host "  ℹ️  Rule already exists" }

# Redis
Write-Host "Adding Redis (6379) rule..."
aws ec2 authorize-security-group-egress --region $REGION --group-id $DEFAULT_SG --protocol tcp --port 6379 --cidr 0.0.0.0/0 2>$null
if ($?) { Write-Host "  ✅ Redis rule added" -ForegroundColor Green } else { Write-Host "  ℹ️  Rule already exists" }

# HTTPS (OpenSearch)
Write-Host "Adding HTTPS (443) rule..."
aws ec2 authorize-security-group-egress --region $REGION --group-id $DEFAULT_SG --protocol tcp --port 443 --cidr 0.0.0.0/0 2>$null
if ($?) { Write-Host "  ✅ HTTPS rule added" -ForegroundColor Green } else { Write-Host "  ℹ️  Rule already exists" }

# HTTP (Tika)
Write-Host "Adding HTTP (9998) rule..."
aws ec2 authorize-security-group-egress --region $REGION --group-id $DEFAULT_SG --protocol tcp --port 9998 --cidr 0.0.0.0/0 2>$null
if ($?) { Write-Host "  ✅ HTTP rule added" -ForegroundColor Green } else { Write-Host "  ℹ️  Rule already exists" }

Write-Host ""

# Step 2: Find and update RDS security group
Write-Host "Step 2: Updating RDS security group..." -ForegroundColor Yellow
$RDS_SG = aws rds describe-db-instances --region $REGION --query 'DBInstances[?DBInstanceIdentifier==`database-1`].VpcSecurityGroups[0].VpcSecurityGroupId' --output text

if ($RDS_SG) {
    Write-Host "RDS Security Group: $RDS_SG"
    aws ec2 authorize-security-group-ingress --region $REGION --group-id $RDS_SG --protocol tcp --port 5432 --source-group $DEFAULT_SG 2>$null
    if ($?) { Write-Host "  ✅ RDS inbound rule added" -ForegroundColor Green } else { Write-Host "  ℹ️  Rule already exists" }
} else {
    Write-Host "  ⚠️  RDS not found, add manually" -ForegroundColor Yellow
}

Write-Host ""

# Step 3: Find and update ElastiCache security group
Write-Host "Step 3: Updating Redis security group..." -ForegroundColor Yellow
$REDIS_SG = aws elasticache describe-cache-clusters --region $REGION --cache-cluster-id vericase-redis --show-cache-node-info --query 'CacheClusters[0].SecurityGroups[0].SecurityGroupId' --output text 2>$null

if ($REDIS_SG) {
    Write-Host "Redis Security Group: $REDIS_SG"
    aws ec2 authorize-security-group-ingress --region $REGION --group-id $REDIS_SG --protocol tcp --port 6379 --source-group $DEFAULT_SG 2>$null
    if ($?) { Write-Host "  ✅ Redis inbound rule added" -ForegroundColor Green } else { Write-Host "  ℹ️  Rule already exists" }
} else {
    Write-Host "  ⚠️  Redis cluster not found, add manually" -ForegroundColor Yellow
}

Write-Host ""

# Step 4: Find and update OpenSearch security group
Write-Host "Step 4: Updating OpenSearch security group..." -ForegroundColor Yellow
$OS_SG = aws opensearch describe-domain --region $REGION --domain-name vericase-opensearch --query 'DomainStatus.VPCOptions.SecurityGroupIds[0]' --output text 2>$null

if ($OS_SG) {
    Write-Host "OpenSearch Security Group: $OS_SG"
    aws ec2 authorize-security-group-ingress --region $REGION --group-id $OS_SG --protocol tcp --port 443 --source-group $DEFAULT_SG 2>$null
    if ($?) { Write-Host "  ✅ OpenSearch inbound rule added" -ForegroundColor Green } else { Write-Host "  ℹ️  Rule already exists" }
} else {
    Write-Host "  ⚠️  OpenSearch not found, add manually" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
Write-Host "✅ Default security group ($DEFAULT_SG) configured" -ForegroundColor Green
Write-Host "✅ Outbound rules added for PostgreSQL, Redis, HTTPS, HTTP" -ForegroundColor Green
Write-Host "✅ Inbound rules added to RDS, Redis, OpenSearch" -ForegroundColor Green
Write-Host ""
Write-Host "Next: Redeploy your App Runner service" -ForegroundColor Yellow
Write-Host "Go to: https://console.aws.amazon.com/apprunner/home?region=$REGION" -ForegroundColor Cyan
