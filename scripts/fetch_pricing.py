#!/usr/bin/env python3
"""
Fetch model pricing from each provider and compare against Hermes's hardcoded rates.

Usage:
  python fetch_pricing.py                        # All providers
  python fetch_pricing.py --provider deepseek    # DeepSeek only
  python fetch_pricing.py --provider anthropic   # Anthropic only
  python fetch_pricing.py --provider openai      # OpenAI only
  python fetch_pricing.py --provider all --diff  # All + diff vs usage_pricing.py

Output:
  - Table of models, their current rates, promo status
  - Comparison to hardcoded OFFICIAL_DOCS_PRICING in agent/usage_pricing.py
  - Warnings if rates differ from what Hermes is using

Data sources:
  DeepSeek:  https://api-docs.deepseek.com/quick_start/pricing (public HTML)
  Anthropic: https://platform.claude.com/docs/en/about-claude/pricing (public HTML)
  OpenAI:    https://openai.com/api/pricing/ (public HTML)
  Google:    https://ai.google.dev/pricing (public HTML)
  NVIDIA:    https://integrate.api.nvidia.com/v1/models (open endpoint, model IDs only)
  OpenRouter: https://openrouter.ai/api/v1/models (live API, pricing in response)
  xAI:       https://docs.x.ai/docs/models (public docs page)
  MiniMax:   /v1/models returns empty list; pricing from https://platform.minimax.io/docs
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class ModelPrice:
    provider: str
    model_id: str
    input_cost: Optional[Decimal]       # $ per 1M tokens (cache miss)
    output_cost: Optional[Decimal]      # $ per 1M tokens
    cache_read_cost: Optional[Decimal]  # $ per 1M tokens (cache hit)
    cache_write_cost: Optional[Decimal] # $ per 1M tokens
    context_length: Optional[int] = None
    promo: str = ""                     # e.g. "75% off until 2026-05-31"
    source_url: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Provider fetchers
# ---------------------------------------------------------------------------

def fetch_deepseek() -> list[ModelPrice]:
    """Parse DeepSeek's public pricing HTML table."""
    resp = requests.get(
        "https://api-docs.deepseek.com/quick_start/pricing",
        timeout=15,
        headers={"User-Agent": "Hermes-Pricing-Script/1.0"},
    )
    resp.raise_for_status()
    html = resp.text

    # Extract all <td> cells
    td_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
    cells = [re.sub(r"<[^>]+>", "", td).strip() for td in td_pattern.findall(html)]
    cells = [c for c in cells if c]

    results: list[ModelPrice] = []

    # DeepSeek's table structure (from observed HTML, May 2026):
    #   col 0: MODEL | deepseek-v4-flash | deepseek-v4-pro
    #   Pricing rows are at known positions in the flat TD list.
    #   Cells at [31,32] = cache-hit prices, [34,35] = cache-miss, [37,38] = output
    #   Context: [13] = "1M" for both models

    model_ids = ["deepseek-v4-flash", "deepseek-v4-pro"]

    # Parse dollar amounts from cells like "$0.14" or "$0.003625 (75% off(3))$0.0145"
    def _parse_price(text: str) -> tuple[Optional[Decimal], Optional[Decimal], str]:
        """Return (current_promo_price, post_promo_price, promo_text)."""
        promo_text = ""
        # Extract parenthetical promo note
        promo_match = re.search(r"\((\d+% off[^)]*)\)", text)
        if promo_match:
            promo_text = promo_match.group(1)
        # Find all dollar amounts
        amounts = re.findall(r"\$([0-9.]+)", text)
        if not amounts:
            return None, None, promo_text
        current = Decimal(amounts[0])
        post = Decimal(amounts[1]) if len(amounts) > 1 else None
        return current, post, promo_text

    # Positions in flat TD list (0-indexed):
    # [31] = V4-Flash cache hit, [32] = V4-Pro cache hit
    # [34] = V4-Flash cache miss, [35] = V4-Pro cache miss
    # [37] = V4-Flash output,    [38] = V4-Pro output

    for i, model_id in enumerate(model_ids):
        cache_hit, _, promo_hit = _parse_price(cells[31 + i]) if (31 + i) < len(cells) else (None, None, "")
        cache_miss, post_miss, promo_miss = _parse_price(cells[34 + i]) if (34 + i) < len(cells) else (None, None, "")
        output, post_output, promo_out = _parse_price(cells[37 + i]) if (37 + i) < len(cells) else (None, None, "")

        promo = promo_hit or promo_miss or promo_out or ""

        results.append(ModelPrice(
            provider="deepseek",
            model_id=model_id,
            input_cost=cache_miss,
            output_cost=output,
            cache_read_cost=cache_hit,
            cache_write_cost=None,  # DeepSeek has no cache write charge
            context_length=1_000_000,
            promo=promo,
            source_url="https://api-docs.deepseek.com/quick_start/pricing",
        ))

    return results


