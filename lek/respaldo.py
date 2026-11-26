"""Respaldo completo, verificable y restaurable de Luna (LEK 2.0, fase 1).

Cada respaldo es un .zip en datos/respaldos/ con:
- luna.db copiada con la API de respaldo de SQLite (consistente aunque Luna esté funcionando),
- el resto de datos/ (configuración, vocabulario, notas, identidad, certificados, secretos cifrados, ideas…),
- habilidades/ y luna/ (identidad y manual),
- manifiesto.json con el SHA-256 de cada archivo y cuántos mensajes y recuerdos había.

verificar() abre el zip, comprueba cada SHA-256, corre PRAGMA integrity_check sobre la base y compara los conteos.
restaurar() solo funciona con Luna apagada: primero hace un respaldo de seguridad de lo actual y luego reemplaza.

Uso por consola (restaurar.bat):  python -m lek.respaldo listar | verificar <zip> | restaurar <zip>
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import sys
import tempfile
import zipfile

EXCLUIR = {"respaldos", "modelos", "navegador", "sandbox", "respaldo_v0", "__pycache__"}
EXCLUIR_ARCHIVOS = {"luna.db", "luna.db-wal", "luna.db-shm"}


def _sha(ruta: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _conteos(db: pathlib.Path) -> dict:
    con = sqlite3.connect(str(db))
    try:
        salida = {}
        for tabla in ("mensajes", "recuerdos", "pendientes", "proyectos"):
            try:
                salida[tabla] = con.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]
            except sqlite3.Error:
                pass
        salida["integridad"] = con.execute("PRAGMA integrity_check").fetchone()[0]
        return salida
    finally:
        con.close()


def crear(raiz: pathlib.Path, con: sqlite3.Connection | None = None, candado=None, nombre: str = "",
          conservar: int = 14) -> pathlib.Path:
    """Crea el zip. `con` es la conexión abierta de Luna (si está corriendo); si no, se copia el archivo."""
    raiz = pathlib.Path(raiz)
    datos = raiz / "datos"
    carpeta = datos / "respaldos"
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = nombre or f"luna-completo-{datetime.datetime.now():%Y-%m-%d_%H%M%S}"
    destino = carpeta / f"{nombre}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        copia = pathlib.Path(tmp) / "luna.db"
        destino_con = sqlite3.connect(str(copia))
        if con is not None:
            if candado:
                with candado:
                    con.backup(destino_con)
            else:
                con.backup(destino_con)
        elif (datos / "luna.db").exists():
            origen = sqlite3.connect(str(datos / "luna.db"))
            origen.backup(destino_con)
            origen.close()
        destino_con.close()
        archivos = {"datos/luna.db": copia} if copia.exists() and copia.stat().st_size else {}
        for base in (datos, raiz / "habilidades", raiz / "luna"):
            if not base.exists():
                continue
            for p in base.rglob("*"):
                rel = p.relative_to(raiz)
                if not p.is_file() or set(rel.parts) & EXCLUIR or (base == datos and p.name in EXCLUIR_ARCHIVOS):
                    continue
                archivos[rel.as_posix()] = p
        manifiesto = {"creado": datetime.datetime.now().isoformat(timespec="seconds"), "version": 1,
                      "conteos": _conteos(copia) if "datos/luna.db" in archivos else {},
                      "archivos": {k: _sha(v) for k, v in archivos.items()}}
        tmp_zip = destino.with_suffix(".tmp")
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for k, v in archivos.items():
                z.write(v, k)
            z.writestr("manifiesto.json", json.dumps(manifiesto, ensure_ascii=False, indent=1))
        tmp_zip.replace(destino)
    for viejo in sorted(carpeta.glob("luna-completo-*.zip"))[:-conservar]:
        viejo.unlink()
    return destino


def verificar(zip_ruta: pathlib.Path) -> dict:
    zip_ruta = pathlib.Path(zip_ruta)
    problemas = []
    try:
        with zipfile.ZipFile(zip_ruta) as z:
            manifiesto = json.loads(z.read("manifiesto.json"))
            for nombre, sha in manifiesto["archivos"].items():
                try:
                    if hashlib.sha256(z.read(nombre)).hexdigest() != sha:
                        problemas.append(f"{nombre}: el contenido no coincide")
                except KeyError:
                    problemas.append(f"{nombre}: falta en el zip")
            conteos = {}
            if "datos/luna.db" in manifiesto["archivos"]:
                with tempfile.TemporaryDirectory() as tmp:
                    z.extract("datos/luna.db", tmp)
                    conteos = _conteos(pathlib.Path(tmp) / "datos" / "luna.db")
                if conteos.get("integridad") != "ok":
                    problemas.append(f"luna.db: integridad {conteos.get('integridad')}")
                for k, v in manifiesto.get("conteos", {}).items():
                    if k != "integridad" and conteos.get(k) != v:
                        problemas.append(f"luna.db: {k} esperaba {v} y hay {conteos.get(k)}")
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError) as e:
        return {"ok": False, "archivo": zip_ruta.name, "problemas": [f"No se pudo leer: {e}"]}
    return {"ok": not problemas, "archivo": zip_ruta.name, "creado": manifiesto.get("creado"),
            "archivos": len(manifiesto["archivos"]), "conteos": manifiesto.get("conteos", {}),
            "problemas": problemas, "megas": round(zip_ruta.stat().st_size / 1e6, 2)}


def listar(raiz: pathlib.Path) -> list:
    carpeta = pathlib.Path(raiz) / "datos" / "respaldos"
    return sorted(carpeta.glob("luna-completo-*.zip"), reverse=True) if carpeta.exists() else []


def luna_encendida(puerto: int = 8090) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", puerto)) == 0


def restaurar(raiz: pathlib.Path, zip_ruta: pathlib.Path, comprobar_apagada=luna_encendida) -> dict:
    """Restaura un respaldo verificado. Exige Luna apagada y antes guarda lo actual."""
    raiz = pathlib.Path(raiz)
    if comprobar_apagada():
        raise RuntimeError("Luna está encendida: ciérrala antes de restaurar.")
    v = verificar(zip_ruta)
    if not v["ok"]:
        raise RuntimeError("El respaldo no pasó la verificación: " + "; ".join(v["problemas"][:5]))
    seguridad = crear(raiz, nombre=f"luna-completo-antes-de-restaurar-{datetime.datetime.now():%Y%m%d_%H%M%S}",
                      conservar=10_000)
    with zipfile.ZipFile(zip_ruta) as z:
        nombres = [n for n in z.namelist() if n != "manifiesto.json"]
        for n in nombres:
            destino = (raiz / n).resolve()
            if raiz.resolve() not in destino.parents:
                raise RuntimeError(f"Ruta no permitida en el respaldo: {n}")
        for extra in ("luna.db-wal", "luna.db-shm"):
            (raiz / "datos" / extra).unlink(missing_ok=True)
        z.extractall(raiz, members=nombres)
    return {"restaurado": pathlib.Path(zip_ruta).name, "respaldo_previo": seguridad.name,
            "conteos": v["conteos"], "archivos": len(nombres)}


def _main(argv: list) -> int:
    raiz = pathlib.Path(__file__).resolve().parents[1]
    if not argv or argv[0] == "listar":
        for i, z in enumerate(listar(raiz), 1):
            print(f"  {i}. {z.name}  ({z.stat().st_size / 1e6:.1f} MB)")
        return 0
    orden = argv[0]
    elegido = argv[1] if len(argv) > 1 else ""
    if elegido.isdigit():
        lista = listar(raiz)
        elegido = str(lista[int(elegido) - 1]) if 0 < int(elegido) <= len(lista) else ""
    ruta = pathlib.Path(elegido)
    if not ruta.is_absolute():
        ruta = raiz / "datos" / "respaldos" / ruta
    if orden == "verificar":
        print(json.dumps(verificar(ruta), ensure_ascii=False, indent=1))
        return 0
    if orden == "restaurar":
        try:
            r = restaurar(raiz, ruta)
        except RuntimeError as e:
            print("  NO se restauró:", e)
            return 1
        print(f"  Listo: restaurado {r['restaurado']}. Lo que había antes quedó en {r['respaldo_previo']}.")
        return 0
    if orden == "crear":
        print("  Creado:", crear(raiz).name)
        return 0
    print("Uso: python -m lek.respaldo listar | crear | verificar <zip|n> | restaurar <zip|n>")
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
