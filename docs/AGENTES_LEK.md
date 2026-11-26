# Agentes de LEK (fase 2, 26/11/2026)

## Principio

LEK 2.0 pide agentes especializados que colaboren, **sin** volverse una colección de asistentes redundantes que agreguen latencia. En este PC (12 GB de RAM, casi siempre al 90–97 %) cada agente que corre en paralelo con un modelo propio cuesta segundos y memoria. Por eso:

- **Luna es el agente principal y el único que conversa.** Los demás son **herramientas con un procedimiento propio**: Luna los llama, ellos trabajan y le devuelven un resultado estructurado.
- Un agente se crea solo cuando un trabajo tiene varios pasos que conviene encapsular y probar. Si una herramienta simple basta, se usa la herramienta.
- Solo corre en paralelo lo independiente (por ejemplo, leer varias páginas a la vez).
- Todo lo que hace un agente aparece en **Actividad** (Módulos → Actividad, `/api/actividad`).

## Agentes que existen hoy

| Agente | Qué hace | Dónde | Estado |
|---|---|---|---|
| Principal | Entiende a Sergio, elige el modelo (enrutador), usa herramientas, controla la privacidad y las afirmaciones | `servidor.responder` | En uso |
| Investigador | Divide la pregunta en subtemas, busca, lee páginas públicas en paralelo y sintetiza con fuentes [n], fechas y contradicciones | `lek/nucleo/investigador.py`, herramienta `investigar` | Probado con pruebas; ver resultado en el PC en `ESTADO_CONTINUIDAD.md` |
| Archivos | Analiza (PDF, Excel, GLB…) y organiza Descargas y Escritorio con deshacer | `lek/analisis`, `lek/pc/organizador.py` | En uso (herramientas) |
| Proyectos y planificación | Convierte objetivos en planes con tareas y dependencias; ejecuta los niveles 0 y 1 cuando el PC está libre | `lek/autonomia` | En uso |
| Memoria | Recuerdos por capas, reemplazos, proyectos contextuales | `lek/memoria_capas.py`, `lek/proyectos_contexto.py` | En uso |
| Diagnóstico | Estado del PC, del sandbox, de los modelos y de los respaldos | `diagnostico`, `/api/diagnostico/sandbox`, `monitor_pc` | En uso |
| Programación | Escribe habilidades que se prueban aisladas y esperan aprobación | `crear_habilidad`, `lek/automejora` | En uso |

## Seguridad del investigador

- Solo lee URL `http(s)` que resuelven a IP públicas. Nunca la red de la casa, Tailscale ni `localhost`, para que una página no pueda hacer que Luna lea su propia API (SSRF). Tampoco sigue redirecciones ni descarga más de 400 KB.
- Su resultado se marca como **datos externos**. En ese turno Luna no puede ejecutar herramientas con efectos.
- La síntesis se pide "solo con las fuentes", ignorando las instrucciones que traigan.

## Registro de herramientas

Desde la fase 2, cada herramienta tiene una ficha única en `lek/nucleo/registro.py` con estos datos: esquema de entrada, función, privacidad, si es externa, si tiene efectos, nivel de autorización y categoría.

- El registro valida los argumentos antes de ejecutar (requeridos y tipos; ignora los campos que el modelo invente).
- Hay una prueba que exige que cada definición tenga su función, y al revés.
- La lista completa se ve en `/api/herramientas`.
