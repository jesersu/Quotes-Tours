"""Command-line entry point: ``quotes catalog check|draft|sql`` and ``quotes quote build``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import TextIO

import psycopg

from quotes.application.catalog import CatalogLoad, CatalogRepository
from quotes.application.catalog_proposal import propose_catalog
from quotes.application.quote import build_quote_options
from quotes.application.quote_rendering import QuoteDocument
from quotes.domain.errors import DomainError
from quotes.infrastructure.catalog_draft import dump_draft, load_draft, validate_draft
from quotes.infrastructure.catalog_sql import SqlLiteralError, render_sql
from quotes.infrastructure.excel_price_sheet import DEFAULT_SHEET, SheetError, read_price_rows
from quotes.infrastructure.latex.pdf import (
    PdfCompilationError,
    PdfResult,
    TectonicFailed,
    compile_pdf,
)
from quotes.infrastructure.latex.quote_renderer import LatexQuoteRenderer
from quotes.infrastructure.output_file import OutputExists, write_new_file
from quotes.infrastructure.postgres_catalog import PostgresCatalogRepository
from quotes.infrastructure.quote_request_file import InvalidRequestFile, read_quote_request
from quotes.infrastructure.settings import MissingSetting, database_url

EXIT_OK = 0
EXIT_CATALOG_ERRORS = 1
EXIT_UNAVAILABLE = 2  # configuration, connection or file problem
DEFAULT_DRAFT = Path("data/private/catalog-draft.yaml")
DEFAULT_SQL = Path("data/private/catalog-import.sql")
DEFAULT_QUOTES_DIR = Path("data/private/quotes")
DEFAULT_COMPANY = Path("data/private/branding/company.tex")
DEFAULT_ASSETS = Path("data/private/branding/assets")


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
    sql = catalog_commands.add_parser(
        "sql", help="turn a reviewed draft into an idempotent SQL script for the SQL Editor"
    )
    sql.add_argument("draft", type=Path)
    sql.add_argument("-o", "--output", type=Path, default=DEFAULT_SQL)
    sql.add_argument("--force", action="store_true", help="overwrite an existing output file")
    quote = commands.add_parser("quote", help="quote commands")
    quote_commands = quote.add_subparsers(dest="quote_command", required=True)
    build = quote_commands.add_parser("build", help="build a branded PDF from a request file")
    build.add_argument("request", type=Path)
    build.add_argument(
        "-o", "--output", type=Path, help=f"default: {DEFAULT_QUOTES_DIR}/<request name>.pdf"
    )
    build.add_argument("--force", action="store_true", help="overwrite an existing output file")
    build.add_argument("--company", type=Path, default=DEFAULT_COMPANY, help="company .tex file")
    build.add_argument("--assets", type=Path, default=DEFAULT_ASSETS, help="brand images folder")
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


def _sql(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    try:
        text = args.draft.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"error: draft not found: {args.draft}", file=err)
        return EXIT_UNAVAILABLE
    except (OSError, UnicodeDecodeError) as exc:
        print(f"error: cannot read {args.draft} ({type(exc).__name__})", file=err)
        return EXIT_UNAVAILABLE
    try:
        draft = validate_draft(load_draft(text))
    except ValueError as exc:
        print(f"error: {exc}", file=err)
        return EXIT_UNAVAILABLE
    if draft.problems:
        print(f"Draft is not ready ({len(draft.problems)} problems); no SQL written:", file=err)
        for problem in draft.problems:
            print(f"  - {problem}", file=err)
        return EXIT_CATALOG_ERRORS
    try:
        sql = render_sql(draft)
    except SqlLiteralError as exc:
        # Validation and rendering share their rules, so this is a defensive net, not a path.
        print(f"error: cannot render the SQL ({exc}); nothing written", file=err)
        return EXIT_CATALOG_ERRORS
    try:
        write_new_file(args.output, sql, force=args.force)
    except OutputExists as exc:
        print(f"error: {exc}", file=err)
        return EXIT_UNAVAILABLE
    except OSError as exc:
        print(f"error: cannot write {args.output} ({type(exc).__name__})", file=err)
        return EXIT_UNAVAILABLE
    print("Catalog SQL", file=out)
    print(f"  pricing items: {len(draft.item_rows)}", file=out)
    print(f"  local payment items: {len(draft.local_rows)}", file=out)
    print(f"  local payment prices: {len(draft.price_rows)}", file=out)
    for warning in draft.warnings:
        print(f"warning {warning}", file=out)
    print(f"  written to: {args.output}", file=out)
    print("Paste it into the Supabase SQL Editor, then run `quotes catalog check`.", file=out)
    return EXIT_OK


def _load_catalog(
    repository: CatalogRepository | None, env: Mapping[str, str] | None, err: TextIO
) -> CatalogLoad | None:
    """Load the catalog, or print the error and return None (callers exit with 2)."""
    try:
        repo = (
            repository if repository is not None else PostgresCatalogRepository(database_url(env))
        )
        return repo.load()
    except MissingSetting as exc:
        print(f"error: {exc}", file=err)
    except psycopg.Error as exc:
        # Never echo the driver message: it can contain parts of the connection string.
        print(
            f"error: cannot load the catalog ({type(exc).__name__}); "
            "check DATABASE_URL, network access and role permissions.",
            file=err,
        )
    return None


def _quote_build(
    args: argparse.Namespace,
    repository: CatalogRepository | None,
    env: Mapping[str, str] | None,
    out: TextIO,
    err: TextIO,
    today: Callable[[], date],
    compile_: Callable[..., PdfResult],
) -> int:
    try:
        wanted = read_quote_request(args.request)
    except InvalidRequestFile as exc:
        print(f"error: {args.request} cannot be used:", file=err)
        for problem in exc.problems:
            print(f"  - {problem}", file=err)
        return EXIT_UNAVAILABLE
    # LaTeX reads these through \input{} from a temporary folder, so they must be absolute.
    company = args.company.resolve()
    if not company.is_file():
        print(f"error: company file not found: {args.company}", file=err)
        return EXIT_UNAVAILABLE
    assets = args.assets.resolve()
    output = args.output or DEFAULT_QUOTES_DIR / f"{args.request.stem}.pdf"
    loaded = _load_catalog(repository, env, err)
    if loaded is None:
        return EXIT_UNAVAILABLE
    try:
        quoted = build_quote_options(wanted.options, loaded.catalog, wanted.policy)
        document = QuoteDocument(
            quoted,
            wanted.client_name,
            wanted.title,
            wanted.issued_on or today(),
            wanted.signed_by,
            wanted.language,
        )
        renderer = LatexQuoteRenderer(company, assets_dir=assets if assets.is_dir() else None)
        tex = renderer.render(document)
    except DomainError as exc:
        print(f"error: {exc}", file=err)
        return EXIT_UNAVAILABLE
    except ValueError as exc:
        print(f"error: {exc}", file=err)
        return EXIT_UNAVAILABLE
    try:
        result = compile_(tex, output, force=args.force)
    except OutputExists as exc:
        print(f"error: {exc}", file=err)
        return EXIT_UNAVAILABLE
    except TectonicFailed as exc:
        print(f"error: {exc}", file=err)
        # The log can echo document text (client names); this is the operator's own terminal.
        print("LaTeX log (may contain document text):", file=err)
        print(exc.log_tail, file=err)
        return EXIT_UNAVAILABLE
    except PdfCompilationError as exc:
        print(f"error: {exc}", file=err)
        return EXIT_UNAVAILABLE
    except OSError as exc:
        print(f"error: cannot write {output} ({type(exc).__name__})", file=err)
        return EXIT_UNAVAILABLE
    if loaded.issues:
        print(
            f"warning: the catalog reported {len(loaded.issues)} issue(s); "
            "run `quotes catalog check` for details.",
            file=err,
        )
    for name in result.missing_images:
        print(f"warning: missing image {name}", file=err)
    if result.missing_images:
        print("warning: the PDF shows placeholder boxes instead of those images.", file=err)
    print("Quote built", file=out)
    print(f"  written to: {result.path}", file=out)
    print(f"  options: {len(quoted)}", file=out)
    print(f"  services: {sum(len(option.quote.lines) for option in quoted)}", file=out)
    print(f"  optional extras: {sum(len(option.quote.extras) for option in quoted)}", file=out)
    print(f"  paid locally: {len(quoted[0].quote.paid_locally)}", file=out)
    print(f"  language: {document.language.value}", file=out)
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None,
    *,
    repository: CatalogRepository | None = None,
    env: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
    today: Callable[[], date] | None = None,
    compile: Callable[..., PdfResult] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if args.command == "quote":
        return _quote_build(
            args,
            repository,
            env,
            out,
            err,
            today if today is not None else date.today,
            compile if compile is not None else compile_pdf,
        )
    if args.catalog_command == "draft":
        return _draft(args, out, err)
    if args.catalog_command == "sql":
        return _sql(args, out, err)
    assert args.catalog_command == "check"
    loaded = _load_catalog(repository, env, err)
    if loaded is None:
        return EXIT_UNAVAILABLE
    _report(loaded, out)
    return EXIT_OK if loaded.ok else EXIT_CATALOG_ERRORS
