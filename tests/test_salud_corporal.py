"""Pruebas del pulso del Apple Watch (lek/salud_corporal.py). Sin red, con reloj fijo."""
import datetime

import pytest

from lek.almacen import Almacen
from lek.salud_corporal import (ErrorPulso, HERRAMIENTA_MI_PULSO, HERRAMIENTAS_SIEMPRE_PRIVADAS, SaludCorporal,
                                leer_bpm, leer_fecha)

COL = datetime.timezone(datetime.timedelta(hours=-5))           # Colombia
AHORA = datetime.datetime(2026, 11, 24, 15, 0, tzinfo=datetime.timezone.utc)  # 10:00 en Colombia


class Reloj:
    def __init__(self, momento):
        self.momento = momento

    def __call__(self):
        return self.momento


@pytest.fixture
def salud(tmp_path):
    reloj = Reloj(AHORA)
    s = SaludCorporal(Almacen(tmp_path), zona=COL, reloj=reloj)
    s.reloj = reloj
    return s


def hace(minutos, base=AHORA):
    return (base - datetime.timedelta(minutes=minutos)).astimezone(COL).isoformat()


def cargar(salud, pares):
    """pares: [(minutos_atrás, bpm)]"""
    return salud.registrar_lote([{"fecha": hace(m), "bpm": b} for m, b in pares])


# ---------------------------------------------------------------- rangos
@pytest.mark.parametrize("valor,esperado", [(25, 25.0), (230, 230.0), ("72", 72.0), ("72,5", 72.5),
                                            ("88 lpm", 88.0), ("64 count/min", 64.0), (71.26, 71.3)])
def test_bpm_validos(valor, esperado):
    assert leer_bpm(valor) == esperado


@pytest.mark.parametrize("valor", [24.9, 231, 0, -70, "", "abc", None, True, float("nan")])
def test_bpm_fuera_de_rango_o_ilegible(valor):
    with pytest.raises(ErrorPulso):
        leer_bpm(valor)


def test_registrar_valida_y_guarda(salud):
    assert salud.registrar(70, hace(5)) is True
    with pytest.raises(ErrorPulso):
        salud.registrar(300, hace(4))
    with pytest.raises(ErrorPulso):
        salud.registrar(70, hace(-60))           # una hora en el futuro
    assert salud.registrar(71) is True           # sin fecha = ahora
    assert salud.resumen(60)["muestras"] == 2


# ---------------------------------------------------------------- lote y fechas de iOS
def test_fechas_iso_de_ios_con_zona():
    utc = datetime.datetime(2026, 11, 24, 15, 15, tzinfo=datetime.timezone.utc)
    for texto in ("2026-11-24T10:15:00-05:00", "2026-11-24T15:15:00Z", "2026-11-24T10:15:00-0500",
                  "2026-11-24 10:15:00 -0500", "2026-11-24T10:15:00.000-05:00", "2026-11-24T15:15:00+00:00",
                  "2026-11-24T16:15:00+01:00", "2026-11-24 15:15:00 UTC", 1795533300, "1795533300000"):
        assert leer_fecha(texto, COL) == utc, texto
    assert leer_fecha("2026-11-24T10:15:00", COL) == utc   # sin zona = hora local del PC
    with pytest.raises(ErrorPulso):
        leer_fecha("24 nov 2026 a las 10:15", COL)


def test_lote_deduplica_por_fecha_aunque_cambie_el_formato(salud):
    lote = [
        {"fecha": "2026-11-24T09:50:00-05:00", "bpm": 70},
        {"fecha": "2026-11-24T14:50:00Z", "bpm": 70},          # misma hora, otra zona: duplicada
        {"fecha": "2026-11-24T09:55:00-05:00", "bpm": "72"},
        {"fecha": "2026-11-24T09:56:00-05:00", "bpm": 400},     # fuera de rango
        {"fecha": "ayer", "bpm": 70},                           # ilegible
        {"bpm": 70},                                            # sin fecha
    ]
    r = salud.registrar_lote(lote)
    assert r["recibidas"] == 6 and r["guardadas"] == 2 and r["duplicadas"] == 1 and r["rechazadas"] == 3
    assert len(r["errores"]) == 3
    r2 = salud.registrar_lote(lote[:3])                         # el Atajo reenvía la misma hora
    assert r2["guardadas"] == 0 and r2["duplicadas"] == 3
    assert salud.resumen(60)["muestras"] == 2


