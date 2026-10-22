# Feature: quote-planner (Phase 4: LLM planner)

## Objective
Turn a client's free-text message into a draft quote request that the owner reviews, and later join the
owner's catalog descriptions into fluent day-by-day text.

## Problem / Why
Today the owner writes every request YAML by hand. The pricing, catalog and PDF chain is deterministic
and tested (Phase 3), so the model only has to fill the request.

## Decisions
- 2026-10-21: plan approved by the owner. Order: T7–T9 in `odd/tasks/quote-rendering.md` first, then
  this feature.
- The LLM selects catalog ids and writes text from owner-written descriptions. It never sets prices or
  the margin, and it never adds facts.
- Everything the LLM produces goes into a draft with `needs_review: true`; `quote build` refuses it until
  the owner reviews it and sets the margin.
- Provider confirmed by the owner 2026-10-21 (Phase 4 plan approved the same day): Anthropic Python SDK as an optional extra; default model `claude-sonnet-5-5`, overridable with
  `QUOTES_LLM_MODEL`; key in `ANTHROPIC_API_KEY`.
- RAG is deferred: about 30 catalog items fit in the prompt.

## Constraints
- Public repository: no real prices, margins, client messages or company data committed; tests synthetic.
- What is sent to the provider: the client message and the price-free catalog view (ids, names, category,
  unit, duration, region, descriptions). Never prices, margin or company identity.
- CI has no secrets: tests use a fake client; a live test is marked `llm` and skipped without the key.
- Errors never echo the API key or the client message.

## Tasks
- [x] P1 — `parse_quote_request(data)` split from `read_quote_request(path)`; `dump_quote_request` writer
  (header, money as quoted text, any float refused); review gate `needs_review` / `review_hints`:
  `needs_review: true` raises `RequestNeedsReview` alone, before structural checks, and `quote build`
  prints only the hints and exits 1 without touching the catalog; a non-bool flag or bad hints are
  ordinary problems; an empty margin reads `pricing.margin_rate: set the margin for this quote`.
  Route: delegated writer. Commit `feat: read quote drafts and refuse them until reviewed` on
  `feat/planner-01-request-draft`. Evidence: RED recovered by stashing the two source files (CLI: 4
  failed, e.g. `assert 2 == 0` for a reviewed request; reader tests: `ImportError: cannot import name
  'HEADER'`), then GREEN: 756 passed, 20 skipped; ruff clean. Parent: readback of the writer and suite
  spot check. Review: assess `medium`, 367 lines, not due (`under_budget`); pending in the slice.
- [x] P2 — `application/planner.py`: price-free `PlannerItem` / `PlannerLocalPayment` / `PlannerCatalog`
  built by `planner_catalog(catalog)`; `PlannedItem`, `PlannedExtra`, `PlannedDay`, `PlannedOption`,
  `PlannedRequest`; `QuotePlanner` protocol; `PlannerUnavailable`. `to_request_data` writes the request
  shape with `needs_review: true`, `signed_by: null` and `margin_rate: null` (the gate stops parsing
  first; once cleared the reader asks for both), always adds the two owner-only hints, drops unknown
  ids and empty extras with a hint each, and keeps an empty option with a hint. Route: delegated
  writer. Branch `feat/planner-02-port` stacked on P1; commit `feat(application): add the price-free
  planner port`. Evidence: RED (`ModuleNotFoundError: quotes.application.planner`) then GREEN 771
  passed, 20 skipped; ruff clean; a test walks every view field and asserts no money and no
  synthetic price string. Parent: readback (imports only `quotes.application.catalog`), suite spot
  check.
- [ ] P3 — Anthropic adapter: optional extra `[llm]`, `settings.anthropic_api_key(env)`, tool use with a
  JSON schema whose ids are an enum of catalog ids, `PlannerUnavailable`, fake client capturing the payload.
- [ ] P4 — `quotes quote plan <message.txt> [-o] [--force]`: writes the draft under
  `data/private/quotes/`, prints path and counts only; CLI dispatch on `quote_command`; `main(planner=)`.
- [ ] P5 — Day text: `DayFacts` + `DayWriter` port; a second forced tool `write_day_texts` joins each
  day's descriptions into a paragraph stored as `itinerary[].text` (still `needs_review: true`); the
  renderer prints it under `\dayhead`, then the service names; without text the output is unchanged.

## Acceptance criteria
- A real client message produces a draft that, after owner review, builds a PDF with `quote build`.
- No price, margin or company datum appears in the provider payload or in console output.

## Delivery
Strategy `ask-on-risk`; forecast about 1.6k authored lines (P1 300, P2 300, P3 350, P4 250, P5 400); one
stacked PR per task.

## Progress
- T7–T9 merged into `main` (PRs #15–#17, af07b29); colcaStarTours migration merged (#98) and applied.
- P1 note: the first writer run stopped after writing the implementation but no tests; RED is recovered honestly by stashing the two source files, running the new tests against the old code, then restoring them.
- P1 started 2026-10-21 on branch `feat/planner-01-request-draft` from `main` (af07b29). Route: delegated writer (reader, CLI and their tests).

## Next step
P3: the Anthropic adapter (optional `[llm]` extra, fake client in tests).
