# ============================================================================
#  Wi-Fi credentials that survive a reboot
#
#  The app sends them over Bluetooth and they are stored as JSON in the board's
#  filesystem, so the next boot joins the network on its own. config.py stays
#  the fallback: a board that was never provisioned -- or whose flash was just
#  wiped -- behaves exactly as it did before this module existed.
# ============================================================================

import json
import os

import config

# Survives a failed write, so a provisioning run still works with a full or
# read-only filesystem. Cleared on reboot.
_cached = None


def load():
    """Stored credentials as {'ssid', 'password'}, or None if never provisioned."""
    global _cached
    if _cached is not None:
        return _cached

    try:
        with open(config.WIFI_FILE) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None

    if not isinstance(data, dict) or not data.get("ssid"):
        return None

    _cached = {"ssid": data["ssid"], "password": data.get("password", "")}
    return _cached


def save(ssid, password):
    """Persist credentials. Returns True when they reached the filesystem."""
    global _cached
    _cached = {"ssid": ssid, "password": password}

    try:
        with open(config.WIFI_FILE, "w") as fh:
            json.dump(_cached, fh)
        return True
    except OSError as exc:
        print("Nao foi possivel gravar %s: %s" % (config.WIFI_FILE, exc))
        return False


def clear():
    """Forget the stored network, e.g. before handing the vase to someone else."""
    global _cached
    _cached = None
    try:
        os.remove(config.WIFI_FILE)
    except OSError:
        pass


def fallback():
    """The credentials compiled into config.py, when it names a network."""
    if config.WIFI_SSID:
        return {"ssid": config.WIFI_SSID, "password": config.WIFI_PASS}
    return None


def active():
    """Stored credentials if present, otherwise the ones compiled in."""
    return load() or fallback()
