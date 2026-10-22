-- ============================================================================
--  Plant vase monitor -- device registry + telemetry ingestion
--  Paste into: Supabase Dashboard -> SQL Editor -> New query -> Run
--
--  Target project: zubizzqwjteajycnwesf (the one the phone app points at, in
--  plantkeeper/.env). The firmware's config.py must name the same host.
--
--  Re-running this file is safe: tables are `if not exists` and functions are
--  `or replace`. It only ever adds -- with one deliberate exception: the
--  retired `rain` column is dropped (see the note on `readings`), which
--  discards the values already stored in it.
--
--  The device row is seeded separately, from seed.local.sql (gitignored), so
--  the device secret never lands in this repository. See seed.example.sql.
-- ============================================================================

-- ---------------------------------------------------------------------------
--  devices: one row per vase
--    device_uid / device_secret  -> flashed into the firmware; the secret
--                                   comes from credentials.py, not git
--    claim_code                  -> short code the user types in the phone app
--                                   to "sign the vase as their vase"
-- ---------------------------------------------------------------------------
create table if not exists public.devices (
  id            uuid primary key default gen_random_uuid(),
  device_uid    text        not null unique,
  device_secret text        not null,
  claim_code    text        not null unique,
  name          text,
  owner_id      uuid references auth.users(id) on delete set null,
  claimed_at    timestamptz,
  last_seen     timestamptz,
  created_at    timestamptz not null default now()
);

comment on table public.devices is
  'Uma linha por vaso. device_uid/secret vão gravados no firmware; claim_code é digitado no aplicativo.';

-- ---------------------------------------------------------------------------
--  readings: append-only telemetry
--
--  soil and light are an index on each module's own scale (raw / 4095 * 100),
--  not a physical unit: neither is calibrated. temperature and humidity are the
--  DHT22's real °C and %RH.
-- ---------------------------------------------------------------------------
create table if not exists public.readings (
  id          bigint generated always as identity primary key,
  device_id   uuid not null references public.devices(id) on delete cascade,
  soil        smallint check (soil  between 0 and 100),
  light       smallint check (light between 0 and 100),
  temperature numeric(4,1),
  humidity    smallint check (humidity between 0 and 100),
  created_at  timestamptz not null default now()
);

-- Retires the rain channel. It was only ever the raw analog output of the rain
-- module expressed as a percentage of ADC full scale -- with unverified polarity
-- and no calibration -- so the app can no longer label it as a measurement.
-- `drop column if exists` makes this run once and then do nothing; the values
-- already stored are gone with it.
alter table public.readings drop column if exists rain;

-- The app's history/charts query: newest-first per device.
create index if not exists readings_device_time_idx
  on public.readings (device_id, created_at desc);

-- Every device read runs through the owner policy, so this is the hot path for
-- the device list. Without it the policy is a sequential scan per request.
create index if not exists devices_owner_idx
  on public.devices (owner_id);

-- ---------------------------------------------------------------------------
--  Row Level Security
-- ---------------------------------------------------------------------------
alter table public.devices  enable row level security;
alter table public.readings enable row level security;

-- Owners may read their own device and its readings.
--
-- `(select auth.uid())` keeps the function stable for the whole statement, so
-- Postgres evaluates it once instead of once per candidate row (Supabase's
-- auth_rls_initplan advisor flags the bare form).
drop policy if exists devices_select_own on public.devices;
create policy devices_select_own on public.devices
  for select to authenticated
  using (owner_id = (select auth.uid()));

drop policy if exists readings_select_own on public.readings;
create policy readings_select_own on public.readings
  for select to authenticated
  using (exists (select 1 from public.devices d
                 where d.id = readings.device_id
                   and d.owner_id = (select auth.uid())));

