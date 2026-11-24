"""Organizador autónomo y seguro de archivos sueltos (Descargas y Escritorio).

Sergio autorizó que Luna ordene sola. Por eso las reglas son estrictas y no se pueden relajar desde la
configuración:

- NUNCA borra ni sobrescribe. Si el destino existe, usa "nombre (2).ext", "nombre (3).ext"...
- Solo MUEVE (renombrar dentro del mismo disco, nunca copiar y borrar) archivos SUELTOS que están
  directamente en la raíz de una carpeta permitida. Nunca entra en subcarpetas ni mueve carpetas.
- Raíces permitidas por defecto: Descargas y Escritorio. Documentos solo se ANALIZA salvo que la
  configuración lo permita ("permitir_documentos": true).
- Nunca toca: rutas del sistema (Windows, Program Files, AppData, ProgramData...), ocultos o de sistema,
  accesos directos (.lnk/.url), enlaces, descargas en curso, archivos de bloqueo, archivos modificados o
  creados hace menos de 24 h, ni archivos bloqueados (si no se pueden abrir en exclusivo, se saltan).
- Las carpetas de proyecto (varios .rvt/.rfa/.dwg/.skp/.3dm/.ifc juntos) solo se reportan; jamás se tocan.
- Todo movimiento queda en la tabla `movimientos` y en la auditoría, y se puede deshacer uno por uno
  (deshacer) o por lote (deshacer_lote). Deshacer tampoco sobrescribe: si el origen ya existe, avisa.

analizar() solo lee metadatos con os.scandir (nunca abre contenidos) y tiene tope de archivos y de tiempo.
"""
import json
import os
import pathlib
import re
import stat as _stat
import threading
import time
import uuid

from lek.almacen import ahora

CARPETA_LUNA = "Organizado por Luna"
TOPE_LOTE = 500                 # máximo de archivos por lote (la config solo puede bajarlo)
HORAS_MINIMAS = 24              # la config solo puede subirlo

ESQUEMA = """
CREATE TABLE IF NOT EXISTS movimientos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lote TEXT NOT NULL,
    fecha TEXT NOT NULL,
    origen TEXT NOT NULL,
    destino TEXT NOT NULL,
    deshecho INTEGER NOT NULL DEFAULT 0,
    fecha_deshecho TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS movimientos_lote ON movimientos(lote);
"""

POR_DEFECTO = {
    "raices": ["Descargas", "Escritorio"],    # dónde puede MOVER (alias o rutas absolutas)
    "solo_analizar": ["Documentos"],           # dónde solo mira
    "permitir_documentos": False,              # True = Documentos también se puede ordenar
    "horas_minimas": HORAS_MINIMAS,
    "tope_lote": TOPE_LOTE,
    "limite_archivos": 5000,                   # tope de entradas leídas por análisis
    "limite_segundos": 20.0,                   # tope de tiempo por análisis
}

# ---------------------------------------------------------------- clasificación
CATEGORIAS = {
    "Revit": {".rvt", ".rfa", ".rte", ".rft"},
    "CAD": {".dwg", ".dxf", ".dwt", ".dwf", ".dwfx", ".dgn"},
    "Modelos 3D": {".skp", ".3dm", ".ifc", ".glb", ".gltf", ".obj", ".fbx", ".stl", ".3ds", ".dae", ".blend",
                   ".max", ".c4d", ".ply", ".usdz", ".d5a"},
    "Imágenes y renders": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".hdr",
                           ".exr", ".psd", ".svg", ".avif"},
    "PDF y documentos": {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".ppt", ".pptx", ".odp", ".epub"},
    "Hojas de cálculo": {".xls", ".xlsx", ".xlsm", ".csv", ".ods"},
    "Instaladores": {".exe", ".msi", ".msix", ".msixbundle", ".appx", ".appxbundle", ".iso"},
    "Comprimidos": {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz"},
}
TODAS = list(CATEGORIAS) + ["Respaldos de Revit", "Otros"]
RESPALDO_REVIT = re.compile(r"\.\d{4}\.(rvt|rfa|rte|rft)$", re.IGNORECASE)
MODELOS = {".rvt", ".rfa", ".dwg", ".skp", ".3dm", ".ifc"}
ACCESOS = {".lnk", ".url"}
EN_CURSO = {".crdownload", ".part", ".partial", ".download", ".opdownload", ".tmp", ".!ut", ".aria2"}
BLOQUEOS = {".dwl", ".dwl2", ".lock", ".slf"}  # archivos de bloqueo de AutoCAD/Revit/otros
SISTEMA_NOMBRES = {"desktop.ini", "thumbs.db", "ntuser.dat", "pagefile.sys", "hiberfil.sys", "swapfile.sys"}
PROTEGIDAS = {"windows", "program files", "program files (x86)", "programdata", "appdata", "$recycle.bin",
              "system volume information", "recovery", "$windows.~bt", "$windows.~ws", "boot", "perflogs"}
