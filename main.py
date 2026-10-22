# ============================================================================
#  Plant health monitor - sensor acquisition
#  Board  : classic ESP32 DevKitC V4 (ESP32-WROOM-32)
#  Runtime: MicroPython 1.27.0 (ESP32_GENERIC-20251209-v1.27.0.bin)
#
#  Reads: soil moisture (ADC), ambient light (ADC),
#         air temperature + humidity (DHT22 in the sim / DHT11 on the real board)
#  Output: serial monitor @115200 + optional LCD1602 over I2C
#          + Supabase via HTTPS (see wifi.py / cloud.py)
#
#  A board with no stored Wi-Fi credentials advertises over Bluetooth and waits
#  for the phone app to send them (see ble_provision.py).
#
#  NOTE  GPIO 34/35 are INPUT-ONLY and live on ADC1, which is the only ADC
#        bank that keeps working while WiFi is active (ADC2 is unusable).
#
#  The two analog channels are published as an index on the sensor's own scale
#  (raw / 4095 * 100), not as a physical unit: neither module is calibrated.
# ============================================================================

import time
import machine
import dht

import config
import wifi
import cloud
import provisioning

try:
    import ble_provision
except ImportError:
    # Some ESP32 MicroPython builds (including Wokwi's simulator) omit the
    # bluetooth module. Provisioning is optional: config.py still supplies a
    # network, and the vase simply runs without the BLE setup path.
    ble_provision = None

# ---------------------------------------------------------------------------
#  Pin map  (must match diagram.json)
# ---------------------------------------------------------------------------
PIN_SOIL  = 34          # ADC1_CH6  soil moisture probe
PIN_LIGHT = 35          # ADC1_CH7  LDR / photoresistor module AO
PIN_DHT   = 4           # DHT data line
PIN_LCD_SDA = 21        # I2C0 default SDA
PIN_LCD_SCL = 22        # I2C0 default SCL
LCD_ADDR  = 0x27        # PCF8574 backpack (use 0x3F if yours differs)

# ---------------------------------------------------------------------------
#  Sensor polarity flags - flip these once you test your real modules
# ---------------------------------------------------------------------------
INVERT_SOIL  = True     # capacitive probe: dry soil = HIGH voltage
INVERT_LIGHT = True     # LDR module: bright light = LOW voltage (inverted AO)
USE_LCD      = True     # set False to skip the LCD entirely

DHT_TYPE   = dht.DHT22  # <-- change to dht.DHT11 for the real hardware
READ_EVERY = 2          # seconds between samples


# ---------------------------------------------------------------------------
#  Analog helpers
# ---------------------------------------------------------------------------
def _make_adc(pin):
    adc = machine.ADC(machine.Pin(pin))
    adc.atten(machine.ADC.ATTN_11DB)    # full 0..3.3 V range
    return adc


def _index(adc, invert=False):
    """Read an ADC pin and return 0..100 as an integer."""
    raw = adc.read()                    # 0..4095 on the ESP32
    pct = (raw * 100) // 4095
    return 100 - pct if invert else pct


# ---------------------------------------------------------------------------
#  Minimal I2C HD44780 driver (PCF8574 backpack)
#     bit0 = RS   bit1 = RW   bit2 = E   bit3 = backlight   bits4-7 = data
# ---------------------------------------------------------------------------
class LCD:
    def __init__(self, i2c, addr=LCD_ADDR):
        self.i2c = i2c
        self.addr = addr
        self.bl = 0x08                  # backlight on
        time.sleep_ms(50)
        # force 8-bit then 4-bit interface
        self._pulse(0x30)
        time.sleep_ms(5)
        self._pulse(0x30)
        time.sleep_ms(1)
        self._pulse(0x30)
        self._pulse(0x20)               # 4-bit mode
        self._cmd(0x28)                 # 2 lines, 5x8 font
        self._cmd(0x0C)                 # display on, cursor off
        self._cmd(0x06)                 # auto-increment, no shift
        self.clear()

    def _pulse(self, val):
        self.i2c.writeto(self.addr, bytes([val | 0x04]))    # E high
        time.sleep_us(50)
        self.i2c.writeto(self.addr, bytes([val & 0xFB]))    # E low
        time.sleep_us(50)

    def _send(self, byte, rs):
        base = self.bl | (0x01 if rs else 0x00)
        self._pulse(base | (byte & 0xF0))
        self._pulse(base | ((byte << 4) & 0xF0))

    def _cmd(self, cmd):
        self._send(cmd, 0)

    def clear(self):
        self._cmd(0x01)
        time.sleep_ms(2)

    def move(self, col, row):
        self._cmd(0x80 | col | (0x40 * row))

    def puts(self, text, col=0, row=0, pad=16):
        self.move(col, row)
        width = max(0, pad - col)
        line = str(text)[:width]
        # MicroPython's str has no ljust(): pad by hand so each frame blanks
        # whatever the previous one left on the line.
        line += " " * (width - len(line))
        for ch in line:
            self._send(ord(ch), 1)


# ---------------------------------------------------------------------------
#  Bring up peripherals
# ---------------------------------------------------------------------------
soil_adc  = _make_adc(PIN_SOIL)
light_adc = _make_adc(PIN_LIGHT)

sensor_dht = DHT_TYPE(machine.Pin(PIN_DHT))

