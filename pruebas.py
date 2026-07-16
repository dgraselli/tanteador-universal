# pruebas.py
# Página web de pruebas del tablero, pensada para el celular: conectado a la
# red TNT, abrís http://192.168.216.1 y tenés un botón por prueba, para
# disparo con una mano mientras mirás el monitor con la otra.
#
# Cada prueba aísla un sospechoso del parpadeo del monitor:
#   - Silencio: abre el stream de audio HDMI sin sonido. Si el monitor
#     parpadea con esto, el enlace HDMI se cae solo por arrancar el audio.
#   - Beep: el mismo beep de un punto, pero sin tocar el tanteador.
#   - Chicharra: pulso en el GPIO, sin audio. Prueba el ruido eléctrico
#     del módulo MOSFET/relé por separado.

import io
import json
import math
import struct
import subprocess
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 80

# Mismo pin y misma síntesis que tanteador.py (duplicado a propósito: importar
# tanteador acá cargaría PyQt entero en un segundo proceso, y la Zero no sobra
# memoria).
CHICHARRA_GPIO = 18
SAMPLE_RATE = 44100

def _wav_beep(pulsos, freq):
    """WAV mono de 16 bits con los pulsos (duración, silencio) en segundos.
    Con freq=0 el seno es siempre cero: sale un WAV de silencio, que igual
    abre el stream de audio HDMI, que es lo que la prueba necesita."""
    frames = bytearray()
    rampa = int(SAMPLE_RATE * 0.005)
    for dur, silencio in pulsos:
        n = int(SAMPLE_RATE * dur)
        for i in range(n):
            amp = 32000
            if i < rampa:
                amp = amp * i // rampa
            elif i > n - rampa:
                amp = amp * (n - i) // rampa
            frames += struct.pack('<h', int(amp * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)))
        frames += b'\x00\x00' * int(SAMPLE_RATE * silencio)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(frames))
    return buf.getvalue()

WAVS = {
    'silencio': _wav_beep([(1.0, 0)], 0),
    'beep': _wav_beep([(0.30, 0)], 1000),   # igual al beep de anotar
}

# Una prueba a la vez: un doble toque en el celular no encima dos aplay.
_lock = threading.Lock()

def _aplay(nombre):
    p = subprocess.run(['aplay', '-q'], input=WAVS[nombre],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                       timeout=10)
    if p.returncode != 0:
        err = p.stderr.decode(errors='replace').strip()
        # 524 (ENOTSUPP): el driver vc4-hdmi no ofrece audio porque el monitor
        # no declaró soportarlo. Con un EDID que llega corrupto, pasa aunque el
        # monitor sí tenga audio: es un síntoma más del enlace HDMI fallado.
        if 'error 524' in err:
            raise RuntimeError('el HDMI quedó SIN AUDIO en este arranque: el '
                               'driver no le leyó soporte de audio al monitor '
                               '(EDID corrupto). Los beeps del tanteador '
                               'tampoco están sonando. Dato importante: '
                               'anotalo junto con la hora.')
        raise RuntimeError(err or 'aplay falló')
    return 'sonó por el parlante (HDMI)'

def _chicharra():
    import time
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(CHICHARRA_GPIO, GPIO.OUT, initial=GPIO.LOW)
    GPIO.output(CHICHARRA_GPIO, GPIO.HIGH)
    time.sleep(0.3)
    GPIO.output(CHICHARRA_GPIO, GPIO.LOW)
    # Sin GPIO.cleanup(): dejaría el pin como entrada y el tanteador, que ya
    # lo configuró como salida en su propio proceso, escribiría al vacío.
    return f'pulso de 0.3 s en GPIO{CHICHARRA_GPIO}'

PRUEBAS = {
    '/silencio': lambda: _aplay('silencio'),
    '/beep': lambda: _aplay('beep'),
    '/chicharra': _chicharra,
}

# ── Señal del control remoto ─────────────────────────────────────────────
# La versión para celular de medir-senal.sh: el control publica su RSSI por
# MQTT cada 5 segundos, y acá se muestra en vivo mientras caminás la cancha.
# Los puntos de medición se marcan con un botón de la página, no con el botón
# del LOCAL: así medir no suma tantos en el tablero.

UMBRALES = [(-60, 'excelente'), (-70, 'bien'),
            (-80, 'MARGINAL: se corta a ratos'), (-999, 'SIN ENLACE ÚTIL')]

def _calidad(dbm):
    for limite, texto in UMBRALES:
        if dbm >= limite:
            return texto

