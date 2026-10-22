# ============================================================================
#  Device configuration
#
#  HARDCODED FOR NOW. The plan is BLE provisioning from the phone app, which
#  writes WiFi credentials + device identity here at runtime. Until then this
#  file is the single place to edit -- except for credentials.py, which holds
#  the two secrets that must not be committed.
#
#  NOTE: Wokwi gives every ESP32 a virtual open AP called "Wokwi-GUEST" -- no
#  password. On your real board, change these to your router's credentials.
#
#  Leave WIFI_SSID empty to ship a vase that is configured by the phone app
#  over Bluetooth instead: the board then boots with no network, advertises,
#  and waits for the app to hand it the credentials (see ble_provision.py).
#  Whatever the app sends is stored in WIFI_FILE and wins over this file on
#  every later boot.
# ============================================================================

WIFI_SSID = "Wokwi-GUEST"
WIFI_PASS = ""


# ---------------------------------------------------------------------------
#  Supabase
#  Host only -- no scheme, the client builds the request line itself.
# ---------------------------------------------------------------------------
SUPABASE_HOST = "zubizzqwjteajycnwesf.supabase.co"

# Modern publishable key (recommended). If PostgREST rejects it, swap in the
# legacy anon JWT from Dashboard -> Settings -> API Keys. Both this key and the
# device secret below are kept out of git: copy credentials.example.py to
# credentials.py and fill them in. Missing credentials leave the board running
# offline (cloud.py refuses to publish) instead of failing at boot.
try:
    from credentials import DEVICE_SECRET, SUPABASE_KEY
except ImportError:
    SUPABASE_KEY = ""
    DEVICE_SECRET = ""


# ---------------------------------------------------------------------------
#  Device identity -- must match the row in supabase/seed.local.sql, or
#  ingest_reading() rejects every sample.
# ---------------------------------------------------------------------------
DEVICE_UID    = "vase-01"


# ---------------------------------------------------------------------------
#  Bluetooth provisioning
#  Read by ble_provision.py / provisioning.py.
# ---------------------------------------------------------------------------

# Name the vase advertises while it waits to be configured. Keep it short: a
# BLE advertising payload is 31 bytes and the service UUID takes 18 of them.
BLE_NAME = "Plantkeeper-01"

# Printed on the label and shown on the LCD. The app reads it over Bluetooth so
# connecting and claiming happen in one go. It is not a secret -- it is the
# same string the user would type by hand, and reading it needs a live BLE
# connection within radio range. Keep it to 16 characters or fewer so it fits
# on one LCD line.
DEVICE_CLAIM_CODE = "PLANT-4K7Q"

# 128-bit UUIDs for the provisioning GATT service. These must match the app's
# src/utils/provisioning.ts.
BLE_SERVICE_UUID = "7a1e0001-6d3c-4f2b-9c8a-5e1d2f3a4b5c"
BLE_CONFIG_UUID  = "7a1e0002-6d3c-4f2b-9c8a-5e1d2f3a4b5c"
BLE_STATUS_UUID  = "7a1e0003-6d3c-4f2b-9c8a-5e1d2f3a4b5c"
BLE_INFO_UUID    = "7a1e0004-6d3c-4f2b-9c8a-5e1d2f3a4b5c"

# Where the app's credentials land on the board's filesystem.
WIFI_FILE = "wifi_config.json"

# How long to keep advertising before giving up and running offline.
BLE_PROVISION_TIMEOUT = 180


# ---------------------------------------------------------------------------
#  Publish cadence
#  Publishing over TLS is far more expensive than sampling. Keep this well
#  above main.py's READ_EVERY, or buffer samples and send an average.
# ---------------------------------------------------------------------------
PUBLISH_EVERY = 15      # seconds between uploads
