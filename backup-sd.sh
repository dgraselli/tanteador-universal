#!/bin/bash
# Baja una imagen completa de la SD de la Raspberry a esta máquina, por ssh.
# No hace falta sacar la SD del tablero: como la Pi corre con la raíz en solo
# lectura (overlay), la SD no cambia durante la copia y la imagen queda
# consistente. Si está montada en escritura (deploy a medias), se niega.
#
#   ./backup-sd.sh              # guarda SDCARD/tnt-sd-AAAAMMDD.img.gz
#   ./backup-sd.sh --check      # muestra tamaño y destino, sin copiar
#   ./backup-sd.sh chaca@otra-ip
#
# Para restaurar en una SD nueva (con lector en esta máquina, ojo con la X):
#   gunzip -c SDCARD/tnt-sd-AAAAMMDD.img.gz | sudo dd of=/dev/sdX bs=4M status=progress

set -euo pipefail

HOST="chaca@192.168.216.1"
DISCO="/dev/mmcblk0"
CHECK=0

for arg in "$@"; do
    case "$arg" in
        --check|-n) CHECK=1 ;;
        -*) echo "❌ Opción desconocida: $arg"; exit 1 ;;
        *) HOST="$arg" ;;
    esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESTDIR="$HERE/SDCARD"
SALIDA="$DESTDIR/tnt-sd-$(date +%Y%m%d).img.gz"

echo "📡 Probando conexión con $HOST..."
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" true 2>/dev/null; then
    echo "❌ No llego a $HOST"
    echo "   ¿Estás conectado a la red WiFi 'TNT'?"
    exit 1
fi

# La imagen solo es consistente si nadie está escribiendo la SD.
if [ "$(ssh "$HOST" 'findmnt -no OPTIONS /media/root-ro | cut -d, -f1')" != "ro" ]; then
    echo "❌ La SD está montada en escritura (¿quedó así de un deploy?)."
    echo "   Reiniciá la Pi (vuelve sola a solo lectura) y corré esto de nuevo."
    exit 1
fi

SIZE=$(ssh "$HOST" "sudo blockdev --getsize64 $DISCO")
LIBRE=$(df --output=avail -B1 "$DESTDIR" | tail -1)
echo "💳 SD: $DISCO, $((SIZE / 1024 / 1024 / 1024)) GB. Destino: $SALIDA"
echo "⏱️  A unos 4 MB/s por el WiFi, tardaría ~$((SIZE / 4194304 / 60)) minutos."

# La imagen comprimida suele ocupar bastante menos, pero mejor pedir de más
# que quedarse sin disco a los 40 minutos de copia.
if [ "$LIBRE" -lt "$SIZE" ]; then
    echo "⚠️  Hay solo $((LIBRE / 1024 / 1024 / 1024)) GB libres acá; si la SD"
    echo "   comprime mal podría no alcanzar."
fi

if [ "$CHECK" = 1 ]; then
    echo "🔍 Modo --check: no se copia nada."
    exit 0
fi

if [ -e "$SALIDA" ]; then
    echo "❌ Ya existe $SALIDA (¿segundo backup del día?). Renombralo o borralo."
    exit 1
fi

# Si algo corta a mitad de camino, no dejar una imagen a medias que después
# alguien confunda con un backup sano.
OK=0
trap '[ "$OK" = 1 ] || { rm -f "$SALIDA"; echo "🗑️  Copia incompleta descartada."; }' EXIT

echo "📥 Copiando (el progreso es del lado de la Pi, en bytes crudos)..."
# gzip -1 en la Pi: comprime poco pero rápido, y por el WiFi viajan menos bytes.
ssh "$HOST" "bash -o pipefail -c 'sudo dd if=$DISCO bs=4M status=progress | gzip -1'" > "$SALIDA"

echo "🔎 Verificando integridad del comprimido..."
gunzip -t "$SALIDA"

OK=1
echo "✅ Backup listo: $SALIDA ($(du -h "$SALIDA" | cut -f1))"
echo "   Restaurar: gunzip -c $SALIDA | sudo dd of=/dev/sdX bs=4M status=progress"
