import time, math, sys, uselect, ujson
time.sleep(0.5) 

from machine import Pin, I2C
import ssd1306, network, ubinascii
import sensores, nube
try: import mpu6050
except: mpu = None

# --- CONFIGURACIÓN ---
WIFI_SSID = "HUAWEI-106J7H"
WIFI_PASS = "EDIFICIO-69@"
FB_API_KEY = "AIzaSyAFE3fKRXgB1NEeaTEEZb6Q2b8_1Je2jR0"
FB_EMAIL = "nodos@senticore.com" 
FB_PASS = "Sentinel2026!"
FB_DB_BASE_URL = "https://sensorcore-51890-default-rtdb.firebaseio.com/flota"

mac_bytes = network.WLAN(network.STA_IF).config('mac')
DEVICE_ID = ubinascii.hexlify(mac_bytes).decode('utf-8').upper()
VERSION_ACTUAL = 1.7

# --- HARDWARE ---
i2c = I2C(0, scl=Pin(7), sda=Pin(6), freq=400000)
try:
    oled = ssd1306.SSD1306_I2C(128, 64, i2c)
    pantalla_ok = True
except: pantalla_ok = False

try: mpu = mpu6050.mpu6050(i2c)
except: mpu = None

pin_a, pin_b, btn = Pin(3, Pin.IN, Pin.PULL_UP), Pin(4, Pin.IN, Pin.PULL_UP), Pin(21, Pin.IN, Pin.PULL_UP)

# --- MENÚ Y ESTADOS ---
modos = ["GONIOMETRO", "VIBROMETRO", "TERMOMETROS", "BATERIA", "SYNC NUBE", "MODO USB"]
indice_menu, modo_activo, pantalla_encendida = 0, False, True
ultimo_uso, estado_anterior, ultimo_paso_encoder = time.ticks_ms(), 0, time.ticks_ms()
despertar_pendiente = False 

# --- INTERRUPCIONES ---
def callback_encoder(p):
    global indice_menu, estado_anterior, ultimo_paso_encoder, ultimo_uso, despertar_pendiente
    ahora = time.ticks_ms()
    if time.ticks_diff(ahora, ultimo_paso_encoder) < 5: return # Debounce
    
    if not pantalla_encendida: 
        despertar_pendiente = True
        ultimo_paso_encoder = ahora
        return
        
    est = (pin_a.value() << 1) | pin_b.value()
    if estado_anterior == 0b11 and not modo_activo:
        if est == 0b01: indice_menu = (indice_menu + 1) % len(modos)
        elif est == 0b10: indice_menu = (indice_menu - 1) % len(modos)
    estado_anterior = est
    ultimo_uso = ahora

def callback_btn(p):
    global modo_activo, ultimo_uso, despertar_pendiente
    ahora = time.ticks_ms()
    if time.ticks_diff(ahora, ultimo_uso) < 200: return # Filtro de rebote
    
    if not pantalla_encendida: 
        despertar_pendiente = True
        ultimo_uso = ahora
        return
        
    modo_activo = not modo_activo
    ultimo_uso = ahora

pin_a.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=callback_encoder)
pin_b.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=callback_encoder)
btn.irq(trigger=Pin.IRQ_FALLING, handler=callback_btn)

