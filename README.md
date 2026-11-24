# LEK — tu asistente personal de IA

Una asistente por voz tipo "Jarvis" que vive en tu PC. Le hablas desde el PC o el celular y te responde con voz. **Es gratis**: el cerebro es una IA que corre en tu propio computador (Ollama), sin pagar API.

- **Escoge su propio nombre** la primera vez que arranca y lo recuerda (le puedes pedir que se lo cambie).
- **Memoria:** "acuérdate de que mi entrega es el viernes".
- **Tus documentos:** responde con lo que haya en la carpeta `conocimiento/` (PDF, Word, txt).
- **Internet:** busca datos actuales (DuckDuckGo, gratis).
- **Tu PC:** abre programas (Revit, AutoCAD, Word…) y páginas web.
- **Notas:** "anota que tengo que comprar balso".
- **Manos libres:** di su nombre y te escucha.
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

- **En el PC:** se abre solo en el navegador (usa Chrome o Edge).
- **En el celular:** abre la dirección "En el celular" en Chrome, conectado a la misma Wi-Fi.
- **Aviso de "conexión no privada":** es normal, porque el certificado lo creó tu propio PC. Toca **Configuración avanzada → Continuar**. Hace falta HTTPS para que el celular deje usar el micrófono.
- **Firewall:** la primera vez Windows pregunta si permite Python en la red. Marca **Redes privadas → Permitir**.
- Toca el núcleo y habla, o escribe. Con **Manos libres** solo tienes que decir su nombre.

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

## Actualizar

Cuando haya cambios en GitHub, abre **`actualizar.bat`**. Tu memoria y tus notas no se tocan.

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
conocimiento/        tus documentos (privado)
datos/               su memoria, notas y nombre (privado, se crea solo)
collar/              firmware y guía del collar de IA
```
