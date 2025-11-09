$body = @{
    email = 'test@vericase.com'
    password = 'password'
} | ConvertTo-Json

$response = Invoke-RestMethod -Uri 'http://localhost:8010/api/auth/login' -Method POST -Body $body -ContentType 'application/json'
Write-Host "Login successful!"
Write-Host "Token: $($response.access_token)"
Write-Host "User: $($response.user.email)"

