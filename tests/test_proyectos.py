"""Objetivos, proyectos y tareas persistentes (lek/autonomia). Sin red y sin cerebros reales."""
import json
import time

import pytest

from lek.almacen import Almacen
from lek.autonomia.programador import Programador
from lek.autonomia.proyectos import (GestorProyectos, TransicionInvalida, extraer_json, herramientas_luna,
                                     validar_plan)


def plan(*tareas, titulo="Entrega final", presupuesto=0):
    return json.dumps({"titulo": titulo, "presupuesto_usd": presupuesto, "tareas": list(tareas)})


def pensar_con(texto):
    pedidos = []

    def pensar(prompt):
        pedidos.append(prompt)
        return texto.pop(0) if isinstance(texto, list) else texto
    pensar.pedidos = pedidos
    return pensar


PLAN_LINEAL = plan({"clave": "a", "titulo": "Reunir normas de equipamientos"},
                   {"clave": "b", "titulo": "Calcular áreas del programa", "depende_de": ["a"]},
                   {"clave": "c", "titulo": "Redactar memoria", "depende_de": ["b"]})


class Ejecutor:
    """Ejecutor falso: registra lo que hace y responde según lo programado por título."""

    def __init__(self, fallar=(), bloquear=()):
        self.hechas, self.fallar, self.bloquear = [], set(fallar), set(bloquear)

    def __call__(self, tarea, punto):
        self.hechas.append(tarea["titulo"])
        if tarea["titulo"] in self.fallar:
            raise RuntimeError("sin datos")
        if tarea["titulo"] in self.bloquear:
            return {"estado": "bloqueada", "motivo": "falta el plano del lote"}
        return {"resultado": f"hecho: {tarea['titulo']}", "evidencia": "archivo.txt"}


@pytest.fixture
def almacen(tmp_path):
    return Almacen(tmp_path / "datos")


@pytest.fixture
def gestor(almacen):
    return GestorProyectos(almacen)


def nuevo_proyecto(gestor, texto=PLAN_LINEAL, aprobar=True):
    oid = gestor.crear_objetivo("Entregar el centro de resiliencia", "Plantas y memoria listas", 1, "2026-12-05")
    pid = gestor.planificar(oid, pensar_con(texto))
    if aprobar:
        gestor.aprobar_plan(pid)
    return pid


def estados(gestor, pid):
    return [t["estado"] for t in gestor.tareas(pid)]


# ---------------------------------------------------------------- plan
def test_plan_queda_propuesto_hasta_aprobar(gestor):
    pid = nuevo_proyecto(gestor, aprobar=False)
    assert gestor.proyecto(pid)["estado"] == "propuesto"
    assert estados(gestor, pid) == ["propuesta"] * 3
    prog = Programador(gestor, Ejecutor())
    assert prog.tick()["hecho"] == "nada"          # sin aprobar no se ejecuta nada
    gestor.aprobar_plan(pid)
    assert estados(gestor, pid) == ["lista"] * 3
    with pytest.raises(TransicionInvalida):
        gestor.aprobar_plan(pid)                   # no se aprueba dos veces


def test_planificar_tolera_texto_alrededor_y_reintenta(gestor):
    oid = gestor.crear_objetivo("Maqueta")
    pensar = pensar_con(["no sé", "<think>hmm</think> Aquí va:\n```json\n" + PLAN_LINEAL + "\n```"])
    pid = gestor.planificar(oid, pensar)
    assert len(gestor.tareas(pid)) == 3 and len(pensar.pedidos) == 2
    ts = gestor.tareas(pid)
    assert ts[1]["depende_de"] == [ts[0]["id"]]
    with pytest.raises(ValueError):
        gestor.planificar(oid, pensar_con("nada de JSON"))
    assert len(gestor._q("SELECT * FROM proyectos")) == 1  # el fallo no deja nada a medias