lcd = None
if USE_LCD:
    try:
        i2c = machine.I2C(0, scl=machine.Pin(PIN_LCD_SCL),
                             sda=machine.Pin(PIN_LCD_SDA), freq=100000)
        lcd = LCD(i2c, LCD_ADDR)
        print("LCD pronto em 0x%02X" % LCD_ADDR)
    except Exception as exc:
        lcd = None
        print("LCD indisponível (%s) - continuando apenas pela serial" % exc)


# ---------------------------------------------------------------------------
#  Pairing display
#  The vase is its own pairing surface: the code the app needs is printed to
#  the serial monitor and shown on the LCD whenever there is no network, and
#  for a moment on every boot so a reset cannot hide it.
# ---------------------------------------------------------------------------
def show_pairing(reason, announce=True):
    """Put the pairing code on the vase's own display.

    `announce` is false for the periodic redraw in the main loop, which would
    otherwise repeat the same serial line every couple of seconds.
    """
    if announce:
        print("%s. Codigo para o app: %s" % (reason, config.DEVICE_CLAIM_CODE))
    if lcd:
        lcd.puts(reason, row=0)
        lcd.puts(config.DEVICE_CLAIM_CODE, row=1)


# Boot/reset: hold the code on screen long enough to read it before WiFi takes
# over the display.
show_pairing("Plantkeeper")
time.sleep(2)


# ---------------------------------------------------------------------------
#  Network bring-up
#  Nothing here is fatal: a vase with no WiFi still reads its sensors and
#  keeps the LCD alive, it just cannot upload.
#
#  A vase that has never been configured (no credentials in flash and none
#  compiled into config.py) opens Bluetooth and waits for the app.
# ---------------------------------------------------------------------------
def provision_bluetooth(timeout=None):
    """Run BLE provisioning when this build includes the bluetooth module."""
    if ble_provision is None:
        print("Bluetooth indisponivel nesta build")
        return None
    return ble_provision.provision(timeout)


if provisioning.load() is None and not config.WIFI_SSID:
    print("Nunca configurado - abrindo o Bluetooth para o aplicativo")
    show_pairing("Conecte no app")
    if provision_bluetooth() is None:
        print("Seguindo sem rede - as leituras ficarao locais")

cloud_ok = wifi.connect() is not None

# A stored network that stopped working (new router, changed password) is the
# one case worth reopening Bluetooth for without wiping the board first.
if not cloud_ok and provisioning.load() is not None:
    print("Rede guardada falhou - reabrindo o Bluetooth por 60 s")
    show_pairing("Rede falhou")
    if provision_bluetooth(timeout=60) is not None:
        cloud_ok = wifi.connect() is not None

if not cloud_ok:
    print("Sem WiFi - as leituras ficarão locais")
else:
    try:
        status = cloud.ping()
        if 200 <= status < 300:
            print("Supabase acessível: HTTP %d" % status)
        elif status == 404:
            cloud_ok = False
            print("Supabase respondeu 404 - schema não aplicado; leituras ficarão locais")
        else:
            cloud_ok = False
            print("Supabase recusou a chave (HTTP %d) - leituras ficarão locais" % status)
    except Exception as exc:
        cloud_ok = False
        print("Supabase inacessível (%s) - executando offline" % exc)


# ---------------------------------------------------------------------------
#  Sampling
# ---------------------------------------------------------------------------
def read_all():
    """Return one dict with every sensor reading."""
    data = {
        "soil":   _index(soil_adc, INVERT_SOIL),
        "light":  _index(light_adc, INVERT_LIGHT),
        "temp":   None,
        "hum":    None,
    }
    try:
        sensor_dht.measure()
        data["temp"] = sensor_dht.temperature()
        # Some builds return humidity as a float; the vase reports whole percent.
        data["hum"]  = int(sensor_dht.humidity())
    except OSError as exc:
        # DHT22 needs ~2 s between reads; a failed CRC lands here too.
        print("Falha na leitura do DHT:", exc)
    return data


def show(data):
    t = "%.1fC" % data["temp"] if data["temp"] is not None else "--.-C"
    h = "%3d%%" % data["hum"]  if data["hum"]  is not None else "---%"
    # soil and light are indices on their sensor's own scale, so they carry no
    # unit here: only the DHT22 reports one.
    print("solo %3d  luz %3d  ar %s  umid %s"
          % (data["soil"], data["light"], t, h))

    if lcd:
        if wifi.is_up():
            # every LCD line must fit 16 columns
            lcd.puts("S%3d L%3d" % (data["soil"], data["light"]), row=0)
            lcd.puts("%s  U%s" % (t, h), row=1)
        else:
            # No network: keep the vase's pairing interface visible. Readings
            # continue on the serial monitor, and come back to the LCD as soon
            # as WiFi reconnects.
            show_pairing("Conecte no app", announce=False)


# ---------------------------------------------------------------------------
#  Main loop
# ---------------------------------------------------------------------------
print("Monitor de plantas ativo - lendo a cada %d s, publicando a cada %d s"
      % (READ_EVERY, config.PUBLISH_EVERY))

last_publish = time.time()
while True:
    data = read_all()
    show(data)

    now = time.time()
    if now - last_publish >= config.PUBLISH_EVERY:
        last_publish = now

        if not cloud_ok:
            # WiFi drops are routine on real hardware -- keep retrying.
            cloud_ok = wifi.connect(timeout=8) is not None

        if cloud_ok:
            try:
                cloud.publish(data)
                print("  -> enviado")
            except Exception as exc:
                print("  -> falha no envio: %s" % exc)
                cloud_ok = False        # force a reconnect next round

    time.sleep(READ_EVERY)
