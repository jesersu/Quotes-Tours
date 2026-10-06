"""Safety guard for the integration-test database.

The fixtures drop the ``quotes`` schema and install stand-ins for Supabase objects, so they
must never run against a shared or remote database. There is deliberately no override.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from psycopg.conninfo import conninfo_to_dict

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_LOOPBACK_ADDRS = frozenset({"127.0.0.1", "::1"})
# Always redirect the connection when set, whatever the DSN says.
_REDIRECTING_ENV = ("PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR")


class UnsafeTestDatabase(RuntimeError):
    """Raised when TEST_DATABASE_URL does not point at a local database."""


def _is_local(host: str) -> bool:
    return host in _LOCAL_HOSTS or host.startswith("/")  # leading slash: unix socket directory


def _split(value: str | None) -> list[str]:
    return [h for h in (value or "").split(",") if h]


def assert_local_database(dsn: str, env: Mapping[str, str] | None = None) -> None:
    """Refuse any DSN that is not explicitly local.

    libpq fills missing parameters from ``PG*`` variables and service files, so the DSN must
    name its own local host and the environment must not be able to redirect it. Messages never
    include the password or the full DSN.
    """
    env = os.environ if env is None else env
    params = conninfo_to_dict(dsn)

    if params.get("service"):
        raise UnsafeTestDatabase(
            "Refusing to run integration tests: the DSN uses a 'service' entry, which can "
            "point at a remote database. Name a local host explicitly instead."
        )
    redirecting = [name for name in _REDIRECTING_ENV if env.get(name)]
    if redirecting:
        raise UnsafeTestDatabase(
            f"Refusing to run integration tests: {', '.join(redirecting)} is set and can "
            "redirect the connection. Unset it for the test run."
        )
    env_host = env.get("PGHOST", "")
    if env_host and not all(_is_local(h) for h in _split(env_host)):
        raise UnsafeTestDatabase(
            "Refusing to run integration tests: PGHOST is set to a non-local value. "
            "Unset it for the test run."
        )

    hosts = _split(params.get("host"))
    if not hosts:
        raise UnsafeTestDatabase(
            "Refusing to run integration tests: the DSN must name a local host explicitly "
            "(localhost, 127.0.0.1, ::1 or a unix socket directory)."
        )
    remote = [h for h in hosts if not _is_local(h)]
    remote += [a for a in _split(params.get("hostaddr")) if a not in _LOOPBACK_ADDRS]
    if remote:
        raise UnsafeTestDatabase(
            f"Refusing to run integration tests against non-local host(s): {', '.join(remote)}. "
            "They drop the 'quotes' schema and install test stand-ins; use a local scratch "
            "database (localhost, 127.0.0.1, ::1 or a unix socket)."
        )
