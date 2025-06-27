#include <ESP8266WiFi.h>
#include <PubSubClient.h>

const char* ssid = "TNT";
const char* password = "SET_YOUR_PASSWORD_HERE"; 
const char* mqtt_server = "192.168.216.1";

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

// Parámetro: tiempo de pulsación larga para descontar (milisegundos)
const unsigned long LONG_PRESS_TIME = 1000;
// Parámetro: tiempo de pulsación para cambiar de tema (milisegundos)
const unsigned long THEME_PRESS_TIME = 2000;

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
  client.setServer(mqtt_server, 1883);
}

void setup_wifi() {
  unsigned long lastBlink = 0;
  bool ledOn = false;
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

void reconnect() {
  while (!client.connected()) {
    if (client.connect("LOLIN_D1_Scoreboard")) {
      Serial.println("MQTT conectado");
    } else {
      delay(1000);
    }
  }
}

void loop() {
  static unsigned long lastBlink = 0;
  static bool ledOn = false;

  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  // Leer botones (activo en LOW por pull-up)
  bool up1 = digitalRead(TEAM1_UP) == LOW;
  bool up2 = digitalRead(TEAM2_UP) == LOW;
  static unsigned long up1PressStart = 0;
  static bool up1LongPressSent = false;
  static unsigned long up2PressStart = 0;
  static bool up2LongPressSent = false;
  static unsigned long resetPressStart = 0;
  static bool resetLongPressSent = false;

  // Detección de combinación para cambiar tema
  if (up1 && up2) {
    if (!themeComboActive) {
      themeComboActive = true;
      themePressStart = millis();
    } else if (millis() - themePressStart > THEME_PRESS_TIME) {
      client.publish("theme", "1");
      while (digitalRead(TEAM1_UP) == LOW || digitalRead(TEAM2_UP) == LOW) {
        delay(100);
      }
      themeComboActive = false;
      delay(500);
    }
  } else {
    themeComboActive = false;
  }

  // --- NUEVA LÓGICA: Descuento con long press en botón de suma ---
  // TEAM1_UP
  if (up1 && !(up1 && up2)) {
    if (up1PressStart == 0) up1PressStart = millis();
    if (millis() - up1PressStart > LONG_PRESS_TIME) {
      client.publish("team1/down", "1");
      up1LongPressSent = true;
      delay(1000); // Anti-rebote
    }
  } else if (up1PressStart != 0) {
    unsigned long pressDuration = millis() - up1PressStart;
    if (!up1LongPressSent && pressDuration <= LONG_PRESS_TIME) {
      client.publish("team1/up", "1");
      delay(300); // Anti-rebote
    }
    up1PressStart = 0;
    up1LongPressSent = false;
  }

  // TEAM2_UP
  if (up2 && !(up1 && up2)) {
    if (up2PressStart == 0) up2PressStart = millis();
    if ( millis() - up2PressStart > LONG_PRESS_TIME) {
      client.publish("team2/down", "1");
      up2LongPressSent = true;
      delay(1000); // Anti-rebote
    }
  } else if (up2PressStart != 0) {
    unsigned long pressDuration = millis() - up2PressStart;
    if (!up2LongPressSent && pressDuration <= LONG_PRESS_TIME) {
      client.publish("team2/up", "1");
      delay(300); // Anti-rebote
    }
    up2PressStart = 0;
    up2LongPressSent = false;
  }

  // --- Lógica para botón RESET con pulsación larga ---
  bool resetPressed = digitalRead(RESET_BTN) == LOW;
  if (resetPressed) {
    if (resetPressStart == 0) resetPressStart = millis();
    if (!resetLongPressSent && millis() - resetPressStart > LONG_PRESS_TIME) {
      client.publish("reset", "1");
      resetLongPressSent = true;
      delay(500);
    }
  } else {
    resetPressStart = 0;
    resetLongPressSent = false;
  }

  //Retardo general anti rebote
  delay(20);

}