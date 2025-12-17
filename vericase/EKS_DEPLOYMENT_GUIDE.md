# VeriCase EKS Deployment Guide - Enable All AI/AWS Features

## ðŸš€ Quick Deploy - Apply Updated Configuration to EKS

```bash
# 1. Connect to your EKS cluster
aws eks update-kubeconfig --region eu-west-2 --name your-cluster-name

# 2. Verify connection
kubectl get nodes

# 3. Apply the updated deployment
kubectl apply -f vericase/k8s/k8s-deployment.yaml

# 4. Restart pods to pick up new environment variables
kubectl rollout restart deployment/vericase-api -n vericase
kubectl rollout restart deployment/vericase-worker -n vericase

# 5. Watch the rollout
kubectl rollout status deployment/vericase-api -n vericase
kubectl rollout status deployment/vericase-worker -n vericase

# 6. Check pod logs for AI key loading
kubectl logs -n vericase -l app=vericase-api --tail=100 | grep -i "secret\|config_production\|AI"
```

---

## âœ… Pre-Deployment Checklist

### 1. AWS Secrets Manager Setup

**Check if secret exists:**
```bash
aws secretsmanager describe-secret \
  --secret-id vericase/ai-api-keys \
  --region eu-west-2
```

**If secret doesn't exist, create it:**
```bash
aws secretsmanager create-secret \
  --name vericase/ai-api-keys \
  --description "VeriCase AI Provider API Keys" \
  --region eu-west-2 \
  --secret-string '{
    "GEMINI_API_KEY": "<your-gemini-key>",
    "CLAUDE_API_KEY": "<your-claude-key>",
    "OPENAI_API_KEY": "<your-openai-key>",
    "GROK_API_KEY": "<your-grok-key>",
    "PERPLEXITY_API_KEY": "<your-perplexity-key>",
    "BEDROCK_ENABLED": "true",
    "BEDROCK_REGION": "eu-west-2"
  }'
```

**Update existing secret:**
```bash
aws secretsmanager update-secret \
  --secret-id vericase/ai-api-keys \
  --region eu-west-2 \
  --secret-string '{
    "GEMINI_API_KEY": "<your-gemini-key>",
    "CLAUDE_API_KEY": "<your-claude-key>",
    "OPENAI_API_KEY": "<your-openai-key>",
    "GROK_API_KEY": "<your-grok-key>",
    "PERPLEXITY_API_KEY": "<your-perplexity-key>",
    "BEDROCK_ENABLED": "true",
    "BEDROCK_REGION": "eu-west-2"
  }'
```

### 2. IAM Role Permissions

**Verify the IAM role has these permissions:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws:secretsmanager:eu-west-2:526015377510:secret:vericase/ai-api-keys-*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::vericase-docs",
        "arn:aws:s3:::vericase-docs/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "textract:AnalyzeDocument",
        "textract:DetectDocumentText",
        "textract:StartDocumentAnalysis",
        "textract:GetDocumentAnalysis"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "comprehend:DetectEntities",
        "comprehend:DetectKeyPhrases",
        "comprehend:DetectSentiment",
        "comprehend:DetectDominantLanguage"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:Retrieve",
        "bedrock:RetrieveAndGenerate"
      ],
      "Resource": "*"
    }
  ]
}
```

**Check if role is attached to service account:**
```bash
kubectl get sa vericase-api-sa -n vericase -o yaml | grep role-arn
```

Should show:
```
eks.amazonaws.com/role-arn: arn:aws:iam::526015377510:role/vericase-eks-pod-role
```

### 3. Bedrock Model Access

**Enable required models in AWS Bedrock console:**
```bash
# Check available models
aws bedrock list-foundation-models --region eu-west-2

# Enable models in console:
# https://console.aws.amazon.com/bedrock/home?region=eu-west-2#/modelaccess
```

Required models:
- âœ… Anthropic Claude 3 Sonnet
- âœ… Amazon Titan Embeddings
- âœ… Cohere Embed English v3

---

## ðŸ“‹ Complete Deployment Steps

### Step 1: Verify Prerequisites

```bash
# Check cluster connection
kubectl cluster-info

# Check namespace exists
kubectl get namespace vericase

# If namespace doesn't exist:
kubectl create namespace vericase

# Check current deployment
kubectl get deployments -n vericase
kubectl get pods -n vericase
```

### Step 2: Check Kubernetes Secrets

```bash
# Verify vericase-secrets exist
kubectl get secret vericase-secrets -n vericase

# If missing, create it:
kubectl create secret generic vericase-secrets -n vericase \
  --from-literal=DATABASE_URL="postgresql+psycopg2://..." \
  --from-literal=JWT_SECRET="..." \
  --from-literal=ADMIN_PASSWORD="..." \
  --from-literal=AG_GRID_LICENSE_KEY="..."
```

### Step 3: Apply Updated Deployment

```bash
# Review changes before applying
kubectl diff -f vericase/k8s/k8s-deployment.yaml

# Apply the updated configuration
kubectl apply -f vericase/k8s/k8s-deployment.yaml

