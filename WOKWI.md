# Running the firmware on Wokwi (browser)

The browser editor is not the same setup as `wokwi.toml` + the local `.bin`.
For MicroPython on wokwi.com, start from the **MicroPython ESP32** template and
paste the project files; the simulator supplies its own MicroPython firmware.

## 1. Create the project

Open:

<https://wokwi.com/projects/new/micropython-esp32>

Use this template, not `new/esp32` (that one is for Arduino sketches). The
default `main.py` just prints `Hello, ESP32!`; you will replace it.

## 2. Paste the circuit

Open the **diagram.json** tab and replace its contents with this project's
`diagram.json`. It already has:

- ESP32-DevKitC V4
- LCD1602 over I2C on GPIO21/22
- DHT22 on GPIO4
- soil potentiometer on GPIO34
- LDR on GPIO35

The RFID, relay, LED, button and buzzer parts are decorative; `main.py` does not
use them.

## 3. Add the code files

Use the **+** button in the file tab bar to add each file, then paste the
contents from this folder:

| File | Needed? | Why |
| --- | --- | --- |
| `main.py` | yes | replaces the template's file |
| `config.py` | yes | network + device identity |
| `credentials.py` | yes | Supabase key + device secret |
| `wifi.py` | yes | Wi-Fi station helper |
| `provisioning.py` | yes | stored-credential helper used by `wifi.py` |
| `cloud.py` | yes | PostgREST upload |
| `ble_provision.py` | no | Wokwi does not simulate Bluetooth |

`main.py` treats `ble_provision` as optional, so leaving it out is expected.
`config.py` sets `WIFI_SSID = "Wokwi-GUEST"`, so the BLE path is never entered.

## 4. Use the Wokwi device identity

The public Wokwi project must not contain the real `vase-01` secret. A throwaway
device is already seeded in Supabase for the simulation.

In `config.py`, change:

```python
DEVICE_UID        = "vase-wokwi"
DEVICE_CLAIM_CODE = "PLANT-W0KW"
```

Keep:

```python
WIFI_SSID = "Wokwi-GUEST"
WIFI_PASS = ""
SUPABASE_HOST = "zubizzqwjteajycnwesf.supabase.co"
PUBLISH_EVERY = 15
```

In `credentials.py`, use:

```python
SUPABASE_KEY  = "sb_publishable_dFYXdB8zZxnfbBZIrWsLvg_zIOP3yeR"
DEVICE_SECRET = "dev_fe48a6beac924c9e56e33b0c11847522"
```

The secret must match the `vase-wokwi` row, or `ingest_reading()` rejects every
sample.

## 5. Run it

Press the green **Play** button. In the serial monitor you should see:

```text
WiFi: conectando a 'Wokwi-GUEST' ... -> ok, ip 10.10.0.2
Supabase acessível: HTTP 200
solo  62  luz  48  ar 24.0C  umid  55%
  -> enviado
```

Then one upload every 15 seconds.

On boot the LCD shows `PLANT-W0KW` for two seconds, and it keeps the code on
screen while the vase has no network. Once Wi-Fi connects, the reading screen
takes over.

## 6. See it in the app

Sign in with Google, tap **+**, and enter:

```text
PLANT-W0KW
```

The vase appears as **Vaso Wokwi** and its readings update every 15 seconds.

## Security notes

- Free Wokwi projects are **public**, and the public IoT gateway monitors
  traffic. Do not paste production secrets into a public project.
- This guide uses a separate `vase-wokwi` device, so the real `vase-01` secret
  stays private.
- To revoke the demo secret, rotate it in Supabase:

  ```sql
  update public.devices
  set device_secret = 'dev_a_new_secret'
  where device_uid = 'vase-wokwi';
  ```

  Then update `credentials.py` in Wokwi. Releasing the device in the app only
  clears the owner; it does not change the secret.
- Wokwi's ESP32 simulator does not implement Bluetooth, so the BLE provisioning
  flow cannot be tested there. Wi-Fi comes from `config.py` instead.

## Troubleshooting

| Serial message | Meaning |
| --- | --- |
| `Supabase respondeu 404 - schema não aplicado` | schema missing (not the case for this project) |
| `credenciais ausentes` | `credentials.py` missing or empty |
| `Supabase recusou a chave (HTTP 401)` | `SUPABASE_KEY` is wrong |
| `Supabase inacessível (sem resposta HTTP, N bytes lidos)` | the request reached Supabase but the response was never read; usually a stale `cloud.py` (older versions reported this as `HTTP 0`) or a TLS timeout |
| `falha no envio: HTTP 400 ... invalid input syntax for type integer` | a sample arrived with a decimal where the schema expects an integer; `cloud.py` rounds those before sending |
| `falha no envio: HTTP 403 unknown device` | `DEVICE_SECRET` does not match `vase-wokwi` |
| `LCD indisponível` | I2C/LCD issue; readings continue over serial |
| `Bluetooth indisponivel nesta build` | expected on Wokwi if `ble_provision.py` is absent |
