# Registro de cambios

## 2026-11-26 — LEK 2.0, fase 6 (respuestas en vivo e interrupción)

- **Respuestas en vivo:** `POST /api/chat/vivo` transmite el texto mientras Claude u Ollama lo escriben (NDJSON), junto con los pasos ("Usando buscar_internet…"). La interfaz lo muestra en una burbuja que se va llenando; si el servidor no tiene la ruta nueva, usa `/api/chat` como antes.
- **Interrumpir:** botón ■ (o tecla Esc) mientras Luna responde → `POST /api/cancelar`. Se detiene entre rondas y antes de cada herramienta; lo que ya hizo queda hecho y la conversación queda guardada con la nota "Me detuve porque me lo pediste".
- **Sin texto fantasma:** si un cerebro falla a mitad de la respuesta y entra el de respaldo, o si la respuesta se corrige (control de afirmaciones), el cliente recibe "reinicio" y se borra lo escrito a medias.
- **Solo la respuesta al usuario se transmite:** los prompts internos (investigador, resúmenes) nunca salen en vivo.
- **"Luna, para":** con la escucha en segundo plano, decir "Luna, para" (o detente, cállate, silencio, basta) mientras piensa o habla detiene el pedido y corta el audio. Usa una gramática cerrada de Vosk y exige el nombre primero, para que la TV no la corte. En la ventana, Esc también calla la voz.
- **Herramienta de desarrollo:** `scripts/generar_api_doc.py` regenera `docs/API_LEK.md` (65 rutas).
- **Pruebas:** 407 → 421.

## 2026-11-26 — LEK 2.0, fase 7 (multimodal, base)

- **PowerPoint:** `analizar_archivo` lee .pptx: diapositivas en orden, títulos, texto, notas e imágenes incrustadas.
- **IFC (BIM exportado desde Revit):** proyecto, niveles con su cota, cantidad de muros, losas, puertas, ventanas, columnas, etc., y espacios con su área cuando el IFC trae cantidades base. Solo lectura. Si el archivo no trae áreas, lo dice y explica cómo exportarlas.
- **OCR sin internet:** herramienta nueva `leer_texto_imagen`, que usa el OCR que trae Windows (Windows.Media.Ocr). Su resultado es privado (clase documentos) y externo (no puede disparar acciones en el mismo turno).
- **Sin librerías nuevas:** todo funciona con la biblioteca estándar de Python y PowerShell.
- **Ajustes → Sistema (nuevo):** arranque con Windows, estado de respaldos, **Crear respaldo** (verificado) y **Diagnóstico del sandbox**. Los endpoints ya existían; faltaban los botones.
- **Documentación:** `docs/INTEGRACION_REVIT.md` (opciones para leer Revit sin modificarlo) y `docs/INSTALACION.md`.
- **Pruebas:** 403 → 407.

## 2026-11-26 — LEK 2.0, fase 4 (autonomía por niveles)

- **Niveles y permisos:** 5 niveles configurables (Ajustes → Autonomía) y reglas por herramienta: permitir, preguntar o bloquear.
- **Aprobaciones:** las acciones que no puede hacer sola quedan como aprobación de un solo uso, con caducidad de 24 h, notificación y sección propia en Tareas autónomas.
- **Revisión diaria:** corre en modo autónomo; lo que actúa sobre el PC pide aprobación.
- **Investigador:** el enrutador decide por la pregunta y no por el prompt interno. En el PC se vio que la división en subtemas usaba Opus sin necesidad.
- **Pruebas:** 397 → 403.

## 2026-11-26 — LEK 2.0, fase 2 (núcleo)

- **Registro único de herramientas** (`lek/nucleo/registro.py`): esquema, validación, privacidad, externa, efectos, nivel y categoría; endpoint `/api/herramientas`.
- **Actividad en vivo** (`lek/nucleo/actividad.py`): turno, cerebro, herramientas, agentes y tareas de fondo; `/api/actividad`. En la interfaz, el estado muestra lo que está haciendo Luna ("Usando…", "Investigador: …") y hay un cajón Actividad nuevo.
- **Agente investigador** (`investigar`): subtemas, búsqueda, lectura de páginas en paralelo y síntesis con fuentes; protección contra SSRF.
- **Documentación:** `docs/AGENTES_LEK.md` y `docs/API_LEK.md` (generado desde el código, 59 rutas).
- **Pruebas:** 387 → 397.

