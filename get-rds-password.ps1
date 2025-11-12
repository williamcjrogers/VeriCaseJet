# Get RDS Password from Secrets Manager
$REGION = "eu-west-2"
$DB_INSTANCE = "database-1"

Write-Host "=== Getting RDS Password from Secrets Manager ===" -ForegroundColor Green
Write-Host ""

# Find the secret ARN for this database
Write-Host "Finding secret for database: $DB_INSTANCE..." -ForegroundColor Yellow

$SECRET_ARN = aws rds describe-db-instances `
  --db-instance-identifier $DB_INSTANCE `
  --region $REGION `
  --query 'DBInstances[0].MasterUserSecret.SecretArn' `
  --output text

if ($SECRET_ARN -eq "None" -or [string]::IsNullOrEmpty($SECRET_ARN)) {
    Write-Host "✗ No managed secret found" -ForegroundColor Red
    exit 1
}

Write-Host "Secret ARN: $SECRET_ARN" -ForegroundColor Cyan
Write-Host ""

# Get the password
Write-Host "Retrieving password..." -ForegroundColor Yellow
$SECRET_JSON = aws secretsmanager get-secret-value `
  --secret-id $SECRET_ARN `
  --region $REGION `
  --query 'SecretString' `
  --output text

$SECRET = $SECRET_JSON | ConvertFrom-Json

Write-Host ""
Write-Host "=== Database Credentials ===" -ForegroundColor Green
$USERNAME = $SECRET.username
$PASSWORD = $SECRET.password
$HOST = if ($SECRET.host) { $SECRET.host } else { "database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com" }
$PORT = if ($SECRET.port) { $SECRET.port } else { "5432" }

Write-Host "Username: $USERNAME" -ForegroundColor Cyan
Write-Host "Password: $PASSWORD" -ForegroundColor Cyan
Write-Host "Host: $HOST" -ForegroundColor Cyan
Write-Host "Port: $PORT" -ForegroundColor Cyan
Write-Host ""
Write-Host "=== Update apprunner.yaml ===" -ForegroundColor Yellow
Write-Host "Replace line 36 DATABASE_URL with:" -ForegroundColor White

Add-Type -AssemblyName System.Web
$ENCODED_PASSWORD = [System.Web.HttpUtility]::UrlEncode($PASSWORD)

Write-Host "postgresql://$USERNAME`:$ENCODED_PASSWORD@$HOST`:$PORT/postgres?sslmode=require" -ForegroundColor Cyan
