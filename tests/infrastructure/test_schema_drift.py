"""The vendored quotes DDL must match the migration in the colcaStarTours repository."""

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = Path("db/migrations/2026-10-04-quotes-pricing-schema.sql")
VENDORED = REPO_ROOT / "tests" / "sql" / "quotes_schema.sql"
HEADER_PREFIX = "-- [vendored]"


def _source_path() -> Path:
    root = os.environ.get("COLCASTAR_REPO")
    base = Path(root) if root else REPO_ROOT.parent.parent / "colcastar" / "colcaStarTours"
    return base / MIGRATION


def _strip_header(text: str) -> str:
    lines = text.splitlines(keepends=True)
    while lines and lines[0].startswith(HEADER_PREFIX):
        lines.pop(0)
    return "".join(lines)


def test_vendored_ddl_matches_source_migration():
    source = _source_path()
    if not source.is_file():
        pytest.skip(f"source migration not found: {source}")
    assert _strip_header(VENDORED.read_text()) == source.read_text()


def test_vendored_header_is_marked():
    assert VENDORED.read_text().startswith(HEADER_PREFIX)
