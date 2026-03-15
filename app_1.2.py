import time
time.sleep(0.5) # <--- EL PARCHE: Deja que el bus I2C respire

from machine import Pin, I2C
import ssd1306, network, ubinascii
import sensores, nube
try: import mpu6050
except: mpu = None

# --- CREDENCIALES ---
WIFI_SSID = "HUAWEI-106J7H"
WIFI_PASS = "EDIFICIO-69@"
FB_API_KEY = "AIzaSyAFE3fKRXgB1NEeaTEEZb6Q2b8_1Je2jR0"
FB_EMAIL = "nodos@senticore.com" 
FB_PASS = "Sentinel2026!"
FB_DB_BASE_URL = "https://sensorcore-51890-default-rtdb.firebaseio.com/flota"

mac_bytes = network.WLAN(network.STA_IF).config('mac')
DEVICE_ID = ubinascii.hexlify(mac_bytes).decode('utf-8').upper()

# --- HARDWARE BLINDADO ---
i2c = I2C(0, scl=Pin(7), sda=Pin(6), freq=400000)
try:
    oled = ssd1306.SSD1306_I2C(128, 64, i2c)
    pantalla_ok = True
except Exception as e:
    print(f"APP ERR: I2C (ENODEV). {e}")
    pantalla_ok = False

try: mpu = mpu6050.mpu6050(i2c)
except: mpu = None

pin_a = Pin(3, Pin.IN, Pin.PULL_UP)
pin_b = Pin(4, Pin.IN, Pin.PULL_UP)
btn = Pin(21, Pin.IN, Pin.PULL_UP)

# --- ESTADOS Y BANDERAS ---
modos = ["GONIOMETRO", "VIBROMETRO", "TERMOMETROS", "BATERIA", "SYNC NUBE"]
indice_menu, modo_activo, pantalla_encendida = 0, False, True
ultimo_uso, estado_anterior, ultimo_paso_encoder = time.ticks_ms(), 0, time.ticks_ms()
despertar_pendiente = False 

# --- INTERRUPCIONES ---
def callback_encoder(p):
    global indice_menu, estado_anterior, ultimo_paso_encoder, ultimo_uso, despertar_pendiente
    ahora = time.ticks_ms()
    if time.ticks_diff(ahora, ultimo_paso_encoder) < 2: return
    if not pantalla_encendida: despertar_pendiente = True; ultimo_paso_encoder = ahora; return
    est = (pin_a.value() << 1) | pin_b.value()
    if estado_anterior == 0b11 and not modo_activo:
        if est == 0b01: indice_menu = (indice_menu + 1) % len(modos)
        elif est == 0b10: indice_menu = (indice_menu - 1) % len(modos)
        ultimo_paso_encoder = ahora
    estado_anterior = est; ultimo_uso = ahora

def callback_btn(p):
    global modo_activo, ultimo_uso, despertar_pendiente
    if time.ticks_diff(time.ticks_ms(), ultimo_uso) < 250: return
    if not pantalla_encendida: despertar_pendiente = True; return
    modo_activo = not modo_activo; ultimo_uso = time.ticks_ms()

pin_a.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=callback_encoder)
pin_b.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=callback_encoder)
btn.irq(trigger=Pin.IRQ_FALLING, handler=callback_btn)

# --- BUCLE PRINCIPAL DE LA APP ---
if pantalla_ok:
    oled.fill(0)
    oled.text("OTA EXITOSO!", 15, 20)
    oled.text("APP v1.2 OK", 20, 40) # <--- VISUALIZACIÓN DEL CAMBIO
    oled.show()
    time.sleep(2)

while True:
    if not pantalla_ok: time.sleep(1); continue
    
    if despertar_pendiente:
        oled.poweron(); pantalla_encendida = True; despertar_pendiente = False; ultimo_uso = time.ticks_ms()
    
    if pantalla_encendida and time.ticks_diff(time.ticks_ms(), ultimo_uso) > 120000:
        oled.poweroff(); pantalla_encendida = False

    if pantalla_encendida:
        oled.fill(0)
        if not modo_activo:
            oled.text("--- MAKER TOOL ---", 0, 0)
            for i in range(min(5, len(modos))):
                idx = (indice_menu + i) % len(modos)
                pref = "> " if idx == indice_menu else "  "
                oled.text(pref + modos[idx], 0, 15 + (i * 10))
            oled.show()
        else:
            sel = modos[indice_menu]
            if sel == "BATERIA":
                v = sensores.leer_bateria()
                oled.text("BATERIA", 35, 0); oled.hline(0,10,128,1); oled.text(f"Voltaje: {v:.2f} V", 10, 30); oled.show(); time.sleep(0.5)
            elif sel == "TERMOMETROS":
                t = sensores.leer_termistor()
                oled.text("TEMP. HOTEND", 20, 0); oled.hline(0,10,128,1); oled.text(f"{t:.1f} C" if t else "NC/CORTO", 30, 30); oled.show(); time.sleep(0.5)
            elif sel == "GONIOMETRO":
                p, r, _ = sensores.leer_imu(mpu, 0)
                oled.text("GONIOMETRO", 25, 0); oled.hline(0,10,128,1); oled.text(f"{abs(p):.1f} deg", 35, 30); oled.show(); time.sleep(0.1)
            elif sel == "VIBROMETRO":
                _, _, v = sensores.leer_imu(mpu, 0.05)
                oled.text("VIBROMETRO", 25, 0); oled.hline(0,10,128,1); oled.text(f"{v:.2f} mm/s", 30, 30); oled.show(); time.sleep(0.05)
            elif sel == "SYNC NUBE":
                wlan = network.WLAN(network.STA_IF)
                if not wlan.isconnected(): oled.text("Reconectando...", 0, 20); oled.show()
                else: oled.text("Red OK. Leyendo...", 0, 20); oled.show()
                hora_exacta = nube.obtener_hora_real()
                payload = {"v_bat": sensores.leer_bateria(), "temp": sensores.leer_termistor(), "timestamp": hora_exacta}
                oled.fill(0); oled.text("Subiendo a FB...", 0, 20); oled.show()
                res = nube.hacer_sync(WIFI_SSID, WIFI_PASS, FB_API_KEY, FB_EMAIL, FB_PASS, FB_DB_BASE_URL, DEVICE_ID, payload)
                oled.fill(0); oled.text(res, 10, 30); oled.show(); time.sleep(3); modo_activo = False
    else:
        time.sleep(0.2)
