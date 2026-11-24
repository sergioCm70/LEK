"""Pruebas de la autoevaluación: el banco, sus verificadores, el evaluador, el informe y el historial."""
import datetime
import json

import pytest

from conftest import CerebroFalso, ErrorProveedor, Respuesta, llamada
from lek.almacen import Almacen
from lek.evaluacion import CASOS, CATEGORIAS, VERSION_BANCO, Salida, evaluar, guardar, historial, informe_comparativo
from lek.evaluacion import evaluador as ev
from lek.evaluacion.banco import HERRAMIENTAS_FALSAS, numeros_en

POR_ID = {c.id: c for c in CASOS}

# id -> (herramienta que llama o None, texto final). Una respuesta buena y una mala por caso.
BUENAS = {
    "esc-01": (None, "Mide 6,4 cm en la maqueta."),
    "esc-02": (None, "Son 14 m reales; en la maqueta, 28 cm."),
    "esc-03": (None, "Mide 9 cm."),
    "esc-04": (None, "Mide 4,3 m en la realidad."),
    "esc-05": (None, "Tiene 3 mm de grosor."),
    "con-01": (None, "Son 25.000 cm²."),
    "con-02": (None, "Son 30 000 m²."),
    "con-03": (None, "Son 25,4 cm."),
    "fec-01": (None, "Cae sábado."),
    "fec-02": (None, "Es viernes."),
    "fec-03": (None, "Hay 11 días."),
    "fec-04": (None, "Sería el 5 de diciembre de 2026."),
    "are-01": (None, "Son 14 m²."),
    "are-02": (None, "El total es 48 m²."),
    "are-03": (None, "Puedes ocupar 360 m² en primer piso."),
    "are-04": (None, "Aproximadamente 28,27 m²."),
    "arq-01": (None, "La diseñó Le Corbusier."),
    "arq-02": (None, "Frank Lloyd Wright."),
    "arq-03": (None, "Pilotis, planta libre, fachada libre, ventana longitudinal y terraza jardín."),
    "arq-04": (None, "Principalmente la tracción."),
    "her-01": (("abrir_programa", {"nombre": "Revit"}), "Listo, abrí Revit."),
    "her-02": (("guardar_nota", {"texto": "comprar balso para la maqueta el viernes"}), "Nota guardada."),
    "her-03": (("buscar_internet", {"consulta": "precio dólar Colombia hoy"}), "Está a 4.000 pesos."),
    "her-04": (("buscar_documentos", {"consulta": "NSR-10"}), "No encontré nada sobre eso en tus apuntes."),
    "voz-01": (None, "Es un corte horizontal del edificio a un metro de altura, visto desde arriba."),
    "voz-02": (None, "Cuida la iluminación, limpia bien los bordes y lleva una lámina con el concepto."),
    "voz-03": (None, "Es el Reglamento Colombiano de Construcción Sismo Resistente."),
    "inv-01": (("buscar_conversaciones", {"consulta": "3 de enero de 2020"}),
               "No tengo ninguna conversación de esa fecha; mis registros empiezan en 2026."),
    "inv-02": (None, "No encuentro esa nota en tus documentos ni en nuestras conversaciones."),
    "inv-03": (None, "No me has dicho cómo se llama tu perro."),
}
MALAS = {
    "esc-01": (None, "Mide 3,2 cm."),
    "esc-02": (None, "Son 14 m reales; en la maqueta, 1,4 cm."),   # el número intermedio no cuenta como acierto
    "esc-03": (None, "Mide 3,6 cm."),
    "esc-04": (None, "Mide 43 cm."),
    "esc-05": (None, "Tiene 7,5 mm."),
    "con-01": (None, "Son 250 cm²."),
    "con-02": (None, "Son 3.000 m²."),
    "con-03": (None, "Son 2,54 cm."),
    "fec-01": (None, "Cae viernes."),
    "fec-02": (None, "Es jueves."),
    "fec-03": (None, "Hay 10 días."),
    "fec-04": (None, "Sería el 15 de diciembre."),
    "are-01": (None, "Son 15 m²."),
    "are-02": (None, "El total es 43,75 m²."),
    "are-03": (None, "Puedes ocupar 600 m²."),
    "are-04": (None, "Unos 113 m²."),
    "arq-01": (None, "La diseñó Mies van der Rohe."),
    "arq-02": (None, "Oscar Niemeyer."),
    "arq-03": (None, "Pilotis, planta libre y fachada libre."),
    "arq-04": (None, "La compresión."),
    "her-01": (None, "Listo, abrí Revit."),                         # dice que abrió sin llamar a la herramienta
    "her-02": (("abrir_programa", {"nombre": "notas"}), "Hecho."),
    "her-03": (None, "El dólar está a 4.000 pesos."),
    "her-04": (("buscar_internet", {"consulta": "NSR-10"}), "La NSR-10 es la norma sismo resistente."),
    "voz-01": (None, "# Planta\n- Es un **corte** horizontal."),
    "voz-02": (None, "1. Iluminación\n2. Bordes limpios\n3. Concepto claro"),
    "voz-03": (None, "La NSR-10 es el reglamento sismo resistente de Colombia. " * 10),
    "inv-01": (None, "Me dijiste que ibas a empezar la maqueta de Taller."),
    "inv-02": (None, "Sacaste un 4,2."),
    "inv-03": (None, "Se llama Max."),
}


