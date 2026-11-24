# Integración: notificaciones transparentes y monitor del PC

Módulos nuevos: `lek/notificaciones.py`, `lek/monitor_pc.py` (sin dependencias nuevas; psutil opcional).
Pruebas: `python -m pytest -q tests/test_notificaciones.py tests/test_monitor_pc.py`.

## 1. Crear el notificador (servidor.py, después de `ALMACEN = Almacen(DATOS)`)
```python
from lek.notificaciones import Notificador
NOTIF = Notificador(ALMACEN)   # crea la tabla notificaciones si no existe
```

## 2. Avisar SIEMPRE que Luna actúa sola (nunca ocultarlo)
```python
NOTIF.notificar("codigo", "Escribí la habilidad clima", "Espera tu aprobación", codigo=codigo)  # crear_habilidad
NOTIF.notificar("archivos", "Ordené Descargas", "Moví 3 PDF a Universidad/Taller 4")
NOTIF.notificar("sistema", "Abrí Revit", "Me lo pediste por voz")                             # abrir_programa
NOTIF.notificar("proyecto", "Anoté un avance de LEK", avance)                                # anotar_avance_lek
NOTIF.notificar("salud", "Llevas 3 h sin pausa", "")
```
Tipos válidos: codigo, archivos, sistema, salud, proyecto, aviso (otro tipo se guarda como `aviso`).
`notificar` guarda, audita (`auditoria.accion = 'notificacion'`) y lanza el toast en un hilo: no bloquea.
Más de 5 del mismo tipo en 1 minuto: un solo toast "Luna hizo 12 cambios en archivos en el último
minuto" (sale ~5 s después de la ráfaga); todas quedan guardadas una por una.

## 3. Endpoints
```python
@app.get("/api/notificaciones")
def ver_notificaciones(request: Request, no_leidas: bool = False, limite: int = 50):
    revisar_pin(request)
    return NOTIF.api_listar(no_leidas, limite)   # {notificaciones:[{id,fecha,tipo,titulo,detalle,codigo,leida}], no_leidas}

@app.post("/api/notificaciones/leidas")
async def marcar_notificaciones(request: Request):
    revisar_pin(request)
    cuerpo = await request.json() if (await request.body()) else {}
    return NOTIF.api_marcar(cuerpo)              # {ids?: [1,2]} sin ids = todas -> {marcadas, no_leidas}
```
La app (static/) debe mostrar el `codigo` completo en un bloque <pre> (escapado, con textContent).

## 4. Herramienta estado_pc
```python
from lek import monitor_pc
HERRAMIENTAS.append(monitor_pc.HERRAMIENTA)
FUNCIONES["estado_pc"] = lambda **_: monitor_pc.estado_pc()
```
Datos crudos para un panel: `monitor_pc.leer()` -> {cpu, memoria, disco, bateria, procesos, encendido,
fuente, errores, alertas}. Tarda ~0,3 s (muestra de CPU); en Windows sin psutil los procesos tardan
1-3 s por PowerShell: no llamarlo en cada mensaje. `diagnostico()` puede añadir `monitor_pc.estado_pc()`.
Opcional: si `leer()["alertas"]` no está vacío, `NOTIF.notificar("salud", alerta, ...)` (con límite propio).
