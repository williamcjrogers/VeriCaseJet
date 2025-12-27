# 🚨 SECURITY INCIDENT RESPONSE - IMMEDIATE ACTION REQUIRED

**Date:** 2025-12-27  
**Severity:** CRITICAL  
**Status:** ACTIVE - REQUIRES IMMEDIATE ACTION

## Executive Summary

AWS has detected exposed credentials in your GitHub repository. Additionally, the `.kilocode/mcp.json` file contains **MULTIPLE EXPOSED CREDENTIALS** beyond just the AWS keys mentioned by AWS.

## 🔴 EXPOSED CREDENTIALS IDENTIFIED

### 1. AWS IAM Access Key (AWS Alert)
- **Access Key:** `AKIAXU6HVWBTKU4CVBUA`
- **User:** `VericaseDocsAdmin`
- **Account:** `526015377510`
- **Status:** Quarantined by AWS
- **Exposed at:** https://github.com/williamcjrogers/VeriCaseJet/blob/76b6ee895b6df30725f53480a42fec339c9a2af2/.kilocode/mcp.json

### 2. PostgreSQL Database Credentials
- **Connection String:** `postgresql://VericaseDocsAdmin:Sunnyday8?!@database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com:5432/postgres`
- **Username:** `VericaseDocsAdmin`
- **Password:** `Sunnyday8?!`
- **Database:** `database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com`
- **Risk:** Full database access compromised

### 3. GitHub Personal Access Token
- **Token:** `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`
- **Permissions:** Unknown (potentially full repo access)
- **Risk:** Can be used to access/modify your GitHub repositories

### 4. Qdrant API Key
- **API Key:** `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIn0.1VBi5gFQ2NEeeVrCoQEWorzsff8UsvSO1aoBFtegRHc`
- **URL:** `https://b5412748-1bf2-4a06-9a94-5ebf25ac2d5f.eu-west-2-0.aws.cloud.qdrant.io`
- **Collection:** `symbolic-bovid-aqua`
- **Risk:** Unauthorized access to vector database

### 5. AWS Secrets Manager Reference
- **Secret ARN:** `arn:aws:secretsmanager:eu-west-2:526015377510:secret:rds!db-5818fc76-6f0c-4d02-8aa4-df3d01776ed3`
- **Risk:** If AWS keys compromised, this secret could be accessed

---

## ⚡ IMMEDIATE ACTIONS (DO NOW - IN THIS ORDER)

### PHASE 1: STOP THE BLEEDING (Next 15 minutes)

#### Step 1.1: Revoke GitHub Personal Access Token
1. Go to: https://github.com/settings/tokens
2. Find token ending in `...c9dmFah`
3. Click **Delete** immediately
4. **Verify:** The token should no longer work

#### Step 1.2: Rotate Qdrant API Key
1. Log into Qdrant Cloud: https://cloud.qdrant.io/
2. Navigate to your cluster: `b5412748-1bf2-4a06-9a94-5ebf25ac2d5f`
3. Go to **API Keys** section
4. Delete the compromised key
5. Generate a new API key
6. **Save it securely** (do NOT commit to git)

#### Step 1.3: Change RDS Database Password
1. Log into AWS Console: https://console.aws.amazon.com/
2. Go to **RDS** → **Databases**
3. Select `database-1`
4. Click **Modify**
5. Under **Settings**, set a new master password
6. Choose **Apply immediately**
7. Click **Modify DB instance**
8. **Note:** This will cause brief downtime for applications

#### Step 1.4: Rotate AWS IAM Access Keys (AWS Priority)
1. Log into AWS Console: https://console.aws.amazon.com/iam/
2. Go to **IAM** → **Users** → **VericaseDocsAdmin**
3. Go to **Security credentials** tab
4. Create a NEW access key (you can have 2 active)
5. **Download the new keys immediately**
6. Update your local AWS credentials file (`~/.aws/credentials`)
7. Test the new keys work
8. **Then delete** the old key `AKIAXU6HVWBTKU4CVBUA`

### PHASE 2: VERIFY NO UNAUTHORIZED ACCESS (Next 30 minutes)

#### Step 2.1: Check CloudTrail for Suspicious Activity
```bash
# Login to AWS Console
# Go to CloudTrail → Event history
# Filter by: User name = VericaseDocsAdmin
# Date range: Last 7 days
# Look for:
#   - Unusual API calls
#   - Calls from unknown IP addresses
#   - Resource creation (EC2, Lambda, etc.)
#   - IAM modifications
```

