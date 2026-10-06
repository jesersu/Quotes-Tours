# Quotes-Tours

Generates bilingual (English/Spanish) tour itineraries with options and prices for Colca Star Tours, as LaTeX (`.tex`) and PDF.

## Architecture (hexagonal, light)

```
src/quotes/
  domain/          # pure business rules (pricing), no I/O
  application/     # use cases (coming)
  infrastructure/  # adapters: Postgres catalog (done); Excel, LLM, RAG, LaTeX (coming)
```

Prices are computed only by the domain pricing engine, never by an LLM.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check .
```

## Database

The pricing catalog lives in the `quotes` schema of the shared Postgres (read-only access).

- `DATABASE_URL`: read-only connection (see `.env.example`). Load it with `set -a; source .env; set +a`.
- `TEST_DATABASE_URL`: scratch database for integration tests. The tests refuse to run unless
  the DSN names an explicit local host (`localhost`, `127.0.0.1`, `::1` or a unix socket
  directory); a DSN without a host, or with a `service` entry, is rejected. They also refuse to
  run while `PGSERVICE`, `PGSERVICEFILE` or `PGHOSTADDR` is set, or `PGHOST` is set to a
  non-local value, because these variables can redirect the connection. There is no override.
  Its fixture drops and recreates the `quotes` schema and creates the roles `anon` and
  `authenticated`, `public.app_role`, `public.set_updated_at` and `public.has_role` only when
  they do not already exist (existing objects are never replaced).

```bash
createdb quotes_test   # any local scratch Postgres 14+
TEST_DATABASE_URL=postgresql://localhost/quotes_test .venv/bin/pytest
```

Without `TEST_DATABASE_URL` the integration tests are skipped. `tests/sql/quotes_schema.sql` is a
vendored copy of the colcaStarTours migration. The drift test compares it only when
`COLCASTAR_REPO` points at a colcaStarTours checkout (checked locally; not enforced in CI); if the
variable is set but the migration file is missing, the test fails.

## Checking the catalog

```bash
set -a; source .env; set +a
.venv/bin/quotes catalog check
```

Loads the active catalog and prints the counts plus one line per issue (`error <id>: ...`,
`warning <id>: ...`, errors first). Rows that cannot be mapped (for example an active local payment
item whose prices are not entered yet) are reported and excluded instead of crashing; local items
missing a visitor category and an empty catalog are warnings. Exit codes: `0` no errors
(warnings allowed), `1` at least one error, `2` configuration or connection failure (the message
never includes the connection string).

## Loading prices from the spreadsheet

Everything under `data/private/` (and every `*.xlsx`) is git-ignored: prices never reach this public
repository. No write credential is needed; the owner pastes the generated SQL into the Supabase SQL
Editor.

1. **Draft.** Propose entries from the sheet (default sheet `PRECIOS GENERAL`, header on `NOMBRE` /
   `PRECIO`):

   ```bash
   .venv/bin/quotes catalog draft path/to/prices.xlsx            # -> data/private/catalog-draft.yaml
   # options: --sheet "PRECIOS GENERAL"  -o <file>  --force
   ```

   The command prints counts and the output path only (never prices) and refuses to overwrite an
   existing file without `--force`. The heuristics (category, unit, duration, English name, the
   Colca tourist ticket as a paid-locally item) are documented in
   `src/quotes/application/catalog_proposal.py`.
2. **Review.** Open the YAML, fix every entry (unit, English name, child price, the two missing
   visitor-category prices of the local payment), then set `needs_review: false` on each one.
3. **SQL.** Generate the import script; it refuses while any entry still needs review, a local
   price is null, or a value is invalid, and lists the reasons:

   ```bash
   .venv/bin/quotes catalog sql data/private/catalog-draft.yaml  # -> data/private/catalog-import.sql
   ```

   The script is one `begin; ... commit;` of upserts (re-running it is safe; no deletes, no DDL)
   with a commented verification query at the end.
4. **Apply and check.** Paste the script into the Supabase SQL Editor and run it, then:

   ```bash
   set -a; source .env; set +a
   .venv/bin/quotes catalog check
   ```

Business data (price spreadsheets) is never committed; this repository is public.
