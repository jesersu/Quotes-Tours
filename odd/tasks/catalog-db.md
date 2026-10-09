# Feature: catalog-db (Phase 2: prices in Supabase)

## Objective
Move the pricing catalog from the owner's Excel into the shared Supabase Postgres, in a dedicated non-exposed schema `quotes`, and give the generator a read-only adapter to it.

## Problem / Why
- The generator will run on a server (Phase 9); a local Excel cannot be read there.
- The admin panel (colcastar-admin) and the generator must share one source of truth.
- Prices and margins are internal business data: must never be reachable with the public anon key.

## Decisions (2026-10-04)
- One database, separate schema `quotes` (not added to Supabase API exposed schemas). Three barriers: schema not exposed + revoked from anon/authenticated, RLS (`public.has_role('admin'|'editor')`), least-privilege login role `quotes_generator` (read-only on pricing).
- Canonical DDL in colcaStarTours `db/schema.sql` + hand-applied migration `db/migrations/2026-10-04-quotes-pricing-schema.sql` (+ `.verify.sql`), following its WHY/SAFE/ROLLBACK, idempotent conventions. Not mirrored in the public site's Drizzle schema (the public site must never use it).
- Excel is used once for the initial import, then kept as a historical backup.
- Admin CRUD screens (2C) deferred; meanwhile prices are edited in the Supabase Table Editor.
- Migration applied to Supabase by Claude only after owner reviews the exact SQL and confirms the target project; the owner sets the `quotes_generator` password by hand (never committed).

## Scope
- 2A (repo colcaStarTours, branch `feat/quotes-pricing-schema` from `develop`, worktree `../colcaStarTours-quotes-schema`): schema `quotes`, tables `pricing_items`, `local_payment_items`, `local_payment_prices`, RLS, grants, role.
- 2B (this repo, branch `feat/catalog-01-db`): `CatalogRepository` port, Postgres adapter (psycopg 3), integration tests (CI Postgres service), `quotes catalog check`, Excel → draft → import.

## Constraints
- Strict TDD; synthetic data only in tests (public repo).
- No secrets in any repo. No real prices committed.
- Remote operations on Supabase only with explicit owner authorization per operation.