_OCULTO = getattr(_stat, "FILE_ATTRIBUTE_HIDDEN", 2)
_SISTEMA = getattr(_stat, "FILE_ATTRIBUTE_SYSTEM", 4)

# Carpetas conocidas de Windows (pueden estar redirigidas a OneDrive)
_GUID = {"Descargas": "374DE290-123F-4565-9164-39C4925E467B",
         "Escritorio": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
         "Documentos": "FDD39AD0-238F-46AF-ADB4-6C85480369C7"}
_NOMBRES = {"Descargas": ["Downloads", "Descargas"], "Escritorio": ["Desktop", "Escritorio"],
            "Documentos": ["Documents", "Documentos"]}


def categoria(nombre: str) -> tuple:
    """(categoría, motivo) para un nombre de archivo."""
    if RESPALDO_REVIT.search(nombre):
        return "Respaldos de Revit", "respaldo automático de Revit (" + nombre.rsplit(".", 2)[-2] + ")"
    ext = os.path.splitext(nombre)[1].lower()
    for cat, extensiones in CATEGORIAS.items():
        if ext in extensiones:
            return cat, f"archivo {ext} → {cat}"
    return "Otros", f"tipo {ext or 'sin extensión'} sin categoría"


def _carpeta_conocida_windows(alias: str):
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]
        u = uuid.UUID(_GUID[alias])
        g = GUID(u.fields[0], u.fields[1], u.fields[2])
        for i, b in enumerate(u.bytes[8:]):
            g.Data4[i] = b
        ruta = ctypes.c_wchar_p()
        shell32, ole32 = ctypes.windll.shell32, ctypes.windll.ole32
        shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                                                 ctypes.POINTER(ctypes.c_wchar_p)]
        if shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(ruta)) != 0:
            return None
        valor = ruta.value
        ole32.CoTaskMemFree(ctypes.cast(ruta, ctypes.c_void_p))
        return pathlib.Path(valor) if valor else None
    except Exception:
        return None


def carpeta_de_usuario(alias: str):
    """Ruta real de Descargas/Escritorio/Documentos (respeta la redirección a OneDrive en Windows)."""
    if os.name == "nt":
        ruta = _carpeta_conocida_windows(alias)
        if ruta and ruta.is_dir():
            return ruta
    casa = pathlib.Path.home()
    candidatas = [casa / n for n in _NOMBRES[alias]] + [casa / "OneDrive" / n for n in _NOMBRES[alias]]
    for c in candidatas:
        if c.is_dir():
            return c
    return None


def _clave(ruta) -> str:
    return os.path.normcase(os.path.abspath(str(ruta)))


def es_ruta_protegida(ruta) -> bool:
    """Rutas del sistema, raíces de disco y cualquier componente oculto (empieza con punto)."""
    p = pathlib.Path(os.path.abspath(str(ruta)))
    if p.parent == p:                       # C:\ o /
        return True
    for parte in p.parts[1:]:
        baja = parte.lower()
        if baja in PROTEGIDAS or parte.startswith("."):
            return True
    return False


