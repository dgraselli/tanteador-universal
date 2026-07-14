#!/usr/bin/env python3
"""Cartel de arranque del tanteador.

Dibuja un texto en letras grandes de bloques, centrado y con color. Lo usa
splash.service para tapar el log del kernel mientras la Pi arranca.

El texto y los colores salen de splash.conf:

    ./splash.py                        # lee splash.conf
    ./splash.py "CLUB UNIVERSAL"       # texto suelto, para probar
    ./splash.py --colores "rojo verde" "CLUB UNIVERSAL"
    ./splash.py --cols 80 --rows 24 "HOLA"   # simula otra pantalla

Sin dependencias a propósito: la Pi no tiene internet, así que no se le puede
instalar figlet ni nada por el estilo. La fuente va acá adentro.
"""

import os
import sys

# Fuente de bloques, 7x7, con trazos de 2 píxeles de ancho: es lo que le da el
# cuerpo. Con trazos de 1 píxel las letras se ven flacas en una pantalla grande.
FUENTE = {
    'A': "..###..|.##.##.|##...##|##...##|#######|##...##|##...##",
    'B': "######.|##...##|##...##|######.|##...##|##...##|######.",
    'C': ".#####.|##...##|##.....|##.....|##.....|##...##|.#####.",
    'D': "######.|##...##|##...##|##...##|##...##|##...##|######.",
    'E': "#######|##.....|##.....|#####..|##.....|##.....|#######",
    'F': "#######|##.....|##.....|#####..|##.....|##.....|##.....",
    'G': ".#####.|##...##|##.....|##..###|##...##|##...##|.#####.",
    'H': "##...##|##...##|##...##|#######|##...##|##...##|##...##",
    'I': "#######|..###..|..###..|..###..|..###..|..###..|#######",
    'J': "....###|.....##|.....##|.....##|.....##|##...##|.#####.",
    'K': "##...##|##..##.|##.##..|####...|##.##..|##..##.|##...##",
    'L': "##.....|##.....|##.....|##.....|##.....|##.....|#######",
    'M': "##...##|###.###|#######|##.#.##|##...##|##...##|##...##",
    'N': "##...##|###..##|####.##|##.####|##..###|##...##|##...##",
    'O': ".#####.|##...##|##...##|##...##|##...##|##...##|.#####.",
    'P': "######.|##...##|##...##|######.|##.....|##.....|##.....",
    'Q': ".#####.|##...##|##...##|##...##|##.#.##|##..##.|.####.#",
    'R': "######.|##...##|##...##|######.|##.##..|##..##.|##...##",
    'S': ".#####.|##...##|##.....|.#####.|.....##|##...##|.#####.",
    'T': "#######|..###..|..###..|..###..|..###..|..###..|..###..",
    'U': "##...##|##...##|##...##|##...##|##...##|##...##|.#####.",
    'V': "##...##|##...##|##...##|##...##|##...##|.##.##.|..###..",
    'W': "##...##|##...##|##...##|##.#.##|#######|###.###|##...##",
    'X': "##...##|##...##|.##.##.|..###..|.##.##.|##...##|##...##",
    'Y': "##...##|##...##|.##.##.|..###..|..###..|..###..|..###..",
    'Z': "#######|....##.|...##..|..##...|.##....|##.....|#######",
    '0': ".#####.|##...##|##..###|##.#.##|###..##|##...##|.#####.",
    '1': "..###..|.####..|..###..|..###..|..###..|..###..|.#####.",
    '2': ".#####.|##...##|....##.|...##..|..##...|.##....|#######",
    '3': "######.|.....##|.....##|.#####.|.....##|.....##|######.",
    '4': "...###.|..####.|.##.##.|##..##.|#######|....##.|....##.",
    '5': "#######|##.....|######.|.....##|.....##|##...##|.#####.",
    '6': ".#####.|##...##|##.....|######.|##...##|##...##|.#####.",
    '7': "#######|.....##|....##.|...##..|..##...|..##...|..##...",
    '8': ".#####.|##...##|##...##|.#####.|##...##|##...##|.#####.",
    '9': ".#####.|##...##|##...##|.######|.....##|##...##|.#####.",
    '-': ".......|.......|.......|#######|.......|.......|.......",
    '.': ".......|.......|.......|.......|.......|.###...|.###...",
    "'": "..##...|..##...|.......|.......|.......|.......|.......",
    '!': "..##...|..##...|..##...|..##...|..##...|.......|..##...",
    ' ': ".......|.......|.......|.......|.......|.......|.......",
}

ALTO = 7
ANCHO = 7
SEPARACION = 1          # casillas entre letra y letra
BLOQUE = '█'

COLORES = {
    'rojo':     '\033[1;31m',
    'verde':    '\033[1;32m',
    'amarillo': '\033[1;33m',
    'azul':     '\033[1;34m',
    'magenta':  '\033[1;35m',
    'cyan':     '\033[1;36m',
    'blanco':   '\033[1;37m',
    'gris':     '\033[0;37m',
}
RESET = '\033[0m'


def glifo(c):
    return FUENTE.get(c.upper(), FUENTE[' ']).split('|')


def ancho_casillas(texto):
    """Ancho de una línea, en casillas de la fuente."""
    if not texto:
        return 0
    return len(texto) * (ANCHO + SEPARACION) - SEPARACION


