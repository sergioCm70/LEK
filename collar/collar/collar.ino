/*
  Collar de IA — XIAO ESP32S3 Sense
  Mantén presionado el botón, habla, suelta: el collar manda tu voz al PC,
  tu asistente piensa y el collar te responde por el parlante.

  Arduino IDE:  placa "XIAO_ESP32S3"  (paquete esp32 de Espressif, versión 3.x)
                Herramientas -> PSRAM: "OPI PSRAM"   (¡obligatorio!)
  Antes de subir: copia config.ejemplo.h como config.h y llena tus datos.
*/
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ESP_I2S.h>
#include "config.h"

// ---- pines
#define PIN_BOTON   1   // D0  -> botón a GND
#define MIC_CLK    42   // micrófono PDM de la placa Sense
#define MIC_DATA   41
#define AMP_BCLK    7   // D8  -> MAX98357A BCLK
#define AMP_LRC     8   // D9  -> MAX98357A LRC
#define AMP_DIN     9   // D10 -> MAX98357A DIN

#define FRECUENCIA     16000
#define MAX_SEGUNDOS   10
#define CABECERA       44

I2SClass mic;
I2SClass parlante;
uint8_t *grabacion = nullptr;   // PSRAM: cabecera WAV + audio
const size_t MAX_AUDIO = FRECUENCIA * 2 * MAX_SEGUNDOS;

// ------------------------------------------------------------ utilidades
void escribirCabeceraWav(uint8_t *h, uint32_t bytesAudio) {
  uint32_t tasa = FRECUENCIA, bytesSeg = FRECUENCIA * 2, total = bytesAudio + 36;
  uint16_t fmt = 1, canales = 1, bloque = 2, bits = 16;
  uint32_t tamFmt = 16;
  memcpy(h, "RIFF", 4);       memcpy(h + 4, &total, 4);     memcpy(h + 8, "WAVE", 4);
  memcpy(h + 12, "fmt ", 4);  memcpy(h + 16, &tamFmt, 4);   memcpy(h + 20, &fmt, 2);
  memcpy(h + 22, &canales, 2); memcpy(h + 24, &tasa, 4);    memcpy(h + 28, &bytesSeg, 4);
  memcpy(h + 32, &bloque, 2); memcpy(h + 34, &bits, 2);
  memcpy(h + 36, "data", 4);  memcpy(h + 40, &bytesAudio, 4);
}

void tono(int hz, int ms) {  // pitidos de aviso
  const int n = FRECUENCIA * ms / 1000;
  int16_t m[256];
  for (int i = 0; i < n; i += 256) {
    int k = min(256, n - i);
    for (int j = 0; j < k; j++) m[j] = (((i + j) * hz * 2 / FRECUENCIA) % 2) ? 2500 : -2500;
    parlante.write((uint8_t *)m, k * 2);
  }
}

void silencio(int ms) {
  int16_t cero[256] = {0};
  for (int i = 0; i < FRECUENCIA * ms / 1000; i += 256) parlante.write((uint8_t *)cero, sizeof(cero));
}

void conectarWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_NOMBRE, WIFI_CLAVE);
  Serial.print("Conectando a Wi-Fi");
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) { delay(250); Serial.print("."); }
  if (WiFi.status() == WL_CONNECTED) Serial.println(" listo: " + WiFi.localIP().toString());
  else Serial.println(" sin conexión");
}

// ------------------------------------------------------------ grabar
size_t grabar() {
  size_t usados = 0;
  uint8_t *audio = grabacion + CABECERA;
  while (digitalRead(PIN_BOTON) == LOW && usados < MAX_AUDIO) {
    size_t leidos = mic.readBytes((char *)(audio + usados), min((size_t)1024, MAX_AUDIO - usados));
    // subir el volumen del micrófono (es bajito)
    int16_t *m = (int16_t *)(audio + usados);
    for (size_t i = 0; i < leidos / 2; i++) {
      int32_t v = (int32_t)m[i] * GANANCIA_MIC;
      m[i] = constrain(v, -32768, 32767);
    }
    usados += leidos;
  }
  escribirCabeceraWav(grabacion, usados);
  return usados;
}

// ------------------------------------------------------------ preguntar al PC y reproducir
void preguntar(size_t bytesAudio) {
  conectarWifi();
  if (WiFi.status() != WL_CONNECTED) { tono(300, 400); return; }

  WiFiClientSecure cliente;
  cliente.setInsecure();  // el PC usa un certificado propio
  HTTPClient http;
  String url = String("https://") + PC_IP + ":" + PC_PUERTO + "/api/collar";
  http.begin(cliente, url);
  http.setTimeout(120000);
  http.addHeader("Content-Type", "audio/wav");
  http.addHeader("X-Asistente-Pin", ASISTENTE_PIN);

  int codigo = http.POST(grabacion, CABECERA + bytesAudio);
  if (codigo != 200) {
    Serial.printf("Error del PC: %d %s\n", codigo, http.errorToString(codigo).c_str());
    http.end(); tono(300, 400); return;
  }

  int largo = http.getSize();
  if (largo <= CABECERA) { http.end(); tono(300, 400); return; }
  uint8_t *respuesta = (uint8_t *)ps_malloc(largo);
  if (!respuesta) { http.end(); tono(300, 400); return; }
  WiFiClient *flujo = http.getStreamPtr();
  int recibidos = 0;
  unsigned long limite = millis() + 30000;
  while (recibidos < largo && millis() < limite) {
    int n = flujo->available();
    if (n > 0) recibidos += flujo->readBytes(respuesta + recibidos, min(n, largo - recibidos));
    else delay(2);
  }
  http.end();

  // volumen y reproducción
  int16_t *m = (int16_t *)(respuesta + CABECERA);
  int muestras = (recibidos - CABECERA) / 2;
  for (int i = 0; i < muestras; i++) m[i] = (int32_t)m[i] * VOLUMEN / 100;
  parlante.write(respuesta + CABECERA, muestras * 2);
  silencio(150);
  free(respuesta);
}

// ------------------------------------------------------------ inicio
void setup() {
  Serial.begin(115200);
  pinMode(PIN_BOTON, INPUT_PULLUP);

  grabacion = (uint8_t *)ps_malloc(CABECERA + MAX_AUDIO);
  if (!grabacion) { Serial.println("Sin PSRAM: activa Herramientas -> PSRAM -> OPI PSRAM"); while (true) delay(1000); }

  mic.setPinsPdmRx(MIC_CLK, MIC_DATA);  // el micrófono primero (usa el I2S 0)
  if (!mic.begin(I2S_MODE_PDM_RX, FRECUENCIA, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO)) Serial.println("Falla el micrófono");
  parlante.setPins(AMP_BCLK, AMP_LRC, AMP_DIN);
  if (!parlante.begin(I2S_MODE_STD, FRECUENCIA, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO)) Serial.println("Falla el parlante");

  conectarWifi();
  tono(880, 80); silencio(60); tono(1320, 80);  // "estoy lista"
}

void loop() {
  if (digitalRead(PIN_BOTON) == LOW) {
    delay(30);  // antirrebote
    if (digitalRead(PIN_BOTON) != LOW) return;
    tono(1000, 60);
    size_t bytes = grabar();
    tono(700, 60);
    if (bytes > FRECUENCIA / 2) preguntar(bytes);  // más de ~0,25 s de voz
    while (digitalRead(PIN_BOTON) == LOW) delay(10);
  }
  delay(10);
}
