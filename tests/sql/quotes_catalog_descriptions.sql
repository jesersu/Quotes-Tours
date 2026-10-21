-- [vendored] Verbatim copy of db/migrations/2026-10-21-quotes-catalog-descriptions.sql
-- [vendored] from the colcaStarTours repository (DDL applied to the shared Supabase database).
-- [vendored] Used only to build a throwaway test database, applied after quotes_schema.sql.
-- [vendored] tests/infrastructure/test_schema_drift.py compares it with the source when COLCASTAR_REPO is set (checked locally; not enforced in CI).
-- [vendored] Do not edit by hand: re-vendor it.
-- 2026-10-21 — Region and descriptions on quote pricing items
--
-- WHY THIS FILE EXISTS
-- The quote generator now builds a day-by-day itinerary. Each day needs base
-- text written by the owner (in Spanish and English), and the planner needs to
-- group services by region ("everything in Puno"). Facts come from these
-- owner-written columns; a language model may later join them into fluent
-- text, but never adds facts.
--
-- SAFE: additive only. Three nullable text columns on quotes.pricing_items; a
-- value, when present, must not be blank. No row is altered. Idempotent. The
-- existing table-level SELECT grant to quotes_generator already covers new
-- columns; anon and authenticated stay revoked.
--
-- ROLLBACK (loses the descriptions; export first):
--   alter table quotes.pricing_items drop column if exists description_en;
--   alter table quotes.pricing_items drop column if exists description_es;
--   alter table quotes.pricing_items drop column if exists region;
--
-- Mirrors db/schema.sql. Apply by hand in the Supabase SQL Editor, then run
-- 2026-10-21-quotes-catalog-descriptions.verify.sql.

alter table quotes.pricing_items
  add column if not exists region         text check (region is null or length(btrim(region)) > 0),
  add column if not exists description_es text check (description_es is null or length(btrim(description_es)) > 0),
  add column if not exists description_en text check (description_en is null or length(btrim(description_en)) > 0);
