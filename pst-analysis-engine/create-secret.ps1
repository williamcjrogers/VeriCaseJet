# create-secret.ps1
$dbUrl = "postgresql+psycopg2://postgres:ZS6q|?Ccxr]Ba_tMYIyI(>~0b|W4@database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com:5432/postgres"
$jwtSecret = "5d41402abc4b2a76b9719d911017c592"

Write-Host "Creating Kubernetes secret 'vericase-secrets'..." -ForegroundColor Cyan

# Delete if exists to allow update
kubectl delete secret vericase-secrets --ignore-not-found

# Create secret
kubectl create secret generic vericase-secrets `
    --from-literal=DATABASE_URL=$dbUrl `
    --from-literal=JWT_SECRET=$jwtSecret

if ($LASTEXITCODE -eq 0) {
    Write-Host "Secret created successfully! ✅" -ForegroundColor Green
}
else {
    Write-Host "Failed to create secret." -ForegroundColor Red
}