**Red flags to look for:**
- EC2 instances you didn't create
- Lambda functions you didn't create
- S3 buckets with unusual names
- IAM users/roles created
- Data exfiltration (large S3 downloads)
- Cryptocurrency mining indicators

#### Step 2.2: Check RDS Database Logs
```bash
# AWS Console → RDS → database-1 → Logs
# Look for:
#   - Connections from unknown IPs
#   - Large data exports
#   - Schema modifications
#   - New user creation
```

#### Step 2.3: Check GitHub Repository Access Logs
```bash
# Go to: https://github.com/williamcjrogers/VeriCaseJet/settings/security-log
# Look for unauthorized access or changes
```

### PHASE 3: REMOVE FROM GIT HISTORY (Next 30 minutes)

⚠️ **WARNING:** This will rewrite git history. Coordinate with any team members.

#### Step 3.1: Remove Sensitive File from Git History

```bash
# OPTION A: Using git-filter-repo (RECOMMENDED)
# Install git-filter-repo first:
pip install git-filter-repo

# Remove the file from all history
git filter-repo --path .kilocode/mcp.json --invert-paths --force

# OPTION B: Using BFG Repo-Cleaner (Alternative)
# Download from: https://rtyley.github.io/bfg-repo-cleaner/
# Run: java -jar bfg.jar --delete-files mcp.json

# After either option, force push to GitHub:
git push origin --force --all
git push origin --force --tags
```

#### Step 3.2: Verify Removal on GitHub
1. Go to the commit that exposed credentials: https://github.com/williamcjrogers/VeriCaseJet/commit/76b6ee895b6df30725f53480a42fec339c9a2af2
2. After force push, this commit should either not exist or not show the file

⚠️ **Note:** Even after removal, GitHub may cache the old version. You may need to contact GitHub Support to purge the cache.

### PHASE 4: AWS ACCOUNT REMEDIATION (Next 30 minutes)

#### Step 4.1: Review AWS Resources for Unwanted Usage

**Check each AWS region** (critical - mining operations often use other regions):

```bash
# Set region and check EC2 instances
aws ec2 describe-instances --region us-east-1 --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,State.Name,LaunchTime]' --output table
aws ec2 describe-instances --region us-west-2 --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,State.Name,LaunchTime]' --output table
aws ec2 describe-instances --region eu-west-1 --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,State.Name,LaunchTime]' --output table

# Check Lambda functions
aws lambda list-functions --region us-east-1
aws lambda list-functions --region us-west-2
aws lambda list-functions --region eu-west-1

# Check S3 buckets (global)
aws s3 ls

# Check for Spot instance requests
aws ec2 describe-spot-instance-requests --region us-east-1
aws ec2 describe-spot-instance-requests --region us-west-2
```

#### Step 4.2: Check Billing for Unusual Charges
1. Go to: https://console.aws.amazon.com/billing/home
2. Review **Bills** for current month
3. Look for:
   - Large EC2 charges
   - Unexpected services
   - Large data transfer charges
   - Resources in regions you don't use

#### Step 4.3: Check IAM for Unauthorized Users/Roles
```bash
# List all IAM users
aws iam list-users

# List all IAM roles (look for suspicious names)
aws iam list-roles

# Check policies attached to VericaseDocsAdmin
aws iam list-attached-user-policies --user-name VericaseDocsAdmin
aws iam list-user-policies --user-name VericaseDocsAdmin
```

#### Step 4.4: Remove Quarantine Policy
Once you've secured your account:
```bash
# Remove the quarantine policy
aws iam detach-user-policy \
  --user-name VericaseDocsAdmin \
  --policy-arn arn:aws:iam::aws:policy/AWSCompromisedKeyQuarantineV3
```

Or via AWS Console:
1. Go to IAM → Users → VericaseDocsAdmin
2. Click **Permissions** tab
3. Find `AWSCompromisedKeyQuarantineV3`
4. Click **Detach**

### PHASE 5: SECURE GOING FORWARD (Next 15 minutes)

#### Step 5.1: Enable MFA on AWS Account
1. AWS Console → IAM → Users → VericaseDocsAdmin
2. **Security credentials** tab
3. Click **Assign MFA device**
4. Follow prompts to set up authenticator app

#### Step 5.2: Create Secure Local Configuration

