#!/usr/bin/env python3
"""
Enrich token-logger CSV logs with live pricing from the pricing-tools cache.
Fixes $0.0000 cost rows by looking up actual rates per provider/model.

Handles:
  - Exact provider+model match
  - Prefix-stripped match (e.g. "deepseek-ai/deepseek-v4-pro" → "deepseek-v4-pro")
  - Cross-provider match (e.g. NVIDIA routes DeepSeek models → find rate under "deepseek")
  - OpenRouter owner/model format

Usage:
  python enrich_logs.py                    # Enrich today's log
  python enrich_logs.py --days 7           # Enrich last 7 days
  python enrich_logs.py --dry-run          # Preview without writing
  python enrich_logs.py --recalculate      # Recalculate even if cost already set
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Resolve paths relative to this script's location (plugin dir)
_PLUGIN_DIR = Path(__file__).resolve().parent
_PRICING_CACHE = _PLUGIN_DIR / "pricing_cache.json"
_TOKEN_LOG_DIR = Path.home() / ".hermes" / "token_logs"
_CACHE_TTL_HOURS = 24


def load_pricing_cache() -> dict:
    """Load pricing-tools cache, return {} if missing/stale."""
    if not _PRICING_CACHE.exists():
        print(f"⚠️  No pricing cache at {_PRICING_CACHE}")
        return {}
    try:
        raw = json.loads(_PRICING_CACHE.read_text())
        fetched = datetime.fromisoformat(raw.get("_fetched_at", "1970"))
        age_h = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600
        if age_h > _CACHE_TTL_HOURS:
            print(f"⚠️  Cache is {age_h:.1f}h old (TTL: {_CACHE_TTL_HOURS}h)")
        return {k: v for k, v in raw.items() if not k.startswith("_")}
    except Exception as e:
        print(f"⚠️  Failed to read cache: {e}")
        return {}


def build_rate_lookup(cache: dict) -> dict[tuple[str, str], dict]:
    """Build (provider, model_id) -> rate dict, plus a bare-model cross-provider index."""
    exact = {}
    bare_model: dict[str, list] = {}  # bare model → list of (provider, rate)

    for provider, models in cache.items():
        for m in models:
            mid = m.get("model_id", "")
            rate = {
                "input_cost": m.get("input_cost"),
                "output_cost": m.get("output_cost"),
                "cache_read_cost": m.get("cache_read_cost"),
            }
            exact[(provider, mid)] = rate
            # Index by bare model name for cross-provider lookup
            bare = mid.split("/")[-1] if "/" in mid else mid
            bare_model.setdefault(bare, []).append((provider, rate))

    return exact, bare_model


def _to_decimal(val) -> str | None:
    if val is None:
        return None
    return str(val)


def _find_rate(
    provider: str,
    model: str,
    exact: dict[tuple[str, str], dict],
    bare_model: dict[str, list],
) -> dict | None:
    """Try multiple matching strategies to find a rate for (provider, model)."""

    # Strategy 1: Exact match (provider, model)
    key = (provider, model)
    if key in exact:
        return exact[key]

    # Strategy 2: Strip common prefixes (e.g. "deepseek-ai/deepseek-v4-pro" → "deepseek-v4-pro")
    if "/" in model:
        bare = model.split("/", 1)[-1]
        rate = exact.get((provider, bare))
        if rate:
            return rate
        # Strategy 3: Cross-provider lookup by bare model name
        if bare in bare_model:
            # Prefer the match where provider name appears in the original model string
            candidates = bare_model[bare]
            for p, r in candidates:
                if p in model or model.replace("-ai/", "-") in r.get("source_url", ""):
                    return r
            return candidates[0][1]

    # Strategy 4: Try matching just the last segment of provider in model
    # e.g. provider="nvidia", model="minimaxai/minimax-m2.7" → try "minimax" provider
    if "/" in model:
        owner = model.split("/")[0].lower()
        bare = model.split("/")[-1]
        # Normalize: "minimaxai" → "minimax", "deepseek-ai" → "deepseek"
        owner_clean = owner.replace("-ai", "").replace("ai", "").rstrip("0123456789")
        rate = exact.get((owner_clean, bare))
        if rate:
            return rate
        # Also try bare model across all providers
        if bare in bare_model:
            return bare_model[bare][0][1]

    # Strategy 5: Full model string as key in any provider
    for (p, m), rate in exact.items():
        if m == model or model.endswith("/" + m):
            return rate

    return None


def _compute_cost(row: dict, rate: dict) -> str:
    """Compute cost_usd from rate and token counts."""
    input_tokens = int(row.get("input_tokens", 0) or 0)
    output_tokens = int(row.get("output_tokens", 0) or 0)
    cache_hit_tokens = int(row.get("cache_hit_tokens", 0) or 0)

    cost = 0.0

    cache_rate = rate.get("cache_read_cost")
    input_rate = rate.get("input_cost")

    if cache_rate is not None and cache_hit_tokens > 0:
        cost += cache_hit_tokens / 1_000_000 * float(cache_rate)
        non_cache_input = max(0, input_tokens - cache_hit_tokens)
    else:
        non_cache_input = input_tokens

    if input_rate is not None and non_cache_input > 0:
        cost += non_cache_input / 1_000_000 * float(input_rate)

    if rate.get("output_cost") is not None and output_tokens > 0:
        cost += output_tokens / 1_000_000 * float(rate["output_cost"])

    return f"{cost:.6f}"


def _row_needs_enrichment(row: dict, recalculate: bool) -> bool:
    """Check if this row's cost needs to be (re)calculated."""
    existing = (row.get("cost_usd") or "").strip()
    if not existing:
        return True
    if existing in ("0", "0.0", "0.0000", "0.000000"):
        return True
    if recalculate:
        return True
    # Check if already enriched by us
    if (row.get("cost_source") or "").strip() == "pricing-tools-cache":
        return False
    return False


