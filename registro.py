# registro.py
# Bitácora del tablero: una línea JSON por evento, en el pendrive TNTLOG.
#
# La SD está en solo lectura (overlayroot): lo que se escribe ahí vive en RAM
# y se pierde al desenchufar. El pendrive es aparte del overlay, así que la
# bitácora sobrevive a los apagados; si se corrompe por un corte de luz, el
# sistema sigue intacto. Sin pendrive montado, se escribe en RAM (/tmp) para
# no perder la sesión en curso.
#
# La Pi no tiene reloj (ni internet): al arrancar, la hora del sistema es
# cualquier cosa. Por eso cada evento lleva, además de la hora de pared 'ts',
# los segundos desde el encendido 'm' (CLOCK_BOOTTIME, que no salta) y el
# encendido 'b' al que pertenece. Cuando un celular pone la Pi en hora (evento
# 'reloj'), historial.py recalcula la hora de todos los eventos de ese
# encendido, incluso los anteriores.
#
# Escribe tanto tanteador.py como pruebas.py, en el mismo archivo: cada línea
# va en un solo write con O_APPEND, así que no se mezclan.

import json
import os
import queue
import threading
import time

PENDRIVE = '/media/tntlog'
ARCHIVO = 'registro.jsonl'
RESPALDO_RAM = '/tmp/tnt-registro.jsonl'

with open('/proc/sys/kernel/random/boot_id') as f:
    ENCENDIDO = f.read().strip()[:8]

def ruta_registro():
    if os.path.ismount(PENDRIVE):
        return os.path.join(PENDRIVE, ARCHIVO)
    return RESPALDO_RAM

def ultimo_ts():
    """Hora de pared del último evento registrado, o None."""
    try:
        with open(ruta_registro(), 'rb') as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 4096))
            lineas = f.read().splitlines()
    except OSError:
        return None
    for linea in reversed(lineas):
        try:
            return json.loads(linea)['ts']
        except (ValueError, KeyError):
            continue
    return None

class Registro:
    """anotar() no bloquea nunca: encola y un hilo aparte escribe. Un
    pendrive lento o colgado no puede trabar la pantalla del tanteador."""

    def __init__(self, origen):
        self.origen = origen
        self._cola = queue.SimpleQueue()
        self._ultimo_error = 0.0
        threading.Thread(target=self._escritor, daemon=True).start()

    def anotar(self, tipo, **datos):
        self._cola.put({'ts': round(time.time(), 3),
                        'm': round(time.clock_gettime(time.CLOCK_BOOTTIME), 3),
                        'b': ENCENDIDO, 'o': self.origen, 'tipo': tipo,
                        **datos})

    def _escritor(self):
        while True:
            ev = self._cola.get()
            linea = json.dumps(ev, ensure_ascii=False, separators=(',', ':')) + '\n'
            try:
                # Abrir en cada evento: si sacan y vuelven a poner el pendrive,
                # se sigue escribiendo donde corresponde.
                fd = os.open(ruta_registro(), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
                try:
                    os.write(fd, linea.encode())
                    os.fsync(fd)  # un corte de luz no se lleva los últimos eventos
                finally:
                    os.close(fd)
            except OSError as e:
                # Al journal, pero sin inundarlo si el pendrive murió.
                if time.monotonic() - self._ultimo_error > 60:
                    self._ultimo_error = time.monotonic()
                    print(f"registro: no pude escribir ({e})", flush=True)
