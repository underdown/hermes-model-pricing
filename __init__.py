"""pricing-tools — Hermes plugin for model pricing and model discovery.

Provides /pricing [provider] and /models [provider] commands for Discord, Telegram,
and other gateway platforms. Pricing data is fetched live from provider APIs and
public pricing pages — no API key required.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


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


def _handle_pricing(args, **_kw) -> str:
    """Tool handler — registry passes (args, **kw) so extract provider from dict."""
    return _fetch_pricing_impl(**args)


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
        return f"No models found for {provider}" + (f" matching '{model_filter}'" if model_filter else "")

    out = [f"**{provider}** — {len(models)} models" + (f" matching `{model_filter}`" if model_filter else "")]
    for m in models[:20]:
        out.append(f"  `{m.model_id}`")
    if len(models) > 20:
        out.append(f"  ... _and {len(models) - 20} more_")
    return "\n".join(out)


def _handle_list_models(args, **_kw) -> str:
    """Tool handler — registry passes (args, **kw) so extract provider/model_filter from dict."""
    return _list_models_impl(**args)


# -----------
# JSON Schema for tools
# -----------

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
    "description": (
        "List available model IDs from a provider. Works without API key."
    ),
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


def register(ctx) -> None:
    _register_commands()

    # Register as gateway slash commands (for Discord, Telegram, etc.)
    # The gateway calls handler(user_args_string), which we convert to a dict.
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

    logger.info("pricing-tools plugin loaded — /pricing and /models available")