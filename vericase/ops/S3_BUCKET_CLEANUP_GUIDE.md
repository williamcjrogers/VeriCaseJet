# VeriCase S3 Bucket Strategy & Cleanup Guide

## ⚠️ AWS Credentials Required

Before running any cleanup commands, configure your AWS credentials:

```powershell
# Option 1: Set environment variables
$Env:AWS_ACCESS_KEY_ID="your-access-key"
$Env:AWS_SECRET_ACCESS_KEY="your-secret-key"  
$Env:AWS_DEFAULT_REGION="eu-west-2"

# Option 2: Use AWS CLI configure
aws configure

# Option 3: Use AWS SSO
aws sso login --profile your-profile
```

Verify credentials work:
```powershell
aws sts get-caller-identity
aws s3 ls
```

## Current Bucket Inventory

You have **8 S3 buckets** with unclear purposes. Here's what they're supposed to be for:

### Bucket Purpose Breakdown

| Bucket Name | Region | Purpose | Status |
|------------|--------|---------|---------|
| `vericase-docs` | eu-west-2 | **Main documents bucket** (production) | ✅ Should keep |
| `vericase-docs-526015377510` | us-east-1 | Test/dev bucket (account ID suffix) | ⚠️ Redundant |
| `vericase-docs-prod-526015377510` | eu-west-2 | Production documents (CDK created) | ⚠️ Duplicate |
| `vericase-docs-production-526015377510` | us-east-1 | Production documents (CDK created) | ⚠️ Duplicate |
| `vericase-documents-526015377510` | us-east-1 | Alternative naming attempt | ⚠️ Redundant |
| `vericase-kb-526015377510` | us-east-1 | Knowledge Base backing store | ⚠️ Duplicate |
| `vericase-kb-production-526015377510` | us-east-1 | Production KB backing store | ⚠️ Duplicate |
| `vericase-knowledge-base-526015377510` | us-east-1 | Alternative KB naming | ⚠️ Duplicate |

## Why So Many Buckets?

Based on your codebase analysis, here's what happened:

### 1. **Multiple Deployment Attempts**
- Different naming conventions tried over time
- Some with account ID suffix (CDK/CloudFormation pattern)
- Some without account ID suffix (manual creation)

### 2. **Multiple Environments Confusion**
- Production, staging, and development buckets
- Created in different regions (eu-west-2 vs us-east-1)
- No clear naming strategy enforced

### 3. **Bedrock Knowledge Base Buckets**
- AWS Bedrock Knowledge Base requires its own S3 bucket
- You have 3 different KB buckets (should only need 1)

## How VeriCase Decides Which Bucket to Use

From your configuration (`vericase/api/app/config.py`):

```python
# Main configuration
S3_BUCKET = "vericase-docs"  # Default main bucket
S3_PST_BUCKET = None  # Optional: dedicated PST bucket
S3_ATTACHMENTS_BUCKET = None  # Optional: dedicated attachments bucket
BEDROCK_KB_ID = "ACKHIYIHPK"  # Your Knowledge Base ID
```

### Bucket Selection Logic:

1. **PST Files**: `S3_PST_BUCKET` → falls back to → `S3_BUCKET`
2. **Email Attachments**: `S3_ATTACHMENTS_BUCKET` → falls back to → `S3_BUCKET`
3. **Other Documents**: Always uses `S3_BUCKET`
4. **Knowledge Base**: Uses bucket associated with `BEDROCK_KB_ID`

### Current Configuration Analysis:

Your active configs point to different buckets:
- `.env` (local): `vericase-docs` (correct for local MinIO)
- `.env.aws`: `vericase-docs-526015377510` 
- `.env.aws-deployed`: `vericase-docs-526015377510`
- `.env.production`: Uses `S3_BUCKET_NAME=vericase-data` ⚠️ (doesn't exist!)

## Recommended Bucket Strategy

### Option A: Single Region (Simplest)

**Keep only these 2 buckets:**

1. **`vericase-docs-prod-526015377510`** (eu-west-2)
   - Main production documents, PST files, attachments
   - Closest to your RDS database (database-1 in eu-west-2)
   - Lower latency and data transfer costs

2. **`vericase-kb-production-526015377510`** (us-east-1)
   - Bedrock Knowledge Base backing store
   - Must be in us-east-1 (Bedrock requirement)

### Option B: Multi-Environment (Recommended)

**Keep these 4 buckets:**

1. **`vericase-docs-prod-526015377510`** (eu-west-2) - Production documents
2. **`vericase-docs-526015377510`** (us-east-1) - Dev/staging documents  
3. **`vericase-kb-production-526015377510`** (us-east-1) - Production KB
4. **`vericase-kb-526015377510`** (us-east-1) - Dev/staging KB

## Cleanup Actions

### Step 1: Verify All Buckets Are Empty

```bash
# Check each bucket
aws s3 ls s3://vericase-docs/ --recursive --summarize --region eu-west-2
aws s3 ls s3://vericase-docs-526015377510/ --recursive --summarize --region us-east-1
aws s3 ls s3://vericase-docs-prod-526015377510/ --recursive --summarize --region eu-west-2
aws s3 ls s3://vericase-docs-production-526015377510/ --recursive --summarize --region us-east-1
aws s3 ls s3://vericase-documents-526015377510/ --recursive --summarize --region us-east-1
aws s3 ls s3://vericase-kb-526015377510/ --recursive --summarize --region us-east-1
aws s3 ls s3://vericase-kb-production-526015377510/ --recursive --summarize --region us-east-1
aws s3 ls s3://vericase-knowledge-base-526015377510/ --recursive --summarize --region us-east-1
```

### Step 2: Delete Redundant Buckets (Following Option A)

```bash
# Delete redundant document buckets
aws s3 rb s3://vericase-docs --force --region eu-west-2
aws s3 rb s3://vericase-docs-526015377510 --force --region us-east-1
aws s3 rb s3://vericase-docs-production-526015377510 --force --region us-east-1
aws s3 rb s3://vericase-documents-526015377510 --force --region us-east-1

# Delete redundant KB buckets
aws s3 rb s3://vericase-kb-526015377510 --force --region us-east-1
aws s3 rb s3://vericase-knowledge-base-526015377510 --force --region us-east-1
```

### Step 3: Update Environment Configuration

**Production config (`.env.aws` or `.env.production`):**

```bash
# S3 Configuration
USE_AWS_SERVICES=true
S3_BUCKET=vericase-docs-prod-526015377510
S3_REGION=eu-west-2
AWS_REGION=eu-west-2

# Optional: Separate buckets for different file types
# S3_PST_BUCKET=vericase-pst-prod-526015377510
# S3_ATTACHMENTS_BUCKET=vericase-attachments-prod-526015377510

# Bedrock Knowledge Base
BEDROCK_KB_ID=ACKHIYIHPK
USE_KNOWLEDGE_BASE=true
```

**Development config (`.env.aws-deployed`):**

```bash
USE_AWS_SERVICES=true
S3_BUCKET=vericase-docs-526015377510
S3_REGION=us-east-1
AWS_REGION=us-east-1

BEDROCK_KB_ID=<your-dev-kb-id>
USE_KNOWLEDGE_BASE=true
```

### Step 4: Verify Bedrock Knowledge Base Configuration

Check which bucket your Bedrock KB is actually using:

```bash
# Get KB details
aws bedrock-agent get-knowledge-base --knowledge-base-id ACKHIYIHPK --region us-east-1

# Get data source details  
aws bedrock-agent get-data-source \
  --knowledge-base-id ACKHIYIHPK \
  --data-source-id <your-data-source-id> \
  --region us-east-1
```

This will show you which S3 bucket the KB is configured to use. Update your config to match.

## Cost Optimization

### Empty Buckets Still Cost Money?

**No** - Empty S3 buckets have no storage costs, but:
- ✅ Each bucket costs $0 for storage if empty
- ⚠️ API requests to empty buckets still cost money
- ⚠️ Having 8 buckets makes management confusing
- ⚠️ Risk of accidentally uploading to wrong bucket

### Recommended Actions:

1. **Delete empty buckets immediately** - No cost, reduces confusion
2. **Enable S3 Lifecycle policies** on kept buckets:
   ```bash
   # Move old PST files to Glacier after 90 days
   # Delete incomplete multipart uploads after 7 days
   ```
3. **Enable S3 Intelligent-Tiering** - Automatic cost optimization

## Implementation Script

Here's a PowerShell script to clean up (following Option A):

```powershell
# cleanup-s3-buckets.ps1

$bucketsToDelete = @(
    @{Name="vericase-docs"; Region="eu-west-2"},
    @{Name="vericase-docs-526015377510"; Region="us-east-1"},
    @{Name="vericase-docs-production-526015377510"; Region="us-east-1"},
    @{Name="vericase-documents-526015377510"; Region="us-east-1"},
    @{Name="vericase-kb-526015377510"; Region="us-east-1"},
    @{Name="vericase-knowledge-base-526015377510"; Region="us-east-1"}
)

Write-Host "=== VeriCase S3 Bucket Cleanup ===" -ForegroundColor Cyan
Write-Host ""

foreach ($bucket in $bucketsToDelete) {
    Write-Host "Checking: $($bucket.Name) in $($bucket.Region)..." -ForegroundColor Yellow
    
    # Check if empty
    $objects = aws s3 ls "s3://$($bucket.Name)/" --recursive --region $($bucket.Region) 2>&1
    
    if ($objects -match "Total Objects: 0" -or !$objects) {
        Write-Host "  ✓ Bucket is empty" -ForegroundColor Green
        
        # Ask for confirmation
        $confirm = Read-Host "  Delete $($bucket.Name)? (y/n)"
        if ($confirm -eq 'y') {
            aws s3 rb "s3://$($bucket.Name)" --region $($bucket.Region)
            Write-Host "  ✓ Deleted" -ForegroundColor Green
        } else {
            Write-Host "  ⊗ Skipped" -ForegroundColor Gray
        }
    } else {
        Write-Host "  ⚠ Bucket contains files - manual review required" -ForegroundColor Red
    }
    Write-Host ""
}

Write-Host "=== Cleanup Complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Remaining buckets:" -ForegroundColor Yellow
aws s3 ls
```

## Best Practices Going Forward

1. **Use consistent naming convention**:
   - Format: `vericase-{purpose}-{environment}-{account-id}`
   - Example: `vericase-docs-prod-526015377510`

2. **Tag all buckets**:
   ```bash
   aws s3api put-bucket-tagging \
     --bucket vericase-docs-prod-526015377510 \
     --tagging 'TagSet=[{Key=Environment,Value=production},{Key=Purpose,Value=documents},{Key=Application,Value=vericase}]'
   ```

3. **Document bucket purposes** in your README or infrastructure-as-code

4. **Use separate buckets only when needed**:
   - ✅ Separate prod/dev/staging environments
   - ✅ Separate regions for data residency
   - ✅ Separate bucket for Bedrock KB (AWS requirement)
   - ❌ Don't create separate buckets for file types unless you have specific compliance needs

5. **Enable versioning and lifecycle policies**:
   ```bash
   # Enable versioning
   aws s3api put-bucket-versioning \
     --bucket vericase-docs-prod-526015377510 \
     --versioning-configuration Status=Enabled
   
   # Add lifecycle policy (example: delete after 1 year)
   aws s3api put-bucket-lifecycle-configuration \
     --bucket vericase-docs-prod-526015377510 \
     --lifecycle-configuration file://lifecycle-policy.json
   ```

## Quick Decision Matrix

| If you need... | Then keep... |
|---------------|--------------|
| Simple single production system | `vericase-docs-prod-526015377510` + KB bucket |
| Separate dev/prod environments | Production buckets + dev buckets |
| Regional data residency | One bucket per required region |
| Cost optimization | Minimum buckets that meet requirements |

## Summary

**Recommendation**: Delete 6 buckets, keep only:
1. `vericase-docs-prod-526015377510` (eu-west-2) - Main production storage
2. `vericase-kb-production-526015377510` (us-east-1) - Bedrock KB storage

Then update all your `.env` files to point to these consistently.
