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
import math
import struct
import subprocess
import sys
import threading
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
        raise RuntimeError(p.stderr.decode(errors='replace').strip() or 'aplay falló')
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
        else:
            self._responder(404, 'no existe')

    def do_POST(self):
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
