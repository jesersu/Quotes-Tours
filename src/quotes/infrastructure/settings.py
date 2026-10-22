"""Process-environment settings."""

from __future__ import annotations

import os
from collections.abc import Mapping

LLM_PROVIDERS = ("ollama", "anthropic")
DEFAULT_LLM_PROVIDER = "ollama"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"
DEFAULT_OLLAMA_MODEL = "qwen2.5:14b"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"


class MissingSetting(Exception):
    """Raised when a required environment variable is unset or blank."""


class InvalidSetting(Exception):
    """Raised when an environment variable holds a value that is not allowed."""


def database_url(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    value = source.get("DATABASE_URL", "").strip()
    if not value:
        raise MissingSetting(
            "DATABASE_URL is not set. Export it (e.g. `set -a; source .env; set +a`); "
            "see .env.example."
        )
    return value


def anthropic_api_key(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    value = source.get("ANTHROPIC_API_KEY", "").strip()
    if not value:
        raise MissingSetting(
            "ANTHROPIC_API_KEY is not set. Export it (e.g. `set -a; source .env; set +a`); "
            "see .env.example."
        )
    return value


def llm_provider(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    value = source.get("QUOTES_LLM_PROVIDER", "").strip().lower() or DEFAULT_LLM_PROVIDER
    if value not in LLM_PROVIDERS:
        # The value is not echoed: a mistyped variable could hold anything.
        raise InvalidSetting(f"QUOTES_LLM_PROVIDER must be one of: {', '.join(LLM_PROVIDERS)}.")
    return value


def llm_model(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    default = DEFAULT_ANTHROPIC_MODEL if llm_provider(env) == "anthropic" else DEFAULT_OLLAMA_MODEL
    return source.get("QUOTES_LLM_MODEL", "").strip() or default


def ollama_host(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    return source.get("OLLAMA_HOST", "").strip().rstrip("/") or DEFAULT_OLLAMA_HOST
