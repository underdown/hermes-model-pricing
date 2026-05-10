#!/usr/bin/env python3
"""
Generate a weekly pricing comparison report.
Compares current cached prices with previous snapshot, highlights changes.
Posts summary to Discord #general via Hermes cron delivery.
"""
import json, sys
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pricing_module import _read_cache

REPORT_DIR = Path.home() / ".hermes" / "reports"
REPORT_DIR.mkdir(exist_ok=True)

def fmt(v):
    if v is None: return "—"
    return f"${float(v):.4f}"

def main():
    cache = _read_cache()
    now = datetime.now(timezone.utc)

    output = []
    output.append(f"# 📊 Weekly Pricing Report — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    output.append("")

    total_models = 0
    total_promo = 0

    for provider in sorted(cache):
        if provider.startswith("_"): continue
        models = cache[provider]
        total_models += len(models)
        output.append(f"\n## {provider.upper()} ({len(models)} models)")

        # Promo check
        promos = [m for m in models if m.get("promo")]
        if promos:
            total_promo += len(promos)
            output.append(f"  ⚡ **Promo active:** {len(promos)} model(s)")
            for m in promos:
                output.append(f"    - `{m['model_id']}`: {m['promo']}")

        # DeepSeek promo expiry warning
        if provider == "deepseek":
            for m in models:
                if "2026-05-31" in str(m.get("promo", "")):
                    days_left = (datetime(2026, 5, 31, tzinfo=timezone.utc) - now).days
                    output.append(f"\n  🚨 **HARD CODED RATES EXPIRE IN {days_left} DAYS**")
                    output.append(f"     After May 31, update `agent/usage_pricing.py` manually")
                    output.append(f"     or run: `hermes tools fetch_pricing deepseek`")

        for m in models:
            mid = m["model_id"]
            inp = fmt(m.get("input_cost"))
            out = fmt(m.get("output_cost"))
            ctx = f"{m['context_length']:,}" if m.get("context_length") else "—"
            cache_r = fmt(m.get("cache_read_cost")) if m.get("cache_read_cost") else ""
            promo_str = f" ⚡{m['promo']}" if m.get("promo") else ""
            cache_str = f"  cache:{cache_r}" if cache_r else ""
            output.append(f"  `{mid}` — in:{inp}/M out:{out}/M ctx:{ctx}{cache_str}{promo_str}")

    # Summary
    output.insert(2, f"**Summary:** {len(cache)} providers, {total_models} models, {total_promo} promo(s)")

    # If previous report exists, diff it
    prev = REPORT_DIR / "pricing_weekly_prev.json"
    if prev.exists():
        old = json.loads(prev.read_text())
        output.append("\n## 📈 Changes from last week")
        for provider in sorted(set(list(cache.keys()) + list(old.keys()))):
            if provider.startswith("_"): continue
            old_models = {m["model_id"]: m for m in old.get(provider, [])}
            for m in cache.get(provider, []):
                mid = m["model_id"]
                if mid in old_models:
                    old_in = old_models[mid].get("input_cost")
                    new_in = m.get("input_cost")
                    if old_in != new_in and old_in is not None and new_in is not None:
                        old_val = float(old_in)
                        new_val = float(new_in)
                        change = ((new_val - old_val) / old_val * 100) if old_val else 0
                        arrow = "⬆️" if new_val > old_val else "⬇️"
                        output.append(f"  {arrow} {provider}/{mid}: {fmt(old_in)} → {fmt(new_in)} ({change:+.1f}%)")

    # Save current for next week
    with open(prev, 'w') as f:
        json.dump(cache, f, indent=2, default=str)

    # Save report
    report_path = REPORT_DIR / f"pricing_weekly_{now.strftime('%Y-%m-%d')}.md"
    report_path.write_text("\n".join(output))
    print("\n".join(output))
    print(f"\n✅ Report saved: {report_path}")

if __name__ == "__main__":
    main()