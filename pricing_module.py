"""Pricing fetcher module — in-process equivalent of fetch_pricing.py."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import requests


@dataclass
class ModelPrice:
    provider: str
    model_id: str
    input_cost: Optional[Decimal]
    output_cost: Optional[Decimal]
    cache_read_cost: Optional[Decimal] = None
    cache_write_cost: Optional[Decimal] = None
    context_length: Optional[int] = None
    promo: str = ""
    source_url: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


UA = {"User-Agent": "Hermes-Pricing-Plugin/1.0"}
TIMEOUT = 15


def _fmt(dec: Optional[Decimal]) -> str:
    if dec is None:
        return "—"
    return f"${float(dec):,.2f}"


# --------------------------------------------------------------------------
# Provider fetchers
# --------------------------------------------------------------------------

def fetch_deepseek() -> list[ModelPrice]:
    resp = requests.get("https://api-docs.deepseek.com/quick_start/pricing", timeout=TIMEOUT, headers=UA)
    resp.raise_for_status()
    td = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
    cells = [re.sub(r"<[^>]+>", "", c).strip() for c in td.findall(resp.text) if c]
    return [
        ModelPrice("deepseek", cells[1].replace("(1)", ""), Decimal("0.14"), Decimal("0.28"),
                   Decimal("0.0028"), context_length=1_000_000, source_url=resp.url),
        ModelPrice("deepseek", cells[2], Decimal("0.435"), Decimal("0.87"),
                   Decimal("0.003625"), promo="75% off until 2026-05-31",
                   context_length=1_000_000, source_url=resp.url),
    ]


def fetch_openrouter() -> list[ModelPrice]:
    resp = requests.get("https://openrouter.ai/api/v1/models", timeout=TIMEOUT, headers={**UA, "Accept": "application/json"})
    resp.raise_for_status()
    results = []
    for m in resp.json().get("data", []):
        pricing = m.get("pricing", {}) or {}
        inp = Decimal(str(pricing.get("prompt", "0") or "0")) * Decimal("1000000")
        out = Decimal(str(pricing.get("completion", "0") or "0")) * Decimal("1000000")
        results.append(ModelPrice("openrouter", m["id"], inp if inp else None, out if out else None,
                                  context_length=m.get("context_length"), source_url=resp.url))
    return results


def fetch_groq() -> list[ModelPrice]:
    rates = {
        "llama-3.1-8b-instruct": ("0.05", "0.08", None, 131072),
        "llama-3.3-70b-versatile": ("0.59", "0.79", None, 131072),
        "meta-llama/llama-4-scout-17b-16e-instruct": ("0.11", "0.34", None, 131072),
        "qwen/qwen3-32b": ("0.29", "0.59", None, 131072),
        "openai/gpt-oss-120b": ("0.15", "0.60", "0.0375", 131072),
        "openai/gpt-oss-20b": ("0.075", "0.30", "0.0375", 131072),
    }
    return [
        ModelPrice("groq", k, Decimal(inp), Decimal(out),
                   Decimal(c) if c else None, context_length=ctx, source_url="https://groq.com/pricing")
        for k, (inp, out, c, ctx) in rates.items()
    ]


def fetch_fireworks() -> list[ModelPrice]:
    rates = {
        "deepseek-ai/DeepSeek-V4-Pro": ("1.74", "3.48", "0.145", 512000),
        "moonshotai/Kimi-K2.6": ("0.95", "4.00", "0.16", 262144),
        "moonshotai/Kimi-K2.5": ("0.60", "3.00", "0.10", 262144),
        "MiniMaxAI/MiniMax-M2.7": ("0.30", "1.20", "0.06", 202752),
        "openai/gpt-oss-120b": ("0.15", "0.60", "0.015", 131072),
        "openai/gpt-oss-20b": ("0.07", "0.30", "0.035", 131072),
    }
    return [
        ModelPrice("fireworks", k, Decimal(inp), Decimal(out), Decimal(c), context_length=ctx,
                   source_url="https://docs.fireworks.ai/serverless/pricing")
        for k, (inp, out, c, ctx) in rates.items()
    ]


def fetch_together() -> list[ModelPrice]:
    rates = [
        ("deepseek-ai/DeepSeek-V4-Pro", "2.10", "4.40", None, 512000),
        ("moonshotai/Kimi-K2.6", "1.20", "4.50", None, 262144),
        ("MiniMaxAI/MiniMax-M2.7", "0.30", "1.20", "0.06", 202752),
        ("Qwen/Qwen3.5-9B", "0.10", "0.15", None, 262144),
        ("Qwen/Qwen3.6-Plus", "0.50", "3.00", None, 1000000),
        ("openai/gpt-oss-120b", "0.15", "0.60", None, 128000),
        ("openai/gpt-oss-20b", "0.05", "0.20", None, 128000),
        ("meta-llama/Llama-3.3-70B-Instruct-Turbo", "0.88", "0.88", None, 131072),
    ]
    return [
        ModelPrice("together", k, Decimal(inp), Decimal(out), Decimal(c) if c else None,
                   context_length=ctx, source_url="https://docs.together.ai/docs/inference-models")
        for k, inp, out, c, ctx in rates
    ]


def fetch_mistral() -> list[ModelPrice]:
    rates = {
        "mistral-small-latest": ("0.10", "0.30", 131072),
        "mistral-medium-latest": ("1.50", "4.00", 131072),
        "mistral-large-latest": ("2.00", "8.00", 131072),
        "codestral-latest": ("0.50", "1.00", 131072),
    }
    return [
        ModelPrice("mistral", k, Decimal(inp), Decimal(out), context_length=ctx,
                   source_url="https://mistral.ai/pricing")
        for k, (inp, out, ctx) in rates.items()
    ]


def fetch_cohere() -> list[ModelPrice]:
    rates = {
        "command-a-03-2025": ("0.50", "1.50", 262144),
        "command-a-08-2025": ("0.50", "1.50", 262144),
        "command-r-plus-08-2024": ("2.50", "10.00", 131072),
        "command-r-03-2024": ("0.50", "1.50", 131072),
        "aya-expanse-8b": ("0.50", "1.50", 262144),
        "aya-expanse-32b": ("0.50", "1.50", 262144),
    }
    return [
        ModelPrice("cohere", k, Decimal(inp), Decimal(out), context_length=ctx,
                   source_url="https://cohere.com/pricing")
        for k, (inp, out, ctx) in rates.items()
    ]


def fetch_minimax() -> list[ModelPrice]:
    rates = {
        "minimax-m2.7": ("0.30", "1.20", 202752),
        "minimax-m1": ("0.50", "5.00", 202752),
        "minimax-text-01": ("0.50", "5.00", 65536),
        "minimax-speech-2.6-turbo": ("0.30", "1.20", 202752),
    }
    return [
        ModelPrice("minimax", k, Decimal(inp), Decimal(out), context_length=ctx,
                   source_url="https://platform.minimax.io/docs")
        for k, (inp, out, ctx) in rates.items()
    ]


def fetch_nvidia() -> list[ModelPrice]:
    resp = requests.get("https://integrate.api.nvidia.com/v1/models", timeout=TIMEOUT, headers=UA)
    resp.raise_for_status()
    return [
        ModelPrice("nvidia", m["id"], None, None, source_url=resp.url)
        for m in resp.json().get("data", [])
    ]


# --------------------------------------------------------------------------
# Fetcher registry
# --------------------------------------------------------------------------

FETCHERS = {
    "deepseek": fetch_deepseek,
    "openrouter": fetch_openrouter,
    "nvidia": fetch_nvidia,
    "groq": fetch_groq,
    "fireworks": fetch_fireworks,
    "together": fetch_together,
    "mistral": fetch_mistral,
    "cohere": fetch_cohere,
    "minimax": fetch_minimax,
}


def fetch_all() -> dict[str, list[ModelPrice]]:
    results = {}
    for name, fn in FETCHERS.items():
        try:
            results[name] = fn()
        except Exception as exc:
            results[name] = [ModelPrice(name, f"FETCH_ERROR: {exc}", None, None)]
    return results


def prices_as_table(provider_name: str, models: list[ModelPrice], max_rows: int = 20) -> str:
    lines = [f"**{provider_name}** ({len(models)} models)"]
    if not models:
        lines.append("  _(none)_")
        return "\n".join(lines)
    for m in models[:max_rows]:
        inp = _fmt(m.input_cost)
        out = _fmt(m.output_cost)
        ctx = f"{m.context_length:,}" if m.context_length else "—"
        promo = f" ⚡{m.promo}" if m.promo else ""
        lines.append(f"  `{m.model_id}` — in:{inp}/M  out:{out}/M  ctx:{ctx}{promo}")
    if len(models) > max_rows:
        lines.append(f"  ... _and {len(models) - max_rows} more_")
    return "\n".join(lines)