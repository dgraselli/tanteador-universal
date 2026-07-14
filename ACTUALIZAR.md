# Cómo actualizar el tanteador en el club

Guía para cuando estás frente al tablero, con la notebook, y tenés acceso físico
a la Raspberry y al control remoto.

## Lo que corre en cada lado

| Dónde | Qué | Cómo se actualiza |
|---|---|---|
| Raspberry Pi | `tanteador.py`, sonidos | `./deploy.sh` desde la notebook |
| Raspberry Pi | AP WiFi (`hostapd`, `dnsmasq`) | editando `/etc/hostapd/hostapd.conf` a mano |
| Wemos D1 Mini | firmware `.ino` | por WiFi (OTA), o por USB la primera vez |

Datos de la red, para tenerlos a mano:

| | |
|---|---|
| Red WiFi | `TNT`, canal 6, SSID visible |
| Raspberry Pi | `192.168.216.1` (usuario `chaca`, código en `/home/chaca/tnt`) |
| Control remoto | `192.168.216.5` (IP fija), hostname `tanteador-remoto` |
| Rango DHCP | `192.168.216.10` a `.50` |
| Broker MQTT | puerto `1883` en la Pi, sin autenticación |

**La Pi no tiene internet.** Su única radio está haciendo de access point. No
podés hacer `git pull` desde la Pi: los archivos se empujan desde la notebook.

## La Pi arranca en solo lectura (leé esto antes de tocar nada)

El sistema de archivos está protegido con `overlayroot=tmpfs`: la SD se monta de
solo lectura y **todo lo que escribís vive en RAM**. Al reiniciar, la Pi vuelve
exactamente al estado que tiene grabado en la tarjeta. Es lo que evita que un
corte de luz en pleno partido te corrompa la SD.

La trampa es que nada te avisa. Editás un archivo, lo ves cambiado, reiniciás, y
el cambio no existió nunca.

`deploy.sh` ya se ocupa: detecta el overlay, remonta la SD en escritura el tiempo
justo, escribe también ahí, y verifica por MD5 que lo que quedó grabado sea lo
tuyo. Si ves `✅ Guardado en la SD: sobrevive al reboot`, estás cubierto.

Para cualquier otro cambio a mano en la Pi (por ejemplo `hostapd.conf`), el
procedimiento es:

```bash
sudo mount -o remount,rw /media/root-ro      # abre la SD
sudo nano /media/root-ro/etc/hostapd/hostapd.conf   # editás la copia de la SD
sudo sync
sudo mount -o remount,ro /media/root-ro      # y la cerrás enseguida
```

Ojo: eso graba en la SD pero **no** cambia lo que ve el sistema corriendo, que
sigue mirando la capa de RAM. Hay que editar los dos: el de `/media/root-ro/...`
para que sobreviva, y el de `/etc/...` para que tome efecto ahora.

Para verificar si un archivo quedó grabado de verdad:

```bash
sudo md5sum /etc/hostapd/hostapd.conf /media/root-ro/etc/hostapd/hostapd.conf
```

Si los dos MD5 coinciden, sobrevive al reboot. Si no, se pierde.

---

## Preparación, una sola vez

Antes de salir de casa, creá los dos archivos de credenciales. Ninguno de los
dos está en el repo, y sin ellos no compila ni se instala nada.

```bash
cp secrets.env.example secrets.env
chmod 600 secrets.env
# editá secrets.env: AP_PASSWORD tiene que ser la contraseña real del AP

cp esp8266/tanteador_remoto_LOLIN/credentials.h.example \
   esp8266/tanteador_remoto_LOLIN/credentials.h
# editá credentials.h: WIFI_PASSWORD igual que AP_PASSWORD, y elegí un OTA_PASSWORD
```

En el club, la primera vez, hay que cambiar el `.xinitrc` de la Pi. Conectate a
la red `TNT` y:

```bash
scp .xinitrc chaca@192.168.216.1:/home/chaca/.xinitrc
```

Del servicio systemd se encarga `deploy.sh`: lo instala si falta, y lo
reemplaza si el de la Pi quedó viejo. La Pi traía un `tanteador.service`
anterior que apuntaba a `tanteador_pyqt.py`, un archivo que ya no existe.

Después del primer deploy, `sudo reboot` una vez para verificar que arranca solo.

