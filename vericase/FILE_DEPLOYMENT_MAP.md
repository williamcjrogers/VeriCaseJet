# VeriCase File Deployment Map - What Goes Where & What Actually Works

## 🔍 The Truth About Your Files

### ❌ IGNORED (Never Touch Running App)

These files are in your repo but **NEVER reach the running application**:

```
Local Files            → GitHub ✅    → EKS ❌    → Application ❌
────────────────────────────────────────────────────────────────
.env                   GITIGNORED - Never pushed, never deployed
.env.aws               GITIGNORED - Never pushed, never deployed  
.env.production        GITIGNORED - Never pushed, never deployed
.env.local.example     Documentation only, not used by app
.env.aws.example       Documentation only, not used by app
.env.production.example Documentation only, not used by app
```

**Why?** These have real secrets and are blocked by `.gitignore`

---

## ✅ WHAT ACTUALLY AFFECTS YOUR RUNNING APP

### 1. Kubernetes Deployment YAML (THE ONLY FILE THAT MATTERS)

```
k8s/k8s-deployment.yaml → GitHub ✅ → kubectl apply → EKS ✅ → Application ✅
```

**This is THE file that controls your production environment variables.**

When you run:
```bash
kubectl apply -f vericase/k8s/k8s-deployment.yaml
kubectl rollout restart deployment/vericase-api -n vericase
```

**Only then** do your changes go live!

### 2. AWS Secrets Manager (THE ONLY SOURCE FOR API KEYS)

```
Local Terminal Command → AWS Secrets Manager → EKS Pods Read It → Application ✅
```

**NOT from files! From AWS Secrets Manager!**

Your production pods load AI keys by:
1. Reading `AWS_SECRETS_MANAGER_AI_KEYS=vericase/ai-api-keys` from K8s deployment
2. Calling AWS Secrets Manager API
3. Loading keys into environment at runtime

---

## 📊 Complete File Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  YOUR LOCAL MACHINE                                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  📁 .env               ──→  ❌ GITIGNORED (never leaves local)  │
│  📁 .env.aws           ──→  ❌ GITIGNORED (never leaves local)  │
│  📁 .env.production    ──→  ❌ GITIGNORED (never leaves local)  │
│  📁 .env.*.example     ──→  ✅ GitHub (docs only, not used)     │
│                                                                 │
│  📁 k8s-deployment.yaml ──→ ✅ GitHub → EKS (ACTUALLY USED!)    │
│  📁 API Python Code    ──→  ✅ GitHub → Docker → EKS           │
│  📁 Documentation .md  ──→  ✅ GitHub (reference only)          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│  GITHUB REPOSITORY                                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ✅ k8s/k8s-deployment.yaml  (Has all env vars!)               │
│  ✅ vericase/api/app/config.py (Reads env vars & Secrets Mgr) │
│  ✅ .env.*.example files (Documentation/templates)             │
│  ✅ Documentation .md files                                     │
│  ❌ .env files (blocked by .gitignore)                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│  DOCKER BUILD (CI/CD or Manual)                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Builds Image From:                                             │
│  - Python code from GitHub                                      │
│  - requirements.txt                                             │
│  - Does NOT include .env files                                  │
│  - Does NOT include env vars yet                                │
│                                                                 │
│  Output: docker.io/wcjrogers/vericase-api:latest              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│  KUBERNETES (EKS)                                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  When you run: kubectl apply -f k8s-deployment.yaml            │
│                                                                 │
│  1. ✅ Pulls Docker image                                       │
│  2. ✅ Injects environment variables from YAML                  │
│  3. ✅ Attaches IAM role for AWS access                         │
│  4. ✅ Pod starts with these env vars:                          │
│                                                                 │
│     From k8s-deployment.yaml:                                   │
│     - ENABLE_AI_AUTO_CLASSIFY=true                             │
│     - ENABLE_AI_DATASET_INSIGHTS=true                          │
│     - ENABLE_AI_NATURAL_LANGUAGE_QUERY=true                    │
│     - USE_TEXTRACT=true                                        │
│     - USE_COMPREHEND=true                                      │
│     - BEDROCK_ENABLED=true                                     │
│     - AWS_SECRETS_MANAGER_AI_KEYS=vericase/ai-api-keys        │
│     - (and 50+ more env vars)                                  │
│                                                                 │
│  5. ✅ At startup, app reads AWS_SECRETS_MANAGER_AI_KEYS       │
│  6. ✅ Calls AWS Secrets Manager to get AI API keys            │
│  7. ✅ Loads GEMINI_API_KEY, CLAUDE_API_KEY, etc.             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│  RUNNING APPLICATION                                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Python Process Reads:                                          │
│  ✅ Environment variables from K8s deployment                   │
│  ✅ AI keys from AWS Secrets Manager                            │
│  ✅ Database URL from K8s secret                                │
│  ✅ JWT secret from K8s secret                                  │
│                                                                 │
│  Features Active If:                                            │
│  ✅ Env var set in k8s-deployment.yaml                         │
│  ✅ AND pods restarted to pick up changes                       │
│  ✅ AND required services accessible (Secrets Mgr, Bedrock)    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🎯 What You Changed vs What's Actually Running

### What You Changed (Local):

| File | Changed? | Pushed to GitHub? | Affects Production? |
|------|----------|-------------------|---------------------|
| `.env` | ✅ Yes | ❌ No (gitignored) | ❌ No |
| `.env.aws` | ✅ Yes | ❌ No (gitignored) | ❌ No |
| `.env.production` | ✅ Yes | ❌ No (gitignored) | ❌ No |
| `k8s-deployment.yaml` | ✅ Yes | ✅ Yes | **⏳ Not Yet** |
| `.env.*.example` | ✅ Yes | ✅ Yes | ❌ No (docs only) |
| Documentation | ✅ Yes | ✅ Yes | ❌ No (docs only) |