def test_plan_con_ciclo_o_dependencia_inexistente_se_rechaza():
    with pytest.raises(ValueError, match="ciclo"):
        validar_plan(json.loads(plan({"clave": "a", "titulo": "A", "depende_de": ["b"]},
                                     {"clave": "b", "titulo": "B", "depende_de": ["a"]})))
    with pytest.raises(ValueError, match="no existe"):
        validar_plan(json.loads(plan({"clave": "a", "titulo": "A", "depende_de": ["z"]})))
    with pytest.raises(ValueError, match="ciclo"):  # una hija no puede depender de su madre
        validar_plan(json.loads(plan({"clave": "m", "titulo": "M"},
                                     {"clave": "h", "titulo": "H", "madre": "m", "depende_de": ["m"]})))
    assert extraer_json({"role": "assistant", "content": PLAN_LINEAL})["titulo"] == "Entrega final"


# ---------------------------------------------------------------- ciclo completo y dependencias
def test_ciclo_completo_respeta_dependencias(gestor):
    pid = nuevo_proyecto(gestor)
    ej = Ejecutor()
    prog = Programador(gestor, ej)
    assert prog.tick() == {"hecho": "completada", "tarea": gestor.tareas(pid)[0]["id"]}
    assert estados(gestor, pid) == ["completada", "lista", "lista"]
    assert gestor.avance(pid) == 33
    prog.tick()
    prog.tick()
    assert ej.hechas == ["Reunir normas de equipamientos", "Calcular áreas del programa", "Redactar memoria"]
    assert gestor.avance(pid) == 100
    assert gestor.proyecto(pid)["estado"] == "completado"
    assert gestor.objetivo(gestor.proyecto(pid)["objetivo_id"])["estado"] == "completado"
    assert prog.tick()["hecho"] == "nada"
    t = gestor.tareas(pid)[2]
    assert t["resultado"] == "hecho: Redactar memoria" and t["evidencia"] == "archivo.txt"
    assert gestor.eventos("tarea", t["id"])                      # todo deja rastro


def test_resultados_previos_llegan_a_la_tarea_siguiente(gestor):
    pid = nuevo_proyecto(gestor)
    recibido = []
    prog = Programador(gestor, lambda t, p: recibido.append(t) or "listo " + t["titulo"])
    prog.tick()
    prog.tick()
    a = gestor.tareas(pid)[0]["id"]
    assert recibido[1]["resultados_previos"] == {a: "listo Reunir normas de equipamientos"}
    assert recibido[1]["objetivo"] == "Entregar el centro de resiliencia"


def test_dependencia_no_cumplida_no_se_toma_y_fallida_bloquea(gestor):
    texto = plan({"clave": "a", "titulo": "A"}, {"clave": "b", "titulo": "B", "depende_de": ["a"]},
                 {"clave": "c", "titulo": "C"})
    pid = nuevo_proyecto(gestor, texto)
    ej = Ejecutor(fallar={"A"})
    prog = Programador(gestor, ej)
    for _ in range(6):
        prog.tick()
    assert ej.hechas == ["A", "C", "A", "A"]            # B nunca se toma: A no se completó
    assert estados(gestor, pid) == ["fallida", "bloqueada", "completada"]
    assert gestor.proyecto(pid)["estado"] == "activo"   # no se completa con una fallida


def test_subtareas_completan_a_su_madre(gestor):
    texto = plan({"clave": "m", "titulo": "Plantas"},
                 {"clave": "p1", "titulo": "Planta 1", "madre": "m"},
                 {"clave": "p2", "titulo": "Planta 2", "madre": "m"},
                 {"clave": "r", "titulo": "Revisar plantas", "depende_de": ["m"]})
    pid = nuevo_proyecto(gestor, texto)
    ej = Ejecutor()
    prog = Programador(gestor, ej)
    for _ in range(4):
        prog.tick()
    assert ej.hechas == ["Planta 1", "Planta 2", "Revisar plantas"]  # la madre no se "ejecuta"
    assert estados(gestor, pid) == ["completada"] * 4
    assert gestor.avance(pid) == 100


