"""Política de riesgo de las habilidades que Luna escribe para sí misma.

Análisis ESTÁTICO con ast: el código nunca se ejecuta aquí. Clasifica en riesgo "bajo" o "alto"
y devuelve motivos concretos (con número de línea) para mostrárselos a Sergio.

Es una lista blanca: solo es de riesgo bajo lo que usa módulos revisados (cálculos, texto, fechas)
y requests GET/HEAD con URL literal hacia HOSTS_PERMITIDOS. Todo lo demás es riesgo alto, lo que
NO significa que sea malo: significa que Sergio debe aprobarlo antes de activarlo.
"""
from __future__ import annotations

import ast
from urllib.parse import urlsplit

HOSTS_PERMITIDOS = {
    "api.open-meteo.com",
    "geocoding-api.open-meteo.com",
    "html.duckduckgo.com",
    "es.wikipedia.org",
}

# Módulos con un motivo concreto. Cualquier módulo fuera de MODULOS_SEGUROS también es riesgo alto.
MODULOS_PELIGROSOS = {
    "os": "importa os (archivos, comandos y variables de entorno)",
    "subprocess": "importa subprocess (ejecuta programas)",
    "shutil": "importa shutil (copia, mueve o borra archivos)",
    "ctypes": "importa ctypes (acceso de bajo nivel al sistema)",
    "socket": "importa socket (red sin control)",
    "winreg": "importa winreg (registro de Windows)",
    "importlib": "importa importlib (carga código de forma dinámica)",
    "sys": "importa sys (acceso al intérprete)",
    "multiprocessing": "importa multiprocessing (lanza procesos)",
    "pickle": "importa pickle (puede ejecutar código al leer datos)",
    "pathlib": "importa pathlib (acceso a archivos del disco)",
    "builtins": "importa builtins (acceso directo a funciones internas)",
    "urllib": "usa urllib para red (solo se permite requests hacia hosts revisados)",
    "http": "importa http (red sin control)",
    "io": "importa io (acceso a archivos)",
    "tempfile": "importa tempfile (crea archivos)",
    "glob": "importa glob (lista archivos del disco)",
    "threading": "importa threading (hilos fuera de control)",
    "webbrowser": "importa webbrowser (abre programas)",
}

MODULOS_SEGUROS = {
    "math", "cmath", "random", "statistics", "decimal", "fractions", "numbers",
    "datetime", "time", "calendar", "zoneinfo",
    "re", "string", "textwrap", "unicodedata", "difflib", "html", "json", "base64", "hashlib",
    "collections", "itertools", "functools", "operator", "bisect", "heapq", "copy", "enum",
    "typing", "uuid", "requests", "urllib.parse", "__future__",
}

FUNCIONES_PELIGROSAS = {
    "eval": "usa eval (ejecuta texto como código)",
    "exec": "usa exec (ejecuta texto como código)",
    "compile": "usa compile (compila código dinámico)",
    "__import__": "usa __import__ (importa módulos de forma oculta)",
    "globals": "usa globals() (toca el estado interno)",
    "vars": "usa vars() (toca el estado interno)",
    "locals": "usa locals() (toca el estado interno)",
    "setattr": "usa setattr (cambia atributos de forma dinámica)",
    "delattr": "usa delattr (borra atributos de forma dinámica)",
    "breakpoint": "usa breakpoint",
    "input": "usa input (se quedaría esperando)",
    "help": "usa help (puede importar cualquier módulo)",
    "get_type_hints": "usa get_type_hints (evalúa texto como código)",
    "ForwardRef": "usa ForwardRef (evalúa texto como código)",
}

