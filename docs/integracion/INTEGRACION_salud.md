# Integración: pulso del Apple Watch (lek/salud_corporal.py)
Datos de salud = SIEMPRE locales. Nada de este módulo debe llegar a un modelo en la nube.

## 1. Crear el módulo (servidor.py, junto a ALMACEN)
```python
from lek.salud_corporal import SaludCorporal, ErrorPulso, HERRAMIENTA_MI_PULSO, HERRAMIENTAS_SIEMPRE_PRIVADAS
SALUD_CORPORAL = SaludCorporal(ALMACEN)          # crea las tablas pulso y pulso_diario si faltan
```

## 2. Endpoints (todos con revisar_pin; ErrorPulso -> 400)
```python
@app.post("/api/salud/pulso")            # {bpm, fecha?, origen}
async def salud_pulso(request: Request):
    revisar_pin(request)
    d = await request.json()
    try:
        nueva = SALUD_CORPORAL.registrar(d.get("bpm"), d.get("fecha"), d.get("origen", "apple_watch"))
    except ErrorPulso as e:
        raise HTTPException(400, str(e))
    return {"guardada": nueva, "resumen": SALUD_CORPORAL.resumen(60)}
@app.post("/api/salud/pulso/lote")       # {muestras:[{fecha, bpm}], origen:'apple_watch'}  (o {texto, origen})
async def salud_pulso_lote(request: Request):
    revisar_pin(request)
    d = await request.json()
    try:
        return SALUD_CORPORAL.registrar_lote(d, origen=str(d.get("origen", "apple_watch")) if isinstance(d, dict)
                                             else "apple_watch")
    except ErrorPulso as e:
        raise HTTPException(400, str(e))
@app.get("/api/salud/pulso")             # ?minutos=60 -> {resumen, serie:[{fecha,bpm}], reposo_24h, alertas}
def salud_pulso_ver(request: Request, minutos: int = 60):
    revisar_pin(request)
    return SALUD_CORPORAL.respuesta_api(minutos)
```
`registrar_lote` devuelve `{recibidas, guardadas, duplicadas, rechazadas, errores}`; deduplica por fecha
(normalizada a UTC: la misma hora con otra zona horaria cuenta como duplicada). Tamaño sugerido: ≤ 2000 muestras.

## 3. Herramienta mi_pulso, SIEMPRE privada
```python
HERRAMIENTAS.append(HERRAMIENTA_MI_PULSO)
FUNCIONES["mi_pulso"] = SALUD_CORPORAL.mi_pulso
# en herramienta_es_privada(nombre), PRIMERA línea (no depende de CONFIG):
    if nombre in HERRAMIENTAS_SIEMPRE_PRIVADAS:
        return True
```
NO la metas en `HERRAMIENTAS_PRIVADAS` con una clase "salud": `CONFIG.get("privacidad", "salud")` no existe
(KeyError) y además dejaría que un ajuste la mande a la nube. Con lo anterior, al llamarla el turno sigue
solo en el PC (el mecanismo `privado=True` que ya existe en responder()).
No añadir `mi_pulso` a la lista blanca de herramientas del flujo de la línea ~862 de servidor.py ("nada privado aquí").

## 4. Certificado (bloqueante para iOS) — requiere cambio en servidor.py, fuera de mi alcance
El certificado propio de `certificado()` dura 1825 días y no trae EKU serverAuth ni BasicConstraints CA:
iOS (Atajos) muy probablemente lo rechaza aunque se instale. Opciones:
- Aceptar variables `ASISTENTE_CERT` / `ASISTENTE_KEY` en .env para usar los archivos de `tailscale cert`
  (recomendado; iOS confía en ellos sin instalar nada; renovar cada ~90 días), o
- generar el propio con vigencia ≤ 825 días, `ExtendedKeyUsage([SERVER_AUTH])` y `BasicConstraints(ca=True)`.
Si se usa `tailscale serve` como proxy, la IP del cliente llega como 127.0.0.1: el PIN sigue valiendo, pero
`es_remoto()` deja de detectar Tailscale (sin PIN quedaría abierto a toda la tailnet).

Pruebas: `python -m pytest -q tests/test_salud_corporal.py` (33 pruebas, sin red, reloj fijo).
