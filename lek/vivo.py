"""Turnos en vivo (LEK 2.0, fase 6): el texto llega mientras el cerebro escribe, y se puede interrumpir.

Cada turno transmitido tiene una cola de eventos y una señal de cancelación. El turno se ata al hilo que lo
atiende (threading.local): así el cerebro y el bucle de herramientas saben a quién avisar sin pasar
parámetros por todas partes. Fuera de un turno en vivo, todo funciona igual que antes (sin transmisión).

Eventos: {"t": "texto", "d": fragmento} · {"t": "reinicio"} (se descarta lo escrito: hubo cambio de cerebro o
corrección) · {"t": "paso", "d": "Usando buscar_internet"} · {"t": "fin", ...} · {"t": "error", "d": motivo}.
"""
from __future__ import annotations

import itertools
import queue
import threading


class Cancelado(Exception):
    """El usuario pidió detener el turno."""


class Turno:
    def __init__(self, tid: int):
        self.id = tid
        self.cola: queue.Queue = queue.Queue()
        self.parar = threading.Event()
        self.escrito = ""          # lo transmitido de la ronda actual (por si se interrumpe)

    def emitir(self, tipo: str, dato=None, **extra) -> None:
        evento = {"t": tipo, **extra}
        if dato is not None:
            evento["d"] = dato
        self.cola.put(evento)

    def al_texto(self, fragmento) -> None:
        """Callback para los proveedores. None = reiniciar lo escrito. Lanza Cancelado si hay que parar."""
        if self.parar.is_set():
            raise Cancelado()
        if fragmento is None:
            self.escrito = ""
            self.emitir("reinicio")
        elif fragmento:
            self.escrito += fragmento
            self.emitir("texto", fragmento)


_local = threading.local()
_turnos: dict[int, Turno] = {}
_candado = threading.Lock()
_contador = itertools.count(1)


def nuevo() -> Turno:
    t = Turno(next(_contador))
    with _candado:
        _turnos[t.id] = t
    return t


def atar(turno: Turno | None) -> None:
    _local.turno = turno


def actual() -> Turno | None:
    return getattr(_local, "turno", None)


def terminar(turno: Turno) -> None:
    with _candado:
        _turnos.pop(turno.id, None)
    if actual() is turno:
        atar(None)


def al_texto():
    """Callback de transmisión del turno de este hilo, o None si no hay turno en vivo."""
    t = actual()
    return t.al_texto if t else None


def revisar() -> None:
    """Lanza Cancelado si el turno de este hilo fue detenido (entre rondas y antes de cada herramienta)."""
    t = actual()
    if t and t.parar.is_set():
        raise Cancelado()


def paso(texto: str) -> None:
    t = actual()
    if t:
        t.emitir("paso", texto)


def cancelar(tid: int | None = None) -> int:
    """Detiene un turno (o todos los activos si tid es None). Devuelve cuántos se detuvieron."""
    with _candado:
        objetivos = [t for i, t in _turnos.items() if tid is None or i == tid]
    for t in objetivos:
        t.parar.set()
    return len(objetivos)


def activos() -> list[int]:
    with _candado:
        return list(_turnos)
