$ErrorActionPreference = "Stop"
$BaseUrl = "http://localhost:8010"
$AdminEmail = "admin@vericase.com"
$AdminPassword = "ChangeMe123"

# 1. Login
Write-Host "Logging in..." -ForegroundColor Cyan
$LoginBody = @{ email = $AdminEmail; password = $AdminPassword } | ConvertTo-Json
try {
    $LoginResponse = Invoke-RestMethod -Uri "$BaseUrl/api/auth/login" -Method Post -Body $LoginBody -ContentType "application/json"
    $Token = $LoginResponse.access_token
    Write-Host "Login successful." -ForegroundColor Green
} catch {
    Write-Error "Login failed: $_"
}
$Headers = @{ Authorization = "Bearer $Token" }

# 2. Test Flat Payload
Write-Host "Testing Flat Payload..." -ForegroundColor Cyan
$FlatPayload = @{
    project_name = "Refactor Flat Project"
    project_code = "REF-FLAT-001"
    description = "Created via flat payload"
    contract_type = "JCT"
    company_name = "Refactor Corp"
} | ConvertTo-Json

try {
    $Resp1 = Invoke-RestMethod -Uri "$BaseUrl/api/projects" -Method Post -Headers $Headers -Body $FlatPayload -ContentType "application/json"
    Write-Host "Flat Project Created: $($Resp1.name) ($($Resp1.case_number))" -ForegroundColor Green
} catch {
    Write-Error "Flat Payload Failed: $_"
}

# 3. Test Nested Payload
Write-Host "Testing Nested Payload..." -ForegroundColor Cyan
$NestedPayload = @{
    details = @{
        projectName = "Refactor Nested Project"
        projectCode = "REF-NEST-001"
        description = "Created via nested payload"
    }
    stakeholders = @{
        contractType = "NEC4"
    }
    company_name = "Refactor Corp"
} | ConvertTo-Json

try {
    $Resp2 = Invoke-RestMethod -Uri "$BaseUrl/api/projects" -Method Post -Headers $Headers -Body $NestedPayload -ContentType "application/json"
    Write-Host "Nested Project Created: $($Resp2.name) ($($Resp2.case_number))" -ForegroundColor Green
} catch {
    Write-Error "Nested Payload Failed: $_"
}
