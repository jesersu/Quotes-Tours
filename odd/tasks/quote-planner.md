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
- Provider: Anthropic Python SDK as an optional extra; default model `claude-sonnet-5-5`, overridable with
  `QUOTES_LLM_MODEL`; key in `ANTHROPIC_API_KEY`.
- RAG is deferred: about 30 catalog items fit in the prompt.

## Constraints
- Public repository: no real prices, margins, client messages or company data committed; tests synthetic.
- What is sent to the provider: the client message and the price-free catalog view (ids, names, category,
  unit, duration, region, descriptions). Never prices, margin or company identity.
- CI has no secrets: tests use a fake client; a live test is marked `llm` and skipped without the key.
- Errors never echo the API key or the client message.

## Tasks
- [ ] P1 — `parse_quote_request(data)` split from `read_quote_request(path)`; `dump_quote_request` writer
  (pattern of `catalog_draft.dump_draft`); review gate `needs_review` / `review_hints`, `quote build`
  refuses while it is true (exit 1); `margin_rate: null` refused with a clear message.
- [ ] P2 — `application/planner.py`: price-free `PlannerCatalog` view, `QuotePlanner` protocol,
  `PlannedRequest`; unknown ids become review hints; output goes through `parse_quote_request`.
- [ ] P3 — Anthropic adapter: optional extra `[llm]`, `settings.anthropic_api_key(env)`, tool use with a
  JSON schema whose ids are an enum of catalog ids, `PlannerUnavailable`, fake client capturing the payload.
- [ ] P4 — `quotes quote plan <message.txt> [-o] [--force]`: writes the draft under
  `data/private/quotes/`, prints path and counts only; CLI dispatch on `quote_command`; `main(planner=)`.
- [ ] P5 — Day text: the LLM joins each day's descriptions into a paragraph stored as
  `itinerary[].text` for review; the renderer prints it under `\dayhead`, falling back to descriptions.

## Acceptance criteria
- A real client message produces a draft that, after owner review, builds a PDF with `quote build`.
- No price, margin or company datum appears in the provider payload or in console output.

## Delivery
Strategy `ask-on-risk`; forecast about 1.6k authored lines (P1 300, P2 300, P3 350, P4 250, P5 400); one
stacked PR per task.

## Progress
- Not started; waits for T7–T9.

## Next step
Start P1 after T9 is merged.
