# ⚠️ YOUR CHANGES AREN'T LIVE YET - HERE'S WHY AND HOW TO FIX IT

## 🎯 THE PROBLEM

**Pushing to GitHub ≠ Deployed to EKS**

You updated files and pushed to GitHub, but **YOUR EKS PODS ARE STILL RUNNING OLD CODE**.

---

## 🚨 WHERE TO SEE CHANGES

### Option 1: Your Application URL

**Where is your application actually running?**

Find your ingress URL:
```bash
kubectl get ingress -n vericase
```

This will show something like:
- `vericase-ui.yourdomain.com`
- Or an AWS Load Balancer URL
- **THIS is where you see changes**

### Option 2: Check What's Actually Running

```bash
# Connect to EKS first
aws eks update-kubeconfig --region eu-west-2 --name your-cluster-name

# Check what environment variables are ACTUALLY set in running pods
kubectl exec -n vericase deployment/vericase-api -- env | grep -E "ENABLE_AI|USE_TEXTRACT|BEDROCK"

# If you DON'T see your new variables, they're NOT deployed yet!
```

---

## ✅ DEPLOY NOW - 3 COMMANDS

### Step 1: Connect to EKS

```bash
# List your clusters
aws eks list-clusters --region eu-west-2

# Connect (replace YOUR_CLUSTER_NAME with actual name from above)
aws eks update-kubeconfig --region eu-west-2 --name YOUR_CLUSTER_NAME

# Verify connection
kubectl get nodes
kubectl get pods -n vericase
```

### Step 2: Apply Updated Configuration

```bash
# This tells Kubernetes about your new environment variables
kubectl apply -f vericase/k8s/k8s-deployment.yaml
```

### Step 3: RESTART PODS (CRITICAL!)

```bash
# Without this, pods keep running with OLD config
kubectl rollout restart deployment/vericase-api -n vericase
kubectl rollout restart deployment/vericase-worker -n vericase

# Wait for restart to complete
kubectl rollout status deployment/vericase-api -n vericase
```

---

## 🔍 VERIFY IT WORKED

```bash
# Check new pods are running
kubectl get pods -n vericase

# Verify NEW environment variables are set
kubectl exec -n vericase deployment/vericase-api -- env | grep -E "ENABLE_AI_AUTO_CLASSIFY|ENABLE_AI_NATURAL_LANGUAGE_QUERY|MULTI_VECTOR"

# Should output:
# ENABLE_AI_AUTO_CLASSIFY=true
# ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
# MULTI_VECTOR_ENABLED=true

# Check logs for AI key loading
kubectl logs -n vericase -l app=vericase-api --tail=50 | grep -i "secret\|AI"
```

---

## 🌐 ACCESS YOUR APPLICATION

### Find Your Application URL:

```bash
# Option 1: Check ingress
kubectl get ingress -n vericase -o wide

# Option 2: Check service
kubectl get svc -n vericase

# Option 3: Port forward for immediate access
kubectl port-forward -n vericase svc/vericase-api 8000:80
# Then open: http://localhost:8000
```

---

## ❌ IF YOU STILL DON'T SEE CHANGES

### Check 1: Are you looking at the right URL?

```bash
# What's your actual application URL?
kubectl get ingress -n vericase

# Not localhost! Not your local docker! The INGRESS URL!
```

### Check 2: Are AI keys in Secrets Manager?

```bash
# Check if the secret exists (this does NOT print the secret value)
aws secretsmanager describe-secret \
  --secret-id vericase/ai-api-keys \
  --region eu-west-2

# If error "ResourceNotFoundException", create it with YOUR keys (do NOT hardcode in docs):
aws secretsmanager create-secret \
  --name vericase/ai-api-keys \
  --region eu-west-2 \
  --secret-string '{
    "GEMINI_API_KEY": "<your-gemini-key>",
    "CLAUDE_API_KEY": "<your-claude-key>",
    "OPENAI_API_KEY": "<your-openai-key>"
  }'
```

> 🔒 Never commit or paste real keys in this repo. Rotate any keys that were previously exposed.

### Check 3: Do you have IAM permissions?

```bash
# Check if the pod's IAM role can access the secret (this does NOT print the secret value)
POD=$(kubectl get pod -n vericase -l app=vericase-api -o jsonpath="{.items[0].metadata.name}")

kubectl exec -n vericase $POD -- aws secretsmanager describe-secret \
  --secret-id vericase/ai-api-keys \
  --region eu-west-2

# If error "AccessDenied", your IAM role needs permissions
```

### Check 4: Are Bedrock models enabled?

Go to AWS Console:
https://console.aws.amazon.com/bedrock/home?region=eu-west-2#/modelaccess

Enable:
- ✅ Anthropic Claude 3 Sonnet
- ✅ Amazon Titan Embeddings
- ✅ Cohere Embed English v3

---

## 📝 SUMMARY - THE TRUTH

| What You Did | Did It Deploy? | Where Do You See It? |
|--------------|----------------|----------------------|
| Updated `.env` files | ❌ Never deploys | Nowhere (gitignored) |
| Pushed to GitHub | ✅ Yes | GitHub only |
| Updated K8s YAML | ✅ Pushed to GitHub | Not deployed yet |
| Ran `kubectl apply` | ❌ You haven't done this | Not deployed |
| Ran `kubectl restart` | ❌ You haven't done this | Not deployed |

**BOTTOM LINE:** Run the 3 commands above (connect, apply, restart), then access your ingress URL.

---

## 🎯 ONE-LINE DEPLOY (After connecting to EKS)

```bash
kubectl apply -f vericase/k8s/k8s-deployment.yaml && \
kubectl rollout restart deployment/vericase-api -n vericase && \
kubectl rollout restart deployment/vericase-worker -n vericase && \
kubectl rollout status deployment/vericase-api -n vericase && \
echo "✅ DEPLOYED! Check your application URL now"
```

---

## 🌐 YOUR APPLICATION URL

**Find it with:**
```bash
kubectl get ingress -n vericase -o jsonpath='{.items[0].spec.rules[0].host}'
```

**OR**

```bash
kubectl get svc -n vericase vericase-api -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

**THAT'S where you see changes. Not localhost. Not GitHub. The actual deployed URL.**
