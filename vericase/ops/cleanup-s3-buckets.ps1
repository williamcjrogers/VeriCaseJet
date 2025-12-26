#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Clean up redundant VeriCase S3 buckets

.DESCRIPTION
    This script identifies and removes empty, redundant S3 buckets from your VeriCase deployment.
    It safely checks each bucket before deletion and requires confirmation.

.PARAMETER DryRun
    Preview what would be deleted without actually deleting

.PARAMETER Force
    Skip confirmation prompts (use with caution!)

.EXAMPLE
    # Preview what would be deleted
    .\cleanup-s3-buckets.ps1 -DryRun

.EXAMPLE
    # Actually delete with confirmations
    .\cleanup-s3-buckets.ps1

.EXAMPLE
    # Delete without confirmations (dangerous!)
    .\cleanup-s3-buckets.ps1 -Force
#>

param(
    [switch]$DryRun,
    [switch]$Force
)

# Buckets to potentially delete (following Option A strategy)
$bucketsToCheck = @(
    @{Name="vericase-docs"; Region="eu-west-2"; Reason="Replaced by vericase-docs-prod-*"},
    @{Name="vericase-docs-526015377510"; Region="us-east-1"; Reason="Dev/test bucket - consolidate if not used"},
    @{Name="vericase-docs-production-526015377510"; Region="us-east-1"; Reason="Duplicate of eu-west-2 prod bucket"},
    @{Name="vericase-documents-526015377510"; Region="us-east-1"; Reason="Alternative naming - not used"},
    @{Name="vericase-kb-526015377510"; Region="us-east-1"; Reason="Dev KB bucket - keep only if needed"},
    @{Name="vericase-knowledge-base-526015377510"; Region="us-east-1"; Reason="Alternative naming - not used"}
)

# Buckets to keep
$bucketsToKeep = @(
    "vericase-docs-prod-526015377510",
    "vericase-kb-production-526015377510"
)

function Write-Info { param([string]$Message) Write-Host $Message -ForegroundColor Cyan }
function Write-Success { param([string]$Message) Write-Host $Message -ForegroundColor Green }
function Write-Warning { param([string]$Message) Write-Host $Message -ForegroundColor Yellow }
function Write-Error { param([string]$Message) Write-Host $Message -ForegroundColor Red }

Write-Info "=== VeriCase S3 Bucket Cleanup ==="
Write-Info ""

if ($DryRun) {
    Write-Warning "DRY-RUN MODE - No buckets will be deleted"
    Write-Info ""
}

# Summary
$toDelete = @()
$toKeep = @()
$nonEmpty = @()
$notFound = @()

Write-Info "Step 1: Analyzing buckets..."
Write-Info ""

foreach ($bucket in $bucketsToCheck) {
    $bucketName = $bucket.Name
    $region = $bucket.Region
    $reason = $bucket.Reason
    
    Write-Host "  Checking: " -NoNewline
    Write-Host $bucketName -ForegroundColor Yellow -NoNewline
    Write-Host " ($region)"
    Write-Host "    Reason: $reason" -ForegroundColor Gray
    
    # Check if bucket exists
    try {
        $bucketExists = aws s3api head-bucket --bucket $bucketName --region $region 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "    Status: " -NoNewline
            Write-Host "Not found or no access" -ForegroundColor Gray
            $notFound += $bucketName
            Write-Host ""
            continue
        }
    } catch {
        Write-Host "    Status: " -NoNewline
        Write-Host "Error checking bucket" -ForegroundColor Red
        $notFound += $bucketName
        Write-Host ""
        continue
    }
    
    # Count objects
    try {
        $output = aws s3 ls "s3://$bucketName/" --recursive --summarize --region $region 2>&1 | Out-String
        
        if ($output -match "Total Objects:\s+(\d+)") {
            $objectCount = [int]$matches[1]
            
            if ($objectCount -eq 0) {
                Write-Host "    Status: " -NoNewline
                Write-Success "Empty - can be deleted"
                $toDelete += @{Bucket=$bucketName; Region=$region; Reason=$reason}
            } else {
                Write-Host "    Status: " -NoNewline
                Write-Error "Contains $objectCount objects - manual review required"
                $nonEmpty += @{Bucket=$bucketName; Region=$region; Count=$objectCount}
            }
        } else {
            Write-Host "    Status: " -NoNewline
            Write-Success "Empty - can be deleted"
            $toDelete += @{Bucket=$bucketName; Region=$region; Reason=$reason}
        }
    } catch {
        Write-Host "    Status: " -NoNewline
        Write-Error "Error listing objects"
    }
    
    Write-Host ""
}

# Check buckets to keep
Write-Info "Step 2: Verifying buckets to keep..."
Write-Info ""

