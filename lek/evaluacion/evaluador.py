"""Evaluador de LUNA: pasa el banco de pruebas a uno o varios modelos y decide por resultados, no por tamaño.

    r = evaluar(proveedor, "qwen3:8b", casos())          # un modelo
    informe = informe_comparativo([r1, r2])               # varios: aciertos %, mediana de tiempo, costo, recomendación
    guardar(almacen, r)                                   # tabla evaluaciones + aviso si cae más de 10 puntos

Usa solo Proveedor.chat. Las herramientas son falsas: nada se abre, se guarda ni se busca de verdad.
"""
import datetime
import json
import re
import statistics
import time

from lek.cerebros.base import ErrorProveedor

from .banco import (CASOS, HERRAMIENTAS_FALSAS, RESULTADO_POR_DEFECTO, VERSION_BANCO, Caso, Salida)

SISTEMA = ("Eres Luna, la asistente de voz de un estudiante de arquitectura en Colombia. Responde en español, "
           "breve (1 a 4 frases), exacta, sin markdown, sin listas y sin emojis: se lee en voz alta. Escribe los "
           "números con cifras. Si no tienes un dato, dilo: nunca inventes. Usa una herramienta cuando la tarea "
           "lo necesite.")
MAX_RONDAS = 3          # rondas de herramientas por caso
EMPATE_PUNTOS = 5.0     # dentro de esta diferencia de aciertos, gana el más barato y rápido
REGRESION_PUNTOS = 10.0
FATALES = {"auth", "saldo"}   # errores que hacen inútil seguir: el resto de casos fallaría igual


def _sin_razonamiento(texto: str) -> str:
    return re.sub(r"<think>.*?</think>", "", texto or "", flags=re.S).strip()


def _argumentos(a) -> dict:
    if isinstance(a, dict):
        return a
    try:
        d = json.loads(a or "{}")
        return d if isinstance(d, dict) else {}
    except (TypeError, ValueError):
        return {}


def _mediana(valores: list) -> float:
    return round(statistics.median(valores), 2) if valores else 0.0


def _correr_caso(proveedor, modelo: str, caso: Caso, sistema: str) -> dict:
    mensajes = [{"role": "system", "content": sistema}, {"role": "user", "content": caso.pregunta}]
    herramientas = HERRAMIENTAS_FALSAS if caso.herramientas else None
    salida, entrada, salida_t, usd, latencias = Salida(), 0, 0, 0.0, 0.0
    inicio = time.perf_counter()
    for _ in range(MAX_RONDAS):
        r = proveedor.chat(modelo, mensajes, herramientas)
        latencias += r.latencia or 0.0
        entrada += r.tokens_entrada or 0
        salida_t += r.tokens_salida or 0
        usd += r.usd or 0.0
        salida.texto = _sin_razonamiento(r.texto)
        if not r.llamadas or not herramientas:
            break
        mensajes.append(r.como_mensaje())
        for i, ll in enumerate(r.llamadas):
            nombre = (ll.get("function") or {}).get("name", "")
            salida.herramientas.append((nombre, _argumentos((ll.get("function") or {}).get("arguments"))))
            texto = caso.resultados_herramientas.get(nombre, RESULTADO_POR_DEFECTO.get(nombre, "Herramienta no disponible."))
            mensajes.append({"role": "tool", "content": texto, "tool_call_id": ll.get("id") or f"t{i}"})
    # la latencia que mide el proveedor es más fiel; si no la da, el reloj de pared
    segundos = latencias if latencias > 0 else time.perf_counter() - inicio
    ok, motivo = caso.verificador(salida)
    return {"id": caso.id, "categoria": caso.categoria, "ok": bool(ok), "segundos": round(segundos, 2),
            "tokens": entrada + salida_t, "tokens_entrada": entrada, "tokens_salida": salida_t,
            "usd": round(usd, 6), "motivo": motivo, "esperado": caso.esperado,
            "respuesta": salida.texto[:300], "herramientas": [n for n, _ in salida.herramientas]}