def enrich_file(
    gz_path: Path,
    exact: dict[tuple[str, str], dict],
    bare_model: dict[str, list],
    *,
    recalculate: bool = False,
    dry_run: bool = False,
) -> dict:
    """Enrich one CSV.gz file. Returns stats dict."""
    stats = {
        "file": gz_path.name,
        "rows": 0,
        "enriched": 0,
        "already_set": 0,
        "no_rate": 0,
        "skipped_read": False,
    }

    try:
        with gzip.open(gz_path, mode="rb") as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))
            headers = reader.fieldnames or []
            rows = list(reader)
    except (EOFError, OSError, gzip.BadGzipFile, Exception) as e:
        print(f"  ⚠️  {gz_path.name}: could not read ({e})")
        stats["skipped_read"] = True
        return stats

    stats["rows"] = len(rows)

    for row in rows:
        provider = (row.get("provider") or "").strip()
        model = (row.get("model") or "").strip()
        if not provider or not model:
            continue

        if not _row_needs_enrichment(row, recalculate):
            stats["already_set"] += 1
            continue

        rate = _find_rate(provider, model, exact, bare_model)

        if rate:
            new_cost = _compute_cost(row, rate)
            if new_cost != row.get("cost_usd", ""):
                row["cost_usd"] = new_cost
                row["cost_status"] = "enriched"
                row["cost_source"] = "pricing-tools-cache"
                stats["enriched"] += 1
            else:
                stats["already_set"] += 1
        else:
            stats["no_rate"] += 1

    if not dry_run and not stats["skipped_read"]:
        backup = gz_path.with_suffix(".csv.gz.bak")
        if not backup.exists():
            import shutil
            shutil.copy2(gz_path, backup)
        with gzip.open(gz_path, mode="wb", compresslevel=6) as f_out:
            with io.TextIOWrapper(f_out, encoding="utf-8") as wrapper:
                writer = csv.DictWriter(wrapper, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows)
        print(f"  ✅ {gz_path.name}: {stats['enriched']} enriched, {stats['already_set']} set, {stats['no_rate']} unmatched")
    else:
        print(f"  🔍 {gz_path.name}: {stats['enriched']} would enrich, {stats['already_set']} set, {stats['no_rate']} unmatched")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Enrich token logs with live pricing from cache")
    parser.add_argument("--days", type=int, default=7, help="Number of days of logs to enrich (default: 7)")
    parser.add_argument("--recalculate", action="store_true", help="Recalculate even if cost already set")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    print(f"Loading pricing cache from {_PRICING_CACHE}...")
    cache = load_pricing_cache()
    providers = list(cache.keys())
    print(f"  Cache has {len(providers)} providers: {', '.join(providers)}")

    exact, bare_model = build_rate_lookup(cache)
    print(f"  Rate lookup: {len(exact)} exact pairs, {len(bare_model)} bare model entries")
    print()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    log_dir = Path.home() / ".hermes" / "token_logs"
    log_files = sorted(log_dir.glob("*.csv.gz"))

    if not log_files:
        print("No log files found!")
        return

    total_stats = {"rows": 0, "enriched": 0, "already_set": 0, "no_rate": 0, "skipped": 0}

    for f in log_files:
        # Handle YYYY-MM-DD.csv.gz stems like "2026-05-08.csv" — strip .csv
        stem_base = f.stem.replace(".csv", "")
        # Handle combined files like "2026-05-08-09-combined" — skip those
        if "-combined" in stem_base or "-enriched" in stem_base:
            if args.dry_run:
                print(f"  SKIP {f.name} (combined/enriched file)")
            continue
        try:
            file_date = datetime.strptime(stem_base, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if file_date < cutoff:
                if args.dry_run:
                    print(f"  SKIP {f.name} (older than {args.days} days)")
                continue
        except ValueError:
            continue

        stats = enrich_file(f, exact, bare_model, recalculate=args.recalculate, dry_run=args.dry_run)
        for k in total_stats:
            total_stats[k] += stats.get(k, 0)

    print()
    mode = "DRY RUN " if args.dry_run else ""
    print(f"{'='*50}")
    print(f"{mode}Summary:")
    print(f"  Total rows:     {total_stats['rows']}")
    print(f"  Enriched:       {total_stats['enriched']}")
    print(f"  Already set:    {total_stats['already_set']}")
    print(f"  No rate found:  {total_stats['no_rate']}")
    print(f"  Skipped (bad):  {total_stats['skipped']}")

    if total_stats["no_rate"] > 0:
        print(f"\n⚠️  {total_stats['no_rate']} rows have no matching rate in cache.")
        print("   Consider adding more providers or running `hermes tools list_models` to expand coverage.")


if __name__ == "__main__":
    main()