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

// Pines de los botones (NodeMCU v3 LOLIN, CH340)
const int TEAM1_UP = D1;    // GPIO5
const int TEAM2_UP = D5;    // GPIO14
const int RESET_BTN = D7;   // GPIO13

// Pines de las luces
const int LED_STATUS = D3; // Luz de estado MQTT (GPIO0)

// Buzzer: suena cuando el tablero confirma que el toque se anotó, con un
// sonido distinto si no contó. Sin buzzer conectado el pin cambia al aire y
// no pasa nada. -1 = sin buzzer.
//
// S3 (GPIO10), del lado izquierdo de la NodeMCU v3 LOLIN, como VIN y GND que
// lo alimentan. Ese lado es casi todo de la memoria flash: GPIO10 queda libre
// solo si el firmware se graba en modo DIO (o DOUT); en QIO la flash lo usa y
// tocarlo cuelga el ESP. PlatformIO graba en DIO por defecto; en el Arduino
// IDE, Herramientas -> Flash Mode: DIO. Por las dudas, setup() mira el modo
// real y, si no es DIO/DOUT, deja el buzzer apagado en vez de colgarse.
// Alternativa sin esa vuelta: D6 (GPIO12), del lado derecho.
const int BUZZER_PIN = 10;  // S3 = GPIO10
int BUZZER = -1;            // el pin en uso, o -1 si no hay buzzer
// Activo (trae oscilador: suena con solo darle tensión, siempre en el mismo
// tono) o pasivo (KY-006: el ESP le genera la frecuencia con tone()). El
// activo no distingue tonos: los sonidos se diferencian por el ritmo.
const bool BUZZER_ACTIVO = true;
// Nivel que lo hace sonar. HIGH con transistor NPN o buzzer suelto; algunos
// módulos de 3 pines suenan con LOW (traen un PNP): si suena siempre y calla
// en los beeps, cambiar a LOW.
const int BUZZER_SUENA = HIGH;

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

// Confirmación de cada toque. Cada mensaje lleva "nonce,seq,t_toque,t_envio":
//   nonce   al azar en cada arranque (el seq y millis() vuelven a cero)
//   seq     número del toque: el tablero descarta los repetidos y contesta
//           "nonce,seq,resultado" en el tópico "ack": "ok" si se anotó (ya
//           está en pantalla), "ign" si lo frenó el antirrebote del tablero
//           (doble toque). A los que llegan tarde no les contesta.
//   t_*     millis() del toque y del envío: con el "latido" (cada
//           RSSI_INTERVAL) el tablero sabe cuánto tardó en llegar y descarta
//           los toques viejos, que caían de golpe al volver la señal.
// Sin ack, el toque se reenvía cada REENVIO_MS hasta ABANDONO_MS (el mismo
// atraso máximo que acepta el tablero). Si no llega la confirmación, el LED
// parpadea rápido: no contó, hay que volver a apretar.
const unsigned long REENVIO_MS = 700;
const unsigned long ABANDONO_MS = 3000;
// Margen para que el ack de un toque que entró justo a tiempo vuelva igual.
const unsigned long ESPERA_ACK_MS = ABANDONO_MS + 1000;
const int MAX_PENDIENTES = 8;

struct Pendiente {
  const char* topico;
  uint32_t seq;
  unsigned long tToque;
  unsigned long tEnvio;  // 0 = todavía no salió
  bool activo;
};
Pendiente pendientes[MAX_PENDIENTES];
char nonce[5];
uint32_t proximoSeq = 1;

// LED: guiño (apagado breve) si el tablero confirmó, parpadeo rápido si no.
unsigned long ledGuinoHasta = 0;
unsigned long ledFallaHasta = 0;

