#!/bin/bash
# Fija la resolución del monitor del tablero, sin depender del EDID. Se corre
# UNA VEZ, desde la notebook conectada a la red WiFi del tablero (TNT).
#
#   ./setup-pantalla.sh             # 1280x720 a 60 Hz
#   ./setup-pantalla.sh 1600x900    # otra resolución (1024x768, 1600x900, 1920x1080)
#   ./setup-pantalla.sh --revertir  # vuelve a que el monitor elija solo
#
# Por qué: con el cable/adaptador HDMI marginal, el EDID (lo que el monitor le
# cuenta a la Pi sobre sí mismo) llega corrupto o no llega, y la resolución
# cambiaba en cada arranque. 1280x720 además pide la mitad de ancho de banda
# que 1920x1080 (74 contra 148 MHz de reloj de píxel): más margen para un
# cable flojo. El Samsung SMB2030N (1600x900) lo agranda ×1,25, sin deformar.
#
# Toca dos cosas:
#
#   * /boot/firmware/cmdline.txt — agrega video=HDMI-A-1:<modo>@60D. El kernel
#     arranca en ese modo, y la D deja la salida prendida aunque no detecte el
#     monitor (el "HDMI disconnected" tras algunos reinicios). Si este archivo
#     queda mal la Pi NO ARRANCA: se valida antes de escribir y queda una copia
#     en cmdline.txt.antes-de-pantalla.
#
#   * ~/.xinitrc — la versión del repo, que lee el modo de /proc/cmdline y se
#     lo impone a X (si no, X vuelve a elegir según el EDID). Sin video= en
#     cmdline no hace nada, así que revertir es solo restaurar cmdline.txt.
#
# Es idempotente: correrlo de nuevo con otro modo reemplaza el anterior.
#
# Después: ssh chaca@192.168.216.1 'sudo reboot', y en /historial o en la
# bitácora el evento "pantalla" tiene que decir siempre el modo elegido.

set -euo pipefail

HOST="chaca@192.168.216.1"
MODO="1280x720"
REVERTIR=0
LOWER="/media/root-ro"   # la SD real, debajo del overlay

for arg in "$@"; do
    case "$arg" in
        --revertir) REVERTIR=1 ;;
        1280x720|1600x900|1920x1080|1024x768) MODO="$arg" ;;
        [0-9]*x[0-9]*) echo "❌ Modo no soportado: $arg (1280x720, 1600x900, 1920x1080 o 1024x768)"; exit 1 ;;
        -*) echo "❌ Opción desconocida: $arg"; exit 1 ;;
        *) HOST="$arg" ;;
    esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

echo "📡 Probando conexión con $HOST..."
ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" true 2>/dev/null || {
    echo "❌ No llego a $HOST. ¿Estás en la red WiFi 'TNT'?"; exit 1; }

if [ "$REVERTIR" = "1" ]; then
    echo "↩️  Revirtiendo: el monitor vuelve a elegir la resolución..."
    ssh "$HOST" "bash -s" <<'REMOTO'
set -e
CMDLINE=/boot/firmware/cmdline.txt
sudo mount -o remount,rw /boot/firmware
NUEVA=$(sed -E 's/ ?video=HDMI-A-1:[^ ]*//g' "$CMDLINE")
case "$NUEVA" in
    *root=*rootfstype=*) ;;
    *) echo "❌ La línea nueva perdió root= o rootfstype=. No la escribo."; sudo mount -o remount,ro /boot/firmware; exit 1 ;;
esac
printf '%s\n' "$NUEVA" | sudo tee "$CMDLINE" > /dev/null
sudo sync
sudo mount -o remount,ro /boot/firmware
echo "   ✅ cmdline.txt sin video= (la copia original sigue en cmdline.txt.antes-de-pantalla)"
REMOTO
    echo "✅ Revertido. Reiniciá la Pi:  ssh $HOST 'sudo reboot'"
    echo "   (el .xinitrc nuevo queda, pero sin video= en cmdline.txt no hace nada)"
    exit 0
fi

echo "🖥️  Fijando la pantalla en $MODO a 60 Hz..."

