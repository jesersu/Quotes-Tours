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
- `TEST_DATABASE_URL`: scratch database for integration tests. They drop and recreate the
  `quotes` schema there, so never use a real database.

```bash
createdb quotes_test   # any scratch Postgres 14+
TEST_DATABASE_URL=postgresql://localhost/quotes_test .venv/bin/pytest
```

Without `TEST_DATABASE_URL` the integration tests are skipped. `tests/sql/quotes_schema.sql` is a
vendored copy of the colcaStarTours migration; a drift test compares it when that repository is
found next to this one (or at `COLCASTAR_REPO`).

Business data (price spreadsheets) is never committed; this repository is public.