-- Owners may rename their own vase.
--
-- USING keeps the update scoped to a row the caller already owns, so the policy
-- cannot be turned around and used to seize someone else's vase. WITH CHECK
-- repeats the test on the new row, which is what stops a rename from doubling
-- as a hand-off to another account -- a transfer `claim_device()` has no way to
-- undo.
--
-- Releasing is deliberately NOT expressible here, even though `owner_id` is
-- nullable. `devices_select_own` keys on `owner_id = auth.uid()`, so an UPDATE
-- that clears `owner_id` produces a new row the caller can no longer SELECT, and
-- Postgres rejects the whole statement with a row-level security violation --
-- no `WITH CHECK` can grant what the SELECT policy forbids. (Verified against a
-- real Postgres: `update devices set owner_id = null` fails with 42501 for the
-- owning user.) Releasing therefore runs outside RLS, as release_device() below.
drop policy if exists devices_update_own on public.devices;
create policy devices_update_own on public.devices
  for update to authenticated
  using (owner_id = (select auth.uid()))
  with check (owner_id = (select auth.uid()));

-- NOTE: there is deliberately NO insert policy and no write policy on
-- `readings`. Ingestion happens only through the SECURITY DEFINER function
-- below, so a leaked publishable/anon key can never write arbitrary rows or
-- enumerate other people's data. The single write surface on `devices` is the
-- UPDATE policy above, and it can only touch rows the caller already owns.

-- ---------------------------------------------------------------------------
--  ingest_reading(): the ESP32's only write path
--  Called as POST /rest/v1/rpc/ingest_reading
--  Floored at 250 ms so a looping/broken board cannot flood the table.
--
--  The argument list IS the function's identity in Postgres, so dropping the
--  retired `p_rain` parameter needs the old 7-argument signature dropped: a
--  `create or replace` with a shorter list would leave both versions installed
--  and let PostgREST pick the wrong one. The grants for the new signature are
--  re-applied with the other functions below, since dropping a function drops
--  its grants.
-- ---------------------------------------------------------------------------
drop function if exists public.ingest_reading(text, text, int, int, int, numeric, int);

create or replace function public.ingest_reading(
  p_uid    text,
  p_secret text,
  p_soil   int     default null,
  p_light  int     default null,
  p_temp   numeric default null,
  p_hum    int     default null
) returns timestamptz
language plpgsql
security definer
set search_path = public
as $$
declare
  v_id  uuid;
  v_now timestamptz := now();
begin
  select id into v_id
    from devices
   where device_uid = p_uid
     and device_secret = p_secret;

  if v_id is null then
    raise exception 'unknown device' using errcode = '28000';
  end if;

  -- simple flood guard: ignore samples arriving faster than 4 Hz
  if exists (select 1 from readings
              where device_id = v_id
                and created_at > v_now - interval '250 milliseconds') then
    return v_now;
  end if;

  insert into readings (device_id, soil, light, temperature, humidity, created_at)
  values (v_id, p_soil, p_light, p_temp, p_hum, v_now);

  update devices set last_seen = v_now where id = v_id;
  return v_now;
end;
$$;

-- ---------------------------------------------------------------------------
--  claim_device(): "sign the vase as my vase"
--  Called by the phone app (authenticated) as POST /rest/v1/rpc/claim_device
--  Bind-once: a code can never be re-claimed by someone else.
-- ---------------------------------------------------------------------------
create or replace function public.claim_device(p_code text)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  v_id uuid;
begin
  if auth.uid() is null then
    raise exception 'not authenticated' using errcode = '28000';
  end if;

  update devices
     set owner_id = auth.uid(), claimed_at = now()
   where upper(claim_code) = upper(trim(p_code))
     and owner_id is null
  returning id into v_id;

  if v_id is null then
    raise exception 'invalid or already-claimed code' using errcode = '22023';
  end if;

  return v_id;
end;
$$;

-- ---------------------------------------------------------------------------
--  release_device(): give a vase back
--  Called by the phone app (authenticated) as POST /rest/v1/rpc/release_device
--
--  Clears the owner so the vase is free for anyone to claim again. This cannot
--  be a plain UPDATE from the app (see the note on devices_update_own), so it
--  runs as the table owner -- and therefore re-checks ownership in its own body
--  before touching anything.
-- ---------------------------------------------------------------------------
create or replace function public.release_device(p_id uuid)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  v_id uuid;
begin
  if auth.uid() is null then
    raise exception 'not authenticated' using errcode = '28000';
  end if;

  update devices
     set owner_id = null, claimed_at = null
   where id = p_id
     and owner_id = auth.uid()
  returning id into v_id;

  if v_id is null then
    raise exception 'device not found or not owned by caller' using errcode = '22023';
  end if;

  return v_id;