# ── 1. cmdline.txt ──────────────────────────────────────────────────────────
ssh "$HOST" "bash -s" <<REMOTO
set -e
CMDLINE=/boot/firmware/cmdline.txt
sudo mount -o remount,rw /boot/firmware

# La copia se hace una sola vez: es la del estado anterior a este script.
if [ ! -f "\$CMDLINE.antes-de-pantalla" ]; then
    sudo cp "\$CMDLINE" "\$CMDLINE.antes-de-pantalla"
    echo "   💾 copia de seguridad: \$CMDLINE.antes-de-pantalla"
fi

# Saca un video= anterior y agrega el nuevo.
NUEVA="\$(sed -E 's/ ?video=HDMI-A-1:[^ ]*//g' "\$CMDLINE") video=HDMI-A-1:$MODO@60D"

# cmdline.txt tiene que ser UNA sola línea y conservar el root, o la Pi no
# arranca. Se valida antes de escribir.
case "\$NUEVA" in
    *root=*rootfstype=*) ;;
    *) echo "❌ La línea nueva perdió root= o rootfstype=. No la escribo."; sudo mount -o remount,ro /boot/firmware; exit 1 ;;
esac
if [ "\$(printf '%s' "\$NUEVA" | wc -l)" != "0" ]; then
    echo "❌ La línea nueva tiene saltos de línea. No la escribo."; sudo mount -o remount,ro /boot/firmware; exit 1
fi

printf '%s\n' "\$NUEVA" | sudo tee "\$CMDLINE" > /dev/null
sudo sync
sudo mount -o remount,ro /boot/firmware
echo "   ✅ cmdline.txt: video=HDMI-A-1:$MODO@60D"
REMOTO

# ── 2. .xinitrc (en la RAM y, si hay overlay, también en la SD) ─────────────
scp -q .xinitrc "$HOST:/home/chaca/.xinitrc"
echo "   ✅ .xinitrc copiado"
if [ "$(ssh "$HOST" 'findmnt -no FSTYPE /')" = "overlay" ]; then
    # En esta Pi el remount a veces dice "mount point is busy" aunque se
    # aplica: lo que manda es lo que diga findmnt (igual que en deploy.sh).
    ssh "$HOST" "sudo mount -o remount,rw $LOWER" 2>/dev/null || true
    if [ "$(ssh "$HOST" "findmnt -no OPTIONS $LOWER" | cut -d, -f1)" != "rw" ]; then
        echo "❌ No pude poner la SD en escritura: el .xinitrc nuevo dura hasta el reboot."
        echo "   cmdline.txt sí quedó. Reiniciá la Pi y volvé a correr este script."
        exit 1
    fi
    ssh "$HOST" "
        set -e
        [ -f $LOWER/home/chaca/.xinitrc.antes-de-pantalla ] || \
            sudo cp $LOWER/home/chaca/.xinitrc $LOWER/home/chaca/.xinitrc.antes-de-pantalla
        sudo cp /home/chaca/.xinitrc $LOWER/home/chaca/.xinitrc
        sudo chown chaca:chaca $LOWER/home/chaca/.xinitrc
        sudo sync
    "
    echo "   ✅ .xinitrc guardado en la SD (copia: .xinitrc.antes-de-pantalla)"
    ssh "$HOST" "sudo mount -o remount,ro $LOWER" 2>/dev/null || true
    if [ "$(ssh "$HOST" "findmnt -no OPTIONS $LOWER" | cut -d, -f1)" != "ro" ]; then
        echo "⚠️  La SD quedó en escritura (el remount a solo lectura falló, pasa en"
        echo "   esta Pi). El reboot que sigue la devuelve a solo lectura."
    fi
fi

echo
echo "✅ Listo. Reiniciá la Pi para aplicarlo:  ssh $HOST 'sudo reboot'"
echo "   Comprobá: ssh $HOST 'DISPLAY=:0 XAUTHORITY=/home/chaca/.Xauthority xrandr | grep \"*\"'"
echo "   Si el monitor queda en negro:  ./setup-pantalla.sh --revertir  y reiniciá."
