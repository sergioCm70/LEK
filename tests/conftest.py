"""Pruebas de LUNA. Corren sin internet, sin Ollama y sin Claude: los cerebros son falsos.

En el PC: probar.bat. Aquí: python -m pytest -q
"""
import importlib.util
import shutil
import sys
import types
import pathlib
import uuid

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

try:  # en el PC FastAPI está instalado; en entornos sin él, un sustituto mínimo basta
    import fastapi  # noqa: F401
except ImportError:
    fa = types.ModuleType("fastapi")

    class _App:
        def get(self, *a, **k):
            return lambda f: f
        post = get
        middleware = get

    class _HTTPException(Exception):
        def __init__(self, status_code=500, detail=""):
            super().__init__(detail)
            self.status_code, self.detail = status_code, detail

    fa.FastAPI, fa.Request, fa.HTTPException = _App, object, _HTTPException
    fr = types.ModuleType("fastapi.responses")
    fr.FileResponse = fr.Response = object

    class _JSONResponse:
        def __init__(self, contenido=None, status_code=200, headers=None):
            self.contenido, self.status_code, self.headers, self.cookies = contenido, status_code, dict(headers or {}), {}

        def set_cookie(self, clave, valor, **opciones):
            self.cookies[clave] = (valor, opciones)

    fr.JSONResponse = _JSONResponse

    class _StreamingResponse:
        def __init__(self, contenido, media_type=None, headers=None):
            self.body_iterator, self.media_type, self.headers = contenido, media_type, headers or {}
    fr.StreamingResponse = _StreamingResponse
    sys.modules.update({"fastapi": fa, "fastapi.responses": fr})

from lek.cerebros.base import ErrorProveedor, Proveedor, Respuesta  # noqa: E402


class CerebroFalso(Proveedor):
    """Responde lo que se le programe y guarda todo lo que recibió."""

    def __init__(self, nombre="ollama", ubicacion="local", respuestas=None, configurado=True):
        self.nombre, self.ubicacion = nombre, ubicacion
        self.respuestas = list(respuestas or [])
        self.recibido = []
        self._configurado = configurado

    def configurado(self):
        return self._configurado

    def chat(self, modelo, mensajes, herramientas, clave=""):
        self.recibido.append({"modelo": modelo, "mensajes": mensajes, "herramientas": herramientas})
        r = self.respuestas.pop(0) if self.respuestas else Respuesta(texto=f"respuesta de {modelo}")
        if isinstance(r, Exception):
            raise r
        if callable(r):
            r = r(mensajes)
        if isinstance(r, str):
            r = Respuesta(texto=r)
        r.modelo, r.proveedor = modelo, self.nombre
        return r

    descargas = {}

    def modelos_cargados(self):
        return []

    def modelos_instalados(self):
        return ["qwen3:8b"]


@pytest.fixture
def luna(tmp_path, monkeypatch):
    """Una copia de LUNA en una carpeta temporal, con cerebros falsos."""
    for nombre in ("servidor.py", "programas.json"):
        shutil.copy2(RAIZ / nombre, tmp_path / nombre)
    for carpeta in ("lek", "habilidades", "luna", "static"):
        shutil.copytree(RAIZ / carpeta, tmp_path / carpeta, ignore=shutil.ignore_patterns("__pycache__", "propuestas"))
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    monkeypatch.setenv("ASISTENTE_MODELO", "qwen3:8b")
    monkeypatch.setenv("ASISTENTE_PIN", "")
    monkeypatch.setenv("LUNA_SEGUNDO_PLANO", "no")     # sin hilos de fondo: cada prueba descarta su Luna
    monkeypatch.setenv("ASISTENTE_DESPERTADOR", "no")
    return cargar_luna(tmp_path)


def cargar_luna(carpeta: pathlib.Path):
    nombre = f"luna_{uuid.uuid4().hex[:8]}"
    spec = importlib.util.spec_from_file_location(nombre, carpeta / "servidor.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    local = CerebroFalso("ollama", "local")
    nube = CerebroFalso("claude", "nube", configurado=False)
    modulo.PROVEEDORES.clear()
    modulo.PROVEEDORES.update({"ollama": local, "claude": nube})
    modulo.CEREBRO.esperar = lambda s: None
    modulo.escribir_json(modulo.IDENTIDAD, {"nombre": "Luna", "por_que": "prueba"})
    return modulo


class Peticion:
    def __init__(self, host="127.0.0.1", pin="", sesion="", headers=None, metodo="GET", ruta="/api/ping",
                 esquema="https"):
        self.headers = dict(headers or {})
        if pin:
            self.headers["x-asistente-pin"] = pin
        if sesion:
            self.headers["x-asistente-sesion"] = sesion
        self.headers.setdefault("host", "localhost:8090")
        self.client = types.SimpleNamespace(host=host)
        self.cookies = {}
        self.method = metodo
        self.url = types.SimpleNamespace(path=ruta, scheme=esquema)


def llamada(nombre, argumentos, id_="t1"):
    return Respuesta(texto="", llamadas=[{"id": id_, "function": {"name": nombre, "arguments": argumentos}}])


__all__ = ["CerebroFalso", "ErrorProveedor", "Respuesta", "Peticion", "llamada", "cargar_luna"]
