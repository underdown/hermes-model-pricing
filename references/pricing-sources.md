# Provider Pricing Sources — May 2026

This file documents where each LLM provider exposes pricing data, which paths are auth-gated, and the known quirks. Used by `fetch_pricing.py` and for manual price verification.

---

## DeepSeek

**Models API:** `GET https://api.deepseek.com/v1/models`
- Status: **401 without valid API key**
- With key: returns model list but pricing fields unclear (requires paid key to probe)

**Public pricing page:** `https://api-docs.deepseek.com/quick_start/pricing`
- Status: **200, public, no auth required**
- Format: Docusaurus HTML — pricing in `<table>` elements
- Content extracted via `web_extract` (no BeautifulSoup needed in hermes-agent venv)
- Rates (as of May 2026):

| Model | Input (cache hit) | Input (cache miss) | Output |
|---|---|---|---|
| deepseek-v4-flash | $0.0028/M | $0.14/M | $0.28/M |
| deepseek-v4-pro | $0.003625/M | $0.435/M | $0.87/M |

> ⚠️ V4-Pro/V4-Flash promo pricing ends **2026/05/31 15:59 UTC**. Post-promo: input miss → $1.74/M, output → $3.48/M. Update `_OFFICIAL_DOCS_PRICING` before then.

**Billing API:** No public billing/usage REST API found (DeepSeek dashboard is web-only).

---

## NVIDIA NIM

**Models API:** `GET https://integrate.api.nvidia.com/v1/models`
- Status: **200, open, no auth required**
- Returns: model IDs, `owned_by`, `created` — **no pricing fields**
- Sample response:
```json
{"object":"list","data":[
  {"id":"01-ai/yi-large","object":"model","created":735790403,"owned_by":"01-ai"},
  ...
]}
```

**Pricing page:** `https://build.nvidia.com/explore/discover`
- Status: 200, HTML only — no structured pricing API found
- Pricing is visible on the website but requires scraping

**Conclusion:** NVIDIA NIM does not expose per-token pricing via API. Cost estimation falls back to `unknown` for all NIM models.

---

## xAI / Grok

**Models API:** `GET https://api.x.ai/v1/models`
- Status: **400 bad key** (requires valid key — no public access)
- Error: `"Incorrect API key provided"`

**Pricing page:** No public pricing page found.

**Conclusion:** xAI does not expose pricing via API or public docs. Cost estimation falls back to `unknown`.

---

## OpenRouter

**Models API:** `GET https://openrouter.ai/api/v1/models`
- Status: **200, open, no auth required**
- Returns: model IDs, `context_length`, **and `pricing` object** with `prompt`/`completion` per-token rates
- Cached in `_model_metadata_cache` for 1 hour in `agent/model_metadata.py`
- Already integrated — no action needed

---

## OpenAI

**Models API:** `GET https://api.openai.com/v1/models`
- Status: **401 without key** (auth required even for model list)

**Public pricing page:** `https://openai.com/api/pricing/`
- Status: 200, public, no auth
- Format: HTML with `<table>` elements (Docusaurus?)

---

## Anthropic

**Models API:** `GET https://api.anthropic.com/v1/models`
- Status: **401 without key**

**Public pricing page:** `https://platform.anthropic.com/en/docs/about-claude/pricing`
- Status: 200, public, no auth
- Format: HTML with pricing tables
- Already has entries in `_OFFICIAL_DOCS_PRICING` — update manually when pricing changes

---

## Google AI (Gemini)

**Models API:** `GET https://generativelanguage.googleapis.com/v1beta/models` (unverified)
- Likely requires API key

**Public pricing page:** `https://ai.google.dev/pricing`
- Status: 200, public, no auth
- Format: HTML tables

---

## MiniMax

**Models API:** `GET https://api.minimax.chat/v1/models`
- Status: **200, open, no auth**
- But: `"data": []` — empty model list (either staged rollout or auth required for full list)

**Public pricing page:** `https://platform.minimax.io/docs` — not confirmed public
- Known pricing (from `_OFFICIAL_DOCS_PRICING`): minimax-m2.7 → $0.30/M input, $1.20/M output

---

## Scripts

### `fetch_pricing.py` — Fetch and diff provider pricing

Located at: `~/.hermes/scripts/fetch_pricing.py`

**Purpose:** Probe each provider's pricing source, compare against hardcoded `_OFFICIAL_DOCS_PRICING`, and report any discrepancies.

**Usage:**
```bash
# Run all providers
python ~/.hermes/scripts/fetch_pricing.py

# Run specific provider
python ~/.hermes/scripts/fetch_pricing.py --provider deepseek

# Show diff only (no prompt to update)
python ~/.hermes/scripts/fetch_pricing.py --diff-only

# Force refresh OpenRouter cache
python ~/.hermes/scripts/fetch_pricing.py --refresh-openrouter
```

**Design decisions:**
- Web scraping via `web_extract` tool (no BeautifulSoup needed — hermes-agent has this tool)
- Fallback to `requests` for APIs that don't need auth
- Writes diff output to stdout — user decides whether to update
- Does NOT auto-update `_OFFICIAL_DOCS_PRICING` (too risky to auto-modify source)
- DeepSeek is prioritized since its promo ends May 31

**Expected output format:**
```
fetch_pricing — provider pricing audit
  last checked: 2026-05-08

  deepseek/deepseek-v4-pro
    input:  $0.435/M  (hardcoded)  vs  $0.435/M  (live)   ✓ match
    output: $0.87/M   (hardcoded)  vs  $0.87/M   (live)   ✓ match
    ⚠️  promo expires 2026-05-31 — post-promo: $1.74/$3.48

  openai/gpt-4.1
    input:  $2.00/M   (hardcoded)  vs  $2.00/M   (live)   ✓ match

  nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
    ⚠️  no pricing data found in NVIDIA NIM /models API
    status: cost will show as unknown
```

---

## Adding a New Provider

1. Add entry to the provider table above with API status and pricing page URL
2. In `fetch_pricing.py`, add a `fetch_<provider>_pricing()` function
3. If the provider has a public pricing page, prefer `web_extract` over `requests` (avoids auth/SSL issues)
4. Test with `--diff-only` and verify it produces correct output before relying on it
5. Update this file with findings