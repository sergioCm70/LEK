"""Niveles de autonomía y permisos por herramienta (LEK 2.0, fase 4).

Niveles (configurables, por defecto 2):
  0 Consulta            solo responde y analiza: ninguna herramienta que cambie algo.
  1 Preparación         investiga, planifica, anota (memoria, notas, pendientes, proyectos); lo que actúa sobre el PC
                        (mover archivos, abrir programas, crear habilidades) pide aprobación.
  2 Ejecución aprobada  lo que Sergio pide en la conversación se hace; lo que Luna haría POR SU CUENTA y actúa sobre
                        el PC pide aprobación.
  3 Autonomía limitada  además, por su cuenta puede usar las herramientas que Sergio marcó como "permitir".
  4 Autonomía supervisada  igual que 3 y, por su cuenta, puede anotar y preparar sin preguntar; todo queda en Actividad,
                        en la auditoría y se puede revocar.

Por herramienta: "permitir", "preguntar" o "bloquear" (bloquear gana siempre; preguntar exige aprobación incluso en la
conversación). Las herramientas de solo consulta (nivel 0) nunca piden permiso.
Las aprobaciones pendientes caducan a las 24 h, se usan una sola vez y quedan auditadas.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import threading

NOMBRES_NIVEL = {0: "Consulta", 1: "Preparación", 2: "Ejecución aprobada", 3: "Autonomía limitada",
                 4: "Autonomía supervisada"}
DESCRIPCION_NIVEL = {
    0: "Solo responde y analiza. No cambia nada.",
    1: "Investiga, planifica y anota. Mover archivos, abrir programas o crear habilidades pide tu aprobación.",
    2: "Hace lo que le pides en la conversación. Lo que haría por su cuenta sobre el PC pide tu aprobación.",
    3: "Además, por su cuenta usa las herramientas que marques como 'permitir'.",
    4: "Por su cuenta anota, prepara y usa lo permitido sin preguntar. Todo queda registrado y se puede revocar.",
}
OPCIONES = ("permitir", "preguntar", "bloquear")
HORAS_CADUCIDAD = 24

ESQUEMA = """CREATE TABLE IF NOT EXISTS aprobaciones_herramienta(
    id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, herramienta TEXT, argumentos TEXT, motivo TEXT,
    contexto TEXT, estado TEXT DEFAULT 'pendiente', respondida TEXT, resultado TEXT)"""


class Permisos:
    def __init__(self, carpeta: pathlib.Path, almacen, avisar=None):
        self.ruta = pathlib.Path(carpeta) / "permisos.json"
        self.almacen = almacen
        self.avisar = avisar or (lambda titulo, detalle: None)
        self._candado = threading.Lock()
        with almacen._candado:
            almacen.con.execute(ESQUEMA)
            almacen.con.commit()

    # ---------------------------------------------------------------- configuración
    def leer(self) -> dict:
        try:
            d = json.loads(self.ruta.read_text(encoding="utf-8"))
        except Exception:
            d = {}
        nivel = d.get("nivel", 2)
        return {"nivel": nivel if nivel in NOMBRES_NIVEL else 2,
                "herramientas": {k: v for k, v in (d.get("herramientas") or {}).items() if v in OPCIONES}}

    def guardar(self, nivel=None, herramientas: dict | None = None) -> dict:
        with self._candado:
            d = self.leer()
            if nivel is not None:
                nivel = int(nivel)
                if nivel not in NOMBRES_NIVEL:
                    raise ValueError("El nivel va de 0 a 4")
                d["nivel"] = nivel
            for nombre, valor in (herramientas or {}).items():
                if valor in (None, "", "normal"):
                    d["herramientas"].pop(nombre, None)
                elif valor in OPCIONES:
                    d["herramientas"][nombre] = valor
                else:
                    raise ValueError(f"{nombre}: usa permitir, preguntar o bloquear")
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self.ruta.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        self.almacen.auditar("permisos", d)
        return d

    def nivel(self) -> int:
        return self.leer()["nivel"]

    # ---------------------------------------------------------------- decisión
    def decidir(self, nombre: str, nivel_herramienta: int, contexto: str = "conversacion") -> tuple:
        """("ejecutar" | "aprobar" | "bloquear", motivo)."""
        cfg = self.leer()
        especial = cfg["herramientas"].get(nombre)
        n = cfg["nivel"]
        if especial == "bloquear":
            return "bloquear", f"Sergio bloqueó {nombre}."
        if nivel_herramienta <= 0:
            return "ejecutar", "solo consulta"
        if especial == "preguntar":
            return "aprobar", f"Sergio pidió que {nombre} siempre le pregunte."
        if n == 0:
            return "bloquear", "Luna está en modo Consulta (nivel 0): no cambia nada."
        if contexto == "conversacion":
            if n == 1 and nivel_herramienta >= 2:
                return "aprobar", "En nivel Preparación, las acciones sobre el PC piden aprobación."
            return "ejecutar", "pedido en la conversación"
        # por iniciativa propia (revisión diaria, tareas de fondo)
        if nivel_herramienta == 1:
            return ("ejecutar", "preparación por iniciativa propia") if n >= 1 else ("bloquear", "nivel 0")
        if n >= 3 and especial == "permitir":
            return "ejecutar", f"permitida por Sergio para el nivel {n}"
        return "aprobar", "Luna quiere hacerlo por su cuenta y actúa sobre el PC."

    # ---------------------------------------------------------------- aprobaciones
    def pedir(self, nombre: str, argumentos: dict, motivo: str, contexto: str) -> int:
        cur = self.almacen._x("INSERT INTO aprobaciones_herramienta(fecha, herramienta, argumentos, motivo, contexto) "
                              "VALUES (?,?,?,?,?)", (datetime.datetime.now().isoformat(timespec="seconds"), nombre,
                                                     json.dumps(argumentos or {}, ensure_ascii=False)[:4000],
                                                     motivo[:300], contexto))
        aid = cur.lastrowid
        self.almacen.auditar("aprobacion_pedida", {"id": aid, "herramienta": nombre})
        resumen = ", ".join(f"{k}={str(v)[:60]}" for k, v in (argumentos or {}).items())
        self.avisar(f"Luna pide permiso para {nombre}", f"#{aid}: {resumen or 'sin argumentos'}. Motivo: {motivo}")
        return aid

    def _caducar(self) -> None:
        limite = (datetime.datetime.now() - datetime.timedelta(hours=HORAS_CADUCIDAD)).isoformat(timespec="seconds")
        self.almacen._x("UPDATE aprobaciones_herramienta SET estado = 'caducada' WHERE estado = 'pendiente' "
                        "AND fecha < ?", (limite,))

    def pendientes(self) -> list:
        self._caducar()
        filas = self.almacen._q("SELECT * FROM aprobaciones_herramienta WHERE estado = 'pendiente' ORDER BY id")
        for f in filas:
            f["argumentos"] = json.loads(f["argumentos"] or "{}")
        return filas

    def responder(self, aid: int, aprobar: bool, ejecutar=None) -> dict:
        """Aprobar ejecuta UNA vez la acción guardada (con `ejecutar(nombre, argumentos, contexto)`)."""
        self._caducar()
        with self._candado:
            filas = self.almacen._q("SELECT * FROM aprobaciones_herramienta WHERE id = ?", (int(aid),))
            if not filas:
                raise KeyError(aid)
            a = filas[0]
            if a["estado"] != "pendiente":
                raise ValueError(f"Esa aprobación ya está {a['estado']}")
            ahora = datetime.datetime.now().isoformat(timespec="seconds")
            self.almacen._x("UPDATE aprobaciones_herramienta SET estado = ?, respondida = ? WHERE id = ?",
                            ("aprobada" if aprobar else "rechazada", ahora, int(aid)))
        self.almacen.auditar("aprobacion_respondida", {"id": aid, "aprobada": aprobar})
        if not aprobar:
            return {"id": aid, "estado": "rechazada"}
        resultado = ejecutar(a["herramienta"], json.loads(a["argumentos"] or "{}"), a["contexto"]) if ejecutar else ""
        self.almacen._x("UPDATE aprobaciones_herramienta SET estado = 'ejecutada', resultado = ? WHERE id = ?",
                        (str(resultado)[:2000], int(aid)))
        return {"id": aid, "estado": "ejecutada", "resultado": str(resultado)[:2000]}

    def estado(self) -> dict:
        cfg = self.leer()
        return {**cfg, "nombre_nivel": NOMBRES_NIVEL[cfg["nivel"]], "niveles": [
            {"nivel": k, "nombre": v, "descripcion": DESCRIPCION_NIVEL[k]} for k, v in NOMBRES_NIVEL.items()],
            "pendientes": len(self.pendientes())}