def evaluar(proveedor, modelo: str, casos: list | None = None, sistema: str = SISTEMA, almacen=None,
            calentar: bool = False) -> dict:
    """Corre los casos contra un modelo. calentar=True hace una llamada previa que no cuenta (carga el modelo
    local en memoria, como /api/inteligencia/probar). Con almacen, cada caso queda en la tabla llamadas
    (motivo "autoevaluación") para que el gasto cuente en el presupuesto del mes."""
    casos = CASOS if casos is None else casos
    if calentar:
        try:
            proveedor.chat(modelo, [{"role": "user", "content": "Responde solo: listo"}], None)
        except Exception:
            pass
    detalle, fatal = [], ""
    for caso in casos:
        if fatal:
            detalle.append({"id": caso.id, "categoria": caso.categoria, "ok": False, "segundos": 0.0, "tokens": 0,
                            "usd": 0.0, "motivo": f"no evaluado: {fatal}", "esperado": caso.esperado,
                            "respuesta": "", "herramientas": [], "evaluado": False})
            continue
        try:
            d = _correr_caso(proveedor, modelo, caso, sistema)
        except Exception as e:  # un caso que falla no tumba la evaluación
            d = {"id": caso.id, "categoria": caso.categoria, "ok": False, "segundos": 0.0, "tokens": 0, "usd": 0.0,
                 "motivo": f"error: {str(e)[:200]}", "esperado": caso.esperado, "respuesta": "", "herramientas": []}
            if isinstance(e, ErrorProveedor) and e.tipo in FATALES:
                fatal = f"{e.tipo}: {e.detalle}"[:200]
        d.setdefault("evaluado", True)
        detalle.append(d)
        if almacen is not None and d["evaluado"]:
            almacen.registrar_llamada(modelo, getattr(proveedor, "nombre", ""), d["segundos"], d.get("tokens_entrada", 0),
                                      d.get("tokens_salida", 0),
                                      d["usd"], ok=not d["motivo"].startswith("error"),
                                      error=d["motivo"] if d["motivo"].startswith("error") else "",
                                      motivo=f"autoevaluación {d['id']}")
    return resumir(modelo, getattr(proveedor, "nombre", ""), detalle, incompleto=fatal)


def resumir(modelo: str, proveedor: str, detalle: list, incompleto: str = "") -> dict:
    categorias = {}
    for d in detalle:
        c = categorias.setdefault(d["categoria"], {"aciertos": 0, "total": 0})
        c["aciertos"] += int(d["ok"])
        c["total"] += 1
    for c in categorias.values():
        c["pct"] = round(100 * c["aciertos"] / c["total"], 1)
    aciertos, total = sum(int(d["ok"]) for d in detalle), len(detalle)
    tiempos = [d["segundos"] for d in detalle if d.get("evaluado", True) and not d["motivo"].startswith("error")]
    return {"modelo": modelo, "proveedor": proveedor, "version_banco": VERSION_BANCO,
            "fecha": datetime.datetime.now().isoformat(timespec="seconds"),
            "aciertos": aciertos, "total": total, "pct": round(100 * aciertos / total, 1) if total else 0.0,
            "mediana_s": _mediana(tiempos), "usd": round(sum(d["usd"] for d in detalle), 6),
            "tokens": sum(d["tokens"] for d in detalle), "categorias": categorias, "casos": detalle,
            "incompleto": incompleto}


# ---------------------------------------------------------------- comparación entre modelos
def _usd_por_mil(r: dict) -> float:
    return round(r["usd"] / r["total"] * 1000, 4) if r["total"] else 0.0


def informe_comparativo(resultados: list, empate: float = EMPATE_PUNTOS) -> dict:
    """Tabla de modelos y una recomendación. No usa tamaño, precio de lista ni fama: solo lo medido.
    Entre los que quedan a `empate` puntos o menos del mejor, recomienda el más barato y, a igual costo, el más
    rápido."""
    filas = [{"modelo": r["modelo"], "pct": r["pct"], "aciertos": r["aciertos"], "total": r["total"],
              "mediana_s": r["mediana_s"], "usd": r["usd"], "usd_por_1000": _usd_por_mil(r),
              "incompleto": r.get("incompleto", ""),
              "debiles": [c for c, v in r["categorias"].items() if v["pct"] < 60]} for r in resultados]
    filas.sort(key=lambda f: (-f["pct"], f["usd"], f["mediana_s"]))
    validos = [f for f in filas if not f["incompleto"]]
    if not validos:
        return {"filas": filas, "recomendado": None, "version_banco": VERSION_BANCO,
                "recomendacion": "No hay evaluaciones completas para comparar."}
    mejor = max(f["pct"] for f in validos)
    empatados = [f for f in validos if f["pct"] >= mejor - empate]
    elegido = min(empatados, key=lambda f: (round(f["usd"], 4), f["mediana_s"], -f["pct"]))
    lider = max(validos, key=lambda f: (f["pct"], -f["usd"], -f["mediana_s"]))
    partes = [f"Recomiendo {elegido['modelo']}: {elegido['pct']:g} % de aciertos, mediana de "
              f"{elegido['mediana_s']:g} s y {elegido['usd_por_1000']:g} USD por cada 1000 preguntas."]
    if lider["modelo"] != elegido["modelo"]:
        partes.append(f"{lider['modelo']} acierta {lider['pct'] - elegido['pct']:g} puntos más, una diferencia "
                      f"de {empate:g} puntos o menos que no justifica su costo o su tiempo.")
    rapido = min(empatados, key=lambda f: f["mediana_s"])
    if rapido["modelo"] != elegido["modelo"] and rapido["mediana_s"] * 3 <= elegido["mediana_s"]:
        partes.append(f"Si la velocidad importa más que el costo, {rapido['modelo']} responde en "
                      f"{rapido['mediana_s']:g} s con calidad equivalente, por {rapido['usd_por_1000']:g} USD "
                      f"por cada 1000 preguntas.")
    if elegido["debiles"]:
        partes.append("Ojo con estas categorías, por debajo de 60 %: " + ", ".join(elegido["debiles"]) + ".")
    if mejor < 50:
        partes.append("Ningún modelo pasa la mitad del banco: no confíes en sus respuestas sin revisarlas.")
    fuera = [f["modelo"] for f in filas if f["incompleto"]]
    if fuera:
        partes.append("Sin evaluación completa, no se comparan: " + ", ".join(fuera) + ".")
    return {"filas": filas, "recomendado": elegido["modelo"], "version_banco": VERSION_BANCO,
            "recomendacion": " ".join(partes)}


