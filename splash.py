#!/usr/bin/env python3
"""Cartel de arranque del tanteador.

Dibuja un texto en letras grandes de bloque macizo, centrado y con color. Lo usa
splash.service para tapar el log del kernel mientras la Pi arranca.

El texto y los colores salen de splash.conf:

    ./splash.py                        # lee splash.conf
    ./splash.py "CLUB UNIVERSAL"       # texto suelto, para probar
    ./splash.py --colores "rojo verde" "CLUB UNIVERSAL"
    ./splash.py --cols 80 --rows 24 "HOLA"   # simula otra pantalla

La fuente (GLIFOS) se generó una vez con figlet (fuente "ANSI Regular") en la
notebook y quedó escrita acá: la Pi no tiene internet y no se le puede instalar
figlet. Cada letra es un bitmap de puntos ('#'/'.'); dos filas de puntos entran
en una fila de consola usando medios bloques (▀ ▄ █), lo que duplica la
resolución vertical y deja escalar el dibujo sin que se rompa.
"""

import os
import sys

ALTO_PX = 12
GLIFOS = {
    'A': [
        '.#####..',
        '.#####..',
        '##...##.',
        '##...##.',
        '#######.',
        '#######.',
        '##...##.',
        '##...##.',
        '##...##.',
        '##...##.',
        '........',
        '........',
    ],
    'B': [
        '######..',
        '######..',
        '##...##.',
        '##...##.',
        '######..',
        '######..',
        '##...##.',
        '##...##.',
        '######..',
        '######..',
        '........',
        '........',
    ],
    'C': [
        '.######.',
        '.######.',
        '##......',
        '##......',
        '##......',
        '##......',
        '##......',
        '##......',
        '.######.',
        '.######.',
        '........',
        '........',
    ],
    'D': [
        '######..',
        '######..',
        '##...##.',
        '##...##.',
        '##...##.',
        '##...##.',
        '##...##.',
        '##...##.',
        '######..',
        '######..',
        '........',
        '........',
    ],
    'E': [
        '#######.',
        '#######.',
        '##......',
        '##......',
        '#####...',
        '#####...',
        '##......',
        '##......',
        '#######.',
        '#######.',
        '........',
        '........',
    ],
    'F': [
        '#######.',
        '#######.',
        '##......',
        '##......',
        '#####...',
        '#####...',
        '##......',
        '##......',
        '##......',
        '##......',
        '........',
        '........',
    ],
    'G': [
        '.######..',
        '.######..',
        '##.......',
        '##.......',
        '##...###.',
        '##...###.',
        '##....##.',
        '##....##.',
        '.######..',
        '.######..',
        '.........',
        '.........',
    ],
    'H': [
        '##...##.',
        '##...##.',
        '##...##.',
        '##...##.',
        '#######.',
        '#######.',
        '##...##.',
        '##...##.',
        '##...##.',
        '##...##.',
        '........',
        '........',
    ],
    'I': [
        '##.',
        '##.',
        '##.',
        '##.',
        '##.',
        '##.',
        '##.',
        '##.',
        '##.',
        '##.',
        '...',
        '...',
    ],
    'J': [
        '.....##.',
        '.....##.',
        '.....##.',
        '.....##.',
        '.....##.',
        '.....##.',
        '##...##.',
        '##...##.',
        '.#####..',
        '.#####..',
        '........',
        '........',
    ],
    'K': [
        '##...##.',
        '##...##.',
        '##..##..',
        '##..##..',
        '#####...',
        '#####...',
        '##..##..',
        '##..##..',
        '##...##.',
        '##...##.',
        '........',
        '........',
    ],
    'L': [
        '##......',
        '##......',
        '##......',
        '##......',
        '##......',
        '##......',
        '##......',
        '##......',
        '#######.',
        '#######.',
        '........',
        '........',
    ],
    'M': [
        '###....###.',
        '###....###.',
        '####..####.',
        '####..####.',
        '##.####.##.',
        '##.####.##.',
        '##..##..##.',
        '##..##..##.',
        '##......##.',
        '##......##.',
        '...........',
        '...........',
    ],
    'N': [
        '###....##.',
        '###....##.',
        '####...##.',
        '####...##.',
        '##.##..##.',
        '##.##..##.',
        '##..##.##.',
        '##..##.##.',
        '##...####.',
        '##...####.',
        '..........',
        '..........',
    ],
    'O': [
        '.######..',
        '.######..',
        '##....##.',
        '##....##.',
        '##....##.',
        '##....##.',
        '##....##.',
        '##....##.',
        '.######..',
        '.######..',
        '.........',
        '.........',
    ],
    'P': [
        '######..',
        '######..',
        '##...##.',
        '##...##.',
        '######..',
        '######..',
        '##......',
        '##......',
        '##......',
        '##......',
        '........',
        '........',
    ],
    'Q': [
        '.######..',
        '.######..',
        '##....##.',
        '##....##.',
        '##....##.',
        '##....##.',
        '##....##.',
        '##.##.##.',
        '.######..',
        '.######..',
        '....##...',
        '.........',
    ],
    'R': [
        '######..',
        '######..',
        '##...##.',
        '##...##.',
        '######..',
        '######..',
        '##...##.',
        '##...##.',
        '##...##.',
        '##...##.',
        '........',
        '........',
    ],
    'S': [
        '#######.',
        '#######.',
        '##......',
        '##......',
        '#######.',
        '#######.',
        '.....##.',
        '.....##.',
        '#######.',
        '#######.',
        '........',
        '........',
    ],
    'T': [
        '########.',
        '########.',
        '...##....',
        '...##....',
        '...##....',
        '...##....',
        '...##....',
        '...##....',
        '...##....',
        '...##....',
        '.........',
        '.........',
    ],
    'U': [
        '##....##.',
        '##....##.',
        '##....##.',
        '##....##.',
        '##....##.',
        '##....##.',
        '##....##.',
        '##....##.',
        '.######..',
        '.######..',
        '.........',
        '.........',
    ],
    'V': [
        '##....##.',
        '##....##.',
        '##....##.',
        '##....##.',
        '##....##.',
        '##....##.',
        '.##..##..',
        '.##..##..',
        '..####...',
        '..####...',
        '.........',
        '.........',
    ],
    'W': [
        '##.....##.',
        '##.....##.',
        '##.....##.',
        '##.....##.',
        '##..#..##.',
        '##..#..##.',
        '##.###.##.',
        '##.###.##.',
        '.###.###..',
        '.###.###..',
        '..........',
        '..........',
    ],
    'X': [
        '##...##.',
        '##...##.',
        '.##.##..',
        '.##.##..',
        '..###...',
        '..###...',
        '.##.##..',
        '.##.##..',
        '##...##.',
        '##...##.',
        '........',
        '........',
    ],
    'Y': [
        '##....##.',
        '##....##.',
        '.##..##..',
        '.##..##..',
        '..####...',
        '..####...',
        '...##....',
        '...##....',
        '...##....',
        '...##....',
        '.........',
        '.........',
    ],
    'Z': [
        '#######.',
        '#######.',
        '...###..',
        '...###..',
        '..###...',
        '..###...',
        '.###....',
        '.###....',
        '#######.',
        '#######.',
        '........',
        '........',
    ],
    '0': [
        '.######..',
        '.######..',
        '##..####.',
        '##..####.',
        '##.##.##.',
        '##.##.##.',
        '####..##.',
        '####..##.',
        '.######..',
        '.######..',
        '.........',
        '.........',
    ],
    '1': [
        '.##.',
        '.##.',
        '###.',
        '###.',
        '.##.',
        '.##.',
        '.##.',
        '.##.',
        '.##.',
        '.##.',
        '....',
        '....',
    ],
    '2': [
        '######..',
        '######..',
        '.....##.',
        '.....##.',
        '.#####..',
        '.#####..',
        '##......',
        '##......',
        '#######.',
        '#######.',
        '........',
        '........',
    ],
    '3': [
        '######..',
        '######..',
        '.....##.',
        '.....##.',
        '.#####..',
        '.#####..',
        '.....##.',
        '.....##.',
        '######..',
        '######..',
        '........',
        '........',
    ],
    '4': [
        '##...##.',
        '##...##.',
        '##...##.',
        '##...##.',
        '#######.',
        '#######.',
        '.....##.',
        '.....##.',
        '.....##.',
        '.....##.',
        '........',
        '........',
    ],
    '5': [
        '#######.',
        '#######.',
        '##......',
        '##......',
        '#######.',
        '#######.',
        '.....##.',
        '.....##.',
        '#######.',
        '#######.',
        '........',
        '........',
    ],
    '6': [
        '.######..',
        '.######..',
        '##.......',
        '##.......',
        '#######..',
        '#######..',
        '##....##.',
        '##....##.',
        '.######..',
        '.######..',
        '.........',
        '.........',
    ],
    '7': [
        '#######.',
        '#######.',
        '.....##.',
        '.....##.',
        '....##..',
        '....##..',
        '...##...',
        '...##...',
        '...##...',
        '...##...',
        '........',
        '........',
    ],
    '8': [
        '.#####..',
        '.#####..',
        '##...##.',
        '##...##.',
        '.#####..',
        '.#####..',
        '##...##.',
        '##...##.',
        '.#####..',
        '.#####..',
        '........',
        '........',
    ],
    '9': [
        '.#####..',
        '.#####..',
        '##...##.',
        '##...##.',
        '.######.',
        '.######.',
        '.....##.',
        '.....##.',
        '.#####..',
        '.#####..',
        '........',
        '........',
    ],
    '-': [
        '......',
        '......',
        '......',
        '......',
        '#####.',
        '#####.',
        '......',
        '......',
        '......',
        '......',
        '......',
        '......',
    ],
    '.': [
        '...',
        '...',
        '...',
        '...',
        '...',
        '...',
        '...',
        '...',
        '##.',
        '##.',
        '...',
        '...',
    ],
    "'": [
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
    ],
    '!': [
        '##.',
        '##.',
        '##.',
        '##.',
        '##.',
        '##.',
        '...',
        '...',
        '##.',
        '##.',
        '...',
        '...',
    ],
    ' ': [
        '....',
        '....',
        '....',
        '....',
        '....',
        '....',
        '....',
        '....',
        '....',
        '....',
        '....',
        '....',
    ],
}

