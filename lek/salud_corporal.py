"""Salud corporal de LUNA: el pulso que manda el Apple Watch (vía un Atajo del iPhone).

PRIVACIDAD: todo lo de este módulo es dato de salud. Vive SOLO en datos/luna.db, en el PC.
Nunca se manda a la nube: la herramienta mi_pulso() es SIEMPRE privada, sin importar los ajustes.

NO ES UN DISPOSITIVO MÉDICO. Los avisos son sobrios, informativos, y solo sugieren consultar a un
profesional si algo persiste. No diagnostican nada.

Tablas:
  pulso(id, fecha_muestra, fecha_recibido, bpm, origen)  -> muestras de los últimos 90 días
  pulso_diario(dia, muestras, promedio, minimo, maximo, reposo, origen) -> resumen por día de lo más viejo
Las fechas de muestra se guardan en UTC ("AAAA-MM-DDTHH:MM:SSZ") para que ordenen y dedupliquen bien,
vengan con la zona horaria que vengan desde iOS.
"""
import datetime
import json
import re

BPM_MIN, BPM_MAX = 25, 230
DIAS_RETENCION = 90
UMBRAL_ALTO, UMBRAL_BAJO = 120, 40          # lpm
MINUTOS_SOSTENIDO = 10                      # cuánto tiempo seguido debe durar para avisar
MIN_MUESTRAS_SOSTENIDO = 3                  # un pico aislado (1-2 muestras) nunca avisa
HUECO_MAXIMO_MIN = 15                       # si entre dos muestras pasa más que esto, la racha se corta
CAMBIO_TENDENCIA = 5                        # lpm de diferencia entre la 1.ª y la 2.ª mitad para decir que sube/baja
FUTURO_TOLERADO = datetime.timedelta(minutes=10)

