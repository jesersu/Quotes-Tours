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
- 2026-10-21, owner: use a local model through Ollama instead of a paid API ("pasemos a Ollama"), so client
  messages never leave the machine and nothing is billed. The Anthropic adapter stays as an option;
  `QUOTES_LLM_PROVIDER` picks the provider, default `ollama`. Owner's machine: Apple M3 Pro, 18 GB RAM,
  Ollama 0.33.3 installed.
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
- [x] P3 — `infrastructure/llm/anthropic_planner.py`: `AnthropicQuotePlanner(client, model, max_tokens)`
  with a duck-typed client; English system prompt (catalog ids only, never prices or margins, doubts
  in `hints`); user content = today's date, the price-free catalog as JSON lines, the client message;
  forced tool `propose_quote_request` whose item and paid-locally ids are `enum`s of catalog ids;
  malformed output → `PlannerUnavailable("unexpected planner output")`; any `create` error →
  `PlannerUnavailable("planner request failed (<type>)")`, chained. `planner_from_env` imports
  `anthropic` lazily (install hint if missing). Settings `anthropic_api_key`, `llm_model` (default
  `claude-sonnet-5-5`). Optional extra `llm = ["anthropic==1.12.0"]`: the newest release at least two
  weeks old on 2026-10-21 (1.17.0–2.1.0 were days old). Route: delegated writer; branch
  `feat/planner-03-anthropic` stacked on P2; commit `feat(infrastructure): add the Anthropic quote
  planner`. Evidence: RED (`ModuleNotFoundError: quotes.infrastructure.llm`; settings `ImportError`)
  then GREEN 803 passed, 21 skipped without `anthropic` installed; ruff clean; a test asserts no
  synthetic price string in the whole payload. Parent: readback; made the live `llm` test opt-in
  (`QUOTES_LIVE_LLM=1` plus the key) so a loaded `.env` never makes an ordinary run call the paid API.
  Pending for the owner: add `ANTHROPIC_API_KEY` (and optionally `QUOTES_LLM_MODEL`) to `.env` and
  `.env.example`, which the agent does not read.
- [x] P4 — `quotes quote plan <message.txt> [-o OUTPUT] [--force]`: reads the message (path-only errors),
  loads the catalog read-only (the planner is built only after it loads), plans, and writes the draft
  with `dump_quote_request` + `write_new_file`; default `data/private/quotes/<stem>.yaml`; refuses to
  overwrite the message itself; prints only the path and counts (options, services, hints, the hints
  count includes the two owner-only reminders); `MissingSetting` and `PlannerUnavailable` exit 2. CLI
  dispatch on `quote_command`; `main(planner=)` seam. `examples/client-message.example.txt` (invented).
  Route: delegated writer; branch `feat/planner-04-cli` stacked on P3; commit `feat(cli): draft a
  quote request from a client message`. Evidence: RED 21 failed (no `planner` keyword, no
  `planner_from_env` in the CLI) then GREEN 824 passed, 21 skipped; ruff clean; the gate end to end:
  `quote build` on a fresh draft exits 1. Parent: readback of the output lines, suite spot check.
  Review: assess `medium`, 399 lines, not due (`under_budget`). Not done: the live run, which needs
  the owner's key and authorization to send a real message.
