#!/usr/bin/env python3
"""
List all available models from a provider's API, including capabilities and pricing.

Usage:
  python list_models.py --provider nvidia
  python list_models.py --provider openrouter --search deepseek
  python list_models.py --provider nvidia --search llama
  python list_models.py --provider groq
  python list_models.py --provider together
  python list_models.py --provider openrouter --sort price  # sort by cheapest input

Providers:
  nvidia      - NVIDIA NIM catalog (public /models endpoint, no pricing)
  openrouter  - OpenRouter (full pricing + context length from models API)
  deepseek    - DeepSeek (from pricing docs page)
  groq        - Groq (hardcoded rates from public pricing page)
  together    - Together AI (hardcoded rates from docs)
  all         - All providers combined
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

PRICE_MAP = {
    "nvidia": "NVIDIA NIM (free/usage-based)",
    "deepseek": "deepseek platform",
    "openrouter": "openrouter",
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google",
    "xai": "xai",
    "minimax": "minimax",
}


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_nvidia() -> list[dict]:
    """NVIDIA NIM — public /models, no auth needed. No pricing returned."""
    resp = requests.get("https://integrate.api.nvidia.com/v1/models", timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", [])


def fetch_openrouter(search: str = "") -> list[dict]:
    """OpenRouter — public /models API with full pricing."""
    resp = requests.get("https://openrouter.ai/api/v1/models", timeout=30)
    resp.raise_for_status()
    data = resp.json()
    models = data.get("data", [])
    if search:
        search_l = search.lower()
        models = [m for m in models if search_l in m.get("id", "").lower() or search_l in m.get("name", "").lower()]
    return models


def fetch_deepseek() -> list[dict]:
    """DeepSeek — from pricing page HTML."""
    resp = requests.get("https://api-docs.deepseek.com/quick_start/pricing", timeout=15)
    resp.raise_for_status()
    html = resp.text

    td_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
    cells = [re.sub(r"<[^>]+>", "", td).strip() for td in td_pattern.findall(html)]
    cells = [c for c in cells if c]

    models = [
        {
            "id": cells[1].replace("(1)", ""),
            "owned_by": "deepseek",
            "version": cells[8],
            "context_length": 1_000_000,
            "pricing": {
                "input_per_million": 0.14,
                "output_per_million": 0.28,
                "cache_hit_per_million": 0.0028,
            },
            "promo": None,
        },
        {
            "id": cells[2],
            "owned_by": "deepseek",
            "version": cells[9],
            "context_length": 1_000_000,
            "pricing": {
                "input_per_million": 0.435,
                "output_per_million": 0.87,
                "cache_hit_per_million": 0.003625,
            },
            "promo": "75% off until 2026-05-31",
        },
    ]
    return models


def fetch_groq_models() -> list[dict]:
    """Groq — hardcoded from groq.com/pricing (May 2026). No public models API."""
    rates = {
        "llama-3.1-8b-instruct":            {"input": 0.05, "output": 0.08, "ctx": 131072},
        "llama-3.3-70b-versatile":          {"input": 0.59, "output": 0.79, "ctx": 131072},
        "meta-llama/llama-4-scout-17b-16e-instruct": {"input": 0.11, "output": 0.34, "ctx": 131072},
        "qwen/qwen3-32b":                   {"input": 0.29, "output": 0.59, "ctx": 131072},
        "openai/gpt-oss-120b":              {"input": 0.15, "output": 0.60, "ctx": 131072, "cache": 0.0375},
        "openai/gpt-oss-20b":               {"input": 0.075, "output": 0.30, "ctx": 131072, "cache": 0.0375},
    }
    return [
        {
            "id": k,
            "owned_by": "groq",
            "context_length": v["ctx"],
            "pricing": {
                "input_per_million": v["input"],
                "output_per_million": v["output"],
                "cache_hit_per_million": v.get("cache"),
            },
            "promo": "",
        }
        for k, v in rates.items()
    ]


def fetch_together_models() -> list[dict]:
    """Together AI — hardcoded from docs.together.ai/docs/inference-models (May 2026)."""
    rates = {
        "deepseek-ai/DeepSeek-V4-Pro":           {"input": 2.10, "output": 4.40, "ctx": 512000},
        "moonshotai/Kimi-K2.6":                   {"input": 1.20, "output": 4.50, "ctx": 262144},
        "moonshotai/Kimi-K2.5":                   {"input": 0.50, "output": 2.80, "ctx": 262144},
        "MiniMaxAI/MiniMax-M2.7":                 {"input": 0.30, "output": 1.20, "ctx": 202752, "cache": 0.06},
        "Qwen/Qwen3.5-9B":                        {"input": 0.10, "output": 0.15, "ctx": 262144},
        "Qwen/Qwen3.6-Plus":                       {"input": 0.50, "output": 3.00, "ctx": 1000000},
        "openai/gpt-oss-120b":                     {"input": 0.15, "output": 0.60, "ctx": 128000},
        "openai/gpt-oss-20b":                      {"input": 0.05, "output": 0.20, "ctx": 128000},
        "meta-llama/Llama-3.3-70B-Instruct-Turbo": {"input": 0.88, "output": 0.88, "ctx": 131072},
        "google/gemma-4-31B-it":                   {"input": 0.20, "output": 0.50, "ctx": 262144},
    }
    return [
        {
            "id": k,
            "owned_by": "together",
            "context_length": v["ctx"],
            "pricing": {
                "input_per_million": v["input"],
                "output_per_million": v["output"],
                "cache_hit_per_million": v.get("cache"),
            },
            "promo": "",
        }
        for k, v in rates.items()
    ]


def fetch_endpoint(base_url: str, api_key: str = "") -> list[dict]:
    """Generic OpenAI-compatible /models endpoint."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    resp = requests.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", [])


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _fmt_price(val) -> str:
    if val is None:
        return "     -"
    try:
        return f"${float(val):>6.4f}"
    except (TypeError, ValueError):
        return "     -"