HERRAMIENTAS_SIEMPRE_PRIVADAS = {"mi_pulso"}
HERRAMIENTA_MI_PULSO = {"type": "function", "function": {
    "name": "mi_pulso",
    "description": "Resumen del pulso (frecuencia cardiaca) que mandó el Apple Watch del usuario: actual, promedio "
                   "de la última hora, tendencia, reposo estimado y avisos. Es información de salud PRIVADA. "
                   "No es un diagnóstico médico.",
    "parameters": {"type": "object", "properties": {
        "minutos": {"type": "integer", "description": "ventana a resumir, en minutos (por defecto 60)"}},
        "required": []}}}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS pulso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_muestra TEXT NOT NULL,          -- UTC, AAAA-MM-DDTHH:MM:SSZ
    fecha_recibido TEXT NOT NULL,         -- hora local del PC
    bpm REAL NOT NULL,
    origen TEXT NOT NULL DEFAULT 'apple_watch'
);
CREATE UNIQUE INDEX IF NOT EXISTS pulso_fecha ON pulso(fecha_muestra);
CREATE TABLE IF NOT EXISTS pulso_diario (
    dia TEXT PRIMARY KEY,                 -- día local AAAA-MM-DD
    muestras INTEGER NOT NULL,
    promedio REAL NOT NULL,
    minimo REAL NOT NULL,
    maximo REAL NOT NULL,
    reposo REAL,
    origen TEXT DEFAULT ''
);
"""

AVISO_NO_MEDICO = ("Luna no es un dispositivo médico y el reloj puede equivocarse. Si se repite o persiste, "
                   "consúltalo con un profesional de salud; si te sientes mal (dolor en el pecho, mareo, "
                   "falta de aire), busca atención de inmediato.")


class ErrorPulso(ValueError):
    """Dato de pulso no válido (fuera de rango, sin fecha legible...)."""


# ---------------------------------------------------------------- fechas y números
def _zona_local() -> datetime.tzinfo:
    return datetime.datetime.now().astimezone().tzinfo


def leer_fecha(valor, zona: datetime.tzinfo = None) -> datetime.datetime:
    """Convierte lo que mande iOS (u otro cliente) a datetime con zona horaria, en UTC.

    Acepta ISO 8601 con o sin zona ('2026-11-24T10:15:00-05:00', '...Z', '...-0500', con espacio en vez de T,
    con fracciones de segundo), y números de época (segundos o milisegundos). Sin zona = hora local del PC."""
    zona = zona or _zona_local()
    if isinstance(valor, datetime.datetime):
        f = valor
    elif isinstance(valor, (int, float)) and not isinstance(valor, bool):
        segundos = valor / 1000 if valor > 1e11 else valor
        f = datetime.datetime.fromtimestamp(segundos, tz=datetime.timezone.utc)
    elif isinstance(valor, str) and valor.strip():
        t = valor.strip()
        if re.fullmatch(r"\d{9,13}(\.\d+)?", t):
            return leer_fecha(float(t), zona)
        t = re.sub(r"^(\d{4}-\d{2}-\d{2}) +(\d)", r"\1T\2", t)        # '2026-11-24 10:15' -> T
        t = re.sub(r" *(UTC|GMT)$", "Z", t, flags=re.I)
        t = re.sub(r" +([+-]\d{2}:?\d{2})$", r"\1", t)                 # '10:15:00 -0500' -> '10:15:00-0500'
        t = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", t)                # -0500 -> -05:00
        t = re.sub(r"(\.\d{6})\d+", r"\1", t)                          # más de 6 decimales
        try:
            f = datetime.datetime.fromisoformat(t)
        except ValueError:
            raise ErrorPulso(f"fecha ilegible: {valor!r} (usa ISO 8601, p. ej. 2026-11-24T10:15:00-05:00)")
    else:
        raise ErrorPulso("falta la fecha de la muestra")
    if f.tzinfo is None:
        f = f.replace(tzinfo=zona)
    return f.astimezone(datetime.timezone.utc).replace(microsecond=0)


def _utc_texto(f: datetime.datetime) -> str:
    return f.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _desde_utc(texto: str) -> datetime.datetime:
    return datetime.datetime.strptime(texto, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)


def leer_bpm(valor) -> float:
    """72, 72.4, '72', '72,5', '72 lpm', '72 count/min' -> número. Valida el rango 25–230."""
    if isinstance(valor, bool):
        raise ErrorPulso("bpm no válido")
    if isinstance(valor, (int, float)):
        n = float(valor)
    else:
        m = re.search(r"\d+(?:[.,]\d+)?", str(valor or ""))
        if not m:
            raise ErrorPulso(f"bpm no válido: {valor!r}")
        n = float(m.group(0).replace(",", "."))
    if n != n or not (BPM_MIN <= n <= BPM_MAX):
        raise ErrorPulso(f"bpm fuera de rango ({BPM_MIN}–{BPM_MAX}): {valor!r}")
    return round(n, 1)


def _percentil(valores: list, p: float) -> float:
    """Percentil con interpolación lineal (p entre 0 y 100)."""
    v = sorted(valores)
    if len(v) == 1:
        return v[0]
    k = (len(v) - 1) * p / 100
    i = int(k)
    return v[i] + (v[min(i + 1, len(v) - 1)] - v[i]) * (k - i)


# ---------------------------------------------------------------- el módulo
class SaludCorporal:
    """Pulso del Apple Watch guardado en el Almacen de Luna (siempre local)."""

    def __init__(self, almacen, zona: datetime.tzinfo = None, reloj=None):
        self.almacen = almacen
        self.zona = zona or _zona_local()
        self._reloj = reloj or (lambda: datetime.datetime.now(datetime.timezone.utc))
        with almacen._candado:
            almacen.con.executescript(ESQUEMA)
            almacen.con.commit()

    # ------------------------------------------------------------ utilidades
    def ahora(self) -> datetime.datetime:
        return self._reloj().astimezone(datetime.timezone.utc).replace(microsecond=0)

    def _local(self, f: datetime.datetime) -> datetime.datetime:
        return f.astimezone(self.zona)

    def _q(self, sql: str, args=()) -> list:
        with self.almacen._candado:
            return [dict(r) for r in self.almacen.con.execute(sql, args).fetchall()]

    def _muestras(self, desde: datetime.datetime, hasta: datetime.datetime = None) -> list:
        hasta = hasta or self.ahora() + FUTURO_TOLERADO
        filas = self._q("SELECT fecha_muestra, bpm, origen FROM pulso WHERE fecha_muestra >= ? AND fecha_muestra <= ? "
                        "ORDER BY fecha_muestra", (_utc_texto(desde), _utc_texto(hasta)))
        for f in filas:
            f["dt"] = _desde_utc(f["fecha_muestra"])
        return filas

    # ------------------------------------------------------------ registrar
    def registrar(self, bpm, fecha=None, origen: str = "apple_watch") -> bool:
        """Guarda una muestra. Devuelve False si ya existía una con la misma fecha. ErrorPulso si no es válida."""
        valor = leer_bpm(bpm)
        momento = leer_fecha(fecha, self.zona) if fecha not in (None, "") else self.ahora()
        if momento > self.ahora() + FUTURO_TOLERADO:
            raise ErrorPulso(f"la fecha {fecha!r} está en el futuro")
        origen = (str(origen or "apple_watch").strip() or "apple_watch")[:40]
        with self.almacen._candado:
            cur = self.almacen.con.execute(
                "INSERT OR IGNORE INTO pulso(fecha_muestra, fecha_recibido, bpm, origen) VALUES (?, ?, ?, ?)",
                (_utc_texto(momento), self._local(self.ahora()).replace(tzinfo=None).isoformat(timespec="seconds"),
                 valor, origen))
            self.almacen.con.commit()
        return cur.rowcount == 1

    def registrar_lote(self, muestras, origen: str = "apple_watch") -> dict:
        """Guarda una lista [{fecha, bpm}] tal como la manda un Atajo de iOS. Deduplica por fecha.

        También acepta: una cadena JSON con esa lista, o texto con una muestra por línea 'fecha;bpm'
        (plan B del Atajo). Devuelve el conteo: recibidas, guardadas, duplicadas, rechazadas y errores."""
        lista = _normalizar_lote(muestras)
        informe = {"recibidas": len(lista), "guardadas": 0, "duplicadas": 0, "rechazadas": 0, "errores": []}
        for i, m in enumerate(lista):
            try:
                if not isinstance(m, dict):
                    raise ErrorPulso("cada muestra debe ser {fecha, bpm}")
                fecha = m.get("fecha", m.get("date", m.get("inicio", m.get("startDate"))))
                bpm = m.get("bpm", m.get("valor", m.get("value")))
                if fecha in (None, ""):
                    raise ErrorPulso("falta la fecha de la muestra")
                if self.registrar(bpm, fecha, m.get("origen") or origen):
                    informe["guardadas"] += 1
                else:
                    informe["duplicadas"] += 1
            except ErrorPulso as e:
                informe["rechazadas"] += 1
                if len(informe["errores"]) < 10:
                    informe["errores"].append(f"muestra {i + 1}: {e}")
        # la auditoría guarda conteos, nunca los valores de salud
        self.almacen.auditar("pulso_lote", {k: informe[k] for k in ("recibidas", "guardadas", "duplicadas", "rechazadas")}
                             | {"origen": str(origen)[:40]})
        self._retener_si_toca()
        return informe

    # ------------------------------------------------------------ leer
    def serie(self, minutos: int = 60) -> list:
        desde = self.ahora() - datetime.timedelta(minutes=max(1, int(minutos)))
        return [{"fecha": self._local(f["dt"]).isoformat(timespec="seconds"), "bpm": f["bpm"]}
                for f in self._muestras(desde)]

    def resumen(self, minutos: int = 60) -> dict:
        """{actual, promedio, minimo, maximo, muestras, tendencia, fecha_ultima} de los últimos `minutos`.
        'actual' y 'fecha_ultima' son de la última muestra que haya, aunque sea más vieja que la ventana."""
        desde = self.ahora() - datetime.timedelta(minutes=max(1, int(minutos)))
        filas = self._muestras(desde)
        ultima = self._q("SELECT fecha_muestra, bpm FROM pulso WHERE fecha_muestra <= ? ORDER BY fecha_muestra DESC "
                         "LIMIT 1", (_utc_texto(self.ahora() + FUTURO_TOLERADO),))
        valores = [f["bpm"] for f in filas]
        return {
            "actual": ultima[0]["bpm"] if ultima else None,
            "promedio": round(sum(valores) / len(valores), 1) if valores else None,
            "minimo": min(valores) if valores else None,
            "maximo": max(valores) if valores else None,
            "muestras": len(valores),
            "tendencia": _tendencia(valores),
            "fecha_ultima": (self._local(_desde_utc(ultima[0]["fecha_muestra"])).isoformat(timespec="seconds")
                             if ultima else None),
        }

    def reposo_estimado(self, horas: int = 24) -> float | None:
        """Pulso de reposo ESTIMADO: percentil 10 de las últimas `horas`. No es la medición de Apple
        (que usa sensores de movimiento); es una aproximación. Necesita al menos 10 muestras."""
        valores = [f["bpm"] for f in self._muestras(self.ahora() - datetime.timedelta(hours=horas))]
        if len(valores) < 10:
            return None
        return round(_percentil(valores, 10), 1)

    def alertas(self, minutos: int = 60) -> list:
        """Rachas sostenidas (≥10 min y ≥3 muestras seguidas) por encima de 120 o por debajo de 40.
        Un pico aislado no avisa. El reloj no le dice a Luna si estabas en reposo: el aviso lo pregunta."""
        filas = self._muestras(self.ahora() - datetime.timedelta(minutes=max(MINUTOS_SOSTENIDO, int(minutos))))
        avisos = []
        for tipo, condicion in (("alto", lambda b: b > UMBRAL_ALTO), ("bajo", lambda b: b < UMBRAL_BAJO)):
            for racha in _rachas(filas, condicion):
                duracion = (racha[-1]["dt"] - racha[0]["dt"]).total_seconds() / 60
                if duracion < MINUTOS_SOSTENIDO or len(racha) < MIN_MUESTRAS_SOSTENIDO:
                    continue
                desde, hasta = self._local(racha[0]["dt"]), self._local(racha[-1]["dt"])
                extremo = max(f["bpm"] for f in racha) if tipo == "alto" else min(f["bpm"] for f in racha)
                if tipo == "alto":
                    texto = (f"Según el reloj, tu pulso estuvo por encima de {UMBRAL_ALTO} lpm unos {round(duracion)} "
                             f"minutos seguidos ({desde:%H:%M}–{hasta:%H:%M}, máximo {extremo:g}). Si no estabas "
                             f"haciendo ejercicio ni acabando de hacerlo, tómalo con calma y observa. ")
                else:
                    texto = (f"Según el reloj, tu pulso estuvo por debajo de {UMBRAL_BAJO} lpm unos {round(duracion)} "
                             f"minutos seguidos ({desde:%H:%M}–{hasta:%H:%M}, mínimo {extremo:g}). ")
                avisos.append({"tipo": tipo, "desde": desde.isoformat(timespec="seconds"),
                               "hasta": hasta.isoformat(timespec="seconds"), "minutos": round(duracion),
                               "muestras": len(racha), "bpm_extremo": extremo, "mensaje": texto + AVISO_NO_MEDICO})
        return sorted(avisos, key=lambda a: a["desde"])

    def respuesta_api(self, minutos: int = 60) -> dict:
        """Lo que devuelve GET /api/salud/pulso?minutos=60."""
        minutos = min(max(1, int(minutos)), 60 * 24 * 7)
        return {"resumen": self.resumen(minutos), "serie": self.serie(minutos),
                "reposo_24h": self.reposo_estimado(), "alertas": self.alertas(minutos)}

    # ------------------------------------------------------------ herramienta (PRIVADA)
    def mi_pulso(self, minutos=60) -> str:
        """Herramienta de Luna: el pulso en una frase (más un aviso sobrio si hay una racha sostenida).
        PRIVADA: su resultado nunca debe ir a un modelo en la nube."""
        try:
            minutos = int(minutos)
        except (TypeError, ValueError):
            minutos = 60
        r = self.resumen(minutos)
        if r["actual"] is None:
            return ("No tengo datos de pulso todavía: en el iPhone corre el Atajo «Enviar pulso a Luna» "
                    "(o di «Oye Siri, envía mi pulso a Luna»).")
        ultima = datetime.datetime.fromisoformat(r["fecha_ultima"])
        hace = round((self.ahora() - ultima).total_seconds() / 60)
        cuando = f"hace {hace} min" if hace < 120 else f"el {ultima:%Y-%m-%d} a las {ultima:%H:%M}"
        frase = f"Tu último pulso fue {r['actual']:g} lpm ({cuando})"
        if r["muestras"]:
            frase += (f"; en los últimos {minutos} min promedió {r['promedio']:g} (entre {r['minimo']:g} y "
                      f"{r['maximo']:g}, {r['muestras']} muestras, {r['tendencia']})")
        else:
            frase += f"; no hay muestras de los últimos {minutos} min"
        reposo = self.reposo_estimado()
        if reposo is not None:
            frase += f", y tu reposo estimado de las últimas 24 h es {reposo:g} lpm"
        frase += "."
        avisos = self.alertas(minutos)
        if avisos:
            frase += " " + avisos[-1]["mensaje"]
        return frase

    # ------------------------------------------------------------ retención: 90 días, luego resumen diario
    def retener(self, dias: int = DIAS_RETENCION) -> dict:
        """Las muestras con más de `dias` pasan a un resumen por día (pulso_diario) y se borran del detalle."""
        corte = _utc_texto(self.ahora() - datetime.timedelta(days=dias))
        viejas = self._q("SELECT fecha_muestra, bpm, origen FROM pulso WHERE fecha_muestra < ? ORDER BY fecha_muestra",
                         (corte,))
        por_dia = {}
        for f in viejas:
            dia = self._local(_desde_utc(f["fecha_muestra"])).date().isoformat()
            por_dia.setdefault(dia, []).append(f)
        with self.almacen._candado:
            try:
                for dia, filas in por_dia.items():
                    valores = [f["bpm"] for f in filas]
                    origenes = ",".join(sorted({f["origen"] for f in filas}))[:80]
                    previo = self.almacen.con.execute("SELECT * FROM pulso_diario WHERE dia = ?", (dia,)).fetchone()
                    n, suma = len(valores), sum(valores)
                    minimo, maximo = min(valores), max(valores)
                    reposo = round(_percentil(valores, 10), 1) if n >= 10 else None
                    if previo:  # el día ya se resumió en parte (llegaron muestras viejas después): se combinan
                        n2 = previo["muestras"] + n
                        suma += previo["promedio"] * previo["muestras"]
                        minimo, maximo = min(minimo, previo["minimo"]), max(maximo, previo["maximo"])
                        reposo = previo["reposo"] if reposo is None else (
                            reposo if previo["reposo"] is None else min(reposo, previo["reposo"]))
                        n = n2
                    self.almacen.con.execute(
                        "INSERT INTO pulso_diario(dia, muestras, promedio, minimo, maximo, reposo, origen) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(dia) DO UPDATE SET muestras=excluded.muestras, "
                        "promedio=excluded.promedio, minimo=excluded.minimo, maximo=excluded.maximo, "
                        "reposo=excluded.reposo, origen=excluded.origen",
                        (dia, n, round(suma / n, 1), minimo, maximo, reposo, origenes))
                self.almacen.con.execute("DELETE FROM pulso WHERE fecha_muestra < ?", (corte,))
                self.almacen.con.commit()
            except Exception:
                self.almacen.con.rollback()
                raise
        if viejas:
            self.almacen.auditar("pulso_retencion", {"muestras": len(viejas), "dias": len(por_dia)})
        return {"muestras_resumidas": len(viejas), "dias": len(por_dia)}

    def diario(self, ultimos: int = 30) -> list:
        return list(reversed(self._q("SELECT * FROM pulso_diario ORDER BY dia DESC LIMIT ?", (ultimos,))))

    def _retener_si_toca(self) -> None:
        hoy = self._local(self.ahora()).date().isoformat()
        if self.almacen.meta("pulso_retencion") != hoy:
            self.retener()
            self.almacen._fijar("pulso_retencion", hoy)


# ---------------------------------------------------------------- ayudas internas
def _normalizar_lote(muestras) -> list:
    if muestras is None:
        return []
    if isinstance(muestras, dict):  # {"muestras": [...]} o {"fechas": ..., "bpms": ...}
        if "muestras" in muestras:
            return _normalizar_lote(muestras["muestras"])
        if "fechas" in muestras and "bpms" in muestras:
            fechas, bpms = _como_lista(muestras["fechas"]), _como_lista(muestras["bpms"])
            if len(fechas) != len(bpms):
                raise ErrorPulso(f"'fechas' ({len(fechas)}) y 'bpms' ({len(bpms)}) no tienen el mismo largo")
            return [{"fecha": f, "bpm": b} for f, b in zip(fechas, bpms)]
        if "texto" in muestras:
            return _normalizar_lote(muestras["texto"])
        return [muestras]
    if isinstance(muestras, str):
        t = muestras.strip()
        if t.startswith("[") or t.startswith("{"):
            try:
                return _normalizar_lote(json.loads(t))
            except json.JSONDecodeError:
                pass
        lista = []
        for linea in t.splitlines():
            if not linea.strip():
                continue
            partes = re.split(r"\s*[;\t|]\s*", linea.strip())
            if len(partes) == 2:
                lista.append({"fecha": partes[0], "bpm": partes[1]})
            else:
                lista.append({"fecha": None, "bpm": linea})
        return lista
    return list(muestras)


def _como_lista(valor) -> list:
    if isinstance(valor, list):
        return valor
    return [x.strip() for x in str(valor or "").splitlines() if x.strip()]


def _tendencia(valores: list) -> str:
    if len(valores) < 4:
        return "sin datos suficientes"
    mitad = len(valores) // 2
    primera, segunda = valores[:mitad], valores[-mitad:]
    diferencia = sum(segunda) / len(segunda) - sum(primera) / len(primera)
    if diferencia >= CAMBIO_TENDENCIA:
        return "subiendo"
    if diferencia <= -CAMBIO_TENDENCIA:
        return "bajando"
    return "estable"


def _rachas(filas: list, condicion) -> list:
    """Grupos de muestras seguidas que cumplen la condición, sin huecos de más de HUECO_MAXIMO_MIN."""
    rachas, actual = [], []
    for f in filas:
        if condicion(f["bpm"]) and (not actual or
                                    (f["dt"] - actual[-1]["dt"]).total_seconds() <= HUECO_MAXIMO_MIN * 60):
            actual.append(f)
        else:
            if actual:
                rachas.append(actual)
            actual = [f] if condicion(f["bpm"]) else []
    if actual:
        rachas.append(actual)
    return rachas
