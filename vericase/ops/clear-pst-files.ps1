#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Clear pending and failed PST files from VeriCase

.DESCRIPTION
    This script uses the admin cleanup API endpoint to remove pending and failed PST files.
    It can target specific projects or cases, and provides a dry-run mode by default.

.PARAMETER ApiUrl
    The base URL of the VeriCase API (default: http://localhost:8010)

.PARAMETER ProjectId
    The project ID to clean up (optional, either ProjectId or CaseId required)

.PARAMETER CaseId
    The case ID to clean up (optional, either ProjectId or CaseId required)

.PARAMETER StuckHours
    Hours after which a processing/queued PST is considered stuck (default: 1)

.PARAMETER IncludeFailed
    Include failed PST files (default: true)

.PARAMETER IncludeStuck
    Include stuck PST files (default: true)

.PARAMETER IncludeDuplicates
    Include duplicate PST files (default: true)

.PARAMETER Apply
    Actually apply the cleanup (default is dry-run mode)

.EXAMPLE
    # Dry-run for a specific project
    .\clear-pst-files.ps1 -ProjectId "your-project-id"

.EXAMPLE
    # Actually delete failed and stuck PSTs for a case
    .\clear-pst-files.ps1 -CaseId "your-case-id" -Apply

.EXAMPLE
    # Clear only failed PSTs (not stuck ones)
    .\clear-pst-files.ps1 -ProjectId "your-project-id" -IncludeStuck $false -Apply
#>

param(
    [string]$ApiUrl = "http://localhost:8010",
    [string]$ProjectId = "",
    [string]$CaseId = "",
    [double]$StuckHours = 1.0,
    [bool]$IncludeFailed = $true,
    [bool]$IncludeStuck = $true,
    [bool]$IncludeDuplicates = $true,
    [switch]$Apply
)

# Color output helpers
function Write-Info { param([string]$Message) Write-Host $Message -ForegroundColor Cyan }
function Write-Success { param([string]$Message) Write-Host $Message -ForegroundColor Green }
function Write-Warning { param([string]$Message) Write-Host $Message -ForegroundColor Yellow }
function Write-Error { param([string]$Message) Write-Host $Message -ForegroundColor Red }

Write-Info "=== VeriCase PST Cleanup Tool ==="
Write-Info ""

# Validate parameters
if (-not $ProjectId -and -not $CaseId) {
    Write-Error "Error: Either -ProjectId or -CaseId must be specified"
    Write-Info "Usage: .\clear-pst-files.ps1 -ProjectId <project-id> [-Apply]"
    Write-Info "   or: .\clear-pst-files.ps1 -CaseId <case-id> [-Apply]"
    exit 1
}

# Check for authentication token
$token = $null
$tokenPath = "$HOME\.vericase-token"
if (Test-Path $tokenPath) {
    $token = Get-Content $tokenPath -Raw
    $token = $token.Trim()
    Write-Info "Using token from: $tokenPath"
} else {
    Write-Warning "No token found at $tokenPath"
    Write-Info "Please login first or manually set the token"
    Write-Info "You can save a token to: $tokenPath"
    exit 1
}

# Build request body
$body = @{
    stuck_hours = $StuckHours
    include_failed = $IncludeFailed
    include_stuck = $IncludeStuck
    include_duplicates = $IncludeDuplicates
    apply = $Apply.IsPresent
}

if ($ProjectId) {
    $body.project_id = $ProjectId
    Write-Info "Target: Project ID = $ProjectId"
}
if ($CaseId) {
    $body.case_id = $CaseId
    Write-Info "Target: Case ID = $CaseId"
}

# Show configuration
Write-Info ""
Write-Info "Configuration:"
Write-Info "  - Include Failed: $IncludeFailed"
Write-Info "  - Include Stuck: $IncludeStuck (after $StuckHours hours)"
Write-Info "  - Include Duplicates: $IncludeDuplicates"
Write-Info "  - Mode: $(if ($Apply.IsPresent) { 'APPLY (WILL DELETE)' } else { 'DRY-RUN (preview only)' })"
Write-Info ""

if (-not $Apply.IsPresent) {
    Write-Warning "Running in DRY-RUN mode (preview only)"
    Write-Warning "Add -Apply to actually delete the files"
    Write-Info ""
}

# Make API request
try {
    $endpoint = "$ApiUrl/api/admin/cleanup-pst"
    Write-Info "Calling API endpoint: $endpoint"
    
    $headers = @{
        "Authorization" = "Bearer $token"
        "Content-Type" = "application/json"
    }
    
    $jsonBody = $body | ConvertTo-Json -Depth 10
    
    $response = Invoke-RestMethod -Uri $endpoint -Method POST -Headers $headers -Body $jsonBody -ContentType "application/json"
    
    Write-Success ""
    Write-Success "=== Cleanup Results ==="
    Write-Success ""
    Write-Info "Mode: $($response.mode)"
    Write-Info "Total Candidates: $($response.candidates_count)"
    Write-Info "Selected for Cleanup: $($response.selected_count)"
    Write-Info ""
    Write-Success "Summary:"
    Write-Info "  - PST Files: $($response.summary.pst_files)"
    Write-Info "  - Email Messages: $($response.summary.email_messages)"
    Write-Info "  - Email Attachments: $($response.summary.email_attachments)"
    Write-Info "  - Evidence Items: $($response.summary.evidence_items)"
    Write-Info ""
    
    if ($response.selected_count -gt 0) {
        Write-Success "Selected PST Files:"
        foreach ($pst in $response.selected) {
            Write-Info "  [$($pst.status)] $($pst.filename)"
            Write-Info "    ID: $($pst.id)"
            Write-Info "    Uploaded: $($pst.uploaded_at)"
            Write-Info "    Emails: $($pst.processed_emails)/$($pst.total_emails)"
            Write-Info "    Will delete: $($pst.counts.email_messages) emails, $($pst.counts.email_attachments) attachments, $($pst.counts.evidence_items) evidence items"
            Write-Info ""
        }
        
        if ($Apply.IsPresent) {
            Write-Success "Cleanup completed successfully!"
        } else {
            Write-Warning "This was a DRY-RUN. No files were deleted."
            Write-Warning "Run with -Apply to actually delete these files."
        }
    } else {
        Write-Success "No PST files matched the cleanup criteria."
    }
    
} catch {
    Write-Error ""
    Write-Error "Error calling cleanup API:"
    Write-Error $_.Exception.Message
    
    if ($_.ErrorDetails) {
        Write-Error "Details: $($_.ErrorDetails.Message)"
    }
    
    # Check for common issues
    if ($_.Exception.Response.StatusCode -eq 401) {
        Write-Warning ""
        Write-Warning "Authentication failed. Please check your token."
    } elseif ($_.Exception.Response.StatusCode -eq 403) {
        Write-Warning ""
        Write-Warning "Access denied. Admin access required (@vericase.com email)."
    }
    
    exit 1
}
