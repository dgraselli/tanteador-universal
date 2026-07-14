#!/bin/bash

set -e

# 🛠️ Configuración personalizable
SSID="TNT"
COUNTRY="AR"
STATIC_IP="192.168.216.1"
# Solo 1, 6 y 11 no se solapan entre sí. Elegí el menos poblado con:
#   systemctl stop hostapd && iw dev wlan0 scan | grep -E 'SSID|freq:|signal:'
CHANNEL="6"

# 🔑 La contraseña vive fuera del repo, en secrets.env (ver secrets.env.example)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS="$HERE/secrets.env"

if [ ! -f "$SECRETS" ]; then
    echo "❌ Falta $SECRETS"
    echo "   cp secrets.env.example secrets.env && chmod 600 secrets.env"
    echo "   y poné adentro la contraseña del AP."
    exit 1
fi

# shellcheck source=/dev/null
. "$SECRETS"
PASSWORD="${AP_PASSWORD:?secrets.env no define AP_PASSWORD}"

if [ "$PASSWORD" = "cambiame" ]; then
    echo "❌ secrets.env todavía tiene la contraseña de ejemplo."
    echo "   Generá una con: openssl rand -base64 18"
    exit 1
fi

# WPA2-PSK no acepta nada fuera de este rango; mejor fallar acá que en hostapd.
if [ ${#PASSWORD} -lt 8 ] || [ ${#PASSWORD} -gt 63 ]; then
    echo "❌ La contraseña debe tener entre 8 y 63 caracteres (tiene ${#PASSWORD})."
    exit 1
fi

echo "👉 Instalando paquetes necesarios..."
apt update
apt install -y hostapd dnsmasq

echo "🛑 Deteniendo servicios por ahora..."
systemctl stop hostapd
systemctl stop dnsmasq

echo "🔧 Configurando IP estática en wlan0..."
cat <<EOF >> /etc/dhcpcd.conf

interface wlan0
    static ip_address=$STATIC_IP/24
    nohook wpa_supplicant
EOF

echo "📡 Configurando dnsmasq..."
mv /etc/dnsmasq.conf /etc/dnsmasq.conf.orig 2>/dev/null || true
cat <<EOF > /etc/dnsmasq.conf
interface=wlan0
dhcp-range=192.168.216.10,192.168.216.50,255.255.255.0,24h
EOF

echo "📶 Configurando hostapd..."
cat <<EOF > /etc/hostapd/hostapd.conf
interface=wlan0
driver=nl80211
ssid=$SSID
hw_mode=g
channel=$CHANNEL
wmm_enabled=0
macaddr_acl=0
auth_algs=1

# SSID visible. Ocultarlo (=1) no aporta seguridad —la red aparece igual en un
# escaneo pasivo apenas un cliente se asocia— y obliga al ESP8266 a asociarse
# por probe requests dirigidas, que es lento y falla seguido.
ignore_broadcast_ssid=0

wpa=2
wpa_passphrase=$PASSWORD
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
country_code=$COUNTRY
EOF

# El archivo queda con la passphrase adentro: que no lo lea cualquiera.
chmod 600 /etc/hostapd/hostapd.conf

sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd || \
echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' >> /etc/default/hostapd

echo "🔓 Desbloqueando Wi-Fi..."
rfkill unblock wlan

echo "✅ Habilitando y arrancando servicios..."
systemctl unmask hostapd
systemctl enable hostapd
systemctl enable dnsmasq
systemctl restart dhcpcd
systemctl start hostapd
systemctl start dnsmasq

echo ""
echo "🎉 ¡Listo! Tu Raspberry ahora es un Access Point llamado '$SSID'"
echo "📱 Conectate con la contraseña que pusiste en secrets.env"
echo "🌐 Dirección IP del AP: $STATIC_IP"
echo "📻 Canal $CHANNEL"

