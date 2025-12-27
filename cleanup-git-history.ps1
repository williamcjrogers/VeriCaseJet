# Git History Cleanup Script
# Removes sensitive file (.kilocode/mcp.json) from ALL git history

Write-Host "========================================" -ForegroundColor Red
Write-Host "GIT HISTORY CLEANUP - REMOVE CREDENTIALS" -ForegroundColor Red
Write-Host "========================================" -ForegroundColor Red
Write-Host ""

Write-Host "⚠️  WARNING: This will rewrite git history!" -ForegroundColor Yellow
Write-Host "⚠️  This is a DESTRUCTIVE operation that cannot be easily undone!" -ForegroundColor Yellow
Write-Host ""
Write-Host "Before proceeding, ensure:" -ForegroundColor Yellow
Write-Host "  1. You have rotated ALL exposed credentials" -ForegroundColor White
Write-Host "  2. You have notified any team members" -ForegroundColor White
Write-Host "  3. You have backed up any important data" -ForegroundColor White
Write-Host "  4. No one else is currently working on this repository" -ForegroundColor White
Write-Host ""

$confirmation = Read-Host "Type 'YES' to continue or anything else to cancel"

if ($confirmation -ne "YES") {
    Write-Host ""
    Write-Host "Operation cancelled. No changes were made." -ForegroundColor Green
    exit
}

Write-Host ""
Write-Host "Starting cleanup process..." -ForegroundColor Cyan
Write-Host ""

# Check if git-filter-repo is installed
Write-Host "Checking for git-filter-repo..." -NoNewline
$filterRepoInstalled = $false

try {
    $null = git filter-repo --version 2>$null
    $filterRepoInstalled = $true
    Write-Host " Found!" -ForegroundColor Green
} catch {
    Write-Host " Not found!" -ForegroundColor Yellow
}

if (-not $filterRepoInstalled) {
    Write-Host ""
    Write-Host "git-filter-repo is not installed. Installing now..." -ForegroundColor Yellow
    
    try {
        # Try to install via pip
        python -m pip install git-filter-repo
        Write-Host "git-filter-repo installed successfully!" -ForegroundColor Green
    } catch {
        Write-Host ""
        Write-Host "ERROR: Failed to install git-filter-repo automatically." -ForegroundColor Red
        Write-Host ""
        Write-Host "Please install manually:" -ForegroundColor Yellow
        Write-Host "  Option 1: pip install git-filter-repo" -ForegroundColor White
        Write-Host "  Option 2: Download from https://github.com/newren/git-filter-repo" -ForegroundColor White
        Write-Host ""
        exit 1
    }
}

Write-Host ""
Write-Host "Step 1: Creating backup..." -ForegroundColor Cyan
$backupName = "backup-before-cleanup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
try {
    git branch $backupName
    Write-Host "✓ Backup branch created: $backupName" -ForegroundColor Green
} catch {
    Write-Host "⚠️  Warning: Could not create backup branch" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Step 2: Removing .kilocode/mcp.json from git history..." -ForegroundColor Cyan
Write-Host "This may take a few minutes..." -ForegroundColor Yellow
Write-Host ""

try {
    # Use git-filter-repo to remove the file
    git filter-repo --path .kilocode/mcp.json --invert-paths --force
    
    Write-Host ""
    Write-Host "✓ File successfully removed from git history!" -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "ERROR: Failed to remove file from git history" -ForegroundColor Red
    Write-Host "Error details: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "You can restore from backup branch: $backupName" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "Step 3: Verifying cleanup..." -ForegroundColor Cyan

# Check if file still exists in history
$fileStillExists = $false
try {
    $null = git log --all --full-history -- .kilocode/mcp.json 2>$null
    if ($LASTEXITCODE -eq 0) {
        $fileStillExists = $true
    }
} catch {
    # File not found in history - good!
}

if ($fileStillExists) {
    Write-Host "⚠️  Warning: File may still exist in history" -ForegroundColor Yellow
} else {
    Write-Host "✓ File successfully removed from all git history" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "CLEANUP COMPLETE" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "NEXT STEPS:" -ForegroundColor Yellow
Write-Host ""
Write-Host "1. Force push to GitHub to remove credentials from remote repository:" -ForegroundColor White
Write-Host "   git push origin --force --all" -ForegroundColor Cyan
Write-Host "   git push origin --force --tags" -ForegroundColor Cyan
Write-Host ""
Write-Host "2. Verify the commit is cleaned on GitHub:" -ForegroundColor White
Write-Host "   https://github.com/williamcjrogers/VeriCaseJet/commit/76b6ee895b6df30725f53480a42fec339c9a2af2" -ForegroundColor Cyan
Write-Host ""
Write-Host "3. You may need to contact GitHub Support to purge cached versions" -ForegroundColor White
Write-Host ""
Write-Host "4. Have all team members re-clone the repository (if applicable)" -ForegroundColor White
Write-Host "   Old clones will have the compromised history" -ForegroundColor Yellow
Write-Host ""
Write-Host "5. Update AWS Support Case #176679531900745 with completion status" -ForegroundColor White
Write-Host ""

$pushNow = Read-Host "Do you want to force push to GitHub now? (yes/no)"

if ($pushNow -eq "yes") {
    Write-Host ""
    Write-Host "Force pushing to GitHub..." -ForegroundColor Cyan
    
    try {
        git push origin --force --all
        git push origin --force --tags
        
        Write-Host ""
        Write-Host "✓ Successfully pushed to GitHub!" -ForegroundColor Green
        Write-Host ""
        Write-Host "Please verify the commit is cleaned on GitHub:" -ForegroundColor Yellow
        Write-Host "https://github.com/williamcjrogers/VeriCaseJet/commit/76b6ee895b6df30725f53480a42fec339c9a2af2" -ForegroundColor Cyan
    } catch {
        Write-Host ""
        Write-Host "ERROR: Failed to push to GitHub" -ForegroundColor Red
        Write-Host "Error details: $_" -ForegroundColor Red
        Write-Host ""
        Write-Host "You can manually push later using:" -ForegroundColor Yellow
        Write-Host "  git push origin --force --all" -ForegroundColor White
        Write-Host "  git push origin --force --tags" -ForegroundColor White
    }
} else {
    Write-Host ""
    Write-Host "Skipping GitHub push. Remember to push manually later!" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Backup branch available: $backupName" -ForegroundColor Cyan
Write-Host "If you need to restore, run: git checkout $backupName" -ForegroundColor Cyan
Write-Host ""
