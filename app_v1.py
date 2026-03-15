import network, time, machine, urequests, ubinascii
from machine import Pin, I2C
import ssd1306

# --- CONFIGURACIÓN DE RED Y NUBE ---
WIFI_SSID = "HUAWEI-106J7H"
WIFI_PASS = "EDIFICIO-69@"
FB_API_KEY = "AIzaSyAFE3fKRXgB1NEeaTEEZb6Q2b8_1Je2jR0"
FB_EMAIL = "nodos@senticore.com" 
FB_PASS = "Sentinel2026!"
FB_DB_BASE_URL = "https://sensorcore-51890-default-rtdb.firebaseio.com/flota"

# Identidad Única
mac_bytes = network.WLAN(network.STA_IF).config('mac')
DEVICE_ID = ubinascii.hexlify(mac_bytes).decode('utf-8').upper()
VERSION_LOCAL = 1.0  # <--- Este número debe coincidir con el de Firebase inicialmente

# --- INICIALIZAR PANTALLA ---
i2c = I2C(0, scl=Pin(7), sda=Pin(6), freq=400000)
try:
    oled = ssd1306.SSD1306_I2C(128, 64, i2c)
    oled.fill(0)
    oled.text("SentiCore BOOT", 10, 10)
    oled.text(f"v{VERSION_LOCAL}", 50, 25)
    oled.show()
except:
    oled = None

# --- FUNCIONES DE ARRANQUE ---
def conectar_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        if oled: oled.fill(0); oled.text("WiFi...", 10, 30); oled.show()
        wlan.connect(WIFI_SSID, WIFI_PASS)
        t_inicio = time.ticks_ms()
        while not wlan.isconnected() and time.ticks_diff(time.ticks_ms(), t_inicio) < 8000:
            time.sleep(0.5)
    return wlan.isconnected()

def reportar_estado(token, estado):
    """Avisa a Firebase si el equipo arrancó bien o si la app falló"""
    url = f"{FB_DB_BASE_URL}/{DEVICE_ID}/estado_ota.json?auth={token}"
    try:
        urequests.put(url, json={"version_actual": VERSION_LOCAL, "status": estado, "uptime": time.ticks_ms()}).close()
    except: pass

def procesar_ota(token):
    """Busca órdenes de actualización en Firebase y descarga de GitHub"""
    url_comando = f"{FB_DB_BASE_URL}/{DEVICE_ID}/comando_ota.json?auth={token}"
    
    try:
        res = urequests.get(url_comando)
        comando = res.json()
        res.close()
        
        if not comando: return False
        
        target_version = comando.get("target_version", 0)
        url_github = comando.get("url", "")
        
        # Si la nube pide una versión mayor a la que tengo
        if target_version > VERSION_LOCAL and url_github:
            if oled: oled.fill(0); oled.text(f"OTA v{target_version}!", 10, 20); oled.text("Descargando...", 10, 40); oled.show()
            
            # 1. Descargar el archivo crudo de GitHub
            res_code = urequests.get(url_github)
            nuevo_codigo = res_code.text
            res_code.close()
            
            # 2. Planchar el archivo app.py
            with open("app.py", "w") as f:
                f.write(nuevo_codigo)
            
            # 3. Reportar éxito temporal (el verdadero éxito se reporta al correr app.py)
            reportar_estado(token, "DESCARGA_OK_REINICIANDO")
            
            if oled: oled.fill(0); oled.text("REINICIANDO...", 10, 30); oled.show()
            time.sleep(2)
            machine.reset() # <--- El auto-reinicio mágico
            return True
            
        return False
    except Exception as e:
        reportar_estado(token, f"FAIL_DESCARGA: {str(e)[:10]}")
        return False

# --- SECUENCIA DE ARRANQUE ---
if conectar_wifi():
    if oled: oled.fill(0); oled.text("Auth FB...", 10, 30); oled.show()
    url_auth = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FB_API_KEY}"
    try:
        res = urequests.post(url_auth, json={"email": FB_EMAIL, "password": FB_PASS, "returnSecureToken": True})
        fb_token = res.json().get("idToken")
        res.close()
        
        if fb_token:
            if oled: oled.fill(0); oled.text("Buscando OTA...", 10, 30); oled.show()
            procesar_ota(fb_token)
            reportar_estado(fb_token, "RUN_OK")
    except:
        pass

# --- EL TRASPASO DE PODER (Anti-Bricking) ---
if oled: oled.fill(0); oled.text("INICIANDO APP...", 10, 30); oled.show()
time.sleep(1)

try:
    # Intenta ejecutar tu código largo
    import app 
except Exception as e:
    # Si te equivocaste en GitHub y el código tiene un error, cae aquí
    if oled: 
        oled.fill(0)
        oled.text("ERROR CRITICO!", 0, 10)
        oled.text("App crasheada.", 0, 25)
        oled.text(str(e)[:16], 0, 45) # Muestra un pedacito del error
        oled.show()
    
    # Intenta avisar a Firebase que el equipo está "ladrillo suave"
    if conectar_wifi():
        try:
            res = urequests.post(url_auth, json={"email": FB_EMAIL, "password": FB_PASS, "returnSecureToken": True})
            fb_token = res.json().get("idToken")
            res.close()
            reportar_estado(fb_token, f"FAIL_CRITICO: {str(e)[:15]}")
        except: pass
    
    # Se queda en un bucle infinito para no reiniciarse a lo loco, 
    # pero el Watchdog Timer (si lo activas después) lo podría reiniciar.
    while True:
        time.sleep(1)
