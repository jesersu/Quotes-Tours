-- [vendored] Verbatim copy of db/migrations/2026-10-04-quotes-pricing-schema.sql
-- [vendored] from the colcaStarTours repository (DDL applied to the shared Supabase database).
-- [vendored] Used only to build a throwaway test database; tests/infrastructure/test_schema_drift.py
-- [vendored] fails when this copy diverges from the source. Do not edit by hand: re-vendor it.
-- 2026-10-04 — Internal quotes pricing schema (`quotes`)
--
-- WHY THIS FILE EXISTS
-- The quote generator (a Python service) and the admin panel need one shared
-- source of truth for INTERNAL pricing: costs, per-person and per-group prices,
-- and the amounts a tourist pays directly on site (e.g. the Colca tourist
-- ticket, shown for information only and never added to a quote total). That
-- data must never be reachable with the public anon key, so it lives in its
-- own schema `quotes` behind three independent barriers:
--   1. the schema is revoked from public/anon/authenticated and must not be
--      added to the Supabase API "Exposed schemas";
--   2. Row Level Security on every table, with a staff-only policy
--      (has_role('admin') or has_role('editor'));
--   3. a least-privilege login role `quotes_generator` with SELECT only.
--
-- Intentionally NOT mirrored in src/server/db/schema.ts: the public site must
-- never read this schema.
--
-- SAFE: additive only. A new schema, two enums, three tables and one role; no
-- existing object is changed. Idempotent: it can be applied more than once.
-- Reuses public.set_updated_at() and public.has_role(). The role has no
-- password until the owner sets one by hand (see barrier 3).
--
-- ROLLBACK (destroys every row in the quotes schema; export first):
--   drop schema if exists quotes cascade;
--   drop role if exists quotes_generator;
--   -- drop role fails while the role still owns objects or holds grants; the
--   -- schema drop above removes its grants on quotes objects.
--
-- Mirrors db/schema.sql. Apply by hand in the Supabase SQL Editor, then run
-- 2026-10-04-quotes-pricing-schema.verify.sql.

create schema if not exists quotes;

-- ---------- Enums ----------
do $$
begin
  if not exists (select 1 from pg_type t join pg_namespace n on n.oid = t.typnamespace
                 where n.nspname = 'quotes' and t.typname = 'pricing_unit') then
    create type quotes.pricing_unit as enum ('group','day','person','unit');
  end if;
  if not exists (select 1 from pg_type t join pg_namespace n on n.oid = t.typnamespace
                 where n.nspname = 'quotes' and t.typname = 'visitor_category') then
    create type quotes.visitor_category as enum ('latin_american_adult','foreign_adult','child_6_15');
  end if;
end $$;

-- ---------- Pricing catalog ----------
create table if not exists quotes.pricing_items (
  id              text primary key
                  check (id ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  category        text not null check (length(btrim(category)) > 0),
  name_es         text not null check (length(btrim(name_es)) > 0),
  name_en         text not null check (length(btrim(name_en)) > 0),
  unit            quotes.pricing_unit not null,
  price_pen       numeric(10,2) not null check (price_pen >= 0),
  child_price_pen numeric(10,2) check (child_price_pen >= 0),
  duration_days   int check (duration_days > 0),
  active          boolean not null default true,
  notes           text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint pricing_items_child_price_only_per_person
    check (child_price_pen is null or unit = 'person')
);

drop trigger if exists pricing_items_updated_at on quotes.pricing_items;
create trigger pricing_items_updated_at before update on quotes.pricing_items
  for each row execute function public.set_updated_at();

-- ---------- Local payments (paid by the tourist on site; information only) ----------
create table if not exists quotes.local_payment_items (
  id         text primary key
             check (id ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  name_es    text not null check (length(btrim(name_es)) > 0),
  name_en    text not null check (length(btrim(name_en)) > 0),
  notes      text,
  active     boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists local_payment_items_updated_at on quotes.local_payment_items;
create trigger local_payment_items_updated_at before update on quotes.local_payment_items
  for each row execute function public.set_updated_at();

create table if not exists quotes.local_payment_prices (
  item_id          text not null references quotes.local_payment_items(id) on delete cascade,
  visitor_category quotes.visitor_category not null,
  price_pen        numeric(10,2) not null check (price_pen >= 0),
  updated_at       timestamptz not null default now(),
  primary key (item_id, visitor_category)
);

drop trigger if exists local_payment_prices_updated_at on quotes.local_payment_prices;
create trigger local_payment_prices_updated_at before update on quotes.local_payment_prices
  for each row execute function public.set_updated_at();

-- ---------- Access control: barrier 1, no API access ----------
-- Do NOT add `quotes` to Supabase > Settings > API > "Exposed schemas": the
-- Data API must never serve this schema. The revokes below hold even if it is.
revoke all on schema quotes from public, anon, authenticated;
revoke all on all tables in schema quotes from public, anon, authenticated;
revoke all on all sequences in schema quotes from public, anon, authenticated;
revoke all on all functions in schema quotes from public, anon, authenticated;
alter default privileges in schema quotes revoke all on tables    from public, anon, authenticated;
alter default privileges in schema quotes revoke all on sequences from public, anon, authenticated;
alter default privileges in schema quotes revoke all on functions from public, anon, authenticated;

-- ---------- Access control: barrier 2, Row Level Security (staff only) ----------
alter table quotes.pricing_items        enable row level security;
alter table quotes.local_payment_items  enable row level security;
alter table quotes.local_payment_prices enable row level security;

drop policy if exists "staff manage pricing_items" on quotes.pricing_items;
create policy "staff manage pricing_items" on quotes.pricing_items
  for all using (public.has_role('admin') or public.has_role('editor'))
  with check (public.has_role('admin') or public.has_role('editor'));

drop policy if exists "staff manage local_payment_items" on quotes.local_payment_items;
create policy "staff manage local_payment_items" on quotes.local_payment_items
  for all using (public.has_role('admin') or public.has_role('editor'))
  with check (public.has_role('admin') or public.has_role('editor'));

drop policy if exists "staff manage local_payment_prices" on quotes.local_payment_prices;
create policy "staff manage local_payment_prices" on quotes.local_payment_prices
  for all using (public.has_role('admin') or public.has_role('editor'))
  with check (public.has_role('admin') or public.has_role('editor'));

-- ---------- Access control: barrier 3, read-only login role for the generator ----------
-- Created WITHOUT a password. The owner sets it by hand in the Supabase SQL
-- Editor, never in a repository:
--   alter role quotes_generator with password '<generated secret>';
-- Through the Supabase pooler the username is `quotes_generator.<project-ref>`.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'quotes_generator') then
    create role quotes_generator login noinherit;
  end if;
end $$;

grant usage on schema quotes to quotes_generator;
grant select on quotes.pricing_items, quotes.local_payment_items, quotes.local_payment_prices
  to quotes_generator;

drop policy if exists "generator reads pricing_items" on quotes.pricing_items;
create policy "generator reads pricing_items" on quotes.pricing_items
  for select to quotes_generator using (true);

drop policy if exists "generator reads local_payment_items" on quotes.local_payment_items;
create policy "generator reads local_payment_items" on quotes.local_payment_items
  for select to quotes_generator using (true);

drop policy if exists "generator reads local_payment_prices" on quotes.local_payment_prices;
create policy "generator reads local_payment_prices" on quotes.local_payment_prices
  for select to quotes_generator using (true);
