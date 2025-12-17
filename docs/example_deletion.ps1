# Welbourne Refine - Example Deletion Script
# PowerShell script demonstrating safe bulk deletion workflow

<#
.SYNOPSIS
    Example script for safely deleting spam emails from Welbourne database
    
.DESCRIPTION
    Demonstrates the complete workflow:
    1. Search for spam patterns
    2. Review and confirm matches
    3. Create backup (optional)
    4. Execute deletion
    5. Report results
    
.EXAMPLE
    .\example_deletion.ps1 -Category "marketing" -BackupEnabled $true
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$WelbourneEmailPath = "C:\path\to\welbourne\emails",
    
    [Parameter(Mandatory=$false)]
    [ValidateSet("marketing", "linkedin", "date_only", "vendor", "other_projects", "all")]
    [string]$Category = "marketing",
    
    [Parameter(Mandatory=$false)]
    [bool]$BackupEnabled = $true,
    
    [Parameter(Mandatory=$false)]
    [bool]$DryRun = $true
)

# Configuration
$BackupBasePath = "C:\path\to\welbourne_backups"
$LogPath = "C:\path\to\welbourne_cleanup_log.txt"

# Spam patterns by category
$Patterns = @{
    marketing = @("*webinar*", "*exhibition*", "*conference*", "*discount*", "*early bird*")
    linkedin = @("*profile view*", "*new connection*", "*person is noticing*")
    date_only = @("20??-??-??*??:??:??*")
    vendor = @("*toolstation*", "*screwfix*", "*trade discount*")
    other_projects = @(
        "*Abbey Road*", "*Peabody*", "*Merrick Place*", "*Southall*",
        "*Oxlow Lane*", "*Dagenham*", "*Roxwell Road*", "*Kings Crescent*",
        "*Peckham Library*", "*Flaxyard*", "*Loxford*", "*Seven Kings*",
        "*Frank Towell Court*", "*Lisson Arches*", "*Beaulieu Park*",
        "*Chelmsford*", "*Islay Wharf*", "*Victory Place*", "*Earlham Grove*",
        "*Canons Park*", "*Rayners Lane*", "*Clapham Park*", "*Osier Way*",
        "*Pocket Living*", "*Moreland Gardens*", "*Buckland*",
        "*South Thames College*", "*Robert Whyte House*", "*Bromley*",
        "*Camley Street*", "*Honeywell*"
    )
}

# Protected keywords - NEVER delete emails containing these
$ProtectedKeywords = @(
    "vobster", "s278", "s106", "remedial", "defects", "variation",
    "ljj", "grangewood", "keylon", "weldrite", "taylor maxwell",
    "tps", "calfordseaden", "czwg", "pte", "argent",
    "claim", "payment", "valuation", "loss and expense",
    "delay", "completion", "critical path", "handover"
)

# Protected senders - NEVER delete from these addresses
$ProtectedSenders = @(
    "noreply@aconex.com",
    "@ljjcontractors.co.uk",
    "@calfordseaden.com",
    "@czwgarchitects.co.uk",
    "@tps.eu.com",
    "@tpsmanagement.uk"
)

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "$timestamp - $Message"
    Write-Host $logMessage
    Add-Content -Path $LogPath -Value $logMessage
}

function Test-IsProtected {
    param([string]$FilePath)
    
    # Quick check: read first 1KB for keyword scan
    try {
        $content = Get-Content $FilePath -TotalCount 50 -ErrorAction Stop | Out-String
        
        # Check for protected keywords
        foreach ($keyword in $ProtectedKeywords) {
            if ($content -match $keyword) {
                Write-Log "⚠️ PROTECTED: $FilePath contains keyword '$keyword'"
                return $true
            }
        }
        
        # Check for protected senders
        foreach ($sender in $ProtectedSenders) {
            if ($content -match [regex]::Escape($sender)) {
                Write-Log "⚠️ PROTECTED: $FilePath from protected sender '$sender'"
                return $true
            }
        }
        
        return $false
    }
    catch {
        Write-Log "⚠️ WARNING: Could not read $FilePath for protection check"
        return $true  # Err on side of caution
    }
}

function Get-SpamEmails {
    param([string]$Category)
    
    Write-Log "Searching for $Category emails in $WelbourneEmailPath"
    
    $allMatches = @()
    $patterns = $Patterns[$Category]
    
    foreach ($pattern in $patterns) {
        $matches = Get-ChildItem -Path $WelbourneEmailPath -Recurse -Filter "*.msg" -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like $pattern }
        
        $allMatches += $matches
    }
    
    # Remove duplicates
    $uniqueMatches = $allMatches | Sort-Object FullName -Unique
    
    Write-Log "Found $($uniqueMatches.Count) potential $Category emails"
    return $uniqueMatches
}

function Show-Samples {
    param([array]$Files, [int]$Count = 10)
    
    Write-Host "`n=== SAMPLE EMAILS TO DELETE ===" -ForegroundColor Yellow
    $samples = $Files | Select-Object -First $Count
    
    foreach ($file in $samples) {
        Write-Host "  📧 $($file.Name)" -ForegroundColor Cyan
        Write-Host "     Path: $($file.DirectoryName)"
        Write-Host "     Size: $([math]::Round($file.Length/1KB, 2)) KB"
        Write-Host "     Date: $($file.LastWriteTime)"
        Write-Host ""
    }
    
    if ($Files.Count -gt $Count) {
        Write-Host "  ... and $($Files.Count - $Count) more emails" -ForegroundColor Gray
    }
}