- [x] P5 — Day text. `DayService`, `DayFacts`, `day_facts(planned, catalog)` (each option's days with a
  title or placed services, names and descriptions in the request language), `DayWriter` protocol,
  `with_day_texts` (deep copy; texts land in the right option's `itinerary`; a count mismatch or unknown
  label → `PlannerUnavailable`; blank texts skipped with a hint; a day without a title gets a "Set a
  title" hint). The Anthropic adapter adds `write_days` with forced tool `write_day_texts` (`{texts}`)
  and a prompt that allows only the given facts; no call when there are no days. `ItineraryDay.text`;
  the reader accepts `itinerary[i].text`; the renderer prints the escaped paragraph under `\dayhead`
  before the services (golden unchanged). `quote plan` writes the texts into the draft and prints
  `day texts: N`; a writer failure exits 2 and writes nothing. Route: delegated writer; branch
  `feat/planner-05-day-text` stacked on P4; commit `feat: write owner-reviewed day text from catalog
  descriptions`. Evidence: RED only as one collection `ImportError: cannot import name 'DayFacts'`
  (weak: the other new tests were not run against the old code), then GREEN 860 passed, 21 skipped;
  ruff clean. Parent: readback of the day prompt, suite spot check.

- [x] P6 — Ollama provider. `llm/planning_contract.py` holds the prompts (now "answer only with the
  requested JSON", rules unchanged), the user-content builders, the request schema (ids as `enum`), the
  day-texts schema and both parsers; `anthropic_planner.py` keeps only its tool transport.
  `OllamaQuotePlanner(host, model, transport, timeout=300)` posts to `{host}/api/chat` with
  `format` = the schema, `stream: false`, temperature 0, via `urllib` (no dependency); unreachable
  server → hint `start it with: ollama serve` (`HTTPError` excluded, the server answered); other
  errors → `planner request failed (<type>)`. Settings `InvalidSetting`, `llm_provider` (default
  `ollama`), `ollama_host` (default `http://localhost:11434`), provider-aware `llm_model`
  (`DEFAULT_OLLAMA_MODEL = "qwen2.5:14b"`, to confirm after a local trial). Neutral
  `planner_from_env` in `quotes.infrastructure.llm.factory`; the CLI imports it there and exits 2 on
  `InvalidSetting`. Includes the `R3-unknown-label-untested` test (passed at once: it pins existing
  behavior). Route: delegated writer; branch `feat/planner-06-ollama` stacked on P5; commit
  `feat(infrastructure): plan quotes with a local Ollama model`. Evidence: RED (collection
  `ImportError: cannot import name 'planner_from_env' from 'quotes.infrastructure.llm'`, missing
  `ollama_planner` and settings names) then GREEN 894 passed, 21 skipped; ruff clean. Parent: readback
  of the transport, suite spot check. Not done: the local trial with a real model.
- [x] P7 — Planner quality from the first local trial (2026-10-21, owner OK to start Ollama and pull
  `qwen2.5:14b`; invented example message; real catalog read-only). Findings: with optional top-level
  fields both `qwen2.5:7b` and `qwen2.5:14b` returned `child_ages: []` for "two children aged 9 and
  12" and skipped extras and paid-locally; the 7b also wrote day texts with invented facts (the catalog
  has no descriptions yet). Requiring every nested field made the 14b run past 10 minutes. Requiring
  only the top-level fields, adding explicit rules and capping output (`num_predict` 2048) gave
  `child_ages: [9, 12]`, the horseback ride as an extra and the Colca ticket as paid locally in about
  67 s, but still extra unrelated tickets, the ride duplicated in items, `quantity` on per-person
  items and a "Client Name" placeholder. Scope: top-level fields required; output cap; prompt rules
  (child ages, extras not duplicated, `quantity` only for `per_unit`, no unrequested services, client
  name hint); deterministic guards in `to_request_data` (drop `quantity` unless `per_unit`, drop items
  that are also extras, each with a hint); no day text for days without any description; refuse an
  empty catalog before calling; a timeout hint suggesting a smaller model; keep `qwen2.5:14b` as the
  Ollama default.
  Done: top-level fields required; `options` and each option's `items` require `minItems: 1` (after
  the writer's first version the 14b returned no options at all; found in the live rerun, fixed
  test-first by the parent); rules for child ages, extras not duplicated, `quantity` only for
  `per_unit`, "items must hold every service the requested trip needs ... leave out services for
  places or tours the client did not mention", and "a greeting such as Hello is not a name";
  `NUM_PREDICT = 2048`; guards in `to_request_data` (quantity dropped unless `per_unit`, items that are
  also extras dropped, empty client → `client: null` + "Set client"), each with a hint; day text only
  for days with a description in the request language; empty catalog refused by both adapters before
  calling; timeout hint. Route: delegated writer plus a parent correction; commit `fix: keep the local
  planner to the request and the catalog`. Evidence: writer RED 24 failed then GREEN; parent RED 4
  failed (prompt phrases, minItems) then GREEN 917 passed, 21 skipped; ruff clean. Live rerun through
  the CLI on the invented example: both models give `child_ages: [9, 12]`, the ride as an extra, the
  Colca ticket paid locally and no invented name. `qwen2.5:7b` (29 s) picked transport, guide, lunch
  and dinner; `qwen2.5:14b` (75 s) still added tickets for unrelated tours (the catalog has no region
  or descriptions yet). `quote build` refused the draft (exit 1); a reviewed copy (placeholder margin)
  built a 2-page English PDF, checked by eye. Follow-ups: one hint per dropped `quantity` is noisy
  (aggregate it); day titles repeat "Day 1:" already shown by `\dayhead`; choose the default model on
  a real message after the catalog has regions and descriptions.

