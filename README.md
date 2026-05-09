# hermes-model-pricing

Fetch live LLM pricing from provider APIs, diff against Hermes's hardcoded rates, and list available models.

---

## What This Is

Hermes Agent hardcodes model pricing in `agent/usage_pricing.py`. Providers change rates occasionally and run promos (e.g. DeepSeek's 75%-off V4-Pro until May 31, 2026). This repo provides:

1. **`fetch_pricing.py`** — Probe live provider APIs, show current rates, and diff against what Hermes is using
2. **`list_models.py`** — List all available models from a provider (catalog browser)
3. **`references/pricing-sources.md`** — Audit of each provider's pricing API: what's public, what's auth-gated, and known quirks

---

## Quick Start

```bash
# Clone
git clone https://github.com/underdown/hermes-model-pricing.git
cd hermes-model-pricing

# Install deps (the scripts only need requests)
pip install requests

# Fetch all live pricing
python scripts/fetch_pricing.py

# Diff against Hermes's hardcoded rates
python scripts/fetch_pricing.py --diff

# List all NVIDIA NIM models
python scripts/list_models.py --provider nvidia

# List OpenRouter models, search for DeepSeek
python scripts/list_models.py --provider openrouter --search deepseek

# List OpenRouter models sorted by price
python scripts/list_models.py --provider openrouter --sort price
```

---

## `fetch_pricing.py`

```
usage: fetch_pricing.py [-h] [--provider {all,deepseek,openrouter,nvidia}]
                        [--diff]

Fetch live LLM pricing from provider APIs and diff against Hermes usage_pricing.py.

Options:
  --provider {all,deepseek,openrouter,nvidia}
                        Which provider(s) to fetch (default: all)
  --diff, -d            Compare fetched pricing against hardcoded rates
```

**Output example:**

```
╔══════════════════════════════════════════════════════════════════════════╗
║  PROVIDER PRICING SNAPSHOT — 2026-05-09 10:00 UTC                        ║
╠══════════════════════════════════════════════════════════════════════════╣
║  MODEL                             INPUT/M    OUTPUT/M   CACHE HIT/M  PROMO ║
║  ─────────────────────────────────────────────────────────────────────── ║
║  deepseek-v4-flash                  $0.1400    $0.2800     $0.0028         ║
║  deepseek-v4-pro                    $0.4350    $0.8700     $0.0036  75% off║
║  openai/gpt-4.1                     $2.0000    $8.0000        N/A         ║
╚══════════════════════════════════════════════════════════════════════════╝
```

**With `--diff`:**

```
⚠️  deepseek/deepseek-v4-pro:
      input:  $0.4350/M (hardcoded) → $0.4350/M (live)   ✓ match
      output: $0.8700/M (hardcoded) → $0.8700/M (live)   ✓ match
      ⚠️  promo expires 2026-05-31 — post-promo: $1.74/M input, $3.48/M output
```

---

## `list_models.py`

```
usage: list_models.py [-h] --provider {nvidia,openrouter,deepseek}
                      [--search SEARCH] [--sort {default,price,ctx}]
                      [--base-url URL] [--api-key KEY]

Options:
  --provider, -p       Provider: nvidia, openrouter, deepseek (required)
  --search, -s         Filter models containing string (case-insensitive)
  --sort               Sort: default (alpha), price (cheapest input first), ctx (largest context)
  --base-url           Custom OpenAI-compatible endpoint (with --api-key)
  --api-key            API key for custom endpoint
```

**Supported providers:**

| Provider | Pricing | Auth Required |
|----------|---------|---------------|
| `nvidia` | No (IDs only) | No |
| `openrouter` | Yes | No |
| `deepseek` | Yes (from docs HTML) | No |

---

## Data Sources

See `references/pricing-sources.md` for the full audit. Summary:

| Provider | Pricing Source | Status |
|----------|---------------|--------|
| OpenRouter | `GET /api/v1/models` | ✅ Public, no auth, full pricing |
| DeepSeek | `https://api-docs.deepseek.com/quick_start/pricing` | ✅ Public HTML, no auth |
| NVIDIA NIM | `GET /v1/models` | ⚠️ Public but **no pricing** returned |
| xAI | — | ❌ No public pricing found |
| Anthropic | Platform docs page | ✅ Public HTML |
| OpenAI | API pricing page | ✅ Public HTML |

**DeepSeek promo alert:** V4-Pro is 75% off until 2026-05-31 15:59 UTC. Post-promo rates: $1.74/M input, $3.48/M output. Run `--diff` before then to check.

---

## Requirements

- Python 3.10+
- `requests`

```bash
pip install requests
```

---

## File Structure

```
hermes-model-pricing/
├── README.md
├── LICENSE
├── scripts/
│   ├── fetch_pricing.py     # Live pricing fetcher + diff
│   └── list_models.py        # Model catalog browser
└── references/
    └── pricing-sources.md    # Provider API audit
```

---

## Updating Hermes Pricing

If `--diff` shows a discrepancy:

1. Edit `~/.hermes/hermes-agent/agent/usage_pricing.py`
2. Find `_OFFICIAL_DOCS_PRICING`
3. Update the affected `PricingEntry` values
4. Restart Hermes Agent

> **Note:** This repo does **not** auto-modify Hermes source. Manual review before updating is required.

---

## License

MIT — Ryan Underdown
