"""Process-environment settings."""

from __future__ import annotations

import os
from collections.abc import Mapping

DEFAULT_LLM_MODEL = "claude-sonnet-5-5"


class MissingSetting(Exception):
    """Raised when a required environment variable is unset or blank."""


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


def llm_model(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    return source.get("QUOTES_LLM_MODEL", "").strip() or DEFAULT_LLM_MODEL
