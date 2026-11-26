# API de LEK

Generada desde `servidor.py` (26/11/2026). Desde este PC no se pide PIN; desde otro dispositivo hace falta
la cabecera `X-Asistente-Sesion` (de `POST /api/sesion`) o `X-Asistente-Pin`. Las rutas que cambian algo
aceptan peticiones solo del mismo origen (o de clientes sin `Origin`, como Atajos o el collar).

| Método | Ruta | Función | Descripción |
|---|---|---|---|
| GET | `/api/mensajes` | `mensajes_nuevos` | Mensajes posteriores a `desde` (para ver en pantalla lo que se habló por voz o desde el celular). desde=-1: solo dice cuál es el último, para empezar a seguir d |
| GET | `/api/voz/vivo` | `voz_en_vivo` | Lo que la escucha en segundo plano está oyendo ahora mismo (para escribirlo en pantalla). |
| GET | `/api/vocabulario` | `ver_vocabulario` |  |
| POST | `/api/vocabulario` | `agregar_vocabulario` |  |
| POST | `/api/sesion` | `abrir_sesion` | Cambia el PIN por una sesión del dispositivo (30 días sin uso). El navegador ya no guarda el PIN. |
| GET | `/api/seguridad` | `estado_seguridad` |  |
| POST | `/api/seguridad/pin` | `cambiar_pin_api` | Poner o cambiar el PIN. Desde este PC basta; desde otro dispositivo hace falta el PIN actual. |
| POST | `/api/seguridad/cerrar_sesiones` | `cerrar_sesiones` |  |
| GET | `/` | `inicio` |  |
| GET | `/api/ping` | `ping` |  |
| POST | `/api/chat` | `chat` |  |
| POST | `/api/reiniciar` | `reiniciar` | Empieza un tema nuevo: el contexto corto se limpia, pero nada se borra (lo busca si hace falta). |
| GET | `/api/habilidades` | `ver_habilidades` |  |
| POST | `/api/habilidades/aprobar` | `aprobar_habilidad` |  |
| POST | `/api/habilidades/rechazar` | `rechazar_habilidad` |  |
| POST | `/api/habilidades/desactivar` | `desactivar_habilidad` |  |
| GET | `/api/ajustes` | `ver_ajustes` |  |
| POST | `/api/ajustes` | `guardar_ajustes` |  |
| GET | `/api/inteligencia` | `ver_inteligencia` | Todo lo que el panel de inteligencia muestra: modelos, estado, motivos, cambios, privacidad y recursos. |
| POST | `/api/inteligencia` | `cambiar_inteligencia` |  |
| POST | `/api/modelos/descargar` | `descargar_modelo` | Descargar un modelo ocupa disco y RAM: con PIN o desde este PC, y queda en la auditoría. |
| POST | `/api/inteligencia/probar` | `probar_modelos` | Prueba comparativa: las mismas preguntas a cada modelo local instalado, midiendo el tiempo. |
| POST | `/api/apagar` | `apagar` | Lo usa una versión nueva de Luna para reemplazar a la vieja. Solo desde el mismo PC. |
| POST | `/api/collar` | `collar` | El collar manda un WAV con tu voz y recibe un WAV con la respuesta. |
| GET | `/api/notificaciones` | `ver_notificaciones` |  |
| POST | `/api/notificaciones/leidas` | `marcar_notificaciones` |  |
| POST | `/api/salud/pulso` | `salud_pulso` |  |
| POST | `/api/salud/pulso/lote` | `salud_pulso_lote` |  |
| GET | `/api/salud/pulso` | `salud_pulso_ver` |  |
| GET | `/api/pc` | `estado_del_pc` |  |
| GET | `/api/archivos/estado` | `archivos_estado` |  |
| POST | `/api/archivos/analizar` | `archivos_analizar` |  |
| POST | `/api/archivos/organizar` | `archivos_organizar` |  |
| POST | `/api/archivos/deshacer` | `archivos_deshacer` |  |
| GET | `/api/proyectos` | `ver_proyectos_api` |  |
| POST | `/api/proyectos/{pid}/{accion}` | `accion_proyecto` |  |
| POST | `/api/aprobaciones/{aid}/{accion}` | `responder_aprobacion` |  |
| POST | `/api/tareas/{tid}/{accion}` | `accion_tarea` |  |
| GET | `/api/memoria/recuerdos` | `ver_recuerdos` |  |
| GET | `/api/memoria/por_que` | `por_que_api` |  |
| POST | `/api/memoria/olvidar` | `olvidar_api` |  |
| POST | `/api/memoria/actualizar` | `actualizar_api` |  |
| GET | `/api/memoria/exportar` | `exportar_memoria` | Toda la memoria organizada (recuerdos con historial, proyectos y pendientes) en un JSON. |
| POST | `/api/memoria/importar` | `importar_memoria` |  |
| GET | `/api/contexto/proyectos` | `ver_proyectos_ctx` |  |
| POST | `/api/contexto/proyectos/{s}/activar` | `activar_proyecto_ctx` |  |
| POST | `/api/contexto/salir` | `salir_proyecto_ctx` |  |
| GET | `/api/sistema` | `ver_sistema` |  |
| POST | `/api/sistema` | `cambiar_sistema` |  |
| GET | `/api/respaldos` | `ver_respaldos` |  |
| POST | `/api/respaldos/crear` | `crear_respaldo` |  |
| POST | `/api/respaldos/verificar` | `verificar_respaldo` |  |
| GET | `/api/actividad` | `ver_actividad` | Lo que Luna está haciendo ahora y lo último que hizo (sin textos privados). |
| GET | `/api/herramientas` | `ver_herramientas` | Cada herramienta con su esquema, permisos y si es privada, externa o con efectos. |
| POST | `/api/diagnostico/sandbox` | `probar_sandbox` | Comprueba en este PC qué barreras del sandbox funcionan de verdad (código de prueba fijo). |
| GET | `/api/voz` | `estado_voz` |  |
| GET | `/api/memoria` | `estado_memoria` |  |
| POST | `/api/inteligencia/evaluar` | `evaluar_modelos` | Banco de 30 preguntas verificables (escalas, fechas, áreas, herramientas...) a cada modelo. |
| GET | `/api/inteligencia/evaluar` | `ver_evaluacion` |  |
