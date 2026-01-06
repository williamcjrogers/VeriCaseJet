# Delete all projects except Welbourne Tottenham Hale (R190056)
# Usage: .\delete_projects.ps1 [-ApiBase "http://localhost:8010"]

param(
    [string]$ApiBase = "http://localhost:8010"
)

$keepProjectCode = "R190056"  # Welbourne Tottenham Hale

Write-Host "Fetching projects from $ApiBase..." -ForegroundColor Cyan

try {
    $projects = Invoke-RestMethod -Uri "$ApiBase/api/projects" -Method Get
    
    Write-Host "Found $($projects.Count) projects" -ForegroundColor Green
    
    $toDelete = $projects | Where-Object { $_.project_code -ne $keepProjectCode }
    $toKeep = $projects | Where-Object { $_.project_code -eq $keepProjectCode }
    
    if ($toKeep) {
        Write-Host "`nKeeping: $($toKeep.project_name) ($($toKeep.project_code))" -ForegroundColor Green
    } else {
        Write-Host "`nWarning: Project with code '$keepProjectCode' not found!" -ForegroundColor Yellow
    }
    
    Write-Host "`nProjects to delete:" -ForegroundColor Yellow
    $toDelete | ForEach-Object {
        Write-Host "  - $($_.project_name) ($($_.project_code)) - ID: $($_.id)"
    }
    
    $confirm = Read-Host "`nDelete $($toDelete.Count) projects? (y/n)"
    
    if ($confirm -eq 'y') {
        foreach ($project in $toDelete) {
            Write-Host "Deleting: $($project.project_name) ($($project.project_code))..." -NoNewline
            try {
                Invoke-RestMethod -Uri "$ApiBase/api/projects/$($project.id)" -Method Delete | Out-Null
                Write-Host " DELETED" -ForegroundColor Green
            } catch {
                Write-Host " FAILED: $($_.Exception.Message)" -ForegroundColor Red
            }
        }
        Write-Host "`nDeletion complete!" -ForegroundColor Green
    } else {
        Write-Host "Cancelled." -ForegroundColor Yellow
    }
    
} catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
}
