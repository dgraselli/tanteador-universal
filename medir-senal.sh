#!/bin/bash
# Mide la señal WiFi del control remoto a lo largo de la cancha.
#
# El control publica su RSSI cada 5 segundos. Los botones también publican, así
# que sirven de marcador: cada vez que apretás el botón del local, el script
# empieza a contar un tramo nuevo.
#
# Cómo se usa:
#   1. Dejá la notebook al lado del tablero y corré:  ./medir-senal.sh 180
#      (180 = segundos de medición; sin argumento son 120)
#   2. Agarrá el control y andá al primer punto de medición.
#   3. Apretá una vez el botón del LOCAL (toque corto) y quedate quieto ~20 s.
#   4. Repetí en cada punto que quieras medir.
#   5. Cuando se cumple el tiempo, termina solo y muestra el resumen por tramo.
#      (Ctrl-C también corta y muestra el resumen.)
#
# El marcador suma puntos en el tablero. Al terminar, mantené apretado RESET.
#
# La medición termina por tiempo y no por Ctrl-C a propósito: así el resumen sale
# siempre, sin depender de cómo bash reparte las señales entre los procesos de la
# tubería. El ssh va DENTRO de la tubería (no con &) porque a los procesos en
# segundo plano de un script no interactivo bash les pone SIGINT en "ignorar", y
# entonces un Ctrl-C los dejaría colgados.

set -uo pipefail

SEGUNDOS=120
HOST="chaca@192.168.216.1"
for arg in "$@"; do
    case "$arg" in
        ''|*[!0-9]*) HOST="$arg" ;;   # tiene letras: es el host
        *)           SEGUNDOS="$arg" ;;
    esac
done

command -v ssh >/dev/null || { echo "❌ Falta ssh"; exit 1; }

if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" true 2>/dev/null; then
    echo "❌ No llego a $HOST. ¿Estás conectado a la red WiFi 'TNT'?"
    exit 1
fi

LECTOR=$(cat <<'PY'
import sys

UMBRALES = [(-60, "excelente"), (-70, "bien"),
            (-80, "MARGINAL — se corta a ratos"), (-999, "SIN ENLACE ÚTIL")]

def calidad(dbm):
    for limite, texto in UMBRALES:
        if dbm >= limite:
            return texto

tramos = []

def resumen():
    print()
    print("═" * 64)
    if not any(tramos):
        print("No hay muestras. ¿Apretaste el botón del LOCAL en cada punto?")
        print("═" * 64)
        return
    print(f"{'Punto':<7}{'muestras':>9}{'peor':>7}{'mejor':>7}{'media':>7}   calidad (según el peor)")
    print("─" * 64)
    for i, t in enumerate(tramos, 1):
        if not t:
            print(f"{i:<7}{0:>9}{'—':>7}{'—':>7}{'—':>7}   (sin muestras: esperá más)")
            continue
        peor, mejor, media = min(t), max(t), sum(t) / len(t)
        print(f"{i:<7}{len(t):>9}{peor:>7}{mejor:>7}{media:>7.0f}   {calidad(peor)}")
    print()
    todas = [d for t in tramos for d in t]
    peor = min(todas)
    print(f"Peor valor de toda la recorrida: {peor} dBm → {calidad(peor)}")
    if peor >= -70:
        print("La señal NO es el problema: hay margen en toda la cancha.")
    elif peor >= -80:
        print("Justo. Conviene mover la Pi, o pasar a un Wemos D1 Mini Pro")
        print("(tiene conector para antena externa).")
    else:
        print("Acá sí hay un problema de señal, y explica los cortes.")
    print("═" * 64)

try:
    for linea in sys.stdin:
        partes = linea.split()
        if len(partes) < 3:
            continue
        _, topico, valor = partes[0], partes[1], partes[2]
        if topico == 'team1/up':
            tramos.append([])
            print(f"\n┌── 📍 punto {len(tramos)}", flush=True)
        elif topico == 'rssi':
            try:
                dbm = int(valor)
            except ValueError:
                continue
            if not tramos:      # todavía no marcó ningún punto
                print(f"│   {dbm} dBm  ({calidad(dbm)})   ← apretá LOCAL para marcar el punto 1",
                      flush=True)
                continue
            tramos[-1].append(dbm)
            print(f"│   {dbm} dBm  ({calidad(dbm)})", flush=True)
except KeyboardInterrupt:
    pass
resumen()
PY
)

echo "📡 Midiendo la señal del control remoto durante $SEGUNDOS segundos..."
echo
echo "   Andá al primer punto, apretá una vez el botón del LOCAL,"
echo "   y quedate quieto unos 20 segundos. Repetí en cada punto."
echo

# timeout mata el ssh cuando se cumple el tiempo; python ve el fin de la entrada
# y saca el resumen.
timeout "$SEGUNDOS" ssh "$HOST" "mosquitto_sub -v -t 'rssi' -t 'team1/up' -F '%I %t %p'" \
    | python3 -c "$LECTOR"
