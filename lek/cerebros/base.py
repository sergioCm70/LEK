"""Interfaz común de todos los cerebros. Nada fuera de lek/cerebros sabe qué proveedor responde.

Formato de mensajes (el mismo para todos): {"role": "system"|"user"|"assistant"|"tool", "content": str,
"tool_calls": [{"id", "function": {"name", "arguments": dict}}], "tool_call_id": str}.
"""
from dataclasses import dataclass, field


@dataclass
class Respuesta:
    texto: str = ""
    llamadas: list = field(default_factory=list)   # [{"id", "function": {"name", "arguments"}}]
    modelo: str = ""
    proveedor: str = ""
    tokens_entrada: int = 0
    tokens_salida: int = 0
    latencia: float = 0.0
    usd: float = 0.0

    def como_mensaje(self) -> dict:
        return {"role": "assistant", "content": self.texto, "tool_calls": self.llamadas}


class ErrorProveedor(Exception):
    """tipo: auth | saldo | limite | red | servidor | tiempo | otro. reintentable: vale la pena repetir ya."""

    def __init__(self, tipo: str, detalle: str, reintentable: bool = False):
        super().__init__(f"{tipo}: {detalle}")
        self.tipo, self.detalle, self.reintentable = tipo, detalle, reintentable


class Proveedor:
    nombre = "base"
    ubicacion = "local"      # "local" o "nube"

    def configurado(self) -> bool:
        return True

    def chat(self, modelo: str, mensajes: list, herramientas: list | None) -> Respuesta:
        raise NotImplementedError
