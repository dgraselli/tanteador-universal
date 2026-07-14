#!/bin/bash
# Configura el cartel de arranque en la Raspberry: apaga el log del kernel y
# deja el texto grande en su lugar. Se corre UNA VEZ, desde la notebook.
#
#   ./setup-splash.sh            # aplica los cambios
#   ./setup-splash.sh --revertir # vuelve todo como estaba
#
# El texto en sí se cambia en splash.conf y se manda con ./deploy.sh: para eso
# no hace falta volver a correr este script.
#
# Toca dos cosas delicadas:
#
#   * /boot/firmware/cmdline.txt — los parámetros del kernel. Vive en la partición
#     FAT de arranque, que está montada de solo lectura (no es el overlay: es
#     otra partición). Si este archivo queda mal, la Pi NO ARRANCA, así que
#     dejamos una copia al lado y validamos antes de escribir.
#
#   * ~/.bashrc — repinta el cartel justo antes de lanzar X. Sin esto, el prompt
#     del login te escribe encima del cartel.
#
# Es idempotente: correlo dos veces y no duplica nada.

set -euo pipefail

HOST="chaca@192.168.216.1"
REVERTIR=0

for arg in "$@"; do
    case "$arg" in
        --revertir) REVERTIR=1 ;;
        -*) echo "❌ Opción desconocida: $arg"; exit 1 ;;
        *) HOST="$arg" ;;
    esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

echo "📡 Probando conexión con $HOST..."
ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" true 2>/dev/null || {
    echo "❌ No llego a $HOST. ¿Estás en la red WiFi 'TNT'?"; exit 1; }

# Parámetros que silencian el arranque:
#   quiet, loglevel=3       → el kernel deja de escupir mensajes
#   logo.nologo             → saca las frambuesas de la esquina
#   vt.global_cursor_default=0 → esconde el cursor titilante
#   systemd.show_status=0   → systemd deja de listar cada servicio
PARAMS="quiet loglevel=3 logo.nologo vt.global_cursor_default=0 systemd.show_status=0"

if [ "$REVERTIR" = "1" ]; then
    echo "↩️  Revirtiendo..."
    ssh "$HOST" "
        set -e
        sudo mount -o remount,rw /boot/firmware
        if [ -f /boot/firmware/cmdline.txt.antes-del-splash ]; then
            sudo cp /boot/firmware/cmdline.txt.antes-del-splash /boot/firmware/cmdline.txt
            echo '   cmdline.txt restaurado'
        fi
        sudo sync; sudo mount -o remount,ro /boot/firmware

        sudo mount -o remount,rw /media/root-ro
        for RAIZ in '' /media/root-ro; do
            sudo sed -i '/splash.py.*# cartel de arranque/d' \$RAIZ/home/chaca/.bashrc 2>/dev/null || true
        done
        sudo systemctl disable --now splash.service 2>/dev/null || true
        sudo rm -f /etc/systemd/system/splash.service /media/root-ro/etc/systemd/system/splash.service
        sudo sync; sudo mount -o remount,ro /media/root-ro
        sudo systemctl daemon-reload
        echo '   servicio y .bashrc limpios'
    "
    echo "✅ Revertido. Reiniciá la Pi para ver el arranque de siempre."
    exit 0
fi

echo "🔧 Configurando el cartel de arranque..."
ssh "$HOST" "bash -s" <<REMOTO
set -e

CMDLINE=/boot/firmware/cmdline.txt

# ── 1. Parámetros del kernel ────────────────────────────────────────────────
sudo mount -o remount,rw /boot/firmware

# La copia de seguridad se hace una sola vez: si ya existe, es del estado
# original y no hay que pisarla con uno ya modificado.
if [ ! -f "\$CMDLINE.antes-del-splash" ]; then
    sudo cp "\$CMDLINE" "\$CMDLINE.antes-del-splash"
    echo "   💾 copia de seguridad: \$CMDLINE.antes-del-splash"
fi

NUEVA=\$(cat "\$CMDLINE")
for p in $PARAMS; do
    case " \$NUEVA " in
        *" \$p "*) ;;                        # ya está
        *) NUEVA="\$NUEVA \$p" ;;
    esac
done

# cmdline.txt tiene que ser UNA sola línea y conservar el root, o la Pi no
# arranca. Validamos antes de escribir.
case "\$NUEVA" in
    *root=*rootfstype=*) ;;
    *) echo "❌ La línea nueva perdió root= o rootfstype=. No la escribo."; exit 1 ;;
esac
if [ "\$(printf '%s' "\$NUEVA" | wc -l)" != "0" ]; then
    echo "❌ La línea nueva tiene saltos de línea. No la escribo."; exit 1
fi

printf '%s\n' "\$NUEVA" | sudo tee "\$CMDLINE" > /dev/null
sudo sync
sudo mount -o remount,ro /boot/firmware
echo "   ✅ cmdline.txt actualizado"

# ── 2. Servicio y .bashrc (van en la raíz, que está bajo el overlay) ────────
sudo mount -o remount,rw /media/root-ro

for RAIZ in "" /media/root-ro; do
    BASHRC="\$RAIZ/home/chaca/.bashrc"
    [ -f "\$BASHRC" ] || continue
    # El cartel se repinta justo antes de startx, si no el prompt lo tapa.
    if ! grep -q "splash.py.*# cartel de arranque" "\$BASHRC"; then
        sudo sed -i 's|^\( *\)startx|\1python3 /home/chaca/tnt/splash.py  # cartel de arranque\n\1startx|' "\$BASHRC"
        echo "   ✅ \$BASHRC: repinta el cartel antes de startx"
    fi
done

sudo touch /home/chaca/.hushlogin /media/root-ro/home/chaca/.hushlogin   # sin mensaje de bienvenida
sudo chown chaca:chaca /home/chaca/.hushlogin /media/root-ro/home/chaca/.hushlogin

sudo sync
sudo mount -o remount,ro /media/root-ro
REMOTO

echo
echo "✅ Listo. Ahora mandá los archivos con:  ./deploy.sh"
echo "   y reiniciá la Pi:  ssh $HOST 'sudo reboot'"
echo
echo "Si algo sale mal:  ./setup-splash.sh --revertir"
