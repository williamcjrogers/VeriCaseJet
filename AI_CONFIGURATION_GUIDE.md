# VeriCase AI Configuration Guide

## Overview
VeriCase includes advanced AI features powered by multiple AI models:
- **OpenAI GPT** - For general intelligence and chronology building
- **Anthropic Claude** - For detailed document analysis
- **Google Gemini** - For multi-modal processing
- **Grok** - For fast reasoning
- **Perplexity** - For web search and fact-checking

## Security Update
The API keys have been removed from `apprunner.yaml` for security. They now need to be configured in AWS Secrets Manager.

## Setup Instructions

### Step 1: Run Configuration Script
```powershell
# Run the provided PowerShell script
.\configure-ai-secrets.ps1
```

This script will:
1. Create a secret in AWS Secrets Manager named `vericase/ai-api-keys`
2. Set up IAM permissions for App Runner to access the secret
3. Configure your App Runner service to load keys at runtime

### Step 2: Add Your API Keys
1. Go to [AWS Secrets Manager Console](https://console.aws.amazon.com/secretsmanager)
2. Find the secret: `vericase/ai-api-keys`
3. Click "Retrieve secret value"
4. Click "Edit" 
5. Replace the placeholder values with your actual API keys:
   ```json
   {
     "OPENAI_API_KEY": "sk-proj-YOUR-ACTUAL-KEY",
     "ANTHROPIC_API_KEY": "sk-ant-YOUR-ACTUAL-KEY", 
     "GEMINI_API_KEY": "AIzaSy-YOUR-ACTUAL-KEY",
     "GROK_API_KEY": "xai-YOUR-ACTUAL-KEY",
     "PERPLEXITY_API_KEY": "pplx-YOUR-ACTUAL-KEY"
   }
   ```
6. Save the secret

### Step 3: Get API Keys

#### OpenAI (Required for core AI features)
1. Go to https://platform.openai.com/api-keys
2. Create a new API key
3. Copy the key starting with `sk-proj-`

#### Anthropic Claude (Optional)
1. Go to https://console.anthropic.com/
2. Create an API key
3. Copy the key starting with `sk-ant-`

#### Google Gemini (Optional)
1. Go to https://makersuite.google.com/app/apikey
2. Create an API key
3. Copy the key starting with `AIzaSy`

#### Grok (Optional)
1. Go to https://console.x.ai/
2. Create an API key
3. Copy the key starting with `xai-`

#### Perplexity (Optional)
1. Go to https://www.perplexity.ai/settings/api
2. Create an API key
3. Copy the key starting with `pplx-`

### Step 4: Deploy Changes
The changes to `apprunner.yaml` and `main.py` need to be deployed:
```bash
git add .
git commit -m "Configure AI API keys with AWS Secrets Manager"
git push
```

## Features Enabled by AI

### 1. AI-Powered Refinement Wizard
- Automatically discovers projects, people, and topics in uploaded PST files
- Suggests exclusions and filters
- Located at: `/ui-direct/refinement-wizard.html`

### 2. AI Chat Assistant
- Multi-model deep research for evidence analysis
- Chronology building
- API endpoint: `/api/ai-chat`

### 3. Intelligent Configuration
- Smart project setup suggestions
- Auto-classification of documents
- API endpoint: `/api/intelligent-config`

## Troubleshooting

### Check if AI Keys are Loaded
Visit: `https://YOUR-APP-URL/api/docs`
- Look for AI endpoints
- Test the endpoints to see if they return proper responses

### View Logs
In App Runner console, check application logs for:
- "Loading AI API keys from AWS Secrets Manager"
- "✓ Loaded OPENAI_API_KEY from Secrets Manager"

### Common Issues
1. **403 Forbidden on Secrets Manager**: The IAM role needs the policy attached
2. **AI features not working**: Check if the API keys are valid and have credits
3. **Deployment not picking up changes**: Make sure to push to GitHub and trigger deployment

## Cost Management
- OpenAI: Set usage limits at https://platform.openai.com/usage
- Monitor API usage regularly
- Consider using GPT-3.5-turbo for development/testing

## Next Steps
After configuration:
1. Test the refinement wizard with a PST upload
2. Try the AI chat features
3. Monitor usage and costs