## Acceptance criteria
- A real client message produces a draft that, after owner review, builds a PDF with `quote build`.
- No price, margin or company datum appears in the provider payload or in console output.

## Review log
- P1 + P2 (range af07b29..fab57d7, 893 lines): assess medium, `slice_budget_reached`; consent granted; one lens (reliability); approved and acknowledged (lineage review-a36306bd5bdf03cd); no advisories.
- P3 (range fab57d7..ef40fa3, 648 lines): assess medium, `slice_budget_reached`; consent granted; one lens (reliability); approved and acknowledged (lineage review-968287d6103ef8ad). SUGGESTIONs: `R3-missing-key-order` (`planner_from_env` checks the extra before the key) and `R3-parse-range` (the adapter does not range-check numbers; `parse_quote_request` does later). Follow-ups.
- P4 + P5 (range ef40fa3..0630ff0, 945 lines): assess medium, `slice_budget_reached`; consent granted; one lens (reliability); approved and acknowledged (lineage review-6a52c98d3070dde0). SUGGESTION `R3-unknown-label-untested` (`with_day_texts` unknown-label branch has no test): added in P6.
- P6 (range 0630ff0..8e03b78, 1145 lines): assess medium, `slice_budget_reached`; consent granted; one lens (reliability); approved and acknowledged (lineage review-b2457bace522f0b3). SUGGESTIONs: `R3-factory-import-order`, `R3-ollama-empty-schema-enum` (an empty catalog gives an empty enum), `R3-ollama-timeout-hint` (a timeout gets no specific hint); the last two are taken into P7.

## Delivery
Strategy `ask-on-risk`; forecast about 1.6k authored lines (P1 300, P2 300, P3 350, P4 250, P5 400); one
stacked PR per task.

## Progress
- T7–T9 merged into `main` (PRs #15–#17, af07b29); colcaStarTours migration merged (#98) and applied.
- P1 note: the first writer run stopped after writing the implementation but no tests; RED is recovered honestly by stashing the two source files, running the new tests against the old code, then restoring them.
- P1 started 2026-10-21 on branch `feat/planner-01-request-draft` from `main` (af07b29). Route: delegated writer (reader, CLI and their tests).

## Next step
Push P1–P7 as stacked PRs (owner's call); the owner writes regions and descriptions; then a
real client message to choose the default model. Old note — local trial: `ollama serve`, pull the model (owner OK for the download), run `quote plan` on the
invented example message, then on a real one; confirm or change `DEFAULT_OLLAMA_MODEL`. For Anthropic only — first live run: needs the owner's `ANTHROPIC_API_KEY` in `.env`, `pip install -e ".[llm]"`, and the
owner's authorization to send a real client message to Anthropic. Then push P1–P5 as stacked PRs.
