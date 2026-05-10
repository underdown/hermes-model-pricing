# hermes-model-pricing

Live LLM pricing plugin for Hermes Agent — scrapes provider APIs and pricing pages, caches for 24 hours, enriches token logs with real costs, and exposes slash commands on Discord and Telegram.

---

## What This Is

A Hermes Gateway plugin that fetches current model pricing from public provider pages and APIs. Replaces hardcoded rates in `agent/usage_pricing.py` with live data that refreshes once per day. Optionally enriches your `token-logger` CSV output with actual cost attribution.

**Supported providers:**

| Provider | Source | Auth Required | Status |
|----------|--------|:---:|:---:|
| OpenRouter | `/api/v1/models` | No | ✅ Live pricing |
| DeepSeek | api-docs HTML scrape | No | ✅ Live pricing |
| Groq | groq.com/pricing HTML | No | ✅ Live pricing |
| Fireworks | docs.fireworks.ai HTML | No | ✅ Live pricing |
| Together AI | `/api/v1/models` | No | ✅ Live pricing |
| NVIDIA NIM | `/api/v1/models` | No | ⚠️ Model IDs only (no pricing) |
| Mistral | Hardcoded fallback | No | 📋 Static rates |
| Cohere | Hardcoded fallback | No | 📋 Static rates |
| MiniMax | Hardcoded fallback | No | 📋 Static rates |

---

## Quick Start

### As a Hermes Plugin (recommended)

```bash
cp -r hermes-model-pricing/ ~/.hermes/plugins/pricing-tools/
```

Ensure `pricing-tools` is listed in `~/.hermes/config.yaml`:

```yaml
plugins:
  - pricing-tools
```

Restart Hermes Agent and Gateway:

```bash
systemctl --user restart hermes-agent
systemctl --user restart hermes-gateway
```

### Optional: Token Logger Enrichment

To automatically fill `$0.0000` cost rows in your token-logger CSVs with live pricing from the cache, add the enrichment cron job (see [Cron Jobs](#cron-jobs) below). This runs daily and back-fills costs using a 5-strategy cross-provider matcher.

---

## Commands

### `/pricing [provider]`
Fetch current pricing for one or all providers.

```
/pricing              → all 9 cached providers
/pricing deepseek     → DeepSeek only
/pricing openrouter   → OpenRouter only
```

### `/models [provider] [--search filter] [--sort price]`
List available models, optionally filtered and sorted.

```
/models                    → all providers
/models openrouter         → OpenRouter only
/models openrouter gpt     → OpenRouter, filtered by "gpt"
/models openrouter deepseek --sort price
```

### `/enrich_logs [--days 7] [--recalculate]`
Enriches token-logger CSV files with live cost data from the pricing cache. Reads CSVs from `~/.hermes/token_logs/`, matches model IDs using a 5-strategy resolver, and rewrites the `cost_usd` column.

```
/enrich_logs                    → enrich last 7 days
/enrich_logs --days 30          → enrich last 30 days
/enrich_logs --recalculate      → re-enrich already-enriched rows
```

### `/compare_models model='<name>'`
Cross-provider price comparison for a given model name. Searches all cached providers and returns a sorted table.

```
/compare_models model='deepseek'
```

---

## Architecture

```
hermes-model-pricing/
├── __init__.py             # Plugin entry: registers commands + tools
├── plugin.yaml             # Hermes plugin manifest
├── pricing_module.py       # Scrapers, cache, data models, 9 provider fetchers
├── enrich_logs.py          # Token-log enrichment pipeline (optional integration)
├── weekly_report.py        # Weekly pricing diff report
├── monthly_spend_report.py # Monthly token spend attribution
├── pricing_cache.json      # 24h cache (auto-generated, ~557 rate pairs)
├── README.md
├── LICENSE
├── scripts/
│   ├── fetch_pricing.py    # CLI: fetch/refresh pricing cache, --diff mode
│   └── list_models.py      # CLI: list models per provider
└── references/
    └── pricing-sources.md  # Provider API audit notes
```

### Caching (`pricing_module.py`)

- **Cache location:** `~/.hermes/plugins/pricing-tools/pricing_cache.json`
- **TTL:** 24 hours from first fetch
- **Behavior:** First call after cache expiry fetches live; subsequent calls read from disk
- **Pre-warm cron job:** Daily at 08:00 (see below)

### Scraper Details

- **OpenRouter / Together / NVIDIA:** Call public REST APIs (JSON), no HTML parsing
- **DeepSeek:** Parse pricing table from `api-docs.deepseek.com/quick_start/pricing` — handles `CACHE HIT` vs `CACHE MISS` vs `OUTPUT` rows
- **Groq:** Parse table from `groq.com/pricing` — extracts only `$`-prefixed amounts
- **Fireworks:** Parse table from `docs.fireworks.ai/serverless/pricing` — splits `input / cache / output` cells
- **Mistral / Cohere / MiniMax:** Hardcoded fallbacks (their pages aren't reliably scrapeable)

### Enrichment Pipeline (`enrich_logs.py`)

Reads token-logger CSVs and fills the `cost_usd` column using a 5-strategy resolver:

1. **Exact match** — `(provider, model_id)` tuple lookup
2. **Bare prefix strip** — strip `provider/` prefix, match on model name
3. **Owner-clean normalize** — normalize `owner/model` format across providers
4. **Cross-provider bare match** — search all providers for bare model name
5. **Full string match** — fallback substring search

This handles NVIDIA routing DeepSeek/MiniMax models under `owner/model` IDs, OpenRouter's free models, and edge cases like CACHE HIT vs CACHE MISS rows.

---

## Cron Jobs

| Job | Schedule | What it does |
|-----|----------|--------------|
| `pricing-cache-daily` | `0 8 * * *` | Pre-warms pricing cache at 08:00 |
| `enrich-token-logs-daily` | `0 9 * * *` | Enriches yesterday's token logs with costs |
| `weekly-pricing-diff-report` | `0 10 * * 1` | Posts pricing changes to Discord `#general` (Mondays) |
| `monthly-token-spend-report` | `0 8 1 * *` | Posts monthly spend breakdown to Discord `#general` |
| `deepseek-promo-expiry-alert` | May 29, 2026 9:00 AM | Warns about May 31 promo deadline |

Cron definitions live in `~/.hermes/cron/jobs.json`. Wrapper scripts in `scripts/`.

---

## DeepSeek Promo Tracking

V4-Pro currently has a **75% discount until 2026-05-31**.

- Promo rates: $0.435/M input, $0.87/M output, $0.003625/M cache hit
- Post-promo rates: $1.74/M input, $3.48/M output (update `pricing_module.py` after expiry)
- Cron alert scheduled for **May 29** (2 days before expiry)

---

## Updating Hermes Hardcoded Pricing

If `fetch_pricing --diff` shows a discrepancy between live and hardcoded rates:

1. Edit `~/.hermes/hermes-agent/agent/usage_pricing.py`
2. Find `_OFFICIAL_DOCS_PRICING`
3. Update the affected `PricingEntry` values
4. Restart Hermes Agent

> **Note:** This plugin does **not** auto-modify Hermes source. Manual review before updating is required.

---

## Requirements

- Python 3.10+
- `requests`

```bash
pip install requests
```

---

## License

MIT — Ryan Underdown