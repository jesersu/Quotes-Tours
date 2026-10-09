# Feature: quote-rendering (Phase 3: end-to-end quote without AI)

## Objective
Turn a hand-written quote request into a branded PDF: look the items up in the catalog, price them with the domain engine and render LaTeX. No LLM involved.

## Problem / Why
- The catalog (Phase 2) and the pricing engine (Phase 1) are not connected by any use case yet.
- Quotes are still written by hand in LaTeX, copying prices from the spreadsheet.
- `QuoteRequest` defined here is the contract the future planner (Phase 4) must produce.

## Decisions
- 2026-10-08, owner: the branding template is split. Layout and macros are public; company identity (RUC, phones, address, founder, certificate) and images stay out of the repository under `data/private/branding/`. Tests use an invented company, the same way they use invented prices.
- Source template: `docs/branding/colcastar.tex` in the private colcaStarTours checkout. It is read-only for this work and is not modified.
- Comments in the public style file are in English, following this repository's convention.
- Delivery strategy: `ask-on-risk`, chain strategy `stacked-to-main` (numbered branches merged to `main`, as in phases 1 and 2). Inferred from the repository history; the owner can change it.

## Scope
- T1 only is authorized so far. T2 to T6 are planned and wait for the owner's go-ahead.

## Constraints
- Public repository: no real prices, margins, supplier data, company identity or company images are committed.
- Prices come only from the domain pricing engine.
- Python 3.12 is the minimum version. Ruff line length 100.

## TDD
- Test-first for behavior changes. Runner: `.venv/bin/pytest`.
- The PDF compile test needs `tectonic` and is skipped when it is not installed (CI does not have it).

## Tasks
- [x] T1 — Branding split: public style file, public example company, private company data and images. Route: inline (one non-trivial file, the test; the rest is a mechanical port of the existing template). Evidence: RED (`ModuleNotFoundError: quotes.infrastructure.latex`) then GREEN 6 passed in `tests/infrastructure/test_latex_branding.py`, including the `tectonic` compile in Spanish and English; full suite 292 passed, 16 skipped; `ruff check` and `ruff format --check` clean. Checked by eye: a sample document compiles to 2 pages with the example company (placeholder boxes) and with the private company data and its 4 images; extracted text keeps `¿ ¡ ñ ü`. Changes from the source template: company data removed, a guard that fails when the company file is not loaded first, `\ifdraft` defaults to final when undeclared, a Unicode font (TeX Gyre Heros) under XeTeX/LuaTeX because the pdfLaTeX font setup misplaces `¿` and `¡` there, and the logo falls back to a placeholder box like the other images.
- [ ] T2 — `QuoteRequest` and the `build_quote` use case (catalog lookup, lines, `price_quote`). Not yet authorized.
- [ ] T3 — `QuoteRenderer` port and LaTeX adapter in Spanish (escaping, money format, price table). Not yet authorized.
- [ ] T4 — PDF compilation with `tectonic`. Not yet authorized.
- [ ] T5 — English output. Not yet authorized.
- [ ] T6 — `quotes quote build <request.yaml>` CLI command. Not yet authorized.

## Acceptance criteria
- T1: the style file defines no company data; the example company defines every field the style uses; a minimal document compiles to PDF in Spanish and English with the example company.

## Open questions
- The price table has no macro in the template. Its layout lives in each hand-written quote and has to be read from one (they contain real prices) before T3.

## Progress
- Branch `feat/render-01-branding` from `main` (50806c6).
- Forecast for T1: about 450 authored lines, most of them the ported template.

- T1 done. Private data copied to `data/private/branding/` (git-ignored, not committed).

## Next step
Owner go-ahead for T2. Before T3, read the price table layout from a hand-written quote.
