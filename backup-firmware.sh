#!/bin/bash
# Vuelca la flash completa del ESP8266 antes de flashear firmware nuevo.
# El binario resultante es lo unico que permite volver exactamente al estado
# anterior: el .ino del repo tiene la password WiFi borrada y no lo reconstruye.
#
#   ./backup-firmware.sh [puerto] [directorio-destino]
#
# Para restaurar:
#   esptool.py --port /dev/ttyUSB0 write_flash 0 <archivo.bin>

set -euo pipefail

PORT="${1:-}"
DEST="${2:-$HOME}"

command -v esptool.py >/dev/null || { echo "❌ Falta esptool.py (pip3 install esptool)"; exit 1; }

# 🔌 Buscar la placa si no la pasaron por parametro
if [ -z "$PORT" ]; then
    mapfile -t PORTS < <(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null)
    case ${#PORTS[@]} in
        0) echo "❌ No hay ninguna placa conectada. Enchufa el D1 Mini por USB."; exit 1 ;;
        1) PORT="${PORTS[0]}" ;;
        *) echo "❌ Hay varias placas: ${PORTS[*]}"
           echo "   Elegi una: $0 ${PORTS[0]}"; exit 1 ;;
    esac
fi
echo "🔌 Usando $PORT"

[ -r "$PORT" ] && [ -w "$PORT" ] || {
    echo "❌ Sin permisos sobre $PORT. Agregate al grupo dialout y volve a entrar:"
    echo "   sudo usermod -aG dialout $USER"
    exit 1
}

# 📏 Preguntarle al chip cuanta flash tiene, en vez de asumir 4MB
echo "📏 Consultando el chip..."
FLASH_MB=$(esptool.py --port "$PORT" flash_id 2>/dev/null \
           | sed -n 's/^Detected flash size: \([0-9]\+\)MB$/\1/p')
[ -n "$FLASH_MB" ] || { echo "❌ No pude detectar el tamaño de flash. ¿Está en modo boot?"; exit 1; }

SIZE=$((FLASH_MB * 1024 * 1024))
printf "📏 Flash detectada: %sMB (%d bytes)\n" "$FLASH_MB" "$SIZE"

OUT="$DEST/firmware_tnt_backup_$(date +%F_%H%M%S).bin"

# 💾 Los clones con CH340 no siempre bancan 460800; caemos a 115200 si falla.
for BAUD in 460800 115200; do
    echo "💾 Volcando a $OUT (baud $BAUD)..."
    if esptool.py --port "$PORT" --baud "$BAUD" \
           read_flash 0 "$SIZE" "$OUT"; then
        break
    fi
    echo "⚠️  Falló a $BAUD."
    rm -f "$OUT"
    [ "$BAUD" = 115200 ] && { echo "❌ No se pudo leer la flash."; exit 1; }
done

ACTUAL=$(stat -c %s "$OUT")
[ "$ACTUAL" -eq "$SIZE" ] || { echo "❌ Volcado incompleto: $ACTUAL de $SIZE bytes."; rm -f "$OUT"; exit 1; }

# ✅ Releer el chip y compararlo contra el archivo, por las dudas
echo "✅ Verificando contra el chip..."
esptool.py --port "$PORT" --baud "$BAUD" verify_flash 0 "$OUT" >/dev/null

chmod 600 "$OUT"
echo ""
echo "🎉 Backup listo: $OUT"
echo "   sha256: $(sha256sum "$OUT" | cut -d' ' -f1)"
echo ""
echo "🔒 Ese archivo tiene la password del WiFi en texto plano (strings lo muestra)."
echo "   No lo subas al repo. Copialo a otra maquina: si se corrompe la SD, lo perdes."
echo ""
echo "↩️  Para restaurar:"
echo "   esptool.py --port $PORT write_flash 0 $OUT"