def salida(plan) -> Salida:
    herramienta, texto = plan
    return Salida(texto=texto, herramientas=[herramienta] if herramienta else [])


def oraculo(planes, latencia=1.0, usd=0.0, tokens=(100, 20)):
    """Proveedor falso que responde cada pregunta del banco según `planes` (pide la herramienta y luego contesta)."""
    por_pregunta = {POR_ID[i].pregunta: p for i, p in planes.items()}

    def responder(mensajes):
        pregunta = next(m["content"] for m in mensajes if m["role"] == "user")
        herramienta, texto = por_pregunta.get(pregunta, (None, "no sé"))
        if herramienta and mensajes[-1]["role"] == "user":
            r = llamada(*herramienta)
        else:
            r = Respuesta(texto=texto)
        r.latencia, r.usd = latencia, usd
        r.tokens_entrada, r.tokens_salida = tokens
        return r

    return CerebroFalso("ollama", "local", respuestas=[responder] * 200)


# ---------------------------------------------------------------- banco
def test_banco_tiene_30_casos_unicos_y_todas_las_categorias():
    assert len(CASOS) == 30
    assert len({c.id for c in CASOS}) == 30
    assert set(CATEGORIAS) == {"escalas", "conversiones", "fechas", "areas", "conocimiento", "herramientas",
                               "formato_voz", "no_inventar"}
    assert VERSION_BANCO and set(BUENAS) == set(MALAS) == set(POR_ID)


def test_respuestas_de_fechas_calculadas_y_verificadas():
    assert datetime.date(2026, 12, 5).strftime("%A") == "Saturday"
    assert POR_ID["fec-01"].esperado == "sábado"
    assert datetime.date(2027, 1, 1).strftime("%A") == "Friday"
    assert POR_ID["fec-02"].esperado == "viernes"
    assert POR_ID["fec-03"].esperado == "11 días"
    assert POR_ID["fec-04"].esperado == "5 de diciembre"


@pytest.mark.parametrize("id_", sorted(POR_ID))
def test_cada_verificador_acepta_la_buena_y_rechaza_la_mala(id_):
    caso = POR_ID[id_]
    ok, motivo = caso.verificador(salida(BUENAS[id_]))
    assert ok, f"{id_} rechazó la buena: {motivo}"
    ok, motivo = caso.verificador(salida(MALAS[id_]))
    assert not ok and motivo != "ok", f"{id_} aceptó la mala"


def test_lectura_de_numeros_en_espanol_e_ingles():
    assert 25000 in numeros_en("son 25.000 cm2")
    assert 25000 in numeros_en("son 25 000 cm2")
    assert 6.4 in numeros_en("mide 6,4 cm.")
    assert 1234.5 in numeros_en("1,234.5") and 1234.5 in numeros_en("1.234,5")
    assert numeros_en("escala 1:50") == [1, 50]


def test_herramientas_falsas_usan_nombres_reales_de_luna():
    nombres = {h["function"]["name"] for h in HERRAMIENTAS_FALSAS}
    assert {"abrir_programa", "guardar_nota", "buscar_internet", "buscar_documentos", "buscar_conversaciones"} <= nombres


