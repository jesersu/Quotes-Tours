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
- [ ] B2 — Postgres adapter + integration tests (CI service, `TEST_DATABASE_URL`, vendored quotes DDL + drift check). Route: delegated writer.
- [ ] B3 — `quotes catalog check`. Route: delegated writer.
- [ ] B4 — Excel → reviewed draft (`data/private/`) → `quotes catalog import`. Route: delegated writer.

## Acceptance criteria
- anon/authenticated have no USAGE on schema `quotes`; RLS enabled on all `quotes` tables; `quotes_generator` can only SELECT pricing tables.
- Migration is idempotent (applies twice cleanly) and matches `db/schema.sql`.
- Generator loads `CatalogItem`/`LocalPaymentInfo` from Postgres; invalid rows reported, not crashing.

## Progress
- Branches created: colcaStarTours `feat/quotes-pricing-schema` (worktree), Quotes-Tours `feat/catalog-01-db`.

## Next step
Owner: set `quotes_generator` password; decide push + PR of colcaStarTours `feat/quotes-pricing-schema` → `develop`. Then A3 and B1–B4.
