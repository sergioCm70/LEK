"""Memoria semántica 100 % local de LUNA.

Convierte mensajes, recuerdos y trozos de documentos en vectores (embeddings) con un modelo de
Ollama que corre en el PC, los guarda en la tabla `vectores` de datos/luna.db y busca por
significado (similitud coseno), no solo por palabras. Nada sale del PC: el embebedor se niega a
hablar con un servidor que no sea local o de la red privada.

Si Ollama o el modelo de embeddings no están, nada falla: la búsqueda cae a la búsqueda por
palabras de siempre (FTS5 de Almacen.buscar_mensajes).

Funciona con numpy (rápido) o sin él (puro Python con array + math.sumprod).

Uso mínimo:
    memoria = MemoriaSemantica(ALMACEN, EmbebedorOllama(OLLAMA))
    memoria.indexar_pendientes(200)               # incremental: solo lo nuevo
    memoria.buscar_hibrido("lo que dije de mi perro", k=6, tipos=("mensaje",))
"""
import array
import heapq
import ipaddress
import json
import math
import operator
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from lek.almacen import ahora, palabras_clave, plano

try:  # numpy es opcional
    import numpy as _np
except Exception:  # pragma: no cover - depende de la instalación
    _np = None

TIPOS = ("mensaje", "documento", "recuerdo")
MODELO_POR_DEFECTO = "nomic-embed-text"
RRF_C = 60  # constante clásica de la fusión por rango recíproco

ESQUEMA_VECTORES = """
CREATE TABLE IF NOT EXISTS vectores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,   -- AUTOINCREMENT: los id nunca se reutilizan (lo usa la caché)
    tipo TEXT NOT NULL,                     -- 'mensaje', 'documento' o 'recuerdo'
    ref TEXT NOT NULL,                      -- id del mensaje / recuerdo, o 'archivo#n' del trozo
    texto TEXT NOT NULL,
    vector BLOB NOT NULL,                   -- float32 little-endian, ya normalizado (norma 1)
    modelo TEXT NOT NULL,
    fecha TEXT NOT NULL,
    UNIQUE (tipo, ref, modelo)
);
CREATE INDEX IF NOT EXISTS vectores_modelo_tipo ON vectores(modelo, tipo);
"""

_sumprod = getattr(math, "sumprod", None)  # Python 3.12+: producto punto en C


def _producto(a, b) -> float:
    if _sumprod is not None:
        return _sumprod(a, b)
    return sum(map(operator.mul, a, b))


def _normalizado(valores) -> array.array:
    """Vector float32 de norma 1 (así coseno = producto punto). Vector nulo -> array vacío."""
    v = array.array("f", valores)
    norma = math.sqrt(_producto(v, v)) if len(v) else 0.0
    if not norma or not math.isfinite(norma):
        return array.array("f")
    return array.array("f", [x / norma for x in v])


def _a_bytes(v: array.array) -> bytes:
    if sys.byteorder == "big":  # en disco siempre little-endian
        v = array.array("f", v)
        v.byteswap()
    return v.tobytes()


def _de_bytes(b: bytes) -> array.array:
    v = array.array("f")
    v.frombytes(b)
    if sys.byteorder == "big":
        v.byteswap()
    return v


class ErrorEmbebedor(Exception):
    pass


# ====================================================================== embebedor local (Ollama)
def es_local(url: str) -> bool:
    """True si el servidor está en este PC o en la red privada (LAN o Tailscale 100.64/10)."""
    host = (urllib.parse.urlparse(url).hostname or "").strip("[]").lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10")


