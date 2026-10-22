# ============================================================================
#  WiFi station helper
#  Credentials come from the app over Bluetooth when the vase has been
#  provisioned, and from config.py otherwise (see provisioning.py).
# ============================================================================

import time

import network

import provisioning


def connect(ssid=None, password=None, timeout=20):
    """Join a network. Returns the WLAN object, or None on timeout.

    With no arguments the stored credentials are used, falling back to the
    ones compiled into config.py.
    """
    sta = network.WLAN(network.STA_IF)
    sta.active(True)

    if sta.isconnected():
        return sta

    if ssid is None:
        creds = provisioning.active()
        if creds is None:
            print("WiFi: nenhuma credencial disponivel")
            return None
        ssid, password = creds["ssid"], creds.get("password", "")
    password = password or ""

    print("WiFi: conectando a %r" % ssid, end="")
    sta.connect(ssid, password)

    deadline = time.time() + timeout
    while not sta.isconnected():
        if time.time() > deadline:
            print(" -> TEMPO ESGOTADO")
            return None
        print(".", end="")
        time.sleep(0.5)

    print(" -> ok, ip %s" % sta.ifconfig()[0])
    return sta


def ip():
    """Current address, or None when the station is down."""
    sta = network.WLAN(network.STA_IF)
    if not sta.isconnected():
        return None
    return sta.ifconfig()[0]


def is_up():
    return network.WLAN(network.STA_IF).isconnected()
