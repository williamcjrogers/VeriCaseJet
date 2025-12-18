# Quick check via Docker
Write-Host "Checking non-email items in database..." -ForegroundColor Cyan

$query = @"
SELECT COUNT(*) as count
FROM email_messages
WHERE (subject LIKE 'IPM.Activity%' OR subject LIKE 'IPM.Appointment%' 
       OR subject LIKE 'IPM.Task%' OR subject LIKE 'IPM.Contact%'
       OR subject LIKE 'IPM.StickyNote%' OR subject LIKE 'IPM.Schedule%'
       OR subject LIKE 'IPM.DistList%' OR subject LIKE 'IPM.Post%')
AND (metadata IS NULL OR metadata->>'is_hidden' IS NULL OR metadata->>'is_hidden' = 'false');
"@

Write-Host "`nQuerying database..." -ForegroundColor Yellow
docker exec vericase-postgres-1 psql -U vericase -d vericase -c $query

Write-Host "`nShowing sample subjects..." -ForegroundColor Yellow
$sampleQuery = @"
SELECT subject 
FROM email_messages
WHERE (subject LIKE 'IPM.Activity%' OR subject LIKE 'IPM.Appointment%' 
       OR subject LIKE 'IPM.Task%' OR subject LIKE 'IPM.Contact%'
       OR subject LIKE 'IPM.StickyNote%' OR subject LIKE 'IPM.Schedule%'
       OR subject LIKE 'IPM.DistList%' OR subject LIKE 'IPM.Post%')
AND (metadata IS NULL OR metadata->>'is_hidden' IS NULL OR metadata->>'is_hidden' = 'false')
LIMIT 5;
"@

docker exec vericase-postgres-1 psql -U vericase -d vericase -c $sampleQuery

Write-Host "`n"
$confirm = Read-Host "Do you want to hide these items? (yes/no)"

if ($confirm -eq "yes") {
    Write-Host "`nApplying update..." -ForegroundColor Green
    
    $updateQuery = @"
BEGIN;
UPDATE email_messages
SET metadata = COALESCE(metadata, '{}'::jsonb) || 
    '{"is_hidden": true, "is_spam": true, "spam_category": "non_email", "spam_score": 100}'::jsonb
WHERE (subject LIKE 'IPM.Activity%' OR subject LIKE 'IPM.Appointment%' 
       OR subject LIKE 'IPM.Task%' OR subject LIKE 'IPM.Contact%'
       OR subject LIKE 'IPM.StickyNote%' OR subject LIKE 'IPM.Schedule%'
       OR subject LIKE 'IPM.DistList%' OR subject LIKE 'IPM.Post%')
AND (metadata IS NULL OR metadata->>'is_hidden' IS NULL OR metadata->>'is_hidden' = 'false');
COMMIT;
"@

    docker exec vericase-postgres-1 psql -U vericase -d vericase -c $updateQuery
    
    Write-Host "`nVerifying changes..." -ForegroundColor Green
    $verifyQuery = "SELECT COUNT(*) as hidden_count FROM email_messages WHERE metadata->>'is_hidden' = 'true';"
    docker exec vericase-postgres-1 psql -U vericase -d vericase -c $verifyQuery
    
    Write-Host "`n✓ Migration complete!" -ForegroundColor Green
} else {
    Write-Host "`nMigration cancelled." -ForegroundColor Yellow
}