# Cuánto del ancho de la pantalla tratar de llenar con la palabra más larga.
OCUPACION = 0.90
HUECO_RENGLONES = 3      # filas en blanco entre una palabra y la siguiente

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


def bitmap_palabra(texto):
    """Las ALTO_PX filas de puntos de una palabra, pegando letra con letra."""
    filas = [''] * ALTO_PX
    for c in texto.upper():
        g = GLIFOS.get(c, GLIFOS[' '])
        for i in range(ALTO_PX):
            filas[i] += g[i]
    return filas


def escalar(bitmap, n):
    """Agranda el bitmap n veces a lo ancho y a lo alto."""
    salida = []
    for fila in bitmap:
        ancha = ''.join(ch * n for ch in fila)
        salida += [ancha] * n
    return salida


def a_consola(bitmap):
    """Convierte el bitmap a filas de texto usando medios bloques.

    Dos filas de puntos entran en una sola fila de consola: el de arriba y el de
    abajo deciden si va bloque entero, medio de arriba, medio de abajo o nada.
    """
    lineas = []
    for i in range(0, len(bitmap), 2):
        arriba = bitmap[i]
        abajo = bitmap[i + 1] if i + 1 < len(bitmap) else '.' * len(arriba)
        linea = ''
        for a, b in zip(arriba, abajo):
            a, b = a == '#', b == '#'
            linea += '█' if a and b else '▀' if a else '▄' if b else ' '
        lineas.append(linea.rstrip())
    return lineas


