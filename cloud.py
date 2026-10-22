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
import time

import config


class CloudError(Exception):
    pass


def _require_credentials():
    """Fail with a readable message instead of a 401 when credentials.py is
    missing -- the file is gitignored, so a fresh clone hits this."""
    if not config.SUPABASE_KEY or not config.DEVICE_SECRET:
        raise CloudError(
            "credenciais ausentes: copie credentials.example.py para "
            "credentials.py e preencha SUPABASE_KEY e DEVICE_SECRET"
        )


def _read(sock, n):
    """MicroPython's wrapped TLS socket exposes read() or recv(), depending
    on the port and mbedtls build. Support both."""
    read = getattr(sock, "read", None)
    if read is not None:
        return read(n)
    return sock.recv(n)


def _send(sock, data):
    """Write every byte: a TLS socket may accept a short write."""
    sent = 0
    while sent < len(data):
        n = sock.write(data[sent:])
        if n is None:
            continue
        if n <= 0:
            raise CloudError("conexao fechada durante o envio")
        sent += n


def _split_head(reply):
    """(header_blob, body_start), or None while the headers are incomplete."""
    end = reply.find(b"\r\n\r\n")
    if end < 0:
        return None
    return reply[:end], end + 4


def _header(head_blob, name):
    """Lowercased value of a response header, or b"" when absent."""
    for line in head_blob.split(b"\r\n")[1:]:
        key, _, value = line.partition(b":")
        if key.strip().lower() == name:
            return value.strip().lower()
    return b""


def _status(reply):
    """HTTP status from the reply, or 0 when there is no status line."""
    start = reply.find(b"HTTP/")
    if start < 0:
        return 0
    fields = reply[start:].split(b"\r\n", 1)[0].split(b" ")
    if len(fields) < 2:
        return 0
    try:
        return int(fields[1].decode())
    except (TypeError, ValueError):
        return 0


def _complete(reply):
    """True once the reply is parseable, so we can stop reading."""
    split = _split_head(reply)
    if split is None:
        return False
    head_blob, body_start = split

    if _status(reply) in (204, 304):
        return True                             # no body by definition

    length = _header(head_blob, b"content-length")
    if length:
        try:
            return len(reply) - body_start >= int(length.decode())
        except (TypeError, ValueError):
            return False

    if b"chunked" in _header(head_blob, b"transfer-encoding"):
        return reply.endswith(b"0\r\n\r\n")

    return False                                # read until the peer closes


def _receive(sock, timeout):
    """Read one HTTP response.

    A zero-byte read is not EOF here. MicroPython's TLS socket returns an
    empty result whenever mbedTLS has to consume a control record first, and
    TLS 1.3 servers (Cloudflare, in front of Supabase) send a session ticket
    right after the handshake. Treating that as the end of the response made
    every request look like "HTTP 0" even though the server had answered.
    """
    deadline = time.time() + timeout
    reply = b""
    empties = 0
    while True:
        chunk = _read(sock, 512)
        if chunk:
            empties = 0
            reply += chunk
            if _complete(reply):
                break
        else:
            empties += 1
            if empties >= 2:
                break                           # peer closed: end of stream
            time.sleep_ms(50)
        if time.time() > deadline:
            break
    return reply


def _request(method, host, path, headers, body=b"", timeout=15):
    addr = socket.getaddrinfo(host, 443)[0][-1]

    raw = socket.socket()
    raw.settimeout(timeout)
    sock = raw
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

        _send(sock, head.encode())
        if body:
            _send(sock, body)

        reply = _receive(sock, timeout)
    finally:
        # Closing the TLS socket closes the transport underneath it too.
        for s in (sock, raw):
            try:
                s.close()
            except Exception:
                pass

    status = _status(reply)
    if status == 0:
        raise CloudError("sem resposta HTTP, %d bytes lidos" % len(reply))

    _, _, reply_body = reply.partition(b"\r\n\r\n")
    return status, reply_body


def ping():
    """Cheap reachability check on the RPC surface the firmware uses.

    The publishable key maps to `anon`, which deliberately has no table access
    (RLS plus no SELECT grant), so a `select` on `devices` would report 401 even
    when everything is fine. `ping()` is a constant-returning RPC granted to
    anon: it answers 200 once the schema is applied and 404 (PGRST202) when it
    is not -- which is exactly the difference worth logging.
    """
    _require_credentials()
    status, _ = _request(
        "POST", config.SUPABASE_HOST, "/rest/v1/rpc/ping", {
            "apikey": config.SUPABASE_KEY,
            "Authorization": "Bearer " + config.SUPABASE_KEY,
            "Content-Type": "application/json",
        }, b"{}", timeout=10)
    return status


def _as_int(value):
    """ingest_reading() declares its moisture, light and humidity parameters
    as `int`, and PostgREST rejects a float instead of rounding it (22P02,
    `invalid input syntax for type integer: "55.0"`). The DHT driver can
    report humidity as a float, so normalise before sending."""
    if value is None:
        return None
    return round(value)


def publish(reading):
    """Upload one sample. Raises CloudError on anything but a 2xx."""
    _require_credentials()
    payload = {
        "p_uid":    config.DEVICE_UID,
        "p_secret": config.DEVICE_SECRET,
        "p_soil":   _as_int(reading.get("soil")),
        "p_light":  _as_int(reading.get("light")),
        "p_temp":   reading.get("temp"),
        "p_hum":    _as_int(reading.get("hum")),
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
