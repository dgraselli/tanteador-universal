# tanteador_pyqt.py
# Servidor de tanteador con interfaz gráfica PyQt5 y consumo MQTT
# Requiere: pip install PyQt5 paho-mqtt

import os
import sys
import time
import subprocess
import threading
import io
import math
import struct
import wave
from collections import OrderedDict, deque
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtGui import QFont, QFontMetrics, QPainter, QColor, QPen, QLinearGradient, QPolygon
from PyQt5.QtCore import Qt, QTimer, QPoint, pyqtSignal

import paho.mqtt.client as mqtt

from registro import Registro

# Segundos que un equipo tiene que esperar entre una suma y la siguiente.
# Subilo a 2 si todavía se cuela algún doble; bajalo si alguna vez bloquea un
# punto legítimo (no debería: entre tanto y tanto siempre pasan varios segundos).
COOLDOWN_PUNTO = 0.5

# Si el reloj de un segundo llega con más atraso que esto, la interfaz estuvo
# trabada y queda anotado en la bitácora (registro.py).
TRABADO_SEG = 1.5

# Un toque del control wifi que llega con más atraso que esto se descarta: con
# la señal floja, los toques quedaban trabados en TCP y caían todos juntos
# segundos después (bitácora, oct 2026). El control deja de reintentar a los
# mismos 3 s (ABANDONO_MS en el firmware) y avisa con el LED que no contó.
ATRASO_MAX_MS = 3000
# El desfase entre el reloj del control y el de la Pi se estima con el envío
# más rápido de esta ventana: los mensajes trabados nunca son el mínimo.
VENTANA_RELOJ_SEG = 600

# Pin BCM donde está (o va a estar) la chicharra de 12 V, vía MOSFET o relé.
# Los beeps salen por la chicharra Y por el parlante a la vez, con el mismo
# ritmo: queda activo aunque no haya nada conectado (el pin suena al aire),
# así conectar la chicharra no requiere tocar código. None = solo parlante.
CHICHARRA_GPIO = 18  # pin físico 12

# Apagada a propósito (octubre 2026): una semana sin ningún sonido, para
# descartar la chicharra como causa de los cuelgues en la cancha. El pin se
# sigue tomando y queda en LOW: suelto, flotaría y según el módulo la
# chicharra podría quedar sonando. Para volver a encenderla: True.
CHICHARRA = False

# Buzzer de 12 V en la caja del control cableado (ver control-cableado.pdf):
# suena con el mismo ritmo que la chicharra, después de que el número ya se
# pintó, así quien aprieta sabe que el punto entró. Va por un módulo MOSFET
# optoacoplado y un hilo blanco del UTP. None = sin buzzer en el control.
CONTROL_GPIO = 23  # pin físico 16
# Apagado mientras dura la semana sin sonido (ver CHICHARRA): prenderlo
# también tocaría el hilo y los GPIO que se están descartando. Como con la
# chicharra, el pin se toma igual y queda en LOW.
BUZZER_CONTROL = False

# Beeps también por el parlante del monitor (audio HDMI). Deshabilitado: con
# el cable/adaptador HDMI marginal, abrir el audio perturba el enlace, y la
# chicharra ya cubre el aviso. En True, los beeps vuelven a salir por el
# daemon de audio (silencio.service, que también hay que habilitar).
PARLANTE = False

# Ritmo de cada evento: lista de (duración, silencio posterior) en segundos.
# Anotar: un beep largo y fuerte, el mismo para los dos equipos.
# Retroceder: dos beeps cortitos. Reset: uno más largo (y grave, en parlante).
PULSOS = {
    'up': [(0.30, 0)],
    'down': [(0.08, 0.06), (0.08, 0)],
    'reset': [(0.50, 0)],
}

# FIFO del daemon de audio (silencio.service): tiene el canal HDMI siempre
# abierto, así los beeps salen enteros y al instante. Si el daemon no está,
# el beep cae solo a un aplay directo.
FIFO_AUDIO = '/run/tnt/beeps'