def test_transiciones_invalidas_se_rechazan(gestor):
    pid = nuevo_proyecto(gestor, aprobar=False)
    tid = gestor.tareas(pid)[0]["id"]
    with pytest.raises(TransicionInvalida):
        gestor.cambiar_estado(tid, "completada")       # propuesta -> completada no existe
    gestor.aprobar_plan(pid)
    with pytest.raises(TransicionInvalida):
        gestor.cambiar_estado(tid, "esperando_aprobacion")
    gestor.cancelar(pid)
    with pytest.raises(TransicionInvalida):
        gestor.cambiar_estado(tid, "lista")            # cancelada es definitiva
    assert estados(gestor, pid) == ["cancelada"] * 3


# ---------------------------------------------------------------- intentos y reinicio
def test_tres_intentos_y_queda_fallida(gestor):
    pid = nuevo_proyecto(gestor, plan({"titulo": "A"}))
    ej = Ejecutor(fallar={"A"})
    prog = Programador(gestor, ej)
    assert prog.tick()["estado"] == "lista"
    assert prog.tick()["estado"] == "lista"
    assert prog.tick()["estado"] == "fallida"
    assert prog.tick()["hecho"] == "nada"
    t = gestor.tareas(pid)[0]
    assert t["intentos"] == 3 and t["estado"] == "fallida" and "sin datos" in t["resultado"]


class Apagon(BaseException):
    """Simula que el PC se apaga a mitad de una tarea (no es una Exception: nadie la atrapa)."""


def test_reinicio_a_mitad_continua_desde_punto_de_control(tmp_path):
    almacen = Almacen(tmp_path / "datos")
    gestor = GestorProyectos(almacen)
    pid = nuevo_proyecto(gestor, plan({"titulo": "Calcular áreas"}))
    pasos = []

    def primera_vez(tarea, punto):
        pasos.append("paso 1")
        punto.guardar(paso=1, areas={"aulas": 240})
        raise Apagon()

    with pytest.raises(Apagon):
        Programador(gestor, primera_vez).tick()
    assert estados(gestor, pid) == ["en_curso"]
    almacen.con.close()

    # LUNA vuelve a encender: otra conexión al mismo luna.db
    gestor2 = GestorProyectos(Almacen(tmp_path / "datos"))

    def despues(tarea, punto):
        if punto.get("paso", 0) < 1:
            pasos.append("paso 1")
        pasos.append("paso 2")
        return f"total {punto.datos['areas']['aulas'] + 60} m2"

    prog = Programador(gestor2, despues)
    assert prog.retomar_al_arrancar()["continuan"] == [gestor2.tareas(pid)[0]["id"]]
    prog.tick()
    t = gestor2.tareas(pid)[0]
    assert pasos == ["paso 1", "paso 2"]                 # el paso 1 no se repite
    assert t["estado"] == "completada" and t["intentos"] == 0 and t["resultado"] == "total 300 m2"


def test_reinicio_sin_punto_de_control_suma_intento(gestor):
    pid = nuevo_proyecto(gestor, plan({"titulo": "A"}))
    tid = gestor.tareas(pid)[0]["id"]
    for i in range(1, 4):
        gestor.cambiar_estado(tid, "en_curso")
        informe = gestor.retomar_al_arrancar()
        if i < 3:
            assert informe["reintentan"] == [tid] and gestor.tareas(pid)[0]["intentos"] == i
    assert informe["fallidas"] == [tid] and estados(gestor, pid) == ["fallida"]


# ---------------------------------------------------------------- aprobaciones (nivel 2)
PLAN_NIVEL2 = plan({"clave": "a", "titulo": "Investigar imprenta"},
                   {"clave": "b", "titulo": "Pagar impresión de planos", "depende_de": ["a"], "nivel_autorizacion": 2,
                    "costo_usd": 12, "riesgo": "gasta dinero"}, presupuesto=20)