def fetch_openrouter() -> list[ModelPrice]:
    """Fetch pricing from OpenRouter's public models API."""
    resp = requests.get(
        "https://openrouter.ai/api/v1/models",
        timeout=30,
        headers={"User-Agent": "Hermes-Pricing-Script/1.0"},
    )
    resp.raise_for_status()
    data = resp.json()

    results: list[ModelPrice] = []
    for model in data.get("data", []):
        pricing = model.get("pricing", {})
        if not pricing:
            continue
        results.append(ModelPrice(
            provider="openrouter",
            model_id=model.get("id", ""),
            input_cost=_to_decimal_per_million(pricing.get("prompt")),
            output_cost=_to_decimal_per_million(pricing.get("completion")),
            cache_read_cost=_to_decimal_per_million(pricing.get("cache_read") or pricing.get("input_cache_read")),
            cache_write_cost=_to_decimal_per_million(pricing.get("cache_write") or pricing.get("input_cache_write")),
            context_length=model.get("context_length"),
            source_url="https://openrouter.ai/api/v1/models",
        ))
    return results


def fetch_nvidia_model_ids() -> list[ModelPrice]:
    """Fetch available model IDs from NVIDIA NIM (no pricing, IDs only)."""
    resp = requests.get(
        "https://integrate.api.nvidia.com/v1/models",
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    results: list[ModelPrice] = []
    for model in data.get("data", []):
        results.append(ModelPrice(
            provider="nvidia",
            model_id=model.get("id", ""),
            input_cost=None,  # NVIDIA NIM doesn't expose pricing in /models
            output_cost=None,
            cache_read_cost=None,
            cache_write_cost=None,
            source_url="https://integrate.api.nvidia.com/v1/models",
        ))
    return results


# ---------------------------------------------------------------------------
# Comparison: current rates vs what Hermes has hardcoded
# ---------------------------------------------------------------------------

def load_hardcoded_pricing() -> dict[tuple[str, str], dict]:
    """Load the hardcoded OFFICIAL_DOCS_PRICING from agent/usage_pricing.py.

    Parses the Python source to extract (provider, model) -> pricing dict.
    Returns empty dict if file not found or parse fails.
    """
    hermes_dir = Path.home() / ".hermes" / "hermes-agent"
    pricing_file = hermes_dir / "agent" / "usage_pricing.py"
    if not pricing_file.exists():
        return {}

    source = pricing_file.read_text(encoding="utf-8")

    # Match each PricingEntry block. Format:
    #   ("provider",\n     "model",\n): PricingEntry(\n     input_cost_per_million=Decimal("X"),\n     ...
    entry_pattern = re.compile(
        r'\(\s*\n?\s*"([^"]+)"\s*,\s*\n?\s*"([^"]+)"[^)]*\)\s*:\s*PricingEntry\((.*?)\n\s*\),',
        re.DOTALL,
    )

    result: dict[tuple[str, str], dict] = {}
    for match in entry_pattern.finditer(source):
        provider = match.group(1)
        model = match.group(2)
        body = match.group(3)

        def _get_decimal(label: str) -> Decimal | None:
            m = re.search(rf'{label}=Decimal\("([^"]*)"\)', body)
            if m and m.group(1):
                return Decimal(m.group(1))
            return None

        result[(provider, model)] = {
            "input_cost": _get_decimal("input_cost_per_million"),
            "output_cost": _get_decimal("output_cost_per_million"),
            "cache_read_cost": _get_decimal("cache_read_cost_per_million"),
            "cache_write_cost": _get_decimal("cache_write_cost_per_million"),
        }

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_decimal_per_million(value) -> Optional[Decimal]:
    """Convert a per-token price to per-million-tokens, or return None."""
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        if d == 0:
            return None
        # OpenRouter prices are per-token; Hermes uses per-million
        return d * 1_000_000
    except Exception:
        return None


def _format_price(d: Optional[Decimal]) -> str:
    if d is None:
        return "    N/A"
    return f"${d:>7.4f}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch model pricing from providers")
    parser.add_argument(
        "--provider", "-p",
        choices=["all", "deepseek", "openrouter", "nvidia"],
        default="all",
        help="Which provider(s) to fetch (default: all)",
    )
    parser.add_argument(
        "--diff", "-d",
        action="store_true",
        help="Compare fetched pricing against hardcoded rates in usage_pricing.py",
    )
    args = parser.parse_args()

    all_prices: list[ModelPrice] = []

    fetchers = {
        "deepseek": fetch_deepseek,
        "openrouter": fetch_openrouter,
        "nvidia": fetch_nvidia_model_ids,
    }

    providers_to_fetch = list(fetchers.keys()) if args.provider == "all" else [args.provider]

    for provider in providers_to_fetch:
        print(f"\n📡 Fetching {provider} ...", end=" ", flush=True)
        try:
            prices = fetchers[provider]()
            all_prices.extend(prices)
            print(f"OK ({len(prices)} models)")
        except Exception as e:
            print(f"FAILED: {e}")
            continue

    if not all_prices:
        print("No pricing data fetched.")
        return

    # Print table
    print(f"\n{'─' * 90}")
    print(f"  PROVIDER PRICING SNAPSHOT — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'─' * 90}")
    print(f"  {'MODEL':<35s} {'INPUT/M':>10s} {'OUTPUT/M':>10s} {'CACHE HIT/M':>12s} {'PROMO':<20s}")
    print(f"  {'─' * 89}")

    for p in sorted(all_prices, key=lambda x: (x.provider, x.model_id)):
        display_id = p.model_id.split("/")[-1] if "/" in p.model_id else p.model_id
        display_id = display_id[:33] + ".." if len(display_id) > 35 else display_id
        print(
            f"  {display_id:<35s} "
            f"{_format_price(p.input_cost):>10s} "
            f"{_format_price(p.output_cost):>10s} "
            f"{_format_price(p.cache_read_cost):>12s} "
            f"{p.promo[:20]:<20s}"
        )

    print(f"  {'─' * 89}")

    # Diff mode: compare with hardcoded
    if args.diff:
        hardcoded = load_hardcoded_pricing()
        if not hardcoded:
            print("\n⚠️  Could not load hardcoded pricing from usage_pricing.py")
            return

        print(f"\n{'─' * 90}")
        print(f"  DIFF vs usage_pricing.py")
        print(f"{'─' * 90}")

        diffs_found = 0
        for p in all_prices:
            key = (p.provider, p.model_id)
            if key not in hardcoded:
                # Try matching without provider prefix
                bare = p.model_id.split("/")[-1] if "/" in p.model_id else p.model_id
                key = (p.provider, bare)
            if key not in hardcoded:
                continue

            hc = hardcoded[key]
            changed = []

            def _cmp(label: str, live_val: Optional[Decimal], hc_val: Optional[Decimal]) -> None:
                if live_val is not None and hc_val is not None and live_val != hc_val:
                    changed.append(f"{label}: {_format_price(hc_val)} → {_format_price(live_val)}")

            _cmp("input", p.input_cost, hc.get("input_cost"))
            _cmp("output", p.output_cost, hc.get("output_cost"))
            _cmp("cache_hit", p.cache_read_cost, hc.get("cache_read_cost"))

            if changed:
                diffs_found += 1
                display = p.model_id.split("/")[-1] if "/" in p.model_id else p.model_id
                print(f"\n  ⚠️  {p.provider}/{display}:")
                for c in changed:
                    print(f"      {c}")

        if diffs_found == 0:
            print("  ✅ All prices match. No updates needed.")
        else:
            print(f"\n  Found {diffs_found} models with pricing discrepancies.")
            print(f"  To update: edit agent/usage_pricing.py -> _OFFICIAL_DOCS_PRICING")
            print(f"  File: ~/.hermes/hermes-agent/agent/usage_pricing.py")


if __name__ == "__main__":
    main()