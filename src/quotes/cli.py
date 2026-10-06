"""Command-line entry point: ``quotes catalog check|draft|sql``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

import psycopg

from quotes.application.catalog import CatalogLoad, CatalogRepository
from quotes.application.catalog_proposal import propose_catalog
from quotes.infrastructure.catalog_draft import dump_draft
from quotes.infrastructure.excel_price_sheet import DEFAULT_SHEET, SheetError, read_price_rows
from quotes.infrastructure.output_file import OutputExists, write_new_file
from quotes.infrastructure.postgres_catalog import PostgresCatalogRepository
from quotes.infrastructure.settings import MissingSetting, database_url

EXIT_OK = 0
EXIT_CATALOG_ERRORS = 1
EXIT_UNAVAILABLE = 2  # configuration, connection or file problem
DEFAULT_DRAFT = Path("data/private/catalog-draft.yaml")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quotes")
    commands = parser.add_subparsers(dest="command", required=True)
    catalog = commands.add_parser("catalog", help="catalog commands")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    catalog_commands.add_parser("check", help="load the catalog and report invalid rows")
    draft = catalog_commands.add_parser(
        "draft", help="propose a reviewable catalog draft from the price spreadsheet"
    )
    draft.add_argument("workbook", type=Path)
    draft.add_argument("--sheet", default=DEFAULT_SHEET)
    draft.add_argument("-o", "--output", type=Path, default=DEFAULT_DRAFT)
    draft.add_argument("--force", action="store_true", help="overwrite an existing output file")
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


def _draft(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    try:
        sheet = read_price_rows(args.workbook, args.sheet)
        proposal = propose_catalog(list(sheet.rows))
        write_new_file(args.output, dump_draft(proposal.as_dict()), force=args.force)
    except (SheetError, OutputExists) as exc:
        print(f"error: {exc}", file=err)
        return EXIT_UNAVAILABLE
    except OSError as exc:
        print(f"error: cannot write {args.output} ({type(exc).__name__})", file=err)
        return EXIT_UNAVAILABLE
    print("Catalog draft", file=out)
    print(f"  pricing items: {len(proposal.pricing_items)}", file=out)
    print(f"  local payments: {len(proposal.local_payments)}", file=out)
    if sheet.skipped_rows:
        rows = ", ".join(str(r) for r in sheet.skipped_rows)
        print(f"  skipped rows (name or price missing/invalid): {rows}", file=out)
    print(f"  written to: {args.output}", file=out)
    print("Review every entry, then set needs_review: false.", file=out)
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None,
    *,
    repository: CatalogRepository | None = None,
    env: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    args = _parser().parse_args(argv)
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if args.catalog_command == "draft":
        return _draft(args, out, err)
    assert args.catalog_command == "check"
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