# ---------------------------------------------------------------- evaluador
def test_modelo_perfecto_saca_100_y_mide_tiempo_tokens_y_costo():
    r = evaluar(oraculo(BUENAS, latencia=2.0, usd=0.0001), "perfecto")
    assert (r["aciertos"], r["total"], r["pct"]) == (30, 30, 100.0)
    assert all(c["pct"] == 100.0 for c in r["categorias"].values())
    caso = next(c for c in r["casos"] if c["id"] == "her-01")
    assert caso["herramientas"] == ["abrir_programa"] and caso["segundos"] == 4.0  # dos rondas de 2 s
    assert caso["tokens"] == 240 and r["mediana_s"] == 2.0
    assert r["usd"] == pytest.approx(0.0001 * 35)   # 25 casos de una ronda + 5 que usan herramienta (dos rondas)
    for c in r["casos"]:
        assert set(c) >= {"ok", "segundos", "tokens", "motivo"}


def test_modelo_malo_falla_con_motivos():
    r = evaluar(oraculo(MALAS), "malo")
    assert r["aciertos"] == 0
    assert all(not c["ok"] and c["motivo"] for c in r["casos"])


def test_la_herramienta_falsa_devuelve_el_resultado_programado_y_sin_herramientas_no_se_ofrecen():
    prov = oraculo(BUENAS)
    evaluar(prov, "m", [POR_ID["inv-01"], POR_ID["esc-01"]])
    segunda = prov.recibido[1]
    assert segunda["herramientas"] is HERRAMIENTAS_FALSAS
    assert segunda["mensajes"][-1]["role"] == "tool"
    assert "2026" in segunda["mensajes"][-1]["content"]
    assert prov.recibido[2]["herramientas"] is None


def test_quita_el_razonamiento_interno_antes_de_verificar():
    prov = CerebroFalso(respuestas=["<think>quizá 5</think>Cae sábado."])
    r = evaluar(prov, "qwen3:8b", [POR_ID["fec-01"]])
    assert r["aciertos"] == 1 and r["casos"][0]["respuesta"] == "Cae sábado."


def test_un_error_no_tumba_la_evaluacion_pero_saldo_agotado_la_detiene():
    prov = CerebroFalso(respuestas=[ErrorProveedor("red", "caída", True), "Mide 9 cm.",
                                    ErrorProveedor("saldo", "sin crédito")])
    r = evaluar(prov, "m", [POR_ID["esc-01"], POR_ID["esc-03"], POR_ID["esc-04"], POR_ID["esc-05"]])
    motivos = [c["motivo"] for c in r["casos"]]
    assert motivos[0].startswith("error") and r["casos"][1]["ok"]
    assert motivos[3].startswith("no evaluado") and r["incompleto"]
    assert len(prov.recibido) == 3


def test_registra_las_llamadas_en_el_almacen_para_el_presupuesto(tmp_path):
    almacen = Almacen(tmp_path)
    evaluar(oraculo(BUENAS, usd=0.01), "claude-haiku-5-5", [POR_ID["esc-01"], POR_ID["her-01"]], almacen=almacen)
    filas = almacen.ultimas_llamadas()
    assert len(filas) == 2 and all(f["motivo"].startswith("autoevaluación") for f in filas)
    assert almacen.gasto_del_mes() == pytest.approx(0.03)


# ---------------------------------------------------------------- informe comparativo
def resultado(modelo, pct, mediana, usd, categorias=None):
    aciertos = round(pct * 30 / 100)
    return {"modelo": modelo, "pct": pct, "aciertos": aciertos, "total": 30, "mediana_s": mediana, "usd": usd,
            "categorias": categorias or {"escalas": {"pct": 100.0}}, "incompleto": "", "casos": [],
            "proveedor": "x", "tokens": 0, "version_banco": VERSION_BANCO, "fecha": "2026-11-24T10:00:00"}


def test_si_el_barato_empata_dentro_de_5_puntos_se_recomienda_el_barato():
    inf = informe_comparativo([resultado("claude-opus-5-5", 93.3, 4.0, 0.40),
                               resultado("claude-haiku-5-5", 90.0, 1.5, 0.01)])
    assert inf["recomendado"] == "claude-haiku-5-5"
    assert "3.3 puntos más" in inf["recomendacion"]