def repartir(palabras, n_lineas):
    """Reparte las palabras en n renglones, lo más parejo posible."""
    if n_lineas >= len(palabras):
        return [[p] for p in palabras]
    lineas, por_linea = [], len(palabras) / n_lineas
    for i in range(n_lineas):
        lineas.append(palabras[round(i * por_linea):round((i + 1) * por_linea)])
    return lineas


def elegir_disposicion(palabras, cols, filas):
    """Busca el reparto en renglones y la escala que llenen mejor la pantalla.

    Devuelve (renglones, ex, ey): cuántas columnas y cuántas filas de consola
    mide cada casilla de la fuente. Van por separado porque los caracteres de
    terminal son como el doble de altos que de anchos: con ex = 2*ey las letras
    salen con su proporción real.
    """
    if not palabras:
        return [], 0, 0

    mejor_renglones, mejor_ex, mejor_ey = [], 0, 0
    for n in range(1, len(palabras) + 1):
        renglones = repartir(palabras, n)
        ancho_px = max(ancho_casillas(' '.join(r)) for r in renglones)
        alto_px = n * ALTO + (n - 1)          # un renglón de hueco entre líneas
        for ey in range(1, 9):
            for ex in range(1, 13):
                # No dejamos que la letra se deforme demasiado: entre un poco
                # angosta y un poco ancha respecto de su proporción real.
                if not 0.6 <= ex / (2 * ey) <= 1.15:
                    continue
                if ancho_px * ex > cols - 2 or alto_px * ey > filas - 2:
                    continue
                if ex * ey > mejor_ex * mejor_ey:
                    mejor_renglones, mejor_ex, mejor_ey = renglones, ex, ey
    return mejor_renglones, mejor_ex, mejor_ey


def colorear(palabras_linea, colores):
    """Un color por palabra; si faltan colores, se repite el último."""
    fuera = []
    for i, palabra in enumerate(palabras_linea):
        color = colores[i] if i < len(colores) else (colores[-1] if colores else None)
        fuera.append((palabra, COLORES.get(color, '')))
    return fuera


def dibujar(texto, cols, filas, colores=None):
    palabras = texto.split()
    renglones, ex, ey = elegir_disposicion(palabras, cols, filas)
    if ex < 1:
        return [texto.center(cols)]

    # A cada palabra le toca su color, en el orden en que aparecen en el texto.
    colores = colores or []
    n = 0
    salida = []
    for i, renglon in enumerate(renglones):
        if i:
            salida += [''] * ey                     # hueco entre renglones
        pintadas = colorear(renglon, colores[n:])
        n += len(renglon)

        for fila in range(ALTO):
            # Cada palabra es un pedazo con su color; entre palabras, un espacio.
            pedazos, ancho_visible = [], 0
            for j, (palabra, color) in enumerate(pintadas):
                if j:
                    hueco = ' ' * ((ANCHO + SEPARACION) * ex)   # el espacio entre palabras
                    pedazos.append(hueco)
                    ancho_visible += len(hueco)
                casillas = ''
                for k, letra in enumerate(palabra):
                    if k:
                        casillas += '.' * SEPARACION
                    casillas += glifo(letra)[fila]
                pintado = ''.join(BLOQUE * ex if c == '#' else ' ' * ex
                                  for c in casillas)
                ancho_visible += len(pintado)
                pedazos.append(f"{color}{pintado}{RESET}" if color else pintado)

            sangria = ' ' * max(0, (cols - ancho_visible) // 2)
            salida += [sangria + ''.join(pedazos)] * ey

    arriba = max(0, (filas - len(salida)) // 2)     # centrado vertical
    return [''] * arriba + salida


def leer_config(base):
    """Lee TEXTO y COLORES de splash.conf."""
    ruta = os.path.join(base, 'splash.conf')
    valores = {}
    if not os.path.exists(ruta):
        return valores
    for linea in open(ruta, encoding='utf-8'):
        linea = linea.strip()
        if linea.startswith('#') or '=' not in linea:
            continue
        clave, valor = linea.split('=', 1)
        valores[clave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def main():
    args = sys.argv[1:]
    cols = filas = None
    colores = None
    resto = []
    i = 0
    while i < len(args):
        if args[i] == '--cols' and i + 1 < len(args):
            cols = int(args[i + 1]); i += 2
        elif args[i] == '--rows' and i + 1 < len(args):
            filas = int(args[i + 1]); i += 2
        elif args[i] == '--colores' and i + 1 < len(args):
            colores = args[i + 1].split(); i += 2
        else:
            resto.append(args[i]); i += 1

    if cols is None or filas is None:
        try:
            tam = os.get_terminal_size()
            cols = cols or tam.columns
            filas = filas or tam.lines
        except OSError:
            # Sin terminal (systemd escribe directo a /dev/tty1): asumimos la
            # consola de la Pi, que con el framebuffer de 1920x1080 es 240x67.
            cols = cols or 240
            filas = filas or 67

    conf = leer_config(os.path.dirname(os.path.abspath(__file__)))
    texto = ' '.join(resto) or conf.get('TEXTO', 'CLUB UNIVERSAL')
    if colores is None:
        colores = conf.get('COLORES', '').split()

    print('\033[2J\033[H', end='')          # limpiar pantalla, cursor arriba
    print('\033[?25l', end='')              # esconder el cursor
    print('\n'.join(dibujar(texto, cols, filas, colores)))


if __name__ == '__main__':
    main()
