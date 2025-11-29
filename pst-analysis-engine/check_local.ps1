# Check local Docker status
Write-Host "=== Local Docker Containers ===" -ForegroundColor Yellow
docker-compose ps

Write-Host "`n=== API Container Logs ===" -ForegroundColor Yellow
docker-compose logs --tail=30 api

Write-Host "`n=== Testing Local API ===" -ForegroundColor Yellow
curl http://localhost:8010/health

Write-Host "`n=== JWT_SECRET in local .env ===" -ForegroundColor Yellow
Select-String -Path .env -Pattern "JWT_SECRET"