class Senal:
    """Escucha los 'rssi' del control por MQTT y lleva los tramos medidos."""

    def __init__(self):
        self.lock = threading.Lock()
        self.ultimo = None      # (timestamp, dbm) de la última muestra
        self.tramos = []        # una lista de dbm por cada punto marcado
        self.error = None
        try:
            import paho.mqtt.client as mqtt
            cliente = mqtt.Client()
            cliente.on_connect = lambda c, u, f, rc: c.subscribe('rssi')
            cliente.on_message = self._mensaje
            # connect_async + loop_start: reintenta solo si mosquitto no está.
            cliente.connect_async('localhost', 1883, 60)
            cliente.loop_start()
        except Exception as e:
            self.error = f'sin MQTT: {e}'

    def _mensaje(self, cliente, userdata, msg):
        try:
            dbm = int(msg.payload)
        except ValueError:
            return
        with self.lock:
            self.ultimo = (time.time(), dbm)
            # Con 500 muestras (~40 min) alcanza para cualquier medición; el
            # tope evita crecer para siempre si alguien deja un punto abierto.
            if self.tramos and len(self.tramos[-1]) < 500:
                self.tramos[-1].append(dbm)

    def punto(self):
        with self.lock:
            self.tramos.append([])
            return f'punto {len(self.tramos)} marcado: quedate quieto ~20 s'

    def reset(self):
        with self.lock:
            self.tramos = []
            return 'medición reiniciada'

    def estado(self):
        with self.lock:
            r = {'error': self.error, 'ahora': None, 'tramos': []}
            if self.ultimo:
                ts, dbm = self.ultimo
                r['ahora'] = {'dbm': dbm, 'edad': round(time.time() - ts),
                              'calidad': _calidad(dbm)}
            for t in self.tramos:
                if t:
                    peor = min(t)
                    r['tramos'].append({'muestras': len(t), 'peor': peor,
                                        'mejor': max(t),
                                        'media': round(sum(t) / len(t)),
                                        'calidad': _calidad(peor)})
                else:
                    r['tramos'].append({'muestras': 0})
            return r

SENAL = Senal()

PAGINA = """<!doctype html>
<html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pruebas del tablero</title>
<style>
  body { background: #111; color: #eee; font-family: sans-serif;
         max-width: 30em; margin: 0 auto; padding: 1em; }
  h1 { font-size: 1.3em; color: #ffbe00; }
  p { color: #aaa; line-height: 1.4; }
  button { display: block; width: 100%; padding: 1.1em; margin: 1em 0 0.2em;
           font-size: 1.2em; font-weight: bold; border: 0; border-radius: 0.6em;
           background: #ffbe00; color: #111; }
  button:disabled { background: #555; color: #999; }
  small { color: #888; display: block; line-height: 1.35; }
  #estado { margin-top: 1.2em; min-height: 2em; font-size: 1.1em; }
</style></head><body>
<h1>Pruebas del tablero</h1>
<p>Parate donde veas el monitor, tocá un botón y fijate si la pantalla
parpadea (se pone negra y vuelve).</p>

<button onclick="probar('/silencio', this)">&#128263; Silencio 1&nbsp;s</button>
<small>Abre el audio HDMI sin sonido. <b>La prueba clave:</b> si el monitor
parpadea con esto, el enlace HDMI se cae solo por arrancar el audio.</small>

<button onclick="probar('/beep', this)">&#128266; Beep de punto</button>
<small>El mismo beep de anotar, sin sumar ning&uacute;n punto.</small>

<button onclick="probar('/chicharra', this)">&#9889; Chicharra 0,3&nbsp;s</button>
<small>Pulso en el GPIO, sin audio. Prueba el ruido el&eacute;ctrico del
m&oacute;dulo de la chicharra por separado. Ojo: si la chicharra est&aacute;
conectada, suena fuerte.</small>

<div id="estado"></div>
<script>
async function probar(ruta, boton) {
  const estado = document.getElementById('estado');
  for (const b of document.querySelectorAll('button')) b.disabled = true;
  estado.textContent = '\\u23f3 Probando\\u2026 mir\\u00e1 el monitor';
  try {
    const r = await fetch(ruta, {method: 'POST'});
    const texto = await r.text();
    estado.textContent = (r.ok ? '\\u2705 ' : '\\u274c ') + texto;
  } catch (e) {
    estado.textContent = '\\u274c sin respuesta: ' + e;
  }
  for (const b of document.querySelectorAll('button')) b.disabled = false;
}
</script>
</body></html>
"""