def test_nivel_2_pide_aprobacion_y_solo_se_ejecuta_una_vez(gestor):
    pid = nuevo_proyecto(gestor, PLAN_NIVEL2)
    avisos = []
    gestor.avisar = avisos.append
    ej = Ejecutor()
    prog = Programador(gestor, ej)
    prog.tick()
    r = prog.tick()
    assert r["hecho"] == "pide_aprobacion"
    assert estados(gestor, pid) == ["completada", "esperando_aprobacion"]
    pendientes = gestor.aprobaciones_pendientes()
    assert len(pendientes) == 1 and pendientes[0]["costo"] == 12 and pendientes[0]["riesgo"] == "gasta dinero"
    assert any("permiso" in a for a in avisos)
    assert prog.tick()["hecho"] == "nada"              # sin respuesta no avanza
    gestor.responder_aprobacion(pendientes[0]["id"], True)
    assert prog.tick()["hecho"] == "completada"
    assert ej.hechas.count("Pagar impresión de planos") == 1
    with pytest.raises(TransicionInvalida):
        gestor.responder_aprobacion(pendientes[0]["id"], True)
    assert gestor._q("SELECT respuesta FROM aprobaciones")[0]["respuesta"] == "usada"


def test_aprobacion_rechazada_cancela_la_tarea(gestor):
    pid = nuevo_proyecto(gestor, plan({"titulo": "Enviar correo al profesor", "nivel_autorizacion": 2}))
    prog = Programador(gestor, Ejecutor())
    prog.tick()
    gestor.responder_aprobacion(gestor.aprobaciones_pendientes()[0]["id"], False)
    assert estados(gestor, pid) == ["cancelada"]
    assert prog.tick()["hecho"] == "nada"


def test_nivel_2_interrumpido_nunca_se_repite_solo(gestor):
    pid = nuevo_proyecto(gestor, plan({"titulo": "Pagar", "nivel_autorizacion": 2}))
    pagos = []

    def pagar(tarea, punto):
        pagos.append(1)
        punto.guardar(pagado=True)
        raise Apagon()

    prog = Programador(gestor, pagar)
    prog.tick()
    gestor.responder_aprobacion(gestor.aprobaciones_pendientes()[0]["id"], True)
    with pytest.raises(Apagon):
        prog.tick()
    informe = Programador(gestor, pagar).retomar_al_arrancar()
    tid = gestor.tareas(pid)[0]["id"]
    assert informe["bloqueadas"] == [tid] and estados(gestor, pid) == ["bloqueada"]
    for _ in range(3):
        prog.tick()
    assert pagos == [1]
    gestor.desbloquear(tid)                             # el usuario decide reintentar...
    assert prog.tick()["hecho"] == "pide_aprobacion"    # ...y aun así se pide permiso nuevo
    assert pagos == [1]


def test_nivel_2_que_falla_pide_permiso_otra_vez(gestor):
    nuevo_proyecto(gestor, plan({"titulo": "Pagar", "nivel_autorizacion": 2}))
    ej = Ejecutor(fallar={"Pagar"})
    prog = Programador(gestor, ej)
    prog.tick()
    gestor.responder_aprobacion(gestor.aprobaciones_pendientes()[0]["id"], True)
    assert prog.tick()["hecho"] == "fallo"
    assert prog.tick()["hecho"] == "pide_aprobacion"
    assert ej.hechas == ["Pagar"]


def test_presupuesto_excedido_bloquea(gestor):
    pid = nuevo_proyecto(gestor, plan({"titulo": "Comprar maqueta", "nivel_autorizacion": 2, "costo_usd": 50},
                                      presupuesto=20))
    assert Programador(gestor, Ejecutor()).tick()["hecho"] == "bloqueada"
    assert estados(gestor, pid) == ["bloqueada"] and not gestor.aprobaciones_pendientes()