end;
$$;

-- ---------------------------------------------------------------------------
--  ping(): the firmware's boot-time probe
--  SECURITY INVOKER and constant-returning, so it proves PostgREST and this
--  schema are live without touching a table and can be granted to anon.
-- ---------------------------------------------------------------------------
create or replace function public.ping()
returns text
language sql
stable
security invoker
set search_path = ''
as $$ select 'pong'::text $$;

comment on function public.ping() is
  'Sonda sem tabela usada pelo firmware para confirmar que o schema foi aplicado.';

-- ---------------------------------------------------------------------------
--  Making the tables reachable through the Data API
--
--  RLS decides which ROWS a role may see; it does not decide whether the role
--  may touch the table at all. PostgREST needs both, so grant just the reads
--  the app performs. `anon` deliberately gets no table access at all: the only
--  unauthenticated paths into this schema are ingest_reading() and ping().
--
--  Supabase matters here: its schema-wide default privileges hand anon and
--  authenticated ALL on every new table, sequence and function. Adding grants
--  on top of that does NOT narrow anything -- on a fresh project anon would
--  still hold INSERT/UPDATE/DELETE/TRUNCATE on both tables, and owners could
--  rewrite device_secret and claim_code with a plain update. The revokes below
--  are what make the grants below them meaningful; without them this file is
--  only least-privilege on a bare Postgres.
-- ---------------------------------------------------------------------------
revoke all on table public.devices  from anon;
revoke all on table public.readings from anon;

revoke insert, update, delete, truncate, references, trigger, maintain
  on table public.devices from authenticated;
revoke insert, update, delete, truncate, references, trigger, maintain
  on table public.readings from authenticated;

-- Ingestion runs through ingest_reading() (SECURITY DEFINER), so neither role
-- needs sequence access on the readings identity column.
revoke all on sequence public.readings_id_seq from anon, authenticated;

grant select on public.devices  to authenticated;
grant select on public.readings to authenticated;

-- Renaming is the app's only direct write, granted per column so the fields the
-- UI never edits cannot be reached even with a valid session -- and the policy
-- above still decides which rows are in play. Releasing goes through
-- release_device() instead; see the note on that policy.
grant update (name) on public.devices to authenticated;

-- ---------------------------------------------------------------------------
--  Function access
--
--  Postgres grants EXECUTE to PUBLIC on every new function, and the three
--  table-touching functions below are SECURITY DEFINER -- they run as the table
--  owner and bypass RLS. Left as-is that makes them callable by any role, so
--  revoke the default and hand out only what each caller needs:
--    ingest_reading() <- the firmware, which holds the publishable key (anon)
--    ping()           <- the firmware's health probe (anon)
--    claim_device()   <- a signed-in user, whose uid is checked in the body
--    release_device() <- a signed-in user, ditto
--
--  The default privileges also grant EXECUTE to anon explicitly, which the
--  `revoke ... from public` below does not remove. Revoke anon by name from the
--  two app-only functions, or the publishable key can reach them (harmless only
--  because each checks auth.uid(), but the intent is already clear).
-- ---------------------------------------------------------------------------
revoke execute on function
  public.ingest_reading(text, text, int, int, numeric, int) from public;
revoke execute on function public.ping() from public;
revoke execute on function public.claim_device(text) from public;
revoke execute on function public.release_device(uuid) from public;

revoke execute on function public.ping()              from authenticated;
revoke execute on function public.claim_device(text)   from anon;
revoke execute on function public.release_device(uuid) from anon;

grant execute on function
  public.ingest_reading(text, text, int, int, numeric, int) to anon;
grant execute on function public.ping() to anon;
grant execute on function public.claim_device(text) to authenticated;
grant execute on function public.release_device(uuid) to authenticated;

-- ---------------------------------------------------------------------------
--  Seed
--  Deliberately not in this file: the device secret must not live in a tracked
--  one. Copy seed.example.sql to seed.local.sql, fill in the real values and
--  run it after this file.
-- ---------------------------------------------------------------------------
