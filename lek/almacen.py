"""Almacén de LUNA: un solo archivo SQLite (datos/luna.db).

Guarda para siempre las conversaciones, la memoria, las llamadas a modelos y la auditoría.
Luna nunca borra conversaciones por su cuenta; "olvidar" un recuerdo lo archiva, no lo destruye.
Cada día se guarda una copia de seguridad en datos/respaldos/.
"""
import datetime
import json
import pathlib
import re
import shutil
import sqlite3
import threading
import unicodedata

VERSION_ESQUEMA = 1

ESQUEMA = """
CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS mensajes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    cliente TEXT NOT NULL DEFAULT 'web',
    rol TEXT NOT NULL,                 -- 'usuario' o 'luna'
    contenido TEXT NOT NULL,
    modelo TEXT DEFAULT '',
    privado INTEGER NOT NULL DEFAULT 0, -- 1 = derivado de memoria o documentos: no se envía a la nube
    origen TEXT DEFAULT 'chat'          -- 'chat', 'migrado'
);
CREATE INDEX IF NOT EXISTS mensajes_fecha ON mensajes(fecha);
CREATE TABLE IF NOT EXISTS resumenes (
    dia TEXT PRIMARY KEY,
    resumen TEXT NOT NULL,
    hasta_id INTEGER NOT NULL,
    modelo TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS recuerdos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dato TEXT NOT NULL,
    fecha TEXT NOT NULL,
    origen TEXT DEFAULT 'chat',
    clase TEXT DEFAULT 'personal',
    archivado INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS llamadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    modelo TEXT NOT NULL,
    proveedor TEXT NOT NULL,
    latencia REAL DEFAULT 0,
    tokens_entrada INTEGER DEFAULT 0,
    tokens_salida INTEGER DEFAULT 0,
    usd REAL DEFAULT 0,
    ok INTEGER NOT NULL DEFAULT 1,
    error TEXT DEFAULT '',
    motivo TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS cambios_modelo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    de TEXT, a TEXT, motivo TEXT
);
CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    accion TEXT NOT NULL,
    detalle TEXT DEFAULT ''
);
"""

VACIAS = set("""que los las del por para con una uno unos unas como mas pero sus esta este esto estos estas
ese esa eso son fue ser hay muy tambien sobre entre cuando donde quien cual dime tengo tiene puedes luna
yo tu mi me te se lo le al el la de en y o a no si ya hoy""".split())