### What's Actually Running in EKS RIGHT NOW:

**OLD configuration** - because you haven't run:
```bash
kubectl apply -f vericase/k8s/k8s-deployment.yaml
kubectl rollout restart deployment/vericase-api -n vericase
```

---

## 🔄 The Deployment Pipeline

### Current State:

```
┌──────────────────┐
│ Local .env files │──→ ❌ Never deployed
│ (your changes)   │
└──────────────────┘

┌──────────────────────┐
│ k8s-deployment.yaml  │──→ ✅ Pushed to GitHub
│ (your changes)       │──→ ⏳ NOT applied to EKS yet
└──────────────────────┘──→ ⏳ Pods NOT restarted yet

┌──────────────────────┐
│ Running EKS Pods     │──→ ❌ Still using OLD config
│                      │──→ ❌ OLD environment variables
└──────────────────────┘
```

### After You Run kubectl Commands:

```
┌──────────────────────┐
│ k8s-deployment.yaml  │──→ ✅ Applied to EKS
│ (your changes)       │
└──────────────────────┘
          ↓
┌──────────────────────┐
│ kubectl apply        │──→ ✅ Updates deployment definition
└──────────────────────┘
          ↓
┌──────────────────────┐
│ kubectl restart      │──→ ✅ Kills old pods
└──────────────────────┘──→ ✅ Creates new pods
          ↓                ──→ ✅ With NEW env vars
┌──────────────────────┐
│ Running EKS Pods     │──→ ✅ NOW using NEW config
│ (restarted)          │──→ ✅ NEW environment variables
└──────────────────────┘──→ ✅ Loads AI keys from Secrets Mgr
```

---

## 📝 Environment Variables: Source of Truth

### Local Development (.env files):
```
Source: .env file on your machine
Used by: docker-compose, local Python
Affects: Only your local machine
```

### EKS Production (K8s deployment):
```
Source: k8s/k8s-deployment.yaml (env: section)
Used by: Kubernetes pods
Affects: Production application
Requires: kubectl apply + kubectl restart
```

### AI API Keys:
```
Source: AWS Secrets Manager (vericase/ai-api-keys)
Loaded by: config_production.py at pod startup
Used by: Production application
Requires: IAM permissions + secret exists
```

---

## 🚨 Why Your Changes Aren't Showing

### Problem: File Confusion

You changed `.env` files locally, but:
1. ❌ They never get pushed to GitHub (gitignored)
2. ❌ Even if pushed, K8s doesn't read them
3. ❌ K8s ONLY reads `k8s-deployment.yaml`

### Solution:

**For EKS/Production:**
```bash
# 1. The YAML file is already pushed to GitHub ✅
# 2. You MUST apply it to K8s:
kubectl apply -f vericase/k8s/k8s-deployment.yaml

# 3. You MUST restart pods:
kubectl rollout restart deployment/vericase-api -n vericase
kubectl rollout restart deployment/vericase-worker -n vericase

# 4. Verify it worked:
kubectl exec -n vericase deployment/vericase-api -- env | grep ENABLE_AI
```

**For Local Development:**
- Your `.env` files are already updated ✅
- Just restart: `docker-compose restart`

---

## 🎯 Quick Verification

### Check What's Actually Running in EKS:

```bash
# Get a running pod name
POD=$(kubectl get pod -n vericase -l app=vericase-api -o jsonpath="{.items[0].metadata.name}")

# Check CURRENT environment variables
kubectl exec -n vericase $POD -- env | grep -E "ENABLE_|USE_|AI_"

# If you see OLD values or missing variables:
# → You haven't applied the k8s-deployment.yaml yet!

# Apply and restart:
kubectl apply -f vericase/k8s/k8s-deployment.yaml
kubectl rollout restart deployment/vericase-api -n vericase
```

---

## 📊 Summary Table

| Question | Answer |
|----------|--------|
| **Are .env files used in production?** | ❌ No, never |
| **What does production use?** | ✅ k8s-deployment.yaml env vars |
| **Where do AI keys come from?** | ✅ AWS Secrets Manager |
| **Do I push .env files?** | ❌ No, gitignored |
| **Do I push k8s-deployment.yaml?** | ✅ Yes (already done) |
| **Is k8s-deployment.yaml applied?** | ⏳ Not until you run kubectl |
| **Are pods restarted?** | ⏳ Not until you run kubectl restart |
| **Are changes live?** | ❌ Not yet - run kubectl commands! |

---

## ✅ The Fix (Run Now):

```bash
# Your cluster name (find it):
aws eks list-clusters --region eu-west-2

# Connect (replace YOUR_CLUSTER_NAME):
aws eks update-kubeconfig --region eu-west-2 --name YOUR_CLUSTER_NAME

# Apply updated config:
kubectl apply -f vericase/k8s/k8s-deployment.yaml

# Force restart to pick up new env vars:
kubectl rollout restart deployment/vericase-api -n vericase
kubectl rollout restart deployment/vericase-worker -n vericase

# Wait for completion:
kubectl rollout status deployment/vericase-api -n vericase

# Verify NEW environment variables are set:
kubectl exec -n vericase deployment/vericase-api -- env | grep -E "ENABLE_AI_AUTO_CLASSIFY|ENABLE_AI_NATURAL_LANGUAGE_QUERY|MULTI_VECTOR_ENABLED"

# Should output:
# ENABLE_AI_AUTO_CLASSIFY=true
# ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
# MULTI_VECTOR_ENABLED=true
```

**THAT'S IT!** Only then are your changes actually live.
