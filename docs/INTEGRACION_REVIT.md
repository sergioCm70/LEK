# Integración de Luna con Revit (solo lectura)

Objetivo: que Luna pueda responder preguntas sobre el modelo de Sergio (niveles, áreas, cantidades de muros,
puertas, ventanas, espacios) **sin modificarlo nunca**.

## Opción 1 — IFC exportado (lista, recomendada)

1. En Revit: Archivo → Exportar → IFC. En "Modificar configuración" → "Conjuntos de propiedades", activar
   **Exportar cantidades base** para que salgan las áreas de los espacios.
2. Guardar el `.ifc` en una carpeta que Luna pueda leer (Documentos, Escritorio o Descargas).
3. Preguntarle: "Luna, analiza modelo.ifc" o "¿cuántas puertas tiene el IFC de Las Delicias?".

Ventajas: no toca Revit, funciona aunque Revit esté cerrado y no consume RAM mientras se modela. Lo hace
`lek/analisis/multimodal.py` con un lector propio del formato STEP (sin librerías).
Límites: es una foto del momento en que se exportó; los volúmenes y geometría detallada no se calculan.

## Opción 2 — pyRevit (futuro, en vivo)

pyRevit permite correr scripts de Python dentro de Revit. Un botón "Enviar a Luna" podría recorrer el modelo
abierto con la API de Revit (FilteredElementCollector) y mandar a Luna un resumen en JSON por `http://127.0.0.1`.
Reglas si se hace: solo lectura (sin `Transaction`), botón que Sergio pulsa a mano, sin abrir puertos nuevos.
No se implementa todavía: necesita instalar pyRevit y probarlo con su versión de Revit, y el PC trabaja al
90–97 % de RAM cuando Revit está abierto.

## Opción 3 — Dynamo

Similar a pyRevit pero con nodos visuales. Más trabajo para Sergio y sin ventajas para este caso.

## Lo que Luna nunca hará

Modificar el `.rvt`, mover, renombrar o borrar archivos de Revit o CAD (el organizador ya los deja intactos).
