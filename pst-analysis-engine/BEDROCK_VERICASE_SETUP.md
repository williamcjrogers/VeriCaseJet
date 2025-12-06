# Amazon Bedrock - VeriCase Optimized Setup

## ✅ Configuration Complete

Your `.env` is now configured with **optimal Bedrock models for each VeriCase AI feature**.

## 🎯 VeriCase AI Features & Model Routing

### 1. AI Chat/Copilot (Deep Research)
**Use Case:** Multi-model evidence analysis, chronology building, narrative construction  
**Bedrock Model:** `amazon.nova-pro-v1:0`  
**Why:** Gap analysis and critical review require deeper reasoning  
**Cost:** $0.80/1M input tokens

```python
# Used in: api/app/ai_chat.py
# Function: _bedrock_identify_gaps()
# Task: "Gap Analysis & Critical Review"
```

### 2. AI Refinement (Data Filtering)
**Use Case:** Spam detection, duplicate removal, project cross-referencing  
**Bedrock Model:** `amazon.nova-lite-v1:0`  
**Why:** Balanced performance for pattern recognition  
**Cost:** $0.06/1M input tokens

```python
# Used in: api/app/ai_refinement.py
# Functions: analyze_for_spam(), analyze_for_other_projects()
# Task: Intelligent data cleanup
```

### 3. AI Orchestrator (Dataset Insights)
**Use Case:** Timeline generation, document insights, trend analysis  
**Bedrock Model:** `amazon.nova-lite-v1:0`  
**Why:** Fast analysis of large datasets  
**Cost:** $0.06/1M input tokens

```python
# Used in: api/app/ai_orchestrator.py
# Functions: analyze_dataset(), query_documents()
# Task: Dataset-wide analytics
```

### 4. Quick Search
**Use Case:** Fast evidence search, simple queries  
**Bedrock Model:** `amazon.nova-micro-v1:0`  
**Why:** Fastest response time for simple tasks  
**Cost:** $0.035/1M input tokens

```python
# Used in: ai_chat.py quick_search()
# Task: "Quick Evidence Search"
```

### 5. Semantic Search (Embeddings)
**Use Case:** Document similarity, vector search  
**Bedrock Model:** `amazon.titan-embed-text-v2:0`  
**Why:** Purpose-built for embeddings (1024 dimensions)  
**Cost:** $0.02/1M input tokens

## 💰 Cost Estimate (Monthly)

### Typical VeriCase Usage (1000 documents, 50 queries)

| Feature | Model | Tokens | Cost |
|---------|-------|--------|------|
| Quick Search (50 queries) | Nova Micro | 0.1M | $0.004 |
| Dataset Insights (10 analyses) | Nova Lite | 0.5M | $0.03 |
| AI Refinement (1 session) | Nova Lite | 1M | $0.06 |
| Deep Research (5 sessions) | Nova Pro | 2M | $1.60 |
| Embeddings (1000 docs) | Titan v2 | 1M | $0.02 |
| **Total** | | | **$1.71/month** |

### vs. Using Claude for Everything
- Same workload with Claude 3.5 Sonnet: **$15.00/month** (9x more expensive)

## 🚀 How It Works

### Automatic Model Selection

Your code already supports Bedrock! The models are automatically selected based on the task:

```python
# In ai_chat.py - Deep Research
bedrock_model = os.getenv("BEDROCK_CHAT_MODEL", "amazon.nova-pro-v1:0")

# In ai_refinement.py - Data Filtering  
bedrock_model = os.getenv("BEDROCK_REFINEMENT_MODEL", "amazon.nova-lite-v1:0")

# In ai_orchestrator.py - Quick Insights
bedrock_model = os.getenv("BEDROCK_ORCHESTRATOR_MODEL", "amazon.nova-lite-v1:0")
```

### Fallback Chain

If Bedrock is unavailable, your app automatically falls back to:
1. Anthropic Claude (if configured)
2. OpenAI GPT (if configured)
3. Google Gemini (if configured)

## 📋 Environment Variables

```bash
# VeriCase-optimized Bedrock configuration
BEDROCK_CHAT_MODEL=amazon.nova-pro-v1:0              # Deep research
BEDROCK_REFINEMENT_MODEL=amazon.nova-lite-v1:0       # Data filtering
BEDROCK_ORCHESTRATOR_MODEL=amazon.nova-lite-v1:0     # Dataset insights
BEDROCK_QUICK_SEARCH_MODEL=amazon.nova-micro-v1:0    # Fast queries
BEDROCK_EMBEDDING_MODEL=amazon.titan-embed-text-v2:0 # Semantic search
BEDROCK_DEFAULT_MODEL=amazon.nova-lite-v1:0          # Fallback
BEDROCK_REGION=eu-west-2
```

