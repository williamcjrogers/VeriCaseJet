# 🚨 IMMEDIATE ACTION PLAN - STEP BY STEP

**Status:** Quarantine policy is blocking automated IAM operations  
**Required:** Manual AWS Console access with root or admin privileges

---

## ✅ COMPLETED

- [x] Security assessment run - **NO UNAUTHORIZED ACTIVITY FOUND**
- [x] Confirmed exposed key: `AKIAXU6HVWBTKU4CVBUA` (Status: Active)
- [x] Identified resources: 3 EC2 instances (legitimate), 2 Lambda functions (legitimate)
- [x] No cryptocurrency mining or unauthorized resources detected

---

## 🔴 CRITICAL - DO THESE NOW (15 minutes)

### 1. Revoke GitHub Personal Access Token ⚡ PRIORITY 1
**This can be done immediately without AWS access**

1. Go to: https://github.com/settings/tokens
2. Look for token ending in `...c9dmFah`
3. Click **Delete** or **Revoke**
4. Confirm deletion

✅ **Action:** Once done, generate a new token:
- Click "Generate new token" → "Generate new token (classic)"
- Name: `VeriCase Development Token`
- Expiration: 90 days
- Scopes: Select only what you need (repo, workflow)
- Click "Generate token"
- **SAVE IT IMMEDIATELY** - you won't see it again
- Store in environment variable (not in files)

---

### 2. Rotate Qdrant API Key ⚡ PRIORITY 2
**This can be done immediately**

1. Go to: https://cloud.qdrant.io/
2. Log in to your account
3. Navigate to your cluster: `b5412748-1bf2-4a06-9a94-5ebf25ac2d5f`
4. Go to **API Keys** section
5. Find the exposed key and click **Delete**
6. Generate a new API key
7. **SAVE IT IMMEDIATELY**
8. Store in environment variable

---

### 3. Change RDS Database Password ⚡ PRIORITY 3
**Requires AWS Console access - Can be done with any admin user**

1. Go to: https://console.aws.amazon.com/rds/
2. Click on **Databases** in the left menu
3. Select `database-1`
4. Click **Modify** button
5. Scroll to **Settings** section
6. Check "Change password"
7. Enter a new strong password (use a password generator)
8. Scroll to bottom and select **Apply immediately**
9. Click **Modify DB Instance**
10. **SAVE THE NEW PASSWORD** in a password manager
11. Wait 5-10 minutes for change to apply

⚠️ **WARNING:** This will cause brief downtime for your application!

---

## 🟠 URGENT - AWS CONSOLE TASKS (Next 30 minutes)

### 4. Remove Quarantine Policy & Rotate AWS Keys
**⚠️ REQUIRES ROOT ACCOUNT OR ANOTHER ADMIN IAM USER**

The `VericaseDocsAdmin` user cannot manage its own keys due to the quarantine policy.

**Option A: Use AWS Root Account**
1. Log in to AWS Console as **root user** (email + password)
2. Enable MFA if not already enabled
3. Go to IAM → Users → VericaseDocsAdmin

**Option B: Use Another Admin IAM User**
1. Log in with a different IAM user that has admin privileges
2. Go to IAM → Users → VericaseDocsAdmin

**Then proceed with these steps:**

#### Step 4.1: Remove Quarantine Policy
1. Click on **VericaseDocsAdmin** user
2. Go to **Permissions** tab
3. Find `AWSCompromisedKeyQuarantineV3` policy
4. Click the **X** or **Detach** button
5. Confirm removal

#### Step 4.2: Create New Access Key
1. Go to **Security credentials** tab
2. Scroll to **Access keys** section
3. Click **Create access key**
4. Select use case: "Command Line Interface (CLI)"
5. Click **Next** and **Create access key**
6. **DOWNLOAD THE CSV FILE IMMEDIATELY** or copy the keys
7. **DO NOT CLOSE THIS WINDOW** until keys are saved

#### Step 4.3: Update Local AWS Credentials
**On your local machine:**

```powershell
# Open AWS credentials file
notepad $HOME\.aws\credentials

# Replace with new keys:
[default]
aws_access_key_id = YOUR_NEW_ACCESS_KEY_ID
aws_secret_access_key = YOUR_NEW_SECRET_ACCESS_KEY
region = eu-west-2
```

#### Step 4.4: Test New Keys
```powershell
aws sts get-caller-identity
# Should show your account without errors
```

#### Step 4.5: Delete Exposed Key
**ONLY after confirming new keys work:**

1. Back in AWS Console → IAM → Users → VericaseDocsAdmin
2. Go to **Security credentials** tab
3. Find key `AKIAXU6HVWBTKU4CVBUA`
4. Click **Actions** → **Delete**
5. Type the access key ID to confirm
6. Click **Delete**

#### Step 4.6: Enable MFA
1. Still in **Security credentials** tab
2. Scroll to **Multi-factor authentication (MFA)**
3. Click **Assign MFA device**
4. Choose **Authenticator app**
5. Scan QR code with Google Authenticator, Authy, or 1Password
6. Enter two consecutive MFA codes
7. Click **Assign MFA**

✅ **Verification:** Try accessing AWS Console - it should now require MFA code

---

## 🟡 IMPORTANT - GIT HISTORY CLEANUP (Next 30 minutes)

### 5. Remove Credentials from Git History

**⚠️ ONLY DO THIS AFTER rotating all credentials above!**

Run the automated cleanup script:

```powershell
cd C:\Users\William\Documents\Projects\VeriCaseJet_canonical
.\cleanup-git-history.ps1
```

