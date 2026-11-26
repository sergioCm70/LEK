"""Respaldo completo verificable, restauración segura e inicio con Windows."""
import json
import os
import pathlib
import zipfile

import pytest

from lek import inicio_windows, respaldo
from lek.almacen import Almacen


def proyecto(tmp_path):
    raiz = tmp_path / "luna_raiz"
    (raiz / "datos").mkdir(parents=True)
    (raiz / "habilidades").mkdir()
    (raiz / "luna").mkdir()
    (raiz / "luna" / "MANUAL_LUNA.md").write_text("manual", encoding="utf-8")
    (raiz / "habilidades" / "clima.py").write_text("def ejecutar(): return 1", encoding="utf-8")
    (raiz / "datos" / "vocabulario.json").write_text('{"palabras": ["Revit"]}', encoding="utf-8")
    (raiz / "datos" / "navegador").mkdir()
    (raiz / "datos" / "navegador" / "perfil.bin").write_bytes(b"x" * 100)
    alm = Almacen(raiz / "datos")
    for i in range(5):
        alm.guardar_mensaje("usuario", f"mensaje {i}", "web")
    alm.recordar("prefiere escala 1:50")
    return raiz, alm


def test_crear_y_verificar(tmp_path):
    raiz, alm = proyecto(tmp_path)
    z = respaldo.crear(raiz, alm.con, alm._candado)
    v = respaldo.verificar(z)
    assert v["ok"], v["problemas"]
    assert v["conteos"]["mensajes"] == 5 and v["conteos"]["recuerdos"] == 1
    nombres = zipfile.ZipFile(z).namelist()
    assert "luna/MANUAL_LUNA.md" in nombres and "habilidades/clima.py" in nombres
    assert not any("navegador" in n for n in nombres)            # el perfil del navegador no se respalda


def test_verificar_detecta_corrupcion(tmp_path):
    raiz, alm = proyecto(tmp_path)
    z = respaldo.crear(raiz, alm.con, alm._candado)
    with zipfile.ZipFile(z) as viejo:
        contenido = {n: viejo.read(n) for n in viejo.namelist()}
    contenido["datos/vocabulario.json"] = b'{"palabras": ["alterado"]}'
    with zipfile.ZipFile(z, "w") as nuevo:
        for n, b in contenido.items():
            nuevo.writestr(n, b)
    v = respaldo.verificar(z)
    assert not v["ok"] and any("vocabulario" in p for p in v["problemas"])


def test_restaurar_exige_luna_apagada_y_guarda_lo_actual(tmp_path):
    raiz, alm = proyecto(tmp_path)
    z = respaldo.crear(raiz, alm.con, alm._candado, nombre="luna-completo-2026-11-01_000000")
    alm.guardar_mensaje("usuario", "mensaje nuevo después del respaldo", "web")
    (raiz / "datos" / "vocabulario.json").write_text('{"palabras": ["cambiado"]}', encoding="utf-8")
    with pytest.raises(RuntimeError):
        respaldo.restaurar(raiz, z, comprobar_apagada=lambda: True)
    alm.con.close()
    r = respaldo.restaurar(raiz, z, comprobar_apagada=lambda: False)
    assert r["conteos"]["mensajes"] == 5
    assert "Revit" in (raiz / "datos" / "vocabulario.json").read_text(encoding="utf-8")
    previo = raiz / "datos" / "respaldos" / (r["respaldo_previo"])
    assert respaldo.verificar(previo)["conteos"]["mensajes"] == 6     # lo que había antes no se perdió
    assert Almacen(raiz / "datos").total_mensajes() == 5


def test_conserva_solo_los_ultimos(tmp_path):
    raiz, alm = proyecto(tmp_path)
    for i in range(4):
        respaldo.crear(raiz, alm.con, alm._candado, nombre=f"luna-completo-2026-11-0{i + 1}_000000", conservar=2)
    assert len(respaldo.listar(raiz)) == 2


def test_inicio_con_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(inicio_windows, "ES_WINDOWS", True)
    inicio = tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    inicio.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    raiz = pathlib.Path("C:/Users/sergi/Downloads/LEK")
    assert inicio_windows.asegurar(raiz, True) == "creado"
    assert "iniciar.bat" in (inicio / "Luna.bat").read_text(encoding="utf-8")
    assert inicio_windows.asegurar(raiz, True) == "igual"
    assert inicio_windows.asegurar(raiz, False) == "quitado" and not (inicio / "Luna.bat").exists()


def test_respaldo_diario_de_luna(luna):
    v = luna.respaldo_diario()
    assert v["ok"] and luna.respaldo_diario()["estado"] == "ya hecho"
