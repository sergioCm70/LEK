# Integrar objetivos, proyectos y tareas (lek/autonomia) en servidor.py

1. Después de `ALMACEN = Almacen(DATOS)` (las tablas se crean solas en luna.db):
```python
from lek.autonomia.proyectos import GestorProyectos, TransicionInvalida, herramientas_luna
from lek.autonomia.programador import Programador
PROYECTOS = GestorProyectos(ALMACEN, avisar=lambda t: (print("  [proyectos]", t), ALMACEN.auditar("aviso_proyectos", t)))
```
2. Herramientas para Luna, justo después de `FUNCIONES = {...}` (Luna propone; solo el usuario aprueba):
```python
def pensar_plan(prompt):  # extraer_json acepta el dict {"content": ...} que devuelve ollama_chat
    return ollama_chat([{"role": "user", "content": prompt}], usar_tools=False)
_defs, _funcs = herramientas_luna(PROYECTOS, pensar_plan)   # crear_objetivo, ver_proyectos
HERRAMIENTAS += _defs
FUNCIONES.update(_funcs)
```
3. Endpoints (aprobar/cancelar con `revisar_aprobacion`: PIN, o sin PIN solo desde el PC):
```python
@app.get("/api/proyectos")      # {proyectos: [{id, titulo, estado, avance, tareas: [{titulo, estado}]}]}
def ver_proyectos_api(request: Request):
    revisar_pin(request)
    return PROYECTOS.resumen_api()

@app.post("/api/proyectos/{pid}/{accion}")   # accion: aprobar | pausar | reanudar | cancelar
def accion_proyecto(pid: int, accion: str, request: Request):
    revisar_aprobacion(request)
    if accion not in ("aprobar", "pausar", "reanudar", "cancelar"):
        raise HTTPException(404, "Acción desconocida")
    try:
        return PROYECTOS.accion(pid, accion)
    except KeyError:
        raise HTTPException(404, "No existe ese proyecto")
    except TransicionInvalida as e:
        raise HTTPException(409, str(e))
```
Recomendado (sin esto el nivel 2 espera para siempre): `GET /api/aprobaciones` -> `PROYECTOS.aprobaciones_pendientes()`;
`POST /api/aprobaciones/{aid}/{aprobar|rechazar}` -> `PROYECTOS.responder_aprobacion(aid, accion == "aprobar")` (igual
manejo de errores). Bloqueadas: `PROYECTOS.desbloquear(tid)` / `PROYECTOS.marcar_completada(tid, evidencia)`.

4. Ejecutor y PC libre (antes de `main()`). Este ejecutor solo piensa y escribe texto, sin herramientas:
```python
def ejecutar_tarea(tarea, punto):
    if tarea["nivel_autorizacion"] >= 2:
        return {"estado": "bloqueada", "motivo": "Esta acción la debes hacer tú; márcala como hecha al terminar."}
    previos = "\n".join(f"- {r[:1500]}" for r in tarea["resultados_previos"].values()) or "(ninguno)"
    pedido = (f"Objetivo: {tarea['objetivo']} (éxito: {tarea['criterio_exito']}).\nTarea: {tarea['titulo']}\n"
              f"{tarea['descripcion']}\nResultados de tareas anteriores:\n{previos}\nHaz la tarea y entrega el resultado.")
    msg = ollama_chat([{"role": "system", "content": construir_prompt()}, {"role": "user", "content": pedido}],
                      usar_tools=False)
    return {"resultado": limpiar_respuesta(msg.get("content", ""))}

def pc_libre():
    r = recursos()
    return r.get("ram_uso_pct", 0) < 80 and ((r.get("gpu") or {}).get("uso_pct", 0) < 50)
```
5. En `main()`, después de `revision.start()` (el hilo revisa cada 2 min; al arrancar retoma lo interrumpido):
```python
    programador = Programador(PROYECTOS, ejecutar_tarea, pc_libre); programador.arrancar()
```
y envolver `asyncio.run(correr())` en `try: ... finally: programador.detener(10)`.
