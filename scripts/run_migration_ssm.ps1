# Run IPM Migration via AWS Systems Manager Session Manager
$ErrorActionPreference = "Stop"

$env:AWS_PROFILE = 'VericaseDocsAdmin'
$INSTANCE_ID = "i-0ade6dff1811bdbcb"
$REGION = "eu-west-2"

Write-Host "=== Running IPM Migration on EC2 via SSM ===" -ForegroundColor Cyan
Write-Host ""

# The migration SQL commands
$MIGRATION_SCRIPT = @'
#!/bin/bash
set -e

echo "Getting database password..."
DB_PASSWORD=$(aws secretsmanager get-secret-value --secret-id rds!db-5818fc76-6f0c-4d02-8aa4-df3d01776ed3 --region eu-west-2 --query SecretString --output text | jq -r .password)
export PGPASSWORD=$DB_PASSWORD

DB_HOST=database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com
DB_USER=vericase
DB_NAME=vericase

echo ""
echo "Step 1: Counting IPM items to hide..."
COUNT=$(psql -h $DB_HOST -U $DB_USER -d $DB_NAME -t -A -c "SELECT COUNT(*) FROM email_messages WHERE (subject LIKE 'IPM.Activity%' OR subject LIKE 'IPM.Appointment%' OR subject LIKE 'IPM.Task%' OR subject LIKE 'IPM.Contact%' OR subject LIKE 'IPM.StickyNote%' OR subject LIKE 'IPM.Schedule%' OR subject LIKE 'IPM.DistList%' OR subject LIKE 'IPM.Post%') AND (metadata IS NULL OR metadata->>'is_hidden' IS NULL OR metadata->>'is_hidden' = 'false');")

echo "Found $COUNT IPM items"
echo ""

if [ "$COUNT" -eq "0" ]; then
  echo "No items to migrate"
  exit 0
fi

echo "Step 2: Sample items (first 5):"
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT id, LEFT(subject, 50) as subject, COALESCE(metadata->>'is_hidden', 'not set') as hidden FROM email_messages WHERE (subject LIKE 'IPM.Activity%' OR subject LIKE 'IPM.Appointment%' OR subject LIKE 'IPM.Task%' OR subject LIKE 'IPM.Contact%' OR subject LIKE 'IPM.StickyNote%' OR subject LIKE 'IPM.Schedule%' OR subject LIKE 'IPM.DistList%' OR subject LIKE 'IPM.Post%') AND (metadata IS NULL OR metadata->>'is_hidden' IS NULL OR metadata->>'is_hidden' = 'false') LIMIT 5;"

echo ""
echo "Executing migration (updating $COUNT items)..."
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "UPDATE email_messages SET metadata = COALESCE(metadata, '{}'::jsonb) || '{\"is_hidden\": true, \"is_spam\": true, \"spam_category\": \"non_email\", \"spam_score\": 100}'::jsonb WHERE (subject LIKE 'IPM.Activity%' OR subject LIKE 'IPM.Appointment%' OR subject LIKE 'IPM.Task%' OR subject LIKE 'IPM.Contact%' OR subject LIKE 'IPM.StickyNote%' OR subject LIKE 'IPM.Schedule%' OR subject LIKE 'IPM.DistList%' OR subject LIKE 'IPM.Post%') AND (metadata IS NULL OR metadata->>'is_hidden' IS NULL OR metadata->>'is_hidden' = 'false');"

echo ""
echo "Verification:"
HIDDEN_COUNT=$(psql -h $DB_HOST -U $DB_USER -d $DB_NAME -t -A -c "SELECT COUNT(*) FROM email_messages WHERE metadata->>'is_hidden' = 'true' AND subject LIKE 'IPM.%';")
echo "Total hidden IPM items: $HIDDEN_COUNT"
echo ""
echo "Migration complete!"
'@

Write-Host "Sending migration command to EC2 instance..." -ForegroundColor Yellow

# Save script to temp file for proper escaping
$tempScript = [System.IO.Path]::GetTempFileName()
Set-Content -Path $tempScript -Value $MIGRATION_SCRIPT -NoNewline

$result = aws ssm send-command `
    --region $REGION `
    --instance-ids $INSTANCE_ID `
    --document-name "AWS-RunShellScript" `
    --comment "IPM Migration Script" `
    --parameters "commands=[`"$(Get-Content $tempScript -Raw | ConvertTo-Json)`"]" `
    --output json | ConvertFrom-Json

Remove-Item $tempScript -Force
$COMMAND_ID = $result.Command.CommandId
Write-Host "Command sent! Command ID: $COMMAND_ID" -ForegroundColor Green
Write-Host ""
Write-Host "Waiting for command to complete..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

# Poll for results
$maxAttempts = 20
$attempt = 0

while ($attempt -lt $maxAttempts) {
    $attempt++
    
    try {
        $output = aws ssm get-command-invocation `
            --region $REGION `
            --command-id $COMMAND_ID `
            --instance-id $INSTANCE_ID `
            --output json | ConvertFrom-Json
        
        $status = $output.Status
        Write-Host "Status: $status" -ForegroundColor Cyan
        
        if ($status -eq "Success") {
            Write-Host ""
            Write-Host "=== Command Output ===" -ForegroundColor Green
            Write-Host $output.StandardOutputContent
            
            if ($output.StandardErrorContent) {
                Write-Host ""
                Write-Host "=== Errors ===" -ForegroundColor Yellow
                Write-Host $output.StandardErrorContent
            }
            break
        } elseif ($status -eq "Failed") {
            Write-Host ""
            Write-Host "=== Command Failed ===" -ForegroundColor Red
            Write-Host $output.StandardOutputContent
            Write-Host $output.StandardErrorContent
            break
        } elseif ($status -in @("InProgress", "Pending")) {
            Start-Sleep -Seconds 2
            continue
        } else {
            Write-Host "Unexpected status: $status" -ForegroundColor Yellow
            break
        }
    } catch {
        Write-Host "Waiting for command to register..." -ForegroundColor Gray
        Start-Sleep -Seconds 2
    }
}

Write-Host ""
Write-Host "=== Complete ===" -ForegroundColor Cyan
