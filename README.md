# LEK — tu asistente personal de IA

Una asistente por voz tipo "Jarvis" que vive en tu PC. Le hablas desde el PC o el celular y te responde con voz. **Es gratis**: el cerebro es una IA que corre en tu propio computador (Ollama), sin pagar API.

- **Escoge su propio nombre** la primera vez que arranca y lo recuerda (le puedes pedir que se lo cambie).
- **Memoria:** "acuérdate de que mi entrega es el viernes".
- **Tus documentos:** responde con lo que haya en la carpeta `conocimiento/` (PDF, Word, txt).
- **Internet:** busca datos actuales (DuckDuckGo, gratis).
- **Tu PC:** abre programas (Revit, AutoCAD, Word…) y páginas web.
- **Notas:** "anota que tengo que comprar balso".
- **Manos libres:** di su nombre y te escucha.
- **Se mejora sola (LEK):** cuando le falta algo, ella misma escribe una habilidad nueva; tú la apruebas con un botón.
- **Collar de IA** opcional: un dije con micrófono y parlante ([collar/COLLAR.md](collar/COLLAR.md)).

---

## Instalación (Windows, una sola vez)

1. **Python 3.11 o más nuevo:** https://www.python.org/downloads/
   Al instalarlo, marca la casilla **"Add python.exe to PATH"**.
2. **Ollama**, el cerebro: https://ollama.com/download
3. **Git** (para descargar y actualizar el código): https://git-scm.com/download/win
4. Abre una terminal (tecla Windows, escribe `cmd`) y ejecuta:
   ```
   cd %USERPROFILE%\Documents
   git clone https://github.com/sergioCm70/LEK.git
   ```
   Si no quieres instalar Git, en GitHub usa el botón verde **Code → Download ZIP** y descomprímelo.
5. Entra a la carpeta `LEK` y abre **`instalar.bat`**. Él instala lo que falte (Python y Ollama, con winget) y descarga el cerebro (varios GB, puede tardar).
6. Abre el archivo **`.env`** con el Bloc de notas y ponle un **PIN**.

> **¿Tu PC es justo de RAM?** `qwen3:8b` necesita unos 8 GB libres. Si va lento, cambia en `.env` a `ASISTENTE_MODELO=qwen3:4b` y ejecuta `ollama pull qwen3:4b`.

## Usarla

Abre **`iniciar.bat`**. La primera vez verás algo así:

```
  AURORA en línea  (cerebro: qwen3:8b, gratis y local)
  En este PC:    https://localhost:8443
  En el celular: https://192.168.1.50:8443   (misma Wi-Fi)
```

- **En el PC:** se abre sola en su propia ventana (`http://localhost:8090`), ya escuchando: di **"Luna…"** y lo que necesitas. La primera vez dale **Permitir** al micrófono; queda recordado.
- **En el celular:** abre la dirección "En el celular" en Chrome, conectado a la misma Wi-Fi.
- **Aviso de "conexión no privada":** es normal, porque el certificado lo creó tu propio PC. Toca **Configuración avanzada → Continuar**. Hace falta HTTPS para que el celular deje usar el micrófono.
- **Firewall:** la primera vez Windows pregunta si permite Python en la red. Marca **Redes privadas → Permitir**.
- Toca el núcleo y habla, o escribe. Con **Manos libres** solo tienes que decir su nombre.

## Cerebro: Claude (rápido e inteligente) o local (gratis)

Por defecto Luna piensa con un modelo local, gratis pero lento en PCs sin tarjeta gráfica potente. Para que responda en pocos segundos y mucho mejor, usa a **Claude** como cerebro:

1. Crea una cuenta en https://platform.claude.com. Las cuentas nuevas traen créditos de prueba; después se recarga con tarjeta, desde 5 dólares.
2. En **API Keys** crea una clave y cópiala.
3. En la pantalla de Luna toca **Ajustes**, pega la clave, escoge el modelo y dale **Guardar**. Luna la prueba antes de guardarla.

| Modelo | Para qué | Costo aproximado por pregunta |
|---|---|---|
| Haiku 5.5 (recomendado) | Rapidísima, para el día a día | ≈ 0,001 dólares (unas mil preguntas por 1 dólar) |
| Sonnet 5.5 | Mucho más inteligente | ≈ 0,02 dólares |
| Opus 5.5 | La más inteligente | ≈ 0,04 dólares |

En **Ajustes** ves cuánto llevas gastado. Si Claude falla (sin internet o sin saldo), Luna sigue con el cerebro local. En la consola de Claude puedes ponerle un límite de gasto mensual.

## Voz

En **Ajustes → Voz** escoges la voz, la velocidad y el tono, y la pruebas antes de usarla. En Edge, las voces **Natural** (por ejemplo, Salomé de Colombia o Dalia de México) son las más humanas.

## Que arranque sola al prender el PC

Abre **`inicio_automatico.bat`** una vez. Desde entonces, al prender el PC Luna arranca minimizada, abre su ventana y saluda: "Estoy lista. Di Luna cuando me necesites". Para quitarlo, borra `Luna.bat` de la carpeta de Inicio de Windows (`Win + R` → `shell:startup`).