function Backup-Files {
    param([array]$Files)
    
    $backupDir = Join-Path $BackupBasePath (Get-Date -Format "yyyyMMdd_HHmmss_$Category")
    New-Item -Path $backupDir -ItemType Directory -Force | Out-Null
    
    Write-Log "Creating backup in $backupDir"
    
    $backedUp = 0
    foreach ($file in $Files) {
        try {
            $destPath = Join-Path $backupDir $file.Name
            Copy-Item $file.FullName $destPath -Force
            $backedUp++
        }
        catch {
            Write-Log "⚠️ Failed to backup: $($file.FullName)"
        }
    }
    
    Write-Log "✓ Backed up $backedUp of $($Files.Count) files"
    return $backupDir
}

function Remove-SpamEmails {
    param([array]$Files, [bool]$DryRun)
    
    $deleted = 0
    $protected = 0
    $failed = 0
    
    foreach ($file in $Files) {
        # Protection check
        if (Test-IsProtected -FilePath $file.FullName) {
            $protected++
            continue
        }
        
        # Delete or dry-run
        if ($DryRun) {
            Write-Host "  [DRY RUN] Would delete: $($file.Name)" -ForegroundColor DarkGray
            $deleted++
        }
        else {
            try {
                Remove-Item $file.FullName -Force -ErrorAction Stop
                Write-Host "  ✓ Deleted: $($file.Name)" -ForegroundColor Green
                $deleted++
            }
            catch {
                Write-Host "  ✗ Failed: $($file.Name) - $($_.Exception.Message)" -ForegroundColor Red
                $failed++
            }
        }
    }
    
    return @{
        Deleted = $deleted
        Protected = $protected
        Failed = $failed
        Total = $Files.Count
    }
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

Write-Host "`n╔════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   WELBOURNE EMAIL CLEANUP UTILITY          ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════╝" -ForegroundColor Cyan

Write-Log "Starting cleanup - Category: $Category, DryRun: $DryRun, Backup: $BackupEnabled"

# Step 1: Search for spam emails
$spamEmails = Get-SpamEmails -Category $Category

if ($spamEmails.Count -eq 0) {
    Write-Host "`n✓ No $Category emails found. Database is clean!" -ForegroundColor Green
    exit 0
}

# Step 2: Show samples
Show-Samples -Files $spamEmails -Count 10

# Step 3: Get confirmation
Write-Host "`n=== CONFIRMATION REQUIRED ===" -ForegroundColor Yellow
Write-Host "Category: $Category" -ForegroundColor White
Write-Host "Total emails to delete: $($spamEmails.Count)" -ForegroundColor White
Write-Host "Backup enabled: $BackupEnabled" -ForegroundColor White
Write-Host "Dry run: $DryRun" -ForegroundColor White

if (-not $DryRun) {
    $confirmation = Read-Host "`nType 'DELETE' to proceed with deletion"
    if ($confirmation -ne "DELETE") {
        Write-Host "`n✗ Deletion cancelled" -ForegroundColor Red
        Write-Log "User cancelled deletion"
        exit 1
    }
}

# Step 4: Backup (if enabled)
if ($BackupEnabled -and -not $DryRun) {
    $backupPath = Backup-Files -Files $spamEmails
    Write-Host "`n✓ Backup completed: $backupPath" -ForegroundColor Green
}

# Step 5: Execute deletion
Write-Host "`n=== DELETION IN PROGRESS ===" -ForegroundColor Yellow
$results = Remove-SpamEmails -Files $spamEmails -DryRun $DryRun

# Step 6: Report results
Write-Host "`n╔════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║   DELETION SUMMARY                         ║" -ForegroundColor Green
Write-Host "╚════════════════════════════════════════════╝" -ForegroundColor Green

$originalCount = 55981
$percentReduction = ($results.Deleted / $originalCount) * 100

Write-Host "Category:        $Category" -ForegroundColor White
Write-Host "Total found:     $($results.Total)" -ForegroundColor White
Write-Host "Deleted:         $($results.Deleted)" -ForegroundColor Green
Write-Host "Protected:       $($results.Protected)" -ForegroundColor Yellow
Write-Host "Failed:          $($results.Failed)" -ForegroundColor Red
Write-Host "Remaining DB:    $($originalCount - $results.Deleted) emails" -ForegroundColor Cyan
Write-Host "Reduction:       $([math]::Round($percentReduction, 3))%" -ForegroundColor Cyan

if ($DryRun) {
    Write-Host "`n⚠️  DRY RUN - No files were actually deleted" -ForegroundColor Yellow
    Write-Host "Run with -DryRun `$false to execute actual deletion" -ForegroundColor Yellow
}

Write-Log "Cleanup completed - Deleted: $($results.Deleted), Protected: $($results.Protected), Failed: $($results.Failed)"

# Step 7: Suggest next steps
if ($results.Protected -gt 0) {
    Write-Host "`n💡 TIP: $($results.Protected) emails were protected due to keywords/senders" -ForegroundColor Cyan
    Write-Host "Review these manually if needed" -ForegroundColor Cyan
}

Write-Host "`n✓ Cleanup complete! Check log at: $LogPath" -ForegroundColor Green
