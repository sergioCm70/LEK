"""Proveedor local: Ollama."""
import json
import threading
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
                  "keep_alive": "30m",   # que no se descargue de memoria entre preguntas
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

    # ---------------------------------------------------------------- descargas (con aprobación)
    descargas: dict = {}

    def descargar(self, modelo: str) -> None:
        """Descarga un modelo en segundo plano; el progreso queda en self.descargas[modelo]."""
        if self.descargas.get(modelo, {}).get("estado") == "descargando":
            return
        self.descargas[modelo] = {"estado": "descargando", "pct": 0, "detalle": "empezando"}

        def trabajo():
            try:
                with requests.post(f"{self.url}/api/pull", json={"model": modelo, "stream": True},
                                   stream=True, timeout=(10, 600)) as r:
                    for linea in r.iter_lines():
                        if not linea:
                            continue
                        d = json.loads(linea)
                        if d.get("error"):
                            raise RuntimeError(d["error"])
                        if d.get("total"):
                            self.descargas[modelo]["pct"] = round(d.get("completed", 0) / d["total"] * 100)
                        self.descargas[modelo]["detalle"] = d.get("status", "")
                self.descargas[modelo].update(estado="lista", pct=100)
            except Exception as e:
                self.descargas[modelo].update(estado="error", detalle=str(e)[:200])

        threading.Thread(target=trabajo, daemon=True).start()
