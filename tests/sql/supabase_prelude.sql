-- Minimal stand-ins for the Supabase objects the quotes migration depends on.
-- Test-only: lets the vendored DDL run on a plain Postgres. Idempotent.

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
  if not exists (select 1 from pg_type t join pg_namespace n on n.oid = t.typnamespace
                 where n.nspname = 'public' and t.typname = 'app_role') then
    create type public.app_role as enum ('admin', 'editor', 'user');
  end if;
end $$;

create or replace function public.set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

-- Policies reference has_role(); tests connect as a superuser that bypasses RLS, so a
-- constant answer is enough.
create or replace function public.has_role(required public.app_role) returns boolean
language sql stable as $$ select false $$;