def test_ejecutor_puede_bloquear_y_usuario_completar(gestor):
    pid = nuevo_proyecto(gestor, plan({"titulo": "A"}))
    prog = Programador(gestor, Ejecutor(bloquear={"A"}))
    assert prog.tick()["hecho"] == "bloqueada"
    gestor.marcar_completada(gestor.tareas(pid)[0]["id"], "lo hice a mano")
    assert gestor.proyecto(pid)["estado"] == "completado"


# ---------------------------------------------------------------- PC ocupado, pausa e hilo
def test_pc_ocupado_no_ejecuta(gestor):
    pid = nuevo_proyecto(gestor)
    libre = {"si": False}
    ej = Ejecutor()
    prog = Programador(gestor, ej, pc_libre=lambda: libre["si"])
    assert prog.tick()["hecho"] == "pc_ocupado"
    assert ej.hechas == [] and estados(gestor, pid) == ["lista"] * 3
    prog.pc_libre = lambda: 1 / 0                      # si la medición falla, no trabaja
    assert prog.tick()["hecho"] == "pc_ocupado"
    prog.pc_libre = lambda: libre["si"]
    libre["si"] = True
    assert prog.tick()["hecho"] == "completada"


def test_pausar_reanudar_y_cancelar(gestor):
    pid = nuevo_proyecto(gestor)
    prog = Programador(gestor, Ejecutor())
    gestor.pausar(pid)
    assert prog.tick()["hecho"] == "nada"
    gestor.reanudar(pid)
    assert prog.tick()["hecho"] == "completada"
    gestor.accion(pid, "cancelar")
    assert estados(gestor, pid) == ["completada", "cancelada", "cancelada"]
    with pytest.raises(TransicionInvalida):
        gestor.reanudar(pid)
    with pytest.raises(ValueError):
        gestor.accion(pid, "borrar")


def test_hilo_trabaja_y_se_detiene_limpio(gestor):
    pid = nuevo_proyecto(gestor)
    prog = Programador(gestor, Ejecutor(), intervalo=0.01)
    prog.arrancar()
    limite = time.time() + 5
    while gestor.proyecto(pid)["estado"] != "completado" and time.time() < limite:
        time.sleep(0.02)
    assert prog.detener(espera=5) is True
    assert not prog.corriendo
    assert gestor.proyecto(pid)["estado"] == "completado"


# ---------------------------------------------------------------- API y herramientas de Luna
def test_forma_api_y_herramientas(gestor):
    defs, funciones = herramientas_luna(gestor, pensar_con(PLAN_NIVEL2))
    assert {d["function"]["name"] for d in defs} == {"crear_objetivo", "ver_proyectos"}
    texto = funciones["crear_objetivo"]("Imprimir planos", "planos impresos", 2, "2026-12-01")
    assert "No empiezo hasta que lo apruebes" in texto and "necesita tu permiso" in texto
    api = gestor.resumen_api()
    p = api["proyectos"][0]
    assert set(p) == {"id", "titulo", "estado", "avance", "tareas"}
    assert p["estado"] == "propuesto" and p["avance"] == 0
    assert p["tareas"] == [{"titulo": "Investigar imprenta", "estado": "propuesta"},
                           {"titulo": "Pagar impresión de planos", "estado": "propuesta"}]
    assert "Proyecto #" in funciones["ver_proyectos"]()
    assert "No pude crear" in funciones["crear_objetivo"]("Algo", fecha_limite="mañana")


def test_tabla_con_otra_forma_da_error_claro(almacen):
    almacen.con.execute("CREATE TABLE eventos (id INTEGER PRIMARY KEY, titulo TEXT)")
    almacen.con.commit()
    with pytest.raises(RuntimeError, match="eventos"):
        GestorProyectos(almacen)
