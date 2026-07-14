#include <ESP8266WiFi.h>
#include <ArduinoOTA.h>
#include <PubSubClient.h>
#include "credentials.h"   // copiar de credentials.h.example (no va al repo)

const char* ssid = WIFI_SSID;
const char* password = WIFI_PASSWORD;
const char* mqtt_server = "192.168.216.1";

// IP fija fuera del rango DHCP de dnsmasq (.10-.50): asocia más rápido y hace
// predecible la dirección para actualizar por OTA.
IPAddress local_ip(192, 168, 216, 5);
IPAddress gateway(192, 168, 216, 1);
IPAddress subnet(255, 255, 255, 0);

// Pines de los botones (Wemos D1 Mini - LOLIN)
const int TEAM1_UP = D1;    // GPIO5
const int TEAM2_UP = D5;    // GPIO14
const int RESET_BTN = D7;   // GPIO13

// Pines de las luces
const int LED_STATUS = D3; // Luz de estado MQTT (GPIO0)

WiFiClient espClient;
PubSubClient client(espClient);

// Temas disponibles (el cliente ya no necesita saberlos)
// const char* themes[] = {"actual", "contraste", "universal"};
// int themeIndex = 0;
unsigned long themePressStart = 0;
bool themeComboActive = false;
bool themeSent = false;

// Parámetro: tiempo de pulsación larga para descontar (milisegundos)
const unsigned long LONG_PRESS_TIME = 1000;
// Parámetro: tiempo de pulsación para cambiar de tema (milisegundos)
const unsigned long THEME_PRESS_TIME = 2000;
// Parámetro: pulsación mínima para considerarse válida (antirrebote)
const unsigned long DEBOUNCE_TIME = 30;
// Parámetro: cada cuánto publica la calidad de señal (milisegundos)
const unsigned long RSSI_INTERVAL = 5000;

void setup() {
  Serial.begin(115200);

  // Configurar botones con pull-up interno
  pinMode(TEAM1_UP, INPUT_PULLUP);
  pinMode(TEAM2_UP, INPUT_PULLUP);
  pinMode(RESET_BTN, INPUT_PULLUP);

  // Configurar LED de estado
  pinMode(LED_STATUS, OUTPUT);
  digitalWrite(LED_STATUS, LOW); // Apagado al inicio

  setup_wifi();
  setup_ota();
  client.setServer(mqtt_server, 1883);
}

// Actualización por WiFi: evita abrir la caja estanca para reflashear.
// Se configura después del WiFi y antes de MQTT, así sigue disponible aunque
// el broker esté caído — que es justo cuando más falta hace.
void setup_ota() {
  ArduinoOTA.setHostname("tanteador-remoto");
  ArduinoOTA.setPassword(OTA_PASSWORD);
  ArduinoOTA.onStart([]() {
    digitalWrite(LED_STATUS, LOW); // LED apagado mientras se graba
  });
  ArduinoOTA.onEnd([]() {
    digitalWrite(LED_STATUS, HIGH);
  });
  ArduinoOTA.begin();
  Serial.print("OTA listo en ");
  Serial.println(WiFi.localIP());
}

void setup_wifi() {
  unsigned long lastBlink = 0;
  bool ledOn = false;
  WiFi.mode(WIFI_STA);
  // Sin modem sleep: dormida la radio, el primer publish tras un rato de
  // inactividad queda encolado en TCP y los puntos llegan todos juntos.
  // El control va por USB, así que el consumo extra no importa.
  WiFi.setSleepMode(WIFI_NONE_SLEEP);
  WiFi.setOutputPower(20.5); // máximo permitido por el chip
  WiFi.persistent(false);    // no reescribir credenciales en flash en cada boot
  WiFi.setAutoReconnect(true);
  WiFi.config(local_ip, gateway, subnet, gateway);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(100);
    Serial.print(".");
    // Parpadeo rápido mientras conecta WiFi
    if (millis() - lastBlink > 200) {
      ledOn = !ledOn;
      digitalWrite(LED_STATUS, ledOn ? HIGH : LOW);
      lastBlink = millis();
    }
  }
  Serial.println("WiFi conectado");
  digitalWrite(LED_STATUS, HIGH); // Encendido fijo al conectar WiFi
}

