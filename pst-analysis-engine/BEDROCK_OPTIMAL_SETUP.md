# Bedrock Optimal Setup for VeriCase

## ✅ Configuration Applied

Your `.env` is now configured with the optimal Bedrock setup:

```bash
# Default model: Nova Lite (best balance of speed/quality/cost)
BEDROCK_DEFAULT_MODEL=amazon.nova-lite-v1:0

# Embeddings: Titan v2 (semantic search)
BEDROCK_EMBEDDING_MODEL=amazon.titan-embed-text-v2:0

# Task-specific routing:
BEDROCK_CLASSIFICATION_MODEL=amazon.nova-micro-v1:0      # Fast, cheap
BEDROCK_ANALYSIS_MODEL=amazon.nova-lite-v1:0             # Balanced
BEDROCK_PREMIUM_MODEL=anthropic.claude-3-5-sonnet-20241022-v2:0  # Premium
```

## 🎯 Model Strategy

### Nova Micro ($0.035/1M tokens)
**Use for:**
- Document classification
- Simple tagging
- Quick categorization
- High-volume batch processing

### Nova Lite ($0.06/1M tokens) ⭐ **DEFAULT**
**Use for:**
- Document summaries
- Key point extraction
- General analysis
- Dataset insights
- Most day-to-day tasks

### Claude 3.5 Sonnet ($3.00/1M tokens)
**Use for:**
- Complex legal analysis
- Contract review
- Critical decisions
- High-stakes documents

### Titan Embeddings v2 ($0.02/1M tokens)
**Use for:**
- Semantic search
- Document similarity
- Clustering
- Vector database

## 💰 Cost Optimization

### Estimated Monthly Costs (1000 documents/month)

| Task | Model | Tokens | Cost |
|------|-------|--------|------|
| Classification (1000 docs × 500 tokens) | Nova Micro | 0.5M | $0.02 |
| Summaries (1000 docs × 2000 tokens) | Nova Lite | 2M | $0.24 |
| Embeddings (1000 docs × 1000 tokens) | Titan v2 | 1M | $0.02 |
| **Total** | | | **$0.28/month** |

### If using Claude for everything:
- Same workload: **$10.50/month** (37x more expensive)

## 🚀 Enable Model Access

**One-time setup:**

1. Go to: https://eu-west-2.console.aws.amazon.com/bedrock/home?region=eu-west-2#/modelaccess
2. Click **"Modify model access"**
3. Enable these models:
   - ✅ **Amazon Nova** (all variants) - Instant approval
   - ✅ **Amazon Titan Embeddings v2** - Instant approval
   - ✅ **Anthropic Claude 3.5 Sonnet** - May require approval (1-2 days)

4. Click **"Save changes"**

## 📝 Usage Examples

### Use Default Model (Nova Lite)
```python
from api.app.ai_providers import BedrockProvider

provider = BedrockProvider()
response = await provider.invoke(
    model_id=os.getenv("BEDROCK_DEFAULT_MODEL"),
    prompt="Summarize this document..."
)
```

### Task-Specific Routing
```python
# Fast classification
classification = await provider.invoke(
    model_id=os.getenv("BEDROCK_CLASSIFICATION_MODEL"),
    prompt="Classify this document type..."
)

# Detailed analysis
analysis = await provider.invoke(
    model_id=os.getenv("BEDROCK_ANALYSIS_MODEL"),
    prompt="Extract key points and themes..."
)

# Premium legal review
review = await provider.invoke(
    model_id=os.getenv("BEDROCK_PREMIUM_MODEL"),
    prompt="Analyze this contract for legal risks..."
)
```

### Semantic Search
```python
# Generate embeddings
embeddings = await provider.get_embeddings(
    text=document_text,
    model_id=os.getenv("BEDROCK_EMBEDDING_MODEL")
)
```

## 🎛️ Fine-Tuning Parameters

### For Classification (Speed Priority)
```python
response = await provider.invoke(
    model_id="amazon.nova-micro-v1:0",
    prompt="Classify: contract/email/report",
    max_tokens=50,        # Short response
    temperature=0.1       # Deterministic
)
```

### For Analysis (Quality Priority)
```python
response = await provider.invoke(
    model_id="amazon.nova-lite-v1:0",
    prompt="Analyze key themes...",
    max_tokens=1000,      # Detailed response
    temperature=0.7       # Creative
)
```

### For Legal Review (Maximum Quality)
```python
response = await provider.invoke(
    model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
    prompt="Review contract obligations...",
    max_tokens=2000,      # Comprehensive
    temperature=0.3       # Balanced
)
```

## 📊 Performance Benchmarks

| Model | Speed | Quality | Cost | Best For |
|-------|-------|---------|------|----------|
| Nova Micro | ⚡⚡⚡ | ⭐⭐⭐ | 💰 | High volume |
| Nova Lite | ⚡⚡ | ⭐⭐⭐⭐ | 💰💰 | **Default** |
| Nova Pro | ⚡ | ⭐⭐⭐⭐⭐ | 💰💰💰 | Complex tasks |
| Claude 3.5 | ⚡ | ⭐⭐⭐⭐⭐ | 💰💰💰💰 | Premium |

## ✅ Verification

Test your setup:
```powershell
python test_bedrock_setup.py
```

Should show:
- ✅ Connection successful
- ✅ All models available
- ✅ Region: eu-west-2

## 🎉 You're Ready!

Your VeriCase platform now has:
- ✅ Optimal model selection
- ✅ Cost-effective routing
- ✅ Premium quality when needed
- ✅ Fast processing for high volume

**Estimated cost: $0.28/month for 1000 documents** 🚀
