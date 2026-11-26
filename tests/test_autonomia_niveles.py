"""Niveles de autonomía y permisos por herramienta (LEK 2.0, fase 4)."""
import datetime

import pytest

from conftest import Peticion, llamada
from lek.almacen import Almacen
from lek.autonomia.permisos import Permisos


@pytest.fixture
def per(tmp_path):
    avisos = []
    p = Permisos(tmp_path, Almacen(tmp_path), avisar=lambda t, d: avisos.append(t))
    p.avisos = avisos
    return p


def test_matriz_de_decisiones(per):
    assert per.nivel() == 2
    assert per.decidir("buscar_internet", 0, "autonomo")[0] == "ejecutar"         # consulta: siempre
    assert per.decidir("organizar_archivos", 2, "conversacion")[0] == "ejecutar"   # Sergio lo pidió
    assert per.decidir("organizar_archivos", 2, "autonomo")[0] == "aprobar"        # por su cuenta: pregunta
    assert per.decidir("recordar", 1, "autonomo")[0] == "ejecutar"
    per.guardar(nivel=1)
    assert per.decidir("organizar_archivos", 2, "conversacion")[0] == "aprobar"
    assert per.decidir("recordar", 1, "conversacion")[0] == "ejecutar"
    per.guardar(nivel=0)
    assert per.decidir("recordar", 1, "conversacion")[0] == "bloquear"
    assert per.decidir("estado_pc", 0, "conversacion")[0] == "ejecutar"
    per.guardar(nivel=3, herramientas={"organizar_archivos": "permitir"})
    assert per.decidir("organizar_archivos", 2, "autonomo")[0] == "ejecutar"
    assert per.decidir("abrir_programa", 2, "autonomo")[0] == "aprobar"


def test_bloquear_y_preguntar_ganan(per):
    per.guardar(nivel=4, herramientas={"abrir_programa": "bloquear", "abrir_web": "preguntar"})
    assert per.decidir("abrir_programa", 2, "conversacion")[0] == "bloquear"
    assert per.decidir("abrir_web", 2, "conversacion")[0] == "aprobar"
    per.guardar(herramientas={"abrir_programa": "normal"})               # revocar la regla
    assert "abrir_programa" not in per.leer()["herramientas"]
    with pytest.raises(ValueError):
        per.guardar(nivel=7)


def test_aprobacion_se_usa_una_vez_y_caduca(per):
    aid = per.pedir("abrir_programa", {"nombre": "Revit"}, "por su cuenta", "autonomo")
    assert per.avisos == ["Luna pide permiso para abrir_programa"]
    hechos = []
    r = per.responder(aid, True, ejecutar=lambda n, a, c: hechos.append((n, a, c)) or "Abriendo Revit.")
    assert r["estado"] == "ejecutada" and hechos == [("abrir_programa", {"nombre": "Revit"}, "autonomo")]
    with pytest.raises(ValueError):
        per.responder(aid, True, ejecutar=lambda *a: "otra vez")              # nunca se reutiliza
    viejo = per.pedir("abrir_web", {}, "x", "autonomo")
    hace_dos_dias = (datetime.datetime.now() - datetime.timedelta(days=2)).isoformat(timespec="seconds")
    per.almacen._x("UPDATE aprobaciones_herramienta SET fecha = ? WHERE id = ?", (hace_dos_dias, viejo))
    assert per.pendientes() == []


def test_luna_en_nivel_1_no_abre_programas_sin_permiso(luna):
    luna.PERMISOS.guardar(nivel=1)
    abiertos = []
    luna.FUNCIONES["abrir_programa"] = lambda nombre="", **_: abiertos.append(nombre) or f"Abriendo {nombre}."
    local = luna.PROVEEDORES["ollama"]
    local.respuestas = [llamada("abrir_programa", {"nombre": "Revit"}), "Te pedí permiso."]
    luna.responder("abre Revit")
    assert abiertos == []
    tool = [m for m in local.recibido[-1]["mensajes"] if m["role"] == "tool"][0]["content"]
    assert tool.startswith("PENDIENTE DE APROBACIÓN #1")
    r = luna.responder_aprobacion_herramienta(1, "aprobar", Peticion())
    assert r["estado"] == "ejecutada" and abiertos == ["Revit"]
    assert any(n["titulo"] == "Hecho (aprobación #1)" for n in luna.NOTIF.listar())


def test_revision_diaria_no_actua_sola_sobre_el_pc(luna):
    assert luna.ejecutar_herramienta("organizar_archivos", {}, contexto="autonomo").startswith("PENDIENTE DE APROBACIÓN")
    assert luna.ver_aprobaciones_herramientas(Peticion())["pendientes"][0]["herramienta"] == "organizar_archivos"


def test_cambiar_autonomia_exige_pc_o_pin(luna):
    with pytest.raises(Exception):
        luna.cambiar_autonomia(luna.AjusteAutonomia(nivel=4), Peticion(host="192.168.1.20"))
    r = luna.cambiar_autonomia(luna.AjusteAutonomia(nivel=0), Peticion())
    assert r["nivel"] == 0 and r["nombre_nivel"] == "Consulta"
    assert luna.ejecutar_herramienta("recordar", {"dato": "algo"}).startswith("BLOQUEADO por los permisos")
