# Arquitectura de LEK (estado real al 26/11/2026)

Luna es la interfaz, la identidad y el agente principal. LEK es el sistema que la sostiene. Todo corre en el PC de Sergio; solo la conversación puede ir a Claude.

## Flujo de un turno

```
pedido (texto, voz del navegador o voz de fondo)
  │  voz → lek/voz/entender.py: correcciones aprendidas + nota "lo dijo en voz alta"
  ▼
servidor.responder()
  1. enrutador (lek/cerebros/enrutador.py): simple / normal / compleja / privada, sin llamar a ningún modelo
  2. se guarda el mensaje del usuario (luna.db); si es privado, nada de este turno sale del PC
  3. contexto: últimos 21 mensajes (sin ruido) + resúmenes + búsqueda (por significado si hay embeddings; si no, por palabras)
  4. bucle de herramientas (máx. 5 rondas):
       ejecutar_herramienta → auditoría, marca de DATOS EXTERNOS y bloqueo de acciones si el turno está contaminado
       herramienta privada → el resto del turno solo con el modelo local
  5. control de afirmaciones: "guardé…" sin herramienta → una corrección
  6. se guarda la respuesta, se indexa en segundo plano
```

## Módulos

| Módulo | Responsabilidad |
|---|---|
| `servidor.py` | FastAPI: endpoints, herramientas, prompt, arranque. Todavía es grande (fase 2: separar el núcleo). |
| `lek/seguridad.py` | PIN cifrado, sesiones, bloqueos, validación de Host y Origin. |
| `lek/control_turno.py` | Datos externos, bloqueo por contaminación, afirmaciones sin respaldo. |
| `lek/pendientes.py` | Memoria de trabajo: pendientes que sobreviven a reinicios. |
| `lek/memoria_capas.py` | Recuerdos con categoría, tipo de fuente, confianza, vigencia e historial (ver `MEMORIA_LEK.md`). |
| `lek/proyectos_contexto.py` | Proyectos contextuales: decisiones vs propuestas, restricciones, fechas, avances, problemas. |
| `lek/respaldo.py` | Respaldo zip verificable y restauración (CLI y `restaurar.bat`). |
| `lek/inicio_windows.py` | Arranque con Windows (carpeta Inicio del usuario). |
| `lek/cerebros/` | Proveedores (Ollama, Claude), catálogo, salud, gestor (presupuesto mensual y diario, avisos al 80 %) y enrutador. |
| `lek/almacen.py` | SQLite: mensajes y FTS, recuerdos, resúmenes, llamadas, auditoría. |
| `lek/memoria_semantica.py` | Embeddings locales e índice híbrido (requiere `nomic-embed-text`). |
| `lek/automejora/` | Política (análisis estático), sandbox y aislamiento de Windows. |
| `lek/autonomia/` | Objetivos, proyectos, tareas y programador en segundo plano. |
| `lek/analisis/` | PDF, DOCX, XLSX/CSV, imágenes (cabecera), GLB y calculadora exacta. |
| `lek/pc/organizador.py` | Organizador de Descargas y Escritorio (mueve con deshacer, nunca borra, no toca Revit/CAD). |
| `lek/voz/` | Despertador (Vosk y Whisper), vocabulario y correcciones. |
| `lek/notificaciones.py`, `monitor_pc.py`, `salud_corporal.py`, `evaluacion/` | Avisos, estado del PC, pulso y banco de evaluación. |

## Datos (`datos/`, nunca a GitHub)

- `luna.db`: tablas mensajes, recuerdos, resumenes, llamadas, auditoria, notificaciones, sesiones, pendientes, proyectos/tareas y vectores.
- `config.json` (solo lo que difiere de lo predeterminado) y `secretos.json` (clave de Claude y PIN cifrado).
- `vocabulario.json`, `notas.md`, `identidad.json` e `ideas.md`.
- `respaldos/` (zips diarios), `sandbox/` (python con integridad baja), `modelos/` (Vosk) y `navegador/` (perfil de Edge).

## Pruebas

```
python -m pytest -q      # 387 pruebas, sin red ni modelos reales (proveedores falsos)
```

En este entorno de desarrollo FastAPI no está instalado: `tests/conftest.py` lo reemplaza por un sustituto mínimo, así que las pruebas llaman a las funciones de los endpoints directamente. El comportamiento HTTP real (middleware y cookies) se verificó en el PC.
