# Estado de continuidad LEK 2.0

Última actualización: 26/11/2026. Este archivo permite retomar el trabajo sin perder contexto.

## Fases

| Fase | Estado | Notas |
|---|---|---|
| 0 Auditoría | **Completada** | `docs/AUDITORIA_LEK2.md` |
| 1 Estabilización | **Completada** | Críticos C1–C3 y altos A1–A7 resueltos. C4 (rotar la clave de Claude) depende de Sergio. Ver `REGISTRO_CAMBIOS.md` |
| 2 Núcleo inteligente | **Completada (base)** | Registro único de herramientas con esquema, validación y permisos (`lek/nucleo/registro.py`); actividad en vivo (`/api/actividad`, Módulos → Actividad); agente investigador con fuentes. Ver `AGENTES_LEK.md` y `API_LEK.md`. Pendiente: sacar los endpoints de `servidor.py` a módulos (refactor mecánico, sin cambio de comportamiento) |
| 3 Memoria por capas | **Completada** | `docs/MEMORIA_LEK.md`. Recuerdos con procedencia y vigencia, contradicciones, olvido con índices, por qué, exportar/importar, proyectos contextuales. Falta: reranking (descartado por RAM) e interfaz para editar items de proyectos |
| 4 Autonomía | **Base completada** | 5 niveles, reglas por herramienta (permitir/preguntar/bloquear), aprobaciones de un solo uso que caducan, revisión diaria en modo autónomo. Ver `AUTONOMIA_LEK.md`. Editor de reglas en la interfaz listo. Pendiente: estado VERIFICANDO, permisos por carpeta y proyecto |
| 5 Autoevolución | Parcial | Sandbox real y aprobación humana listos. Faltan versiones e historial por habilidad, reversión desde la interfaz y propuestas de mejora del núcleo en rama aparte |
| 6 Interfaz y voz | **Base completada** | Respuestas en vivo (`/api/chat/vivo`), interrupción (■ / Esc / "Luna, para"), voz frase por frase y modo compacto para celular. Pendiente de verificar en el PC y en el celular real |
| 7 Multimodal | **Base completada** | PDF, DOCX, XLSX/CSV, GLB, **PPTX**, **IFC** (Revit → Exportar → IFC: niveles, conteo de elementos, espacios y áreas; solo lectura) y **OCR de Windows** (`leer_texto_imagen`, sin internet). OCR pendiente de verificar en el PC. Falta: visión (describir imágenes) con un modelo local, y lectura en vivo de Revit con pyRevit (ver `INTEGRACION_REVIT.md`) |
| 8 Ecosistema | Parcial | Celular por LAN (con PIN). Tailscale sin instalar; Apple Watch sin iPhone confirmado; collar sin hardware |
| 9 Validación | Continua | 421 pruebas automáticas. Criterios de aceptación en `AUDITORIA_LEK2.md` |

## Criterios de aceptación de la fase 1

| Prueba | Resultado |
|---|---|
| Acceso remoto sin PIN rechazado | Aprobada (pruebas); en el PC la consola confirma "solo este PC" |
| PIN guardado cifrado, sesiones y bloqueo por intentos | Aprobada (pruebas) |
| Petición de otro sitio rechazada (CSRF) y Host ajeno rechazado | Aprobada (pruebas) |
| Habilidad nueva espera aprobación humana | Aprobada (pruebas) |
| Sandbox de Windows bloquea escritura, procesos hijos y exceso de memoria | **Aprobada en el PC real** |
| Habilidades reales siguen funcionando dentro del sandbox | **Aprobada en el PC real** (clima y escala) |
| Documento externo no puede mover archivos | Aprobada (pruebas) |
| Afirmación sin herramienta corregida | Aprobada (pruebas) |
| Respaldo completo verificado | **Aprobada en el PC real** (96 mensajes, integridad ok) |
| Restauración | Aprobada (pruebas); no se ejecutó en el PC para no tocar datos reales |
| Arranque con Windows | **Acceso creado en el PC**; falta comprobarlo tras un reinicio real |
| Acceso desde el celular con PIN y sesión | Pendiente: Sergio debe poner un PIN y probar |

## Criterios de aceptación de la fase 3

| Prueba | Resultado |
|---|---|
| Recupera recuerdos por lenguaje natural | Aprobada (pruebas) |
| Distingue información actual de la antigua (reemplazos con historial) | Aprobada (pruebas) |
| Lo inferido no se presenta como hecho | Aprobada (pruebas) |
| Olvidar invalida y limpia el índice | Aprobada (pruebas) |
| Conserva el contexto de proyectos (decisiones vs propuestas) | Aprobada (pruebas) |
| Migración con respaldo previo verificado | **Aprobada en el PC real** |
| "Trabajemos en Las Delicias" de punta a punta | **Aprobada en el PC real**: 127 s con el modelo local (y el proyecto no quedó activo por un error, ya corregido); 2,8 s con Claude después de que Sergio permitió `proyectos = nube` (26/11), con el proyecto activo y los mensajes asociados |

## Criterios de aceptación de la fase 2

| Prueba | Resultado |
|---|---|
| Cada herramienta tiene ficha completa (definición = función) | Aprobada (pruebas) |
| Argumentos inválidos se rechazan antes de ejecutar | Aprobada (pruebas) |
| La actividad muestra turno, cerebro y herramientas sin texto privado | Aprobada (pruebas) |
| El investigador cita fuentes y no lee dos veces la misma página | Aprobada (pruebas) |
| El investigador no puede leer la red local ni a Luna (SSRF) | Aprobada (pruebas) |
| Lo investigado contamina el turno (sin acciones con efectos) | Aprobada (pruebas) |
| En el PC: actividad, herramientas e investigación real | Ver más abajo |

## Pendientes de Sergio

1. Poner un PIN en Ajustes → Seguridad (6 dígitos o más).
2. Rotar la clave de Claude en platform.claude.com y pegar la nueva en Ajustes.
3. Instalar Tailscale (`instalar_tailscale.bat`) si quiere usar a Luna fuera de casa.
4. Confirmar si tiene iPhone (necesario para el Apple Watch).
5. Opcional: `ollama pull nomic-embed-text` para la memoria por significado (unos 274 MB, usa RAM).

6. ~~Privacidad de proyectos~~: Sergio eligió "pueden ir a Claude" (26/11). La memoria personal, las notas y los documentos siguen solo locales.

## Próximo paso recomendado

1. Cuando el PC vuelva: desplegar todo lo pendiente desde el commit cd44d19, reiniciar Luna y verificar en vivo `/api/actividad`, `/api/herramientas`, `/api/autonomia`, una investigación real `leer_texto_imagen` con una imagen con texto, y una respuesta en vivo con interrupción (que el texto aparezca por partes y que ■ detenga).
2. Fase 6 (streaming de respuestas, interrupción, estados visibles y diseño para celular).