// Sonidos: notas (frecuencia, duración, silencio después) que el loop toca
// de a una, sin frenar la lectura de los botones. Con buzzer activo la
// frecuencia se ignora: cuentan la duración y los silencios.
struct Nota { unsigned int hz; unsigned int ms; unsigned int pausa; };
const Nota SON_PUNTO[] = {{2400, 120, 0}};
const Nota SON_RESTA[] = {{1600, 70, 60}, {1600, 70, 0}};   // como en el tablero
const Nota SON_RESET[] = {{1200, 400, 0}};
const Nota SON_TEMA[]  = {{2000, 60, 30}, {2800, 60, 0}};
// No contó: tres largos y graves, que no se confunden con nada de lo anterior.
const Nota SON_FALLA[] = {{500, 200, 80}, {420, 200, 80}, {350, 450, 0}};
const Nota* sonido = nullptr;
int notasRestantes = 0;
unsigned long proximaNota = 0;
unsigned long apagarBuzzer = 0;  // solo buzzer activo: cuándo cortar la nota
bool buzzerSonando = false;

void sonar(const Nota* notas, int cuantas);
void atenderSonido();
void enviar(const char* topico);
void publicarPendiente(Pendiente& p);
void atenderPendientes();
void recibir(char* topico, byte* payload, unsigned int largo);

void setup() {
  Serial.begin(115200);

  // Configurar botones con pull-up interno
  pinMode(TEAM1_UP, INPUT_PULLUP);
  pinMode(TEAM2_UP, INPUT_PULLUP);
  pinMode(RESET_BTN, INPUT_PULLUP);

  // Configurar LED de estado
  pinMode(LED_STATUS, OUTPUT);
  digitalWrite(LED_STATUS, LOW); // Apagado al inicio
  FlashMode_t modo = ESP.getFlashChipMode();
  if (BUZZER_PIN == 9 || BUZZER_PIN == 10) {
    if (modo == FM_DIO || modo == FM_DOUT) {
      BUZZER = BUZZER_PIN;
    } else {
      Serial.println("Flash en QIO: GPIO9/10 son de la flash, buzzer apagado");
    }
  } else {
    BUZZER = BUZZER_PIN;
  }
  if (BUZZER >= 0) {
    pinMode(BUZZER, OUTPUT);
    digitalWrite(BUZZER, BUZZER_ACTIVO ? !BUZZER_SUENA : LOW);
  }

  setup_wifi();
  // Después del WiFi: el generador del ESP8266 saca el azar del ruido de la
  // radio, y antes de encenderla el valor es menos aleatorio.
  snprintf(nonce, sizeof(nonce), "%04x", (unsigned) (ESP.random() & 0xffff));
  setup_ota();
  client.setServer(mqtt_server, 1883);
  client.setCallback(recibir);
}

#define SONAR(son) sonar(son, sizeof(son) / sizeof(son[0]))

// Un sonido nuevo corta el que estuviera sonando.
void sonar(const Nota* notas, int cuantas) {
  if (BUZZER < 0) return;
  sonido = notas;
  notasRestantes = cuantas;
  proximaNota = millis();
}

void atenderSonido() {
  if (buzzerSonando && (long) (millis() - apagarBuzzer) >= 0) {
    digitalWrite(BUZZER, !BUZZER_SUENA);
    buzzerSonando = false;
  }
  if (notasRestantes == 0 || (long) (millis() - proximaNota) < 0) return;
  if (BUZZER_ACTIVO) {
    digitalWrite(BUZZER, BUZZER_SUENA);
    buzzerSonando = true;
    apagarBuzzer = millis() + sonido->ms;
  } else {
    tone(BUZZER, sonido->hz, sonido->ms);
  }
  proximaNota = millis() + sonido->ms + sonido->pausa;
  sonido++;
  notasRestantes--;
}

// El sonido de confirmación según qué se apretó.
void sonarConfirmado(const char* topico) {
  if (strcmp(topico, "reset") == 0) SONAR(SON_RESET);
  else if (strcmp(topico, "theme") == 0) SONAR(SON_TEMA);
  else if (strstr(topico, "/down")) SONAR(SON_RESTA);
  else SONAR(SON_PUNTO);
}

// Anota el toque y lo manda: el loop lo reenvía hasta tener ack.
void enviar(const char* topico) {
  int libre = 0;
  for (int i = 0; i < MAX_PENDIENTES; i++) {
    if (!pendientes[i].activo) { libre = i; break; }
    // Sin lugar: se pisa el más viejo (ya está por abandonarse).
    if (pendientes[i].tToque < pendientes[libre].tToque) libre = i;
  }
  pendientes[libre] = {topico, proximoSeq++, millis(), 0, true};
  publicarPendiente(pendientes[libre]);
}

