-- Minimal stand-ins for the Supabase objects the quotes migration depends on.
-- Test-only: lets the vendored DDL run on a plain Postgres. Idempotent and non-clobbering:
-- every object is created only if it does not already exist.

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

-- Never replace an existing function: on a database that already has the real ones they stay.
do $$
begin
  if not exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                 where n.nspname = 'public' and p.proname = 'set_updated_at') then
    create function public.set_updated_at() returns trigger
    language plpgsql as $f$
    begin
      new.updated_at = now();
      return new;
    end $f$;
  end if;

  -- Policies reference has_role(); tests connect as a superuser that bypasses RLS, so a
  -- constant answer is enough.
  if not exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                 where n.nspname = 'public' and p.proname = 'has_role') then
    create function public.has_role(required public.app_role) returns boolean
    language sql stable as $f$ select false $f$;
  end if;
end $$;
