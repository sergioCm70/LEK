# Memoria de LEK (fase 3, 26/11/2026)

## Capas

| Capa | Qué guarda | Dónde |
|---|---|---|
| Inmediata | Los últimos 21 mensajes de la conversación (sin lo descartado como ruido) | `servidor.responder` |
| Episódica | Todas las conversaciones, para siempre, y un resumen por día | tablas `mensajes` y `resumenes` |
| Semántica | Recuerdos organizados, con procedencia y vigencia | tabla `recuerdos` (`lek/memoria_capas.py`) |
| Procedimental | Habilidades aprobadas y vocabulario y correcciones de voz | `habilidades/`, `datos/vocabulario.json` |
| De trabajo | Pendientes, proyectos contextuales, tareas autónomas | `pendientes`, `proyectos_ctx` y `proyecto_items`, `lek/autonomia` |

## Recuerdos

Cada recuerdo tiene estos campos:
- **categoría:** preferencia, dato_personal, persona, decision, proyecto, procedimiento, compromiso, conocimiento o dato.
- **tipo de fuente:** confirmado (lo dijo Sergio), inferido, temporal, hipótesis o externo.
- **fuente:** `mensaje:ID` o el origen.
- **fechas:** de registro y de última actualización.
- **confianza:** 1,0 si lo confirmó Sergio; 0,5 si es inferido.
- **vigencia:** vigente, reemplazado, olvidado o expirado.
- **enlaces:** al recuerdo que reemplaza y al que lo reemplazó.
- **otros:** proyecto, clave y fecha de expiración.

Reglas verificadas con pruebas (`tests/test_memoria_capas.py`):
- **Contradicciones:** un dato con la misma `clave` reemplaza al anterior, que queda en el historial. Sin clave, Luna recibe un aviso de "se parece a…" para que use `actualizar_recuerdo` y no guarde dos versiones.
- **Lo inferido nunca aparece como hecho:** el prompt lo marca "inferido (no confirmado)".
- **Lo temporal expira solo** al pasar su fecha.
- **Olvidar:** invalida el recuerdo y borra sus vectores del índice semántico. Las conversaciones no se borran (regla de Sergio). Los respaldos anteriores conservan la versión previa hasta que rotan, a los 14 días.
- **Por qué recuerdo algo:** fecha, tipo, confianza, frase original de Sergio y versiones anteriores.

## Comandos (por voz o texto)

| Sergio dice | Herramienta |
|---|---|
| "¿Qué recuerdas de mí?" | `ver_memoria` (agrupado por categoría, solo lo vigente) |
| "Recuerda que…" | `recordar` |
| "Actualiza…", "ya no es así, ahora…" | `actualizar_recuerdo` |
| "¿Por qué recuerdas eso?" | `por_que_recuerdo` |
| "Olvida…" | `olvidar` |
| "Muéstrame los recuerdos de este proyecto" | `ver_memoria(proyecto=…)` |
| "Trabajemos en Las Delicias" | `trabajar_en` |

Interfaz: Módulos → Memoria (proyectos, recuerdos, ¿por qué?, olvidar, exportar).
API: `/api/memoria/recuerdos`, `/api/memoria/por_que`, `/api/memoria/olvidar`, `/api/memoria/actualizar`, `/api/memoria/exportar`, `/api/memoria/importar`.

## Proyectos contextuales

Cada proyecto guarda:
- nombre, descripción, objetivo y alias;
- items: decisiones (confirmadas), propuestas (NO confirmadas), restricciones, fechas, avances, problemas, archivos y notas.

Una propuesta solo pasa a ser decisión con `aprobar_propuesta`. Lo que cambia se marca "reemplazado" y queda en el historial.

Mientras un proyecto está activo:
- cada mensaje queda asociado a él (columna `mensajes.proyecto`);
- el cerebro recibe en cada turno un resumen corto, con lo confirmado separado de lo propuesto.

Si Sergio nombra un proyecto que no está activo, Luna sugiere activarlo.

## Recuperación

Los recuerdos se buscan por palabras clave, ponderadas por confianza y recencia, y por significado cuando el modelo de embeddings está instalado. Las conversaciones se buscan con FTS5 y embeddings (fusión por rango recíproco).

**No se implementó reranking:** con 12 GB de RAM al 90–97 %, un segundo modelo para reordenar resultados haría más lento cada turno, y la base de recuerdos todavía es pequeña.

## Privacidad

- La memoria (`privacidad.memoria`) y los proyectos (`privacidad.proyectos`) son **solo locales** por defecto.
- Con Claude como cerebro, ver un proyecto o la memoria hace que **ese turno lo termine el modelo local**.
- **Medido en el PC (26/11):** con la RAM al 97 %, qwen3:8b tardó 127 s en responder "trabajemos en Las Delicias".
- Si Sergio permite `proyectos = nube` (Inteligencia → Privacidad), el contexto del proyecto va a Claude y la respuesta tarda pocos segundos.

## Migración

Al arrancar, si a la tabla `recuerdos` le faltan las columnas nuevas, Luna:
1. crea un respaldo verificado `luna-completo-antes-de-migrar-memoria-*.zip`;
2. agrega las columnas (no borra ni cambia datos).

El código anterior sigue funcionando: `archivado = 1` sigue significando "no usar". Para revertir, se restaura ese respaldo con `restaurar.bat`. **Ejecutado en el PC el 26/11 a las 17:21:** la migración salió bien y el respaldo previo quedó guardado.
