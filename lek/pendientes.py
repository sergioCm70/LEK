"""Pendientes (memoria de trabajo): lo que Sergio y Luna dejaron por hacer.

Sobreviven a reinicios (están en luna.db). Nunca se borran: se cierran con un estado y una fecha.
Existe porque el 24/11 Luna dijo "dejé guardados los pendientes" sin tener dónde guardarlos.
"""
from __future__ import annotations

import datetime

ESQUEMA = """CREATE TABLE IF NOT EXISTS pendientes(
    id INTEGER PRIMARY KEY AUTOINCREMENT, creado TEXT, texto TEXT, fecha_limite TEXT,
    proyecto TEXT, estado TEXT DEFAULT 'abierto', cerrado TEXT, nota TEXT, origen TEXT)"""


class Pendientes:
    def __init__(self, almacen):
        self.almacen = almacen
        with almacen._candado:
            almacen.con.execute(ESQUEMA)
            almacen.con.commit()

    def anotar(self, texto: str, fecha_limite: str = "", proyecto: str = "", origen: str = "conversacion") -> dict:
        texto = " ".join(str(texto or "").split())[:500]
        if not texto:
            raise ValueError("El pendiente está vacío")
        if fecha_limite:
            datetime.date.fromisoformat(str(fecha_limite)[:10])
        cur = self.almacen._x("INSERT INTO pendientes(creado, texto, fecha_limite, proyecto, origen) VALUES (?,?,?,?,?)",
                              (datetime.datetime.now().isoformat(timespec="seconds"), texto,
                               str(fecha_limite or "")[:10], str(proyecto or "")[:80], origen))
        return {"id": cur.lastrowid, "texto": texto}

    def abiertos(self, proyecto: str = "") -> list:
        if proyecto:
            return self.almacen._q("SELECT * FROM pendientes WHERE estado = 'abierto' AND proyecto = ? "
                                   "ORDER BY COALESCE(NULLIF(fecha_limite, ''), '9999'), id", (proyecto,))
        return self.almacen._q("SELECT * FROM pendientes WHERE estado = 'abierto' "
                               "ORDER BY COALESCE(NULLIF(fecha_limite, ''), '9999'), id")

    def cerrar(self, pid: int, estado: str = "hecho", nota: str = "") -> dict:
        if estado not in ("hecho", "descartado"):
            raise ValueError("El estado debe ser 'hecho' o 'descartado'")
        filas = self.almacen._q("SELECT * FROM pendientes WHERE id = ?", (int(pid),))
        if not filas:
            raise KeyError(pid)
        self.almacen._x("UPDATE pendientes SET estado = ?, cerrado = ?, nota = ? WHERE id = ?",
                        (estado, datetime.datetime.now().isoformat(timespec="seconds"), str(nota)[:300], int(pid)))
        return {**filas[0], "estado": estado}

    def texto(self) -> str:
        filas = self.abiertos()
        if not filas:
            return "No hay pendientes abiertos."
        return "\n".join(f"#{f['id']} {f['texto']}" + (f" (para el {f['fecha_limite']})" if f["fecha_limite"] else "")
                         + (f" [{f['proyecto']}]" if f["proyecto"] else "") for f in filas[:30])


def herramientas(p: Pendientes):
    def _f(nombre, descripcion, propiedades, requeridos):
        return {"type": "function", "function": {"name": nombre, "description": descripcion, "parameters": {
            "type": "object", "properties": propiedades, "required": requeridos}}}

    def anotar(texto="", fecha_limite="", proyecto="", **_):
        try:
            r = p.anotar(texto, fecha_limite, proyecto)
        except ValueError as e:
            return f"No lo anoté: {e}"
        return f"Pendiente #{r['id']} anotado: {r['texto']}"

    def cerrar(id=0, estado="hecho", nota="", **_):
        try:
            r = p.cerrar(int(id), estado, nota)
        except (KeyError, ValueError) as e:
            return f"No pude cerrarlo: {e}"
        return f"Pendiente #{r['id']} marcado como {estado}."

    definiciones = [
        _f("anotar_pendiente", "Anota algo que queda por hacer (para Sergio o para ti). Úsala SIEMPRE que digas "
           "que dejas algo pendiente o guardado para después.",
           {"texto": {"type": "string", "description": "qué hay que hacer"},
            "fecha_limite": {"type": "string", "description": "AAAA-MM-DD si tiene fecha"},
            "proyecto": {"type": "string", "description": "proyecto relacionado, si hay"}}, ["texto"]),
        _f("ver_pendientes", "Lista los pendientes abiertos (sobreviven a reinicios).", {}, []),
        _f("cerrar_pendiente", "Marca un pendiente como hecho o descartado (no se borra).",
           {"id": {"type": "string", "description": "número del pendiente"},
            "estado": {"type": "string", "description": "'hecho' o 'descartado'"},
            "nota": {"type": "string", "description": "detalle opcional"}}, ["id"]),
    ]
    return definiciones, {"anotar_pendiente": anotar, "ver_pendientes": lambda **_: p.texto(),
                          "cerrar_pendiente": cerrar}