Create `.kilocode/mcp.local.json` with actual credentials (already in .gitignore):
```json
{
  "mcpServers": {
    "postgres": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://username:password@host:5432/dbname"]
    },
    "github": {
      "type": "stdio",
      "command": "docker",
      "args": ["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", "ghcr.io/github/github-mcp-server"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${env:GITHUB_TOKEN}"
      }
    },
    "qdrant": {
      "type": "stdio",
      "command": "uvx",
      "args": ["mcp-server-qdrant"],
      "env": {
        "QDRANT_URL": "${env:QDRANT_URL}",
        "QDRANT_API_KEY": "${env:QDRANT_API_KEY}",
        "COLLECTION_NAME": "symbolic-bovid-aqua"
      }
    }
  }
}
```

#### Step 5.3: Use Environment Variables for Credentials
Add to your shell profile (~/.bashrc or PowerShell $PROFILE):
```bash
# AWS
export AWS_PROFILE=default
export AWS_REGION=eu-west-2

# GitHub
export GITHUB_TOKEN="<new-token-here>"

# Qdrant
export QDRANT_URL="<qdrant-url-here>"
export QDRANT_API_KEY="<new-api-key-here>"
```

#### Step 5.4: Update .kilocode/mcp.json to Use Placeholders
Remove ALL hardcoded credentials and use environment variable references:
```json
{
  "mcpServers": {
    "postgres": {
      "args": ["-y", "@modelcontextprotocol/server-postgres", "${env:POSTGRES_URL}"]
    }
  }
}
```

---

## 📋 RESPONSE TO AWS SUPPORT CASE

After completing Steps 1-4, respond to AWS Support Case #176679531900745:

```
Subject: Re: [Action Required] Your AWS Access Key is Exposed - Case 176679531900745

Dear AWS Support,

I have completed the following security remediation steps:

1. ✅ STEP 1 COMPLETE: Rotated AWS access keys
   - Created new access key for IAM user VericaseDocsAdmin
   - Updated local credentials
   - Deleted exposed key AKIAXU6HVWBTKU4CVBUA

2. ✅ STEP 2 COMPLETE: Checked CloudTrail logs
   - Reviewed event history for user VericaseDocsAdmin
   - Finding: [NO UNAUTHORIZED ACTIVITY FOUND / FOUND SUSPICIOUS ACTIVITY: describe here]
   - Actions taken: [If applicable]

3. ✅ STEP 3 COMPLETE: Reviewed AWS usage
   - Checked all regions for unwanted resources
   - Verified billing for unusual charges
   - Finding: [NO UNWANTED USAGE / FOUND AND TERMINATED: describe here]

4. ✅ STEP 4 COMPLETE: Removed quarantine policy
   - Detached AWSCompromisedKeyQuarantineV3 from VericaseDocsAdmin user

5. ✅ ADDITIONAL SECURITY MEASURES:
   - Enabled MFA on IAM user
   - Removed sensitive file from git history using git-filter-repo
   - Force pushed to GitHub to remove from public view
   - Rotated all other exposed credentials (database password, API keys)
   - Implemented environment variable-based credential management

The account is now secured. I request:
- Confirmation that the quarantine has been fully lifted
- Review of any billing adjustments for unauthorized usage (if applicable)
- Confirmation that no further action is required

Thank you for your prompt alert and assistance.

Best regards,
[Your name]
```

---

## 🔒 SECURITY CHECKLIST

- [ ] GitHub PAT revoked
- [ ] Qdrant API key rotated
- [ ] RDS database password changed
- [ ] AWS IAM access key rotated
- [ ] Old AWS access key deleted
- [ ] CloudTrail logs reviewed
- [ ] AWS resources checked for unwanted usage
- [ ] Billing reviewed for unusual charges
- [ ] IAM users/roles checked for unauthorized access
- [ ] Sensitive file removed from git history
- [ ] Force pushed to GitHub
- [ ] Quarantine policy removed
- [ ] MFA enabled on AWS account
- [ ] Local config updated to use environment variables
- [ ] AWS Support Case responded to
- [ ] Team members notified (if applicable)

---

## 📞 EMERGENCY CONTACTS

- **AWS Support Case:** 176679531900745
- **AWS Support:** https://console.aws.amazon.com/support/home
- **GitHub Support:** https://support.github.com/
- **Qdrant Support:** https://qdrant.io/contact/

---

## 📚 REFERENCES

1. AWS Quarantine Policy: https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_managed-vs-inline.html
2. Removing files from Git history: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository
3. AWS CloudTrail: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-user-guide.html
4. Enabling MFA: https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_mfa.html

---

**Last Updated:** 2025-12-27 01:10 UTC  
**Next Review:** After completing all checklist items
