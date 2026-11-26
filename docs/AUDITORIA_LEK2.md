# Auditoría LEK 2.0 — Fase 0

Fecha: 26 de noviembre de 2026. Versión auditada: commit `b3c1e18` (rama `main`).

Fuentes: el código del repositorio, las 338 pruebas automáticas y Luna corriendo en el PC de Sergio
(Windows, Python 3.15, 12 GB de RAM, RTX 3050 de 4 GB). En el PC se revisaron los endpoints
y los 92 mensajes guardados.

Cada hallazgo indica si se **verificó en el PC**, si se **verificó con pruebas** o si **solo se leyó en el código**.

---

## 1. Arquitectura actual

```
Navegador (PC: http://localhost:8090  ·  celular: https://IP:8443 o Tailscale)
        │  static/index.html (HUD, voz del navegador, paneles)
        ▼
servidor.py  (FastAPI, ~2.000 líneas: endpoints + herramientas + prompt + arranque)
   ├─ lek/cerebros/   gestor (cadena, salud, presupuesto) · enrutador · ollama · claude · catálogo
   ├─ lek/almacen.py  SQLite datos/luna.db (mensajes+FTS5, recuerdos, resúmenes, llamadas, auditoría)
   ├─ lek/memoria_semantica.py  embeddings locales (requiere nomic-embed-text: NO instalado)
   ├─ lek/autonomia/  objetivos → proyectos → tareas, programador en segundo plano
   ├─ lek/automejora/ análisis estático (ast) + ejecución en subproceso
   ├─ lek/analisis/   PDF, DOCX, XLSX/CSV, imágenes (cabecera), GLB, calculadora exacta
   ├─ lek/pc/         organizador de archivos (mueve con deshacer, nunca borra)
   ├─ lek/voz/        despertador (Vosk + Whisper), vocabulario y correcciones
   ├─ lek/notificaciones.py, monitor_pc.py, salud_corporal.py, evaluacion/
   └─ habilidades/    3 habilidades aprobadas (clima, dias_hasta, escala_maqueta)
```

## 2. Funcionalidades: qué está verificado y qué no

| Función | Estado | Cómo se verificó |
|---|---|---|
| Chat con Claude Haiku y respaldo local qwen3:8b | Funciona | En el PC: 29 llamadas, 100 % éxito, 3 s de media, 0,025 USD en el mes |
| Memoria permanente de conversaciones (SQLite + FTS) | Funciona | En el PC: 92 mensajes conservados desde la migración |
| Enrutador automático (simple/normal/compleja/privada) | Funciona en pruebas | Pruebas; en el PC solo se vieron pedidos "normal" |
| Privacidad (memoria/notas/documentos solo locales) | Funciona en pruebas | Pruebas con proveedores falsos |
| Memoria por significado | **Inactiva** | En el PC: falta `nomic-embed-text`; 92 mensajes pendientes |
| Escucha "Luna" en segundo plano | Funciona, con ruido | En el PC: activa; se disparó con TV/videos (mensajes 79–90) |
| Whisper | Instalado sin probar con voz real | En el PC: instalación por plan B (sin PyAV) |
| Proyectos persistentes | Sin uso real | Pruebas; 0 proyectos en el PC |
| Organizador de archivos | Sin uso real | Pruebas |
| Análisis de documentos | Sin uso real | Pruebas (54) |
| Habilidades en sandbox | Funciona en Linux | Pruebas en Linux; **en Windows solo hay límite de tiempo** |
| Pulso del Apple Watch | Sin probar | No hay iPhone confirmado |
| Acceso desde la calle (Tailscale) | **No instalado** | En el PC: no aparece Tailscale |
| Inicio automático con Windows | **No activo** | En el PC: Luna estaba apagada hoy; hubo que abrirla a mano |
| Collar | Sin probar | Sin hardware |

## 3. Hallazgos por severidad

### Crítico

| # | Hallazgo | Evidencia |
|---|---|---|
| C1 | **Sin PIN, cualquiera en la misma red Wi-Fi controla a Luna.** Puede chatear y leer notificaciones (con código), pulso y archivos. Además, por medio del chat, Luna puede **mover archivos** (`organizar_archivos`) y analizar Descargas, Escritorio y Documentos. | Verificado en el PC: "PIN: sin PIN". Código: `revisar_pin` solo exige PIN por Tailscale |
| C2 | **Ataques desde páginas web (CSRF / DNS rebinding).** Una página maliciosa abierta en el navegador del PC puede enviar POST a `localhost:8090` (organizar, deshacer, aprobar habilidades, apagar). Con un dominio que apunte a 127.0.0.1, también puede leer las respuestas. No se valida `Host` ni `Origin`. | Código: no hay middleware de origen ni de host |
| C3 | **PIN sin protección contra fuerza bruta.** Un PIN de 4 dígitos se prueba entero en minutos. Además, el PIN se guarda en texto plano en `.env` y en el `localStorage` del navegador. | Código: `revisar_pin`, `index.html` línea 568 |
| C4 | **La clave de Claude quedó expuesta** en el chat del 23 de noviembre. | Debe rotarla Sergio en platform.claude.com; no se puede arreglar desde aquí |

### Alto

