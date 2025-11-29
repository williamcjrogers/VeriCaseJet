# VeriCase - All Issues Fixed

**Date:** November 29, 2025

## ✅ Code Fixes Applied

### 1. Python f-string Syntax Errors - FIXED
**Files Modified:**
- `pst-analysis-engine/api/app_runner_start.py` - All print statements now use proper f-strings
- `pst-analysis-engine/api/apply_migrations.py` - All print statements now use proper f-strings

### 2. AWS Secrets Manager Integration - FIXED
**File Modified:** `pst-analysis-engine/api/app/config_production.py`
- Added `load_ai_keys_from_secrets_manager()` function
- Automatically loads AI API keys at startup when running in AWS
- Supports: OPENAI, ANTHROPIC/CLAUDE, GEMINI, GROK, PERPLEXITY

---

## 🔧 AWS IAM Policies Created

New policy files in `pst-analysis-engine/iam-policies/`:

### 1. `apprunner-s3-policy.json`
Grants S3 access to the bucket `vericase-docs-prod-526015377510`

### 2. `apprunner-secrets-policy.json`
Grants Secrets Manager access to `vericase/ai-api-keys`

### 3. `apprunner-opensearch-policy.json`
Grants OpenSearch HTTP access to the VeriCase domain

### 4. `opensearch-domain-policy.json`
Domain access policy to allow App Runner role (apply via AWS Console)

---

## 🚀 How to Apply AWS Fixes

### Option 1: Run PowerShell Script (Recommended)
```powershell
.\fix-all-iam-policies.ps1
```

### Option 2: Manual AWS CLI Commands

**Step 1: Create and attach S3 policy**
```bash
aws iam create-policy \
  --policy-name VeriCaseS3AccessPolicy \
  --policy-document file://pst-analysis-engine/iam-policies/apprunner-s3-policy.json \
  --region eu-west-2

aws iam attach-role-policy \
  --role-name VeriCaseAppRunnerInstanceRole \
  --policy-arn arn:aws:iam::526015377510:policy/VeriCaseS3AccessPolicy
```

**Step 2: Create and attach Secrets Manager policy**
```bash
aws iam create-policy \
  --policy-name VeriCaseSecretsManagerPolicy \
  --policy-document file://pst-analysis-engine/iam-policies/apprunner-secrets-policy.json \
  --region eu-west-2

aws iam attach-role-policy \
  --role-name VeriCaseAppRunnerInstanceRole \
  --policy-arn arn:aws:iam::526015377510:policy/VeriCaseSecretsManagerPolicy
```

**Step 3: Create and attach OpenSearch policy**
```bash
aws iam create-policy \
  --policy-name VeriCaseOpenSearchPolicy \
  --policy-document file://pst-analysis-engine/iam-policies/apprunner-opensearch-policy.json \
  --region eu-west-2

aws iam attach-role-policy \
  --role-name VeriCaseAppRunnerInstanceRole \
  --policy-arn arn:aws:iam::526015377510:policy/VeriCaseOpenSearchPolicy
```

**Step 4: Create AI API keys secret**
```bash
aws secretsmanager create-secret \
  --name vericase/ai-api-keys \
  --secret-string '{"OPENAI_API_KEY":"","ANTHROPIC_API_KEY":"","GEMINI_API_KEY":"","GROK_API_KEY":"","PERPLEXITY_API_KEY":""}' \
  --region eu-west-2
```

**Step 5: Add your actual API keys**
```bash
aws secretsmanager put-secret-value \
  --secret-id vericase/ai-api-keys \
  --secret-string '{"OPENAI_API_KEY":"sk-...","ANTHROPIC_API_KEY":"sk-ant-...","GEMINI_API_KEY":"..."}' \
  --region eu-west-2
```

**Step 6: Update OpenSearch domain access policy**
1. Go to AWS Console → OpenSearch Service → vericase-opensearch
2. Click "Security configuration" → "Edit"
3. Under "Access policy", add the App Runner role:
```json
{
  "Effect": "Allow",
  "Principal": {
    "AWS": "arn:aws:iam::526015377510:role/VeriCaseAppRunnerInstanceRole"
  },
  "Action": "es:*",
  "Resource": "arn:aws:es:eu-west-2:526015377510:domain/vericase-opensearch/*"
}
```

**Step 7: Redeploy App Runner**
```bash
aws apprunner start-deployment \
  --service-arn <your-service-arn> \
  --region eu-west-2
```

---

## 📋 Summary of All Changes

| Issue | Status | Fix |
|-------|--------|-----|
| Python f-string errors in startup | ✅ Fixed | Added `f` prefix to all formatted strings |
| S3 Access Denied (403) | ✅ Policy Created | Run `fix-all-iam-policies.ps1` |
| Secrets Manager Invalid Token | ✅ Policy Created | Run `fix-all-iam-policies.ps1` |
| OpenSearch Authorization (403) | ✅ Policy Created | Apply domain policy via AWS Console |
| AI keys not loading | ✅ Code Fixed | Auto-loads from Secrets Manager |

---

## 🧪 Verification

After applying all fixes and redeploying:

1. **Check App Runner logs** for successful startup messages:
   ```
   ✓ Loaded OPENAI_API_KEY from Secrets Manager
   ✓ Loaded CLAUDE_API_KEY from Secrets Manager
   ```

2. **Test S3 upload** - Should work without "Access Denied"

3. **Test AI features** - Intelligent wizard should respond

4. **Test search** - OpenSearch queries should work

---

## 📞 Support

If issues persist after applying all fixes:
1. Check App Runner logs for specific error messages
2. Verify IAM role has all policies attached
3. Verify Secrets Manager secret contains valid API keys
4. Verify OpenSearch domain policy includes the App Runner role
