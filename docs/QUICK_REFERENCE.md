# Welbourne Refine - Quick Reference

## One-Liner Commands

### Search for Marketing Emails
```powershell
# Find webinar/conference emails
start_search(path="C:\path\to\welbourne", pattern="webinar|exhibition|conference|summit", searchType="content")
```

### Search for LinkedIn Notifications
```powershell
# Find LinkedIn profile/connection notifications
start_search(pattern="people viewed your profile|new connection|person is noticing", searchType="content")
```

### Search for Date-Only Subjects
```powershell
# Find emails with only date/timestamp as subject
start_search(pattern="^20\\d{2}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2}:\\d{2}", searchType="content")
```

### Search by Sender Domain
```powershell
# Find all emails from specific domain
start_search(pattern="@eventbrite\\.com|@mailchimp\\.com", searchType="content")
```

### Search for Other Projects (Non-Welbourne)
```powershell
# Find emails about other projects (high confidence deletion)
start_search(pattern="Abbey Road|Peabody|Merrick Place|Southall|Oxlow Lane", searchType="content")
start_search(pattern="Roxwell Road|Kings Crescent|Peckham Library|Flaxyard", searchType="content")
start_search(pattern="Beaulieu Park|Chelmsford|Islay Wharf|Camley Street", searchType="content")
```

## Bulk Deletion Scripts

### PowerShell: Delete Marketing Emails
```powershell
# Get list of files to delete
$marketingFiles = @(
    "C:\path\to\email1.msg",
    "C:\path\to\email2.msg",
    # ... more files
)

# Dry run first (preview what would be deleted)
$marketingFiles | ForEach-Object { 
    Write-Host "Would delete: $_"
}

# Actual deletion (run after confirmation)
$marketingFiles | ForEach-Object {
    Remove-Item $_ -Force
    Write-Host "Deleted: $_"
}

# Report
Write-Host "Total deleted: $($marketingFiles.Count) files"
```

### PowerShell: Delete by Pattern with Confirmation
```powershell
# Search and delete with built-in confirmation
$searchPath = "C:\path\to\welbourne\emails"
$pattern = "*webinar*"

# Find matches
$matches = Get-ChildItem -Path $searchPath -Recurse -Filter "*.msg" | 
    Where-Object { $_.Name -like $pattern }

# Show what will be deleted
Write-Host "Found $($matches.Count) matches:"
$matches | Select-Object -First 10 | ForEach-Object { 
    Write-Host "  $($_.Name)"
}

# Confirm
$confirm = Read-Host "Delete $($matches.Count) files? (yes/no)"
if ($confirm -eq "yes") {
    $matches | Remove-Item -Force
    Write-Host "Deleted $($matches.Count) files"
} else {
    Write-Host "Cancelled"
}
```

### PowerShell: Delete from CSV List
```powershell
# If search results exported to CSV
$deleteList = Import-Csv "C:\path\to\spam_emails.csv"

$deleted = 0
$failed = 0

foreach ($email in $deleteList) {
    try {
        Remove-Item $email.FilePath -Force -ErrorAction Stop
        $deleted++
        Write-Host "✓ Deleted: $($email.FilePath)"
    } catch {
        $failed++
        Write-Host "✗ Failed: $($email.FilePath) - $($_.Exception.Message)"
    }
}

Write-Host "`nDeletion Summary:"
Write-Host "  Deleted: $deleted"
Write-Host "  Failed: $failed"
Write-Host "  Total: $($deleteList.Count)"
```

## Safety Checks

### PowerShell: Verify No Protected Keywords
```powershell
# Check if files contain protected keywords before deletion
$protectedKeywords = @(
    "vobster", "s278", "s106", "remedial", "defects",
    "ljj", "grangewood", "keylon", "claim", "payment",
    "delay", "completion", "critical path"
)

$filesToCheck = @("C:\path\to\email1.msg") # ... list of files

foreach ($file in $filesToCheck) {
    $content = Get-Content $file -Raw -ErrorAction SilentlyContinue
    
    foreach ($keyword in $protectedKeywords) {
        if ($content -match $keyword) {
            Write-Host "⚠️ PROTECTED: $file contains '$keyword'"
            break
        }
    }
}
```

### PowerShell: Create Backup Before Deletion
```powershell
# Create timestamped backup directory
$backupPath = "C:\path\to\welbourne_backups\$(Get-Date -Format 'yyyyMMdd_HHmmss')"
New-Item -Path $backupPath -ItemType Directory -Force

# Copy files to backup before deletion
$filesToDelete = @("C:\path\to\email1.msg", "C:\path\to\email2.msg")

foreach ($file in $filesToDelete) {
    $destPath = Join-Path $backupPath (Split-Path $file -Leaf)
    Copy-Item $file $destPath -Force
}

Write-Host "Backed up $($filesToDelete.Count) files to $backupPath"
Write-Host "Safe to proceed with deletion"
```

## Common Patterns Cheat Sheet

| Category | Pattern | Confidence | Auto-Hide |
|----------|---------|------------|-----------|
| Marketing | `webinar\|exhibition\|conference` | 95% | ✓ |
| LinkedIn | `people viewed your profile` | 98% | ✓ |
| News Digest | `appointed to\|framework awarded` | 90% | ✓ |
| Date-Only | `^20\\d{2}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2}` | 85% | ✓ |
| Vendor Spam | `toolstation\|screwfix.*discount` | 90% | ✓ |
| Other Projects | `Abbey Road\|Peabody\|Merrick Place\|etc` | 92% | ✓ |
| Out of Office | `automatic reply\|out of office` | 75% | ✗ |
| HR Automated | `check-up for\|probation review` | 70% | ✗ |
| Surveys | `survey\|feedback request` | 65% | ✗ |

## Workflow Shortcuts

### Quick Marketing Clean
```
1. Claude: "Search for marketing emails"
2. Review top 10
3. Claude: "Delete all marketing emails" → gets confirmation
4. Done
```

### Quick LinkedIn Purge
```
1. Claude: "Remove LinkedIn notifications"  
2. Review samples
3. Confirm deletion
4. Report: "Deleted X LinkedIn emails"
```

### Quick Other Projects Cleanup
```
1. Claude: "Clean up emails from other projects"
2. Review samples (Abbey Road, Peabody, etc.)
3. Confirm deletion
4. Report: "Deleted X other-project emails"
```

### Progressive Cleanup
```
Phase 1: High confidence (marketing, LinkedIn, date-only, other projects)
Phase 2: Medium confidence (OOO, surveys)  
Phase 3: Manual review remaining low-value
```

## Database Impact Tracking

```powershell
# Calculate deletion percentage
$originalCount = 55981
$deletedCount = 284
$remainingCount = $originalCount - $deletedCount
$percentReduction = ($deletedCount / $originalCount) * 100

Write-Host "Original: $originalCount emails"
Write-Host "Deleted: $deletedCount emails"
Write-Host "Remaining: $remainingCount emails"
Write-Host "Reduction: $([math]::Round($percentReduction, 2))%"
```

## Critical Reminders

✓ Always show samples before deletion
✓ Get explicit confirmation for bulk operations  
✓ Check for protected keywords in content
✓ Preserve Aconex notifications (noreply@aconex.com)
✓ Backup PST before large deletions (500+)
✓ Report deletion counts and database impact
✓ Document all operations in audit log

✗ Never auto-delete without confirmation
✗ Never delete without showing examples
✗ Never bulk delete without keyword check
✗ Never delete claim-related correspondence
