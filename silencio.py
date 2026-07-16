# silencio.py
# Daemon de audio del tanteador: el canal HDMI queda siempre abierto.
#
# El monitor tarda unas décimas en abrir el audio cada vez que un aplay
# arranca, y lo abre con fade-in: los beeps cortos salían cortados o bajitos.
# El vc4-hdmi no permite dmix (solo acepta IEC958), así que la mezcla clásica
# de ALSA no es una opción: acá hay UN solo proceso dueño del dispositivo,
# reproduciendo silencio todo el tiempo, que recibe pedidos de beep por un
# FIFO y los intercala en el stream sin cerrar nunca el canal.
#
# Protocolo: una línea por sonido en /run/tnt/beeps ('up', 'down', 'reset',
# 'beep', 'silencio'). tanteador.py y pruebas.py escriben ahí; si este daemon
# no está corriendo, caen solos al aplay directo de siempre.

import math
import os
import struct
import subprocess
import threading
import time

FIFO = '/run/tnt/beeps'
RATE = 48000                          # la tasa nativa del HDMI
CHUNK_FRAMES = RATE // 20             # 50 ms por escritura
SILENCIO = b'\x00' * (CHUNK_FRAMES * 4)   # S16 estéreo: 4 bytes por frame

# Mismos ritmos y tonos que PULSOS en tanteador.py; 'beep' y 'silencio' son
# los de la página de pruebas.
TONOS = {
    'up': ([(0.30, 0)], 1000),
    'down': ([(0.08, 0.06), (0.08, 0)], 1000),
    'reset': ([(0.50, 0)], 440),
    'beep': ([(0.30, 0)], 1000),
    'silencio': ([(1.0, 0)], 0),
}

def _pcm(pulsos, freq):
    """S16 estéreo crudo a 48 kHz, con rampas de 5 ms contra los clics."""
    frames = bytearray()
    rampa = int(RATE * 0.005)
    for dur, silencio in pulsos:
        n = int(RATE * dur)
        for i in range(n):
            amp = 32000
            if i < rampa:
                amp = amp * i // rampa
            elif i > n - rampa:
                amp = amp * (n - i) // rampa
            muestra = struct.pack('<h', int(amp * math.sin(2 * math.pi * freq * i / RATE)))
            frames += muestra + muestra
        frames += b'\x00' * (4 * int(RATE * silencio))
    return bytes(frames)

PCM = {nombre: _pcm(*spec) for nombre, spec in TONOS.items()}

# PCM pendiente de salir. Un beep nuevo PISA al pendiente en vez de encolarse:
# un beep atrasado no le sirve a nadie.
_cola = bytearray()
_lock = threading.Lock()

def _lector():
    """Lee pedidos del FIFO. El open bloquea hasta que alguien escriba, y el
    for termina cuando el que escribe cierra: se reabre y a esperar el próximo."""
    while True:
        try:
            with open(FIFO) as f:
                for linea in f:
                    pcm = PCM.get(linea.strip())
                    if pcm:
                        with _lock:
                            _cola[:] = pcm
        except OSError:
            time.sleep(1)

def main():
    if not os.path.exists(FIFO):
        os.mkfifo(FIFO)
    threading.Thread(target=_lector, daemon=True).start()

    periodo = CHUNK_FRAMES / RATE
    while True:
        # Buffer de 100 ms: es el techo del retardo entre pedir un beep y
        # escucharlo. Más chico glitchea si la Zero se distrae; más grande
        # atrasa los beeps.
        p = subprocess.Popen(['aplay', '-q', '-t', 'raw', '-f', 'S16_LE',
                              '-r', str(RATE), '-c', '2',
                              '--buffer-time=100000'],
                             stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        print("canal HDMI abierto", flush=True)
        try:
            # Escrituras marcadas por reloj, no por la contrapresión del pipe:
            # si dejáramos que el pipe se llene, cada beep esperaría atrás de
            # medio segundo de silencio ya escrito.
            proxima = time.monotonic()
            while True:
                with _lock:
                    if _cola:
                        data = bytes(_cola[:len(SILENCIO)])
                        del _cola[:len(SILENCIO)]
                        data += b'\x00' * (len(SILENCIO) - len(data))
                    else:
                        data = SILENCIO
                p.stdin.write(data)
                proxima += periodo
                espera = proxima - time.monotonic()
                if espera > 0:
                    time.sleep(espera)
                else:
                    proxima = time.monotonic()  # nos atrasamos: resincronizar
        except OSError:
            # Sin monitor con audio, aplay muere enseguida: esperar un poco
            # y volver a intentar (cuando enchufen el HDMI, esto se recupera).
            try:
                p.stdin.close()
            except OSError:
                pass
            p.wait()
            print("aplay se cayó (¿HDMI sin audio?); reintento en 5 s", flush=True)
            time.sleep(5)

if __name__ == '__main__':
    main()