# Expected output:
# serviceaccount/vericase-api-sa unchanged
# deployment.apps/vericase-api configured
# deployment.apps/vericase-worker configured
# service/vericase-api unchanged
# horizontalpodautoscaler.autoscaling/vericase-api-hpa unchanged
# horizontalpodautoscaler.autoscaling/vericase-worker-hpa unchanged
# poddisruptionbudget.policy/vericase-api-pdb unchanged
# poddisruptionbudget.policy/vericase-worker-pdb unchanged
```

### Step 4: Restart Pods (Force New Env Vars)

```bash
# Restart API pods
kubectl rollout restart deployment/vericase-api -n vericase

# Restart Worker pods
kubectl rollout restart deployment/vericase-worker -n vericase

# Wait for rollout to complete
kubectl rollout status deployment/vericase-api -n vericase
kubectl rollout status deployment/vericase-worker -n vericase
```

### Step 5: Verify Deployment

```bash
# Check pod status
kubectl get pods -n vericase -w

# Check if new pods are running
kubectl get pods -n vericase -l app=vericase-api
kubectl get pods -n vericase -l app=vericase-worker

# Check pod ages (should be recent)
kubectl get pods -n vericase -o wide
```

### Step 6: Verify Environment Variables

```bash
# Check environment variables in running pod
kubectl exec -n vericase deployment/vericase-api -- env | grep -E "ENABLE_|USE_|BEDROCK|AI_"

# Should show:
# USE_AWS_SERVICES=true
# ENABLE_AI_AUTO_CLASSIFY=true
# ENABLE_AI_DATASET_INSIGHTS=true
# ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
# AI_WEB_ACCESS_ENABLED=true
# AI_TASK_COMPLEXITY_DEFAULT=advanced
# MULTI_VECTOR_ENABLED=true
# USE_TEXTRACT=true
# USE_COMPREHEND=true
# BEDROCK_ENABLED=true
# USE_KNOWLEDGE_BASE=true
```

### Step 7: Check Logs for AI Key Loading

```bash
# Check API logs for Secrets Manager loading
kubectl logs -n vericase -l app=vericase-api --tail=200 | grep -i "secret\|config_production\|ai"

# Look for these lines:
# [config_production] Should load AI keys from Secrets Manager: True
# [config_production] Loading AI keys from Secrets Manager...
# [config_production] âœ“ Loaded GEMINI_API_KEY from Secrets Manager
# [config_production] âœ“ Loaded CLAUDE_API_KEY from Secrets Manager
# [config_production] âœ“ Loaded OPENAI_API_KEY from Secrets Manager
# Successfully loaded X AI API keys from Secrets Manager
```

### Step 8: Test AI Features

```bash
# Get a pod name
POD=$(kubectl get pod -n vericase -l app=vericase-api -o jsonpath="{.items[0].metadata.name}")

# Check config in Python
kubectl exec -n vericase $POD -- python -c "
from app.config import settings
print(f'Gemini Key: {\"SET\" if settings.GEMINI_API_KEY else \"NOT SET\"}')
print(f'Claude Key: {\"SET\" if settings.CLAUDE_API_KEY else \"NOT SET\"}')
print(f'OpenAI Key: {\"SET\" if settings.OPENAI_API_KEY else \"NOT SET\"}')
print(f'Auto Classify: {settings.ENABLE_AI_AUTO_CLASSIFY}')
print(f'Dataset Insights: {settings.ENABLE_AI_DATASET_INSIGHTS}')
print(f'NL Query: {settings.ENABLE_AI_NATURAL_LANGUAGE_QUERY}')
print(f'Multi-Vector: {settings.MULTI_VECTOR_ENABLED}')
print(f'Bedrock Enabled: {settings.BEDROCK_ENABLED}')
print(f'Use Textract: {settings.USE_TEXTRACT}')
print(f'Use Comprehend: {settings.USE_COMPREHEND}')
"
```

---

## ðŸ”§ Troubleshooting

### Issue: Pods Not Starting

```bash
# Check pod status
kubectl get pods -n vericase

# Describe problematic pod
kubectl describe pod <pod-name> -n vericase

# Check events
kubectl get events -n vericase --sort-by='.lastTimestamp'
```

### Issue: Secrets Manager Access Denied

```bash
# Check if pod has IAM role
kubectl get pod <pod-name> -n vericase -o yaml | grep serviceAccount

# Check IAM role permissions
aws iam get-role --role-name vericase-eks-pod-role
aws iam list-attached-role-policies --role-name vericase-eks-pod-role

# Test Secrets Manager access from pod
kubectl exec -n vericase <pod-name> -- aws secretsmanager describe-secret \
  --secret-id vericase/ai-api-keys \
  --region eu-west-2
```

### Issue: AI Keys Not Loading

```bash
# Check full pod logs
kubectl logs -n vericase <pod-name> | grep -A 20 -B 20 "config_production"

# Check environment variables
kubectl exec -n vericase <pod-name> -- env | grep AWS_SECRETS_MANAGER