def comparar(pares: list, casos: list | None = None, **opciones) -> dict:
    """pares = [(proveedor, modelo), ...]. Devuelve {"resultados": [...], "informe": {...}}."""
    resultados = [evaluar(p, m, casos, **opciones) for p, m in pares]
    return {"resultados": resultados, "informe": informe_comparativo(resultados)}


# ---------------------------------------------------------------- historial y regresiones
TABLA = """CREATE TABLE IF NOT EXISTS evaluaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    modelo TEXT NOT NULL,
    version_banco TEXT NOT NULL,
    aciertos INTEGER NOT NULL,
    total INTEGER NOT NULL,
    mediana_s REAL DEFAULT 0,
    usd REAL DEFAULT 0,
    detalle TEXT DEFAULT '{}'
)"""


def _preparar(almacen) -> None:
    almacen._x(TABLA)


def historial(almacen, modelo: str | None = None, version_banco: str | None = None, n: int = 20) -> list:
    _preparar(almacen)
    sql, args = "SELECT * FROM evaluaciones WHERE 1=1", []
    if modelo:
        sql, args = sql + " AND modelo = ?", args + [modelo]
    if version_banco:
        sql, args = sql + " AND version_banco = ?", args + [version_banco]
    filas = almacen._q(sql + " ORDER BY id DESC LIMIT ?", (*args, n))
    for f in filas:
        f["pct"] = round(100 * f["aciertos"] / f["total"], 1) if f["total"] else 0.0
        f["detalle"] = json.loads(f["detalle"] or "{}")
    return filas


def guardar(almacen, resultado: dict, umbral: float = REGRESION_PUNTOS) -> dict:
    """Guarda la evaluación y la compara con la anterior completa del mismo modelo y la misma versión del banco.
    Devuelve {"id", "anterior_pct", "aviso"}; aviso no vacío = regresión de más de `umbral` puntos."""
    _preparar(almacen)
    anteriores = [f for f in historial(almacen, resultado["modelo"], resultado["version_banco"], n=50)
                  if not f["detalle"].get("incompleto")]
    detalle = {k: resultado[k] for k in ("proveedor", "pct", "tokens", "categorias", "casos", "incompleto")}
    cur = almacen._x("INSERT INTO evaluaciones(fecha, modelo, version_banco, aciertos, total, mediana_s, usd, detalle) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (resultado["fecha"], resultado["modelo"], resultado["version_banco"], resultado["aciertos"],
                      resultado["total"], resultado["mediana_s"], resultado["usd"],
                      json.dumps(detalle, ensure_ascii=False)))
    anterior = anteriores[0]["pct"] if anteriores else None
    aviso = ""
    if anterior is not None and not resultado.get("incompleto") and anterior - resultado["pct"] > umbral:
        peores = [c for c, v in resultado["categorias"].items()
                  if v["pct"] < anteriores[0]["detalle"].get("categorias", {}).get(c, {}).get("pct", 0)]
        aviso = (f"Regresión: {resultado['modelo']} bajó de {anterior:g} % a {resultado['pct']:g} % "
                 f"({anterior - resultado['pct']:g} puntos) en el banco {resultado['version_banco']}."
                 + (f" Empeoró en: {', '.join(peores)}." if peores else ""))
        almacen.auditar("regresion_modelo", aviso)
    almacen.auditar("evaluacion", {"modelo": resultado["modelo"], "pct": resultado["pct"],
                                   "version_banco": resultado["version_banco"], "usd": resultado["usd"]})
    return {"id": cur.lastrowid, "anterior_pct": anterior, "aviso": aviso}
