# ============================================================================
#  Supabase client -- minimal HTTPS POST
#
#  Supabase has no MQTT broker, so the ESP32 speaks PostgREST over HTTPS and
#  calls the ingest_reading() RPC instead. That keeps the publishable key
#  harmless: RLS denies all direct writes, so the only thing the key can do is
#  invoke a function that demands the per-device secret.
#
#  TLS note: we run with CERT_NONE. MicroPython's CERT_REQUIRED needs the
#  device clock to be set (NTP) or every handshake fails, which is a lot of
#  fragility for a prototype. Traffic is still encrypted; it is just not
#  authenticated. Switch to CERT_REQUIRED + load_verify_locations() once the
#  board sets its clock at boot.
# ============================================================================

import json
import socket
import ssl

import config


class CloudError(Exception):
    pass


def _read(sock, n):
    """MicroPython's wrapped TLS socket exposes read() or recv(), depending
    on the port and mbedtls build. Support both."""
    read = getattr(sock, "read", None)
    if read is not None:
        return read(n)
    return sock.recv(n)


def _request(method, host, path, headers, body=b"", timeout=15):
    addr = socket.getaddrinfo(host, 443)[0][-1]

    raw = socket.socket()
    raw.settimeout(timeout)
    try:
        raw.connect(addr)

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.verify_mode = ssl.CERT_NONE
        sock = ctx.wrap_socket(raw, server_hostname=host)

        head = "%s %s HTTP/1.1\r\n" % (method, path)
        head += "Host: %s\r\n" % host
        head += "Connection: close\r\n"
        for name, value in headers.items():
            head += "%s: %s\r\n" % (name, value)
        head += "Content-Length: %d\r\n\r\n" % len(body)

        sock.write(head.encode())
        if body:
            sock.write(body)

        reply = b""
        while True:
            chunk = _read(sock, 256)
            if not chunk:
                break
            reply += chunk
    finally:
        try:
            raw.close()
        except Exception:
            pass

    header_blob, _, reply_body = reply.partition(b"\r\n\r\n")
    status_line = header_blob.split(b"\r\n", 1)[0].decode()
    fields = status_line.split(" ")
    status = int(fields[1]) if len(fields) > 1 else 0
    return status, reply_body


def ping():
    """Cheap reachability check -- hits PostgREST's root."""
    status, _ = _request("GET", config.SUPABASE_HOST, "/rest/v1/", {
        "apikey": config.SUPABASE_KEY,
        "Authorization": "Bearer " + config.SUPABASE_KEY,
    }, timeout=10)
    return status


def publish(reading):
    """Upload one sample. Raises CloudError on anything but a 2xx."""
    payload = {
        "p_uid":    config.DEVICE_UID,
        "p_secret": config.DEVICE_SECRET,
        "p_soil":   reading.get("soil"),
        "p_light":  reading.get("light"),
        "p_temp":   reading.get("temp"),
        "p_hum":    reading.get("hum"),
    }

    status, reply = _request(
        "POST",
        config.SUPABASE_HOST,
        "/rest/v1/rpc/ingest_reading",
        {
            "apikey":        config.SUPABASE_KEY,
            "Authorization": "Bearer " + config.SUPABASE_KEY,
            "Content-Type":  "application/json",
            "Prefer":        "return=minimal",
        },
        json.dumps(payload).encode(),
    )

    if status not in (200, 201, 204):
        raise CloudError("HTTP %d %s" % (status, reply[:160]))

    return status