Ojo: la escucha por voz del navegador usa el servicio de reconocimiento de Microsoft o Google, así que lo que se oye mientras escucha pasa por ellos. Si no la quieres escuchando, desmarca **Manos libres**.

## Enseñarle cosas

| Quieres… | Haz esto |
|---|---|
| Que sepa de tus documentos | Ponlos en la carpeta `conocimiento/` |
| Que recuerde algo para siempre | Dile "acuérdate de que…" |
| Que olvide algo | Dile "olvida lo de…" |
| Que abra un programa nuevo | Agrégalo en `programas.json` (nombre y ruta del .exe) |
| Que te llame de otra forma | `ASISTENTE_LLAMARME` en `.env` |
| Ponerle tú el nombre (ej. LEK) | `ASISTENTE_NOMBRE=LEK` en `.env` |

Tus datos personales (memoria, notas, nombre que eligió, certificados) quedan en la carpeta `datos/`, y tus documentos en `conocimiento/`. **Ninguna de las dos se sube a GitHub**, igual que el archivo `.env`.

## Quién es Luna

Su identidad completa está en [`luna/MANUAL_LUNA.md`](luna/MANUAL_LUNA.md): misión, iniciativa, automejora, niveles de autorización y desarrollo de LEK. En cada conversación lleva una versión condensada, para seguir rápida, y consulta el manual completo cuando lo necesita.

- **Propuestas de mejora** con los 8 puntos del manual (problema, oportunidad, solución, recursos, implementación, riesgos, resultado y verificación), clasificadas por impacto y dificultad.
- **Revisión diaria por iniciativa propia:** 3 minutos después de iniciar, una vez al día, revisa su estado y las últimas conversaciones y, si encuentra algo valioso, registra una propuesta. Nunca cambia nada sola.
- **Autodiagnóstico:** "Luna, haz un diagnóstico" te dice RAM, disco, velocidad, fallos y habilidades.
- **Tu información:** "¿qué recuerdas de mí?" te muestra todo; "olvida lo de…" lo borra.
- **Hoja de ruta de LEK:** [`luna/HOJA_DE_RUTA_LEK.md`](luna/HOJA_DE_RUTA_LEK.md). Los avances verificados quedan en `datos/bitacora_lek.md`.

## LEK: Luna se mejora sola

Pídele algo que todavía no sepa hacer ("crea una habilidad para convertir pulgadas a centímetros"), o deja que ella lo note sola. Entonces:

1. Ella **escribe la habilidad** en Python y la deja **esperando tu aprobación**.
2. Toca **Habilidades** (abajo en la pantalla), lee qué hace y, si quieres, el código.
3. Toca **Aprobar** y desde ese momento ella la usa. Puedes **Desactivar** cualquiera cuando quieras.

Si una habilidad borra archivos, ejecuta programas o toca tus ajustes, aparece un aviso ⚠. No apruebes nada que no entiendas: el código aprobado corre en tu PC.

Por seguridad, sin PIN solo se puede aprobar desde el mismo PC, no desde el celular.

Sus propuestas de mejora más grandes aparecen en esa misma pantalla, para programarlas después.

Ya trae tres habilidades: **escala de maqueta** ("¿cuánto miden 12 metros a escala 1:100?"), **clima** y **días que faltan** para una fecha.

## Actualizar

Cuando haya cambios en GitHub, abre **`actualizar.bat`**. La primera vez instala Git y conecta la carpeta con GitHub. Tu memoria, tus conversaciones y tus notas (carpeta `datos/`) no se tocan.

## PIN

Abre **`cambiar_pin.bat`**, escribe el PIN y vuelve a abrir `iniciar.bat`. La ventana de Luna y el celular lo piden una sola vez.

## Usarla fuera de casa (opcional)

Instala **Tailscale** (gratis) en el PC y en el celular, con la misma cuenta. En el celular abre `https://NOMBRE-DE-TU-PC:8443` (el nombre aparece en la app de Tailscale). Funciona desde cualquier red mientras el PC esté prendido con el asistente abierto.

## Problemas comunes

- **"No encuentro Ollama":** abre Ollama (queda en la barra de tareas) y vuelve a iniciar.
- **No me escucha en el celular:** usa Chrome y acepta el permiso del micrófono. Safari en iPhone a veces falla con el reconocimiento de voz; ahí puedes escribir.
- **El celular no abre la página:** revisa que esté en la misma Wi-Fi y que el firewall permita Python.
- **Responde lento:** usa el modelo `qwen3:4b`. Si tienes tarjeta gráfica NVIDIA, Ollama la usa sola.

## Archivos

```
servidor.py          el cerebro: conversación, herramientas, memoria
static/index.html    la cara: núcleo, voz y chat
programas.json       programas que puede abrir
habilidades/         habilidades aprobadas (propuestas/ esperan, versiones/ son respaldos)
luna/                su manual de identidad y la hoja de ruta de LEK
conocimiento/        tus documentos (privado)
datos/               su memoria, notas y nombre (privado, se crea solo)
collar/              firmware y guía del collar de IA
```