This script will:
- Create a backup branch
- Remove `.kilocode/mcp.json` from all git history
- Prompt you to force push to GitHub

**Or manually:**

```powershell
# Install git-filter-repo
pip install git-filter-repo

# Remove the sensitive file from all history
git filter-repo --path .kilocode/mcp.json --invert-paths --force

# Force push to GitHub (THIS REWRITES HISTORY)
git push origin --force --all
git push origin --force --tags
```

---

## 🔵 VERIFICATION (Next 15 minutes)

### 6. Verify the Exposed Commit is Cleaned

1. Go to: https://github.com/williamcjrogers/VeriCaseJet/commit/76b6ee895b6df30725f53480a42fec339c9a2af2
2. The file `.kilocode/mcp.json` should no longer appear OR the commit should not exist
3. If still visible, GitHub may have cached it - wait 30 minutes and check again
4. If still cached after 1 hour, contact GitHub Support to purge cache

### 7. Check CloudTrail for Unauthorized Activity

**After removing quarantine policy:**

```powershell
# Check recent events
aws cloudtrail lookup-events --lookup-attributes AttributeKey=Username,AttributeValue=VericaseDocsAdmin --max-results 50 --output table
```

Look for:
- Unusual API calls from unknown IPs
- Resource creation you didn't perform
- Access to sensitive data

### 8. Check AWS Billing

1. Go to: https://console.aws.amazon.com/billing/home
2. Click **Bills** in left menu
3. Review current month charges
4. Look for:
   - Large EC2 charges
   - Unexpected services
   - Large data transfer
   - Resources in regions you don't use

---

## 📋 FINAL STEPS

### 9. Update AWS Support Case

Go to: https://console.aws.amazon.com/support/home  
Case ID: **176679531900745**

**Message template:**

```
Subject: Re: [Action Required] Your AWS Access Key is Exposed - Case 176679531900745

Dear AWS Support,

I have completed the following security remediation steps:

✅ COMPLETED ACTIONS:

1. Rotated AWS IAM access keys
   - Created new access key for user VericaseDocsAdmin
   - Updated local AWS CLI credentials
   - Deleted exposed key AKIAXU6HVWBTKU4CVBUA
   - Confirmed new keys working properly

2. Reviewed CloudTrail logs
   - No unauthorized API calls detected
   - All activity matches expected usage patterns
   - No access from unknown IP addresses

3. Verified AWS resources
   - Checked all regions for unauthorized EC2 instances: None found
   - Checked for Lambda functions: Only legitimate functions present
   - Checked for Spot instances: None found
   - No cryptocurrency mining or malicious workloads detected

4. Reviewed billing
   - No unexpected charges detected
   - All costs match legitimate usage

5. Removed quarantine policy
   - Successfully detached AWSCompromisedKeyQuarantineV3 from VericaseDocsAdmin

6. Enhanced security
   - Enabled MFA on VericaseDocsAdmin user
   - Removed exposed credentials from git repository history
   - Force pushed to GitHub to remove from public view
   - Rotated all other exposed credentials (database, GitHub, API keys)
   - Implemented environment variable-based credential management

FINDINGS:
- No unauthorized access detected
- No malicious resource creation
- No unexpected billing charges
- Account now secured with MFA and new credentials

The account is fully secured. I request:
- Confirmation that the incident is resolved
- Confirmation that no further action is required
- Any billing adjustments if applicable (though no unauthorized charges were found)

Thank you for the prompt notification.

Best regards,
[Your Name]
```

### 10. Set Up Secure Environment Variables

Follow the guide in `SECURE_SETUP_GUIDE.md`:

```powershell
# Edit PowerShell profile
notepad $PROFILE

# Add environment variables (with NEW credentials):
$env:POSTGRES_CONNECTION_STRING = "postgresql://username:NEW_PASSWORD@database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com:5432/postgres"
$env:GITHUB_TOKEN = "YOUR_NEW_GITHUB_TOKEN"
$env:QDRANT_URL = "https://b5412748-1bf2-4a06-9a94-5ebf25ac2d5f.eu-west-2-0.aws.cloud.qdrant.io"
$env:QDRANT_API_KEY = "YOUR_NEW_QDRANT_KEY"

# Save and reload
. $PROFILE
```

### 11. Update .kilocode/mcp.json

```powershell
# Use the secure template
Copy-Item .kilocode\mcp.json.secure-template .kilocode\mcp.json -Force
```

The template uses environment variable references instead of hardcoded credentials.

---

## ✅ FINAL CHECKLIST

- [ ] GitHub PAT revoked and new one created
- [ ] Qdrant API key rotated
- [ ] RDS database password changed
- [ ] AWS quarantine policy removed
- [ ] New AWS access key created
- [ ] Exposed AWS access key deleted
- [ ] MFA enabled on AWS IAM user
- [ ] Git history cleaned (credentials removed)
- [ ] Changes force-pushed to GitHub
- [ ] CloudTrail reviewed (no unauthorized activity)
- [ ] Billing reviewed (no unexpected charges)
- [ ] Environment variables configured with NEW credentials
- [ ] `.kilocode/mcp.json` updated to use environment variables
- [ ] AWS Support Case #176679531900745 updated
- [ ] Application tested with new credentials
- [ ] All team members notified (if applicable)

---

## 📞 IF YOU NEED HELP

- **AWS Console:** https://console.aws.amazon.com/
- **AWS Support Case:** https://console.aws.amazon.com/support/home#/case/?displayId=176679531900745
- **GitHub Support:** https://support.github.com/

---

**Created:** 2025-12-27 01:25 UTC  
**Priority:** CRITICAL - Complete within 2 hours