def test_lote_en_formatos_alternativos(salud):
    assert salud.registrar_lote({"muestras": [{"fecha": hace(3), "bpm": 70}]})["guardadas"] == 1
    assert salud.registrar_lote('[{"fecha": "%s", "bpm": 71}]' % hace(4))["guardadas"] == 1
    texto = f"{hace(5)};72\n{hace(6)};73\n\n"
    assert salud.registrar_lote(texto)["guardadas"] == 2
    paralelas = {"fechas": f"{hace(7)}\n{hace(8)}", "bpms": "74\n75"}
    assert salud.registrar_lote(paralelas)["guardadas"] == 2
    assert salud.resumen(60)["muestras"] == 6
    with pytest.raises(ErrorPulso):
        salud.registrar_lote({"fechas": hace(9), "bpms": "1\n2"})


def test_auditoria_no_guarda_valores_de_salud(salud):
    cargar(salud, [(5, 87), (4, 93)])
    fila = salud.almacen._q("SELECT detalle FROM auditoria WHERE accion = 'pulso_lote'")[-1]
    assert "87" not in fila["detalle"] and "93" not in fila["detalle"] and '"guardadas": 2' in fila["detalle"]


# ---------------------------------------------------------------- resumen y tendencia
def test_resumen_vacio(salud):
    r = salud.resumen(60)
    assert r == {"actual": None, "promedio": None, "minimo": None, "maximo": None, "muestras": 0,
                 "tendencia": "sin datos suficientes", "fecha_ultima": None}
    assert "No tengo datos" in salud.mi_pulso()


def test_resumen_y_tendencias(salud):
    cargar(salud, [(50, 60), (40, 62), (30, 70), (20, 75), (10, 80), (5, 82)])
    r = salud.resumen(60)
    assert r["actual"] == 82 and r["minimo"] == 60 and r["maximo"] == 82 and r["muestras"] == 6
    assert r["promedio"] == round((60 + 62 + 70 + 75 + 80 + 82) / 6, 1)
    assert r["tendencia"] == "subiendo"
    assert r["fecha_ultima"] == "2026-11-24T09:55:00-05:00"
    assert salud.resumen(15)["muestras"] == 2                   # la ventana filtra

    salud.reloj.momento = AHORA + datetime.timedelta(hours=2)   # nueva hora: baja
    salud.registrar_lote([{"fecha": hace(m, salud.reloj.momento), "bpm": b}
                          for m, b in [(40, 90), (30, 88), (20, 70), (10, 66)]])
    assert salud.resumen(60)["tendencia"] == "bajando"

    salud.reloj.momento = AHORA + datetime.timedelta(hours=4)
    salud.registrar_lote([{"fecha": hace(m, salud.reloj.momento), "bpm": b}
                          for m, b in [(40, 70), (30, 72), (20, 71), (10, 70)]])
    assert salud.resumen(60)["tendencia"] == "estable"


def test_ultima_muestra_vieja_se_reporta_pero_no_en_la_ventana(salud):
    cargar(salud, [(300, 66)])
    r = salud.resumen(60)
    assert r["actual"] == 66 and r["muestras"] == 0
    assert "no hay muestras de los últimos 60 min" in salud.mi_pulso()


def test_reposo_estimado(salud):
    assert salud.reposo_estimado() is None
    cargar(salud, [(m * 60, b) for m, b in enumerate([55, 56, 58, 60, 65, 70, 80, 95, 110, 120, 57, 59])])
    reposo = salud.reposo_estimado()
    assert 55 <= reposo <= 57


def test_serie_y_respuesta_api(salud):
    cargar(salud, [(10, 70), (5, 72)])
    api = salud.respuesta_api(60)
    assert set(api) >= {"resumen", "serie"}
    assert api["serie"] == [{"fecha": "2026-11-24T09:50:00-05:00", "bpm": 70.0},
                            {"fecha": "2026-11-24T09:55:00-05:00", "bpm": 72.0}]


