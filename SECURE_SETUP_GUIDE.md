# Secure Environment Setup Guide

## Overview

After the security incident, all credentials must be stored securely using environment variables instead of being hardcoded in configuration files. This guide explains how to set up your environment properly.

## 🔐 Required Environment Variables

After rotating all credentials, you need to set the following environment variables:

### AWS Credentials
Set via AWS CLI configuration (preferred method):
```bash
aws configure
# Enter your NEW access key ID
# Enter your NEW secret access key
# Default region: eu-west-2
# Default output format: json
```

Or set manually:
```powershell
# PowerShell (Windows)
$env:AWS_ACCESS_KEY_ID = "YOUR_NEW_ACCESS_KEY"
$env:AWS_SECRET_ACCESS_KEY = "YOUR_NEW_SECRET_KEY"
$env:AWS_REGION = "eu-west-2"
```

### Database Credentials
```powershell
# PowerShell
$env:POSTGRES_CONNECTION_STRING = "postgresql://username:NEW_PASSWORD@database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com:5432/postgres"
```

```bash
# Bash (Linux/Mac)
export POSTGRES_CONNECTION_STRING="postgresql://username:NEW_PASSWORD@database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com:5432/postgres"
```

### GitHub Token
```powershell
# PowerShell
$env:GITHUB_TOKEN = "YOUR_NEW_GITHUB_PAT"
```

```bash
# Bash
export GITHUB_TOKEN="YOUR_NEW_GITHUB_PAT"
```

### Qdrant Credentials
```powershell
# PowerShell
$env:QDRANT_URL = "https://b5412748-1bf2-4a06-9a94-5ebf25ac2d5f.eu-west-2-0.aws.cloud.qdrant.io"
$env:QDRANT_API_KEY = "YOUR_NEW_QDRANT_API_KEY"
```

```bash
# Bash
export QDRANT_URL="https://b5412748-1bf2-4a06-9a94-5ebf25ac2d5f.eu-west-2-0.aws.cloud.qdrant.io"
export QDRANT_API_KEY="YOUR_NEW_QDRANT_API_KEY"
```

### SSH Host (if needed)
```powershell
# PowerShell
$env:SSH_HOST = "YOUR_EC2_IP"
```

### Context7 API Key (if needed)
```powershell
# PowerShell
$env:CONTEXT7_API_KEY = "YOUR_CONTEXT7_KEY"
```

## 📝 Permanent Setup

### Windows (PowerShell Profile)

1. Open your PowerShell profile:
```powershell
notepad $PROFILE
```

2. If the file doesn't exist, create it:
```powershell
New-Item -Path $PROFILE -Type File -Force
```

3. Add all environment variables:
```powershell
# VeriCase Project Environment Variables

# AWS Configuration
$env:AWS_REGION = "eu-west-2"
$env:AWS_PROFILE = "default"

# Database
$env:POSTGRES_CONNECTION_STRING = "postgresql://username:password@host:5432/dbname"

# GitHub
$env:GITHUB_TOKEN = "your_new_github_token"

# Qdrant
$env:QDRANT_URL = "https://your-cluster.qdrant.io"
$env:QDRANT_API_KEY = "your_new_qdrant_key"

# SSH
$env:SSH_HOST = "your_ec2_ip"

# Context7 (if used)
$env:CONTEXT7_API_KEY = "your_context7_key"

Write-Host "VeriCase environment variables loaded" -ForegroundColor Green
```

4. Save and reload:
```powershell
. $PROFILE
```

### Linux/Mac (Bash Profile)

1. Edit your bash profile:
```bash
nano ~/.bashrc
# or for Mac:
nano ~/.zshrc
```

2. Add environment variables:
```bash
# VeriCase Project Environment Variables

# AWS Configuration
export AWS_REGION="eu-west-2"
export AWS_PROFILE="default"

# Database
export POSTGRES_CONNECTION_STRING="postgresql://username:password@host:5432/dbname"

# GitHub
export GITHUB_TOKEN="your_new_github_token"

# Qdrant
export QDRANT_URL="https://your-cluster.qdrant.io"
export QDRANT_API_KEY="your_new_qdrant_key"

# SSH
export SSH_HOST="your_ec2_ip"

# Context7 (if used)
export CONTEXT7_API_KEY="your_context7_key"

echo "VeriCase environment variables loaded"
```

3. Reload:
```bash
source ~/.bashrc
# or for Mac:
source ~/.zshrc
```

## 🔄 Update Configuration Files

### Update .kilocode/mcp.json

Copy the secure template:
```powershell
Copy-Item .kilocode\mcp.json.secure-template .kilocode\mcp.json -Force
```

