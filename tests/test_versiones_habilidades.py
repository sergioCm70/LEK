"""Fase 5: historial de versiones de las habilidades y vuelta atrás."""
import pytest

from conftest import Peticion
from lek.automejora import versiones


def test_listar_y_restaurar(tmp_path):
    hab, ver = tmp_path / "habilidades", tmp_path / "habilidades" / "versiones"
    hab.mkdir()
    (hab / "clima.py").write_text("DESCRIPCION = 'v2'\nx = 2\n", encoding="utf-8")
    ver.mkdir()
    (ver / "clima_20261101_100000.py").write_text("DESCRIPCION = 'v1'\nx = 1\n", encoding="utf-8")
    (ver / "clima_extra_20261101_100000.py").write_text("otra habilidad", encoding="utf-8")   # no es de 'clima'
    lista = versiones.listar(hab, ver, "clima")
    assert [v["archivo"] for v in lista] == ["clima_20261101_100000.py"]
    assert lista[0]["fecha"] == "2026-11-01T10:00" and lista[0]["cambios_vs_actual"] == 4
    r = versiones.restaurar(hab, ver, "clima", "clima_20261101_100000.py")
    assert (hab / "clima.py").read_text(encoding="utf-8") == "DESCRIPCION = 'v1'\nx = 1\n"
    assert (ver / r["copia_de_la_anterior"]).read_text(encoding="utf-8").startswith("DESCRIPCION = 'v2'")
    assert len(versiones.listar(hab, ver, "clima")) == 2                  # se puede deshacer


def test_restaurar_rechaza_rutas_ajenas(tmp_path):
    hab, ver = tmp_path, tmp_path / "versiones"
    ver.mkdir()
    for malo in ("../servidor.py", "otra_20261101_100000.py", "clima.py"):
        with pytest.raises(ValueError):
            versiones.restaurar(hab, ver, "clima", malo)
    with pytest.raises(FileNotFoundError):
        versiones.restaurar(hab, ver, "clima", "clima_20261101_100000.py")


def test_copias_del_mismo_segundo_no_se_pisan(tmp_path):
    actual = tmp_path / "clima.py"
    actual.write_text("a", encoding="utf-8")
    a = versiones.guardar_copia(tmp_path / "v", actual)
    b = versiones.guardar_copia(tmp_path / "v", actual)
    assert a != b and a.exists() and b.exists()


def test_endpoints_en_luna(luna):
    hab = luna.HABILIDADES
    (hab / "saludo.py").write_text("DESCRIPCION = 'Saluda'\ndef ejecutar():\n    return 'hola v2'\n", encoding="utf-8")
    vieja = "DESCRIPCION = 'Saluda'\ndef ejecutar():\n    return 'hola v1'\n"
    luna.VERSIONES.mkdir(parents=True, exist_ok=True)
    (luna.VERSIONES / "saludo_20261120_090000.py").write_text(vieja, encoding="utf-8")
    activas = {a["nombre"]: a for a in luna.ver_habilidades(Peticion())["activas"]}
    assert activas["saludo"]["versiones"] == 1
    v = luna.ver_versiones_habilidad("saludo", Peticion())["versiones"]
    assert v[0]["riesgo"] == "bajo" and v[0]["cambios_vs_actual"] == 2
    r = luna.restaurar_habilidad(luna.Restaurar(nombre="saludo", archivo="saludo_20261120_090000.py"), Peticion())
    assert r["ok"] and (hab / "saludo.py").read_text(encoding="utf-8") == vieja
    with pytest.raises(Exception):
        luna.restaurar_habilidad(luna.Restaurar(nombre="saludo", archivo="../../servidor.py"), Peticion())
