# Autonomía de LEK (fase 4, 26/11/2026)

## Niveles

El nivel se configura en Ajustes → Autonomía (`/api/autonomia`). Por defecto es el 2.

| Nivel | Nombre | En la conversación (Sergio lo pide) | Por iniciativa propia (revisión diaria, tareas de fondo) |
|---|---|---|---|
| 0 | Consulta | Solo herramientas de consulta | Nada que cambie algo |
| 1 | Preparación | Anota (memoria, notas, pendientes, proyectos); lo que actúa sobre el PC pide aprobación | Anota y prepara |
| 2 | Ejecución aprobada | Hace lo que se le pide | Anota y prepara; lo que actúa sobre el PC pide aprobación |
| 3 | Autonomía limitada | Hace lo que se le pide | Además usa las herramientas marcadas "permitir" |
| 4 | Autonomía supervisada | Hace lo que se le pide | Igual que 3; todo queda en Actividad y auditoría y se puede revocar |

**Nivel de cada herramienta** (lo da su ficha en el registro, ver `/api/herramientas`):
- 0 = consulta.
- 1 = cambia algo dentro de Luna (memoria, notas, pendientes, proyectos, vocabulario).
- 2 = actúa sobre el PC o el mundo: mover archivos, deshacer, abrir programas o webs, crear habilidades.

**Reglas por herramienta** (`datos/permisos.json`):
- `bloquear`: nunca, gana siempre.
- `preguntar`: siempre pide aprobación, incluso en la conversación.
- `permitir`: permitida por iniciativa propia en los niveles 3 y 4.

**Revocar** es bajar el nivel, o poner `bloquear` o `normal` en una herramienta. El cambio aplica desde la siguiente acción.

## Aprobaciones

- Cuando una acción necesita permiso, **no se ejecuta**. Queda guardada en `aprobaciones_herramienta` con su herramienta, sus argumentos y el motivo, y llega una notificación.
- A Luna se le indica que NO diga que ya lo hizo (el control de afirmaciones de la fase 1 también lo vigila).
- Se aprueba o rechaza en Módulos → Tareas autónomas → "Acciones que esperan tu permiso" (`/api/aprobaciones_herramientas/{id}/aprobar`).
- Aprobar ejecuta la acción **una sola vez**. El resultado llega como notificación y queda en la auditoría. Las aprobaciones pendientes caducan a las 24 h.
- Aprobar o cambiar los permisos solo se puede desde el PC o con PIN.

## Tareas autónomas

Los objetivos, proyectos y tareas (`lek/autonomia/proyectos.py`) avanzan cuando el PC está libre: RAM por debajo del 85 % y GPU por debajo del 50 %. Ya existían:
- pausar, reanudar y cancelar (una tarea cancelada descarta su resultado);
- reintentos (3) y punto de control;
- recuperación tras un reinicio.

Hoy el ejecutor de tareas **solo piensa y escribe texto** (niveles 0 y 1). Las tareas de nivel 2 se le devuelven a Sergio.

Luna nunca dice que trabajó con el PC apagado: el programador solo corre mientras Luna está encendida, y al reiniciar retoma lo interrumpido.

## Pendiente

- Estado VERIFICANDO: comprobar el criterio de éxito antes de marcar un objetivo como completado. Hoy el evento dice que nadie lo verificó.
- Permisos por carpeta y por proyecto. Hoy las carpetas se limitan en el organizador (Descargas y Escritorio) y en el análisis (conocimiento, Descargas, Escritorio, Documentos).
- Editar en la interfaz las reglas por herramienta. Hoy se cambian por API o en `datos/permisos.json`; el nivel sí se cambia en Ajustes.
