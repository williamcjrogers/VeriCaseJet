# Direct AWS RDS IPM Migration Script
# Requires: PostgreSQL client tools (psql)

$ErrorActionPreference = "Stop"

Write-Host "=== VeriCase IPM Migration (AWS RDS Direct) ===" -ForegroundColor Cyan
Write-Host ""

# Configuration
$env:AWS_PROFILE = 'VericaseDocsAdmin'
$DB_HOST = "database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com"
$DB_NAME = "vericase"
$DB_USER = "vericase"
$DB_PORT = 5432

# Get password from AWS Secrets Manager
Write-Host "Retrieving database password from AWS Secrets Manager..." -ForegroundColor Yellow
$secretJson = aws secretsmanager get-secret-value `
    --secret-id "rds!db-5818fc76-6f0c-4d02-8aa4-df3d01776ed3" `
    --region eu-west-2 `
    --query SecretString `
    --output text

$secret = $secretJson | ConvertFrom-Json
$DB_PASSWORD = $secret.password
Write-Host "Password retrieved successfully" -ForegroundColor Green
Write-Host ""

# Set environment variable for psql
$env:PGPASSWORD = $DB_PASSWORD

# Step 1: Count IPM items
Write-Host "Step 1: Counting IPM items that need to be hidden..." -ForegroundColor Yellow
$COUNT_SQL = @"
SELECT COUNT(*) 
FROM email_messages 
WHERE (subject LIKE 'IPM.Activity%' 
   OR subject LIKE 'IPM.Appointment%' 
   OR subject LIKE 'IPM.Task%' 
   OR subject LIKE 'IPM.Contact%'
   OR subject LIKE 'IPM.StickyNote%' 
   OR subject LIKE 'IPM.Schedule%'
   OR subject LIKE 'IPM.DistList%' 
   OR subject LIKE 'IPM.Post%')
AND (metadata IS NULL 
   OR metadata->>'is_hidden' IS NULL 
   OR metadata->>'is_hidden' = 'false');
"@

$count = psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -t -A -c $COUNT_SQL
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to connect to database" -ForegroundColor Red
    exit 1
}

$count = $count.Trim()
Write-Host "Found $count IPM items to hide" -ForegroundColor Cyan
Write-Host ""

if ($count -eq "0") {
    Write-Host "No items to migrate. Exiting." -ForegroundColor Green
    exit 0
}

# Step 2: Show sample items
Write-Host "Step 2: Sample items (first 5):" -ForegroundColor Yellow
$SAMPLE_SQL = @"
SELECT id, subject, 
       COALESCE(metadata->>'is_hidden', 'not set') as current_hidden_status
FROM email_messages 
WHERE (subject LIKE 'IPM.Activity%' 
   OR subject LIKE 'IPM.Appointment%' 
   OR subject LIKE 'IPM.Task%' 
   OR subject LIKE 'IPM.Contact%'
   OR subject LIKE 'IPM.StickyNote%' 
   OR subject LIKE 'IPM.Schedule%'
   OR subject LIKE 'IPM.DistList%' 
   OR subject LIKE 'IPM.Post%')
AND (metadata IS NULL 
   OR metadata->>'is_hidden' IS NULL 
   OR metadata->>'is_hidden' = 'false')
LIMIT 5;
"@

psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -c $SAMPLE_SQL
Write-Host ""

# Step 3: Confirmation
Write-Host "This will update $count items by setting:" -ForegroundColor Yellow
Write-Host "  - is_hidden: true" -ForegroundColor White
Write-Host "  - is_spam: true" -ForegroundColor White
Write-Host "  - spam_category: non_email" -ForegroundColor White
Write-Host "  - spam_score: 100" -ForegroundColor White
Write-Host ""
$confirm = Read-Host "Do you want to proceed? (yes/no)"

if ($confirm -ne "yes") {
    Write-Host "Migration cancelled." -ForegroundColor Yellow
    exit 0
}

# Step 4: Execute update
Write-Host ""
Write-Host "Step 3: Executing migration..." -ForegroundColor Yellow
$UPDATE_SQL = @"
BEGIN;

UPDATE email_messages
SET metadata = COALESCE(metadata, '{}'::jsonb) || 
    '{"is_hidden": true, "is_spam": true, "spam_category": "non_email", "spam_score": 100}'::jsonb
WHERE (subject LIKE 'IPM.Activity%' 
   OR subject LIKE 'IPM.Appointment%' 
   OR subject LIKE 'IPM.Task%' 
   OR subject LIKE 'IPM.Contact%'
   OR subject LIKE 'IPM.StickyNote%' 
   OR subject LIKE 'IPM.Schedule%'
   OR subject LIKE 'IPM.DistList%' 
   OR subject LIKE 'IPM.Post%')
AND (metadata IS NULL 
   OR metadata->>'is_hidden' IS NULL 
   OR metadata->>'is_hidden' = 'false');

COMMIT;
"@

psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -c $UPDATE_SQL
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Migration failed!" -ForegroundColor Red
    exit 1
}

Write-Host "Migration completed successfully!" -ForegroundColor Green
Write-Host ""

# Step 5: Verify
Write-Host "Step 4: Verification - counting hidden IPM items..." -ForegroundColor Yellow
$VERIFY_SQL = @"
SELECT COUNT(*) 
FROM email_messages 
WHERE metadata->>'is_hidden' = 'true' 
AND subject LIKE 'IPM.%';
"@

$hidden_count = psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -t -A -c $VERIFY_SQL
$hidden_count = $hidden_count.Trim()
Write-Host "Total hidden IPM items: $hidden_count" -ForegroundColor Cyan
Write-Host ""
Write-Host "=== Migration Complete ===" -ForegroundColor Green

# Clean up
Remove-Item Env:\PGPASSWORD
