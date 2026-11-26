"""Actividad en vivo (LEK 2.0, fase 2): qué está haciendo Luna, con qué herramienta y con qué modelo.

Cada operación publica un evento de inicio y uno de fin (o error). La interfaz lee /api/actividad para mostrar lo que
pasa en ese momento y lo último que pasó. Se guarda en memoria (últimos 400 eventos): es un tablero, no un registro
permanente. El registro permanente es la tabla `auditoria`.

Privacidad: los eventos nunca llevan el texto de un pedido ni el resultado de una herramienta privada; solo qué se
hizo, cuánto tardó y si salió bien.
"""
from __future__ import annotations

import contextlib
import datetime
import itertools
import threading
import time
from collections import deque


class Actividad:
    def __init__(self, maximo: int = 400):
        self._eventos: deque = deque(maxlen=maximo)
        self._en_curso: dict[int, dict] = {}
        self._contador = itertools.count(1)
        self._candado = threading.Lock()

    def _publicar(self, evento: dict) -> dict:
        with self._candado:
            evento["id"] = next(self._contador)
            evento["fecha"] = datetime.datetime.now().isoformat(timespec="seconds")
            self._eventos.append(evento)
        return evento

    def inicio(self, tipo: str, titulo: str, detalle: str = "") -> int:
        e = self._publicar({"tipo": tipo, "estado": "inicio", "titulo": titulo[:160], "detalle": detalle[:300]})
        with self._candado:
            self._en_curso[e["id"]] = {**e, "t0": time.monotonic()}
        return e["id"]

    def fin(self, id_inicio: int, ok: bool = True, detalle: str = "") -> None:
        with self._candado:
            abierto = self._en_curso.pop(id_inicio, None)
        if not abierto:
            return
        ms = int((time.monotonic() - abierto["t0"]) * 1000)
        self._publicar({"tipo": abierto["tipo"], "estado": "fin" if ok else "error", "titulo": abierto["titulo"],
                        "detalle": detalle[:300], "ms": ms, "de": id_inicio})

    def nota(self, tipo: str, titulo: str, detalle: str = "", estado: str = "info") -> None:
        self._publicar({"tipo": tipo, "estado": estado, "titulo": titulo[:160], "detalle": detalle[:300]})

    @contextlib.contextmanager
    def paso(self, tipo: str, titulo: str, detalle: str = ""):
        i = self.inicio(tipo, titulo, detalle)
        try:
            yield i
        except Exception as e:
            self.fin(i, ok=False, detalle=f"{type(e).__name__}: {e}"[:300])
            raise
        else:
            self.fin(i)

    def desde(self, ultimo_id: int = 0, limite: int = 100) -> dict:
        with self._candado:
            eventos = [dict(e) for e in self._eventos if e["id"] > ultimo_id][-limite:]
            en_curso = [{k: v for k, v in e.items() if k != "t0"} | {"segundos": round(time.monotonic() - e["t0"], 1)}
                        for e in self._en_curso.values()]
        return {"eventos": eventos, "en_curso": en_curso, "ultimo": eventos[-1]["id"] if eventos else ultimo_id}
