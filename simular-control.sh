#!/bin/bash
# Simula el control remoto (ESP8266) publicando por MQTT desde el teclado.
# Sirve para probar el tanteador en la notebook, sin la Raspberry ni el Wemos.
#
#   Terminal 1:  python3 tanteador.py
#   Terminal 2:  ./simular-control.sh
#
# Por defecto habla con el broker local. Para apuntar a la Pi:
#   ./simular-control.sh 192.168.216.1

set -uo pipefail

BROKER="${1:-localhost}"

command -v mosquitto_pub >/dev/null || { echo "❌ Falta mosquitto-clients"; exit 1; }

if ! mosquitto_pub -h "$BROKER" -t ping -m 1 2>/dev/null; then
    echo "❌ No hay broker MQTT en $BROKER:1883"
    echo "   Local:  sudo systemctl start mosquitto"
    exit 1
fi

cat <<'EOF'
🎮 Control remoto simulado. Teclas:

   q  local suma          a  local resta
   p  visita suma         l  visita resta
   r  reset               t  cambiar tema
   s  ráfaga: 5 puntos seguidos al local (el bug de los jugadores)
   x  salir

EOF
echo "📡 Broker: $BROKER"
echo

pub() { mosquitto_pub -h "$BROKER" -t "$1" -m 1 && echo "   → $1"; }

while true; do
    read -rsn1 -p "> " key
    echo
    case "$key" in
        q) pub team1/up ;;
        a) pub team1/down ;;
        p) pub team2/up ;;
        l) pub team2/down ;;
        r) pub reset ;;
        t) pub theme ;;
        s) echo "   ráfaga de 5..."; for _ in 1 2 3 4 5; do pub team1/up; sleep 0.1; done ;;
        x) echo "👋 Chau."; exit 0 ;;
        *) echo "   (tecla sin uso)" ;;
    esac
done
