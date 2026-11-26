"""Memoria por capas y proyectos contextuales (LEK 2.0, fase 3)."""
import json

import pytest

from conftest import Peticion, llamada
from lek.almacen import Almacen
from lek.memoria_capas import Memoria
from lek.proyectos_contexto import ProyectosContexto


@pytest.fixture
def mem(tmp_path):
    alm = Almacen(tmp_path)
    m = Memoria(alm)
    m.migrar()
    return m


def test_migracion_conserva_recuerdos_viejos(tmp_path):
    alm = Almacen(tmp_path)
    alm.recordar("Estudia en la UAN")
    alm.recordar("Le gustaba el té")
    alm.archivar_recuerdos("té")
    m = Memoria(alm)
    assert m.necesita_migracion()
    m.migrar()
    assert not m.necesita_migracion()
    assert [r["dato"] for r in m.vigentes()] == ["Estudia en la UAN"]
    assert alm._q("SELECT vigencia FROM recuerdos WHERE dato LIKE '%té%'")[0]["vigencia"] == "olvidado"
    assert m.migrar()["columnas_agregadas"] == []                    # idempotente


def test_dato_que_cambia_reemplaza_al_anterior(mem):
    mem.recordar("Prefiere escala 1:100 para maquetas", "preferencia", clave="escala preferida")
    r = mem.recordar("Prefiere escala 1:50 para maquetas", "preferencia", clave="escala preferida")
    assert r["estado"] == "reemplazo"
    vigentes = [x["dato"] for x in mem.vigentes()]
    assert vigentes == ["Prefiere escala 1:50 para maquetas"]          # nada contradictorio vigente
    historial = mem.historial(r["id"])
    assert [h["dato"] for h in historial] == ["Prefiere escala 1:50 para maquetas", "Prefiere escala 1:100 para maquetas"]


def test_parecido_sin_clave_avisa_para_no_duplicar(mem):
    mem.recordar("Su profesor de Taller 4 es Julian Villa", "persona")
    r = mem.recordar("Su profesor de Taller 4 ahora es otro", "persona")
    assert r["estado"] == "nuevo" and r["parecidos"]


def test_actualizar_y_por_que(mem):
    r = mem.recordar("Vive en Palmira", "dato_personal", fuente="mensaje:7")
    mem.almacen.guardar_mensaje("usuario", "yo vivo en Palmira", "web")
    mem.actualizar("Palmira", "Vive en Cali", "se mudó")
    assert [x["dato"] for x in mem.vigentes()] == ["Vive en Cali"]
    explicacion = mem.por_que("Cali")
    assert "confirmado por Sergio" in explicacion and "Antes decía: «Vive en Palmira»" in explicacion


def test_inferido_nunca_aparece_como_hecho(mem):
    mem.recordar("Parece que trabaja de noche", "dato_personal", tipo="inferido")
    texto = mem.texto_para_prompt()
    assert "inferido (no confirmado)" in texto
    assert mem.vigentes()[0]["confianza"] == 0.5


def test_temporal_expira(mem):
    mem.recordar("Esta semana está en parciales", "dato_personal", tipo="temporal", expira="2020-01-01")
    assert mem.vigentes() == []
    assert mem.almacen._q("SELECT vigencia FROM recuerdos")[0]["vigencia"] == "expirado"


def test_olvidar_limpia_el_indice(mem):
    with mem.almacen._candado:
        mem.almacen.con.execute("CREATE TABLE IF NOT EXISTS vectores(id INTEGER PRIMARY KEY, tipo TEXT, ref TEXT)")
    r = mem.recordar("Contraseña del wifi en la nevera")
    mem.almacen._x("INSERT INTO vectores(tipo, ref) VALUES ('recuerdo', ?)", (str(r["id"]),))
    assert mem.olvidar("wifi")
    assert mem.almacen._q("SELECT count(*) AS n FROM vectores")[0]["n"] == 0
    assert mem.vigentes() == []


def test_buscar_relacionados(mem):
    mem.recordar("La maqueta de Las Delicias es en balso", "proyecto")
    mem.recordar("Le gusta el café", "preferencia")
    assert [r["dato"] for r in mem.buscar("¿de qué material es la maqueta?")] == ["La maqueta de Las Delicias es en balso"]


def test_exportar_importar(mem, tmp_path):
    mem.recordar("Estudia arquitectura", "dato_personal")
    datos = json.loads(json.dumps(mem.exportar()))
    otra = Memoria(Almacen(tmp_path / "otra"))
    otra.migrar()
    assert otra.importar(datos) == {"importados": 1}
    assert otra.importar(datos) == {"importados": 0}                  # sin duplicados
    with pytest.raises(ValueError):
        otra.importar({"formato": "otra cosa"})


# ---------------------------------------------------------------- proyectos contextuales
@pytest.fixture
def pc(tmp_path):
    return ProyectosContexto(Almacen(tmp_path))


