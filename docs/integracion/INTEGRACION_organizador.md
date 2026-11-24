# Integración: organizador autónomo (lek/pc/organizador.py)
Solo mueve archivos SUELTOS de la raíz de Descargas/Escritorio a `<raíz>\Organizado por Luna\<categoría>`.
Nunca borra ni sobrescribe (sufijo " (2)"), revalida todo al mover, todo se deshace. Sin dependencias nuevas.

## 1. Crear (servidor.py, junto a ALMACEN)
```python
from lek.pc.organizador import Organizador, cargar_config, HERRAMIENTAS as HERRAMIENTAS_ARCHIVOS
ORGANIZADOR = Organizador(ALMACEN, cargar_config(DATOS / "organizador.json"))  # crea la tabla movimientos
```
`datos/organizador.json` es opcional: `{"raices": ["Descargas","Escritorio"], "solo_analizar": ["Documentos"],
"permitir_documentos": false, "tope_lote": 500, "limite_archivos": 5000, "limite_segundos": 20}`.
Las raíces aceptan alias (Descargas/Escritorio/Documentos, con OneDrive) o rutas absolutas. `horas_minimas`
no baja de 24 ni `tope_lote` sube de 500. Rutas del sistema/ocultas se rechazan (`ORGANIZADOR.avisos`).

## 2. Herramientas de Luna
```python
HERRAMIENTAS += HERRAMIENTAS_ARCHIVOS   # analizar_archivos, organizar_archivos, deshacer_organizacion{id?|lote?}
for _n in ("analizar_archivos", "organizar_archivos", "deshacer_organizacion"):
    FUNCIONES[_n] = (lambda n: lambda **a: ORGANIZADOR.ejecutar(n, a))(_n)
```
`ejecutar` devuelve texto en español listo para decir. `deshacer_organizacion` sin argumentos = último lote.

## 3. Endpoints (todos con revisar_pin; def normal: FastAPI los corre en un hilo)
```python
@app.get("/api/archivos/estado")          # no recorre el disco
def archivos_estado(request: Request):
    revisar_pin(request); return ORGANIZADOR.api_estado()
@app.post("/api/archivos/analizar")
def archivos_analizar(request: Request):
    revisar_pin(request); return ORGANIZADOR.api_analizar()
@app.post("/api/archivos/organizar")      # {plan?:[{origen}]}; sin plan usa el último análisis (requiere import asyncio)
async def archivos_organizar(request: Request):
    revisar_pin(request)
    d = await request.json() if (await request.body()) else {}
    return await asyncio.to_thread(ORGANIZADOR.api_organizar, d.get("plan"))
@app.post("/api/archivos/deshacer")       # {id}
async def archivos_deshacer(request: Request):
    revisar_pin(request); d = await request.json()
    return ORGANIZADOR.api_deshacer(int(d["id"]))
```
Todas responden exactamente:
`{estado, resumen:{total, por_tipo}, plan:[{origen, destino, motivo}], movimientos:[{id, fecha, origen, destino, deshecho}]}`
- `estado`: texto ("sin analizar", "analizado", "Organicé 12 archivos (lote …). Salté 3.", "Deshecho: …").
- `por_tipo`: {"Revit", "Respaldos de Revit", "PDF y documentos", "Imágenes y renders", "Modelos 3D", "CAD",
  "Instaladores", "Comprimidos", "Hojas de cálculo", "Otros"} → cantidad. `movimientos`: últimos 50, `deshecho` bool.
- El `destino` que mande el cliente se ignora: se recalcula y se revalida cada `origen`.

## 4. API de Python (para notificaciones / tareas programadas)
- `analizar()` → resumen, plan, saltados[{ruta,motivo}], carpetas_proyecto, solo_analisis, truncado, avisos.
- `organizar(plan=None)` → `{movidos, saltados:[{ruta, motivo}], lote, pendientes, mensaje}` (para notificar).
- `deshacer(id)` → `{ok, id, mensaje}`; `deshacer_lote(lote)` → `{lote, deshechos, fallidos, mensaje}`.
- Auditoría: `archivos_organizar`, `archivos_deshacer`, `archivos_deshacer_lote`.

## 5. Pruebas
`python -m pytest -q tests/test_organizador.py` (17 pruebas, carpetas temporales).
