# Collar de IA

Un dije con micrófono y parlante. Mantienes presionado el botón, hablas y lo sueltas. El collar manda tu voz al PC, tu asistente piensa y te responde por el parlante. Todo pasa por tu PC, así que sigue siendo **gratis**.

```
[collar] --voz (Wi-Fi)--> [tu PC: Whisper entiende -> Ollama piensa -> voz de Windows] --respuesta--> [collar]
```

## Piezas

| Pieza | Para qué |
|---|---|
| Seeed **XIAO ESP32S3 Sense** | Cerebro del collar, trae micrófono y Wi-Fi |
| Amplificador **MAX98357A** | Mueve el parlante |
| Parlante pequeño 8 Ω, 0,5–1 W (20–28 mm) | La voz |
| Pulsador pequeño (6×6 mm) | Hablar |
| Batería LiPo 3,7 V, 400–600 mAh (con conector o cables) | Energía |
| Interruptor deslizante mini (opcional) | Apagarlo sin desconectar |
| Cables delgados, estaño, cordón o cadena | — |

## Conexiones

| XIAO ESP32S3 | Va a |
|---|---|
| D0 | Botón (la otra pata del botón a GND) |
| D8 | MAX98357A **BCLK** |
| D9 | MAX98357A **LRC** |
| D10 | MAX98357A **DIN** |
| 3V3 | MAX98357A **VIN** |
| GND | MAX98357A **GND** |
| — | Parlante a **+** y **−** del MAX98357A |
| BAT+ / BAT− (pads de abajo) | Batería (+ rojo, − negro). Si usas interruptor, va en el cable rojo |

El micrófono ya viene en la placa de expansión Sense, así que no hay que conectarle nada. La batería se carga sola cuando conectas el USB-C.

## Programarlo

1. Instala **Arduino IDE 2**. En *Preferencias → URLs adicionales* pega:
   `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
2. En *Gestor de placas*, instala **esp32** (de Espressif), versión **3.x**.
3. Abre `collar/collar/collar.ino`.
4. En esa misma carpeta copia `config.ejemplo.h` como **`config.h`** y llena tu Wi-Fi, la IP del PC (la que muestra la ventana del asistente) y tu PIN.
5. *Herramientas*: placa **XIAO_ESP32S3** y **PSRAM: "OPI PSRAM"** (si no, no funciona).
6. Conecta por USB-C y dale **Subir**.

## En el PC

- Abre **`instalar_collar.bat`** (instala Whisper, el oído del collar).
- La primera vez que hables, el PC descarga el modelo de Whisper (unos 500 MB con `small`).
- La voz usa las voces de Windows. Para que suene en español: *Configuración → Hora e idioma → Voz → Agregar voces* → Español (México o España).
- El PC y el collar deben estar en la misma Wi-Fi. Para usarlo fuera de casa, mira la sección Tailscale del README (el collar necesitaría un hotspot de tu celular).

## Cómo se usa

- Al prenderse hace dos pitidos: está lista.
- Mantén presionado el botón: **pip** agudo. Habla (hasta 10 s) y suelta: **pip** grave.
- Unos segundos después te responde. Un pitido grave y largo significa que no logró hablar con el PC (revisa que el asistente esté abierto y la IP en `config.h`).

## Batería

Con 500 mAh dura unas **3 a 5 horas** encendido y conectado al Wi-Fi. Si la quieres más larga, se puede agregar modo de bajo consumo para que se despierte con el botón.

## Carcasa para imprimir en 3D

Medidas internas mínimas sugeridas: **46 × 36 × 15 mm**.

- XIAO + Sense: 21 × 17,8 × 15 mm (deja el USB-C accesible en un borde).
- MAX98357A: 18 × 18 mm, apilado o al lado.
- Parlante de 28 mm: al frente, con rejilla de agujeros de 1,5 mm.
- Batería: al fondo, plana.
- Micrófono: un agujero de 1 mm justo encima del micrófono de la placa Sense.
- Botón: a un costado, donde caiga el pulgar.
- Argolla arriba para el cordón.

PLA o PETG con paredes de 1,6 mm. Tapa a presión o con 2 tornillos M2.
