# Copy this file to credentials.py (gitignored) and fill both values in.
#
# The firmware imports it at boot; the same two values must appear in
# supabase/seed.local.sql (copied from seed.example.sql) or ingest_reading()
# rejects every sample.
#
# Find them in the Supabase dashboard under Project Settings -> API Keys
# (publishable key) and in the seed you applied to the devices table.

SUPABASE_KEY = "sb_publishable_your_key_here"
DEVICE_SECRET = "dev_your_device_secret_here"