def bloqueado_por_defecto(ruta: str) -> bool:
    """True si el archivo no se puede abrir en exclusivo (otro programa lo tiene abierto)."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            k32.CreateFileW.restype = wintypes.HANDLE
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            # GENERIC_READ, sin compartir (exclusivo), OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL
            h = k32.CreateFileW(str(ruta), 0x80000000, 0, None, 3, 0x80, None)
            if h is None or h == ctypes.c_void_p(-1).value:
                return True
            k32.CloseHandle(h)
            return False
        except Exception:
            return True                     # ante la duda, no se toca
    try:
        with open(ruta, "rb") as f:
            try:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except ImportError:
                pass
        return False
    except OSError:
        return True


def _mover_sin_sobrescribir(origen: str, destino: str) -> None:
    """Mueve sin copiar y sin pisar nada. Lanza FileExistsError si el destino ya existe."""
    if os.path.lexists(destino):
        raise FileExistsError(destino)
    if os.name == "nt":
        os.rename(origen, destino)          # en Windows rename nunca sobrescribe
        return
    try:
        os.link(origen, destino)            # atómico: falla si el destino existe
    except FileExistsError:
        raise
    except OSError:
        if os.path.lexists(destino):
            raise FileExistsError(destino)
        os.rename(origen, destino)
        return
    os.unlink(origen)                       # quita solo el nombre viejo: el contenido sigue en destino


def _con_sufijo(carpeta: str, nombre: str, reservados: set) -> str:
    base, ext = os.path.splitext(nombre)
    candidato = os.path.join(carpeta, nombre)
    n = 2
    while os.path.lexists(candidato) or _clave(candidato) in reservados:
        candidato = os.path.join(carpeta, f"{base} ({n}){ext}")
        n += 1
        if n > 10000:
            raise RuntimeError("demasiados archivos con el mismo nombre")
    return candidato


def cargar_config(ruta) -> dict:
    """Lee datos/organizador.json si existe; si no, los valores por defecto."""
    datos = dict(POR_DEFECTO)
    try:
        guardado = json.loads(pathlib.Path(ruta).read_text(encoding="utf-8"))
        datos.update({k: v for k, v in guardado.items() if k in POR_DEFECTO})
    except Exception:
        pass
    return datos


class Organizador:
    def __init__(self, almacen, config: dict = None, bloqueado=None, rutas_alias: dict = None):
        """config: ver POR_DEFECTO. bloqueado: función(ruta)->bool (para pruebas).
        rutas_alias: {"Descargas": ruta, ...} para no depender de la carpeta del usuario (pruebas)."""
        self.almacen = almacen
        c = dict(POR_DEFECTO)
        c.update(config or {})
        self.horas = max(HORAS_MINIMAS, float(c["horas_minimas"]))
        self.tope = max(1, min(TOPE_LOTE, int(c["tope_lote"])))
        self.limite_archivos = max(1, int(c["limite_archivos"]))
        self.limite_segundos = max(0.5, float(c["limite_segundos"]))
        self.bloqueado = bloqueado or bloqueado_por_defecto
        self._alias = rutas_alias or {}
        self.avisos = []
        mover = list(c["raices"])
        mirar = list(c["solo_analizar"])
        documentos = self._resolver("Documentos")
        self.raices = []        # donde puede mover
        self.solo_analisis = []  # donde solo mira
        for r in mover:
            ruta = self._resolver(r)
            es_doc = (r == "Documentos") or (ruta and documentos and _clave(ruta) == _clave(documentos))
            if es_doc and not c["permitir_documentos"]:
                mirar.append(r)
                continue
            self._agregar(self.raices, ruta, r)
        if c["permitir_documentos"] and documentos:
            self._agregar(self.raices, documentos, "Documentos")
        for r in mirar:
            ruta = self._resolver(r)
            if ruta and _clave(ruta) not in {_clave(x) for x in self.raices}:
                self._agregar(self.solo_analisis, ruta, r)
        self._candado = threading.Lock()
        self._ultimo = None
        self._estado = "sin analizar"
        with almacen._candado:
            almacen.con.executescript(ESQUEMA)
            almacen.con.commit()

    # ---------------------------------------------------------------- raíces
    def _resolver(self, r):
        if r in self._alias:
            return pathlib.Path(self._alias[r])
        if r in _GUID:
            return carpeta_de_usuario(r)
        return pathlib.Path(os.path.expandvars(os.path.expanduser(str(r))))

    def _agregar(self, lista, ruta, nombre):
        if not ruta:
            self.avisos.append(f"No encontré la carpeta {nombre}")
            return
        ruta = pathlib.Path(os.path.abspath(str(ruta)))
        if es_ruta_protegida(ruta):
            self.avisos.append(f"{ruta} es una ruta protegida: no la toco")
            return
        if os.path.islink(ruta) or not ruta.is_dir():
            self.avisos.append(f"{ruta} no es una carpeta válida")
            return
        if _clave(ruta) not in {_clave(x) for x in lista}:
            lista.append(ruta)

    def _raiz_movible(self, ruta: str):
        """La raíz permitida de la que el archivo es hijo DIRECTO, o None."""
        padre = _clave(os.path.dirname(os.path.abspath(ruta)))
        for r in self.raices:
            if _clave(r) == padre:
                return r
        return None

    # ---------------------------------------------------------------- reglas
    def _por_que_no(self, nombre: str, st) -> str:
        """Motivo para NO tocar un archivo suelto ('' si se puede mover). Solo usa metadatos (lstat)."""
        ext = os.path.splitext(nombre)[1].lower()
        if _stat.S_ISLNK(st.st_mode):
            return "es un enlace"
        if not _stat.S_ISREG(st.st_mode):
            return "no es un archivo normal"
        if nombre.startswith(".") or nombre.startswith("~$"):
            return "archivo oculto o temporal"
        atributos = getattr(st, "st_file_attributes", 0)
        if atributos & (_OCULTO | _SISTEMA):
            return "archivo oculto o de sistema"
        if nombre.lower() in SISTEMA_NOMBRES:
            return "archivo de sistema"
        if ext in ACCESOS:
            return "acceso directo"
        if ext in EN_CURSO:
            return "descarga en curso o temporal"
        if ext in BLOQUEOS:
            return "archivo de bloqueo de un programa abierto"
        reciente = st.st_mtime
        if os.name == "nt":
            reciente = max(reciente, getattr(st, "st_birthtime", st.st_ctime))
        if time.time() - reciente < self.horas * 3600:
            return f"modificado hace menos de {int(self.horas)} h"
        return ""

    # ---------------------------------------------------------------- análisis (solo lectura)
    def analizar(self) -> dict:
        """Recorre SOLO el primer nivel de cada raíz con os.scandir. No abre ni cambia nada."""
        inicio = time.monotonic()
        leidas = 0
        truncado = False
        por_tipo = {}
        total = 0
        plan, saltados, proyectos, solo_mirar = [], [], [], 0
        reservados = set()
        raices = [(r, True) for r in self.raices] + [(r, False) for r in self.solo_analisis]
        for raiz, movible in raices:
            if truncado:
                break
            destino_base = os.path.join(str(raiz), CARPETA_LUNA)
            base_ok = not os.path.lexists(destino_base) or (os.path.isdir(destino_base)
                                                             and not os.path.islink(destino_base))
            try:
                entradas = os.scandir(raiz)
            except OSError as e:
                self.avisos.append(f"No pude leer {raiz}: {e}")
                continue
            with entradas:
                for e in entradas:
                    leidas += 1
                    if leidas > self.limite_archivos or time.monotonic() - inicio > self.limite_segundos:
                        truncado = True
                        break
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.name != CARPETA_LUNA and not e.name.startswith("."):
                                n = self._modelos_en(e.path)
                                if n >= 2:
                                    proyectos.append({"ruta": e.path, "modelos": n})
                            continue
                        if not (e.is_file(follow_symlinks=False) or e.is_symlink()):
                            continue
                        st = e.stat(follow_symlinks=False)
                    except OSError as err:
                        saltados.append({"ruta": e.path, "motivo": f"no se pudo leer: {err.strerror}"})
                        continue
                    cat, motivo = categoria(e.name)
                    total += 1
                    por_tipo[cat] = por_tipo.get(cat, 0) + 1
                    if not movible:
                        solo_mirar += 1
                        continue
                    razon = self._por_que_no(e.name, st)
                    if not razon and not base_ok:
                        razon = f"'{CARPETA_LUNA}' existe pero no es una carpeta normal"
                    if razon:
                        saltados.append({"ruta": e.path, "motivo": razon})
                        continue
                    destino = _con_sufijo(os.path.join(destino_base, cat), e.name, reservados)
                    reservados.add(_clave(destino))
                    plan.append({"origen": e.path, "destino": destino, "motivo": motivo})
        analisis = {
            "resumen": {"total": total, "por_tipo": dict(sorted(por_tipo.items(), key=lambda x: -x[1]))},
            "plan": plan,
            "saltados": saltados,
            "carpetas_proyecto": proyectos,
            "solo_analisis": solo_mirar,
            "truncado": truncado,
            "segundos": round(time.monotonic() - inicio, 2),
            "raices": [str(r) for r in self.raices],
            "raices_solo_analisis": [str(r) for r in self.solo_analisis],
            "avisos": list(self.avisos),
        }
        self._ultimo = analisis
        self._estado = "analizado" + (" (parcial: se alcanzó el límite)" if truncado else "")
        return analisis

    def _modelos_en(self, carpeta: str, limite: int = 300) -> int:
        n = 0
        try:
            with os.scandir(carpeta) as it:
                for i, e in enumerate(it):
                    if i >= limite:
                        break
                    if os.path.splitext(e.name)[1].lower() in MODELOS:
                        n += 1
        except OSError:
            pass
        return n

    # ---------------------------------------------------------------- organizar
    def organizar(self, plan: list = None) -> dict:
        """Mueve según el plan (o el del último análisis). Revalida TODO en el momento de mover;
        el 'destino' del plan se ignora y se recalcula. Máximo `tope_lote` archivos por lote."""
        with self._candado:
            if plan is None:
                plan = (self._ultimo or self.analizar())["plan"]
            lote = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
            movidos, saltados, pendientes = 0, [], 0
            vistos = set()
            for item in plan:
                origen = str(item.get("origen", "") if isinstance(item, dict) else item)
                if not origen or _clave(origen) in vistos:
                    continue
                vistos.add(_clave(origen))
                if movidos >= self.tope:
                    pendientes += 1
                    continue
                razon, destino = self._validar(origen)
                if razon:
                    saltados.append({"ruta": origen, "motivo": razon})
                    continue
                cur = self.almacen._x("INSERT INTO movimientos(lote, fecha, origen, destino) VALUES (?, ?, ?, ?)",
                                      (lote, ahora(), origen, destino))
                try:
                    os.makedirs(os.path.dirname(destino), exist_ok=True)
                    _mover_sin_sobrescribir(origen, destino)
                    movidos += 1
                except Exception as e:
                    self.almacen._x("DELETE FROM movimientos WHERE id = ?", (cur.lastrowid,))
                    motivo = "ya existe un archivo con ese nombre" if isinstance(e, FileExistsError) \
                        else f"no se pudo mover ({getattr(e, 'strerror', '') or e})"
                    saltados.append({"ruta": origen, "motivo": motivo})
            informe = {"movidos": movidos, "saltados": saltados, "lote": lote, "pendientes": pendientes}
            informe["mensaje"] = texto_informe(informe)
            self.almacen.auditar("archivos_organizar", {"lote": lote, "movidos": movidos,
                                                        "saltados": len(saltados), "pendientes": pendientes})
            self._estado = informe["mensaje"]
            self._ultimo = None
            return informe

    def _validar(self, origen: str) -> tuple:
        """(motivo para no mover, destino). Repite todas las reglas sobre el estado actual del disco."""
        origen = os.path.abspath(origen)
        raiz = self._raiz_movible(origen)
        if raiz is None:
            return "no está suelto en una carpeta permitida", ""
        if es_ruta_protegida(origen):
            return "ruta protegida", ""
        nombre = os.path.basename(origen)
        try:
            st = os.lstat(origen)
        except FileNotFoundError:
            return "ya no existe", ""
        except OSError as e:
            return f"no se pudo leer ({e.strerror})", ""
        razon = self._por_que_no(nombre, st)
        if razon:
            return razon, ""
        base = os.path.join(str(raiz), CARPETA_LUNA)
        for carpeta in (base, os.path.join(base, categoria(nombre)[0])):
            if os.path.lexists(carpeta) and (os.path.islink(carpeta) or not os.path.isdir(carpeta)
                                             or getattr(os.path, "isjunction", lambda _: False)(carpeta)):
                return f"'{carpeta}' no es una carpeta normal", ""
        if self.bloqueado(origen):
            return "está abierto o bloqueado por otro programa", ""
        return "", _con_sufijo(os.path.join(base, categoria(nombre)[0]), nombre, set())

    # ---------------------------------------------------------------- deshacer
    def deshacer(self, id_movimiento: int) -> dict:
        with self._candado:
            filas = self.almacen._q("SELECT * FROM movimientos WHERE id = ?", (int(id_movimiento),))
            if not filas:
                return {"ok": False, "id": id_movimiento, "mensaje": "No existe ese movimiento."}
            m = filas[0]
            if m["deshecho"]:
                return {"ok": False, "id": m["id"], "mensaje": "Ese movimiento ya se había deshecho."}
            if not os.path.lexists(m["destino"]):
                return {"ok": False, "id": m["id"],
                        "mensaje": f"El archivo ya no está en {m['destino']}; no puedo devolverlo."}
            if os.path.lexists(m["origen"]):
                return {"ok": False, "id": m["id"],
                        "mensaje": f"Ya hay otro archivo en {m['origen']}; no lo sobrescribo. "
                                   "Muévelo o renómbralo y vuelve a intentar."}
            if not os.path.isdir(os.path.dirname(m["origen"])):
                return {"ok": False, "id": m["id"],
                        "mensaje": f"La carpeta original {os.path.dirname(m['origen'])} ya no existe."}
            try:
                _mover_sin_sobrescribir(m["destino"], m["origen"])
            except FileExistsError:
                return {"ok": False, "id": m["id"], "mensaje": f"Ya hay otro archivo en {m['origen']}; no lo sobrescribo."}
            except OSError as e:
                return {"ok": False, "id": m["id"], "mensaje": f"No se pudo devolver: {e.strerror or e}"}
            self.almacen._x("UPDATE movimientos SET deshecho = 1, fecha_deshecho = ? WHERE id = ?", (ahora(), m["id"]))
            self.almacen.auditar("archivos_deshacer", {"id": m["id"], "origen": m["origen"]})
            self._estado = f"Deshecho: {os.path.basename(m['origen'])} volvió a {os.path.dirname(m['origen'])}"
            return {"ok": True, "id": m["id"], "mensaje": self._estado}

    def deshacer_lote(self, lote: str) -> dict:
        filas = self.almacen._q("SELECT id FROM movimientos WHERE lote = ? AND deshecho = 0 ORDER BY id DESC",
                                (str(lote),))
        deshechos, fallidos = 0, []
        for f in filas:
            r = self.deshacer(f["id"])
            if r["ok"]:
                deshechos += 1
            else:
                fallidos.append({"id": f["id"], "motivo": r["mensaje"]})
        self.almacen.auditar("archivos_deshacer_lote", {"lote": lote, "deshechos": deshechos, "fallidos": len(fallidos)})
        msg = f"Lote {lote}: {deshechos} archivos devueltos a su lugar" + (
            f", {len(fallidos)} no se pudieron devolver" if fallidos else "") + "."
        self._estado = msg
        return {"lote": lote, "deshechos": deshechos, "fallidos": fallidos, "mensaje": msg}

    # ---------------------------------------------------------------- consultas
    def movimientos(self, n: int = 50) -> list:
        filas = self.almacen._q("SELECT * FROM movimientos ORDER BY id DESC LIMIT ?", (int(n),))
        return [{"id": f["id"], "fecha": f["fecha"], "origen": f["origen"], "destino": f["destino"],
                 "deshecho": bool(f["deshecho"])} for f in filas]

    def ultimo_lote(self) -> str:
        filas = self.almacen._q("SELECT lote FROM movimientos ORDER BY id DESC LIMIT 1")
        return filas[0]["lote"] if filas else ""

    # ---------------------------------------------------------------- forma exacta para la API
    def _respuesta(self) -> dict:
        u = self._ultimo or {"resumen": {"total": 0, "por_tipo": {}}, "plan": []}
        return {"estado": self._estado,
                "resumen": {"total": u["resumen"]["total"], "por_tipo": dict(u["resumen"]["por_tipo"])},
                "plan": [{"origen": p["origen"], "destino": p["destino"], "motivo": p["motivo"]} for p in u["plan"]],
                "movimientos": self.movimientos()}

    def api_estado(self) -> dict:                      # GET /api/archivos/estado (no recorre el disco)
        return self._respuesta()

    def api_analizar(self) -> dict:                    # POST /api/archivos/analizar
        self.analizar()
        return self._respuesta()

    def api_organizar(self, plan: list = None) -> dict:  # POST /api/archivos/organizar {plan?}
        self.organizar(plan)
        return self._respuesta()

    def api_deshacer(self, id_movimiento: int) -> dict:  # POST /api/archivos/deshacer {id}
        self.deshacer(id_movimiento)
        return self._respuesta()

    # ---------------------------------------------------------------- herramientas para Luna
    def ejecutar(self, nombre: str, argumentos: dict = None) -> str:
        a = argumentos or {}
        if nombre == "analizar_archivos":
            return texto_analisis(self.analizar())
        if nombre == "organizar_archivos":
            return self.organizar()["mensaje"]
        if nombre == "deshacer_organizacion":
            if a.get("id"):
                return self.deshacer(int(a["id"]))["mensaje"]
            lote = a.get("lote") or self.ultimo_lote()
            return self.deshacer_lote(lote)["mensaje"] if lote else "No hay movimientos para deshacer."
        return f"Herramienta desconocida: {nombre}"


def _f(nombre, descripcion, props=None):
    return {"type": "function", "function": {"name": nombre, "description": descripcion,
                                             "parameters": {"type": "object", "properties": props or {},
                                                            "required": []}}}


HERRAMIENTAS = [
    _f("analizar_archivos", "Revisa (sin cambiar nada) los archivos sueltos de Descargas y Escritorio y dice "
                            "cuántos hay de cada tipo y qué se ordenaría."),
    _f("organizar_archivos", "Ordena los archivos sueltos de Descargas y Escritorio en 'Organizado por Luna' "
                             "(nunca borra ni sobrescribe; se puede deshacer)."),
    _f("deshacer_organizacion", "Devuelve archivos a su lugar: un movimiento con 'id' o un lote con 'lote' "
                                "(sin nada, el último lote).",
       {"id": {"type": "integer"}, "lote": {"type": "string"}}),
]


def texto_analisis(a: dict) -> str:
    r = a["resumen"]
    tipos = ", ".join(f"{n} {c}" for c, n in r["por_tipo"].items()) or "ninguno"
    t = f"Encontré {r['total']} archivos sueltos ({tipos}). Puedo ordenar {len(a['plan'])}"
    t += f"; dejo quietos {len(a['saltados'])}" if a["saltados"] else ""
    t += f"; {a['solo_analisis']} están en carpetas que solo reviso" if a["solo_analisis"] else ""
    t += "."
    if a["carpetas_proyecto"]:
        t += f" Hay {len(a['carpetas_proyecto'])} carpetas de proyecto que no toco."
    if a["truncado"]:
        t += " (Análisis parcial: alcancé el límite de archivos o de tiempo.)"
    return t


def texto_informe(i: dict) -> str:
    t = f"Organicé {i['movidos']} archivos (lote {i['lote']})."
    if i["saltados"]:
        t += f" Salté {len(i['saltados'])}."
    if i.get("pendientes"):
        t += f" Quedan {i['pendientes']} para el próximo lote."
    return t