## TDD
- Mode: strict (user global config). Runner: `.venv/bin/pytest` (2B). 2A: SQL validated against PGlite (admin repo's dev dependency) with the Supabase prelude.

## Tasks
- [x] A1 — Migration + verify + `db/schema.sql` mirror in colcaStarTours. Route: delegated writer (3 files). Evidence: colcaStarTours commit 8276204 (feat/quotes-pricing-schema, unpushed). PGlite: RED all verify checks false; GREEN old schema + migration ×2, fresh schema, and migration over fresh schema → 12/12 checks true, 6 policies; constraint behavior checks pass. RLS enforcement not testable in PGlite (superuser). Review assess: medium, under_budget (320 lines) — pending.
- [x] A2 — Owner review of SQL; apply to Supabase; run `.verify.sql`. Route: inline, owner-authorized remote op. Evidence (2026-10-05, project `cstar`, sa-east-1): verify BEFORE all false; prerequisites present (set_updated_at, has_role, app_role, anon, authenticated); migration applied via Management API in one transaction (HTTP 201); verify AFTER 12/12 true, 6 policies; API exposed schemas = `public,graphql_public` (quotes not exposed). Owner approved each command in default permission mode. Pending owner action: set `quotes_generator` password.
- [ ] A3 — Follow-up: re-vendor `colcastar-admin/test/sql/schema.sql` (drift test). Route: inline mechanical.
- [x] B1 — `CatalogRepository` port + in-memory catalog. Route: delegated writer. Evidence: RED (ModuleNotFoundError quotes.application.catalog) then GREEN 105 passed; ruff format/check clean. `CatalogEntry`/`LocalPaymentEntry` wrap domain objects with bilingual names, category, duration, notes; domain untouched.
- [x] B2 — Postgres adapter + integration tests (CI service, `TEST_DATABASE_URL`, vendored quotes DDL + drift check). Route: delegated writer. Evidence: RED (ModuleNotFoundError settings/postgres_catalog) then GREEN against throwaway local Postgres 14: 122 passed + 1 skipped (drift, source absent); with COLCASTAR_REPO set: 123 passed; TEST_DATABASE_URL unset: 110 passed, 13 skipped. Migration runs unchanged on PG14. CI postgres:16 service added (not yet run in CI).
- [x] B3 — `quotes catalog check` + degrade instead of crash. Route: delegated writer. Evidence: RED (collection errors: missing CatalogLoad/audit_catalog/quotes.cli/build_catalog_load) then GREEN against throwaway local Postgres 14: 179 passed, 1 skipped (drift). Port is now `load() -> CatalogLoad(catalog, issues)`; bad rows become error issues and are excluded. Console script run: clean data exit 0; active local payment item without prices exit 1 with the issue listed; missing DATABASE_URL exit 2.
- [x] B4 (code) — `quotes catalog draft <xlsx>` (Excel → reviewable YAML under `data/private/`) and `quotes catalog sql <draft>` (reviewed draft → idempotent upsert SQL for the Supabase SQL Editor; validation reuses `build_catalog_load`). Route: delegated writer. Evidence: RED (ModuleNotFoundError for the new modules, twice) then GREEN against throwaway local Postgres 14: 276 passed, 1 skipped (drift); the integration test executes the generated SQL, loads it through `PostgresCatalogRepository`, re-runs it (idempotent) and applies a modified draft (upsert updates). Without `TEST_DATABASE_URL` the DB tests skip. Tested with synthetic workbooks only; the real workbook was not opened.
- [x] B4 (owner steps) — run `quotes catalog draft` on the real workbook, review `data/private/catalog-draft.yaml`, run `quotes catalog sql`, paste the SQL in the Supabase SQL Editor, run `quotes catalog check`. Route: inline, owner-authorized read-only remote op. Evidence: owner reviewed the draft and reported running the generated SQL in the SQL Editor (2026-10-06); `quotes catalog check` against the read-only `DATABASE_URL` (2026-10-08): 30 pricing items, 1 local payment item, 0 errors, 0 warnings, exit code 0.

## Acceptance criteria
- anon/authenticated have no USAGE on schema `quotes`; RLS enabled on all `quotes` tables; `quotes_generator` can only SELECT pricing tables.
- Migration is idempotent (applies twice cleanly) and matches `db/schema.sql`.
- Generator loads `CatalogItem`/`LocalPaymentInfo` from Postgres; invalid rows reported, not crashing.

## Progress
- colcaStarTours `feat/quotes-pricing-schema`: schema migration applied to Supabase (A1, A2); A3 pending.
- Quotes-Tours `feat/catalog-01-db`: B1, B2 done and reviewed; advisory fixes (unit F) applied; B3 done; B4 code done and merged (PR #2); owner import steps done, load confirmed by `quotes catalog check` (2026-10-08).

## Review log
- B1–B2 (range main..41edbf1, 19 files, 874 lines): assess risk=high (shell in ci.yml), review due; consent granted by owner; 4 lenses (risk, resilience, readability, reliability) APPROVED; acknowledged (gentle-ai.review-acknowledged/v1, lineage review-13809761c345a5f6). Reviewed boundary advances to 41edbf1.
- Advisory, non-blocking (candidates for follow-up, owner decides):
  - W: integration fixture is destructive beyond the documented scope (prelude replaces `public.has_role`/`public.set_updated_at`, creates roles) with no guard on `TEST_DATABASE_URL`.
  - W: one unmappable active row fails the whole `load()` (e.g. active local payment item with no prices yet); contradicts "reported, not crashing".
  - W: drift test default path does not match README and never runs in CI.
  - S: no connect/statement timeout; opaque unknown-unit message; `_index` getattr indirection; connection-failure test gated by DB skip; untested pricing-item mapping error and local-entry blank `name_en`; stale Progress/Next step in this doc.
- Unit F (after 41edbf1): fixed the integration fixture guard (local hosts only, non-clobbering prelude), drift test honesty (COLCASTAR_REPO), connect/statement timeouts, explicit unknown-unit/visitor-category errors, typed `_index`, ungated connection-failure test, extra mapper and blank-name tests, stale Progress. The "one unmappable row fails `load()`" advisory is addressed by B3. Not done: `.env.example` wording (file edits denied by the sandbox).
- F+B3 (range 41edbf1..23e7aec): assess medium (slice_budget_reached); consent granted by owner; reliability lens APPROVED; acknowledged (gentle-ai.review-acknowledged/v1, lineage review-893ff74f86765df0). Reviewed boundary advances to 23e7aec.
- Advisory, non-blocking (all four fixed by the follow-up commit `fix(catalog): close test-database guard bypass and review follow-ups`):
  - W: test-database guard only inspected DSN `host`/`hostaddr`; a host-less DSN, `service=`, or `PGHOST`/`PGHOSTADDR`/`PGSERVICE`/`PGSERVICEFILE` could redirect the destructive fixture. Now an explicit local host is required, `service` and those variables are rejected.
  - S: vacuous statement-timeout echo test removed (the `pg_sleep` cancellation test is the proof).
  - S: row mapper wrapper narrowed to `CatalogDataError`/`DomainError`; the domain wraps all value-level failures in `InvalidPricingInput`, and the mapper now also rejects a child price on a non-person unit. Tests added.
  - S: CLI selects the injected repository with `is None`, not truthiness.
- Still an owner task: `.env.example` wording (agents cannot read or edit it).
- ccde176 + B4 (range 23e7aec..3579f06, 24 files, 1842 lines): assess medium (slice_budget_reached); consent granted by owner; reliability lens APPROVED; acknowledged (gentle-ai.review-acknowledged/v1, lineage review-0ea61c16e08e3508). Reviewed boundary advances to 3579f06. Advisory, non-blocking (owner decides):
  - W: price-absence assertions in tests/test_cli_draft.py and tests/test_cli_sql.py can collide with digits in pytest's tmp_path (flaky).
  - W: `validate_draft` and `render_sql` disagree (NUL text, very large duration_days) → uncaught SqlLiteralError traceback in the CLI.
  - W: excel reader quantizes before the max-price check → InvalidOperation traceback on huge cell values.
  - S: slug check uses `$` (accepts trailing newline); unknown draft keys silently ignored; lazy sheet-read errors not wrapped; `--force` write not atomic and file mode untested.
- Follow-up commit `fix(catalog): harden draft and SQL export against bad input` fixes the seven advisories of lineage review-0ea61c16e08e3508: deterministic CLI price-absence assertions with synthetic prices, `validate_draft` now rejects everything the SQL renderer refuses (shared rules), huge/invalid spreadsheet prices are skipped instead of crashing, slugs use `fullmatch`, unknown draft keys are reported, lazy sheet-read failures become `SheetError`, and output files are written atomically with mode 0o600.
- e0f51e9 (range 3579f06..e0f51e9, 15 files, 507 lines): assess medium (slice_budget_reached); consent granted by owner; reliability lens APPROVED; acknowledged (gentle-ai.review-acknowledged/v1, lineage review-74fc910576eb083d). Reviewed boundary advances to e0f51e9. Advisory, non-blocking, checked by the parent:
  - W `os.link` fails on filesystems without hard links (FAT/exFAT, some mounts) → traceback on the no-force path. Real but not reachable on the owner's APFS disk. DEFERRED.
  - W NaN/inf cell test doubted by the reviewer → REFUTED: `tests/infrastructure/test_excel_price_sheet.py` passes (15 tests).
  - W no automated round trip of real `draft` output through `validate_draft` → REFUTED in practice: the owner's generated draft yields only `needs_review` (31) and null ticket prices (2), no unknown-key problems. A pinned test is still missing. DEFERRED.
  - S reader `except` region broad / message carries only the exception type; `without_path_lines` drops whole lines. DEFERRED.
  Owner agreed to stop polishing this branch after this round; deferred items are candidates for a later small commit.

## Next step
A3 (re-vendor the admin drift-test schema) is the only open task; then Phase 3.
