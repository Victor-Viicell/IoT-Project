# ============================================================================
#  Bluetooth provisioning -- the app hands the vase its Wi-Fi credentials
#
#  A vase with no network advertises a small GATT service. The app writes a
#  JSON blob ({"ssid": ..., "password": ...}) to the config characteristic and
#  watches the status characteristic for progress.
#
#  A BLE write only carries MTU-3 bytes (20 by default), so the blob arrives in
#  chunks. The characteristic is buffered without append, so each write IRQ
#  yields exactly the latest chunk; those chunks are collected here and every
#  one is offered to json.loads(). The moment the JSON closes, provisioning is
#  done -- no length prefix and no commit command to get wrong.
#
#  Status notifications look like:
#      {"state": "advertising"}
#      {"state": "connecting", "ssid": "Casa"}
#      {"state": "connected", "ip": "192.168.0.42"}
#      {"state": "failed", "message": "..."}
#      {"state": "timeout"}
# ============================================================================

import bluetooth
import json
import time

import config
import provisioning
import wifi

# --- IRQ events (values fixed by the MicroPython bluetooth module) ----------
_IRQ_CENTRAL_CONNECT = 1
_IRQ_CENTRAL_DISCONNECT = 2
_IRQ_GATTS_WRITE = 3

_FLAG_READ = bluetooth.FLAG_READ
_FLAG_WRITE = bluetooth.FLAG_WRITE
_FLAG_NOTIFY = bluetooth.FLAG_NOTIFY

# Largest blob we will assemble. SSID (32) + password (63) + JSON furniture is
# well under this, so exceeding it means a confused client.
_MAX_PAYLOAD = 256

# 100 ms, in microseconds.
_ADVERTISE_INTERVAL_US = 100_000


class Provisioner:
    """Advertises the configuration service and reports progress back."""

    def __init__(self):
        self.received = None

        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.config(gap_name=config.BLE_NAME)
        self._ble.irq(self._irq)

        self._pending = b""
        self._conn = None

        (handles,) = self._ble.gatts_register_services(
            (
                (
                    config.BLE_SERVICE_UUID,
                    (
                        (config.BLE_CONFIG_UUID, _FLAG_WRITE),
                        (config.BLE_STATUS_UUID, _FLAG_READ | _FLAG_NOTIFY),
                        (config.BLE_INFO_UUID, _FLAG_READ),
                    ),
                ),
            )
        )
        self._config_handle, self._status_handle, self._info_handle = handles

        # append=False: every write lands as its own chunk instead of piling up
        # inside the stack, so the assembly below stays in one place.
        self._ble.gatts_set_buffer(self._config_handle, _MAX_PAYLOAD)

        self._ble.gatts_write(self._info_handle, json.dumps(self._info()))
        self._ble.gatts_write(self._status_handle, json.dumps({"state": "idle"}))

        self._advertise()

    # -- public ------------------------------------------------------------

    def status(self, state, message=None, ssid=None, ip=None):
        """Publish progress to whoever is connected. Never raises."""
        payload = {"state": state}
        if message is not None:
            payload["message"] = message
        if ssid is not None:
            payload["ssid"] = ssid
        if ip is not None:
            payload["ip"] = ip

        data = json.dumps(payload)
        self._ble.gatts_write(self._status_handle, data)
        if self._conn is not None:
            try:
                self._ble.gatts_notify(self._conn, self._status_handle, data)
            except OSError:
                pass

    def close(self):
        """Stop advertising and release the radio for Wi-Fi."""
        try:
            self._ble.gap_advertise(None)
        except OSError:
            pass
        self._ble.active(False)

    # -- internals ---------------------------------------------------------

    def _info(self):
        """Identity the app reads once, before sending any credentials."""
        return {
            "name": config.BLE_NAME,
            "uid": config.DEVICE_UID,
            "claimCode": config.DEVICE_CLAIM_CODE,
        }

    def _advertise(self):
        adv = bluetooth.advertising_payload(name=config.BLE_NAME)
        # A 128-bit UUID and a name do not both fit in the 31-byte payload.
        resp = bluetooth.advertising_payload(services=[config.BLE_SERVICE_UUID])
        self._ble.gap_advertise(_ADVERTISE_INTERVAL_US, adv_data=adv, resp_data=resp)

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            self._conn = data[0]
            self._pending = b""
        elif event == _IRQ_CENTRAL_DISCONNECT:
            self._conn = None
            self._pending = b""
            # Stay discoverable: the app may have been closed mid-setup.
            self._advertise()
        elif event == _IRQ_GATTS_WRITE:
            _, value_handle = data
            if value_handle == self._config_handle:
                self._accept(self._ble.gatts_read(self._config_handle))

    def _accept(self, chunk):
        if not chunk:
            return

        # A blob always opens with '{'; anything else is stray and would poison
        # the assembly, so drop it rather than fail the whole run.
        if not self._pending and chunk[:1] != b"{":
            return

        self._pending += chunk

        if len(self._pending) > _MAX_PAYLOAD:
            self._pending = b""
            self.status("failed", message="payload muito grande")
            return

        try:
            payload = json.loads(self._pending.decode())
        except ValueError:
            return  # still mid-blob

        if not isinstance(payload, dict) or not payload.get("ssid"):
            return

        # A new blob may start arriving immediately; hand delivery to
        # provision() and start clean.
        self._pending = b""
        self.received = (payload["ssid"], payload.get("password", ""))
        self.status("received", ssid=payload["ssid"])


def provision(timeout=None):
    """Advertise until the app delivers a network the board can actually join.

    Returns {'ssid', 'password'} on success, or None when nothing arrived in
    time. Credentials that fail to connect are reported and then ignored, so a
    typo does not leave the vase unreachable.
    """
    timeout = config.BLE_PROVISION_TIMEOUT if timeout is None else timeout

    ble = Provisioner()
    ble.status("advertising")
    print("Bluetooth: anunciando como %r por ate %d s" % (config.BLE_NAME, timeout))

    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            if ble.received is not None:
                ssid, password = ble.received
                ble.received = None
                print("Bluetooth: credenciais recebidas para %r" % ssid)
                ble.status("connecting", ssid=ssid)

                if wifi.connect(ssid, password, timeout=20) is not None:
                    provisioning.save(ssid, password)
                    ip = wifi.ip()
                    ble.status("connected", ip=ip)
                    print("Bluetooth: conectado, ip %s" % ip)
                    return {"ssid": ssid, "password": password}

                ble.status("failed", message="nao foi possivel entrar em %s" % ssid)
                print("Bluetooth: falha ao entrar em %r" % ssid)

            time.sleep(0.2)

        ble.status("timeout")
        print("Bluetooth: ninguem configurou o aparelho a tempo")
        return None
    finally:
        ble.close()
