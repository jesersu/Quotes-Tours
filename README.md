# Quotes-Tours

Generates bilingual (English/Spanish) tour itineraries with options and prices for Colca Star Tours, as LaTeX (`.tex`) and PDF.

## Architecture (hexagonal, light)

```
src/quotes/
  domain/          # pure business rules (pricing), no I/O
  application/     # use cases (coming)
  infrastructure/  # adapters: Excel, LLM, RAG, LaTeX (coming)
```

Prices are computed only by the domain pricing engine, never by an LLM.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check .
```

Business data (price spreadsheets) is never committed; this repository is public.
