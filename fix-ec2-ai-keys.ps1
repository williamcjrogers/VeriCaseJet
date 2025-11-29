# Fix EC2 AI Keys - Add API keys directly to .env file
# This is the simplest solution - no Secrets Manager needed

$EC2_IP = "18.130.216.34"
$PEM_FILE = "VeriCase-Safe.pem"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Fix EC2 AI API Keys" -ForegroundColor Cyan  
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if PEM file exists
if (-not (Test-Path $PEM_FILE)) {
    Write-Host "[ERROR] PEM file not found: $PEM_FILE" -ForegroundColor Red
    exit 1
}

# API Keys from local .env (these are already in your repo)
$GEMINI_KEY = "AIzaSyAYr2z67p3pHe4lGTj9gYYJu4hpOTjl0A4"
$CLAUDE_KEY = "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"
$OPENAI_KEY = "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"
$GROK_KEY = "xai-FbYwX58sSeOjqQzIuNNDjY9FBtCH1Tg5R5Yxy4j9LeblPCmFJyGXJTnagdNmBZ1WOD7ebWUZTxU8Lpop"
$PERPLEXITY_KEY = "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"

Write-Host "Connecting to EC2 at $EC2_IP..." -ForegroundColor Yellow

# Create the commands to run
$sshCommands = @"
cd /home/ec2-user/VeriCaseJet/pst-analysis-engine

echo '=== Backing up .env ==='
cp .env .env.backup.\$(date +%Y%m%d_%H%M%S) 2>/dev/null || true

echo '=== Adding/Updating AI API Keys ==='

# Remove old keys if they exist (to avoid duplicates)
sed -i '/^GEMINI_API_KEY=/d' .env
sed -i '/^CLAUDE_API_KEY=/d' .env
sed -i '/^OPENAI_API_KEY=/d' .env
sed -i '/^GROK_API_KEY=/d' .env
sed -i '/^PERPLEXITY_API_KEY=/d' .env

# Add the keys
echo 'GEMINI_API_KEY=$GEMINI_KEY' >> .env
echo 'CLAUDE_API_KEY=$CLAUDE_KEY' >> .env
echo 'OPENAI_API_KEY=$OPENAI_KEY' >> .env
echo 'GROK_API_KEY=$GROK_KEY' >> .env
echo 'PERPLEXITY_API_KEY=$PERPLEXITY_KEY' >> .env

echo '=== Verifying keys added ==='
grep -E 'API_KEY=' .env | head -10

echo ''
echo '=== Restarting Docker containers ==='
docker-compose -f docker-compose.prod.yml restart api

echo ''
echo '=== Waiting for API to restart (15 seconds) ==='
sleep 15

echo ''
echo '=== Checking AI Status ==='
curl -s http://localhost:8010/api/ai/status | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8010/api/ai/status

echo ''
echo '=== Done ==='
"@

# Run SSH command
ssh -i $PEM_FILE -o StrictHostKeyChecking=no ec2-user@$EC2_IP $sshCommands

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Complete! Check AI status above." -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