# Atributos que, se llamen sobre lo que se llamen, delatan archivos, procesos o red por dentro.
ATRIBUTOS_PROHIBIDOS = {
    "write_text": "escribe archivos", "write_bytes": "escribe archivos", "touch": "crea archivos",
    "mkdir": "crea carpetas", "makedirs": "crea carpetas", "unlink": "borra archivos",
    "rmdir": "borra carpetas", "rmtree": "borra carpetas", "rename": "mueve o renombra archivos",
    "move": "mueve archivos", "chmod": "cambia permisos", "symlink_to": "crea enlaces",
    "read_text": "lee archivos del disco", "read_bytes": "lee archivos del disco",
    "open": "abre archivos o programas", "system": "ejecuta comandos", "popen": "ejecuta comandos",
    "environ": "lee variables de entorno", "getenv": "lee variables de entorno", "modules": "toca módulos cargados",
    "connection": "manipula la conexión de red por dentro", "send": "envía datos por una conexión",
    "mount": "cambia el transporte de red", "request": "manipula peticiones de red por dentro",
    "raw": "lee la conexión de red cruda", "get_type_hints": "evalúa texto como código",
    "ForwardRef": "evalúa texto como código",
    "attrgetter": "lee atributos con nombres calculados", "methodcaller": "llama métodos con nombres calculados",
    "Formatter": "lee atributos con nombres calculados", "get_field": "lee atributos con nombres calculados",
}
# Marcos de ejecución y código compilado: desde ahí se llega a los builtins sin escribir "__".
ATRIBUTOS_PROHIBIDOS.update({a: "accede a marcos de ejecución o código interno" for a in (
    "gi_frame", "gi_code", "cr_frame", "cr_code", "ag_frame", "ag_code", "f_globals", "f_locals",
    "f_builtins", "f_back", "f_code", "tb_frame", "tb_next", "co_code", "co_consts", "gi_yieldfrom")})
ATRIBUTOS_PROHIBIDOS.update({m: f"llega al módulo '{m}' a través de otro" for m in MODULOS_PELIGROSOS})

PALABRAS_SENSIBLES = (".env", "luna.db", "secret", "api_key", "asistente_pin", "password", "contraseña",
                      "token", "identidad.json")
METODOS_REQUESTS_OK = {"get", "head"}
ARGUMENTOS_REQUESTS_OK = {"url", "params", "timeout", "headers", "allow_redirects"}
ATRIBUTOS_REQUESTS_OK = {"exceptions", "RequestException", "Timeout", "ConnectionError", "HTTPError"}


def host_permitido(url: str) -> bool:
    try:
        partes = urlsplit(url)
        return partes.scheme == "https" and (partes.hostname or "") in HOSTS_PERMITIDOS and not partes.username
    except ValueError:
        return False


def _url_literal(nodo) -> str | None:
    """La URL si se sabe sin ejecutar: texto literal, o f-string cuyo inicio literal ya cierra el host."""
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    if isinstance(nodo, ast.JoinedStr) and nodo.values and isinstance(nodo.values[0], ast.Constant):
        inicio = str(nodo.values[0].value)
        if inicio.count("/") >= 3:  # "https://host/..." (no f"https://es.wikipedia.org{resto}")
            return inicio
    return None


def _es_dunder(nombre: str) -> bool:
    return nombre.startswith("__") and nombre.endswith("__") and nombre not in ("__name__", "__doc__", "__init__")