def test_si_la_diferencia_es_grande_gana_la_calidad_aunque_cueste_mas():
    inf = informe_comparativo([resultado("qwen3:8b", 70.0, 9.0, 0.0), resultado("claude-haiku-5-5", 90.0, 1.5, 0.01)])
    assert inf["recomendado"] == "claude-haiku-5-5"


def test_entre_gratis_y_barato_empatados_gana_el_gratis_y_avisa_si_el_otro_es_mucho_mas_rapido():
    inf = informe_comparativo([resultado("qwen3:8b", 86.7, 12.0, 0.0, {"fechas": {"pct": 50.0}}),
                               resultado("claude-haiku-5-5", 90.0, 1.5, 0.01)])
    assert inf["recomendado"] == "qwen3:8b"
    assert "claude-haiku-5-5 responde en 1.5 s" in inf["recomendacion"]
    assert "fechas" in inf["recomendacion"]


def test_a_igual_costo_y_calidad_gana_el_mas_rapido_y_los_incompletos_no_compiten():
    inc = resultado("claude-sonnet-5-5", 100.0, 1.0, 0.0)
    inc["incompleto"] = "saldo: sin crédito"
    inf = informe_comparativo([resultado("qwen3:8b", 80.0, 12.0, 0.0), resultado("qwen3:4b", 80.0, 4.0, 0.0), inc])
    assert inf["recomendado"] == "qwen3:4b"
    assert "Sin evaluación completa" in inf["recomendacion"]


# ---------------------------------------------------------------- historial y regresiones
def test_guarda_en_tabla_evaluaciones_y_avisa_regresion_de_mas_de_10_puntos(tmp_path):
    almacen = Almacen(tmp_path)
    r1 = evaluar(oraculo(BUENAS), "qwen3:8b")
    g1 = guardar(almacen, r1)
    assert g1["anterior_pct"] is None and not g1["aviso"]
    columnas = [c[1] for c in almacen.con.execute("PRAGMA table_info(evaluaciones)")]
    assert columnas == ["id", "fecha", "modelo", "version_banco", "aciertos", "total", "mediana_s", "usd", "detalle"]

    # cae 2 casos (6,7 puntos): sin aviso
    planes = dict(BUENAS, **{k: MALAS[k] for k in ("esc-01", "esc-02")})
    assert not guardar(almacen, evaluar(oraculo(planes), "qwen3:8b"))["aviso"]

    # cae 5 casos más respecto a la anterior (16,7 puntos): aviso, con la categoría que empeoró
    planes.update({k: MALAS[k] for k in ("fec-01", "fec-02", "fec-03", "fec-04", "are-01")})
    g3 = guardar(almacen, evaluar(oraculo(planes), "qwen3:8b"))
    assert "Regresión" in g3["aviso"] and "fechas" in g3["aviso"]
    assert any(a["accion"] == "regresion_modelo" for a in almacen._q("SELECT * FROM auditoria"))

    h = historial(almacen, "qwen3:8b")
    assert [f["aciertos"] for f in h] == [23, 28, 30]
    assert h[0]["detalle"]["casos"][0]["id"] == "esc-01" and isinstance(json.dumps(h[0]["detalle"]), str)


def test_no_compara_entre_versiones_del_banco_ni_con_evaluaciones_incompletas(tmp_path):
    almacen = Almacen(tmp_path)
    viejo = evaluar(oraculo(BUENAS), "qwen3:8b")
    viejo["version_banco"] = "2020.01.01-1"
    guardar(almacen, viejo)
    nuevo = evaluar(oraculo(MALAS), "qwen3:8b")
    assert guardar(almacen, nuevo)["anterior_pct"] is None
    incompleto = evaluar(oraculo(BUENAS), "qwen3:8b")
    incompleto["incompleto"] = "saldo"
    guardar(almacen, incompleto)
    assert guardar(almacen, evaluar(oraculo(MALAS), "qwen3:8b"))["anterior_pct"] == 0.0


def test_comparar_varios_modelos_de_punta_a_punta():
    out = ev.comparar([(oraculo(BUENAS, latencia=8.0), "qwen3:8b"),
                       (oraculo(BUENAS, latencia=1.0, usd=0.001), "claude-haiku-5-5")])
    assert out["informe"]["recomendado"] == "qwen3:8b"     # mismo puntaje y gratis
    assert len(out["resultados"]) == 2
