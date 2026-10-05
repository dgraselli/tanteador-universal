# El tanteador ya no se lanza acá: lo maneja systemd (tanteador.service).
# Así se reinicia sin reiniciar la Pi, y se levanta solo si se cae en un partido.

# Resolución fija, si cmdline.txt la pide (video=HDMI-A-1:..., lo pone
# setup-pantalla.sh). Sin esto, X elige según el EDID del monitor, que con el
# cable marginal llega corrupto: cada arranque salía en una resolución
# distinta (1024x768, 1600x900, 1920x1080; bitácora, oct 2026).
MODO=$(grep -o 'video=HDMI-A-1:[0-9]*x[0-9]*' /proc/cmdline | cut -d: -f2)
if [ -n "$MODO" ]; then
    SALIDA=HDMI-1
    if ! xrandr --output "$SALIDA" --mode "$MODO" 2>/dev/null; then
        # El EDID no trajo ese modo (no se pudo leer): se agrega a mano, con
        # los tiempos estándar de cada resolución a 60 Hz.
        case "$MODO" in
            1280x720)  LINEA="74.25 1280 1390 1430 1650 720 725 730 750 +hsync +vsync" ;;
            1600x900)  LINEA="108.00 1600 1624 1704 1800 900 901 904 1000 +hsync +vsync" ;;
            1920x1080) LINEA="148.50 1920 2008 2052 2200 1080 1084 1089 1125 +hsync +vsync" ;;
            1024x768)  LINEA="65.00 1024 1048 1184 1344 768 771 777 806 -hsync -vsync" ;;
        esac
        if [ -n "$LINEA" ]; then
            xrandr --newmode "tnt-$MODO" $LINEA
            xrandr --addmode "$SALIDA" "tnt-$MODO"
            xrandr --output "$SALIDA" --mode "tnt-$MODO"
        fi
    fi
fi

exec openbox
