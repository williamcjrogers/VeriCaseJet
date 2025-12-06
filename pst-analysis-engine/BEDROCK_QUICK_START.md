# Amazon Bedrock - Quick Start

## 🚀 Setup (5 minutes)

### 1. Configure AWS Credentials

```bash
aws configure
```

Enter:
- AWS Access Key ID
- AWS Secret Access Key  
- Default region: `eu-west-2`

### 2. Install Dependencies

```bash
pip install boto3
```

### 3. Test Connection

```bash
python test_bedrock_setup.py
```

### 4. Enable in .env

```bash
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
BEDROCK_DEFAULT_MODEL=amazon.nova-micro-v1:0
AWS_REGION=eu-west-2
```

## 📝 Basic Usage

```python
from api.app.ai_providers import BedrockProvider

# Initialize
provider = BedrockProvider(region="eu-west-2")

# Simple query
response = await provider.invoke(
    model_id="amazon.nova-micro-v1:0",
    prompt="Summarize this document...",
    max_tokens=1000
)
```

## 🎯 Model Selection

| Model | Best For | Cost |
|-------|----------|------|
| `amazon.nova-micro-v1:0` | Simple tasks, high volume | $ |
| `amazon.nova-lite-v1:0` | Balanced performance | $$ |
| `amazon.nova-pro-v1:0` | Complex analysis | $$$ |
| `anthropic.claude-3-5-sonnet-20241022-v2:0` | Premium quality | $$$$ |

## 🔧 Common Tasks

### Document Classification
```python
from api.app.bedrock_integration_example import BedrockDocumentAnalyzer

analyzer = BedrockDocumentAnalyzer()
result = await analyzer.classify_document(text)
```

### Extract Key Points
```python
points = await analyzer.extract_key_points(text, max_points=5)
```

### Generate Summary
```python
summary = await analyzer.summarize_document(text, max_length=200)
```

### Get Embeddings
```python
embeddings = await provider.get_embeddings(text)
```

## 🛠️ Troubleshooting

### "No credentials found"
```bash
aws configure
# or add to .env:
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
```

### "Access denied"
1. Go to AWS Console → Bedrock → Model access
2. Request access to models
3. Wait for approval (instant for Nova)

### "Model not found"
- Check model ID spelling
- Verify model access in console
- Ensure region supports model

## 📚 Resources

- **Full Guide:** `BEDROCK_SETUP.md`
- **Examples:** `api/app/bedrock_integration_example.py`
- **Test Script:** `test_bedrock_setup.py`
- **Setup Script:** `setup-bedrock.ps1`

## ✅ Checklist

- [ ] AWS credentials configured
- [ ] boto3 installed
- [ ] Test script passes
- [ ] Model access enabled
- [ ] .env updated
- [ ] AI features enabled

## 🎉 You're Ready!

Start using Bedrock in your VeriCase application!

```bash
# Run full setup
.\setup-bedrock.ps1

# Start application
docker-compose up
```
