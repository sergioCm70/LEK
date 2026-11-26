"""Arranque de Luna con Windows (Sergio lo pidió: "que abra apenas prenda mi PC").

Crea o quita un acceso en la carpeta Inicio del usuario: %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup.
No necesita permisos de administrador. Se controla con la opción sistema.iniciar_con_windows.
"""
from __future__ import annotations

import os
import pathlib

ES_WINDOWS = os.name == "nt"


def carpeta_inicio() -> pathlib.Path | None:
    appdata = os.environ.get("APPDATA")
    return pathlib.Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" if appdata else None


def contenido(raiz: pathlib.Path) -> str:
    return ("@echo off\r\nrem Arranca a Luna al prender el PC. Se quita desde Ajustes de Luna o borrando este archivo.\r\n"
            f'start "Luna" /min cmd /c "{pathlib.Path(raiz) / "iniciar.bat"}"\r\n')


def estado(raiz: pathlib.Path) -> dict:
    c = carpeta_inicio()
    if not ES_WINDOWS or c is None:
        return {"disponible": False, "activo": False}
    archivo = c / "Luna.bat"
    return {"disponible": True, "activo": archivo.exists(), "archivo": str(archivo)}


def asegurar(raiz: pathlib.Path, activo: bool) -> str:
    """Deja el acceso como dice la configuración. Devuelve 'creado', 'quitado', 'igual' o 'no disponible'."""
    c = carpeta_inicio()
    if not ES_WINDOWS or c is None or not c.exists():
        return "no disponible"
    archivo = c / "Luna.bat"
    if activo:
        texto = contenido(raiz)
        if archivo.exists() and archivo.read_bytes() == texto.encode("utf-8"):
            return "igual"
        archivo.write_bytes(texto.encode("utf-8"))
        return "creado"
    if archivo.exists():
        archivo.unlink()
        return "quitado"
    return "igual"
