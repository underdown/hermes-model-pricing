# hermes-model-pricing

Live LLM pricing plugin for Hermes Agent — scrapes provider APIs and pricing pages, caches for 24 hours, enriches token logs with real costs, and exposes slash commands on Discord and Telegram.

---

## What This Is

A Hermes Gateway plugin that fetches current model pricing from public provider pages and APIs. Replaces hardcoded rates in `agent/usage_pricing.py` with live data that refreshes once per day. Optionally enriches your `token-logger` CSV output with actual cost attribution.

### Changelog

**v1.2.0**
- **Added Nous Portal** — 410 models, no API key, per-1M pricing with cache read/write and `:batch` aliases.
- **Fixed silent pricing failures on routed calls** — `custom:<provider>` prefixes now resolve instead of returning `None`. This was under-reporting *live* cost, not just history.
- **Fixed enricher blindness to same-day rows** — it globbed only `*.csv.gz`, but the logger writes plain `.csv` for today and compresses only on nightly archive. Same-day costs were never enriched at all.
- **Fixed float artifacts in scaled prices** — `0.0000002 × 1e6` landed as `0.19999999999999998` in cache; now quantised to 6dp.
- **Consolidated the provider list** — it existed in three divergent copies; `/models` was missing four providers. Single `PROVIDERS` tuple now, with slash-command hints derived from it.
- **Replaced the expired-promo section with a Known Gaps table.**

On a representative day this moved 60 rows from `$0` to real prices and roughly doubled attributed spend ($0.25 → $0.59) — the earlier figure was an undercount, not a spend drop.

**Supported providers:**

| Provider | Source | Auth Required | Status |
|----------|--------|:---:|:---:|
| OpenRouter | `/api/v1/models` | No | ✅ Live pricing |
| Nous Portal | `/v1/models` | No | ✅ Live pricing |
| DeepSeek | api-docs HTML scrape | No | ✅ Live pricing |
| Fireworks | docs.fireworks.ai HTML | No | ✅ Live pricing |
| Together AI | `/api/v1/models` | No | ✅ Live pricing |
| Mistral | Hardcoded fallback | No | 📋 Static rates |
| Cohere | Hardcoded fallback | No | 📋 Static rates |
| MiniMax | Hardcoded fallback | No | 📋 Static rates |
| Groq | groq.com/pricing HTML | No | ⚠️ Stale — unverified |
| NVIDIA NIM | `/api/v1/models` | No | ⚠️ Model IDs only (no pricing) |

### Nous Portal

The Nous Portal (`https://inference-api.nousresearch.com/v1/models`) serves
pricing for ~410 LLMs with no API key required. It returns per-token costs as
`input_cost`, `output_cost`, `cache_read_cost`, and `cache_write_cost`; this
plugin scales all four to per-1M by 1e6 and quantises to 6dp.

It is the richest unauthenticated source in the set — it carries first-party
rates for Anthropic, OpenAI, DeepSeek, Qwen, GLM and others, often *lower* than
the same model's OpenRouter rate, plus `:batch` and `-latest` aliases the other
sources don't list. Notably it reports `stealth/space-bunny-alpha` at $0.

Embedding, rerank, and audio models (`voyageai/*`, `sentence-transformers/*`,
`amazon/*`, `cohere-embed/*`) are filtered out — their prices are per-unit
rather than per-token and would corrupt the 1M scaling.

```bash
/pricing nous        # live table
/models nous claude  # 33 Anthropic models incl. :batch variants
```

> **Note:** `cache_write_cost` is captured but not yet used in cost math —
> `_compute_cost` consumes input, output, and cache-read only. Treat
> cache-write-heavy workloads as slightly undercounted.

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
/pricing              → all 10 cached providers
/pricing deepseek     → DeepSeek only
/pricing nous         → Nous Portal (410 models)
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
├── pricing_module.py       # Scrapers, cache, data models, 10 provider fetchers
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

- **OpenRouter / Together / NVIDIA / Nous:** Call public REST APIs (JSON), no HTML parsing. Nous needs no key and is scaled from per-token to per-1M (see [Nous Portal](#nous-portal))
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

#### Routing-prefix stripping (v1.2.0)

Hermes config routes some calls through `custom:<provider>` — e.g. an OpenAI-
compatible gateway configured as `custom:openrouter`. `get_pricing_entry()`
now strips that prefix and retries on the bare provider, so routed calls
resolve instead of silently returning `None`. This affected **live** cost
logging, not just historical files.

#### Both file formats

The enricher originally globbed only `*.csv.gz`. The token logger writes a
plain `.csv` for the current day and only compresses it on nightly archive, so
the enricher was structurally unable to see same-day rows. It now matches both
`.csv` and `.csv.gz` and preserves each file's format on write-back instead of
gzipping a file the archiver still expects to find.

> **Note:** the enricher runs daily on *existing* files. It will not retroactively
> reprice history written before a provider was added — use `--recalculate` for that.

---

## Cron Jobs

| Job | Schedule | What it does |
|-----|----------|--------------|
| `pricing-cache-daily` | `0 8 * * *` | Pre-warms pricing cache at 08:00 |
| `enrich-token-logs-daily` | `0 9 * * *` | Enriches yesterday's token logs with costs |
| `weekly-pricing-diff-report` | `0 10 * * 1` | Posts pricing changes to Discord `#general` (Mondays) |
| `monthly-token-spend-report` | `0 8 1 * *` | Posts monthly spend breakdown to Discord `#general` |

> The `deepseek-promo-expiry-alert` one-shot job has fired and been removed —
> that promo expired 2026-05-31. See [Known Gaps](#known-gaps).

Cron definitions live in `~/.hermes/cron/jobs.json`. Wrapper scripts in `scripts/`.

---

## Known Gaps

Honest list of what is **not** working, so nobody trusts a number they shouldn't:

| Gap | Impact |
|-----|--------|
| `cache_write_cost` unused in cost math | Cache-write-heavy runs are slightly undercounted. Input/output/cache-read are correct. |
| Groq scraper unverified | `groq.com/pricing` layout changed; figures may be stale. No prices have been confirmed against it. |
| NVIDIA NIM has no prices | Model IDs only. Anything routed through NIM resolves to `$0`, not to its real cost. |
| No retroactive repricing | Adding a provider only affects files enriched after that point. |
| DeepSeek promo expired | The V4-Pro 75%-off promo ended 2026-05-31. The static fallback table in `scripts/list_models.py` still carries promo rates and has **not** been reverted to list price. |

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