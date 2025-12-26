$ErrorActionPreference = "Stop"

# Configuration
$BaseUrl = "http://localhost:8010"
$AdminEmail = "admin@vericase.com"
$AdminPassword = "ChangeMe123"

# 1. Login
Write-Host "Logging in..." -ForegroundColor Cyan
$LoginBody = @{
    email = $AdminEmail
    password = $AdminPassword
} | ConvertTo-Json

try {
    $LoginResponse = Invoke-RestMethod -Uri "$BaseUrl/api/auth/login" -Method Post -Body $LoginBody -ContentType "application/json"
    $Token = $LoginResponse.access_token
    Write-Host "Login successful. Token obtained." -ForegroundColor Green
} catch {
    Write-Error "Login failed: $_"
}

$Headers = @{
    Authorization = "Bearer $Token"
}

# 2. Get Default Project
Write-Host "Getting default project..." -ForegroundColor Cyan
try {
    $Projects = Invoke-RestMethod -Uri "$BaseUrl/api/projects/default" -Method Get -Headers $Headers
    $ProjectId = $Projects.id
    Write-Host "Default Project ID: $ProjectId" -ForegroundColor Green
} catch {
    Write-Error "Failed to get default project: $_"
}

# 3. Init Multipart Upload
Write-Host "Initiating Multipart Upload..." -ForegroundColor Cyan
$InitBody = @{
    filename = "test-upload.pst"
    content_type = "application/vnd.ms-outlook"
    file_size = 1024
    project_id = $ProjectId
} | ConvertTo-Json

try {
    $InitResponse = Invoke-RestMethod -Uri "$BaseUrl/api/correspondence/pst/upload/multipart/init" -Method Post -Headers $Headers -Body $InitBody -ContentType "application/json"
    Write-Host "Upload Init Successful!" -ForegroundColor Green
    Write-Host "Upload ID: $($InitResponse.upload_id)"
    Write-Host "S3 Key: $($InitResponse.s3_key)"
    
    # Check if the bucket is correct (if returned in response, though usually it's not)
    # But we can check if the key starts with the project id or something expected.
} catch {
    Write-Error "Upload Init Failed: $_"
}
