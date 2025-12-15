<#
.SYNOPSIS
    Fetches AI API keys from AWS Secrets Manager and writes them to .env

.DESCRIPTION
    Pulls the vericase/ai-api-keys secret from AWS Secrets Manager and
    merges the keys into your local .env file. This lets you use Secrets
    Manager as the single source of truth while still running locally.

.PARAMETER SecretName
    Name of the secret in AWS Secrets Manager (default: vericase/ai-api-keys)

.PARAMETER Region
    AWS region (default: eu-west-2)

.PARAMETER EnvFile
    Path to .env file to update (default: ..\\.env relative to this script)

.EXAMPLE
    .\fetch-ai-keys.ps1
    .\fetch-ai-keys.ps1 -SecretName "vericase/ai-api-keys" -Region "eu-west-2"
#>

param(
    [string]$SecretName = "vericase/ai-api-keys",
    [string]$Region = "eu-west-2",
    [string]$EnvFile = ""
)

$ErrorActionPreference = "Stop"

# Resolve .env path
if (-not $EnvFile) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $EnvFile = Join-Path (Split-Path -Parent $ScriptDir) ".env"
}

Write-Host "🔐 Fetching AI keys from AWS Secrets Manager..." -ForegroundColor Cyan
Write-Host "   Secret: $SecretName"
Write-Host "   Region: $Region"
Write-Host "   Target: $EnvFile"
Write-Host ""

# Check AWS CLI
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-Error "AWS CLI not found. Install from https://aws.amazon.com/cli/"
    exit 1
}

# Fetch secret
try {
    $secretJson = aws secretsmanager get-secret-value `
        --secret-id $SecretName `
        --region $Region `
        --query SecretString `
        --output text 2>&1

    if ($LASTEXITCODE -ne 0) {
        throw "AWS CLI returned error: $secretJson"
    }
}
catch {
    Write-Error "Failed to fetch secret: $_"
    Write-Host ""
    Write-Host "Make sure you have:" -ForegroundColor Yellow
    Write-Host "  1. AWS CLI configured (aws configure)"
    Write-Host "  2. Permissions to read secretsmanager:GetSecretValue"
    Write-Host "  3. The secret '$SecretName' exists in region '$Region'"
    exit 1
}

# Parse JSON
try {
    $secrets = $secretJson | ConvertFrom-Json
}
catch {
    Write-Error "Failed to parse secret JSON: $_"
    exit 1
}

# Map secret keys to env var names
$keyMap = @{
    "OPENAI_API_KEY"     = "OPENAI_API_KEY"
    "CLAUDE_API_KEY"     = "CLAUDE_API_KEY"
    "ANTHROPIC_API_KEY"  = "CLAUDE_API_KEY"  # Alias
    "GEMINI_API_KEY"     = "GEMINI_API_KEY"
    "XAI_API_KEY"        = "XAI_API_KEY"
    "GROK_API_KEY"       = "GROK_API_KEY"
    "PERPLEXITY_API_KEY" = "PERPLEXITY_API_KEY"
    "SIGPARSER_API_KEY"  = "SIGPARSER_API_KEY"
    "BEDROCK_ENABLED"    = "BEDROCK_ENABLED"
    "BEDROCK_REGION"     = "BEDROCK_REGION"
    "BEDROCK_KB_ID"      = "BEDROCK_KB_ID"
}

# Read existing .env or create from template
if (Test-Path $EnvFile) {
    $envContent = Get-Content $EnvFile -Raw
    Write-Host "📄 Updating existing .env file" -ForegroundColor Green
}
else {
    $templateFile = Join-Path (Split-Path -Parent $EnvFile) ".env.ai-fullpower.example"
    if (Test-Path $templateFile) {
        $envContent = Get-Content $templateFile -Raw
        Write-Host "📄 Creating .env from .env.ai-fullpower.example template" -ForegroundColor Green
    }
    else {
        $envContent = ""
        Write-Host "📄 Creating new .env file" -ForegroundColor Green
    }
}

# Update env content with secrets
$updatedCount = 0
foreach ($prop in $secrets.PSObject.Properties) {
    $secretKey = $prop.Name
    $secretValue = $prop.Value

    # Get the env var name (may be aliased)
    $envVarName = if ($keyMap.ContainsKey($secretKey)) { $keyMap[$secretKey] } else { $secretKey }

    if ([string]::IsNullOrWhiteSpace($secretValue)) {
        continue
    }

    # Check if key exists in content
    $pattern = "(?m)^${envVarName}=.*$"
    if ($envContent -match $pattern) {
        # Replace existing
        $envContent = $envContent -replace $pattern, "${envVarName}=${secretValue}"
    }
    else {
        # Append
        $envContent = $envContent.TrimEnd() + "`n${envVarName}=${secretValue}`n"
    }
    
    # Mask key for display
    $masked = if ($secretValue.Length -gt 8) {
        $secretValue.Substring(0, 4) + "..." + $secretValue.Substring($secretValue.Length - 4)
    } else { "****" }
    
    Write-Host "   ✓ $envVarName = $masked" -ForegroundColor DarkGray
    $updatedCount++
}

# Ensure AWS_SECRETS_MANAGER_AI_KEYS is set for runtime loading
$secretsManagerVar = "AWS_SECRETS_MANAGER_AI_KEYS=$SecretName"
if ($envContent -notmatch "(?m)^AWS_SECRETS_MANAGER_AI_KEYS=") {
    $envContent = $envContent.TrimEnd() + "`n`n# Auto-set by fetch-ai-keys.ps1`n$secretsManagerVar`n"
    Write-Host "   ✓ AWS_SECRETS_MANAGER_AI_KEYS = $SecretName" -ForegroundColor DarkGray
}

# Write .env
$envContent | Set-Content $EnvFile -NoNewline

Write-Host ""
Write-Host "✅ Updated $updatedCount keys in $EnvFile" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Review $EnvFile"
Write-Host "  2. Run: docker compose up -d --build"
Write-Host "  3. Access: http://localhost:8010/ui/dashboard.html"
Write-Host ""
Write-Host "⚠️  Remember: .env is gitignored and should never be committed!" -ForegroundColor Yellow
