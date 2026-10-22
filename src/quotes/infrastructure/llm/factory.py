"""Pick the planner adapter from the environment (``QUOTES_LLM_PROVIDER``, default ollama)."""

from __future__ import annotations

from collections.abc import Mapping

from quotes.application.planner import PlannerUnavailable, QuotePlanner
from quotes.infrastructure.settings import (
    anthropic_api_key,
    llm_model,
    llm_provider,
    ollama_host,
)

__all__ = ["planner_from_env"]


def planner_from_env(env: Mapping[str, str] | None = None) -> QuotePlanner:
    """The configured planner: a local Ollama model by default, Anthropic when asked for."""
    if llm_provider(env) == "anthropic":
        try:
            import anthropic
        except ImportError as exc:
            raise PlannerUnavailable(
                "the [llm] extra is not installed: pip install -e '.[llm]'"
            ) from exc
        from quotes.infrastructure.llm.anthropic_planner import AnthropicQuotePlanner

        client = anthropic.Anthropic(api_key=anthropic_api_key(env))
        return AnthropicQuotePlanner(client, llm_model(env))
    from quotes.infrastructure.llm.ollama_planner import OllamaQuotePlanner

    return OllamaQuotePlanner(ollama_host(env), llm_model(env))