| # | Hallazgo | Evidencia |
|---|---|---|
| A1 | **Luna afirma haber hecho cosas que no hizo.** Dijo "Dejé guardados los pendientes" (mensaje 74) y luego reconoció que no los guardó (mensaje 84). No existe una herramienta de pendientes ni se verifica lo que afirma. | Verificado en el PC |
| A2 | **El código que escribe Luna puede activarse sin aprobación humana** (modo autónomo). LEK 2.0 exige aprobación explícita y prohíbe la autoaprobación. | Código: `AUTOMEJORA_AUTONOMA` sí por defecto |
| A3 | **En Windows, el sandbox no aísla de verdad.** Es un subproceso con el mismo usuario, sin límite de memoria ni de procesos hijos, y con permiso para escribir en todos los archivos de Sergio. | Código: `sandbox.py` (los límites solo aplican en Linux) |
| A4 | **Inyección de instrucciones.** Lo que devuelve internet o un documento entra al contexto sin marca, y en el mismo turno Luna puede ejecutar acciones (mover archivos, abrir programas, crear habilidades). | Código: `responder` / `ejecutar_herramienta` |
| A5 | **Falsas activaciones de voz.** Se envían a Claude y quedan guardadas para siempre como si fueran de Sergio. | Verificado en el PC (mensajes 79–90). Mitigado el 24/11, sin medir |
| A6 | **No hay restauración ni verificación de respaldos.** Se hace una copia diaria de `luna.db`, pero no se comprueba su integridad, no hay forma de restaurarla y no se respaldan `vocabulario.json`, `config.json`, la identidad ni las notas en un solo paquete. | Código: `Almacen.respaldar` |
| A7 | **Luna no arranca con Windows.** | Verificado en el PC |

### Medio

| # | Hallazgo |
|---|---|
| M1 | Las acciones de las herramientas no quedan en la auditoría: solo `crear_habilidad` y `olvidar` se registran. |
| M2 | "Olvidar" archiva el recuerdo, pero no lo quita del índice de vectores. Los recuerdos no guardan procedencia, confianza, vigencia ni categoría (fase 3). |
| M3 | Solo hay presupuesto mensual: no hay tope diario ni aviso al 80 %. |
| M4 | `servidor.py` mezcla endpoints, herramientas, prompt y arranque en unas 2.000 líneas. Las herramientas se arman en varios lugares (`HERRAMIENTAS +=`). |
| M5 | `/api/inteligencia` ejecuta `nvidia-smi` en cada consulta, y la interfaz la consulta cada 20 s. |
| M6 | La memoria por significado está apagada porque falta el modelo de embeddings. Instalarlo cuesta RAM, que ya está al 90–97 % con Revit abierto. |
| M7 | No se analizan PPTX ni se hace OCR o visión de imágenes (fase 7). |
| M8 | Las respuestas no llegan por streaming: la interfaz espera la respuesta completa. |

### Bajo

| # | Hallazgo |
|---|---|
| B1 | La etiqueta `v0.5-prototipo` existe solo en local (el push falló). |
| B2 | GitHub avisa que el repositorio cambió de URL (`LEK-` → `LEK`); el remoto funciona igual. |
| B3 | Los documentos de integración de los agentes ya están en `docs/integracion/` y son históricos. |

## 4. Dependencias

No se encontraron dependencias innecesarias. Algunas son opcionales y su ausencia se tolera: numpy, psutil, openpyxl, Pillow, vosk, sounddevice y faster-whisper. Con Python 3.15, PyAV y onnxruntime no tienen paquetes para Windows: Whisper funciona sin ellos, pero sin el filtro de voz (VAD).

## 5. Plan priorizado

| Orden | Trabajo | Hallazgos | Fase LEK 2.0 |
|---|---|---|---|
| 1 | Seguridad de acceso: PIN obligatorio fuera del PC, PIN cifrado, sesiones que caducan, bloqueo por intentos, validación de Host y Origin, cabecera anti-CSRF | C1, C2, C3 | 1 |
| 2 | Aprobación humana obligatoria de habilidades y sandbox de Windows con Job Object y nivel de integridad bajo, con autoprueba en el PC | A2, A3 | 1 / 5 |
| 3 | Defensa contra inyección: datos externos marcados y acciones bloqueadas en turnos contaminados | A4 | 1 |
| 4 | Honestidad operativa: pendientes reales y verificación de acciones afirmadas sin herramienta | A1 | 1 |
| 5 | Respaldo completo verificable, restauración e inicio con Windows | A6, A7 | 1 |
| 6 | Auditoría de cada herramienta, tope diario y aviso del 80 % | M1, M3, M5 | 1 |
| 7 | Separar el núcleo de `servidor.py` en módulos (registro de herramientas con permisos) | M4 | 2 |
| 8 | Memoria por capas: vigencia, procedencia, contradicciones, proyectos contextuales y olvido con índices | M2, M6 | 3 |
| 9 | Autonomía en 5 niveles, permisos por herramienta y carpeta, panel de actividad | — | 4 |
| 10 | Multimodal (PPTX, OCR, visión), streaming, investigación con fuentes | M7, M8 | 6 / 7 |

El avance real de cada fase se registra en `docs/ESTADO_CONTINUIDAD.md`.
