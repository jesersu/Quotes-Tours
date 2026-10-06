"""The vendored quotes DDL must match the migration in the colcaStarTours repository.

Runs only when COLCASTAR_REPO points at a colcaStarTours checkout (checked locally; not
enforced in CI). If the variable is set but the migration is missing, that is a
misconfiguration and the test fails.
"""

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = Path("db/migrations/2026-10-04-quotes-pricing-schema.sql")
VENDORED = REPO_ROOT / "tests" / "sql" / "quotes_schema.sql"
HEADER_PREFIX = "-- [vendored]"


def _strip_header(text: str) -> str:
    lines = text.splitlines(keepends=True)
    while lines and lines[0].startswith(HEADER_PREFIX):
        lines.pop(0)
    return "".join(lines)


def test_vendored_ddl_matches_source_migration():
    root = os.environ.get("COLCASTAR_REPO")
    if not root:
        pytest.skip("COLCASTAR_REPO is not set (path to a colcaStarTours checkout)")
    source = Path(root) / MIGRATION
    assert source.is_file(), f"COLCASTAR_REPO is set but the migration is missing: {source}"
    assert _strip_header(VENDORED.read_text()) == source.read_text()


def test_vendored_header_is_marked():
    assert VENDORED.read_text().startswith(HEADER_PREFIX)


def test_vendored_header_does_not_claim_ci_enforcement():
    header = "".join(
        line
        for line in VENDORED.read_text().splitlines(keepends=True)
        if line.startswith(HEADER_PREFIX)
    )
    assert "COLCASTAR_REPO" in header
    assert "not enforced in CI" in header
