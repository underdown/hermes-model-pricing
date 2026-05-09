# Provider Pricing Sources — May 2026

This file documents where each LLM provider exposes pricing data, which paths are auth-gated, and known quirks. Used by `fetch_pricing.py` and for manual price verification.

---

## Quick Summary

| Provider | Pricing Source | Auth | Priority |
|----------|---------------|------|----------|
| OpenRouter | `GET /api/v1/models` | No | ✅ Already done |
| DeepSeek | docs HTML | No | ✅ Already done |
| NVIDIA NIM | `GET /v1/models` (IDs only) | No | ✅ Already done |
| Groq | `groq.com/pricing` HTML | No | 🔴 Add this |
| Fireworks AI | `docs.fireworks.ai/serverless/pricing` | No | 🔴 Add this |
| Together AI | `docs.together.ai/docs/inference-models` | No | 🔴 Add this |
| Mistral | `mistral.ai/pricing` HTML | No | 🔴 Add this |
| Cohere | `cohere.com/pricing` HTML | No | 🟡 Scrape, model list needs key |
| HuggingFace | `huggingface.co/pricing` | No | 🟡 Partial |
| Anthropic | Platform docs page | No | ✅ In pricing dict |
| OpenAI | `openai.com/api/pricing/` | No | ✅ In pricing dict |
| Google AI | `ai.google.dev/pricing` | No | ✅ In pricing dict |
| xAI | — | — | ❌ No public pricing |
| Azure Foundry | Enterprise | — | ❌ Per-deployment |
| Ollama Cloud | Self-hosted style | — | ❌ No fixed pricing |

---

## OpenRouter

**Models API:** `GET https://openrouter.ai/api/v1/models`
- Status: **200, open, no auth required**
- Returns: model IDs, `context_length`, `pricing` object with `prompt`/`completion` per-token rates
- Cached in `_model_metadata_cache` for 1 hour in `agent/model_metadata.py`
- **Already integrated in `fetch_pricing.py`**

---

## DeepSeek

**Models API:** `GET https://api.deepseek.com/v1/models`
- Status: **401 without valid API key**

**Public pricing page:** `https://api-docs.deepseek.com/quick_start/pricing`
- Status: **200, public, no auth required**
- Format: Docusaurus HTML — pricing in `<table>` elements
- **Already integrated in `fetch_pricing.py`**
- Rates (as of May 2026):

| Model | Input (cache miss) | Output | Cache hit |
|-------|-------------------|--------|-----------|
| deepseek-v4-flash | $0.14/M | $0.28/M | $0.0028/M |
| deepseek-v4-pro | $0.435/M | $0.87/M | $0.003625/M |

> ⚠️ V4-Pro promo pricing ends **2026/05/31 15:59 UTC**. Post-promo: input → $1.74/M, output → $3.48/M.

---

## NVIDIA NIM

**Models API:** `GET https://integrate.api.nvidia.com/v1/models`
- Status: **200, open, no auth required**
- Returns: model IDs, `owned_by`, `created` — **no pricing fields**
- **Already integrated in `fetch_pricing.py`** (model IDs only, no pricing)

---

## Groq

**Models API:** `GET https://api.groq.com/openai/v1/models`
- Status: **401 without API key**

**Public pricing page:** `https://groq.com/pricing`
- Status: **200, public, no auth**
- Format: HTML table with per-model pricing
- Key rates (May 2026):

| Model | Input /M | Output /M | Context |
|-------|---------|---------|---------|
| llama-3.1-8b-instant | $0.05 | $0.08 | 131K |
| llama-3.3-70b-versatile | $0.59 | $0.79 | 131K |
| llama-4-scout-17b-16e | $0.11 | $0.34 | 131K |
| qwen3-32b | $0.29 | $0.59 | 131K |
| openai/gpt-oss-120b | $0.15 | $0.60 | 131K |
| openai/gpt-oss-20b | $0.075 | $0.30 | 131K |

**Prompt caching:** cache_read for gpt-oss models: $0.0375/M (50% of input)

---

## Fireworks AI

**API:** Requires key — `https://api.fireworks.ai/v1/models` auth-gated

**Public docs:** `https://docs.fireworks.ai/serverless/pricing`
- Status: **200, public, no auth**
- Format: Structured pricing table (input / cached input / output per 1M tokens)
- Key rates (Standard tier, May 2026):

| Model | Input /M | Cache Hit /M | Output /M |
|-------|---------|------------|----------|
| DeepSeek V4 Pro | $1.74 | $0.145 | $3.48 |
| Kimi K2.6 | $0.95 | $0.16 | $4.00 |
| Kimi K2.5 | $0.60 | $0.10 | $3.00 |
| GLM 5.1 | $1.40 | $0.26 | $4.40 |
| MiniMax 2.7 | $0.30 | $0.06 | $1.20 |
| Qwen3 VL 30B A3B | $0.15 | $0.075 | $0.60 |
| OpenAI GPT-OSS 120B | $0.15 | $0.015 | $0.60 |
| OpenAI GPT-OSS 20B | $0.07 | $0.035 | $0.30 |