# Verify secret exists
aws secretsmanager describe-secret \
  --secret-id vericase/ai-api-keys \
  --region eu-west-2 \
```

### Issue: Features Not Working

```bash
# Check actual configuration in running pod
kubectl exec -n vericase deployment/vericase-api -- python -c "
from app.config import settings
import json
config = {
    'ENABLE_AI_AUTO_CLASSIFY': settings.ENABLE_AI_AUTO_CLASSIFY,
    'ENABLE_AI_DATASET_INSIGHTS': settings.ENABLE_AI_DATASET_INSIGHTS,
    'ENABLE_AI_NATURAL_LANGUAGE_QUERY': settings.ENABLE_AI_NATURAL_LANGUAGE_QUERY,
    'AI_WEB_ACCESS_ENABLED': settings.AI_WEB_ACCESS_ENABLED,
    'MULTI_VECTOR_ENABLED': settings.MULTI_VECTOR_ENABLED,
    'USE_TEXTRACT': settings.USE_TEXTRACT,
    'USE_COMPREHEND': settings.USE_COMPREHEND,
    'BEDROCK_ENABLED': settings.BEDROCK_ENABLED,
    'GEMINI_KEY': 'SET' if settings.GEMINI_API_KEY else 'NOT SET',
    'CLAUDE_KEY': 'SET' if settings.CLAUDE_API_KEY else 'NOT SET',
}
print(json.dumps(config, indent=2))
"
```

---

## ðŸŽ¯ What Was Changed

### Environment Variables Added to K8s Deployment:

**AI Feature Flags (NEW):**
- `ENABLE_AI_AUTO_CLASSIFY=true`
- `ENABLE_AI_DATASET_INSIGHTS=true`
- `ENABLE_AI_NATURAL_LANGUAGE_QUERY=true`
- `AI_DEFAULT_MODEL=gemini`
- `AI_WEB_ACCESS_ENABLED=true`
- `AI_TASK_COMPLEXITY_DEFAULT=advanced`
- `MULTI_VECTOR_ENABLED=true`

**AWS AI Services (NEW):**
- `USE_COMPREHEND=true`
- `BEDROCK_ENABLED=true`
- `USE_KNOWLEDGE_BASE=true`
- `BEDROCK_REGION=eu-west-2`
- `EMBEDDING_PROVIDER=bedrock`
- `BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0`

**Already Configured:**
- `USE_TEXTRACT=true`
- `AWS_SECRETS_MANAGER_AI_KEYS=vericase/ai-api-keys`
- `BEDROCK_KB_ID=ACKHIYIHPK`
- `BEDROCK_DS_ID=D9BX79MBSG`

---

## ðŸ“Š Verification Checklist

After deployment, verify each feature:

- [ ] **Pods Running**: All pods in `Running` state
- [ ] **Secrets Manager**: AI keys loading successfully in logs
- [ ] **AI Providers**: Gemini, Claude, OpenAI keys loaded
- [ ] **Auto Classification**: `ENABLE_AI_AUTO_CLASSIFY=true` in pod
- [ ] **Dataset Insights**: `ENABLE_AI_DATASET_INSIGHTS=true` in pod
- [ ] **Natural Language Query**: `ENABLE_AI_NATURAL_LANGUAGE_QUERY=true` in pod
- [ ] **Multi-Vector Search**: `MULTI_VECTOR_ENABLED=true` in pod
- [ ] **Textract**: `USE_TEXTRACT=true` and IAM permissions set
- [ ] **Comprehend**: `USE_COMPREHEND=true` and IAM permissions set
- [ ] **Bedrock**: `BEDROCK_ENABLED=true` and models enabled
- [ ] **Knowledge Base**: `USE_KNOWLEDGE_BASE=true` and KB accessible
- [ ] **Health Checks**: Pods passing liveness/readiness probes
- [ ] **Application**: UI accessible and features working

---

## ðŸš¨ Critical Next Steps

1. **Apply the K8s deployment** - Run the kubectl apply command above
2. **Restart pods** - Force pods to pick up new environment variables
3. **Verify Secrets Manager** - Ensure AI keys are in Secrets Manager
4. **Check IAM permissions** - Verify pod role has all required permissions
5. **Enable Bedrock models** - Go to Bedrock console and enable models
6. **Test features** - Try uploading a document and using AI features

---

## ðŸ“ Quick Command Reference

```bash
# Full deployment in one go
aws eks update-kubeconfig --region eu-west-2 --name your-cluster-name && \
kubectl apply -f vericase/k8s/k8s-deployment.yaml && \
kubectl rollout restart deployment/vericase-api -n vericase && \
kubectl rollout restart deployment/vericase-worker -n vericase && \
kubectl rollout status deployment/vericase-api -n vericase && \
kubectl logs -n vericase -l app=vericase-api --tail=100 | grep -i "secret\|AI"

# Check everything
kubectl get pods -n vericase && \
kubectl exec -n vericase deployment/vericase-api -- env | grep -E "ENABLE_|USE_|BEDROCK|AI_"
```

