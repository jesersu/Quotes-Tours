"""LLM adapters. Ollama needs nothing extra; Anthropic needs the `llm` extra."""

from quotes.infrastructure.llm.factory import planner_from_env

__all__ = ["planner_from_env"]
