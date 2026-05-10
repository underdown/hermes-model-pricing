#!/usr/bin/env python3
"""
Generate a monthly token spend report with live cost attribution.
Reads all token-logger CSV.gz files, computes spend by provider/model/day.
"""
import csv, gzip, io, json, sys, os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_LOG_DIR = Path.home() / ".hermes" / "token_logs"
CACHE_PATH = Path.home() / ".hermes" / "plugins" / "pricing-tools" / "pricing_cache.json"
REPORT_DIR = Path.home() / ".hermes" / "reports"


def load_cache():
    if not CACHE_PATH.exists():
        return {}
    try:
        raw = json.loads(CACHE_PATH.read_text())
        return {k: v for k, v in raw.items() if not k.startswith("_")}
    except Exception:
        return {}


def build_lookup(cache):
    exact = {}
    bare_idx = {}
    for provider, models in cache.items():
        for m in models:
            mid = m.get("model_id", "")
            rate = m
            exact[(provider, mid)] = rate
            bare = mid.split("/")[-1] if "/" in mid else mid
            bare_idx.setdefault(bare, []).append((provider, rate))
    return exact, bare_idx


def find_rate(p, m, exact, bare_idx):
    key = (p, m)
    if key in exact:
        return exact[key]
    if "/" in m:
        bare = m.split("/", 1)[-1]
        r = exact.get((p, bare))
        if r:
            return r
        if bare in bare_idx:
            owner = m.split("/")[0].lower().replace("-ai", "").replace("ai", "")
            r = exact.get((owner, bare))
            if r:
                return r
            return bare_idx[bare][0][1]
    if "/" in m:
        bare = m.split("/")[-1]
        for prov_try in ["deepseek", "minimax"]:
            r = exact.get((prov_try, bare))
            if r:
                return r
    return None


def cost_val(row, rate):
    input_t = int(row.get("input_tokens", 0) or 0)
    output_t = int(row.get("output_tokens", 0) or 0)
    cache_hit_t = int(row.get("cache_hit_tokens", 0) or 0)
    c = 0.0
    cr = rate.get("cache_read_cost")
    ir = rate.get("input_cost")
    orr = rate.get("output_cost")
    if cr and cache_hit_t > 0:
        c += cache_hit_t / 1_000_000 * float(cr)
        non = max(0, input_t - cache_hit_t)
    else:
        non = input_t
    if ir and non > 0:
        c += non / 1_000_000 * float(ir)
    if orr and output_t > 0:
        c += output_t / 1_000_000 * float(orr)
    return c


def main():
    REPORT_DIR.mkdir(exist_ok=True)
    cache = load_cache()
    exact, bare_idx = build_lookup(cache)
    now = datetime.now(timezone.utc)

    # Gather all log files
    files = sorted(_LOG_DIR.glob("*.csv.gz"))
    if not files:
        print("No log files found!")
        return

    # Aggregators
    by_provider = defaultdict(lambda: {"count": 0, "tokens_in": 0, "tokens_out": 0, "cost": 0.0})
    by_model = defaultdict(lambda: {"provider": "", "count": 0, "cost": 0.0})
    by_day = defaultdict(lambda: {"count": 0, "cost": 0.0})
    total_rows = 0
    total_cost = 0.0
    no_rate = 0
    enriched = 0

    for f in files:
        try:
            decompressed = gzip.decompress(f.read_bytes())
            reader = csv.DictReader(io.StringIO(decompressed.decode("utf-8")))
        except Exception as e:
            print(f"  SKIP {f.name}: {e}")
            continue

        for row in reader:
            p = (row.get("provider") or "").strip()
            m = (row.get("model") or "").strip()
            if not p or not m:
                continue

            total_rows += 1
            date = row.get("timestamp", "")[:10]

            rate = find_rate(p, m, exact, bare_idx)
            if rate:
                c = cost_val(row, rate)
                if c > 0:
                    enriched += 1
                by_provider[p]["count"] += 1
                by_provider[p]["tokens_in"] += int(row.get("input_tokens", 0) or 0)
                by_provider[p]["tokens_out"] += int(row.get("output_tokens", 0) or 0)
                by_provider[p]["cost"] += c

                by_model[m]["provider"] = p
                by_model[m]["count"] += 1
                by_model[m]["cost"] += c

                by_day[date]["count"] += 1
                by_day[date]["cost"] += c

                total_cost += c
            else:
                no_rate += 1

    # Build report
    out = []
    out.append(f"# 💰 Monthly Token Spend Report")
    out.append(f"**Period:** {files[0].stem} to {files[-1].stem}")
    out.append(f"**Generated:** {now.strftime('%Y-%m-%d %H:%M UTC')}")
    out.append(f"")
    out.append(f"## Summary")
    out.append(f"| Metric | Value |")
    out.append(f"|--------|-------|")
    out.append(f"| Total API calls | {total_rows:,} |")
    out.append(f"| Calls with rate | {enriched:,} |")
    out.append(f"| Calls without rate | {no_rate:,} |")
    out.append(f"| **Total spend** | **${total_cost:,.6f}** |")
    out.append(f"| Top provider calls | {max(by_provider.items(), key=lambda x: x[1]['count'])[0] if by_provider else 'N/A'} |")
    out.append(f"| Top provider cost | {max(by_provider.items(), key=lambda x: x[1]['cost'])[0] if by_provider else 'N/A'} |")
    out.append(f"")

    out.append(f"## Spend by Provider")
    out.append(f"| Provider | Calls | Tokens In | Tokens Out | Cost |")
    out.append(f"|----------|-------|-----------|------------|------|")
    for p in sorted(by_provider, key=lambda k: by_provider[k]["cost"], reverse=True):
        d = by_provider[p]
        out.append(f"| {p} | {d['count']:,} | {d['tokens_in']:,} | {d['tokens_out']:,} | ${d['cost']:,.6f} |")

    out.append(f"\n## Top 10 Models by Cost")
    out.append(f"| Model | Provider | Calls | Cost |")
    out.append(f"|-------|----------|-------|------|")
    for m in sorted(by_model, key=lambda k: by_model[k]["cost"], reverse=True)[:10]:
        d = by_model[m]
        out.append(f"| `{m}` | {d['provider']} | {d['count']:,} | ${d['cost']:,.6f} |")

    out.append(f"\n## Daily Spend Trend")
    out.append(f"| Date | Calls | Cost |")
    out.append(f"|------|-------|------|")
    for d in sorted(by_day):
        bd = by_day[d]
        out.append(f"| {d} | {bd['count']:,} | ${bd['cost']:,.6f} |")

    report = "\n".join(out)
    report_path = REPORT_DIR / f"spend_report_{now.strftime('%Y-%m')}.md"
    report_path.write_text(report)
    print(report)
    print(f"\n✅ Saved to {report_path}")


if __name__ == "__main__":
    main()