def test_decisiones_separadas_de_propuestas(pc):
    pc.crear("Las Delicias", "Centro de resiliencia climática", alias=["delicias", "centro de resiliencia"])
    pc.registrar("las-delicias", "decision", "4 pisos: vivienda arriba, equipamiento abajo")
    prop = pc.registrar("las-delicias", "propuesta", "Fachada con celosía de ladrillo")
    pc.registrar("las-delicias", "restriccion", "Altura máxima 15 m")
    pc.registrar("las-delicias", "fecha", "Entrega final", fecha_objetivo="2099-12-05")
    resumen = pc.resumen("las-delicias")
    assert "Decisiones confirmadas: #1 4 pisos" in resumen
    assert "Propuestas pendientes (NO confirmadas): #2 Fachada" in resumen
    assert "(2099-12-05)" in resumen
    pc.aprobar(prop["id"])
    assert "celosía" in " ".join(i["contenido"] for i in pc.items("las-delicias", "decision"))
    assert pc.items("las-delicias", "propuesta") == []


def test_reemplazo_conserva_historial(pc):
    pc.crear("Maqueta")
    viejo = pc.registrar("maqueta", "decision", "Escala 1:100")
    pc.registrar("maqueta", "decision", "Escala 1:75", reemplaza=viejo["id"])
    assert [i["contenido"] for i in pc.items("maqueta", "decision")] == ["Escala 1:75"]
    assert len(pc.items("maqueta", "decision", incluir_historial=True)) == 2


def test_buscar_y_detectar_por_alias(pc):
    pc.crear("Las Delicias", alias=["centro de resiliencia"])
    assert pc.buscar("las delicias")["slug"] == "las-delicias"
    assert pc.buscar("Delicias")["slug"] == "las-delicias"
    assert pc.detectar("¿cómo vamos con el centro de resiliencia?")["slug"] == "las-delicias"
    assert pc.detectar("hablemos de comida") is None


def test_trabajemos_en_las_delicias(luna):
    luna.PROYECTOS_CTX.crear("Las Delicias", "Centro de resiliencia climática")
    luna.PROYECTOS_CTX.registrar("las-delicias", "decision", "4 pisos")
    luna.PROYECTOS_CTX.registrar("las-delicias", "propuesta", "Cubierta verde")
    local = luna.PROVEEDORES["ollama"]
    local.respuestas = [llamada("trabajar_en", {"proyecto": "Las Delicias"}), "Retomemos: tenemos 4 pisos confirmados."]
    luna.responder("Luna, trabajemos en Las Delicias")
    tool = [m for m in local.recibido[-1]["mensajes"] if m["role"] == "tool"][0]["content"]
    assert "Decisiones confirmadas: #1 4 pisos" in tool and "Propuestas pendientes" in tool
    assert luna.PROYECTOS_CTX.activo()["slug"] == "las-delicias"
    local.respuestas = ["Sí, la cubierta verde sigue como propuesta."]
    luna.responder("¿qué falta decidir?")
    nota = local.recibido[-1]["mensajes"][-1]["content"]
    assert "Proyecto activo" in nota and "Cubierta verde" in nota
    assert luna.PROYECTOS_CTX.conversaciones("las-delicias")["n"] == 4   # mensajes asociados al proyecto


def test_con_nube_el_proyecto_no_sale_del_pc(luna):
    luna.PROYECTOS_CTX.crear("Las Delicias")
    luna.PROYECTOS_CTX.registrar("las-delicias", "decision", "Presupuesto secreto de 900 millones")
    luna.PROYECTOS_CTX.activar("las-delicias")
    nube = luna.PROVEEDORES["claude"]
    nube._configurado = True
    nube.respuestas = ["Claro."]
    luna.responder("dime algo útil para hoy")
    assert "900 millones" not in str(nube.recibido) and "Las Delicias" in str(nube.recibido)


def test_luna_recuerda_con_procedencia(luna):
    local = luna.PROVEEDORES["ollama"]
    local.respuestas = [llamada("recordar", {"dato": "Prefiere láminas en A1", "categoria": "preferencia"}), "Anotado."]
    luna.responder("recuerda que prefiero las láminas en A1")
    r = luna.MEMORIA_CAPAS.vigentes()[0]
    assert r["fuente"].startswith("mensaje:") and r["categoria"] == "preferencia"
    assert "prefiero las láminas en A1" in luna.MEMORIA_CAPAS.por_que("A1")


def test_endpoints_de_memoria(luna):
    luna.ejecutar_herramienta("recordar", {"dato": "Prefiere láminas en A1", "categoria": "preferencia"})
    pc = Peticion()
    assert luna.ver_recuerdos(pc)["recuerdos"][0]["dato"] == "Prefiere láminas en A1"
    assert "confirmado" in luna.por_que_api(pc, ref="A1")["explicacion"]
    datos = luna.exportar_memoria(pc).contenido
    assert datos["formato"] == "lek-memoria-1" and "pendientes" in datos
    luna.olvidar_api(luna.RefRecuerdo(ref="A1"), pc)
    assert luna.ver_recuerdos(pc)["recuerdos"] == []
    with pytest.raises(Exception):
        luna.olvidar_api(luna.RefRecuerdo(ref="1"), Peticion(host="192.168.1.9"))   # desde fuera sin PIN, no
