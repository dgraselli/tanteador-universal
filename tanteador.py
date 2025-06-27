# tanteador_pyqt.py
# Servidor de tanteador con interfaz gráfica PyQt5 y consumo MQTT
# Requiere: pip install PyQt5 paho-mqtt

import sys
import time
from PyQt5.QtWidgets import QApplication, QWidget, QLabel
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QLinearGradient
from PyQt5.QtCore import Qt, QTimer
#from PyQt5.QtMultimedia import QSound
#from PyQt5.QtCore import pyqtSignal

import paho.mqtt.client as mqtt
import os

# Definición de temas parametrizados
THEMES = {
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
    'universal-dark': {
        'background': (0, 0, 0),
        'shadow': (15, 15, 15),
        'num': {
            'local': {'color': (200, 0, 0), 'font': ('Arial', 0.50, True)},
            'visita': {'color': (0, 200, 0), 'font': ('Arial', 0.50, True)},
        },
        'clock': {'color': (200, 200, 200), 'font': ('Arial', 0.18, True)}
    },
    'digital-dark': {
        'background': (10, 10, 10),
        'num': {
            'local': {'color': (200, 0, 0), 'font': ('DS-Digital', 0.58, True)},
            'visita': {'color': (0, 200, 0), 'font': ('DS-Digital', 0.58, True)},
        },
        'clock': {'color': (200, 200, 200), 'font': ('DS-Digital', 0.18, True)}
    },
}

class TanteadorWidget(QWidget):
        
    def __init__(self):
        super().__init__()
        
        self.scores = {'local': 0, 'visita': 0, 'reset': 0, 'ultimo': None}
        self.theme = 'universal-dark'
        self.last_reset = time.time()
        self.setWindowTitle('Tanteador PyQt')
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.showFullScreen()
        self.setCursor(Qt.BlankCursor)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(1000)


    def play_sound(self, key):
        path = os.path.join(os.path.dirname(__file__), 'sonidos', self.theme, f'{key}.wav')
        print(path)
        if path and os.path.exists(path):
            os.system(f"aplay {path} &")
        else:
            path = os.path.join(os.path.dirname(__file__), 'sonidos', f'{key}.wav')
            if path and os.path.exists(path):
                os.system(f"aplay {path} &")
            

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
        panel_y = int(h * 0.01)  # Subido casi al tope
        panel_w = int(w * 0.44)  # Más ancho
        panel_h = int(h * 0.72)  # Más alto
        qp.setPen(Qt.NoPen)
        bg = theme['background']
        qp.setBrush(QColor(*theme.get('shadow',bg)))
        qp.drawRoundedRect(panel_x_local, panel_y, panel_w, panel_h, panel_radius, panel_radius)
        # Panel visita
        panel_x_visita = int(w * 0.53)
        qp.drawRoundedRect(panel_x_visita, panel_y, panel_w, panel_h, panel_radius, panel_radius)
        # Borde indicador del último que anotó
        border_width = max(6, int(h * 0.018))
        if self.scores['ultimo'] == 'local':
            qp.setPen(QPen(QColor(*theme['num']['local']['color']), border_width))
            qp.setBrush(Qt.NoBrush)
            qp.drawRoundedRect(panel_x_local, panel_y, panel_w, panel_h, panel_radius, panel_radius)
        elif self.scores['ultimo'] == 'visita':
            qp.setPen(QPen(QColor(*theme['num']['visita']['color']), border_width))
            qp.setBrush(Qt.NoBrush)
            qp.drawRoundedRect(panel_x_visita, panel_y, panel_w, panel_h, panel_radius, panel_radius)
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
        # Sombra local
        qp.setFont(font_num_local)
        qp.setPen(QPen(shadow_color, max(7, int(h * 0.035))))
        qp.drawText(int(w * 0.05)+shadow_offset, panel_y + int(h * 0.07)+shadow_offset, int(w * 0.4), int(h * 0.62), Qt.AlignCenter, str(self.scores['local']))
        # Sombra visita
        qp.setFont(font_num_visita)
        qp.setPen(QPen(shadow_color, max(7, int(h * 0.035))))
        qp.drawText(int(w * 0.55)+shadow_offset, panel_y + int(h * 0.07)+shadow_offset, int(w * 0.4), int(h * 0.62), Qt.AlignCenter, str(self.scores['visita']))
        # Números relleno
        qp.setFont(font_num_local)
        qp.setPen(QPen(QColor(*theme['num']['local']['color']), 1))
        qp.drawText(int(w * 0.05), panel_y + int(h * 0.07), int(w * 0.4), int(h * 0.62), Qt.AlignCenter, str(self.scores['local']))
        qp.setFont(font_num_visita)
        qp.setPen(QPen(QColor(*theme['num']['visita']['color']), 1))
        qp.drawText(int(w * 0.55), panel_y + int(h * 0.07), int(w * 0.4), int(h * 0.62), Qt.AlignCenter, str(self.scores['visita']))

    def update_scores(self, scores, theme):
        self.scores = scores
        self.theme = theme
        if scores.get('reset'):
            self.last_reset = time.time()
            self.scores['reset'] = None
        self.update()

# MQTT callbacks
class TanteadorMQTT:
    def __init__(self, widget):
        self.widget = widget
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect('localhost', 1883, 60)
        self.client.loop_start()
    def on_connect(self, client, userdata, flags, rc):
        topics = [
            'team1/up',
            'team1/down',
            'team2/up',
            'team2/down',
            'reset',
            'theme'
        ]
        for t in topics:
            client.subscribe(t)
    def on_message(self, client, userdata, msg):
        topic = msg.topic
        scores = self.widget.scores.copy()
        theme = self.widget.theme
        if topic == 'team1/up':
            scores['local'] = min(99, scores['local'] + 1)
            scores['ultimo'] = 'local'
            self.widget.play_sound('up_local')

        elif topic == 'team1/down':
            scores['local'] = max(0, scores['local'] - 1)
            self.widget.play_sound('down_local')
        elif topic == 'team2/up':
            scores['visita'] = min(99, scores['visita'] + 1)
            scores['ultimo'] = 'visita'
            self.widget.play_sound('up_visita')
        elif topic == 'team2/down':
            scores['visita'] = max(0, scores['visita'] - 1)
            self.widget.play_sound('down_visita')
        elif topic == 'reset':
            scores['local'] = 0
            scores['visita'] = 0
            scores['reset'] = 1
            scores['ultimo'] = None
            self.widget.play_sound('reset')
        elif topic == 'theme':
            # Alternar cíclicamente entre los temas definidos
            theme_names = list(THEMES.keys())
            if theme in theme_names:
                idx = theme_names.index(theme)
                theme = theme_names[(idx + 1) % len(theme_names)]
            else:
                theme = theme_names[0]
            print(f"Cambiando tema a: {theme}")
        self.widget.update_scores(scores, theme)

def main():
    app = QApplication(sys.argv)
    widget = TanteadorWidget()
    widget.show()
    mqtt_client = TanteadorMQTT(widget)
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
