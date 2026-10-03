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

## Phase 1b — business rules confirmed by owner (2026-10-03)
- Margin applies to the full subtotal (confirmed).
- No commercial USD rounding for now: final price is in PEN (sale PEN); USD is shown as a converted reference (sale PEN / FX, 2 decimals).
- FX default 3.5 (overridable per quote).
- Optional extras: same margin, no rounding, never added to the main total.
- Travelers = adults + children with ages. Children under 6: free on everything. Children 6-15: free on PER_GROUP/PER_DAY items (transport, guide); per-person items use an optional child unit price (e.g. buffet lunch has a child price), otherwise same as adult (e.g. hot springs).
- Colca tourist ticket is NOT priced by us: paid directly by the tourist at the valley entrance. Shown as information only (Latin American / Foreign adult, child 6-15), like the "paid locally" section in LaTeX quotes. Not in subtotal/margin/total.
- Per-person reference price divides by paying travelers (adults), not by all travelers.

- [x] T5 — Travelers (adults + child ages) + child pricing rules (under 6 free; child unit price on per-person items). Route: delegated writer. Evidence: RED: collection failed (no `quotes.domain.travelers`, no `build_line`); GREEN: all domain tests pass, ruff clean. Replaces `quantity_for` with `build_line(item, days, travelers)` returning a `QuoteLine(quantity, child_quantity)`; `price_quote`/`price_optional_extras` take `Travelers`. Base 0321c90.
- [x] T6 — Policy update: FX default 3.5, optional rounding (disabled by default), USD as reference; extras without rounding. Route: delegated writer. Evidence: RED: 7 new tests failed (`fx_rate` required, no rounding default, final PEN derived from rounded USD); GREEN: 78 passed, ruff clean. Previous commit 33ce506. `usd_rounding_step: Decimal | None = None`; extras always priced with rounding off.
- [ ] T7 — Info-only items paid locally (Colca ticket by visitor category, adult/child), excluded from totals. Route: delegated writer.
- [ ] T8 — Per-person reference price by adults. Route: delegated writer.

## Acceptance criteria
- A synthetic 2D1N quote (transport flat + guide per day + lunch/ticket per person) yields correct subtotal, margin, sale PEN, USD rounded up to step, final PEN, per-person USD.
- Invalid input rejected: negative prices, zero/negative pax or days, margin < 0, FX <= 0, mixed currencies.
- `ruff check` and `pytest` pass.

## Open questions (do not block)
- USD rounding step: off by default (owner decision); optional `usd_rounding_step` kept for later.
- FX: default 3.5, overridable per quote.
- Children aged 16-17 are priced as adults (assumption, coded in `travelers.py`); confirm with the owner.

## Progress
- Branch: `feat/pricing-01-domain` (main holds scaffold).

## Review log
- T1–T4 (range main..0321c90): assess risk=medium, review_due=slice_budget_reached; consent granted by owner; reliability lens APPROVED; acknowledged (gentle-ai.review-acknowledged/v1, lineage review-0cbbbd015315e2db). Advisory (non-blocking) R3-001: no test for non-finite Decimal strings ('NaN', 'Infinity') in money.to_decimal. Reviewed boundary advances to 0321c90.

## Next step
Phase 1b T5–T8 (delegated writer, strict TDD); next review base = 0321c90.