def elegir_escala(palabras, cols, filas):
    """La escala entera más grande que entre a lo ancho y a lo alto."""
    ancho_px = max(len(bitmap_palabra(p)[0]) for p in palabras)
    # alto en filas de consola: ALTO_PX/2 por palabra, más los huecos
    alto_base = len(palabras) * (ALTO_PX // 2) + (len(palabras) - 1) * HUECO_RENGLONES
    for n in range(8, 0, -1):
        if ancho_px * n <= cols * OCUPACION and alto_base * n <= filas - 2:
            return n
    return 1


def dibujar(texto, cols, filas, colores=None):
    palabras = texto.split()
    if not palabras:
        return []
    colores = colores or []
    n = elegir_escala(palabras, cols, filas)

    salida = []
    for i, palabra in enumerate(palabras):
        if i:
            salida += [''] * HUECO_RENGLONES
        lineas = a_consola(escalar(bitmap_palabra(palabra), n))
        ancho = max((len(l) for l in lineas), default=0)
        sangria = ' ' * max(0, (cols - ancho) // 2)
        color = colores[i] if i < len(colores) else (colores[-1] if colores else None)
        cod = COLORES.get(color, '')
        for l in lineas:
            l = sangria + l
            salida.append(f"{cod}{l}{RESET}" if cod else l)

    arriba = max(0, (filas - len(salida)) // 2)      # centrado vertical
    return [''] * arriba + salida


def leer_config(base):
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
            # Sin terminal (systemd escribe directo a /dev/tty1): la consola de
            # la Pi, con el framebuffer de 1920x1080, es de 240x67.
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
