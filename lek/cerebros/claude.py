"""Proveedor en la nube: Claude (API de Anthropic)."""
import json
import time

import requests

from .base import ErrorProveedor, Proveedor, Respuesta


def a_formato_claude(mensajes: list) -> tuple[str, list]:
    """Convierte el formato común al formato de mensajes de Claude."""
    sistema, salida = "", []
    for m in mensajes:
        rol = m.get("role")
        if rol == "system":
            sistema += m.get("content", "")
            continue
        if rol == "tool":
            bloque = {"type": "tool_result", "tool_use_id": m.get("tool_call_id") or "sin_id",
                      "content": str(m.get("content", "")) or "(vacío)"}
            if salida and salida[-1]["role"] == "user" and isinstance(salida[-1]["content"], list):
                salida[-1]["content"].append(bloque)
            else:
                salida.append({"role": "user", "content": [bloque]})
            continue
        if rol == "assistant" and m.get("tool_calls"):
            bloques = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            for ll in m["tool_calls"]:
                f = ll.get("function", {})
                args = f.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args or "{}")
                    except Exception:
                        args = {}
                bloques.append({"type": "tool_use", "id": ll.get("id") or "sin_id", "name": f.get("name", ""),
                                "input": args or {}})
            salida.append({"role": "assistant", "content": bloques})
            continue
        texto = str(m.get("content", "")).strip() or "…"
        if salida and salida[-1]["role"] == rol and isinstance(salida[-1]["content"], str):
            salida[-1]["content"] += "\n" + texto  # Claude pide turnos alternados
        else:
            salida.append({"role": rol, "content": texto})
    while salida and salida[0]["role"] != "user":
        salida.pop(0)
    return sistema, salida


class Claude(Proveedor):
    nombre = "claude"
    ubicacion = "nube"

    def __init__(self, obtener_clave, precios: dict):
        self.obtener_clave = obtener_clave   # función: la clave puede cambiar desde la interfaz
        self.precios = precios

    def configurado(self) -> bool:
        return bool(self.obtener_clave())

    def chat(self, modelo, mensajes, herramientas, clave: str = ""):
        clave = clave or self.obtener_clave()
        if not clave:
            raise ErrorProveedor("auth", "no hay clave de Claude")
        sistema, msgs = a_formato_claude(mensajes)
        cuerpo = {"model": modelo, "max_tokens": 1024, "system": sistema, "messages": msgs}
        if herramientas:
            cuerpo["tools"] = [{"name": t["function"]["name"], "description": t["function"]["description"],
                                "input_schema": t["function"]["parameters"]} for t in herramientas]
        inicio = time.monotonic()
        try:
            r = requests.post("https://api.anthropic.com/v1/messages", json=cuerpo, timeout=(10, 90), headers={
                "x-api-key": clave, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        except requests.Timeout:
            raise ErrorProveedor("tiempo", "Claude no respondió en 2 minutos", reintentable=True)
        except requests.RequestException as e:
            raise ErrorProveedor("red", f"sin conexión con Claude ({e.__class__.__name__})", reintentable=True)
        if r.status_code != 200:
            try:
                detalle = r.json().get("error", {}).get("message", r.text[:200])
            except Exception:
                detalle = r.text[:200]
            if r.status_code in (401, 403):
                raise ErrorProveedor("auth", detalle)
            if r.status_code == 429:
                raise ErrorProveedor("limite", detalle, reintentable=True)
            if r.status_code == 400 and "credit" in detalle.lower():
                raise ErrorProveedor("saldo", detalle)
            raise ErrorProveedor("servidor" if r.status_code >= 500 else "otro", f"{r.status_code}: {detalle}",
                                 reintentable=r.status_code >= 500)
        datos = r.json()
        uso = datos.get("usage", {})
        entrada = (uso.get("input_tokens", 0) + uso.get("cache_read_input_tokens", 0)
                   + uso.get("cache_creation_input_tokens", 0))
        salida_t = uso.get("output_tokens", 0)
        pe, ps = self.precios.get(modelo, (0, 0))
        texto = "".join(b.get("text", "") for b in datos.get("content", []) if b.get("type") == "text")
        llamadas = [{"id": b["id"], "function": {"name": b["name"], "arguments": b.get("input", {})}}
                    for b in datos.get("content", []) if b.get("type") == "tool_use"]
        return Respuesta(texto=texto, llamadas=llamadas, modelo=modelo, proveedor=self.nombre,
                         tokens_entrada=entrada, tokens_salida=salida_t, latencia=time.monotonic() - inicio,
                         usd=entrada / 1e6 * pe + salida_t / 1e6 * ps)