class _Revisor(ast.NodeVisitor):
    def __init__(self):
        self.motivos: list[str] = []
        self.modulos: dict[str, str] = {}           # alias -> módulo ("r" -> "requests")
        self.nombres_requests: dict[str, str] = {}  # from requests import get as g -> {"g": "get"}
        self.llamados: set[int] = set()             # nodos que son la función de una llamada

    def alto(self, nodo, motivo: str) -> None:
        texto = f"línea {getattr(nodo, 'lineno', '?')}: {motivo}"
        if texto not in self.motivos:
            self.motivos.append(texto)

    # ---------------------------------------------------------------- importaciones
    def _modulo(self, nodo, nombre: str) -> None:
        raiz = nombre.split(".")[0]
        if nombre in MODULOS_SEGUROS or (raiz in MODULOS_SEGUROS and raiz != "urllib"):
            return
        self.alto(nodo, MODULOS_PELIGROSOS.get(raiz) or f"importa '{nombre}', un módulo fuera de la lista revisada")

    def registrar_import(self, nodo) -> None:
        if isinstance(nodo, ast.Import):
            for a in nodo.names:
                self._modulo(nodo, a.name)
                self.modulos[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
            return
        modulo = nodo.module or ""
        if nodo.level:
            self.alto(nodo, "importación relativa (toca otros archivos de Luna)")
        for a in nodo.names:
            completo = f"{modulo}.{a.name}"
            self._modulo(nodo, completo if completo in MODULOS_SEGUROS else modulo)
            if a.name == "*":
                self.alto(nodo, f"from {modulo} import * (oculta qué se usa)")
            elif a.name in ATRIBUTOS_PROHIBIDOS or a.name in FUNCIONES_PELIGROSAS or a.name.startswith("_"):
                self.alto(nodo, f"importa '{a.name}' desde {modulo}")
            if modulo == "requests":
                if a.name not in METODOS_REQUESTS_OK | ATRIBUTOS_REQUESTS_OK:
                    self.alto(nodo, f"usa requests.{a.name} (solo se permiten GET y HEAD)")
                self.nombres_requests[a.asname or a.name] = a.name

    # ---------------------------------------------------------------- red
    def _revisar_peticion(self, nodo: ast.Call, metodo: str) -> None:
        if metodo not in METODOS_REQUESTS_OK:
            self.alto(nodo, f"requests.{metodo} (solo se permiten GET y HEAD)")
            return
        url_nodo = nodo.args[0] if nodo.args else next((k.value for k in nodo.keywords if k.arg == "url"), None)
        url = _url_literal(url_nodo) if url_nodo is not None else None
        if url is None:
            self.alto(nodo, "petición web a una dirección que no se puede verificar sin ejecutar")
        elif not host_permitido(url):
            self.alto(nodo, f"petición web a '{urlsplit(url).hostname or url}', fuera de la lista permitida")
        if len(nodo.args) > 1:
            self.alto(nodo, "petición web con argumentos posicionales extra (no se pueden verificar)")
        for k in nodo.keywords:
            if k.arg not in ARGUMENTOS_REQUESTS_OK:
                self.alto(nodo, f"petición web con '{k.arg or '**'}' (solo params, headers, timeout)")

    # ---------------------------------------------------------------- visitas
    def visit_Call(self, nodo):
        f = nodo.func
        self.llamados.add(id(f))
        if isinstance(f, ast.Name):
            if f.id in FUNCIONES_PELIGROSAS:
                self.alto(nodo, FUNCIONES_PELIGROSAS[f.id])
            elif f.id == "open":
                self.alto(nodo, self._motivo_open(nodo))
            elif f.id in ("getattr", "hasattr"):
                self._revisar_getattr(nodo)
            elif f.id in self.nombres_requests:
                self._revisar_peticion(nodo, self.nombres_requests[f.id])
        elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            if self.modulos.get(f.value.id) == "requests" and f.attr not in ATRIBUTOS_REQUESTS_OK:
                self._revisar_peticion(nodo, f.attr)
        self.generic_visit(nodo)

    @staticmethod
    def _motivo_open(nodo: ast.Call) -> str:
        modo = nodo.args[1] if len(nodo.args) > 1 else next((k.value for k in nodo.keywords if k.arg == "mode"), None)
        if modo is None:
            return "open() lee archivos del disco"
        if isinstance(modo, ast.Constant) and isinstance(modo.value, str):
            if set(modo.value) & set("wax+"):
                return f"open() en modo '{modo.value}' (escribe archivos)"
            return "open() lee archivos del disco"
        return "open() con un modo que no se puede verificar (podría escribir)"

    def _revisar_getattr(self, nodo: ast.Call) -> None:
        if len(nodo.args) < 2:
            self.alto(nodo, "getattr sin argumentos verificables")
            return
        objeto, atributo = nodo.args[0], nodo.args[1]
        if isinstance(objeto, ast.Name) and (objeto.id in self.modulos or objeto.id.startswith("__")):
            self.alto(nodo, f"getattr dinámico sobre '{objeto.id}'")
        elif not (isinstance(atributo, ast.Constant) and isinstance(atributo.value, str)):
            self.alto(nodo, "getattr con un nombre calculado (no se puede verificar)")
        elif atributo.value.startswith("_") or atributo.value in ATRIBUTOS_PROHIBIDOS:
            self.alto(nodo, f"getattr sobre '{atributo.value}'")

    def visit_Attribute(self, nodo):
        base = nodo.value.id if isinstance(nodo.value, ast.Name) else None
        if _es_dunder(nodo.attr):
            self.alto(nodo, f"accede a '{nodo.attr}' (vía típica para saltarse las reglas)")
        elif nodo.attr in ATRIBUTOS_PROHIBIDOS:
            self.alto(nodo, f".{nodo.attr}: {ATRIBUTOS_PROHIBIDOS[nodo.attr]}")
        elif base in self.modulos and nodo.attr.startswith("_"):
            self.alto(nodo, f"accede a la parte interna '{base}.{nodo.attr}'")
        elif base and self.modulos.get(base) == "urllib" and nodo.attr != "parse":
            self.alto(nodo, f"usa urllib.{nodo.attr} (solo se permite urllib.parse)")
        elif (base and self.modulos.get(base) == "requests" and id(nodo) not in self.llamados
              and nodo.attr not in ATRIBUTOS_REQUESTS_OK):
            self.alto(nodo, f"usa requests.{nodo.attr} sin llamarlo directamente (no se puede verificar)")
        self.generic_visit(nodo)

    def visit_Name(self, nodo):
        if _es_dunder(nodo.id):
            self.alto(nodo, f"usa '{nodo.id}' (acceso interno de Python)")
        elif (nodo.id in FUNCIONES_PELIGROSAS or nodo.id in ("open", "getattr")) and id(nodo) not in self.llamados:
            self.alto(nodo, f"guarda o pasa '{nodo.id}' como valor (forma de ocultar su uso)")
        elif nodo.id in self.nombres_requests and id(nodo) not in self.llamados:
            self.alto(nodo, f"usa {nodo.id} de requests sin llamarlo directamente")
        self.generic_visit(nodo)

    def visit_Import(self, nodo):  # ya revisados en la primera pasada
        pass

    visit_ImportFrom = visit_Import


def _anotaciones(arbol):
    for n in ast.walk(arbol):
        if isinstance(n, ast.arg) and n.annotation is not None:
            yield n.annotation
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.returns is not None:
            yield n.returns
        elif isinstance(n, ast.AnnAssign):
            yield n.annotation


def analizar(codigo: str) -> dict:
    """{"riesgo": "bajo"|"alto", "motivos": [...], "compila": bool, "error": str|None}. No ejecuta nada."""
    try:
        arbol = ast.parse(codigo or "")
        compile(arbol, "<habilidad>", "exec")  # solo compila para detectar errores; no se ejecuta
    except (SyntaxError, ValueError) as e:
        linea = getattr(e, "lineno", None)
        error = f"no compila{f' (línea {linea})' if linea else ''}: {getattr(e, 'msg', e)}"
        return {"riesgo": "alto", "motivos": [error], "compila": False, "error": error}
    revisor = _Revisor()
    for nodo in ast.walk(arbol):  # primero los imports, para conocer los alias estén donde estén
        if isinstance(nodo, (ast.Import, ast.ImportFrom)):
            revisor.registrar_import(nodo)
    revisor.visit(arbol)
    for anotacion in _anotaciones(arbol):
        if any(isinstance(n, ast.Constant) and isinstance(n.value, str) for n in ast.walk(anotacion)):
            revisor.alto(anotacion, "anotación de tipo en texto (algunas librerías la evalúan como código)")
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
            texto = nodo.value.lower().replace("\\", "/")
            if "__" in texto:
                revisor.alto(nodo, "texto con '__' (podría usarse para llegar a partes internas)")
            if texto.strip("/") == "datos" or "datos/" in texto:
                revisor.alto(nodo, "menciona la carpeta 'datos' de Luna")
        else:
            continue
        for palabra in PALABRAS_SENSIBLES:
            if palabra in texto:
                revisor.alto(nodo, f"menciona '{palabra}' (ajustes privados o datos de Luna)")
    for nodo in ast.walk(arbol):  # nombres de variables o atributos con palabras sensibles
        nombre = nodo.id if isinstance(nodo, ast.Name) else nodo.attr if isinstance(nodo, ast.Attribute) else ""
        for palabra in PALABRAS_SENSIBLES:
            if palabra in nombre.lower():
                revisor.alto(nodo, f"usa el nombre '{nombre}' (parece un secreto)")
    motivos = revisor.motivos
    return {"riesgo": "alto" if motivos else "bajo", "motivos": motivos, "compila": True, "error": None}


def tiene_funcion(codigo: str, nombre: str = "ejecutar") -> bool:
    try:
        return any(isinstance(n, ast.FunctionDef) and n.name == nombre for n in ast.parse(codigo).body)
    except (SyntaxError, ValueError):
        return False


def leer_constante(codigo: str, nombre: str, defecto=None):
    """Lee DESCRIPCION, PARAMETROS o EJEMPLOS sin ejecutar el código (solo literales)."""
    try:
        for n in ast.parse(codigo).body:
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == nombre for t in n.targets):
                return ast.literal_eval(n.value)
    except (SyntaxError, ValueError, TypeError):
        pass
    return defecto