# --- APLICACIÓN: GONIOMETRO ---
def app_goniometro():
    global modo_activo
    btn.irq(handler=None) # Control manual del botón
    off_x, off_y, off_z = 0.0, 0.0, 0.0
    con_tara = False
    
    while True:
        if mpu:
            d = mpu.get_values()
            ax, ay, az = d["AcX"], d["AcY"], d["AcZ"]
            ang_x = math.atan2(ay, math.sqrt(ax**2 + az**2)) * 180 / math.pi
            ang_y = math.atan2(ax, math.sqrt(ay**2 + az**2)) * 180 / math.pi
            ang_z = math.atan2(math.sqrt(ax**2 + ay**2), az) * 180 / math.pi
            fx, fy, fz = ang_x - off_x, ang_y - off_y, ang_z - off_z
            nivelado = abs(fx) < 0.5 and abs(fy) < 0.5
        else: fx, fy, fz, nivelado = 0, 0, 0, False

        # Lógica de botón manual
        if btn.value() == 0:
            t_ini = time.ticks_ms()
            while btn.value() == 0:
                if time.ticks_diff(time.ticks_ms(), t_ini) > 1500: # Clic largo = TARA
                    off_x, off_y, off_z = ang_x, ang_y, ang_z
                    con_tara = True
                    oled.fill(1); oled.text("TARA OK", 35, 30, 0); oled.show(); time.sleep(0.5)
                    break
            if 50 < time.ticks_diff(time.ticks_ms(), t_ini) < 1000: # Clic corto = SALIR
                break

        oled.fill(1 if nivelado else 0)
        c = 0 if nivelado else 1 
        oled.text("GONIOMETRO", 40, 0, c)
        oled.rect(5, 12, 40, 40, c) # Burbuja
        bx = max(6, min(42, int(25 - (fy * 1.2))))
        by = max(13, min(50, int(32 - (fx * 1.2))))
        oled.fill_rect(bx-2, by-2, 5, 5, c)
        
        oled.text(f"X: {fx:>5.1f}*", 55, 15, c)
        oled.text(f"Y: {fy:>5.1f}*", 55, 28, c)
        oled.text(f"Z: {fz:>5.1f}*", 55, 41, c)
        oled.text("TARA: OK" if con_tara else "SIN TARA", 55, 54, c)
        oled.show()
        time.sleep(0.05)

    modo_activo = False
    btn.irq(trigger=Pin.IRQ_FALLING, handler=callback_btn)

# --- OTRAS FUNCIONES ---
def app_modo_usb():
    global modo_activo
    oled.fill(0); oled.text("MODO USB", 35, 10); oled.text("Esperando PC...", 10, 30); oled.show()
    poller = uselect.poll()
    poller.register(sys.stdin, uselect.POLLIN)
    while modo_activo:
        if poller.poll(100): 
            cmd = sys.stdin.readline().strip()
            if cmd == "GET_DATA":
                print(ujson.dumps({"v_bat": sensores.leer_bateria(), "temp": sensores.leer_termistor()}))
            elif cmd == "EXIT": modo_activo = False

# --- BUCLE PRINCIPAL ---
if pantalla_ok:
    oled.fill(0); oled.text("SENTICORE 1.7", 15, 25); oled.show(); time.sleep(1)

while True:
    if not pantalla_ok: time.sleep(1); continue
    if despertar_pendiente:
        oled.poweron(); pantalla_encendida = True; despertar_pendiente = False; ultimo_uso = time.ticks_ms()
    if pantalla_encendida and time.ticks_diff(time.ticks_ms(), ultimo_uso) > 120000:
        oled.poweroff(); pantalla_encendida = False

    if pantalla_encendida:
        oled.fill(0)
        if not modo_activo:
            oled.text("--- MENU ---", 25, 0)
            # Títulos fijos, flecha móvil
            for i in range(min(5, len(modos))):
                y_pos = 15 + (i * 10)
                oled.text(modos[i], 15, y_pos) # Texto desplazado a la derecha
                if i == indice_menu:
                    oled.text(">", 0, y_pos) # Flecha en la posición del índice
            oled.show()
        else:
            sel = modos[indice_menu]
            if sel == "GONIOMETRO": app_goniometro()
            elif sel == "MODO USB": app_modo_usb()
            elif sel == "BATERIA":
                v = sensores.leer_bateria()
                oled.text(f"BAT: {v:.2f}V", 25, 30); oled.show(); time.sleep(0.5)
            elif sel == "SYNC NUBE":
                oled.text("Sync...", 45, 30); oled.show()
                res = nube.hacer_sync(WIFI_SSID, WIFI_PASS, FB_API_KEY, FB_EMAIL, FB_PASS, FB_DB_BASE_URL, DEVICE_ID, {"v":VERSION_ACTUAL})
                oled.fill(0); oled.text(res, 35, 30); oled.show(); time.sleep(2); modo_activo = False
            else:
                # Si la app no existe, regresa al menú
                modo_activo = False
    else: time.sleep(0.2)
