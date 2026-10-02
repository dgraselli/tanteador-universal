# botones.py
# Control cableado: tres botones a 30 m por UTP, que entran a la Pi por un
# módulo de optoacopladores (12 V del lado del cable, 3,3 V del lado de la
# Pi). Publica en mosquitto los mismos mensajes que el control wifi, así el
# tanteador no se entera de cuál apretaron. Los dos controles conviven.
#
# Misma lógica que el firmware del control wifi (tanteador_remoto_LOLIN.ino):
#   - toque corto en LOCAL o VISITA: suma un punto
#   - mantener 1 s LOCAL o VISITA: resta un punto
#   - LOCAL + VISITA juntos 2 s: cambia el tema
#   - mantener 1 s RESET: pone el tablero en cero
#
# Conexión (ver README): OUT1/OUT2/OUT3 del módulo a GPIO17/27/22 (pines
# físicos 11/13/15). La salida del módulo baja a GND con el botón apretado,
# como los botones del ESP: activo en LOW, con pull-up. Sin nada conectado,
# los pines quedan en HIGH y el servicio no publica nada.

import time

import paho.mqtt.client as mqtt
import RPi.GPIO as GPIO

from registro import Registro

LOCAL = 17    # pin físico 11
VISITA = 27   # pin físico 13
RESET = 22    # pin físico 15

TOQUE_LARGO = 1.0    # s: más que esto resta (o resetea)
TOQUE_TEMA = 2.0     # s: LOCAL + VISITA juntos para cambiar el tema
ANTIRREBOTE = 0.03   # s: menos que esto es ruido del cable, no un toque
PERIODO = 0.01       # s entre lecturas de los pines

class Boton:
    """Estado de un botón de puntos: corto suma, largo resta."""

    def __init__(self, pin, equipo):
        self.pin = pin
        self.equipo = equipo
        self.desde = None       # cuándo se apretó (None = suelto)
        self.largo_enviado = False
        self.anulado = False    # lo absorbió la combinación del tema

def main():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in (LOCAL, VISITA, RESET):
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    registro = Registro('botones')
    cliente = mqtt.Client(client_id='control-cableado')
    cliente.connect_async('localhost', 1883, 60)
    cliente.loop_start()

    def publicar(topico, detalle):
        cliente.publish(topico, '1')
        registro.anotar('toque', topico=topico, detalle=detalle)

    botones = [Boton(LOCAL, 'team1'), Boton(VISITA, 'team2')]
    tema_desde = None
    tema_enviado = False
    reset_desde = None
    reset_enviado = False
    print("Control cableado escuchando en GPIO "
          f"{LOCAL}/{VISITA}/{RESET}", flush=True)

    while True:
        ahora = time.monotonic()
        apretados = [GPIO.input(b.pin) == GPIO.LOW for b in botones]
        combo = all(apretados)

        # Combinación del tema. Anula lo pendiente de los dos botones: si no,
        # apretar el segundo haría que el primero publique un punto al soltar.
        if combo:
            for b in botones:
                b.anulado = True
            if tema_desde is None:
                tema_desde = ahora
            elif not tema_enviado and ahora - tema_desde > TOQUE_TEMA:
                publicar('theme', 'combinación')
                tema_enviado = True
        else:
            tema_desde = None
            tema_enviado = False

        for b, apretado in zip(botones, apretados):
            if apretado:
                if b.desde is None:
                    b.desde = ahora
                if (not b.largo_enviado and not b.anulado and not combo
                        and ahora - b.desde > TOQUE_LARGO):
                    publicar(f'{b.equipo}/down', 'largo')
                    b.largo_enviado = True   # una sola resta por apretón
            elif b.desde is not None:
                dur = ahora - b.desde
                if (not b.largo_enviado and not b.anulado
                        and ANTIRREBOTE <= dur <= TOQUE_LARGO):
                    publicar(f'{b.equipo}/up', 'corto')
                b.desde = None
                b.largo_enviado = False
                b.anulado = False

        if GPIO.input(RESET) == GPIO.LOW:
            if reset_desde is None:
                reset_desde = ahora
            if not reset_enviado and ahora - reset_desde > TOQUE_LARGO:
                publicar('reset', 'largo')
                reset_enviado = True
        else:
            reset_desde = None
            reset_enviado = False

        time.sleep(PERIODO)

if __name__ == '__main__':
    main()
