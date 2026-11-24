# Hoja de ruta de LEK

LUNA es la inteligencia que acompaña a Sergio y dirige el desarrollo. LEK es la tecnología que va saliendo de las capacidades, experimentos y mejoras de LUNA.

Reglas para construir LEK:
- Cada etapa debe dar una capacidad **verificable**, con una prueba que la demuestre.
- La arquitectura es modular: cada capacidad es una habilidad o un módulo aparte, con documentación.
- Antes de cambiar algo se guarda la versión anterior y debe poderse revertir.
- No se pasa a una etapa si su dependencia no funciona.
- Todo corre en el PC y gratis, salvo que Sergio autorice otra cosa.

Prioridad: **A** = alto impacto y pronto · **B** = intermedio · **C** = investigación avanzada.

---

## Etapa 0 — Núcleo de LUNA (funciona; parte sin verificar en el PC)
- Voz en el navegador del PC y del celular, IA local con Ollama (qwen3:8b).
- Memoria permanente, documentos (carpeta `conocimiento`), búsqueda en internet, notas, abrir programas.
- **Habilidades**: LUNA escribe código nuevo para sí misma y Sergio lo aprueba con un botón.
- **Propuestas de mejora** con el formato de 8 puntos y clasificación por impacto y dificultad.
- Autodiagnóstico y revisión diaria por iniciativa propia.

**Verificación:** responde por voz desde el celular, recuerda un dato después de reiniciar y crea una habilidad que funciona después de aprobarla.

Estado real (auditoría del 24 de noviembre de 2026): verificado en el PC el cerebro local con herramientas, las habilidades de ejemplo, la revisión diaria y la voz en el navegador. Sin verificar todavía: acceso desde el celular, crear y aprobar habilidades en el PC y Claude como cerebro.

## Plan maestro, fases 0 y 1 (en curso desde el 24 de noviembre de 2026)
- Almacén SQLite (`datos/luna.db`): todas las conversaciones se guardan para siempre, con búsqueda y resúmenes diarios; olvidar archiva y no borra; respaldo diario.
- Cerebros intercambiables (`lek/cerebros`): interfaz común, catálogo, salud con reintentos y pausa, respaldo local automático, métricas por llamada.
- Privacidad: memoria, notas y documentos solo en el PC; a la nube solo la conversación.
- Panel de Inteligencia en la interfaz.
- Siguiente: evaluar OpenJarvis y traer solo lo útil (detección de hardware, selección de modelos, habilidades del estándar agentskills.io), sin su personalidad.

## Etapa 1 — Cimientos confiables (A)
- Medir: tiempo de respuesta, herramientas que fallan, habilidades rechazadas.
- Pruebas automáticas para cada habilidad antes de aprobarla (ejecutarla con un ejemplo en un entorno aislado).
- Historial de versiones de habilidades con botón "volver a la versión anterior".
- PIN obligatorio para todo lo que sea nivel 2.

**Depende de:** Etapa 0.
**Verificación:** un informe semanal de rendimiento, y una habilidad con errores que queda bloqueada sola antes de llegar a Sergio.

## Etapa 2 — Memoria útil y organizada (A)
- Memoria por proyectos (entrega final, maqueta, Taller 4…) en vez de una sola lista.
- Búsqueda por significado en documentos usando embeddings locales (por ejemplo `nomic-embed-text` en Ollama), en vez de solo palabras clave.
- Pantalla para que Sergio vea, corrija y borre lo que LUNA recuerda.

**Depende de:** Etapa 1.
**Verificación:** 20 preguntas sobre sus documentos, con al menos 17 respondidas bien con la fuente correcta.

## Etapa 3 — Gestión inteligente del PC (A/B)
- Buscar archivos por nombre o contenido, sugerir orden de carpetas (mover solo con permiso).
- Recordatorios y alarmas con aviso en el PC y el celular.
- Consultar recursos del sistema y procesos, y vigilar tareas largas (renders, descargas).
- Generar documentos (actas, listas de chequeo de entregas).

**Depende de:** Etapa 1 (permisos y PIN).
**Verificación:** "encuentra el último .rvt de LEK y dime cuánto pesa", y un recordatorio que suena a la hora exacta.

## Etapa 4 — Voz y presencia (B)
- Palabra de activación local, sin navegador (openWakeWord).
- Oído local con Whisper en el PC y voz neural local (Piper), más natural que la de Windows.
- Collar de IA (firmware ya listo en `collar/`).

**Depende de:** Etapa 0.
**Verificación:** conversación de 5 turnos solo con el collar, con respuesta en menos de 6 segundos.

## Etapa 5 — Visión y arquitectura (B/C)
- Ver la pantalla o una imagen con un modelo multimodal local (por ejemplo `qwen2.5vl`) para comentar planos y renders.
- Conectarse a Revit (pyRevit / Revit API) para consultar áreas, niveles y elementos del modelo.

**Depende de:** Etapas 1 y 3.
**Verificación:** a partir de una planta exportada de Revit, lista los espacios y sus áreas con un error menor al 5 %.

## Etapa 6 — Arquitectura multiagente (C)
- LUNA como orquestadora, con agentes especializados: investigadora, programadora de habilidades, organizadora del PC.
- Modelo en la nube opcional para tareas pesadas, solo con autorización.

**Depende de:** Etapas 1, 2 y 3.
**Verificación:** una tarea compleja ("prepara la lista de entrega del viernes con lo que falta") resuelta mejor que con un solo agente, medida con la misma prueba.

## Etapa 7 — Aprendizaje y autoevaluación (C)
- Reflexión diaria sobre errores, con la lección guardada como memoria de método.
- Ajuste fino (LoRA) del modelo **solo** si hay suficientes ejemplos buenos y la etapa 2 no alcanza.

**Depende de:** todas las anteriores.
**Verificación:** menos errores repetidos mes a mes, según los informes de la etapa 1.

---

## Descartado por ahora
- Ajuste fino temprano: cuesta mucho y la memoria más los documentos dan casi lo mismo.
- Control total del PC sin permisos: va contra el nivel 3.
- Servicios de pago: no por ahora, salvo que Sergio lo autorice.

## Bitácora
LUNA anota los avances verificados de LEK (fecha, qué se logró y cómo se comprobó) en `datos/bitacora_lek.md`.
