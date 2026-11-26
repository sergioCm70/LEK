"""Historial de versiones de cada habilidad y vuelta atrás (LEK 2.0, fase 5).

Antes de reemplazar una habilidad activa se guarda una copia en habilidades/versiones/<nombre>_AAAAMMDD_HHMMSS.py.
Aquí se listan esas copias y se restaura una: la versión actual también se guarda antes, así que volver atrás
siempre se puede deshacer. Nunca se borra una versión.
"""
from __future__ import annotations

import datetime
import difflib
import re
import shutil
from pathlib import Path

_FECHA = re.compile(r"_(\d{8}_\d{6})(?:_\d+)?\.py$")


def _patron(nombre: str) -> re.Pattern:
    return re.compile(rf"^{re.escape(nombre)}_\d{{8}}_\d{{6}}(?:_\d+)?\.py$")


def guardar_copia(versiones: Path, actual: Path) -> Path:
    """Copia la versión actual al historial con la fecha de ahora (sin pisar otra copia del mismo segundo)."""
    versiones.mkdir(parents=True, exist_ok=True)
    base = f"{actual.stem}_{datetime.datetime.now():%Y%m%d_%H%M%S}"
    destino, n = versiones / f"{base}.py", 1
    while destino.exists():
        destino, n = versiones / f"{base}_{n}.py", n + 1
    shutil.copy2(actual, destino)
    return destino


def _cambios(a: str, b: str) -> int:
    return sum(1 for l in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0)
               if l[:1] in "+-" and not l.startswith(("+++", "---")))


def listar(habilidades: Path, versiones: Path, nombre: str) -> list[dict]:
    """Versiones anteriores, de la más nueva a la más vieja, con cuántas líneas cambian frente a la actual."""
    if not versiones.exists():
        return []
    actual_p = habilidades / f"{nombre}.py"
    actual = actual_p.read_text(encoding="utf-8") if actual_p.exists() else ""
    patron, salida = _patron(nombre), []
    for p in versiones.glob(f"{nombre}_*.py"):
        if not patron.match(p.name):
            continue
        codigo = p.read_text(encoding="utf-8")
        m = _FECHA.search(p.name)
        fecha = datetime.datetime.strptime(m.group(1), "%Y%m%d_%H%M%S").isoformat(timespec="minutes") if m else ""
        salida.append({"archivo": p.name, "fecha": fecha, "lineas": len(codigo.splitlines()),
                       "cambios_vs_actual": _cambios(actual, codigo), "igual_a_la_actual": codigo == actual,
                       "codigo": codigo})
    return sorted(salida, key=lambda v: v["archivo"], reverse=True)


def restaurar(habilidades: Path, versiones: Path, nombre: str, archivo: str) -> dict:
    """Pone la versión elegida como activa. La actual (si hay) queda en el historial antes."""
    archivo = Path(archivo).name
    if not _patron(nombre).match(archivo):
        raise ValueError("Esa versión no es de esta habilidad.")
    origen = versiones / archivo
    if not origen.exists():
        raise FileNotFoundError("No encuentro esa versión.")
    destino = habilidades / f"{nombre}.py"
    copia = guardar_copia(versiones, destino).name if destino.exists() else None
    shutil.copy2(origen, destino)
    return {"restaurada": archivo, "copia_de_la_anterior": copia}