# ---------------------------------------------------------------- alertas
def test_pico_aislado_no_alerta(salud):
    cargar(salud, [(30, 72), (25, 150), (20, 74), (15, 140), (14, 145), (10, 75)])
    assert salud.alertas(60) == []
    assert "consúltalo" not in salud.mi_pulso()


def test_alto_sostenido_alerta_sobria(salud):
    cargar(salud, [(30, 72), (20, 125), (16, 131), (12, 128), (8, 126), (2, 80)])
    avisos = salud.alertas(60)
    assert len(avisos) == 1
    a = avisos[0]
    assert a["tipo"] == "alto" and a["minutos"] == 12 and a["muestras"] == 4 and a["bpm_extremo"] == 131
    assert "profesional de salud" in a["mensaje"] and "no es un dispositivo médico" in a["mensaje"]
    assert "ejercicio" in a["mensaje"]
    assert "profesional de salud" in salud.mi_pulso()


def test_racha_corta_o_con_hueco_no_alerta(salud):
    cargar(salud, [(20, 125), (16, 130), (12, 128)])            # solo 8 minutos
    assert salud.alertas(60) == []
    salud.reloj.momento = AHORA + datetime.timedelta(hours=3)
    base = salud.reloj.momento
    salud.registrar_lote([{"fecha": hace(m, base), "bpm": b} for m, b in [(50, 125), (48, 126), (20, 127)]])
    assert salud.alertas(60) == []                              # 28 min de hueco: no es "sostenido"


def test_bajo_sostenido_alerta(salud):
    cargar(salud, [(25, 38), (20, 37), (15, 39), (10, 36)])
    avisos = salud.alertas(60)
    assert [a["tipo"] for a in avisos] == ["bajo"] and avisos[0]["bpm_extremo"] == 36


# ---------------------------------------------------------------- retención
def test_retencion_90_dias_pasa_a_resumen_diario(salud):
    viejo = AHORA - datetime.timedelta(days=100)
    salud.registrar_lote([{"fecha": (viejo + datetime.timedelta(minutes=10 * i)).isoformat(), "bpm": 60 + i}
                          for i in range(12)])
    # registrar_lote corre la retención una vez al día: ese primer lote viejo ya quedó resumido
    assert salud.almacen._q("SELECT count(*) AS n FROM pulso")[0]["n"] == 0
    cargar(salud, [(5, 70)])
    assert salud.retener() == {"muestras_resumidas": 0, "dias": 0}
    assert salud.almacen._q("SELECT count(*) AS n FROM pulso")[0]["n"] == 1
    dia = salud.diario()
    assert len(dia) == 1 and dia[0]["dia"] == viejo.astimezone(COL).date().isoformat()
    assert dia[0]["muestras"] == 12 and dia[0]["minimo"] == 60 and dia[0]["maximo"] == 71
    assert dia[0]["promedio"] == 65.5 and dia[0]["reposo"] is not None


def test_retencion_combina_muestras_viejas_que_llegan_tarde(salud):
    viejo = AHORA - datetime.timedelta(days=95)
    salud.registrar_lote([{"fecha": viejo.isoformat(), "bpm": 60}, {"fecha": (viejo + datetime.timedelta(minutes=5)).isoformat(), "bpm": 80}])
    salud.retener()
    salud.registrar(100, (viejo + datetime.timedelta(minutes=9)).isoformat())
    salud.retener()
    d = salud.diario()[0]
    assert d["muestras"] == 3 and d["promedio"] == 80 and d["minimo"] == 60 and d["maximo"] == 100
    assert salud.almacen._q("SELECT count(*) AS n FROM pulso")[0]["n"] == 0


# ---------------------------------------------------------------- herramienta privada
def test_mi_pulso_una_frase_y_privada(salud):
    cargar(salud, [(m, 70) for m in range(5, 60, 5)])
    texto = salud.mi_pulso()
    assert texto.startswith("Tu último pulso fue 70 lpm (hace 5 min)") and texto.count(".") == 1
    assert salud.mi_pulso("no-numero")                           # argumento raro: no revienta
    assert "mi_pulso" in HERRAMIENTAS_SIEMPRE_PRIVADAS
    assert HERRAMIENTA_MI_PULSO["function"]["name"] == "mi_pulso"
    assert "PRIVADA" in HERRAMIENTA_MI_PULSO["function"]["description"]