void publicarPendiente(Pendiente& p) {
  if (!client.connected()) return;
  char buf[48];
  unsigned long ahora = millis();
  snprintf(buf, sizeof(buf), "%s,%lu,%lu,%lu", nonce, (unsigned long) p.seq,
           p.tToque, ahora);
  if (client.publish(p.topico, buf)) p.tEnvio = ahora;
}

void atenderPendientes() {
  unsigned long ahora = millis();
  for (int i = 0; i < MAX_PENDIENTES; i++) {
    Pendiente& p = pendientes[i];
    if (!p.activo) continue;
    unsigned long edad = ahora - p.tToque;
    if (edad > ESPERA_ACK_MS) {
      p.activo = false;
      ledFallaHasta = ahora + 2000;
      SONAR(SON_FALLA);
    } else if (edad < ABANDONO_MS &&
               (p.tEnvio == 0 || ahora - p.tEnvio > REENVIO_MS)) {
      publicarPendiente(p);
    }
  }
}

// "ack": "nonce,seq,resultado" del toque que el tablero recibió.
void recibir(char* topico, byte* payload, unsigned int largo) {
  char buf[32];
  if (strcmp(topico, "ack") != 0 || largo >= sizeof(buf)) return;
  memcpy(buf, payload, largo);
  buf[largo] = 0;
  char* coma = strchr(buf, ',');
  if (!coma) return;
  *coma = 0;
  if (strcmp(buf, nonce) != 0) return;
  char* resto;
  uint32_t seq = strtoul(coma + 1, &resto, 10);
  // Sin resultado (tablero anterior a este cambio): se toma como anotado.
  bool anotado = *resto != ',' || strcmp(resto + 1, "ok") == 0;
  for (int i = 0; i < MAX_PENDIENTES; i++) {
    if (pendientes[i].activo && pendientes[i].seq == seq) {
      pendientes[i].activo = false;
      // "ign" (doble toque frenado): el primero ya sonó, este queda callado.
      if (anotado) {
        ledGuinoHasta = millis() + 150;
        sonarConfirmado(pendientes[i].topico);
      }
    }
  }
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
    client.subscribe("ack");
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
  atenderPendientes();
  atenderSonido();

  // LED: fijo con MQTT conectado, parpadeo lento si se cayó. Encima, el
  // resultado del último toque: guiño si entró, parpadeo rápido si no.
  if (millis() < ledFallaHasta) {
    digitalWrite(LED_STATUS, (millis() / 100) % 2 ? HIGH : LOW);
  } else if (millis() < ledGuinoHasta) {
    digitalWrite(LED_STATUS, LOW);
  } else if (client.connected()) {
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
    // Reloj del control, para que el tablero mida el atraso de los toques.
    char latido[24];
    snprintf(latido, sizeof(latido), "%s,%lu", nonce, millis());
    client.publish("latido", latido);
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
      enviar("theme");
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
      enviar("team1/down");
      up1LongPressSent = true; // no repetir mientras siga apretado
    }
  } else if (up1PressStart != 0) {
    unsigned long pressDuration = millis() - up1PressStart;
    if (!up1LongPressSent && !up1Cancelled &&
        pressDuration >= DEBOUNCE_TIME && pressDuration <= LONG_PRESS_TIME) {
      enviar("team1/up");
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
      enviar("team2/down");
      up2LongPressSent = true;
    }
  } else if (up2PressStart != 0) {
    unsigned long pressDuration = millis() - up2PressStart;
    if (!up2LongPressSent && !up2Cancelled &&
        pressDuration >= DEBOUNCE_TIME && pressDuration <= LONG_PRESS_TIME) {
      enviar("team2/up");
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
      enviar("reset");
      resetLongPressSent = true;
    }
  } else {
    resetPressStart = 0;
    resetLongPressSent = false;
  }

  //Retardo general anti rebote
  delay(20);

}