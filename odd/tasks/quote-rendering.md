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
- T1 and T2 are authorized (T2 on 2026-10-08). T3 to T6 are planned and wait for the owner's go-ahead.

## Constraints
- Public repository: no real prices, margins, supplier data, company identity or company images are committed.
- Prices come only from the domain pricing engine.
- Python 3.12 is the minimum version. Ruff line length 100.

## TDD
- Test-first for behavior changes. Runner: `.venv/bin/pytest`.
- The PDF compile test needs `tectonic` and is skipped when it is not installed (CI does not have it).

## Tasks
- [x] T1 — Branding split: public style file, public example company, private company data and images. Route: inline (one non-trivial file, the test; the rest is a mechanical port of the existing template). Evidence: RED (`ModuleNotFoundError: quotes.infrastructure.latex`) then GREEN 6 passed in `tests/infrastructure/test_latex_branding.py`, including the `tectonic` compile in Spanish and English; full suite 292 passed, 16 skipped; `ruff check` and `ruff format --check` clean. Checked by eye: a sample document compiles to 2 pages with the example company (placeholder boxes) and with the private company data and its 4 images; extracted text keeps `¿ ¡ ñ ü`. Changes from the source template: company data removed, a guard that fails when the company file is not loaded first, `\ifdraft` defaults to final when undeclared, a Unicode font (TeX Gyre Heros) under XeTeX/LuaTeX because the pdfLaTeX font setup misplaces `¿` and `¡` there, and the logo falls back to a placeholder box like the other images.
- [x] T2 — `QuoteRequest` and the `build_quote` use case (catalog lookup, lines, `price_quote`). Route: delegated writer (two non-trivial files; the reading that prepares the write went with it). Files: `src/quotes/application/quote.py` (154 lines), `tests/application/test_quote.py` (320 lines); about 474 lines, over the 400-line heuristic because the tests were kept in full. Evidence, writer: RED (`ModuleNotFoundError: quotes.application.quote`) then GREEN 43 passed; full suite 340 passed, 16 skipped; ruff clean. Parent: structural readback of `quote.py` (no money arithmetic outside the domain; only the two allowed files changed) and spot check re-running the full suite, `ruff check` and `ruff format --check` with the same results. Contract for the next tasks: `RequestedItem(item_id, days=None, quantity=None)`, `RequestedExtra(label, items)`, `QuoteRequest(days, travelers, items, extras=(), paid_locally=())`, `QuotedLine(entry, line)`, `QuotedExtra(label, lines, breakdown)`, `Quote(request, lines, breakdown, extras, paid_locally)`, `build_quote(request, catalog, policy)`. Notes: per-item `days` overrides the request's; duplicate `paid_locally` ids are rejected in the request because `price_quote` does not check them; duplicate extra labels and a `PER_UNIT` item without quantity are rejected by the domain when `build_quote` runs.
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

- Range main..d2bcbd1 (same code plus the review log above, 6 files, 542 lines): the stop hook raised the accumulated branch as a new target; consent granted by owner; reliability lens APPROVED; acknowledged (lineage review-1480f6d51d3b35fd). Same advisories, plus S: a `\CoLang` value other than exactly `en` silently produces Spanish.
- Follow-up commit `fix(infrastructure): harden brand style placeholders and diagnostics` addresses the three warnings, at the owner's request:
  - Placeholder: file names and paths are printed through `\coverbatim` (detokenized). RED: a missing image named with an underscore failed the build, confirming the advisory. GREEN after the fix.
  - Diagnostics: `\brandingdiag` now uses `\coimgstatus`, which looks in the local `assets/` first and then in `\CoAssetsDir`, like the image macros. RED (`\coimgstatus` undefined) then GREEN, with one image only in each folder and an assets path containing an underscore.
  - Coverage: the compile tests now assert through the log that the declared language is the one resolved, that a document with no declarations is Spanish and final, that `\drafttrue` is respected, and that loading the style without the company file fails with the guard message. These four passed on first run; they add proof, not a behaviour change. The compile runs with the document folder as working directory.
  - Evidence: 11 passed in `tests/infrastructure/test_latex_branding.py`; full suite 297 passed, 16 skipped; ruff clean; the real-data sample still compiles to 2 pages.
- Range main..380a61c (the branch with that follow-up, 6 files, 661 lines): consent granted by owner; reliability lens APPROVED; acknowledged (lineage review-ad8aba73c72b9c5d). Merged as PR #6. New advisories, non-blocking, none verified: W no automated test includes an image from the company folder (checked by hand only); S a missing image leaves no trace in the log, so a final document can ship with placeholder boxes (worth a log warning in T4); S the placeholder test asserts compile only; S `\CoEmail` and `\CoWeb` are printed raw, so an underscore in them would break the build.
- T2, commit 8083a03 (range main..8083a03, 3 files, 483 lines): assess risk=medium, review_due=slice_budget_reached; consent granted by owner; reliability lens APPROVED; acknowledged (lineage review-257c235eab44391f). Advisory, non-blocking: W extras were paired with their breakdowns by position and no test used two extras; S a non-list collection raised a bare `TypeError` and a text `paid_locally` was split into characters; S untested combinations (explicit quantity on a non-`PER_UNIT` item, per-item days inside an extra, a non-text local payment id).
- Follow-up commit `fix(application): match extras by label and reject non-list collections`, at the owner's request, addresses the warning and the first suggestion. Extras are now matched to their breakdown by label; a test with two extras passes even when the pricing function returns them reversed (RED with positional pairing, then GREEN). `items`, `extras` and `paid_locally` given as `None`, a number or text raise `InvalidPricingInput` (RED: 8 cases raised `TypeError`; GREEN). Evidence: 61 passed in `tests/application/test_quote.py`; full suite 358 passed, 16 skipped; ruff clean. The third suggestion is not addressed.
- Not addressed (owner's call): the pdfLaTeX font branch is not compiled anywhere (no pdfLaTeX on this machine or in CI); CI still runs only the regex tests because it has no `tectonic`; the three suggestions and the `\CoLang` one.

- T2 done on branch `feat/render-02-build-quote` (from main 248ee14).

## Next step
Before T3, read the price table layout from a hand-written quote; then owner go-ahead for T3. Before T3, read the price table layout from a hand-written quote.