> El `.xinitrc` nuevo ya no lanza el tanteador; lo lanza systemd. Por eso el
> orden importa: corré `./deploy.sh` **antes** de copiar el `.xinitrc`, o al
> reiniciar la Pi te quedás con la pantalla vacía.

---

## Actualizar el tablero (Raspberry)

Conectate a la red `TNT` desde la notebook y, parado en el repo:

```bash
./deploy.sh --check    # muestra qué archivos cambiarían, sin tocar nada
./deploy.sh            # copia y reinicia el servicio
```

El script se niega a seguir si no llega a la Pi, y si el servicio no levanta te
muestra las últimas 30 líneas del log en vez de dejarte adivinando.

No hace falta reiniciar la Pi. Tampoco hace falta reiniciar el control remoto.

Para reiniciar el tanteador sin desplegar nada:

```bash
ssh chaca@192.168.216.1 'sudo systemctl restart tanteador'
```

---

## Actualizar el control remoto (ESP8266)

### La primera vez: por USB

Hay que abrir la caja estanca. **Antes de flashear, guardá el firmware actual**,
que es lo único que te permite volver exactamente al estado anterior:

```bash
./backup-firmware.sh
```

Guardá ese `.bin` fuera de la Pi. Tiene la contraseña del WiFi adentro, en texto
plano, así que no lo subas al repo (el `.gitignore` ya ignora `*.bin`).

Después, abrí `esp8266/tanteador_remoto_LOLIN/tanteador_remoto_LOLIN.ino` en el
Arduino IDE, elegí la placa **LOLIN(WEMOS) D1 R2 & mini**, el puerto USB, y dale
a subir.

### De ahí en adelante: por WiFi (OTA)

Con el firmware nuevo ya instalado, el control remoto acepta actualizaciones por
la red y no hay que volver a abrir la caja.

En el Arduino IDE, con la notebook conectada a la red `TNT`, aparece un puerto
de red nuevo en **Herramientas → Puerto**: `tanteador-remoto at 192.168.216.5`.
Elegilo y subí normalmente. Te va a pedir el `OTA_PASSWORD` de `credentials.h`.

Desde la terminal, si preferís:

```bash
python3 ~/.platformio/packages/framework-arduinoespressif8266/tools/espota.py \
    -i 192.168.216.5 -p 8266 --auth=TU_OTA_PASSWORD -f firmware.bin
```

El OTA se configura **antes** que MQTT y funciona aunque el broker esté caído,
que es justo cuando más lo necesitás. Lo que sí necesita es que el ESP esté
asociado al WiFi: si no aparece el puerto de red, mirá la sección de
diagnóstico.

---

## Verificar que quedó bien

El LED del control remoto queda **fijo** cuando está conectado a MQTT, y
**parpadea lento** cuando el WiFi anda pero el broker no responde.

Desde la Pi, mirá los mensajes en vivo:

```bash
ssh chaca@192.168.216.1
mosquitto_sub -v -t '#' -F '%I %t %p'
```

Apretá los botones y comprobá:

- Toque corto en un botón de equipo → un `team1/up` (o `team2/up`), un solo punto.
- Mantener apretado más de un segundo → **un solo** `team1/down`, aunque lo
  sigas apretando.
- Los dos botones juntos, dos segundos → un `theme`, y **ningún** punto.
- Cada 5 segundos aparece un `rssi` con la calidad de señal en dBm.

Sobre el RSSI: de −30 a −60 dBm es excelente; de −60 a −70 está bien; de −70 a
−80 es marginal y se va a cortar a ratos; peor que −85 dBm no hay enlace.

Para medirlo a lo largo de la cancha, dejá la notebook al lado del tablero y:

```bash
./medir-senal.sh 180        # mide 3 minutos
```

Agarrá el control, andá al primer punto, apretá una vez el botón del LOCAL para
marcarlo, y quedate quieto ~20 segundos. Repetí en cada punto. Al terminar te
muestra el peor, el mejor y la media de cada uno. El botón suma puntos en el
tablero: cuando termines, mantené apretado RESET.

El número que importa es el **peor** valor en el punto más lejano, con la caja
cerrada y montada. Si ahí sigue por encima de −70 dBm, la señal queda descartada
como causa de los cortes.

