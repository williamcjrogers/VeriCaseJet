# AWS Secrets Manager Setup for API Keys

## Why Use Secrets Manager?

- âœ… API keys never stored in code or `.env` files
- âœ… Automatic rotation support
- âœ… Audit trail of who accessed keys
- âœ… Keys encrypted at rest
- âœ… No risk of committing keys to Git

## Setup Steps

### 1. Get New API Keys

Rotate your exposed keys:

1. **Gemini**: https://aistudio.google.com/app/apikey
2. **Claude**: https://console.anthropic.com/settings/keys
3. **OpenAI**: https://platform.openai.com/api-keys
4. **Grok**: https://console.x.ai/
5. **Perplexity**: https://www.perplexity.ai/settings/api

### 2. Store Keys in Secrets Manager

Edit `setup-secrets-manager.sh` and replace `YOUR_NEW_*_KEY` with actual keys, then run:

```bash
chmod +x setup-secrets-manager.sh
./setup-secrets-manager.sh
```

**Or manually via AWS Console:**

1. Go to: https://eu-west-2.console.aws.amazon.com/secretsmanager/
2. Click "Store a new secret"
3. Choose "Other type of secret"
4. Add key-value pairs:
   ```
   GEMINI_API_KEY: your-key
   CLAUDE_API_KEY: your-key
   OPENAI_API_KEY: your-key
   GROK_API_KEY: your-key
   PERPLEXITY_API_KEY: your-key
   SIGPARSER_API_KEY: <your-sigparser-key>
   ```
5. Name it: `vericase/api-keys`
6. Click "Store"

### 3. Grant IAM Permissions

Your EKS pods/EC2 instances need permission to read the secret:

```bash
# For EKS (using IRSA)
aws iam create-policy \
  --policy-name VeriCaseSecretsAccess \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws:secretsmanager:eu-west-2:*:secret:vericase/api-keys*"
    }]
  }'

# Attach to your EKS service account or EC2 instance role
```

### 4. Verify It Works

```bash
# Verify the secret exists (this does NOT print the secret value)
aws secretsmanager describe-secret \
  --secret-id vericase/api-keys \
  --region eu-west-2
```

> Avoid printing secret values in terminals or CI logs. Use the AWS Console to view/edit the JSON securely.

### 5. Deploy

Your app will automatically load keys from Secrets Manager on startup (already configured in `main.py`).

```bash
# Deploy to EKS
kubectl apply -f your-deployment.yaml

# Or EC2
ssh ec2-user@35.179.167.235
./aws-deploy.sh
```

## How It Works

Your `main.py` already has this code (lines 220-245):

```python
# Load AI API keys from AWS Secrets Manager if configured
try:
    secret_name = os.getenv('AWS_SECRETS_MANAGER_AI_KEYS')
    if secret_name:
        import json
        import boto3
        
        client = boto3.client('secretsmanager', region_name='eu-west-2')
        response = client.get_secret_value(SecretId=secret_name)
        secret_data = json.loads(response['SecretString'])
        
        # Update environment variables with the loaded keys
        for key_name in ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY', ...]:
            if key_name in secret_data:
                os.environ[key_name] = secret_data[key_name]
except Exception as e:
    logger.warning(f"AWS Secrets Manager integration skipped: {e}")
```

## Update Keys Later

```bash
# Update a single key
aws secretsmanager update-secret \
  --secret-id vericase/api-keys \
  --region eu-west-2 \
  --secret-string '{
    "GEMINI_API_KEY": "new-key",
    "CLAUDE_API_KEY": "new-key",
    ...
  }'

# Restart your app to load new keys
kubectl rollout restart deployment/vericase-api
```

## Cost

- **Free tier**: 30 days free trial
- **After**: $0.40/month per secret
- **API calls**: $0.05 per 10,000 calls

For 1 secret with ~100 app restarts/month: **~$0.40/month**

## Security Best Practices

âœ… Keys never in Git
âœ… Keys encrypted at rest (AWS KMS)
âœ… Keys encrypted in transit (TLS)
âœ… Access logged in CloudTrail
âœ… Can enable automatic rotation
âœ… Can restrict access by IAM role

## Summary

Your `.env.production` now references:
```bash
AWS_SECRETS_MANAGER_AI_KEYS=vericase/api-keys
```

Instead of storing actual keys. Much more secure! ðŸ”’