class EmbebedorOllama:
    """Pide embeddings a Ollama (POST /api/embed). Solo a servidores locales."""

    def __init__(self, url: str = "", modelo: str = MODELO_POR_DEFECTO, lote: int = 16,
                 timeout: float = 10.0, timeout_sondeo: float = 1.5, keep_alive: str = "2m",
                 permitir_remoto: bool = False, espera_tras_fallo: float = 60.0):
        self.url = (url or os.getenv("OLLAMA_URL") or "http://127.0.0.1:11434").strip().rstrip("/")
        self.modelo = modelo
        self.lote = max(1, int(lote))
        self.timeout = timeout
        self.timeout_sondeo = timeout_sondeo
        self.keep_alive = keep_alive          # corto: con la RAM al 90 % conviene que se descargue pronto
        self.espera_tras_fallo = espera_tras_fallo
        self.local = permitir_remoto or es_local(self.url)
        self.motivo = "" if self.local else f"{self.url} no es local: la memoria semántica no sale del PC"
        self._estado = None                   # (disponible: bool, momento)
        self._candado = threading.Lock()
        # sin proxies: todo es local, y un proxy del sistema podría desviar la petición
        self._abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _pedir(self, ruta: str, datos=None, timeout: float = 10.0) -> dict:
        cuerpo = None if datos is None else json.dumps(datos).encode("utf-8")
        req = urllib.request.Request(self.url + ruta, data=cuerpo,
                                     headers={"Content-Type": "application/json"},
                                     method="GET" if datos is None else "POST")
        with self._abridor.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _marcar(self, ok: bool, motivo: str = "") -> None:
        with self._candado:
            self._estado = (ok, time.monotonic())
            if motivo or ok:
                self.motivo = motivo

    def disponible(self, forzar: bool = False) -> bool:
        """¿Ollama responde y tiene el modelo? Se recuerda la respuesta un rato para no frenar cada turno."""
        if not self.local:
            return False
        with self._candado:
            estado = self._estado
        if estado and not forzar and time.monotonic() - estado[1] < self.espera_tras_fallo:
            return estado[0]
        try:
            nombres = [m.get("name", "") for m in self._pedir("/api/tags", timeout=self.timeout_sondeo).get("models", [])]
        except Exception as e:
            self._marcar(False, f"Ollama no responde en {self.url}: {e}")
            return False
        # 'nomic-embed-text' es lo mismo que 'nomic-embed-text:latest' para Ollama
        aceptados = {self.modelo, self.modelo if ":" in self.modelo else self.modelo + ":latest"}
        ok = any(n in aceptados for n in nombres)
        self._marcar(ok, "" if ok else f"falta el modelo: ollama pull {self.modelo}")
        return ok

    def _prefijo(self, consulta: bool) -> str:
        # nomic-embed-text está entrenado con estos prefijos; mejoran bastante la búsqueda
        if "nomic" in self.modelo:
            return "search_query: " if consulta else "search_document: "
        return ""

    def embeber(self, textos: list, consulta: bool = False) -> list:
        if not self.local:
            raise ErrorEmbebedor(self.motivo)
        prefijo = self._prefijo(consulta)
        salida = []
        for i in range(0, len(textos), self.lote):
            parte = [prefijo + t for t in textos[i:i + self.lote]]
            try:
                r = self._pedir("/api/embed", {"model": self.modelo, "input": parte, "truncate": True,
                                               "keep_alive": self.keep_alive}, timeout=self.timeout)
            except (urllib.error.URLError, OSError, ValueError) as e:
                self._marcar(False, f"/api/embed falló: {e}")
                raise ErrorEmbebedor(str(e)) from e
            vectores = r.get("embeddings") or []
            if len(vectores) != len(parte):
                self._marcar(False, "respuesta de /api/embed incompleta")
                raise ErrorEmbebedor(f"Ollama devolvió {len(vectores)} vectores para {len(parte)} textos")
            salida.extend(vectores)
        return salida


