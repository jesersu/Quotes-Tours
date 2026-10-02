# Feature: pricing-engine (Phase 0 + Phase 1)

## Objective
Deterministic, tested pricing engine that reproduces how Colca Star prices a quote in its spreadsheet (`precio-colca-valley.xlsx`, sheets `P-C-2D1N*`), so later phases (LLM planner, LaTeX renderer) never compute prices.

## Problem / Why
Prices are hand-calculated in Excel and hand-copied into LaTeX. The AI must never invent or compute prices; a pure domain engine is the single source of truth for money.

## Pricing model observed in the Excel
- Catalog items with a unit price in soles (PEN), e.g. transport by duration (flat per group), guide per day, meals per person, tickets per person.
- Line cost = unit price × quantity (quantity = days, people, or 1 depending on item).
- Subtotal = sum of included lines.
- Margin = subtotal × margin rate (configurable per quote).
- Sale price PEN = subtotal + margin.
- Sale price USD = sale PEN / FX (configurable per quote) → rounded UP to a commercial step (e.g. 512.34 → 550 with step 50).
- Final PEN = rounded USD × FX.
- Optional extras (LaTeX sections D/E) are priced separately and not in the main total.

## Scope
- Phase 0: repo scaffold (pyproject, pytest, ruff, README, CI workflow).
- Phase 1: `src/quotes/domain/` — Money/Currency, PricingUnit, CatalogItem, QuoteLine, PricingPolicy (margin, FX, USD rounding step), PriceBreakdown, OptionalExtra pricing, per-person total.

## Constraints
- Pure Python, no I/O in domain; `Decimal` for money, never float.
- Repo is PUBLIC: no real Excel, no real supplier prices in tests (synthetic numbers with the same structure).
- Strict TDD: RED → GREEN → REFACTOR.
- Hexagonal light: domain knows nothing about Excel/LLM/LaTeX.

## TDD
- Mode: strict (source: user global config "Strict TDD Mode: enabled").
- Runner: `.venv/bin/pytest`.

## Tasks
- [x] T0 — Scaffold: pyproject (Python >=3.12, hatchling, pytest, ruff), README, CI (GitHub Actions: ruff + pytest). Route: inline (mechanical). Evidence: commit 4939f9e on main; `ruff check` passed, `pytest` 1 passed (smoke).
- [x] T1 — Money + Currency (Decimal, add/multiply, currency mismatch error, 2-decimal quantization). Route: delegated writer. Evidence: commit 2f5c9e8; RED: `pytest tests/domain/test_money.py` failed at collection (no `quotes.domain.errors`); GREEN: 15 new tests, 16 total passed; ruff check/format clean.
- [x] T2 — CatalogItem + PricingUnit (PER_GROUP, PER_DAY, PER_PERSON, PER_UNIT) + QuoteLine cost. Route: delegated writer. Evidence: commit 3f54fa3; RED: `pytest tests/domain/test_catalog.py` failed at collection (no `quotes.domain.catalog`); GREEN: 16 new tests, 32 total passed; ruff clean.
- [x] T3 — PricingPolicy + PriceBreakdown: subtotal, margin, sale PEN, USD conversion, round-up step, final PEN, per-person. Route: delegated writer. Evidence: commit f38bb15; RED: `pytest tests/domain/test_pricing.py` failed at collection (no `quotes.domain.pricing`); GREEN: 18 new tests, 50 total passed; ruff clean.
- [x] T4 — Optional extras priced separately with same policy. Route: delegated writer. Evidence: commit see `git log` (`feat(domain): price optional extras separately`); RED: `pytest tests/domain/test_extras.py` failed at collection (no `quotes.domain.extras`); GREEN: 6 new tests, 56 total passed; ruff clean.

## Acceptance criteria
- A synthetic 2D1N quote (transport flat + guide per day + lunch/ticket per person) yields correct subtotal, margin, sale PEN, USD rounded up to step, final PEN, per-person USD.
- Invalid input rejected: negative prices, zero/negative pax or days, margin < 0, FX <= 0, mixed currencies.
- `ruff check` and `pytest` pass.

## Open questions (do not block)
- USD rounding step: default 50, configurable.
- FX: configurable per quote.
- Children pricing: not in the Excel. Not modeled yet.

## Progress
- Branch: `feat/pricing-01-domain` (main holds scaffold).

## Next step
T1–T4 done on `feat/pricing-01-domain`; next: native review/PR slicing decision.
