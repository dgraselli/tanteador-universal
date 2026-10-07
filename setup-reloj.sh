#!/bin/bash
# Activa el módulo de reloj DS3231 (con pila) para que la Pi sepa la hora
# aunque nadie se conecte. Se corre UNA VEZ, desde la notebook conectada a la
# red WiFi del tablero (TNT), con el módulo ya cableado:
#
#   VCC → pin 17 (3,3 V; con 5 V el ZS-042 carga la pila y una CR2032 se hincha)
#   GND → pin 20    SDA → pin 3 (GPIO2)    SCL → pin 5 (GPIO3)
#
#   ./setup-reloj.sh             # aplica los cambios
#   ./setup-reloj.sh --revertir  # vuelve todo como estaba
#
# Toca dos cosas:
#
#   * /boot/firmware/config.txt — activa el bus I2C (dtparam=i2c_arm=on) y el
#     reloj (dtoverlay=i2c-rtc,ds3231). Al arrancar, el kernel copia la hora
#     del módulo al sistema solo. Queda una copia en config.txt.antes-del-reloj.
#
#   * /etc/udev/rules.d/60-tnt-rtc.rules — deja que pruebas.py (usuario
#     chaca, grupo i2c) grabe en /dev/rtc0 la hora que manda el celular.
#
# Después: ssh chaca@192.168.216.1 'sudo reboot'. El módulo nuevo viene en el
# año 2000: hasta que un celular abra una página, pruebas.py no le cree y usa
# la hora de la bitácora, como antes.

set -euo pipefail

HOST="chaca@192.168.216.1"
REVERTIR=0
LOWER="/media/root-ro"   # la SD real, debajo del overlay
REGLA="/etc/udev/rules.d/60-tnt-rtc.rules"

for arg in "$@"; do
    case "$arg" in
        --revertir) REVERTIR=1 ;;
        -*) echo "❌ Opción desconocida: $arg"; exit 1 ;;
        *) HOST="$arg" ;;
    esac
done

echo "📡 Probando conexión con $HOST..."
ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" true 2>/dev/null || {
    echo "❌ No llego a $HOST. ¿Estás en la red WiFi 'TNT'?"; exit 1; }

# La regla de udev va en la raíz, que está bajo el overlay: se escribe en la
# RAM y, si hay overlay, también en la SD (igual que deploy.sh).
en_la_sd() {
    if [ "$(ssh "$HOST" 'findmnt -no FSTYPE /')" != "overlay" ]; then
        return 0
    fi
    # En esta Pi el remount a veces dice "mount point is busy" aunque se
    # aplica: lo que manda es lo que diga findmnt.
    ssh "$HOST" "sudo mount -o remount,rw $LOWER" 2>/dev/null || true
    if [ "$(ssh "$HOST" "findmnt -no OPTIONS $LOWER" | cut -d, -f1)" != "rw" ]; then
        echo "❌ No pude poner la SD en escritura: la regla dura hasta el reboot."
        return 1
    fi
    ssh "$HOST" "$1"
    ssh "$HOST" "sudo sync; sudo mount -o remount,ro $LOWER" 2>/dev/null || true
    if [ "$(ssh "$HOST" "findmnt -no OPTIONS $LOWER" | cut -d, -f1)" != "ro" ]; then
        echo "⚠️  La SD quedó en escritura (pasa en esta Pi); el reboot la devuelve a solo lectura."
    fi
}

if [ "$REVERTIR" = "1" ]; then
    echo "↩️  Revirtiendo..."
    ssh "$HOST" "bash -s" <<'REMOTO'
set -e
CONFIG=/boot/firmware/config.txt
sudo mount -o remount,rw /boot/firmware
if [ -f "$CONFIG.antes-del-reloj" ]; then
    sudo cp "$CONFIG.antes-del-reloj" "$CONFIG"
    echo "   ✅ config.txt restaurado"
fi
sudo sync
sudo mount -o remount,ro /boot/firmware
sudo rm -f /etc/udev/rules.d/60-tnt-rtc.rules
REMOTO
    en_la_sd "sudo rm -f $LOWER$REGLA" && echo "   ✅ regla de udev borrada"
    echo "✅ Revertido. Reiniciá la Pi:  ssh $HOST 'sudo reboot'"
    exit 0
fi

echo "🕰️  Activando el módulo de reloj..."

# ── 1. config.txt ───────────────────────────────────────────────────────────
ssh "$HOST" "bash -s" <<'REMOTO'
set -e
CONFIG=/boot/firmware/config.txt
sudo mount -o remount,rw /boot/firmware

# La copia se hace una sola vez: es la del estado anterior a este script.
if [ ! -f "$CONFIG.antes-del-reloj" ]; then
    sudo cp "$CONFIG" "$CONFIG.antes-del-reloj"
    echo "   💾 copia de seguridad: $CONFIG.antes-del-reloj"
fi

# I2C: descomentar la línea que trae Raspberry Pi OS, o agregarla.
if grep -q '^#dtparam=i2c_arm=on' "$CONFIG"; then
    sudo sed -i 's/^#dtparam=i2c_arm=on/dtparam=i2c_arm=on/' "$CONFIG"
elif ! grep -q '^dtparam=i2c_arm=on' "$CONFIG"; then
    printf '\n[all]\ndtparam=i2c_arm=on\n' | sudo tee -a "$CONFIG" > /dev/null
fi

# El reloj, al final y dentro de [all] (si no, podría quedar en una sección
# que solo vale para otro modelo de placa).
if ! grep -q '^dtoverlay=i2c-rtc,ds3231' "$CONFIG"; then
    printf '\n[all]\n# Módulo de reloj DS3231 (setup-reloj.sh)\ndtoverlay=i2c-rtc,ds3231\n' \
        | sudo tee -a "$CONFIG" > /dev/null
fi

sudo sync
sudo mount -o remount,ro /boot/firmware
echo "   ✅ config.txt: $(grep -E '^(dtparam=i2c_arm|dtoverlay=i2c-rtc)' "$CONFIG" | tr '\n' ' ')"
REMOTO

# ── 2. Permiso para grabar la hora en el módulo ─────────────────────────────
CONTENIDO='KERNEL=="rtc0", GROUP="i2c", MODE="0660"'
ssh "$HOST" "echo '$CONTENIDO' | sudo tee $REGLA > /dev/null; sudo udevadm control --reload"
en_la_sd "sudo cp $REGLA $LOWER$REGLA" && echo "   ✅ regla de udev: /dev/rtc0 escribible por el grupo i2c"

# ── 3. Zona horaria ─────────────────────────────────────────────────────────
# La bitácora y el historial no la usan (guardan instantes UTC y el
# navegador los muestra en su hora local); es para que date, journalctl y
# los logs por ssh salgan en hora de Argentina y no de Londres.
ZONA="America/Argentina/Buenos_Aires"
ssh "$HOST" "sudo timedatectl set-timezone $ZONA"
en_la_sd "sudo ln -sf /usr/share/zoneinfo/$ZONA $LOWER/etc/localtime; echo $ZONA | sudo tee $LOWER/etc/timezone > /dev/null" \
    && echo "   ✅ zona horaria: $ZONA"

echo
echo "✅ Listo. Mandá pruebas.py con ./deploy.sh y reiniciá la Pi:"
echo "   ssh $HOST 'sudo reboot'"
echo "   Comprobá: ssh $HOST 'cat /sys/class/rtc/rtc0/date /sys/class/rtc/rtc0/time; date -u'"
echo "Si algo sale mal:  ./setup-reloj.sh --revertir"