## 🎛️ Customization Options

### Want More Speed?
Use Nova Micro for everything:
```bash
BEDROCK_CHAT_MODEL=amazon.nova-micro-v1:0
BEDROCK_REFINEMENT_MODEL=amazon.nova-micro-v1:0
BEDROCK_ORCHESTRATOR_MODEL=amazon.nova-micro-v1:0
```
**Cost:** ~$0.20/month (10x cheaper)

### Want Premium Quality?
Use Claude for deep research:
```bash
BEDROCK_CHAT_MODEL=anthropic.claude-3-5-sonnet-20241022-v2:0
```
**Cost:** +$4/month for deep research

### Want Maximum Performance?
Use Nova 2 Pro (latest generation):
```bash
BEDROCK_CHAT_MODEL=amazon.nova-2-pro-v1:0
BEDROCK_REFINEMENT_MODEL=amazon.nova-2-lite-v1:0
```

## 🔧 Testing Your Setup

### Test Each Feature

```bash
# Test Bedrock connection
python test_bedrock_setup.py

# Test AI Chat (uses Nova Pro)
curl -X POST http://localhost:8010/api/ai-chat/query \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"query": "Test", "mode": "quick"}'

# Test AI Refinement (uses Nova Lite)
curl -X POST http://localhost:8010/api/ai-refinement/analyze \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"project_id": "YOUR_PROJECT_ID"}'

# Test AI Orchestrator (uses Nova Lite)
curl -X GET http://localhost:8010/ai/orchestrator/analyze/dataset \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## 📊 Model Comparison

| Model | Speed | Quality | Cost | Best For |
|-------|-------|---------|------|----------|
| Nova Micro | ⚡⚡⚡ | ⭐⭐⭐ | $ | Quick searches |
| Nova Lite | ⚡⚡ | ⭐⭐⭐⭐ | $$ | **Default choice** |
| Nova Pro | ⚡ | ⭐⭐⭐⭐⭐ | $$$ | Deep analysis |
| Nova 2 Pro | ⚡ | ⭐⭐⭐⭐⭐ | $$$ | Latest generation |
| Claude 3.5 | ⚡ | ⭐⭐⭐⭐⭐ | $$$$ | Premium legal |
| Titan v2 | ⚡⚡⚡ | N/A | $ | Embeddings only |

## 🎯 Feature-Specific Recommendations

### AI Chat/Copilot
**Current:** Nova Pro ($0.80/1M)  
**Alternative:** Claude 3.5 Sonnet for premium legal analysis ($3.00/1M)  
**Budget:** Nova Lite for cost savings ($0.06/1M)

### AI Refinement
**Current:** Nova Lite ($0.06/1M) ✅ **Optimal**  
**Alternative:** Nova Micro for faster processing ($0.035/1M)

### AI Orchestrator
**Current:** Nova Lite ($0.06/1M) ✅ **Optimal**  
**Alternative:** Nova Pro for deeper insights ($0.80/1M)

### Quick Search
**Current:** Nova Micro ($0.035/1M) ✅ **Optimal**  
**Alternative:** Nova Lite for better quality ($0.06/1M)

## ✅ Next Steps

1. **Test your setup** (models auto-enable on first use):
   ```bash
   python test_bedrock_setup.py
   ```

2. **Start using VeriCase with Bedrock:**
   ```bash
   docker-compose up
   ```

3. **Monitor costs:**
   - AWS Cost Explorer: https://console.aws.amazon.com/cost-management/
   - Set up billing alerts for peace of mind

**Note:** Bedrock models are now **automatically enabled** when first invoked. No manual activation needed! 🎉

## 🎉 You're Ready!

Your VeriCase platform now has:
- ✅ Optimal Bedrock models for each AI feature
- ✅ Cost-effective routing (~$1.71/month for typical usage)
- ✅ Automatic fallback to other providers
- ✅ Premium quality when needed

**Estimated savings vs Claude-only: $13.29/month (88% cheaper)** 🚀

---

**Questions?** Check:
- Quick Start: `BEDROCK_QUICK_START.md`
- Full Setup: `BEDROCK_SETUP.md`
- Integration Summary: `BEDROCK_INTEGRATION_SUMMARY.md`
