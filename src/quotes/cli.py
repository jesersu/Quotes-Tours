"""Command-line entry point: ``quotes catalog check``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from typing import TextIO

import psycopg

from quotes.application.catalog import CatalogLoad, CatalogRepository
from quotes.infrastructure.postgres_catalog import PostgresCatalogRepository
from quotes.infrastructure.settings import MissingSetting, database_url

EXIT_OK = 0
EXIT_CATALOG_ERRORS = 1
EXIT_UNAVAILABLE = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quotes")
    commands = parser.add_subparsers(dest="command", required=True)
    catalog = commands.add_parser("catalog", help="catalog commands")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    catalog_commands.add_parser("check", help="load the catalog and report invalid rows")
    return parser


def _report(loaded: CatalogLoad, out: TextIO) -> None:
    catalog = loaded.catalog
    print("Catalog check", file=out)
    print(f"  pricing items: {len(catalog.items())}", file=out)
    print(f"  local payment items: {len(catalog.local_payments())}", file=out)
    print(f"  errors: {len(loaded.errors)}, warnings: {len(loaded.warnings)}", file=out)
    for issue in (*loaded.errors, *loaded.warnings):
        print(f"{issue.severity} {issue.subject_id}: {issue.message}", file=out)
    if not loaded.issues:
        print("No issues found.", file=out)


def main(
    argv: Sequence[str] | None = None,
    *,
    repository: CatalogRepository | None = None,
    env: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    args = _parser().parse_args(argv)
    assert (args.command, args.catalog_command) == ("catalog", "check")
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    try:
        repo = (
            repository if repository is not None else PostgresCatalogRepository(database_url(env))
        )
        loaded = repo.load()
    except MissingSetting as exc:
        print(f"error: {exc}", file=err)
        return EXIT_UNAVAILABLE
    except psycopg.Error as exc:
        # Never echo the driver message: it can contain parts of the connection string.
        print(
            f"error: cannot load the catalog ({type(exc).__name__}); "
            "check DATABASE_URL, network access and role permissions.",
            file=err,
        )
        return EXIT_UNAVAILABLE
    _report(loaded, out)
    return EXIT_OK if loaded.ok else EXIT_CATALOG_ERRORS
