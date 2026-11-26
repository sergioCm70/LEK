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


def leer_flujo(lineas, al_texto) -> tuple[str, list, dict]:
    """Lee el flujo SSE de Claude. Llama al_texto(fragmento) con cada pedazo de texto.
    Devuelve (texto, llamadas, uso). Si al_texto lanza (p. ej. el usuario detuvo el turno), se propaga."""
    texto, bloques, uso = "", {}, {}
    for linea in lineas:
        if isinstance(linea, bytes):
            linea = linea.decode("utf-8", "replace")
        if not linea.startswith("data:"):
            continue
        try:
            ev = json.loads(linea[5:].strip())
        except json.JSONDecodeError:
            continue
        tipo = ev.get("type")
        if tipo == "message_start":
            uso.update(ev.get("message", {}).get("usage", {}))
        elif tipo == "content_block_start":
            b = ev.get("content_block", {})
            bloques[ev.get("index", 0)] = {"tipo": b.get("type"), "id": b.get("id"), "nombre": b.get("name"), "json": ""}
        elif tipo == "content_block_delta":
            d = ev.get("delta", {})
            if d.get("type") == "text_delta":
                texto += d.get("text", "")
                al_texto(d.get("text", ""))
            elif d.get("type") == "input_json_delta":
                bloques.setdefault(ev.get("index", 0), {"tipo": "tool_use", "json": ""})["json"] += d.get("partial_json", "")
        elif tipo == "message_delta":
            uso.update(ev.get("usage", {}))
        elif tipo == "error":
            err = ev.get("error", {})
            raise ErrorProveedor("servidor", f"Claude cortó la respuesta: {err.get('message', '')[:160]}",
                                 reintentable=err.get("type") in ("overloaded_error", "api_error"))
    llamadas = []
    for i in sorted(bloques):
        b = bloques[i]
        if b.get("tipo") == "tool_use":
            try:
                argumentos = json.loads(b["json"]) if b["json"].strip() else {}
            except json.JSONDecodeError:
                argumentos = {}
            llamadas.append({"id": b.get("id") or f"t{i}", "function": {"name": b.get("nombre") or "", "arguments": argumentos}})
    return texto, llamadas, uso


class Claude(Proveedor):
    nombre = "claude"
    ubicacion = "nube"
    transmite = True

    def __init__(self, obtener_clave, precios: dict):
        self.obtener_clave = obtener_clave   # función: la clave puede cambiar desde la interfaz
        self.precios = precios

    def configurado(self) -> bool:
        return bool(self.obtener_clave())

    def chat(self, modelo, mensajes, herramientas, clave: str = "", al_texto=None):
        clave = clave or self.obtener_clave()
        if not clave:
            raise ErrorProveedor("auth", "no hay clave de Claude")
        sistema, msgs = a_formato_claude(mensajes)
        cuerpo = {"model": modelo, "max_tokens": 1024, "system": sistema, "messages": msgs}
        if herramientas:
            cuerpo["tools"] = [{"name": t["function"]["name"], "description": t["function"]["description"],
                                "input_schema": t["function"]["parameters"]} for t in herramientas]
        if al_texto:
            cuerpo["stream"] = True
        inicio = time.monotonic()
        try:
            r = requests.post("https://api.anthropic.com/v1/messages", json=cuerpo, timeout=(10, 90),
                              stream=bool(al_texto), headers={
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
        if al_texto:
            try:
                texto, llamadas, uso = leer_flujo(r.iter_lines(), al_texto)
            except requests.RequestException as e:
                raise ErrorProveedor("red", f"se cortó la conexión con Claude ({e.__class__.__name__})", reintentable=True)
            finally:
                r.close()
        else:
            datos = r.json()
            uso = datos.get("usage", {})
            texto = "".join(b.get("text", "") for b in datos.get("content", []) if b.get("type") == "text")
            llamadas = [{"id": b["id"], "function": {"name": b["name"], "arguments": b.get("input", {})}}
                        for b in datos.get("content", []) if b.get("type") == "tool_use"]
        entrada = (uso.get("input_tokens", 0) + uso.get("cache_read_input_tokens", 0)
                   + uso.get("cache_creation_input_tokens", 0))
        salida_t = uso.get("output_tokens", 0)
        pe, ps = self.precios.get(modelo, (0, 0))
        return Respuesta(texto=texto, llamadas=llamadas, modelo=modelo, proveedor=self.nombre,
                         tokens_entrada=entrada, tokens_salida=salida_t, latencia=time.monotonic() - inicio,
                         usd=entrada / 1e6 * pe + salida_t / 1e6 * ps)
