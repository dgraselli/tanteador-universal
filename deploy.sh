#!/bin/bash
# Copia el tanteador a la Raspberry y reinicia el servicio.
# Se corre desde la notebook, conectada a la red WiFi del tablero (TNT).
#
#   ./deploy.sh              # despliega a chaca@192.168.216.1
#   ./deploy.sh --check      # muestra qué cambiaría, sin tocar nada
#   ./deploy.sh --no-persist # no escribe en la SD (el cambio dura hasta el reboot)
#   ./deploy.sh chaca@otra-ip
#
# La Pi no tiene internet, así que no puede hacer git pull: hay que empujarle
# los archivos desde acá.
#
# La Pi arranca con el sistema de archivos en solo lectura (overlayroot=tmpfs):
# todo lo que se escribe vive en RAM y se pierde al reiniciar. Este script lo
# detecta y escribe también en la SD real, remontándola en escritura un momento.

set -euo pipefail

HOST="chaca@192.168.216.1"
DEST="/home/chaca/tnt"
UNIT="/etc/systemd/system/tanteador.service"
LOWER="/media/root-ro"      # la SD real, cuando el overlay está activo
DRY=""
PERSIST=1

for arg in "$@"; do
    case "$arg" in
        --check|-n) DRY="--dry-run" ;;
        --no-persist) PERSIST=0 ;;
        -*) echo "❌ Opción desconocida: $arg"; exit 1 ;;
        *) HOST="$arg" ;;
    esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

command -v rsync >/dev/null || { echo "❌ Falta rsync"; exit 1; }

echo "📡 Probando conexión con $HOST..."
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" true 2>/dev/null; then
    echo "❌ No llego a $HOST"
    echo "   ¿Estás conectado a la red WiFi 'TNT'?"
    echo "   ¿Tenés la clave pública en la Pi? (ssh-copy-id $HOST)"
    exit 1
fi

# ¿Está el sistema de archivos en solo lectura?
OVERLAY=0
if [ "$(ssh "$HOST" 'findmnt -no FSTYPE /')" = "overlay" ]; then
    OVERLAY=1
    echo "🔒 La Pi está en modo solo lectura (overlay en RAM)."
    if [ "$PERSIST" = "1" ]; then
        echo "   Voy a escribir también en la SD para que el cambio sobreviva al reboot."
    else
        echo "   ⚠️  --no-persist: el cambio se pierde al reiniciar la Pi."
    fi
fi

[ -n "$DRY" ] && echo "🔍 Modo --check: no se escribe nada."

echo "📦 Sincronizando archivos..."
rsync -av $DRY tanteador.py "$HOST:$DEST/"
# --delete solo en sonidos/: si borrás un tema acá, se borra allá.
rsync -av $DRY --delete sonidos/ "$HOST:$DEST/sonidos/"

if [ -n "$DRY" ]; then
    echo "🔍 Nada más que hacer en modo --check."
    exit 0
fi

# El unit file se sincroniza como un archivo más. No alcanza con preguntar si
# existe un servicio llamado 'tanteador': la Pi tenía uno viejo que apuntaba a
# tanteador_pyqt.py (nombre que ya no existe) y el deploy lo reiniciaba feliz.
if ! ssh "$HOST" "sudo cmp -s $UNIT -" < tanteador.service 2>/dev/null; then
    echo "📝 Instalando/actualizando tanteador.service..."
    scp -q tanteador.service "$HOST:/tmp/tanteador.service"
    ssh "$HOST" "sudo mv /tmp/tanteador.service $UNIT && \
                 sudo chown root:root $UNIT && \
                 sudo systemctl daemon-reload && \
                 sudo systemctl enable tanteador"
fi

# Todo lo anterior escribió en la capa de RAM. Ahora, lo mismo sobre la SD.
if [ "$OVERLAY" = "1" ] && [ "$PERSIST" = "1" ]; then
    echo "💾 Escribiendo en la SD (la remonto en escritura un momento)..."
    # El trap la deja en solo lectura pase lo que pase.
    ssh "$HOST" "sudo mount -o remount,rw $LOWER"
    trap 'echo "🔒 Devolviendo la SD a solo lectura..."; ssh "$HOST" "sudo mount -o remount,ro $LOWER" || true' EXIT

    rsync -a --rsync-path="sudo rsync" tanteador.py "$HOST:$LOWER$DEST/"
    rsync -a --rsync-path="sudo rsync" --delete sonidos/ "$HOST:$LOWER$DEST/sonidos/"
    scp -q tanteador.service "$HOST:/tmp/tanteador.service"
    ssh "$HOST" "sudo cp /tmp/tanteador.service $LOWER$UNIT && \
                 sudo chown -R chaca:chaca $LOWER$DEST && \
                 sync"

    ssh "$HOST" "sudo mount -o remount,ro $LOWER"
    trap - EXIT

    # Escribir el unit en la capa de abajo le cambia la fecha al de la vista
    # combinada, y systemd se queja si no le avisamos.
    ssh "$HOST" 'sudo systemctl daemon-reload'

    # Verificación: lo que quedó en la SD tiene que ser byte a byte lo nuestro.
    LOCAL_SUM=$(md5sum tanteador.py | cut -d' ' -f1)
    DISK_SUM=$(ssh "$HOST" "sudo md5sum $LOWER$DEST/tanteador.py | cut -d' ' -f1")
    if [ "$LOCAL_SUM" = "$DISK_SUM" ]; then
        echo "✅ Guardado en la SD: sobrevive al reboot."
    else
        echo "❌ Lo que quedó en la SD no coincide. El cambio se pierde al reiniciar."
        exit 1
    fi
fi

echo "🔄 Reiniciando el tanteador..."
# reset-failed: si el servicio viejo agotó sus reintentos, systemd lo deja en
# 'failed' y un restart a secas no lo levanta.
ssh "$HOST" 'sudo systemctl reset-failed tanteador 2>/dev/null; sudo systemctl restart tanteador'
sleep 3
if ssh "$HOST" 'systemctl is-active --quiet tanteador'; then
    echo "✅ El tanteador está corriendo."
else
    echo "❌ El servicio no levantó. Mirá el log:"
    ssh "$HOST" 'journalctl -u tanteador -n 30 --no-pager'
    exit 1
fi

echo "🎉 Listo."
