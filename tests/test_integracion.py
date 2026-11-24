"""Pruebas de que los módulos de la fase 2 quedaron conectados a Luna (servidor.py)."""
import asyncio
import json

import pytest

from conftest import Peticion, llamada


class PeticionJSON(Peticion):
    def __init__(self, cuerpo=None, **kw):
        super().__init__(**kw)
        self._cuerpo = json.dumps(cuerpo or {}).encode()

    async def body(self):
        return self._cuerpo

    async def json(self):
        return json.loads(self._cuerpo)


def correr(c):
    return asyncio.run(c)


def test_herramientas_nuevas_estan_disponibles(luna):
    nombres = {h["function"]["name"] for h in luna.herramientas_actuales()}
    for n in ("estado_pc", "analizar_archivos", "organizar_archivos", "deshacer_organizacion", "mi_pulso",
              "crear_objetivo", "ver_proyectos", "analizar_archivo", "calcular_tabla", "comparar_archivos"):
        assert n in nombres, n
    assert len(nombres) == len(luna.herramientas_actuales())        # sin nombres repetidos


def test_pulso_nunca_sale_del_pc(luna):
    correr(luna.salud_pulso(PeticionJSON({"bpm": 72})))
    nube, local = luna.PROVEEDORES["claude"], luna.PROVEEDORES["ollama"]
    nube._configurado = True
    nube.respuestas = [llamada("mi_pulso", {})]
    local.respuestas = ["Tu pulso está tranquilo."]
    luna.responder("dime algo útil para hoy")
    assert len(nube.recibido) == 1                                   # después de mi_pulso, solo el PC
    assert "72" in str(local.recibido[0]["mensajes"])
    assert "72" not in str(nube.recibido)


def test_pregunta_de_salud_va_directo_al_pc(luna):
    nube, local = luna.PROVEEDORES["claude"], luna.PROVEEDORES["ollama"]
    nube._configurado = True
    local.respuestas = ["Bien."]
    luna.responder("¿cómo va mi pulso?")
    assert nube.recibido == []


def test_pulso_remoto_requiere_pin(luna):
    with pytest.raises(Exception):
        correr(luna.salud_pulso(PeticionJSON({"bpm": 70}, host="100.101.1.2")))


def test_notificaciones_api(luna):
    luna.NOTIF.notificar("codigo", "Prueba", "detalle", codigo="print('hola')")
    r = luna.ver_notificaciones(Peticion())
    assert r["no_leidas"] >= 1 and r["notificaciones"][0]["codigo"] == "print('hola')"
    m = correr(luna.marcar_notificaciones(PeticionJSON({})))
    assert m["no_leidas"] == 0


def test_abrir_programa_desconocido_no_notifica(luna):
    antes = len(luna.NOTIF.listar())
    luna.abrir_programa("programa que no existe")
    assert len(luna.NOTIF.listar()) == antes


def test_proyectos_y_archivos_endpoints(luna):
    assert "proyectos" in luna.ver_proyectos_api(Peticion())
    assert "estado" in luna.archivos_estado(Peticion())
    with pytest.raises(Exception):                                   # organizar desde fuera sin PIN: no
        correr(luna.archivos_organizar(PeticionJSON({}, host="192.168.1.9")))


def test_enrutador_en_el_panel(luna):
    luna.PROVEEDORES["ollama"].respuestas = ["Hola."]
    luna.responder("hola")
    assert luna.CEREBRO.estado()["eleccion"]["clase"] == "simple"
    assert "texto" not in json.dumps(luna.CEREBRO.estado()["eleccion"])


def test_memoria_estado(luna):
    r = luna.estado_memoria(Peticion())
    assert "semantica" in r and r["mensajes"] >= 0