# Beeps sintetizados en memoria: el tanteador no depende de ningún .wav en la SD.
SAMPLE_RATE = 44100

def _wav_beep(pulsos, freq):
    """WAV mono de 16 bits con los pulsos (duración, silencio) en segundos.
    Rampa de 5 ms en los extremos de cada pulso para que no meta clics."""
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

BEEPS = {tipo: _wav_beep(pulsos, 440 if tipo == 'reset' else 1000)
         for tipo, pulsos in PULSOS.items()}

# Definición de temas parametrizados. El orden importa: es el orden de rotación
# al cambiar de tema, y el primero es el inicial (los oscuros primero, que son
# los que se usan en la cancha).
THEMES = {
    'universal-bermellon': {
        'background': (0, 0, 0),
        'shadow': (15, 15, 15),
        'num': {
            'local': {'color': (255, 70, 0), 'font': ('Arial', 0.50, True)},
            'visita': {'color': (0, 200, 0), 'font': ('Arial', 0.50, True)},
        },
        'clock': {'color': (200, 200, 200), 'font': ('Arial', 0.18, True)}
    },
    'universal-dark': {
        'background': (0, 0, 0),
        'shadow': (15, 15, 15),
        'num': {
            'local': {'color': (255, 190, 0), 'font': ('Arial', 0.50, True)},
            'visita': {'color': (0, 200, 0), 'font': ('Arial', 0.50, True)},
        },
        'clock': {'color': (200, 200, 200), 'font': ('Arial', 0.18, True)}
    },
    'digital-dark': {
        'background': (10, 10, 10),
        'num': {
            'local': {'color': (255, 190, 0), 'font': ('DS-Digital', 0.58, True)},
            'visita': {'color': (0, 200, 0), 'font': ('DS-Digital', 0.58, True)},
        },
        'clock': {'color': (200, 200, 200), 'font': ('DS-Digital', 0.18, True)}
    },
    'universal': {
        'background': (255, 255, 255),
        'shadow': (240, 240, 240),
        'num': {
            'local': {'color': (200, 0, 0), 'font': ('Arial', 0.50, True)},
            'visita': {'color': (0, 200, 0), 'font': ('Arial', 0.50, True)},
        },
        'clock': {'color': (90, 90, 90), 'font': ('Arial', 0.18, True)}
    },
    'digital': {
        'background': (255, 255, 255),
        'num': {
            'local': {'color': (200, 0, 0), 'font': ('DS-Digital', 0.58, True)},
            'visita': {'color': (0, 200, 0), 'font': ('DS-Digital', 0.58, True)},
        },
        'clock': {'color': (90, 90, 90), 'font': ('DS-Digital', 0.18, True)}
    },
}