The secure template uses environment variable references like `${env:GITHUB_TOKEN}` instead of hardcoded credentials.

### Verify Configuration

After setting environment variables, verify they're accessible:

```powershell
# PowerShell
Write-Host "Checking environment variables..."
Write-Host "AWS Region: $env:AWS_REGION"
Write-Host "GitHub Token: $(if($env:GITHUB_TOKEN) {'SET'} else {'NOT SET'})"
Write-Host "Qdrant API Key: $(if($env:QDRANT_API_KEY) {'SET'} else {'NOT SET'})"
Write-Host "Postgres Connection: $(if($env:POSTGRES_CONNECTION_STRING) {'SET'} else {'NOT SET'})"
```

```bash
# Bash
echo "Checking environment variables..."
echo "AWS Region: $AWS_REGION"
echo "GitHub Token: $([ -n "$GITHUB_TOKEN" ] && echo 'SET' || echo 'NOT SET')"
echo "Qdrant API Key: $([ -n "$QDRANT_API_KEY" ] && echo 'SET' || echo 'NOT SET')"
echo "Postgres Connection: $([ -n "$POSTGRES_CONNECTION_STRING" ] && echo 'SET' || echo 'NOT SET')"
```

## 🚫 What NOT to Do

❌ **NEVER** commit files containing credentials to git:
- `.env` files with real credentials
- Config files with hardcoded passwords
- Private keys (`.pem`, `.key` files)
- Database connection strings with passwords
- API keys or tokens

✅ **ALWAYS**:
- Use environment variables
- Use AWS Secrets Manager for production
- Keep credentials in gitignored files
- Rotate credentials regularly
- Enable MFA where available

## 📁 File Structure

```
VeriCaseJet_canonical/
├── .kilocode/
│   ├── mcp.json                    # ✅ Safe (uses environment variables)
│   ├── mcp.json.secure-template    # ✅ Template without credentials
│   └── mcp.local.json.example      # ✅ Example file (in .gitignore)
├── .env                            # ❌ NEVER commit (in .gitignore)
├── .gitignore                      # ✅ Ensures sensitive files not committed
└── SECURE_SETUP_GUIDE.md          # ✅ This file
```

## 🔐 Best Practices

### 1. Credential Rotation Schedule
- **AWS Keys**: Rotate every 90 days
- **Database Passwords**: Rotate every 90 days
- **API Tokens**: Rotate every 90 days
- **SSH Keys**: Rotate annually

### 2. Use AWS Secrets Manager (Production)

For production deployments, use AWS Secrets Manager:

```python
import boto3
import json

# Fetch secrets from AWS Secrets Manager
secrets_client = boto3.client('secretsmanager', region_name='eu-west-2')
secret = secrets_client.get_secret_value(SecretId='your-secret-id')
credentials = json.loads(secret['SecretString'])
```

### 3. Enable MFA Everywhere

Enable Multi-Factor Authentication on:
- [x] AWS Console
- [x] GitHub Account
- [x] Qdrant Dashboard
- [x] Database (if supported)

### 4. Least Privilege Access

- Grant minimum permissions needed
- Use separate IAM users for different purposes
- Review permissions regularly
- Use IAM roles for EC2/EKS instead of access keys

### 5. Monitor for Exposure

Set up alerts for:
- Failed authentication attempts
- Unusual API calls
- Access from unexpected locations
- Credential exposure in public repositories

## 🆘 If Credentials Are Exposed Again

1. **IMMEDIATELY** rotate the exposed credentials
2. Check CloudTrail/logs for unauthorized access
3. Remove from git history (use `cleanup-git-history.ps1`)
4. Force push to remove from GitHub
5. Contact service providers if needed
6. Review and update security practices

## 📞 Support

- **AWS Support**: https://console.aws.amazon.com/support/home
- **GitHub Security**: https://github.com/security
- **Project Security Contact**: [Your email]

## ✅ Setup Verification Checklist

After completing setup, verify:

- [ ] All credentials have been rotated
- [ ] Environment variables are set in shell profile
- [ ] `.kilocode/mcp.json` uses environment variable references
- [ ] No hardcoded credentials in any files
- [ ] `.gitignore` is properly configured
- [ ] Git history has been cleaned
- [ ] Changes pushed to GitHub
- [ ] MFA enabled on all accounts
- [ ] AWS quarantine policy removed
- [ ] CloudTrail shows no unauthorized activity
- [ ] Billing shows no unexpected charges
- [ ] AWS Support case updated

---

**Last Updated:** 2025-12-27  
**Version:** 1.0
