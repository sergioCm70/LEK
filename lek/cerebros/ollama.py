"""Proveedor local: Ollama."""
import time

import requests

from .base import ErrorProveedor, Proveedor, Respuesta


class Ollama(Proveedor):
    nombre = "ollama"
    ubicacion = "local"

    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def chat(self, modelo, mensajes, herramientas):
        cuerpo = {"model": modelo, "messages": mensajes, "stream": False, "think": False,
                  "options": {"temperature": 0.6, "num_ctx": 8192}}
        if herramientas:
            cuerpo["tools"] = herramientas
        inicio = time.monotonic()
        try:
            r = requests.post(f"{self.url}/api/chat", json=cuerpo, timeout=300)
            if r.status_code == 400 and "think" in r.text:  # Ollama viejo o modelo sin esa opción
                cuerpo.pop("think")
                r = requests.post(f"{self.url}/api/chat", json=cuerpo, timeout=300)
        except requests.Timeout:
            raise ErrorProveedor("tiempo", "Ollama no respondió en 5 minutos", reintentable=False)
        except requests.RequestException as e:
            raise ErrorProveedor("red", f"no encuentro Ollama ({e.__class__.__name__})", reintentable=True)
        if r.status_code != 200:
            raise ErrorProveedor("servidor", f"Ollama respondió {r.status_code}: {r.text[:200]}",
                                 reintentable=r.status_code >= 500)
        datos = r.json()
        msg = datos.get("message", {})
        llamadas = []
        for i, ll in enumerate(msg.get("tool_calls") or []):
            f = ll.get("function", {})
            llamadas.append({"id": ll.get("id") or f"local_{i}", "function": {"name": f.get("name", ""),
                                                                               "arguments": f.get("arguments", {})}})
        return Respuesta(texto=msg.get("content", ""), llamadas=llamadas, modelo=modelo, proveedor=self.nombre,
                         tokens_entrada=datos.get("prompt_eval_count", 0) or 0,
                         tokens_salida=datos.get("eval_count", 0) or 0,
                         latencia=time.monotonic() - inicio)

    def modelos_instalados(self) -> list:
        try:
            return [m.get("name", "") for m in requests.get(f"{self.url}/api/tags", timeout=5).json().get("models", [])]
        except Exception:
            return []

    def modelos_cargados(self) -> list:
        """Lo que Ollama tiene en memoria ahora: tamaño total y cuánto está en la GPU."""
        try:
            return requests.get(f"{self.url}/api/ps", timeout=5).json().get("models", [])
        except Exception:
            return []