def _fmt_ctx(val) -> str:
    if val is None:
        return "     -"
    try:
        v = int(val)
        if v >= 1_000_000:
            return f"{v/1_000_000:.0f}M"
        if v >= 1_000:
            return f"{v//1_000}K"
        return str(v)
    except (TypeError, ValueError):
        return "     -"


def display(models: list[dict], provider: str, sort_by: str = "default") -> None:
    if not models:
        print("No models found.")
        return

    # Extract pricing per model
    rows: list[dict] = []
    for m in models:
        pricing = m.get("pricing", {}) or {}

        # OpenRouter: pricing.prompt/completion are per-token, multiply by 1M
        input_p = pricing.get("prompt") or pricing.get("input_per_million")
        output_p = pricing.get("completion") or pricing.get("output_per_million")
        cache_p = pricing.get("cache_read") or pricing.get("cache_hit_per_million")

        # Convert per-token to per-million if needed
        def _to_per_million(val):
            if val is None:
                return None
            try:
                d = float(val)
                if d < 0.001:  # looks like per-token, not per-million
                    return d * 1_000_000
                return d
            except (TypeError, ValueError):
                return None

        rows.append({
            "id": m.get("id", "?"),
            "ctx": m.get("context_length"),
            "input": _to_per_million(input_p),
            "output": _to_per_million(output_p),
            "cache": _to_per_million(cache_p),
            "owned_by": m.get("owned_by", ""),
            "promo": m.get("promo", ""),
        })

    # Sort
    if sort_by == "price":
        rows.sort(key=lambda r: r["input"] if r["input"] is not None else 9999)
    elif sort_by == "ctx":
        rows.sort(key=lambda r: -(r["ctx"] or 0))
    # default: alphabetical

    print(f"\n{'─' * 100}")
    print(f"  {provider.upper()} — {len(rows)} models — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'─' * 100}")
    print(f"  {'MODEL ID':<45s} {'CTX':>6s} {'INPUT/M':>10s} {'OUTPUT/M':>10s} {'CACHE/M':>10s} {'OWNER':<15s}")
    print(f"  {'─' * 97}")

    for r in rows:
        display_id = r["id"]
        if len(display_id) > 43:
            display_id = display_id[:41] + ".."
        promo_flag = " ⚡" if r["promo"] else ""
        print(
            f"  {display_id:<45s} "
            f"{_fmt_ctx(r['ctx']):>6s} "
            f"{_fmt_price(r['input']):>10s} "
            f"{_fmt_price(r['output']):>10s} "
            f"{_fmt_price(r['cache']):>10s} "
            f"{r['owned_by'][:14]:<15s}"
            f"{promo_flag}"
        )

    print(f"  {'─' * 97}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="List available models from a provider")
    parser.add_argument("--provider", "-p", required=True,
                        help="Provider: nvidia, openrouter, deepseek, groq, together")
    parser.add_argument("--search", "-s", help="Filter models containing this string (case-insensitive)")
    parser.add_argument("--sort", choices=["default", "price", "ctx"], default="default", help="Sort order")
    parser.add_argument("--base-url", help="Custom base URL for generic OpenAI-compatible endpoint")
    parser.add_argument("--api-key", help="API key for custom endpoint", default="")
    args = parser.parse_args()

    provider = args.provider.lower()

    try:
        if provider == "nvidia":
            models = fetch_nvidia()
        elif provider == "openrouter":
            models = fetch_openrouter(search=args.search or "")
        elif provider == "deepseek":
            models = fetch_deepseek()
        elif provider == "groq":
            models = fetch_groq_models()
        elif provider == "together":
            models = fetch_together_models()
        elif args.base_url:
            models = fetch_endpoint(args.base_url, args.api_key or "")
        else:
            print(f"Unknown provider: {provider}")
            print("Supported: nvidia, openrouter, deepseek, groq, together")
            print("For others, use --base-url with --api-key")
            sys.exit(1)
    except Exception as e:
        print(f"Error fetching {provider}: {e}")
        sys.exit(1)

    # Filter by search string if provided
    if args.search and provider not in ("openrouter",):
        search_l = args.search.lower()
        models = [m for m in models if search_l in m.get("id", "").lower()]

    display(models, provider, sort_by=args.sort)


if __name__ == "__main__":
    main()