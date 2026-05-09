"""Pricing fetcher module — live scrape + 24h cache for all LLM providers."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import requests


# ---------------------------------------------------------------------------
# Cache path
# ---------------------------------------------------------------------------

_CACHE_PATH = Path(__file__).parent / "pricing_cache.json"
_CACHE_TTL_HOURS = 24

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

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

    def to_dict(self) -> dict:
        d = asdict(self)
        for field_name in ("input_cost", "output_cost", "cache_read_cost", "cache_write_cost"):
            if d.get(field_name) is not None:
                d[field_name] = str(d[field_name])
        d["fetched_at"] = self.fetched_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ModelPrice:
        d = dict(d)
        for field_name in ("input_cost", "output_cost", "cache_read_cost", "cache_write_cost"):
            if d.get(field_name):
                d[field_name] = Decimal(d[field_name])
        if d.get("fetched_at"):
            d["fetched_at"] = datetime.fromisoformat(d["fetched_at"])
        return cls(**d)


# ---------------------------------------------------------------------------
# Cache read / write
# ---------------------------------------------------------------------------

def _read_cache() -> dict[str, list[dict]]:
    if not _CACHE_PATH.exists():
        return {}
    try:
        raw = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(raw.get("_fetched_at", "1970"))
        if datetime.now(timezone.utc) - fetched > timedelta(hours=_CACHE_TTL_HOURS):
            return {}
        return {k: v for k, v in raw.items() if not k.startswith("_")}
    except Exception:
        return {}


def _write_cache(data: dict[str, list[dict]]) -> None:
    try:
        out = {**data, "_fetched_at": datetime.now(timezone.utc).isoformat()}
        _CACHE_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
        logger.debug("Pricing cache written")
    except Exception as e:
        logger.warning("Failed to write pricing cache: %s", e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UA = {"User-Agent": "Hermes-Pricing-Plugin/1.0"}
TIMEOUT = 15


def _dec(s: Optional[str]) -> Optional[Decimal]:
    if not s:
        return None
    s = s.strip().lstrip("$").replace(",", "").split()[0]  # "0.50(13.3M / $1)*" → "0.50"
    if s in ("-", "", "N/A"):
        return None
    try:
        return Decimal(s)
    except Exception:
        return None


def _clean(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def _drain_table(html: str, price_cols: list[int] = None) -> list[list[str]]:
    rows_out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL):
        cells = [_clean(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL)]
        if not any(cells):
            continue
        if price_cols:
            for i in price_cols:
                if i < len(cells):
                    cells[i] = cells[i].lstrip("$").strip()
        rows_out.append(cells)
    return rows_out


# ---------------------------------------------------------------------------
# Live scrapers
# ---------------------------------------------------------------------------

def _live_deepseek() -> list[ModelPrice]:
    """Scrape DeepSeek pricing page. Table format:
    Row 0: MODEL | deepseek-v4-flash | deepseek-v4-pro
    Rows 11+: PRICING section with CACHE HIT / CACHE MISS / OUTPUT rows.
    """
    resp = requests.get("https://api-docs.deepseek.com/quick_start/pricing", timeout=TIMEOUT, headers=UA)
    resp.raise_for_status()

    tables = re.findall(r'<table[^>]*>(.*?)</table>', resp.text, re.DOTALL)
    if not tables:
        raise RuntimeError("No table found on DeepSeek pricing page")
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', tables[0], re.DOTALL)

    # Find MODEL row to get column → model name mapping
    model_cols: dict[int, str] = {}  # column index → model_id (stripped)
    pricing_rows: list[list[str]] = []
    in_pricing = False

    for row in rows:
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row, re.DOTALL)]
        if not cells or not any(cells for c in cells):
            continue
        if cells[0] == "MODEL":
            for j, cell in enumerate(cells[1:], start=1):
                name = re.sub(r'\s*\(\d+\)\s*$', '', cell).strip()  # strip "(1)" suffix
                model_cols[j] = name
        elif "PRICING" in cells[0]:
            in_pricing = True
        elif in_pricing and (cells[0].startswith("1M INPUT") or cells[0].startswith("1M OUTPUT")):
            pricing_rows.append(cells)

    if not model_cols or not pricing_rows:
        raise RuntimeError("DeepSeek pricing table structure unexpected")

    # Aggregate prices per model
    prices: dict[str, dict] = {name: {} for name in model_cols.values()}
    for row in pricing_rows:
        label = row[0]
        for col_idx, model_id in model_cols.items():
            if col_idx < len(row):
                raw = row[col_idx]
                # First dollar amount in the cell
                m = re.search(r"\$?([\d.]+)", raw)
                if m:
                    price = Decimal(m.group(1))
                    if "CACHE HIT" in label:
                        prices[model_id]["cache_hit"] = price
                    elif "CACHE MISS" in label:
                        prices[model_id]["input"] = price
                    elif "OUTPUT" in label:
                        prices[model_id]["output"] = price

    return [
        ModelPrice(
            provider="deepseek",
            model_id=model_id,
            input_cost=p.get("input"),
            output_cost=p.get("output"),
            cache_read_cost=p.get("cache_hit"),
            context_length=1_000_000,
            promo="75% off until 2026-05-31" if (p.get("input") or Decimal(0)) > Decimal("0.4") else "",
            source_url=resp.url,
        )
        for model_id, p in prices.items()
    ]


def _live_openrouter() -> list[ModelPrice]:
    resp = requests.get("https://openrouter.ai/api/v1/models", timeout=TIMEOUT,
                        headers={**UA, "Accept": "application/json"})
    resp.raise_for_status()
    return [
        ModelPrice(
            provider="openrouter",
            model_id=m["id"],
            input_cost=Decimal(str(float(p["prompt"]) * 1_000_000)) if (p := m.get("pricing", {}) or {}).get("prompt") else None,
            output_cost=Decimal(str(float(p["completion"]) * 1_000_000)) if (p := m.get("pricing") or {}).get("completion") else None,
            context_length=m.get("context_length"),
            source_url=resp.url,
        )
        for m in resp.json().get("data", [])
        if m.get("pricing")
    ]


def _live_nvidia() -> list[ModelPrice]:
    resp = requests.get("https://integrate.api.nvidia.com/v1/models", timeout=TIMEOUT, headers=UA)
    resp.raise_for_status()
    return [
        ModelPrice(provider="nvidia", model_id=m["id"], input_cost=None, output_cost=None,
                   source_url=resp.url)
        for m in resp.json().get("data", [])
    ]


def _live_groq() -> list[ModelPrice]:
    resp = requests.get("https://groq.com/pricing", timeout=TIMEOUT, headers=UA)
    resp.raise_for_status()
    html = re.sub(r"<script[^>]*>.*?</script>", "", resp.text, re.DOTALL)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, re.DOTALL)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)

    results = []
    for row in rows:
        # Rows with prices have "AI ModelNAME" AND dollar signs
        if "AI Model" not in row or "$" not in row:
            continue
        first_cell = re.sub(r"<[^>]+>", "", row).split("</td>")[0].strip()
        if not first_cell.startswith("AI Model"):
            continue
        name_match = re.match(r"AI Model(.+?)(?:Current Speed|$)", first_cell)
        if not name_match:
            continue
        model_name = name_match.group(1).strip()
        # Extract ONLY $-prefixed amounts (model names have no $)
        amounts = re.findall(r"\$(\d+\.\d+)", row)
        if len(amounts) < 2:
            continue
        try:
            inp = Decimal(amounts[0])
            out = Decimal(amounts[1])
        except Exception:
            continue
        if inp is None and out is None:
            continue
        results.append(ModelPrice(
            provider="groq",
            model_id=model_name,
            input_cost=inp,
            output_cost=out,
            context_length=131072,
            source_url=resp.url,
        ))
    return results


def _live_fireworks() -> list[ModelPrice]:
    resp = requests.get("https://docs.fireworks.ai/serverless/pricing", timeout=TIMEOUT, headers=UA)
    resp.raise_for_status()

    # Main pricing table is the first table on the page
    tables = re.findall(r'<table[^>]*>(.*?)</table>', resp.text, re.DOTALL)
    if not tables:
        raise RuntimeError("No table found on Fireworks pricing page")

    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', tables[0], re.DOTALL)
    results = []
    for row in rows[1:]:  # skip header row
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL)]
        if len(cells) < 2 or not cells[0] or cells[0] == "Model":
            continue
        model_name = cells[0]
        price_cell = cells[1].lstrip("$").strip()  # "$in / $cache / $out"
        parts = [p.strip() for p in price_cell.split("/")]
        inp = _dec(parts[0]) if len(parts) > 0 else None
        cache = _dec(parts[1]) if len(parts) > 1 else None
        out = _dec(parts[2]) if len(parts) > 2 else None
        if inp is None and out is None:
            continue
        results.append(ModelPrice(
            provider="fireworks",
            model_id=model_name,
            input_cost=inp,
            cache_read_cost=cache,
            output_cost=out,
            context_length=262144,
            source_url=resp.url,
        ))
    return results


def _live_together() -> list[ModelPrice]:
    resp = requests.get("https://docs.together.ai/docs/inference-models", timeout=TIMEOUT, headers=UA)
    resp.raise_for_status()
    html = re.sub(r"<script[^>]*>.*?</script>", "", resp.text, re.DOTALL)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, re.DOTALL)

    # Primary LLM table: org | model name | api string | ctx | input | cache_in | output | ...
    rows = _drain_table(html, price_cols=[4, 5, 6])

    results = []
    for row in rows:
        if len(row) < 6:
            continue
        api_str = row[2].strip()
        # Skip non-LLM rows (images, video, audio, embeddings)
        if not api_str or "/" not in api_str:
            continue
        if any(skip in api_str.lower() for skip in
               ["imagen", "veo", "sora", "flux", "hailuo", "pixverse", "kling",
                "seedance", "vidu", "wan", "kokoro", "orpheus", "e5-", "codestral",
                "minimax/video", "stable-diffusion"]):
            continue
        ctx_str = row[3].strip()
        ctx = int(ctx_str) if ctx_str.isdigit() else None
        inp = _dec(row[4])
        cache_in = _dec(row[5]) if len(row) > 5 else None
        out_cost = _dec(row[6]) if len(row) > 6 else None
        if inp is None and out_cost is None:
            continue
        results.append(ModelPrice(
            provider="together",
            model_id=api_str,
            input_cost=inp,
            cache_read_cost=cache_in,
            output_cost=out_cost,
            context_length=ctx,
            source_url=resp.url,
        ))
    return results


def _live_mistral() -> list[ModelPrice]:
    return _static_mistral()


def _live_cohere() -> list[ModelPrice]:
    return _static_cohere()


def _live_minimax() -> list[ModelPrice]:
    return _static_minimax()


# ---------------------------------------------------------------------------
# Static / fallback fetchers
# ---------------------------------------------------------------------------

def _static_mistral() -> list[ModelPrice]:
    rates = [
        ("mistral-small-latest", "0.10", "0.30", 131072),
        ("mistral-medium-latest", "1.50", "4.00", 131072),
        ("mistral-large-latest", "2.00", "8.00", 131072),
        ("codestral-latest", "0.50", "1.00", 131072),
    ]
    return [
        ModelPrice(provider="mistral", model_id=k, input_cost=Decimal(i),
                   output_cost=Decimal(o), context_length=c,
                   source_url="https://mistral.ai/pricing")
        for k, i, o, c in rates
    ]


def _static_cohere() -> list[ModelPrice]:
    rates = [
        ("command-a-03-2025", "0.50", "1.50", 262144),
        ("command-r-plus-08-2024", "2.50", "10.00", 131072),
        ("command-r-03-2024", "0.50", "1.50", 131072),
        ("aya-expanse-8b", "0.50", "1.50", 262144),
        ("aya-expanse-32b", "0.50", "1.50", 262144),
    ]
    return [
        ModelPrice(provider="cohere", model_id=k, input_cost=Decimal(i),
                   output_cost=Decimal(o), context_length=c,
                   source_url="https://cohere.com/pricing")
        for k, i, o, c in rates
    ]


def _static_minimax() -> list[ModelPrice]:
    rates = [
        ("minimax-m2.7", "0.30", "1.20", 202752),
        ("minimax-m1", "0.50", "5.00", 202752),
        ("minimax-text-01", "0.50", "5.00", 65536),
    ]
    return [
        ModelPrice(provider="minimax", model_id=k, input_cost=Decimal(i),
                   output_cost=Decimal(o), context_length=c,
                   source_url="https://platform.minimax.io/docs")
        for k, i, o, c in rates
    ]


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------

_PROVIDER_LIVE_FETCHERS: dict[str, callable] = {
    "deepseek":   _live_deepseek,
    "openrouter": _live_openrouter,
    "nvidia":     _live_nvidia,
    "groq":       _live_groq,
    "fireworks":  _live_fireworks,
    "together":   _live_together,
    "mistral":    _live_mistral,
    "cohere":     _live_cohere,
    "minimax":    _live_minimax,
}


def _load_provider(provider: str) -> list[ModelPrice]:
    """Load models for a provider — from cache if fresh, else fetch live and cache."""
    cache = _read_cache()
    if provider in cache:
        return [ModelPrice.from_dict(d) for d in cache[provider]]

    fetcher = _PROVIDER_LIVE_FETCHERS.get(provider, _static_minimax)
    try:
        models = fetcher()
    except Exception as exc:
        logger.warning("Failed to fetch pricing for %s: %s", provider, exc)
        if provider in cache:
            return [ModelPrice.from_dict(d) for d in cache[provider]]
        if provider == "mistral":
            return _static_mistral()
        if provider == "cohere":
            return _static_cohere()
        if provider == "minimax":
            return _static_minimax()
        return []

    cache[provider] = [m.to_dict() for m in models]
    _write_cache(cache)
    return models


def fetch_all() -> dict[str, list[ModelPrice]]:
    results = {}
    for name in _PROVIDER_LIVE_FETCHERS:
        try:
            results[name] = _load_provider(name)
        except Exception as exc:
            results[name] = [ModelPrice(name, f"FETCH_ERROR: {exc}", None, None)]
    return results


def prices_as_table(provider_name: str, models: list[ModelPrice], max_rows: int = 20) -> str:
    def fmt(dec):
        if dec is None:
            return "—"
        return f"${float(dec):,.2f}"

    lines = [f"**{provider_name}** ({len(models)} models)"]
    if not models:
        lines.append("  _(none)_")
        return "\n".join(lines)

    for m in models[:max_rows]:
        inp = fmt(m.input_cost)
        out = fmt(m.output_cost)
        ctx = f"{m.context_length:,}" if m.context_length else "—"
        promo = f" ⚡{m.promo}" if m.promo else ""
        cache = f"  cache:{fmt(m.cache_read_cost)}" if m.cache_read_cost else ""
        lines.append(f"  `{m.model_id}` — in:{inp}/M  out:{out}/M  ctx:{ctx}{cache}{promo}")

    if len(models) > max_rows:
        lines.append(f"  ... _and {len(models) - max_rows} more_")

    cache_info = _read_cache().get("_fetched_at")
    if cache_info:
        age_h = round((datetime.now(timezone.utc) - datetime.fromisoformat(cache_info)).total_seconds() / 3600, 1)
        lines.append(f"\n  _Cache: {age_h}h old — refreshes every {_CACHE_TTL_HOURS}h_")

    return "\n".join(lines)