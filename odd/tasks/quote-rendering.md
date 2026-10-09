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

## Review log
- T1, commit 08a9f64 (range main..08a9f64, 6 files, 532 lines): assess risk=medium, review_due=slice_budget_reached; consent granted by owner; reliability lens APPROVED; acknowledged (gentle-ai.review-acknowledged/v1, lineage review-ab3070fdc65d427a). Reviewed boundary advances to 08a9f64.
- Advisory, non-blocking (owner decides; none verified by the parent yet):
  - W: the missing-image placeholder prints the raw file name in `\texttt`; a name with `_`, `&` or `#` would break the build in the very case the fallback exists for.
  - W: `\brandingdiag` is not exercised by any test, prints the folder path raw, and checks only `\CoAssetsDir` while the image macros look in the local `assets/` first.
  - W: untested paths: the guard when the company file is missing, the undeclared draft switch, the default language and image folder, `\drafttrue`, and the pdfLaTeX font branch. In CI only the regex tests run.
  - S: the definition regex sees only braced `\newcommand`-style forms, not `\def`, `\edef` or `\let`.
  - S: with `tectonic` installed but offline or with a cold cache, the compile test fails or times out instead of skipping; glyphs are checked by eye only.
  - S: nothing asserts that the `.tex` files ship in a non-editable install.

## Next step
Owner decides on the advisory items, then go-ahead for T2. Before T3, read the price table layout from a hand-written quote.
