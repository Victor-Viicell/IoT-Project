-- ============================================================================
--  Seed: the vase you are building right now.
--
--  Copy to seed.local.sql (gitignored) and fill in the real values, then run
--  it in Dashboard -> SQL Editor after schema.sql. Re-running it is safe.
--
--  device_uid / device_secret MUST match credentials.py exactly, and the same
--  claim code must be compiled into config.py.
--  Change the claim code before shipping anything to a real user.
-- ============================================================================
insert into public.devices (device_uid, device_secret, claim_code, name)
values ('vase-01',
        'dev_your_device_secret_here',
        'PLANT-4K7Q',
        'Vaso protótipo')
on conflict (device_uid) do update
  set device_secret = excluded.device_secret,
      claim_code    = excluded.claim_code;