class TanteadorWidget(QWidget):

    # Los mensajes MQTT llegan en el hilo de red de paho. Esta señal los cruza
    # al hilo gráfico, único que puede tocar el widget y repintar. Viajan con
    # la hora de llegada (monotonic), para medir cuánto esperó cada toque, y,
    # si viene del control wifi, su nonce, su número y el atraso con que llegó
    # (ver TanteadorMQTT.on_message; '' y -1 para los mensajes sin número).
    mqtt_event = pyqtSignal(str, float, str, int, int)

    def __init__(self):
        super().__init__()

        self.scores = {'local': 0, 'visita': 0, 'ultimo': None}
        self.theme = 'universal-bermellon'
        self.last_reset = time.time()
        # Anti doble-punto: si el mismo equipo suma (o resta) dos veces en menos
        # de COOLDOWN_PUNTO segundos, la segunda se ignora: tapa el doble
        # apretón del botón. Sumas y restas se registran por separado, así una
        # corrección (resta justo después de una suma) entra siempre.
        self.last_up = {'local': 0.0, 'visita': 0.0}
        self.last_down = {'local': 0.0, 'visita': 0.0}
        # Toques del control wifi ya atendidos, (nonce, seq) -> resultado: el
        # control reenvía hasta tener ack, y un reenvío no puede sumar dos
        # veces. Resultados: 'ok' (se aplicó), 'ign' (lo frenó el cooldown),
        # 'tarde' (descartado: no se confirma, ni el original ni sus reenvíos).
        self._vistos = OrderedDict()
        # Contesta al control con el resultado; lo conecta TanteadorMQTT.
        self.acusar = lambda nonce, seq, resultado: None
        self.registro = Registro('tanteador')
        self.registro.anotar('arranque', tema=self.theme)
        # Chicharra y buzzer del control cableado por GPIO, si están
        # configurados. Si RPi.GPIO no está o un pin no se puede tomar, los
        # beeps caen al parlante: un problema de GPIO no puede dejar el
        # tanteador sin arrancar.
        self._gpio = None
        pines = [p for p in (CHICHARRA_GPIO, CONTROL_GPIO) if p is not None]
        if pines:
            try:
                import RPi.GPIO as GPIO
                GPIO.setmode(GPIO.BCM)
                GPIO.setwarnings(False)
                for pin in pines:
                    GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
                self._gpio = GPIO
                self._chicharra_lock = threading.Lock()
            except Exception as e:
                print(f"Chicharra deshabilitada ({e}); beeps por parlante.")
        self.setWindowTitle('Tanteador PyQt')
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.showFullScreen()
        self.setCursor(Qt.BlankCursor)
        self.mqtt_event.connect(self.handle_event)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tic)
        self._ultimo_tic = time.monotonic()
        self.timer.start(1000)
        # Si X arranca antes de que el monitor negocie el EDID (pasa en cada
        # encendido del tablero: se prende todo junto), el fullscreen se hace
        # contra una pantalla que todavía no existe y la ventana queda de 1x1:
        # tablero negro hasta reiniciar el servicio. Este vigía la reestira en
        # cuanto la pantalla real aparece (o cambia: monitor enchufado después).
        self.fs_timer = QTimer(self)
        self.fs_timer.timeout.connect(self._vigilar_fullscreen)
        self.fs_timer.start(5000)

    def _tic(self):
        # El reloj del tablero de paso mide si la interfaz se traba: si este
        # timer de 1 s llega muy tarde, el hilo gráfico estuvo ocupado.
        ahora = time.monotonic()
        atraso = ahora - self._ultimo_tic - 1
        self._ultimo_tic = ahora
        if atraso > TRABADO_SEG:
            self.registro.anotar('trabado', seg=round(atraso, 1))
        self.update()

    def _vigilar_fullscreen(self):
        pantalla = QApplication.primaryScreen()
        if pantalla and self.geometry() != pantalla.geometry():
            g = pantalla.geometry()
            self.registro.anotar('pantalla', ancho=g.width(), alto=g.height())
            self.setGeometry(pantalla.geometry())
            self.showFullScreen()


    def play_sound(self, key):
        tipo = key.split('_')[0]  # 'up_local' -> 'up', 'reset' -> 'reset'
        # Chicharra y parlante suenan a la vez: cada uno cubre al otro si
        # falta (chicharra sin conectar, parlante que no se escucha).
        pines = [p for p, prendido in ((CHICHARRA_GPIO, CHICHARRA),
                                       (CONTROL_GPIO, BUZZER_CONTROL))
                 if p is not None and prendido]
        if self._gpio is not None and pines:
            threading.Thread(target=self._chicharra, args=(PULSOS[tipo], pines),
                             daemon=True).start()
        if not PARLANTE:
            return
        # Primero el daemon de audio, que tiene el canal HDMI siempre abierto
        # (sin él, el monitor abre el audio con retardo y fade-in y se come
        # los beeps cortos). O_NONBLOCK: si no hay nadie leyendo, falla al
        # toque en vez de congelar la interfaz.
        try:
            fd = os.open(FIFO_AUDIO, os.O_WRONLY | os.O_NONBLOCK)
            try:
                os.write(fd, f'{tipo}\n'.encode())
            finally:
                os.close(fd)
            return
        except OSError:
            pass  # el daemon no está: aplay directo, como siempre
        # aplay lee el wav por stdin. Los beeps entran enteros en el buffer del
        # pipe (~64 KB), así que el write no bloquea la interfaz.
        p = subprocess.Popen(['aplay', '-q'], stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        p.stdin.write(BEEPS[tipo])
        p.stdin.close()

    def _chicharra(self, pulsos, pines):
        # Corre en un hilo aparte: los sleep no pueden congelar la interfaz.
        # El lock serializa beeps casi simultáneos (los dos equipos anotando a
        # la vez): el segundo espera al primero en vez de pisarle el pin.
        # Chicharra y buzzer del control suenan juntos, con el mismo ritmo.
        with self._chicharra_lock:
            for dur, silencio in pulsos:
                self._gpio.output(pines, self._gpio.HIGH)
                time.sleep(dur)
                self._gpio.output(pines, self._gpio.LOW)
                if silencio:
                    time.sleep(silencio)


    def paintEvent(self, event):
        qp = QPainter(self)
        w, h = self.width(), self.height()
        theme = THEMES.get(self.theme, THEMES['universal'])
        # Fondo con gradiente vertical
        grad = QLinearGradient(0, 0, 0, h)
        color1 = QColor(*theme['background'])
        color2 = color1.darker(0)
        grad.setColorAt(0, color1)
        grad.setColorAt(1, color2)
        qp.fillRect(0, 0, w, h, grad)
        # Paneles con bordes redondeados y efecto glass
        panel_radius = int(h * 0.07)
        panel_alpha = 180
        qp.setRenderHint(QPainter.Antialiasing)
        # Panel local
        panel_x_local = int(w * 0.03)
        panel_y = 50  # margen fijo contra el borde superior de la pantalla
        panel_w = int(w * 0.44)  # Más ancho
        # El panel pierde por arriba lo que ganó de margen: así el borde de abajo
        # no se mueve y el triángulo y el reloj se quedan donde están.
        panel_h = int(h * 0.72) + 20 - panel_y
        # Los números cuelgan del pie del panel, no de su techo: si mañana cambia
        # el margen de arriba, no se corren.
        num_y = panel_y + panel_h - int(h * 0.65)
        qp.setPen(Qt.NoPen)
        bg = theme['background']
        qp.setBrush(QColor(*theme.get('shadow',bg)))
        qp.drawRoundedRect(panel_x_local, panel_y, panel_w, panel_h, panel_radius, panel_radius)
        # Panel visita
        panel_x_visita = int(w * 0.53)
        qp.drawRoundedRect(panel_x_visita, panel_y, panel_w, panel_h, panel_radius, panel_radius)
        # Indicador del último que anotó
        ultimo = self.scores['ultimo']
        if ultimo in ('local', 'visita'):
            color = QColor(*theme['num'][ultimo]['color'])
            # Flecha hacia arriba debajo del panel. Va pegada al borde exterior
            # (izquierda para local, derecha para visita) porque el reloj está
            # centrado y a esta altura: por el medio se pisarían.
            tri_w = int(h * 0.24)
            tri_h = int(h * 0.16)
            tri_top = panel_y + panel_h + int(h * 0.02)
            if ultimo == 'local':
                cx = panel_x_local + tri_w
            else:
                cx = panel_x_visita + panel_w - tri_w
            qp.setPen(Qt.NoPen)
            qp.setBrush(color)
            qp.drawPolygon(QPolygon([
                QPoint(cx, tri_top),
                QPoint(cx - tri_w // 2, tri_top + tri_h),
                QPoint(cx + tri_w // 2, tri_top + tri_h),
            ]))
        # Reloj (solo hora y minuto)
        elapsed = int(time.time() - self.last_reset)
        horas = elapsed // 3600
        minutos = (elapsed % 3600) // 60
        reloj = f"{horas}:{minutos:02}"
        clock_cfg = theme['clock']
        # Agrando la fuente del reloj
        font_reloj = QFont(clock_cfg['font'][0], int(h * (clock_cfg['font'][1] + 0.04)), QFont.Bold if clock_cfg['font'][2] else QFont.Normal)
        qp.setFont(font_reloj)
        qp.setPen(QColor(*clock_cfg['color']))
        qp.drawText(0, h - int(h * 0.26), w, int(h * 0.25), Qt.AlignHCenter | Qt.AlignVCenter, reloj)
        # Sombra para números
        shadow_offset = int(h * 0.018)
        shadow_color = QColor(0, 0, 0, 180)
        font_num_local = QFont(theme['num']['local']['font'][0], int(h * theme['num']['local']['font'][1]), QFont.Bold if theme['num']['local']['font'][2] else QFont.Normal)
        font_num_visita = QFont(theme['num']['visita']['font'][0], int(h * theme['num']['visita']['font'][1]), QFont.Bold if theme['num']['visita']['font'][2] else QFont.Normal)
        # Con tamaño fijo, tanteos anchos (18, 29, tres cifras) no entran en el
        # rectángulo y drawText los recorta: se achica la fuente solo cuando hace
        # falta, descontando la pluma de la sombra que engorda cada trazo.
        max_num_w = int(w * 0.4) - max(7, int(h * 0.035)) * 2
        font_num_local = self._encoger_hasta_entrar(font_num_local, str(self.scores['local']), max_num_w)
        font_num_visita = self._encoger_hasta_entrar(font_num_visita, str(self.scores['visita']), max_num_w)
        # Sombra local
        qp.setFont(font_num_local)
        qp.setPen(QPen(shadow_color, max(7, int(h * 0.035))))
        qp.drawText(int(w * 0.05)+shadow_offset, num_y+shadow_offset, int(w * 0.4), int(h * 0.62), Qt.AlignCenter, str(self.scores['local']))
        # Sombra visita
        qp.setFont(font_num_visita)
        qp.setPen(QPen(shadow_color, max(7, int(h * 0.035))))
        qp.drawText(int(w * 0.55)+shadow_offset, num_y+shadow_offset, int(w * 0.4), int(h * 0.62), Qt.AlignCenter, str(self.scores['visita']))
        # Números relleno
        qp.setFont(font_num_local)
        qp.setPen(QPen(QColor(*theme['num']['local']['color']), 1))
        qp.drawText(int(w * 0.05), num_y, int(w * 0.4), int(h * 0.62), Qt.AlignCenter, str(self.scores['local']))
        qp.setFont(font_num_visita)
        qp.setPen(QPen(QColor(*theme['num']['visita']['color']), 1))
        qp.drawText(int(w * 0.55), num_y, int(w * 0.4), int(h * 0.62), Qt.AlignCenter, str(self.scores['visita']))

    def _encoger_hasta_entrar(self, font, texto, max_w):
        """Achica la fuente hasta que el texto entre en max_w píxeles."""
        # El ancho crece en proporción al tamaño: se salta directo al que entra.
        # Bajar de a 2 puntos costaba ~45 tamaños nuevos la primera vez que el
        # tanteo pasaba a dos cifras, y Qt carga las métricas de cada uno: en
        # la Pi, el 10 tardaba hasta un segundo en aparecer (bitácora, oct 2026).
        ancho = QFontMetrics(font).horizontalAdvance(texto)
        if ancho > max_w:
            font.setPointSize(max(10, font.pointSize() * max_w // ancho))
        # Lo que el redondeo deje afuera, de a un punto (una o dos vueltas).
        while font.pointSize() > 10 and QFontMetrics(font).horizontalAdvance(texto) > max_w:
            font.setPointSize(font.pointSize() - 1)
        return font

    def _accion_permitida(self, equipo, ultimos):
        """True si pasó el cooldown desde la última acción de ese equipo en
        el registro dado (last_up o last_down)."""
        ahora = time.time()
        if ahora - ultimos[equipo] < COOLDOWN_PUNTO:
            return False
        ultimos[equipo] = ahora
        return True

    def _resultado(self, toque, resultado):
        """Recuerda qué pasó con un toque del control wifi y se lo contesta.
        Los frenados por el cooldown también se contestan ('ign'): si no, el
        control los reenvía y, pasado el cooldown, el reenvío sí sumaría."""
        if toque is None:
            return  # botones.py o el simulador: no esperan respuesta
        self._vistos[toque] = resultado
        while len(self._vistos) > 64:
            self._vistos.popitem(last=False)
        if resultado != 'tarde':
            self.acusar(*toque, resultado)

    def handle_event(self, topic, llegada, nonce='', seq=-1, atraso_ms=-1):
        # Corre siempre en el hilo gráfico (ver mqtt_event).
        cola_ms = round((time.monotonic() - llegada) * 1000)
        toque = (nonce, seq) if nonce else None
        if toque in self._vistos:
            # Reenvío: el ack anterior se perdió. Se repite el mismo resultado.
            self.registro.anotar('repetido', t=topic, seq=seq)
            self._resultado(toque, self._vistos[toque])
            return
        if toque and atraso_ms > ATRASO_MAX_MS:
            # Sin ack: el control avisa solo, con el LED y el buzzer, que no contó.
            self._resultado(toque, 'tarde')
            self.registro.anotar('tarde', t=topic, atraso_ms=atraso_ms)
            return
        sound = None
        evento = None  # lo que va a la bitácora: (tipo, datos)
        if topic == 'team1/up':
            if not self._accion_permitida('local', self.last_up):
                self.registro.anotar('ignorado', eq='local', d=1, cola_ms=cola_ms)
                self._resultado(toque, 'ign')
                return
            self.scores['local'] = min(99, self.scores['local'] + 1)
            self.scores['ultimo'] = 'local'
            sound = 'up_local'
            evento = ('punto', {'eq': 'local', 'd': 1})
        elif topic == 'team1/down':
            if not self._accion_permitida('local', self.last_down):
                self.registro.anotar('ignorado', eq='local', d=-1, cola_ms=cola_ms)
                self._resultado(toque, 'ign')
                return
            self.scores['local'] = max(0, self.scores['local'] - 1)
            sound = 'down_local'
            evento = ('punto', {'eq': 'local', 'd': -1})
        elif topic == 'team2/up':
            if not self._accion_permitida('visita', self.last_up):
                self.registro.anotar('ignorado', eq='visita', d=1, cola_ms=cola_ms)
                self._resultado(toque, 'ign')
                return
            self.scores['visita'] = min(99, self.scores['visita'] + 1)
            self.scores['ultimo'] = 'visita'
            sound = 'up_visita'
            evento = ('punto', {'eq': 'visita', 'd': 1})
        elif topic == 'team2/down':
            if not self._accion_permitida('visita', self.last_down):
                self.registro.anotar('ignorado', eq='visita', d=-1, cola_ms=cola_ms)
                self._resultado(toque, 'ign')
                return
            self.scores['visita'] = max(0, self.scores['visita'] - 1)
            sound = 'down_visita'
            evento = ('punto', {'eq': 'visita', 'd': -1})
        elif topic == 'reset':
            # El marcador con que terminó el partido, antes de borrarlo.
            evento = ('reset', {'l': self.scores['local'], 'v': self.scores['visita']})
            self.scores['local'] = 0
            self.scores['visita'] = 0
            self.scores['ultimo'] = None
            self.last_reset = time.time()
            sound = 'reset'
        elif topic == 'theme':
            # Alternar cíclicamente entre los temas definidos
            theme_names = list(THEMES.keys())
            if self.theme in theme_names:
                idx = theme_names.index(self.theme)
                self.theme = theme_names[(idx + 1) % len(theme_names)]
            else:
                self.theme = theme_names[0]
            print(f"Cambiando tema a: {self.theme}")
            evento = ('tema', {'tema': self.theme})
        else:
            return

        # Primero el número en pantalla, después el sonido: lanzar aplay cuesta
        # unos cuantos ms y el jugador no debe esperarlos para ver su punto.
        t0 = time.monotonic()
        self.repaint()
        pintar_ms = round((time.monotonic() - t0) * 1000)
        # Ya está en pantalla: recién ahora el control puede sonar "anotado".
        self._resultado(toque, 'ok')
        if sound:
            self.play_sound(sound)
        tipo, datos = evento
        if tipo == 'punto':
            datos.update(l=self.scores['local'], v=self.scores['visita'])
        if atraso_ms >= 0:
            datos['atraso_ms'] = atraso_ms
        self.registro.anotar(tipo, cola_ms=cola_ms, pintar_ms=pintar_ms, **datos)

# MQTT callbacks
class TanteadorMQTT:
    def __init__(self, widget):
        self.widget = widget
        # nonce del control -> deque de (llegada, desfase en ms) recientes.
        self.relojes = {}
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        # connect_async + loop_start: si mosquitto todavía no levantó (arranque
        # de la Pi) reintenta solo en vez de abortar.
        self.client.connect_async('localhost', 1883, 60)
        self.client.loop_start()
        widget.acusar = self.acusar
    def on_connect(self, client, userdata, flags, rc):
        topics = [
            'team1/up',
            'team1/down',
            'team2/up',
            'team2/down',
            'reset',
            'theme',
            'latido',
        ]
        for t in topics:
            client.subscribe(t)
        self.widget.registro.anotar('mqtt', estado='conectado')
    def on_disconnect(self, client, userdata, rc):
        self.widget.registro.anotar('mqtt', estado='desconectado', rc=rc)

    def acusar(self, nonce, seq, resultado):
        self.client.publish('ack', f'{nonce},{seq},{resultado}')

    def _desfase(self, nonce, llegada, enviado_ms):
        """Anota una muestra del reloj del control y devuelve el desfase
        mínimo de la ventana: llegada (ms de la Pi) menos envío (ms del
        control) cuando el mensaje viajó sin demora."""
        if nonce not in self.relojes:
            self.relojes = {nonce: deque()}   # el control se reinició
        muestras = self.relojes[nonce]
        muestras.append((llegada, llegada * 1000 - enviado_ms))
        while llegada - muestras[0][0] > VENTANA_RELOJ_SEG:
            muestras.popleft()
        return min(d for _, d in muestras)

    def on_message(self, client, userdata, msg):
        # Sin trabajo pesado acá: el hilo de red vuelve enseguida a leer socket.
        llegada = time.monotonic()
        partes = msg.payload.decode(errors='replace').split(',')
        try:
            if msg.topic == 'latido':
                self._desfase(partes[0], llegada, int(partes[1]))
                return
            # Control wifi: "nonce,seq,t_toque,t_envio" (millis del control).
            # botones.py y el simulador mandan "1": sin número ni atraso.
            if len(partes) == 4:
                nonce, seq, toque, envio = partes[0], int(partes[1]), int(partes[2]), int(partes[3])
                desfase = self._desfase(nonce, llegada, envio)
                atraso = round(llegada * 1000 - desfase - toque)
                self.widget.mqtt_event.emit(msg.topic, llegada, nonce, seq, atraso)
                return
        except (IndexError, ValueError):
            return
        self.widget.mqtt_event.emit(msg.topic, llegada, '', -1, -1)

def main():
    app = QApplication(sys.argv)
    widget = TanteadorWidget()
    widget.show()
    mqtt_client = TanteadorMQTT(widget)
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