# ====================================================================== memoria semántica
class MemoriaSemantica:
    def __init__(self, almacen, embebedor=None, usar_numpy=None, minimo: float = 0.0,
                 max_caracteres: int = 2000):
        self.almacen = almacen
        self.embebedor = embebedor
        self.np = _np if (usar_numpy is None or usar_numpy) else None
        if usar_numpy and _np is None:
            raise RuntimeError("se pidió numpy pero no está instalado")
        self.minimo = minimo                    # puntaje coseno mínimo para aceptar un resultado semántico
        self.max_caracteres = max_caracteres
        self._cache = None
        self._candado_cache = threading.Lock()
        self._candado_indexar = threading.Lock()
        with almacen._candado:
            almacen.con.executescript(ESQUEMA_VECTORES)
            almacen.con.commit()

    # ---------------------------------------------------------------- utilidades
    @property
    def modelo(self) -> str:
        return getattr(self.embebedor, "modelo", "") or "desconocido"

    def _q(self, sql: str, args=()) -> list:
        with self.almacen._candado:
            return [dict(r) for r in self.almacen.con.execute(sql, args).fetchall()]

    def listo(self) -> bool:
        if self.embebedor is None:
            return False
        try:
            return bool(self.embebedor.disponible())
        except Exception:
            return False

    def _embeber(self, textos: list, consulta: bool = False) -> list:
        crudos = self.embebedor.embeber([t[:self.max_caracteres] for t in textos], consulta=consulta)
        if len(crudos) != len(textos):
            raise ErrorEmbebedor("el embebedor devolvió una cantidad distinta de vectores")
        return [_normalizado(v) for v in crudos]

    def _guardar(self, filas: list) -> int:
        """filas: (tipo, ref, texto, vector). Idempotente: (tipo, ref, modelo) es único."""
        filas = [f for f in filas if len(f[3])]
        if not filas:
            return 0
        fecha, modelo = ahora(), self.modelo
        with self.almacen._candado:
            antes = self.almacen.con.total_changes
            self.almacen.con.executemany(
                "INSERT OR IGNORE INTO vectores(tipo, ref, texto, vector, modelo, fecha) VALUES (?, ?, ?, ?, ?, ?)",
                [(t, str(r), x, _a_bytes(v), modelo, fecha) for t, r, x, v in filas])
            self.almacen.con.commit()
            return self.almacen.con.total_changes - antes

    def _progreso(self, que: str) -> int:
        return int(self.almacen.meta(f"semantica:{self.modelo}:{que}", "0") or 0)

    def _avanzar(self, que: str, hasta: int) -> None:
        self.almacen._fijar(f"semantica:{self.modelo}:{que}", str(hasta))

    # ---------------------------------------------------------------- indexado
    def indexar_pendientes(self, limite: int = 200) -> dict:
        """Indexa mensajes y recuerdos nuevos (desde la última vez). Incremental e idempotente.
        Si el embebedor falla a mitad, guarda lo hecho y sigue la próxima vez desde ahí."""
        informe = {"mensajes": 0, "recuerdos": 0, "pendientes": 0, "error": ""}
        if not self.listo():
            informe["error"] = getattr(self.embebedor, "motivo", "") or "sin embebedor"
            informe["pendientes"] = self.pendientes()
            return informe
        with self._candado_indexar:
            for que, sql, campo in (
                    ("mensajes", "SELECT id, contenido AS texto FROM mensajes WHERE id > ? ORDER BY id LIMIT ?", "mensaje"),
                    ("recuerdos", "SELECT id, dato AS texto FROM recuerdos WHERE id > ? AND archivado = 0 "
                                  "ORDER BY id LIMIT ?", "recuerdo")):
                restante = limite - informe["mensajes"] - informe["recuerdos"]
                if restante <= 0:
                    break
                filas = self._q(sql, (self._progreso(que), restante))
                lote = getattr(self.embebedor, "lote", 16) or 16
                for i in range(0, len(filas), lote):
                    parte = filas[i:i + lote]
                    utiles = [f for f in parte if len((f["texto"] or "").strip()) >= 4]
                    try:
                        vecs = self._embeber([f["texto"] for f in utiles]) if utiles else []
                    except Exception as e:
                        informe["error"] = str(e)
                        break
                    informe[que] += self._guardar([(campo, f["id"], f["texto"], v) for f, v in zip(utiles, vecs)])
                    self._avanzar(que, parte[-1]["id"])
                if informe["error"]:
                    break
        informe["pendientes"] = self.pendientes()
        return informe

    def pendientes(self) -> int:
        n = self._q("SELECT count(*) AS n FROM mensajes WHERE id > ?", (self._progreso("mensajes"),))[0]["n"]
        n += self._q("SELECT count(*) AS n FROM recuerdos WHERE id > ? AND archivado = 0",
                     (self._progreso("recuerdos"),))[0]["n"]
        return n

    def indexar_documento(self, nombre: str, trozos: list) -> dict:
        """Indexa los trozos de un documento (lista de str o de dicts con 'texto').
        Idempotente: solo calcula vectores de trozos nuevos o cambiados y borra los que sobran."""
        textos = [t.get("texto", "") if isinstance(t, dict) else str(t) for t in trozos]
        prefijo = f"{nombre}#"
        actuales = {f["ref"]: f for f in self._filas_documento(nombre, "id, ref, texto", self.modelo)}
        deseados = {f"{prefijo}{i}": x for i, x in enumerate(textos) if x.strip()}
        cambiados = [r for r, x in deseados.items() if r not in actuales or actuales[r]["texto"] != x]
        sobrantes = [f["id"] for r, f in actuales.items() if r not in deseados or r in cambiados]
        informe = {"nuevos": 0, "sin_cambios": len(deseados) - len(cambiados), "borrados": 0, "error": ""}
        if cambiados and not self.listo():
            informe["error"] = getattr(self.embebedor, "motivo", "") or "sin embebedor"
            return informe
        nuevos = []
        try:
            lote = getattr(self.embebedor, "lote", 16) or 16
            for i in range(0, len(cambiados), lote):
                refs = cambiados[i:i + lote]
                nuevos.extend(zip(refs, self._embeber([deseados[r] for r in refs])))
        except Exception as e:
            informe["error"] = str(e)
            return informe            # no se toca nada: el índice viejo sigue sirviendo
        with self.almacen._candado:
            if sobrantes:
                self.almacen.con.executemany("DELETE FROM vectores WHERE id = ?", [(i,) for i in sobrantes])
                self.almacen.con.commit()
        informe["borrados"] = len([r for r in actuales if r not in deseados])
        informe["nuevos"] = self._guardar([("documento", r, deseados[r], v) for r, v in nuevos])
        return informe

    def _filas_documento(self, nombre: str, campos: str, modelo: str = "") -> list:
        """Trozos guardados de un documento (exactamente ese nombre: 'a' no arrastra a 'a#b.txt')."""
        prefijo = f"{nombre}#"
        sql = (f"SELECT {campos} FROM vectores WHERE tipo = 'documento' AND substr(ref, 1, ?) = ?"
               + (" AND modelo = ?" if modelo else ""))
        filas = self._q(sql, (len(prefijo), prefijo, *((modelo,) if modelo else ())))
        return [f for f in filas if f["ref"].rpartition("#")[0] == nombre]

    def olvidar_documento(self, nombre: str) -> int:
        """Quita del índice los vectores de un documento, de cualquier modelo (p. ej. si se borró el archivo)."""
        ids = [(f["id"],) for f in self._filas_documento(nombre, "id, ref")]
        with self.almacen._candado:
            self.almacen.con.executemany("DELETE FROM vectores WHERE id = ?", ids)
            self.almacen.con.commit()
        return len(ids)

    def documentos_indexados(self) -> list:
        filas = self._q("SELECT DISTINCT ref FROM vectores WHERE tipo = 'documento' AND modelo = ?", (self.modelo,))
        return sorted({f["ref"].rsplit("#", 1)[0] for f in filas})

    def podar_documentos(self, vigentes) -> int:
        """Borra del índice los documentos que ya no están en la carpeta."""
        vigentes = set(vigentes)
        return sum(self.olvidar_documento(n) for n in self.documentos_indexados() if n not in vigentes)

    # ---------------------------------------------------------------- caché en memoria
    def _cargar(self):
        """Vectores del modelo actual en memoria. Se recarga solo lo nuevo (los id solo crecen)."""
        modelo = self.modelo
        firma = self._q("SELECT count(*) AS n, coalesce(max(id), 0) AS m FROM vectores WHERE modelo = ?", (modelo,))[0]
        with self._candado_cache:
            c = self._cache
            if c and c["modelo"] == modelo and (c["n"], c["max"]) == (firma["n"], firma["m"]):
                return c
            agregar = c is not None and c["modelo"] == modelo and firma["m"] >= c["max"]
            filas = self._q("SELECT id, tipo, ref, vector FROM vectores WHERE modelo = ? AND id > ? ORDER BY id",
                            (modelo, c["max"] if agregar else 0))
            if agregar and c["n"] + len(filas) != firma["n"]:
                agregar = False   # hubo borrados: se recarga todo
                filas = self._q("SELECT id, tipo, ref, vector FROM vectores WHERE modelo = ? ORDER BY id", (modelo,))
            if not agregar:
                c = {"modelo": modelo, "n": 0, "max": 0, "dim": 0, "ids": [], "tipos": [], "refs": [],
                     "vecs": [], "matriz": None}
            if filas and not c["dim"]:
                c["dim"] = len(filas[-1]["vector"]) // 4
            dim = c["dim"]
            nuevas = [f for f in filas if len(f["vector"]) == dim * 4]
            c["ids"] += [f["id"] for f in nuevas]
            c["tipos"] += [f["tipo"] for f in nuevas]
            c["refs"] += [f["ref"] for f in nuevas]
            if self.np is not None:
                if nuevas:
                    bloque = self.np.frombuffer(b"".join(f["vector"] for f in nuevas), dtype="<f4").reshape(-1, dim)
                    c["matriz"] = bloque.copy() if c["matriz"] is None else self.np.vstack([c["matriz"], bloque])
            else:
                c["vecs"] += [_de_bytes(f["vector"]) for f in nuevas]
            c["n"], c["max"] = firma["n"], firma["m"]
            self._cache = c
            return c

    # ---------------------------------------------------------------- búsqueda
    def buscar(self, consulta: str, k: int = 6, tipos=None, antes_de_id: int = 0, minimo=None) -> list:
        """Lo más parecido en significado. Si no hay embebedor, cae a la búsqueda por palabras (FTS)."""
        tipos = tuple(tipos or TIPOS)
        if not (consulta or "").strip():
            return []
        if not self.listo():
            return self._buscar_texto(consulta, k, tipos, antes_de_id)
        try:
            q = self._embeber([consulta], consulta=True)[0]
        except Exception:
            return self._buscar_texto(consulta, k, tipos, antes_de_id)
        if not len(q):
            return []
        minimo = self.minimo if minimo is None else minimo
        c = self._cargar()
        if not c["ids"] or len(q) != c["dim"]:
            return self._buscar_texto(consulta, k, tipos, antes_de_id)

        def vale(i: int) -> bool:
            if c["tipos"][i] not in tipos:
                return False
            return not (antes_de_id and c["tipos"][i] == "mensaje" and int(c["refs"][i]) >= antes_de_id)

        # se piden candidatos de más por si algunos ya no existen (recuerdo archivado, etc.)
        cupo = k * 3 + 10
        if self.np is not None:
            puntajes = c["matriz"] @ self.np.asarray(q, dtype="<f4")
            # empates: primero lo más nuevo (igual que heapq.nlargest con (puntaje, i) en puro Python)
            orden = self.np.lexsort((-self.np.arange(len(puntajes)), -puntajes))
            candidatos = []
            for i in orden:
                i = int(i)
                if puntajes[i] < minimo:
                    break
                if vale(i):
                    candidatos.append((float(puntajes[i]), i))
                    if len(candidatos) >= cupo:
                        break
        else:
            ql = q.tolist()  # lista de float: math.sumprod va el doble de rápido que con array
            vecs = c["vecs"]
            candidatos = heapq.nlargest(cupo, ((_producto(ql, vecs[i]), i) for i in range(len(vecs)) if vale(i)))
            candidatos = [(p, i) for p, i in candidatos if p >= minimo]
        return self._completar([(p, c["tipos"][i], c["refs"][i]) for p, i in candidatos], k, "semantica")

    def _completar(self, candidatos: list, k: int, fuente: str) -> list:
        """Convierte (puntaje, tipo, ref) en filas con todos sus datos; descarta lo que ya no existe."""
        ids_m = [int(r) for _, t, r in candidatos if t == "mensaje"]
        ids_r = [int(r) for _, t, r in candidatos if t == "recuerdo"]
        docs = [r for _, t, r in candidatos if t == "documento"]
        mensajes = {f["id"]: f for f in self._en("SELECT * FROM mensajes WHERE id IN ({})", ids_m)}
        recuerdos = {f["id"]: f for f in self._en("SELECT * FROM recuerdos WHERE archivado = 0 AND id IN ({})", ids_r)}
        trozos = {f["ref"]: f for f in self._en(
            f"SELECT ref, texto, fecha FROM vectores WHERE tipo = 'documento' AND modelo = ? AND ref IN ({{}})",
            docs, (self.modelo,))}
        salida = []
        for puntaje, tipo, ref in candidatos:
            if tipo == "mensaje" and int(ref) in mensajes:
                m = mensajes[int(ref)]
                fila = {**m, "texto": m["contenido"]}
            elif tipo == "recuerdo" and int(ref) in recuerdos:
                r = recuerdos[int(ref)]
                fila = {**r, "texto": r["dato"], "privado": 1}
            elif tipo == "documento" and ref in trozos:
                archivo, _, n = ref.rpartition("#")
                fila = {"archivo": archivo, "trozo": int(n), "texto": trozos[ref]["texto"],
                        "fecha": trozos[ref]["fecha"], "privado": 1}
            else:
                continue
            fila.update(tipo=tipo, ref=str(ref), puntaje=round(float(puntaje), 4), fuente=fuente)
            salida.append(fila)
            if len(salida) >= k:
                break
        return salida

    def _en(self, sql: str, valores: list, previos=()) -> list:
        if not valores:
            return []
        return self._q(sql.format(",".join("?" * len(valores))), (*previos, *valores))

    def _buscar_texto(self, consulta: str, k: int, tipos, antes_de_id: int = 0) -> list:
        """Respaldo sin embeddings: FTS5 para mensajes y palabras clave para recuerdos.
        (Los documentos siguen con la búsqueda por palabras de servidor.buscar_documentos.)"""
        candidatos = []
        if "mensaje" in tipos:
            try:
                filas = self.almacen.buscar_mensajes(consulta, limite=k, antes_de_id=antes_de_id)
            except Exception:
                filas = []
            candidatos += [(1.0 / (n + 1), "mensaje", f["id"]) for n, f in enumerate(filas)]
        if "recuerdo" in tipos:
            claves = palabras_clave(consulta)
            puntuados = []
            for r in self.almacen.recuerdos():
                aciertos = sum(1 for w in claves if w in plano(r["dato"]))
                if aciertos:
                    puntuados.append((aciertos / len(claves), "recuerdo", r["id"]))
            candidatos += sorted(puntuados, key=lambda x: -x[0])[:k]
        candidatos.sort(key=lambda x: -x[0])
        return self._completar(candidatos, k, "texto")

    def buscar_hibrido(self, consulta: str, k: int = 6, tipos=None, antes_de_id: int = 0,
                       minimo=None, c: int = RRF_C) -> list:
        """Fusión por rango recíproco (RRF) de la búsqueda semántica y la de palabras.
        puntaje = Σ 1 / (c + posición). Lo que sale en ambas listas sube."""
        tipos = tuple(tipos or TIPOS)
        n = max(k * 3, 10)
        listas = [self._buscar_texto(consulta, n, tipos, antes_de_id)]
        if self.listo():
            semantica = self.buscar(consulta, n, tipos, antes_de_id, minimo)
            listas.insert(0, [f for f in semantica if f["fuente"] == "semantica"])
        fusion = {}
        for lista in listas:
            for pos, fila in enumerate(lista):
                clave = (fila["tipo"], fila["ref"])
                if clave not in fusion:
                    fusion[clave] = {**fila, "puntaje_rrf": 0.0, "fuentes": set()}
                fusion[clave]["puntaje_rrf"] += 1.0 / (c + pos + 1)
                fusion[clave]["fuentes"].add(fila["fuente"])
        salida = sorted(fusion.values(), key=lambda f: -f["puntaje_rrf"])[:k]
        for f in salida:
            fuentes = f.pop("fuentes")
            f["fuente"] = "ambas" if len(fuentes) > 1 else next(iter(fuentes))
            f["puntaje_rrf"] = round(f["puntaje_rrf"], 5)
        return salida

    # ---------------------------------------------------------------- diagnóstico
    def estado(self) -> dict:
        por_tipo = {f["tipo"]: f["n"] for f in self._q(
            "SELECT tipo, count(*) AS n FROM vectores WHERE modelo = ? GROUP BY tipo", (self.modelo,))}
        return {"modelo": self.modelo, "disponible": self.listo(), "vectores": por_tipo,
                "pendientes": self.pendientes(), "numpy": self.np is not None,
                "motivo": getattr(self.embebedor, "motivo", "")}