---

## Si algo sale mal

**El tanteador no arranca:**

```bash
ssh chaca@192.168.216.1 'journalctl -u tanteador -n 50 --no-pager'
```

El servicio reintenta cada 2 segundos para siempre, así que un error transitorio
(por ejemplo, que X todavía no levantó) se resuelve solo. Un error de import de
Python, no.

**Volver a la versión anterior del tanteador:**

```bash
git checkout HEAD~1 -- tanteador.py && ./deploy.sh
```

**Volver al firmware anterior del ESP** (requiere USB, no se puede por OTA):

```bash
esptool.py --port /dev/ttyUSB0 write_flash 0 ~/firmware_tnt_backup_FECHA.bin
```

**El control remoto no aparece como puerto de red:** revisá que la notebook esté
en la red `TNT` y no en otra. Después, desde la Pi, verificá que el ESP esté
asociado: `ping 192.168.216.5`. Si no responde, quedó sin WiFi y hay que
abrir la caja y flashear por USB.

---

## Rotar la contraseña del WiFi

**Esto siempre requiere USB.** No se puede hacer por OTA, y el motivo es fácil de
pasar por alto: si flasheás por WiFi un firmware con la contraseña nueva, el ESP
reinicia, intenta asociarse al AP que todavía tiene la contraseña vieja, falla, y
te quedás sin OTA y sin control remoto. La única salida sería abrir la caja.

El orden correcto:

1. Generá la contraseña nueva: `openssl rand -base64 18`
2. Ponela en `secrets.env` (`AP_PASSWORD`) y en `credentials.h` (`WIFI_PASSWORD`).
3. Cambiala en la Pi, en los **dos** lugares (acordate del solo lectura):
   ```bash
   ssh chaca@192.168.216.1
   sudo mount -o remount,rw /media/root-ro
   sudo nano /media/root-ro/etc/hostapd/hostapd.conf   # línea wpa_passphrase=
   sudo sync && sudo mount -o remount,ro /media/root-ro
   sudo nano /etc/hostapd/hostapd.conf                 # la misma línea, copia viva
   # y comprobá que quedaron iguales:
   sudo md5sum /etc/hostapd/hostapd.conf /media/root-ro/etc/hostapd/hostapd.conf
   ```
4. Flasheá el ESP **por USB** con el `credentials.h` nuevo, *antes* de reiniciar
   el AP: el flasheo no necesita WiFi, y así conservás la red hasta el final.
5. Recién ahora reiniciá el AP: `sudo systemctl restart hostapd`. Se te cae el
   SSH y el WiFi.
6. Reconectá la notebook (y los celulares) a `TNT` con la contraseña nueva.

Anotá la contraseña vieja junto al archivo de backup del firmware: ese `.bin` la
lleva compilada adentro, y si algún día lo restaurás, el ESP va a buscar la red
con la clave vieja.

> No vuelvas a correr `setup-ap.sh` sobre una Pi que ya está configurada. El
> script hace `>>` sobre `/etc/dhcpcd.conf` y te duplica el bloque `interface
> wlan0` en cada corrida. Está pensado para una instalación desde cero.

---

## Diagnóstico rápido

```bash
# ¿está corriendo el tanteador?
ssh chaca@192.168.216.1 'systemctl status tanteador'

# ¿está levantado el access point?
ssh chaca@192.168.216.1 'systemctl status hostapd'

# ¿quién está conectado a la red?
ssh chaca@192.168.216.1 'sudo iw dev wlan0 station dump | grep -E "Station|signal"'

# ¿llegan los mensajes del control remoto?
ssh chaca@192.168.216.1 "mosquitto_sub -v -t '#' -F '%I %t %p'"

# ¿qué canales están ocupados? (corta el AP unos segundos)
ssh chaca@192.168.216.1 'sudo systemctl stop hostapd && \
    sudo iw dev wlan0 scan | grep -E "SSID|freq:|signal:" ; \
    sudo systemctl start hostapd'
```

Si en `mosquitto_sub` ves llegar varios puntos **con la misma marca de tiempo**
después de que alguien apretó el botón varias veces, el ESP está guardando los
mensajes y soltándolos en ráfaga: es el problema del modem sleep, y significa que
el firmware que tiene cargado es el viejo.