// No bloquea: reintenta una vez por segundo y devuelve el control al loop,
// que así sigue leyendo los botones y refrescando el LED de estado.
void reconnect() {
  static unsigned long lastAttempt = 0;
  if (millis() - lastAttempt < 1000) return;
  lastAttempt = millis();
  if (client.connect("LOLIN_D1_Scoreboard")) {
    Serial.println("MQTT conectado");
  }
}

void loop() {
  static unsigned long lastBlink = 0;
  static bool ledOn = false;

  ArduinoOTA.handle();

  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  // LED: fijo con MQTT conectado, parpadeo lento si se cayó.
  if (client.connected()) {
    digitalWrite(LED_STATUS, HIGH);
  } else if (millis() - lastBlink > 500) {
    ledOn = !ledOn;
    digitalWrite(LED_STATUS, ledOn ? HIGH : LOW);
    lastBlink = millis();
  }

  // Telemetría de señal, para diagnosticar la cobertura desde la cancha:
  //   mosquitto_sub -v -t rssi
  static unsigned long lastRssi = 0;
  if (client.connected() && millis() - lastRssi > RSSI_INTERVAL) {
    lastRssi = millis();
    char buf[8];
    itoa(WiFi.RSSI(), buf, 10);
    client.publish("rssi", buf);
  }

  // Leer botones (activo en LOW por pull-up)
  bool up1 = digitalRead(TEAM1_UP) == LOW;
  bool up2 = digitalRead(TEAM2_UP) == LOW;
  bool combo = up1 && up2;
  static unsigned long up1PressStart = 0;
  static bool up1LongPressSent = false;
  static bool up1Cancelled = false;
  static unsigned long up2PressStart = 0;
  static bool up2LongPressSent = false;
  static bool up2Cancelled = false;
  static unsigned long resetPressStart = 0;
  static bool resetLongPressSent = false;

  // Detección de combinación para cambiar tema. Anula los eventos pendientes
  // de ambos botones: sin esto, apretar el segundo botón hace que el primero
  // se lea como soltado y publique un punto antes de arrancar la combinación.
  if (combo) {
    up1Cancelled = true;
    up2Cancelled = true;
    if (!themeComboActive) {
      themeComboActive = true;
      themePressStart = millis();
    } else if (!themeSent && millis() - themePressStart > THEME_PRESS_TIME) {
      client.publish("theme", "1");
      themeSent = true;
    }
  } else {
    themeComboActive = false;
    themeSent = false;
  }

  // --- NUEVA LÓGICA: Descuento con long press en botón de suma ---
  // TEAM1_UP
  if (up1) {
    if (up1PressStart == 0) up1PressStart = millis();
    if (!up1LongPressSent && !up1Cancelled && !combo &&
        millis() - up1PressStart > LONG_PRESS_TIME) {
      client.publish("team1/down", "1");
      up1LongPressSent = true; // no repetir mientras siga apretado
    }
  } else if (up1PressStart != 0) {
    unsigned long pressDuration = millis() - up1PressStart;
    if (!up1LongPressSent && !up1Cancelled &&
        pressDuration >= DEBOUNCE_TIME && pressDuration <= LONG_PRESS_TIME) {
      client.publish("team1/up", "1");
    }
    up1PressStart = 0;
    up1LongPressSent = false;
    up1Cancelled = false;
  }

  // TEAM2_UP
  if (up2) {
    if (up2PressStart == 0) up2PressStart = millis();
    if (!up2LongPressSent && !up2Cancelled && !combo &&
        millis() - up2PressStart > LONG_PRESS_TIME) {
      client.publish("team2/down", "1");
      up2LongPressSent = true;
    }
  } else if (up2PressStart != 0) {
    unsigned long pressDuration = millis() - up2PressStart;
    if (!up2LongPressSent && !up2Cancelled &&
        pressDuration >= DEBOUNCE_TIME && pressDuration <= LONG_PRESS_TIME) {
      client.publish("team2/up", "1");
    }
    up2PressStart = 0;
    up2LongPressSent = false;
    up2Cancelled = false;
  }

  // --- Lógica para botón RESET con pulsación larga ---
  bool resetPressed = digitalRead(RESET_BTN) == LOW;
  if (resetPressed) {
    if (resetPressStart == 0) resetPressStart = millis();
    if (!resetLongPressSent && millis() - resetPressStart > LONG_PRESS_TIME) {
      client.publish("reset", "1");
      resetLongPressSent = true;
    }
  } else {
    resetPressStart = 0;
    resetLongPressSent = false;
  }

  //Retardo general anti rebote
  delay(20);

}