## 2026-11-26 — LEK 2.0, fase 3 (memoria por capas y proyectos contextuales)

- **Recuerdos:** categoría, tipo de fuente, confianza, vigencia, reemplazos con historial y expiración de los temporales.
- **Comandos de memoria:** `actualizar_recuerdo`, `por_que_recuerdo`, y `olvidar`, que ahora también limpia el índice de vectores.
- **Proyectos contextuales:** `trabajar_en`, `crear_proyecto`, `anotar_en_proyecto`, `aprobar_propuesta`, `ver_proyecto` y `salir_de_proyecto`; mensajes asociados al proyecto y detección cuando se nombra uno.
- **Contexto de cada turno:** el proyecto activo (con lo confirmado separado de lo propuesto) y los recuerdos relacionados.
- **Privacidad:** nueva clase `proyectos`, solo local por defecto.
- **Interfaz y API:** cajón Memoria (proyectos, recuerdos, ¿por qué?, olvidar, exportar); endpoints `/api/memoria/*` y `/api/contexto/*`.
- **Migración:** solo agrega columnas, con un respaldo verificado antes. Se ejecutó en el PC.
- **Error encontrado en el PC y corregido:** al crear un proyecto nuevo con `trabajar_en`, no quedaba activo.
- **Pruebas:** 369 → 387.

## 2026-11-26 — LEK 2.0, fases 0 y 1 (auditoría y estabilización)

**Por qué:** la auditoría (`docs/AUDITORIA_LEK2.md`) encontró 4 problemas críticos y 7 altos.

**Seguridad de acceso (C1–C3)**
- PIN obligatorio para cualquier dispositivo que no sea el PC. Sin PIN, solo responde el PC.
- PIN cifrado (PBKDF2), sesiones de 30 días, bloqueo progresivo por intentos y bloqueo global.
- Validación de Host (contra DNS rebinding) y de Origin/Sec-Fetch-Site (contra CSRF), más cabeceras de seguridad.
- Ajustes → Seguridad: poner o cambiar el PIN y cerrar todas las sesiones.

**Habilidades (A2, A3)**
- Aprobación humana obligatoria por defecto (`LUNA_AUTOMEJORA_AUTONOMA=no`).
- Ficha de cada propuesta: archivo, dependencias, permisos, riesgo y pruebas.
- Sandbox de Windows: integridad baja + Job Object, con autoprueba al arrancar. Verificado en el PC: las 4 barreras funcionan.

**Inyección y honestidad (A4, A1)**
- Datos externos marcados; acciones bloqueadas en los turnos contaminados.
- Control de afirmaciones sin herramienta.
- Herramientas `anotar_pendiente`, `ver_pendientes` y `cerrar_pendiente`.

**Datos y continuidad (A6, A7, A5)**
- Respaldo zip completo y verificado cada día, endpoints de respaldo y `restaurar.bat`.
- Arranque con Windows (opción `sistema.iniciar_con_windows`, activada porque Sergio lo pidió).
- Lo que la escucha descarta como ruido queda guardado, pero fuera del contexto.

**Otros (M1, M3, M5)**
- Auditoría de cada herramienta.
- Tope de gasto diario (0,5 USD) y aviso al 80 % del mes.
- Caché de 10 s para las mediciones del PC (`nvidia-smi`).
- Tiempo de espera de Claude reducido de 120 s a 90 s, con 10 s para conectar.

**Pruebas:** 338 → 369, todas pasan.

## 2026-11-24 — Voz y fase 2

- Subtítulos en vivo, Whisper con vocabulario, correcciones aprendidas, nota de interpretación y filtro de ruido.
- Enrutador, memoria por significado, automejora en sandbox, proyectos, organizador, análisis, voz en segundo plano, pulso, monitor, evaluación e interfaz HUD.

## 2026-11-23 — Base

- Luna con FastAPI, Claude más Ollama, memoria permanente en SQLite, Tailscale y PIN fuera de casa.