foreach ($bucketName in $bucketsToKeep) {
    $region = if ($bucketName -like "*eu-west-2*" -or $bucketName -like "*prod*") { "eu-west-2" } else { "us-east-1" }
    
    Write-Host "  Checking: " -NoNewline
    Write-Host $bucketName -ForegroundColor Green -NoNewline
    Write-Host " ($region)"
    
    try {
        $bucketExists = aws s3api head-bucket --bucket $bucketName --region $region 2>&1
        if ($LASTEXITCODE -eq 0) {
            $output = aws s3 ls "s3://$bucketName/" --recursive --summarize --region $region 2>&1 | Out-String
            if ($output -match "Total Objects:\s+(\d+)") {
                $objectCount = [int]$matches[1]
                Write-Host "    Status: " -NoNewline
                Write-Success "Exists - $objectCount objects"
                $toKeep += @{Bucket=$bucketName; Region=$region; Count=$objectCount}
            } else {
                Write-Host "    Status: " -NoNewline
                Write-Success "Exists - empty"
                $toKeep += @{Bucket=$bucketName; Region=$region; Count=0}
            }
        } else {
            Write-Host "    Status: " -NoNewline
            Write-Warning "Not found - you may need to create it"
        }
    } catch {
        Write-Host "    Status: " -NoNewline
        Write-Warning "Error checking"
    }
    
    Write-Host ""
}

# Summary
Write-Info "=== Summary ==="
Write-Info ""

Write-Info "Buckets to DELETE ($($toDelete.Count)):"
if ($toDelete.Count -eq 0) {
    Write-Host "  None" -ForegroundColor Gray
} else {
    foreach ($bucket in $toDelete) {
        Write-Host "  • " -NoNewline
        Write-Host $bucket.Bucket -ForegroundColor Red -NoNewline
        Write-Host " ($($bucket.Region))" -ForegroundColor Gray
        Write-Host "    → $($bucket.Reason)" -ForegroundColor Gray
    }
}
Write-Host ""

Write-Info "Buckets to KEEP ($($toKeep.Count)):"
if ($toKeep.Count -eq 0) {
    Write-Warning "  None found - you may need to create production buckets!"
} else {
    foreach ($bucket in $toKeep) {
        Write-Host "  ✓ " -NoNewline
        Write-Success "$($bucket.Bucket) ($($bucket.Region)) - $($bucket.Count) objects"
    }
}
Write-Host ""

if ($nonEmpty.Count -gt 0) {
    Write-Warning "Buckets with DATA (manual review required):"
    foreach ($bucket in $nonEmpty) {
        Write-Host "  ⚠ " -NoNewline
        Write-Warning "$($bucket.Bucket) ($($bucket.Region)) - $($bucket.Count) objects"
    }
    Write-Host ""
}

if ($notFound.Count -gt 0) {
    Write-Host "Buckets NOT FOUND or no access:" -ForegroundColor Gray
    foreach ($bucketName in $notFound) {
        Write-Host "  • $bucketName" -ForegroundColor Gray
    }
    Write-Host ""
}

# Delete buckets
if ($toDelete.Count -eq 0) {
    Write-Success "No empty redundant buckets to delete!"
    exit 0
}

if ($DryRun) {
    Write-Warning "DRY-RUN: Would delete $($toDelete.Count) buckets"
    Write-Info "Run without -DryRun to actually delete"
    exit 0
}

Write-Info "=== Deletion ==="
Write-Info ""

if (-not $Force) {
    Write-Warning "About to delete $($toDelete.Count) empty buckets"
    $confirm = Read-Host "Continue? (yes/no)"
    if ($confirm -ne "yes") {
        Write-Info "Cancelled"
        exit 0
    }
    Write-Host ""
}

$deleted = 0
$failed = 0

foreach ($bucket in $toDelete) {
    $bucketName = $bucket.Bucket
    $region = $bucket.Region
    
    Write-Host "Deleting: " -NoNewline
    Write-Host $bucketName -ForegroundColor Yellow -NoNewline
    Write-Host " ... " -NoNewline
    
    try {
        $result = aws s3 rb "s3://$bucketName" --region $region 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Success "✓ Deleted"
            $deleted++
        } else {
            Write-Error "✗ Failed"
            Write-Host "    Error: $result" -ForegroundColor Red
            $failed++
        }
    } catch {
        Write-Error "✗ Failed"
        Write-Host "    Error: $_" -ForegroundColor Red
        $failed++
    }
}

Write-Host ""
Write-Info "=== Complete ==="
Write-Success "Deleted: $deleted buckets"
if ($failed -gt 0) {
    Write-Error "Failed: $failed buckets"
}

Write-Host ""
Write-Info "Next steps:"
Write-Host "1. Update your .env files to use the remaining buckets" -ForegroundColor Cyan
Write-Host "2. See: vericase/ops/S3_BUCKET_CLEANUP_GUIDE.md" -ForegroundColor Cyan
