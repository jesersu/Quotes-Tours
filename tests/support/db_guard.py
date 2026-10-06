"""Safety guard for the integration-test database.

The fixtures drop the ``quotes`` schema and install stand-ins for Supabase objects, so they
must never run against a shared or remote database. There is deliberately no override.
"""

from __future__ import annotations

from psycopg.conninfo import conninfo_to_dict

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class UnsafeTestDatabase(RuntimeError):
    """Raised when TEST_DATABASE_URL does not point at a local database."""


def _is_local(host: str) -> bool:
    return host in _LOCAL_HOSTS or host.startswith("/")  # leading slash: unix socket directory


def assert_local_database(dsn: str) -> None:
    params = conninfo_to_dict(dsn)
    targets = [h for key in ("host", "hostaddr") for h in (params.get(key) or "").split(",") if h]
    remote = [h for h in targets if not _is_local(h)]
    if remote:
        raise UnsafeTestDatabase(
            f"Refusing to run integration tests against non-local host(s): {', '.join(remote)}. "
            "They drop the 'quotes' schema and install test stand-ins; use a local scratch "
            "database (localhost, 127.0.0.1, ::1 or a unix socket)."
        )
