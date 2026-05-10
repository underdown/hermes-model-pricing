"""pricing-tools — Hermes plugin for model pricing and model discovery.

Provides /pricing [provider] and /models [provider] commands for Discord, Telegram,
and other gateway platforms. Pricing data is fetched live from provider APIs and
public pricing pages — no API key required.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


# ── Gateway slash commands ──────────────────────────────────────────────

def _register_commands() -> None:
    """Inject /pricing and /models into the central command registry."""
    try:
        from hermes_cli.commands import COMMAND_REGISTRY, CommandDef

        COMMAND_REGISTRY.extend([
            CommandDef(
                "pricing",
                "Fetch live model pricing from a provider",
                "Info",
                args_hint="[deepseek|openrouter|groq|fireworks|together|mistral|cohere|minimax|all]",
            ),
            CommandDef(
                "models",
                "List available models from a provider",
                "Info",
                args_hint="[openrouter|nvidia|groq|together|deepseek]",
            ),
        ])
        logger.info("pricing-tools commands registered")
    except Exception as exc:
        logger.warning("Could not register /pricing /models commands: %s", exc)


# ── Core implementations ────────────────────────────────────────────────

def _fetch_pricing_impl(provider: str = "all", **_kw) -> str:
    """Internal implementation — calls _load_provider which uses 24h disk cache."""
    from .pricing_module import _load_provider, prices_as_table

    provider = provider.strip().lower() or "all"

    if provider not in ("all", "deepseek", "openrouter", "nvidia", "groq",
                         "fireworks", "together", "mistral", "cohere", "minimax"):
        return (
            f"Unknown provider: '{provider}'.\n"
            f"Available providers: `deepseek`, `openrouter`, `nvidia`, `groq`, "
            f"`fireworks`, `together`, `mistral`, `cohere`, `minimax`, `all`."
        )

    if provider == "all":
        from .pricing_module import fetch_all as _fetch_all
        results = _fetch_all()
        tables = [prices_as_table(name, models) for name, models in results.items()]
        return "\n\n".join(tables)

    models = _load_provider(provider)
    return prices_as_table(provider, models)


def _list_models_impl(provider: str = "openrouter", model_filter: str = "", **_kw) -> str:
    """Internal implementation — calls _load_provider which uses 24h disk cache."""
    from .pricing_module import _load_provider

    provider = provider.strip().lower() or "openrouter"
    model_filter = (model_filter or "").strip().lower()

    known = {"deepseek", "openrouter", "nvidia", "groq", "fireworks",
             "together", "mistral", "cohere", "minimax"}
    if provider not in known:
        return f"Unknown provider '{provider}'. Try: `{'`, `'.join(sorted(known))}`."

    try:
        models = _load_provider(provider)
    except Exception as exc:
        return f"Error listing models for {provider}: {exc}"

    if model_filter:
        models = [m for m in models if model_filter in m.model_id.lower()]

    if not models:
        return (f"No models found for {provider}"
                + (f" matching '{model_filter}'" if model_filter else ""))

    out = [f"**{provider}** — {len(models)} models"
           + (f" matching `{model_filter}`" if model_filter else "")]
    for m in models[:20]:
        out.append(f"  `{m.model_id}`")
    if len(models) > 20:
        out.append(f"  ... _and {len(models) - 20} more_")
    return "\n".join(out)


def _enrich_logs_impl(days: int = 7, recalculate: bool = False, **_kw) -> str:
    """Run the enrichment pipeline to fill $0.0000 cost rows from pricing cache."""
    import os
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, plugin_dir)
    from enrich_logs import main as _enrich_main

    from io import StringIO
    old_argv = sys.argv
    old_stdout = sys.stdout
    args_list = ["--days", str(days)]
    if recalculate:
        args_list += ["--recalculate"]
    sys.argv = ["enrich_logs.py"] + args_list

    try:
        captured = StringIO()
        sys.stdout = captured
        try:
            _enrich_main()
        finally:
            sys.stdout = old_stdout
        return captured.getvalue()
    finally:
        sys.argv = old_argv


def _compare_models_impl(model: str = "", **_kw) -> str:
    """Cross-provider price comparison for a given model."""
    from .pricing_module import _read_cache
    from decimal import Decimal

    model_lower = model.strip().lower()
    if not model_lower:
        return "Usage: /compare_models model='<model_name>'"

    cache = _read_cache()
    results = []  # list of dicts

    for provider, models in cache.items():
        if provider.startswith("_"):
            continue
        for m in models:
            mid = m.get("model_id", "")
            if model_lower in mid.lower():
                results.append({
                    "provider": provider,
                    "model_id": mid,
                    "input_cost": m.get("input_cost"),
                    "output_cost": m.get("output_cost"),
                    "cache_read_cost": m.get("cache_read_cost"),
                })

    if not results:
        return (f"No matches for '{model}' in pricing cache. "
                "Available providers: groq, fireworks, deepseek, minimax, openrouter, nvidia")

    def sort_key(r):
        ic = r["input_cost"]
        return (ic is None, Decimal(str(ic)) if ic is not None else Decimal("999999"))
    results.sort(key=sort_key)

    out = [f"**Price comparison for '{model}':**\n"]
    out.append(f"{'Provider':<14} {'Model ID':<35} {'Input/M':>10} {'Output/M':>10} {'Cache/M':>10}")
    out.append("─" * 85)

    fmt = lambda v: f"${float(v):.4f}" if v is not None else "—"
    for r in results:
        out.append(
            f"{r['provider']:<14} {r['model_id']:<35} {fmt(r['input_cost']):>10} "
            f"{fmt(r['output_cost']):>10} {fmt(r.get('cache_read_cost')):>10}"
        )

    cheapest = results[0]
    out.append(f"\n🏆 Cheapest: **{cheapest['provider']}/{cheapest['model_id']}** "
               f"at ${float(cheapest['input_cost']):.4f}/M input")
    return "\n".join(out)


# ── Handler wrappers ─────────────────────────────────────────────────────

def _handle_pricing(args, **_kw) -> str:
    return _fetch_pricing_impl(**args)


def _handle_list_models(args, **_kw) -> str:
    return _list_models_impl(**args)


def _handle_enrich_logs(args, **_kw) -> str:
    return _enrich_logs_impl(**args)


def _handle_compare_models(args, **_kw) -> str:
    return _compare_models_impl(**args)


# ── JSON Schemas ─────────────────────────────────────────────────────────

FETCH_PRICING_SCHEMA = {
    "name": "fetch_pricing",
    "description": (
        "Fetch live model pricing from a provider. Returns input/output cost per million tokens. "
        "No API key required — uses public pricing pages and open /v1/models endpoints. "
        "Provider names: deepseek, openrouter, groq, fireworks, together, mistral, cohere, minimax, nvidia, all"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "provider": {
                "type": "string",
                "description": "Provider name to fetch pricing for. Use 'all' to get all providers at once.",
            },
        },
        "required": [],
    },
}

LIST_MODELS_SCHEMA = {
    "name": "list_models",
    "description": "List available model IDs from a provider. Works without API key.",
    "parameters": {
        "type": "object",
        "properties": {
            "provider": {
                "type": "string",
                "description": "Provider to list models from — openrouter, nvidia, groq, together, deepseek.",
            },
            "model_filter": {
                "type": "string",
                "description": "Optional substring to filter model IDs by (case-insensitive).",
            },
        },
        "required": [],
    },
}

ENRICH_LOGS_SCHEMA = {
    "name": "enrich_logs",
    "description": (
        "Enrich token-logger CSV files with live pricing from the pricing-tools cache. "
        "Fills $0.0000 cost rows with actual per-token costs. "
        "Backs up each file before overwriting."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "Number of days of logs to enrich (default: 7)",
                "default": 7,
            },
            "recalculate": {
                "type": "boolean",
                "description": "Recalculate even if cost is already set (default: false)",
                "default": False,
            },
        },
        "required": [],
    },
}

COMPARE_MODELS_SCHEMA = {
    "name": "compare_models",
    "description": (
        "Compare pricing for a specific model across all providers in the cache. "
        "Shows cheapest provider first."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "description": "Model name or substring to search for (e.g. 'deepseek-v4', 'llama')",
            },
        },
        "required": ["model"],
    },
}


# ── Plugin registration ──────────────────────────────────────────────────

def register(ctx) -> None:
    _register_commands()

    # Slash commands
    ctx.register_command(
        name="pricing",
        handler=lambda args="all", **_: _fetch_pricing_impl(provider=args),
        description="Fetch live model pricing from a provider",
        args_hint="[deepseek|openrouter|groq|fireworks|together|mistral|cohere|minimax|all]",
    )
    ctx.register_command(
        name="models",
        handler=lambda args="openrouter", **_: _list_models_impl(provider=args),
        description="List available models from a provider",
        args_hint="[openrouter|nvidia|groq|together|deepseek]",
    )

    # Tools
    ctx.register_tool(
        name="fetch_pricing",
        toolset="pricing-tools",
        schema=FETCH_PRICING_SCHEMA,
        handler=_handle_pricing,
        emoji="💲",
        description=FETCH_PRICING_SCHEMA["description"],
    )
    ctx.register_tool(
        name="list_models",
        toolset="pricing-tools",
        schema=LIST_MODELS_SCHEMA,
        handler=_handle_list_models,
        emoji="📋",
        description=LIST_MODELS_SCHEMA["description"],
    )
    ctx.register_tool(
        name="enrich_logs",
        toolset="pricing-tools",
        schema=ENRICH_LOGS_SCHEMA,
        handler=_handle_enrich_logs,
        emoji="💰",
        description=ENRICH_LOGS_SCHEMA["description"],
    )
    ctx.register_tool(
        name="compare_models",
        toolset="pricing-tools",
        schema=COMPARE_MODELS_SCHEMA,
        handler=_handle_compare_models,
        emoji="📊",
        description=COMPARE_MODELS_SCHEMA["description"],
    )

    logger.info("pricing-tools loaded — /pricing, /models, enrich_logs, compare_models available")