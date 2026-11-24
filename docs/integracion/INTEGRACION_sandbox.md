# Integración: automejora segura (lek/automejora)

Módulos: `lek/automejora/politica.py` (análisis estático con `ast`) y `lek/automejora/sandbox.py`
(subproceso aislado). No tocan servidor.py: estos son los cambios sugeridos.

## 1. crear_habilidad → decidir
```python
from lek.automejora import decidir, ejecutar_habilidad_aprobada
AUTONOMA = os.getenv("LUNA_AUTOMEJORA_AUTONOMA", "1") == "1"   # o CONFIG

def crear_habilidad(nombre, codigo, descripcion=""):
    ...  # limpieza, slug y DESCRIPCION como hoy
    d = decidir(codigo, modo_autonomo=AUTONOMA)
    if d["accion"] == "rechazar":
        return f"No la guardé: {d['resumen']} Corrígela y vuelve a intentarlo."
    destino = (HABILIDADES if d["accion"] == "activar_sola" else PROPUESTAS) / f"{n}.py"
    # si destino existe: copiar a VERSIONES antes (igual que aprobar_habilidad)
    destino.write_text(cabecera + codigo, encoding="utf-8")
    ALMACEN/notificación: guardar d["resumen"], d["motivos"], d["riesgo"], d["pruebas"], d["codigo"]
    return d["resumen"] + " Dile a Sergio qué hiciste y muéstrale el código."
```
- La notificación es SIEMPRE (también al activar sola): resumen + código + motivos.
- `rechazar` devuelve el motivo a Luna para que corrija (falta EJEMPLOS, ejemplo falló, no compila).

## 2. Pedirle EJEMPLOS a Luna
En la descripción de la herramienta `crear_habilidad` añadir:
`EJEMPLOS = [{"args": {...}, "espera_contiene": "texto"}]` (≥ 1, literales, sin internet si se puede).
Sin EJEMPLOS una habilidad de riesgo bajo se rechaza.

## 3. Ejecutar habilidades aisladas
En `ejecutar_herramienta`, para nombres `hab_*`, en lugar de llamar `funcion(**args)` en el proceso:
```python
r = ejecutar_habilidad_aprobada(HABILIDADES / h["archivo"], argumentos, tiempo_limite=30)
return r["resultado"] if r["ok"] else f"La habilidad falló: {r['error']}"
```
`cargar_habilidades()` hoy hace `exec_module` en el proceso de Luna (código a nivel de módulo corre ahí):
cambiarlo a leer DESCRIPCION/PARAMETROS con `leer_info_habilidad` (ast, sin ejecutar).

## 4. Panel de habilidades
`leer_info_habilidad` puede usar `politica.analizar(codigo)["motivos"]` en vez de las regex `RIESGOS`
(motivos con número de línea). Añadir un botón "desactivar" visible para las activadas solas.

## Reglas de decisión
| Situación | Acción |
|---|---|
| No compila / sin `ejecutar()` | rechazar |
| Riesgo alto | pedir_aprobacion (NO se ejecuta ni en pruebas) |
| Riesgo bajo + algún ejemplo falla o se cuelga | rechazar |
| Riesgo bajo + pruebas OK + modo autónomo | activar_sola |
| Riesgo bajo + pruebas OK + modo autónomo apagado | pedir_aprobacion |

## Límites reales
- El subproceso NO es una jaula del sistema: mismo usuario de Windows, puede leer/escribir rutas
  absolutas y usar la red. La protección es la política (lista blanca) + sin claves + tiempo límite.
- Análisis estático de Python nunca es perfecto: se bloquean las vías conocidas (dunders, marcos,
  getattr dinámico, attrgetter...), pero un truco nuevo podría pasar. Por eso todo se notifica.
- Límite de memoria (1 GB) y de tamaño de archivo solo en Linux/Mac; en Windows solo tiempo.
- Un GET a un host permitido puede llevar datos en la URL (p. ej. a DuckDuckGo); como la habilidad
  de riesgo bajo no puede leer archivos ni entorno, solo podría filtrar sus propios argumentos.
- Cada ejecución arranca Python (~0,1–0,5 s más por llamada, más si importa requests).