PAGINA_SENAL = """<!doctype html>
<html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Señal del control remoto</title>
<style>
  body { background: #111; color: #eee; font-family: sans-serif;
         max-width: 30em; margin: 0 auto; padding: 1em; }
  h1 { font-size: 1.3em; color: #ffbe00; }
  p, small { color: #aaa; line-height: 1.4; }
  #dbm { font-size: 4em; font-weight: bold; text-align: center; margin: 0.2em 0 0; }
  #calidad { text-align: center; font-size: 1.3em; min-height: 1.4em; }
  #edad { text-align: center; color: #888; min-height: 1.4em; }
  button { display: block; width: 100%; padding: 1.1em; margin: 1em 0 0.2em;
           font-size: 1.2em; font-weight: bold; border: 0; border-radius: 0.6em;
           background: #ffbe00; color: #111; }
  button.gris { background: #444; color: #ccc; }
  table { width: 100%; border-collapse: collapse; margin-top: 1em; }
  th, td { padding: 0.4em 0.3em; text-align: right; border-bottom: 1px solid #333; }
  th:first-child, td:first-child { text-align: left; }
  .exc { color: #5d5; } .bien { color: #cc5; } .marg { color: #f92; } .mal { color: #f55; }
</style></head><body>
<h1>Señal del control remoto</h1>
<p>Caminá la cancha con el control <b>encendido</b> mirando esto (publica cada
5&nbsp;s). En cada punto que quieras medir, tocá <b>Marcar punto</b> y quedate
quieto ~20&nbsp;s. No suma tantos en el tablero.</p>

<div id="dbm">—</div>
<div id="calidad"></div>
<div id="edad"></div>

<button onclick="accion('/punto')">&#128205; Marcar punto</button>
<button class="gris" onclick="accion('/senal/reset')">Reiniciar medici&oacute;n</button>

<div id="aviso"></div>
<table id="tramos" hidden>
<thead><tr><th>Punto</th><th>muestras</th><th>peor</th><th>mejor</th><th>media</th></tr></thead>
<tbody></tbody>
</table>
<small>La calidad de cada punto se juzga por el <b>peor</b> valor: de −30 a −60
excelente, hasta −70 bien, hasta −80 marginal (se corta a ratos), peor que −85
no hay enlace. El número que importa es el peor del punto más lejano.</small>

<script>
function clase(dbm) {
  return dbm >= -60 ? 'exc' : dbm >= -70 ? 'bien' : dbm >= -80 ? 'marg' : 'mal';
}
async function refrescar() {
  let e;
  try { e = await (await fetch('/senal/datos')).json(); }
  catch (err) { document.getElementById('calidad').textContent = 'sin respuesta de la Pi'; return; }
  const dbm = document.getElementById('dbm');
  const cal = document.getElementById('calidad');
  const edad = document.getElementById('edad');
  if (e.error) { cal.textContent = e.error; return; }
  if (!e.ahora) {
    dbm.textContent = '—';
    cal.textContent = 'esperando al control\\u2026';
    edad.textContent = '\\u00bfest\\u00e1 prendido y en la red?';
  } else {
    dbm.textContent = e.ahora.dbm;
    dbm.className = clase(e.ahora.dbm);
    cal.textContent = e.ahora.calidad;
    cal.className = clase(e.ahora.dbm);
    edad.textContent = e.ahora.edad > 12
      ? 'sin noticias hace ' + e.ahora.edad + ' s \\u2014 \\u00bfse apag\\u00f3 el control?'
      : 'hace ' + e.ahora.edad + ' s';
  }
  const tabla = document.getElementById('tramos');
  tabla.hidden = e.tramos.length === 0;
  const cuerpo = tabla.querySelector('tbody');
  cuerpo.innerHTML = '';
  e.tramos.forEach((t, i) => {
    const tr = document.createElement('tr');
    if (t.muestras === 0) {
      tr.innerHTML = '<td>' + (i + 1) + '</td><td>0</td><td colspan="3">esperando muestras\\u2026</td>';
    } else {
      tr.innerHTML = '<td>' + (i + 1) + '</td><td>' + t.muestras + '</td>' +
        '<td class="' + clase(t.peor) + '">' + t.peor + '</td>' +
        '<td>' + t.mejor + '</td><td>' + t.media + '</td>';
    }
    cuerpo.appendChild(tr);
  });
}
async function accion(ruta) {
  try { await fetch(ruta, {method: 'POST'}); } catch (e) {}
  refrescar();
}
refrescar();
setInterval(refrescar, 2000);
</script>
</body></html>
"""

class Handler(BaseHTTPRequestHandler):

    def _responder(self, codigo, texto, tipo='text/plain'):
        cuerpo = texto.encode()
        self.send_response(codigo)
        self.send_header('Content-Type', f'{tipo}; charset=utf-8')
        self.send_header('Content-Length', str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        if self.path == '/':
            self._responder(200, PAGINA, 'text/html')
        elif self.path == '/senal':
            self._responder(200, PAGINA_SENAL, 'text/html')
        elif self.path == '/senal/datos':
            self._responder(200, json.dumps(SENAL.estado()), 'application/json')
        else:
            self._responder(404, 'no existe')

    def do_POST(self):
        # Las acciones de la medición de señal no compiten por nada: van sin
        # el lock de las pruebas de sonido.
        if self.path == '/punto':
            self._responder(200, SENAL.punto())
            return
        if self.path == '/senal/reset':
            self._responder(200, SENAL.reset())
            return
        prueba = PRUEBAS.get(self.path)
        if prueba is None:
            self._responder(404, 'no existe')
            return
        if not _lock.acquire(blocking=False):
            self._responder(409, 'hay una prueba en curso, esperá que termine')
            return
        try:
            self._responder(200, prueba())
        except Exception as e:
            self._responder(500, f'falló: {e}')
        finally:
            _lock.release()

    def log_message(self, formato, *args):
        # Al journal, para correlacionar cada prueba con lo que se vio.
        print(f"{self.address_string()} {formato % args}", flush=True)

def main():
    servidor = ThreadingHTTPServer(('', PORT), Handler)
    print(f"Página de pruebas en el puerto {PORT}", flush=True)
    servidor.serve_forever()

if __name__ == '__main__':
    main()
