# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Bilingual (EN/ES) tour quote generator for Colca Star Tours. Target output is LaTeX/PDF itineraries
with prices. Today the repository holds the pricing domain, the catalog read model with its Postgres
adapter, and a CLI to audit the catalog and to load prices from the owner's spreadsheet. The LLM
planner, RAG and LaTeX renderer are not built yet.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

.venv/bin/pytest                                              # whole suite
.venv/bin/pytest tests/domain/test_pricing.py                 # one file
.venv/bin/pytest tests/domain/test_pricing.py::test_name      # one test
.venv/bin/pytest -m "not integration"                         # skip Postgres tests explicitly

.venv/bin/ruff check .
.venv/bin/ruff format --check .                               # CI fails on unformatted code

.venv/bin/quotes catalog check                                # needs DATABASE_URL
.venv/bin/quotes catalog draft <prices.xlsx>                  # -> data/private/catalog-draft.yaml
.venv/bin/quotes catalog sql data/private/catalog-draft.yaml  # -> data/private/catalog-import.sql
```

Load the environment with `set -a; source .env; set +a` (see `.env.example`).

CI (`.github/workflows/ci.yml`) runs `ruff check`, `ruff format --check`, and `pytest` on Python 3.12
and 3.14 against a Postgres 16 service. 3.12 is the minimum supported version, so do not use newer
syntax.

### Integration tests

Tests marked `integration` need `TEST_DATABASE_URL` and are skipped without it:

```bash
createdb quotes_test
TEST_DATABASE_URL=postgresql://localhost/quotes_test .venv/bin/pytest
```

`tests/support/db_guard.py` refuses any DSN that does not name an explicit local host, and refuses to
run while `PGSERVICE`, `PGSERVICEFILE`, `PGHOSTADDR` or a non-local `PGHOST` is set. There is no
override, because the fixture drops and recreates the `quotes` schema. Do not weaken this guard.

`tests/sql/quotes_schema.sql` is a vendored copy of a migration owned by the separate colcaStarTours
repository. `tests/infrastructure/test_schema_drift.py` compares the two only when `COLCASTAR_REPO`
points at a checkout of it (local only, not enforced in CI). Schema changes belong in that
repository; update the vendored copy to match.

## Hard rules

- **The repository is public.** Real prices, margins and supplier data never get committed. `*.xlsx`,
  `data/private/` and `.env` are git-ignored; tests use synthetic numbers with the same structure.
  CLI commands print counts and paths, never prices, and error messages never include the
  connection string.
- **Prices come only from the domain pricing engine**, never from an LLM or from ad-hoc arithmetic
  in adapters.
- **Money is `Decimal`.** `to_decimal` rejects floats and bools on purpose; pass `Decimal`, `int`
  or `str`.
- **Database access is read-only.** `DATABASE_URL` is a read-only connection to the `quotes` schema
  of a shared Supabase Postgres. Writes happen only through the generated SQL script, which the
  owner pastes into the Supabase SQL Editor. Do not add a write path or a write credential.

## Architecture

Light hexagonal layout under `src/quotes/`. Dependencies point inward:
`cli` -> `infrastructure` -> `application` -> `domain`.

- `domain/` is pure: frozen dataclasses that validate in `__post_init__` and raise
  `InvalidPricingInput` (a `DomainError`). No I/O.
- `application/` holds the catalog read model (`Catalog`, `CatalogEntry`, `LocalPaymentEntry`), the
  `CatalogRepository` port, `audit_catalog`, and the pure spreadsheet heuristics in
  `catalog_proposal.py`. `CatalogEntry` wraps a domain `CatalogItem` with what the future planner
  and renderer need (category, bilingual names, duration); the domain item stays minimal.
- `infrastructure/` holds the adapters: Postgres catalog, in-memory catalog (tests), Excel reader,
  YAML draft read/validate, SQL renderer, settings, safe file output.
- `cli.py` is the composition root and owns exit codes: `0` ok (warnings allowed), `1` catalog
  errors, `2` configuration, connection or file problem.

### Pricing rules (`domain/pricing.py`, `catalog.py`, `travelers.py`, `extras.py`)

These were confirmed by the business owner and are easy to break by "fixing" them:

- Catalog prices are in PEN. `subtotal -> margin on the full subtotal -> sale PEN`.
- The final price is the PEN sale price; USD is a converted reference (`sale PEN / fx_rate`,
  default 3.5). Commercial USD round-up exists (`usd_rounding_step`) but is off by default; when
  on, final PEN is derived back from the rounded USD.
- `build_line(item, days, travelers)` turns a `PricingUnit` into quantities. Children under 6 are
  free on everything. Children 6-15 are free on `PER_GROUP`/`PER_DAY` items and use
  `child_unit_price` on `PER_PERSON` items when present, otherwise the adult price.
- Per-person reference prices divide by `Travelers.full_fare_count` (adults), not all travelers.
- Optional extras are priced separately with the same margin, never rounded, never added to the
  main total.
- Paid-locally items (`LocalPaymentInfo`, e.g. the Colca tourist ticket by visitor category) are
  information only. They travel through `price_quote(..., paid_locally=)` into the breakdown and
  never enter subtotal, margin or totals.

### Catalog loading tolerates bad rows

`PostgresCatalogRepository` reads active rows from `quotes.pricing_items` and
`quotes.local_payment_items`. A row that cannot be mapped is excluded and reported as a
`CatalogIssue` inside `CatalogLoad` instead of raising, so `quotes catalog check` can list every
problem in one run. Keep that behavior when adding columns or mappings.

### Spreadsheet-to-catalog pipeline

`xlsx -> draft YAML -> owner review -> SQL -> owner applies it`

1. `excel_price_sheet.read_price_rows` reads the sheet (default `PRECIOS GENERAL`, header located
   by `NOMBRE` / `PRECIO`) into raw rows.
2. `catalog_proposal.propose_catalog` guesses category, unit, duration and English name from
   keywords. The rule table lives in that module's docstring; keep it in sync with the code. Every
   proposed entry is `needs_review: true`.
3. `catalog_draft.validate_draft` refuses a draft while any entry still needs review, a local price
   is null, or a value is invalid, and returns all reasons together.
4. `catalog_sql.render_sql` emits one `begin; ... commit;` of upserts: idempotent, no deletes, no
   DDL. Every value goes through the `quote_*` helpers in that module; never interpolate draft
   values into SQL directly.

`output_file.write_new_file` refuses to overwrite without `--force`.

## Conventions

- Ruff: line length 100, rules `E, F, I, B, UP, SIM`.
- Tests mirror the source layout (`tests/domain`, `tests/application`, `tests/infrastructure`).
  Behavior changes are developed test-first (RED, GREEN, refactor).
- `odd/tasks/<feature>.md` are the feature documents: scope, owner-confirmed business decisions,
  task checklist and evidence. Read the relevant one before changing pricing or catalog behavior,
  and update it when the work is tracked there.
- Conventional Commits.
