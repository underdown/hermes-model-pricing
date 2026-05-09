# hermes-model-pricing

Live LLM pricing plugin for Hermes Agent — scrapes provider APIs and pricing pages, caches for 24 hours, and exposes `/pricing` and `/models` slash commands on Discord and Telegram.

---

## What This Is

A Hermes Gateway plugin that fetches current model pricing from public provider pages and APIs. Replaces hardcoded rates in `agent/usage_pricing.py` with live data that refreshes once per day.

**Supported providers:**

| Provider | Source | Auth Required | Scraped? |
|----------|--------|:---:|:---:|
| OpenRouter | `/api/v1/models` | No | ✅ Live |
| DeepSeek | api-docs HTML | No | ✅ Live |
| Groq | groq.com/pricing HTML | No | ✅ Live |
| Fireworks | docs.fireworks.ai HTML | No | ✅ Live |
| Together | `/api/v1/models` | No | ✅ Live |
| NVIDIA NIM | `/api/v1/models` | No | ✅ Live (names only) |
| Mistral | — | — | 📋 Hardcoded fallback |
| Cohere | — | — | 📋 Hardcoded fallback |
| MiniMax | — | — | 📋 Hardcoded fallback |

---

## Quick Start

### As a Hermes Plugin (recommended)

Copy the plugin directory into your Hermes plugins folder:

```bash
cp -r hermes-model-pricing/ ~/.hermes/plugins/pricing-tools/
```

Ensure `pricing-tools` is listed in `~/.hermes/config.yaml` under `plugins:`:

```yaml
plugins:
  - pricing-tools
```

Restart Hermes Agent:

```bash
systemctl --user restart hermes-agent   # CLI
systemctl --user restart hermes-gateway # Gateway (for slash commands)
```

That's it. The plugin will:
1. Register `/pricing` and `/models` as gateway slash commands
2. Fetch live pricing on first call and cache to disk for 24 hours
3. Auto-register all providers found in `COMMAND_REGISTRY` — no manual config needed

### Commands

**`/pricing [provider]`** — Fetch current pricing for one or all providers.

```
/pricing              → all providers
/pricing deepseek     → DeepSeek only
/pricing openrouter   → OpenRouter only
```

**`/models [provider]`** — List available models.

```
/models                    → all providers
/models openrouter         → OpenRouter only
/models openrouter gpt     → OpenRouter, filtered by "gpt"
/models openrouter deepseek --sort price
```

---

## Architecture

```
hermes-model-pricing/
├── __init__.py             # Plugin entry: registers commands + tools
├── plugin.yaml             # Hermes plugin manifest
├── pricing_module.py       # Scrapers, cache, data models
├── README.md
├── LICENSE
└── references/
    └── pricing-sources.md   # Provider API audit
```

### Caching (`pricing_module.py`)

- **Cache location:** `~/.hermes/plugins/pricing-tools/pricing_cache.json`
- **TTL:** 24 hours from first fetch
- **Behavior:** First call after cache expiry fetches live; subsequent calls read from disk
- **Pre-warm cron job:** A daily job (`pricing-cache-daily`) runs at 08:00 to refresh the cache before users ask

### Scraper Details

- **OpenRouter / Together / NVIDIA:** Call public REST APIs (JSON), no HTML parsing
- **DeepSeek:** Parse pricing `<table>` from `api-docs.deepseek.com/quick_start/pricing` — handles `CACHE HIT` vs `CACHE MISS` vs `OUTPUT` rows and `(1)` suffixes in column headers
- **Groq:** Parse `<table>` from `groq.com/pricing` — extracts only `$`-prefixed amounts to avoid model size numbers (`20B`, `128k`)
- **Fireworks:** Parse `<table>` from `docs.fireworks.ai/serverless/pricing` — splits `input / cache / output` slash-delimited cells
- **Mistral / Cohere / MiniMax:** Hardcoded fallbacks (their pages aren't reliably scrapeable)

---

## Updating Hermes Hardcoded Pricing

If `--diff` shows a discrepancy between live and hardcoded rates:

1. Edit `~/.hermes/hermes-agent/agent/usage_pricing.py`
2. Find `_OFFICIAL_DOCS_PRICING`
3. Update the affected `PricingEntry` values
4. Restart Hermes Agent

> **Note:** This plugin does **not** auto-modify Hermes source. Manual review before updating is required.

---

## DeepSeek Promo Tracking

V4-Pro currently has a **75% discount until 2026-05-31**. This is hardcoded in the scraper and will need updating after expiry. Post-promo rates: $1.74/M input, $3.48/M output.

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