def ahora() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def plano(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower()


def palabras_clave(texto: str) -> list:
    vistas = []
    for w in re.findall(r"[a-z0-9]{3,}", plano(texto)):
        if w not in VACIAS and w not in vistas:
            vistas.append(w)
    return vistas[:8]


class Almacen:
    def __init__(self, carpeta: pathlib.Path):
        self.carpeta = carpeta
        self.ruta = carpeta / "luna.db"
        self._candado = threading.RLock()
        carpeta.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.ruta), check_same_thread=False, timeout=30)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(ESQUEMA)
        self.fts = self._crear_fts()
        self._fijar("version_esquema", str(VERSION_ESQUEMA))

    # ---------------------------------------------------------------- utilidades
    def _crear_fts(self) -> bool:
        """Búsqueda de texto completo (FTS5). Si esta instalación de SQLite no la trae, se usa LIKE."""
        try:
            with self._candado:
                self.con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS mensajes_fts USING fts5("
                                 "contenido, content='mensajes', content_rowid='id', tokenize='unicode61 remove_diacritics 2')")
                self.con.executescript("""
                    CREATE TRIGGER IF NOT EXISTS mensajes_ai AFTER INSERT ON mensajes BEGIN
                      INSERT INTO mensajes_fts(rowid, contenido) VALUES (new.id, new.contenido);
                    END;""")
                self.con.commit()
            return True
        except sqlite3.OperationalError:
            return False

    def _x(self, sql: str, args=()) -> sqlite3.Cursor:
        with self._candado:
            cur = self.con.execute(sql, args)
            self.con.commit()
            return cur

    def _q(self, sql: str, args=()) -> list:
        with self._candado:
            return [dict(r) for r in self.con.execute(sql, args).fetchall()]

    def _fijar(self, clave: str, valor: str) -> None:
        self._x("INSERT INTO meta(clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
                (clave, valor))

    def meta(self, clave: str, defecto: str = "") -> str:
        filas = self._q("SELECT valor FROM meta WHERE clave=?", (clave,))
        return filas[0]["valor"] if filas else defecto

    def auditar(self, accion: str, detalle="") -> None:
        if not isinstance(detalle, str):
            detalle = json.dumps(detalle, ensure_ascii=False)
        self._x("INSERT INTO auditoria(fecha, accion, detalle) VALUES (?, ?, ?)", (ahora(), accion, detalle[:2000]))

    # ---------------------------------------------------------------- conversaciones (para siempre)
    def guardar_mensaje(self, rol: str, contenido: str, cliente: str = "web", modelo: str = "",
                        privado: bool = False, fecha: str = "", origen: str = "chat") -> int:
        cur = self._x("INSERT INTO mensajes(fecha, cliente, rol, contenido, modelo, privado, origen) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (fecha or ahora(), cliente, rol, contenido, modelo, int(privado), origen))
        return cur.lastrowid

    def ultimos_mensajes(self, n: int = 20) -> list:
        """Los últimos mensajes de todas las conversaciones (PC, celular y collar son una sola charla)."""
        filas = self._q("SELECT * FROM mensajes ORDER BY id DESC LIMIT ?", (n,))
        return list(reversed(filas))

    def buscar_mensajes(self, consulta: str, limite: int = 6, antes_de_id: int = 0) -> list:
        """Mensajes pasados relacionados con la consulta, con su fecha."""
        claves = palabras_clave(consulta)
        if not claves:
            return []
        filtro = " AND m.id < ?" if antes_de_id else ""
        extra = (antes_de_id,) if antes_de_id else ()
        if self.fts:
            q = " OR ".join(f'"{w}"' for w in claves)
            try:
                return self._q("SELECT m.* FROM mensajes_fts f JOIN mensajes m ON m.id = f.rowid "
                               f"WHERE mensajes_fts MATCH ?{filtro} ORDER BY bm25(mensajes_fts) LIMIT ?",
                               (q, *extra, limite))
            except sqlite3.OperationalError:
                pass
        condicion = " OR ".join("lower(m.contenido) LIKE ?" for _ in claves)
        return self._q(f"SELECT m.* FROM mensajes m WHERE ({condicion}){filtro} ORDER BY m.id DESC LIMIT ?",
                       (*[f"%{w}%" for w in claves], *extra, limite))

    def mensajes_del_dia(self, dia: str) -> list:
        return self._q("SELECT * FROM mensajes WHERE substr(fecha, 1, 10) = ? ORDER BY id", (dia,))

    def dias_sin_resumen(self, hasta_dia: str) -> list:
        filas = self._q("SELECT DISTINCT substr(fecha, 1, 10) AS dia FROM mensajes "
                        "WHERE substr(fecha, 1, 10) < ? AND substr(fecha, 1, 10) NOT IN (SELECT dia FROM resumenes) "
                        "ORDER BY dia", (hasta_dia,))
        return [f["dia"] for f in filas]

    def guardar_resumen(self, dia: str, resumen: str, hasta_id: int, modelo: str = "") -> None:
        self._x("INSERT INTO resumenes(dia, resumen, hasta_id, modelo) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(dia) DO UPDATE SET resumen=excluded.resumen, hasta_id=excluded.hasta_id, modelo=excluded.modelo",
                (dia, resumen, hasta_id, modelo))

    def resumenes(self, ultimos: int = 7) -> list:
        return list(reversed(self._q("SELECT * FROM resumenes ORDER BY dia DESC LIMIT ?", (ultimos,))))

    def total_mensajes(self) -> int:
        return self._q("SELECT count(*) AS n FROM mensajes")[0]["n"]

    # ---------------------------------------------------------------- recuerdos
    def recordar(self, dato: str, origen: str = "chat", clase: str = "personal") -> bool:
        if any(plano(r["dato"]) == plano(dato) for r in self.recuerdos()):
            return False
        self._x("INSERT INTO recuerdos(dato, fecha, origen, clase) VALUES (?, ?, ?, ?)",
                (dato, datetime.date.today().isoformat(), origen, clase))
        return True

    def recuerdos(self, incluir_archivados: bool = False) -> list:
        sql = "SELECT * FROM recuerdos" + ("" if incluir_archivados else " WHERE archivado = 0") + " ORDER BY id"
        return self._q(sql)

    def archivar_recuerdos(self, texto: str) -> int:
        """'Olvidar' no destruye: archiva, para que se pueda recuperar."""
        clave = plano(texto).strip()
        ids = [r["id"] for r in self.recuerdos() if clave and clave in plano(r["dato"])]
        for i in ids:
            self._x("UPDATE recuerdos SET archivado = 1 WHERE id = ?", (i,))
        return len(ids)

    # ---------------------------------------------------------------- métricas de modelos
    def registrar_llamada(self, modelo: str, proveedor: str, latencia: float, tokens_entrada: int = 0,
                          tokens_salida: int = 0, usd: float = 0.0, ok: bool = True, error: str = "",
                          motivo: str = "") -> None:
        self._x("INSERT INTO llamadas(fecha, modelo, proveedor, latencia, tokens_entrada, tokens_salida, usd, ok, error, motivo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ahora(), modelo, proveedor, round(latencia, 2), tokens_entrada, tokens_salida, round(usd, 6),
                 int(ok), error[:500], motivo[:300]))

    def estadisticas_modelos(self, dias: int = 30) -> dict:
        desde = (datetime.datetime.now() - datetime.timedelta(days=dias)).isoformat(timespec="seconds")
        filas = self._q("SELECT modelo, count(*) AS llamadas, sum(ok) AS exitos, "
                        "avg(CASE WHEN ok = 1 THEN latencia END) AS latencia_media, "
                        "sum(usd) AS usd, sum(tokens_entrada) AS tokens_entrada, sum(tokens_salida) AS tokens_salida "
                        "FROM llamadas WHERE fecha >= ? GROUP BY modelo", (desde,))
        return {f["modelo"]: f for f in filas}

    def gasto_del_mes(self) -> float:
        mes = datetime.date.today().strftime("%Y-%m")
        return round(self._q("SELECT coalesce(sum(usd), 0) AS u FROM llamadas WHERE substr(fecha, 1, 7) = ?",
                             (mes,))[0]["u"], 4)

    def ultimas_llamadas(self, n: int = 10) -> list:
        return self._q("SELECT * FROM llamadas ORDER BY id DESC LIMIT ?", (n,))

    def registrar_cambio_modelo(self, de: str, a: str, motivo: str) -> None:
        self._x("INSERT INTO cambios_modelo(fecha, de, a, motivo) VALUES (?, ?, ?, ?)", (ahora(), de, a, motivo[:300]))

    def cambios_modelo(self, n: int = 15) -> list:
        return self._q("SELECT * FROM cambios_modelo ORDER BY id DESC LIMIT ?", (n,))

    # ---------------------------------------------------------------- respaldos
    def respaldar(self, conservar: int = 14) -> pathlib.Path:
        """Una copia por día en datos/respaldos/; guarda las últimas `conservar`."""
        carpeta = self.carpeta / "respaldos"
        carpeta.mkdir(exist_ok=True)
        destino = carpeta / f"luna-{datetime.date.today().isoformat()}.db"
        if not destino.exists():
            with self._candado:
                copia = sqlite3.connect(str(destino))
                self.con.backup(copia)
                copia.close()
        for viejo in sorted(carpeta.glob("luna-*.db"))[:-conservar]:
            viejo.unlink()
        return destino

    # ---------------------------------------------------------------- migración desde la versión 0 (JSON)
    def migrar_desde_json(self) -> dict:
        """Una sola vez: copia datos/ a datos/respaldo_v0/ y pasa los JSON a SQLite.
        Si los conteos no cuadran, deshace y deja todo como estaba."""
        if self.meta("migrado_v0") == "si":
            return {"estado": "ya migrado"}
        respaldo = self.carpeta / "respaldo_v0"
        if not respaldo.exists():
            respaldo.mkdir()
            for f in self.carpeta.iterdir():
                if f.is_file() and f.suffix in (".json", ".jsonl", ".md", ".txt"):
                    shutil.copy2(f, respaldo / f.name)
        informe = {"mensajes": 0, "recuerdos": 0, "llamadas": 0}
        try:
            with self._candado:
                # conversaciones registradas desde la instalación
                registro = self.carpeta / "conversaciones.jsonl"
                esperados = 0
                if registro.exists():
                    for linea in registro.read_text(encoding="utf-8").splitlines():
                        if not linea.strip():
                            continue
                        d = json.loads(linea)
                        for rol, texto in (("usuario", d.get("usuario", "")), ("luna", d.get("luna", ""))):
                            if texto:
                                esperados += 1
                                self.con.execute("INSERT INTO mensajes(fecha, cliente, rol, contenido, origen) "
                                                 "VALUES (?, ?, ?, ?, 'migrado')",
                                                 (d.get("fecha", ahora()), d.get("cliente", "web"), rol, texto))
                                informe["mensajes"] += 1
                # memoria
                memoria = self.carpeta / "memoria.json"
                if memoria.exists():
                    for r in json.loads(memoria.read_text(encoding="utf-8")).get("datos", []):
                        self.con.execute("INSERT INTO recuerdos(dato, fecha, origen) VALUES (?, ?, 'migrado')",
                                         (r["dato"], r.get("fecha", datetime.date.today().isoformat())))
                        informe["recuerdos"] += 1
                # gasto anterior en Claude
                estado = self.carpeta / "estado.json"
                if estado.exists():
                    g = json.loads(estado.read_text(encoding="utf-8")).get("claude")
                    if g and g.get("consultas"):
                        self.con.execute("INSERT INTO llamadas(fecha, modelo, proveedor, tokens_entrada, tokens_salida, usd, motivo) "
                                         "VALUES (?, 'claude (antes de la migración)', 'claude', ?, ?, ?, 'migrado')",
                                         (ahora(), g.get("tokens_entrada", 0), g.get("tokens_salida", 0), g.get("usd", 0)))
                        informe["llamadas"] += 1
                n = self.con.execute("SELECT count(*) FROM mensajes WHERE origen = 'migrado'").fetchone()[0]
                if n != esperados:
                    raise RuntimeError(f"conteo de mensajes no cuadra: {n} de {esperados}")
                if self.fts:
                    self.con.execute("INSERT INTO mensajes_fts(mensajes_fts) VALUES ('rebuild')")
                self.con.execute("INSERT INTO meta(clave, valor) VALUES ('migrado_v0', 'si') "
                                 "ON CONFLICT(clave) DO UPDATE SET valor='si'")
                self.con.commit()
        except Exception as e:
            self.con.rollback()
            return {"estado": "error", "detalle": str(e)}
        self.auditar("migracion_v0", informe)
        return {"estado": "migrado", **informe}
