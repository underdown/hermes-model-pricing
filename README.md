# hermes-model-pricing

Live pricing fetcher + model catalog for LLM providers used by Hermes Agent.

**What it does:**
- Fetches current per-token rates from DeepSeek, OpenRouter, and NVIDIA NIM
- Compares live rates against Hermes's hardcoded `usage_pricing.py`
- Alerts if promo pricing is about to expire
- Lists all available models from a provider

**Scripts:**

```bash
# Fetch live pricing from all providers
python scripts/fetch_pricing.py

# Diff against hardcoded rates in Hermes
python scripts/fetch_pricing.py --diff

# List models from a specific provider
python scripts/list_models.py --provider nvidia
python scripts/list_models.py --provider openrouter --search deepseek
```

**Files:**
- `scripts/fetch_pricing.py` — main pricing fetcher + diff tool
- `scripts/list_models.py` — model catalog lister
- `references/pricing-sources.md` — provider API status + known quirks

**Requirements:** `requests`, `decimal` (stdlib)

---

## Data Sources

| Provider | Pricing API | Auth Required |
|----------|------------|---------------|
| OpenRouter | `GET /api/v1/models` | No |
| DeepSeek | Public docs HTML | No |
| NVIDIA NIM | `GET /v1/models` (IDs only) | No |
| xAI | None found | — |
| Anthropic | Docs page | No |
| OpenAI | Docs page | No |

See `references/pricing-sources.md` for full details.
