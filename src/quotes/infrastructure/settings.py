"""Process-environment settings."""

from __future__ import annotations

import os
from collections.abc import Mapping


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
