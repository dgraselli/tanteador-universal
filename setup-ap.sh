#!/bin/bash

set -e

# 🛠️ Configuración personalizable
SSID="TNT"
PASSWORD="tnt212121"
COUNTRY="AR"
STATIC_IP="192.168.216.1"

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
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1

#ignore_broadcast_ssid=0
ignore_broadcast_ssid=1    # para ocultar SSID

wpa=2
wpa_passphrase=$PASSWORD
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
country_code=$COUNTRY
EOF

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
echo "📱 Podés conectarte usando la contraseña '$PASSWORD'"
echo "🌐 Dirección IP del AP: $STATIC_IP"