> Note: Post-promo DeepSeek V4 Pro rates: $1.74/$3.48/M input/output.

---

## Together AI

**API:** Requires key — `https://api.together.ai/v1/models` auth-gated

**Public docs:** `https://docs.together.ai/docs/inference-models`
- Status: **200, public, no auth**
- Format: Structured table with org, model name, API string, context, input/output pricing
- Key rates (Serverless, May 2026):

| Model | API String | Context | Input /M | Output /M |
|-------|-----------|---------|---------|---------|
| DeepSeek V4 Pro | deepseek-ai/DeepSeek-V4-Pro | 512K | $2.10 | $4.40 |
| Kimi K2.6 | moonshotai/Kimi-K2.6 | 262K | $1.20 | $4.50 |
| Kimi K2.5 | moonshotai/Kimi-K2.5 | 262K | $0.50 | $2.80 |
| MiniMax M2.7 | MiniMaxAI/MiniMax-M2.7 | 202K | $0.30 | $1.20 |
| GLM-5.1 | zai-org/GLM-5.1 | 202K | $1.40 | $4.40 |
| Qwen3.5 9B | Qwen/Qwen3.5-9B | 262K | $0.10 | $0.15 |
| Qwen3.6-Plus | Qwen/Qwen3.6-Plus | 1M | $0.50 | $3.00 |
| OpenAI GPT-OSS 120B | openai/gpt-oss-120b | 128K | $0.15 | $0.60 |
| OpenAI GPT-OSS 20B | openai/gpt-oss-20b | 128K | $0.05 | $0.20 |
| Llama 3.3 70B | meta-llama/Llama-3.3-70B-Instruct-Turbo | 131K | $0.88 | $0.88 |
| Gemma 4 31B | google/gemma-4-31B-it | 262K | $0.20 | $0.50 |

> Note: Cached input available for some models (e.g. MiniMax M2.7: $0.06/M cached).

---

## Mistral AI

**API:** Requires key — `GET https://api.mistral.ai/v1/models`

**Public pricing page:** `https://mistral.ai/pricing`
- Status: **200, public, no auth**
- Format: Interactive page — structured data available via docs
- Key rates from docs (May 2026):

| Model | API ID | Input /M | Output /M | Context |
|-------|--------|---------|---------|---------|
| Mistral Small 4 | mistral-small-latest | ~$0.10 | ~$0.30 | 131K |
| Mistral Medium 3.5 | mistral-medium-latest | ~$1.50 | ~$4.00 | 131K |
| Mistral Large 3 | mistral-large-latest | ~$2.00 | ~$8.00 | 131K |
| Codestral | codestral-latest | ~$0.50 | ~$1.00 | 131K |

> Note: Mistral pricing page is interactive/react-based — HTML scraping may be fragile. Consider hardcoding known rates and verifying quarterly.

---

## Cohere

**API:** Requires key — `GET https://api.cohere.ai/v1/models`

**Public pricing page:** `https://cohere.com/pricing`
- Status: **200, public, no auth**
- Key rates (May 2026):

| Model | Input /M | Output /M | Context |
|-------|---------|---------|---------|
| Command A | command-a-03-2025 | $0.50 | $1.50 | 256K |
| Command R+ 08-2024 | command-r-plus-08-2024 | $2.50 | $10.00 | 128K |
| Command R 03-2024 | command-r-03-2024 | $0.50 | $1.50 | 128K |
| Aya Expanse 8B | aya-expanse-8b | $0.50 | $1.50 | 256K |
| Aya Expanse 32B | aya-expanse-32b | $0.50 | $1.50 | 256K |

---

## HuggingFace

**Inference API:** `https://api-inference.huggingface.co/models` — requires token

**Public pricing page:** `https://huggingface.co/pricing`
- Status: **200, public**
- HF inference is pay-as-you-go. Rate depends on model size and hardware. Not easily scraped — consider hardcoding common models.

---

## xAI / Grok

**API:** `GET https://api.x.ai/v1/models`
- Status: **400 bad key** (requires valid key)

**Pricing page:** No public pricing page found.

**Conclusion:** ❌ xAI does not expose pricing via API or public docs. Cost estimation falls back to `unknown`.

---

## Adding a New Provider to fetch_pricing.py

1. Add entry to this file with API status and pricing page URL
2. In `fetch_pricing.py`, add a `fetch_<provider>()` function
3. Prefer open APIs (no auth) where available:
   - OpenRouter `/api/v1/models` — full pricing, no auth ✅
   - NVIDIA `/v1/models` — IDs only, no pricing ⚠️
   - Most others require scraping public HTML pages
4. If scraping HTML, use `requests` + `re` (no BeautifulSoup needed):
   ```python
   resp = requests.get(url, timeout=15, headers={"User-Agent": "Hermes-Pricing/1.0"})
   # parse with td_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
   ```
5. Test and verify before relying on it
6. Update this file with findings