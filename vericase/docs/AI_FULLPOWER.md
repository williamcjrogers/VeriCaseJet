# 🚀 VeriCase AI Full Power Mode

Enable **every AI capability** — all 6 providers, all features, all routing modes.

---

## Quick Start

```bash
# 1) Copy the full-power template
cp .env.ai-fullpower.example .env

# 2) Add your API keys to .env
#    (OpenAI, Anthropic, Gemini, xAI, Perplexity, and optionally AWS credentials)

# 3) Start Docker stack
docker compose up -d --build

# 4) Open UI
#    http://localhost:8010/ui/dashboard.html
```

---

## Providers Enabled

| Provider       | Default Model               | Use Case                             |
|----------------|-----------------------------|--------------------------------------|
| **OpenAI**     | `gpt-4o` / `gpt-5.2-*`      | General reasoning, embeddings        |
| **Anthropic**  | `claude-sonnet-4-*`         | Deep analysis, long context          |
| **Gemini**     | `gemini-2.5-pro/flash`      | Multi-modal, huge docs (1M tokens)   |
| **Bedrock**    | `amazon.nova-pro-v1:0`      | Cost-optimized, Claude via AWS       |
| **xAI / Grok** | `grok-4.1-fast`             | 2M context, cheapest premium         |
| **Perplexity** | `sonar` / `sonar-pro`       | Real-time web search, citations      |

---

## Feature Flags

| Flag                              | Default | Description                              |
|-----------------------------------|---------|------------------------------------------|
| `ENABLE_AI_AUTO_CLASSIFY`         | `true`  | Auto-classify document types             |
| `ENABLE_AI_DATASET_INSIGHTS`      | `true`  | AI-generated dataset summaries           |
| `ENABLE_AI_NATURAL_LANGUAGE_QUERY`| `true`  | NL search across evidence                |
| `AI_WEB_ACCESS_ENABLED`           | `true`  | Allow AI to search the web (Perplexity)  |
| `AI_TASK_COMPLEXITY_DEFAULT`      | `advanced` | basic / moderate / deep_research / advanced |

---

## Routing & Fallback

| Flag                      | Default     | Description                                     |
|---------------------------|-------------|-------------------------------------------------|
| `AI_FALLBACK_ENABLED`     | `true`      | Auto-failover to next provider on error         |
| `AI_ROUTING_STRATEGY`     | `balanced`  | performance / cost / latency / quality / balanced |
| `AI_PREFER_BEDROCK`       | `true`      | Prioritize Bedrock for cost savings             |
| `BEDROCK_ROUTE_CLAUDE`    | `true`      | Route Claude calls through Bedrock              |
| `AI_ENABLE_MULTI_MODEL`   | `false`     | Parallel multi-model execution                  |
| `AI_ENABLE_VALIDATION`    | `true`      | Second model validates first model output       |

---

## AWS AI Services

| Flag                 | Default | Description                             |
|----------------------|---------|-----------------------------------------|
| `USE_TEXTRACT`       | `true`  | OCR via AWS Textract                    |
| `USE_COMPREHEND`     | `true`  | NLP entity extraction                   |
| `USE_KNOWLEDGE_BASE` | `true`  | Bedrock RAG knowledge base              |
| `MACIE_ENABLED`      | `true`  | Sensitive data scanning                 |
| `MULTI_VECTOR_ENABLED`| `true` | 4-vector semantic search                |

---

## Obtaining API Keys

| Provider       | Console URL                                  |
|----------------|----------------------------------------------|
| OpenAI         | https://platform.openai.com/api-keys         |
| Anthropic      | https://console.anthropic.com/settings/keys  |
| Google Gemini  | https://aistudio.google.com/app/apikey       |
| xAI (Grok)     | https://console.x.ai/                        |
| Perplexity     | https://www.perplexity.ai/settings/api       |
| AWS Bedrock    | Uses IAM credentials (no API key)            |

---

## Production Security

1. **Never commit real keys.** Use `.env.ai-fullpower.example` as template.
2. **Use AWS Secrets Manager** in production:
   ```bash
   AWS_SECRETS_MANAGER_AI_KEYS=vericase/ai-api-keys
   ```
3. **Rotate keys** regularly (see `AI_KEY_MANAGEMENT.md`).
4. **Use IAM roles** (IRSA/instance profile) instead of access keys.

---

## Files Reference

| File                           | Purpose                            |
|--------------------------------|------------------------------------|
| `.env.ai-fullpower.example`    | Full-power env template            |
| `AI_KEY_MANAGEMENT.md`         | Key rotation and Secrets Manager   |
| `docs/AI_CONFIGURATION_GUIDE.md`| Detailed AI setup instructions    |
| `docs/AI.md`                   | Model comparison and pricing       |
| `api/app/config.py`            | Env var definitions                |
| `api/app/ai_settings.py`       | Runtime settings & routing         |
| `api/app/ai_runtime.py`        | Provider execution logic           |
| `api/app/ai_fallback.py`       | Fallback chain definitions         |
| `api/app/ai_router.py`         | Adaptive routing engine            |
| `api/app/ai_models_2025.py`    | Model registry (Dec 2025)          |

---

## Troubleshooting

| Symptom                        | Fix                                                 |
|--------------------------------|-----------------------------------------------------|
| "API key not configured"       | Set key in `.env` or Secrets Manager                |
| Bedrock calls fail             | `BEDROCK_ENABLED=true`, valid IAM credentials       |
| Perplexity/Grok not working    | Add `PERPLEXITY_API_KEY` / `XAI_API_KEY` to `.env`  |
| Fallback not triggering        | Set `AI_FALLBACK_ENABLED=true`                      |
| Claude going to Bedrock        | `BEDROCK_ROUTE_CLAUDE=true` routes via AWS Bedrock  |

---

🎉 **You're now running VeriCase at full AI power!**
