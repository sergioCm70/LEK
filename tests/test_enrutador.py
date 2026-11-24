"""Pruebas del enrutador automático de modelos (lek/cerebros/enrutador.py). Sin red ni modelos reales."""
from conftest import CerebroFalso
from lek.almacen import Almacen
from lek.cerebros.catalogo import catalogo
from lek.cerebros.enrutador import BANCO, clasificar, elegir, precision
from lek.cerebros.gestor import Cerebro
from lek.config import Config

HAIKU, SONNET, OPUS, LOCAL = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "qwen3:8b"


def armar(tmp_path, nube_ok=True, modo="auto", instalados=None):
    cfg, alm = Config(tmp_path), Almacen(tmp_path)
    proveedores = {"ollama": CerebroFalso("ollama", "local"),
                   "claude": CerebroFalso("claude", "nube", configurado=nube_ok)}
    c = Cerebro(cfg, alm, proveedores, catalogo(LOCAL, instalados), LOCAL)
    c.esperar = lambda s: None
    cfg.cambiar("cerebro", "modo", modo)
    return c, cfg, alm


def medir(alm, modelo, latencia, veces=4, proveedor="claude"):
    for _ in range(veces):
        alm.registrar_llamada(modelo, proveedor, latencia)


def modelos_de(e):
    return [m for m, _ in e.cadena]


def es_nube(c, modelo):
    return c.modelos.get(modelo, {}).get("ubicacion") == "nube"


# ---------------------------------------------------------------- banco etiquetado
def test_banco_tiene_40_pedidos_de_las_cuatro_clases():
    assert len(BANCO) == 40
    for clase in ("simple", "normal", "compleja", "privada"):
        assert sum(1 for _, c in BANCO if c == clase) == 10


def test_banco_aciertos_y_cero_privados_en_la_nube(tmp_path):
    c, cfg, alm = armar(tmp_path)
    medir(alm, HAIKU, 3.6)
    r = precision()
    assert r["porcentaje"] >= 85, r["fallos"]
    privados_en_nube = []
    for texto, esperada in BANCO:
        e = elegir(texto, c)
        assert e.cadena[-1] == (LOCAL, e.cadena[-1][1])          # siempre termina en el respaldo local
        if esperada == "privada" and any(es_nube(c, m) for m in modelos_de(e)):
            privados_en_nube.append(texto)
    assert privados_en_nube == []


# ---------------------------------------------------------------- clasificador
def test_clasificador_da_senales_auditables():
    assert clasificar("¿Qué hora es?") == ("simple", ["hora"])
    clase, senales = clasificar("Compara guadua y concreto paso a paso")
    assert clase == "compleja" and "comparación" in senales and "paso a paso" in senales
    assert clasificar("¿Cómo está mi pulso?")[0] == "privada"


def test_clima_de_arquitectura_no_es_pregunta_del_tiempo():
    assert clasificar("¿Va a llover mañana?")[0] == "simple"
    assert clasificar("Sugiéreme materiales para clima cálido húmedo")[0] == "normal"


def test_preguntas_encadenadas_y_texto_largo_suben_a_compleja():
    assert clasificar("¿Qué es un alero? ¿Cuánto debe volar? ¿Y en Palmira?")[0] == "compleja"
    assert clasificar(" ".join(["palabra"] * 80))[0] == "compleja"


def test_privacidad_configurable_para_documentos_pero_no_para_contrasenas():
    assert clasificar("Busca en mis documentos el acta")[0] == "privada"
    assert clasificar("Busca en mis documentos el acta", {"documentos": "nube"})[0] != "privada"
    todo_nube = {"documentos": "nube", "memoria": "nube", "notas": "nube"}
    assert clasificar("Guarda mi contraseña del banco", todo_nube)[0] == "privada"
    assert clasificar("¿Cómo está mi pulso?", todo_nube)[0] == "privada"


# ---------------------------------------------------------------- elección por clase
def test_simple_usa_el_mas_rapido_medido(tmp_path):
    c, cfg, alm = armar(tmp_path, instalados=["qwen3:4b"])
    medir(alm, HAIKU, 3.6)
    medir(alm, "qwen3:4b", 1.2, proveedor="ollama")
    e = elegir("¿Qué hora es?", c)
    assert e.clase == "simple" and modelos_de(e) == ["qwen3:4b", HAIKU, LOCAL]
    assert "el más rápido medido" in e.motivo_global and "1,2 s" in e.motivo_global


def test_simple_ignora_un_rapido_que_falla_mucho(tmp_path):
    c, cfg, alm = armar(tmp_path, instalados=["qwen3:4b"])
    medir(alm, HAIKU, 3.6)
    medir(alm, "qwen3:4b", 1.0, proveedor="ollama")
    for _ in range(4):
        alm.registrar_llamada("qwen3:4b", "ollama", 0, ok=False, error="se cayó")
    assert modelos_de(elegir("¿Qué día es hoy?", c))[0] == HAIKU


def test_simple_sin_mediciones_usa_el_principal(tmp_path):
    c, *_ = armar(tmp_path)
    e = elegir("Hola Luna", c)
    assert modelos_de(e) == [HAIKU, LOCAL] and "sin mediciones" in e.motivo_global


def test_normal_usa_el_principal(tmp_path):
    c, *_ = armar(tmp_path)
    e = elegir("¿Qué es un muro cortina?", c)
    assert e.clase == "normal" and modelos_de(e) == [HAIKU, LOCAL]


def test_compleja_sube_al_de_mas_razonamiento(tmp_path):
    c, *_ = armar(tmp_path)
    e = elegir("Analiza las ventajas y desventajas de la guadua frente al concreto", c)
    assert e.clase == "compleja" and modelos_de(e) == [OPUS, HAIKU, LOCAL]
    assert "más razonamiento" in e.motivo_global


def test_privada_solo_locales(tmp_path):
    c, *_ = armar(tmp_path, instalados=["qwen3:4b"])
    e = elegir("Lee mis notas de estructuras y analízalas en detalle", c)
    assert e.clase == "privada" and not any(es_nube(c, m) for m in modelos_de(e))


def test_turno_marcado_privado_nunca_sale(tmp_path):
    c, *_ = armar(tmp_path)
    e = elegir("Analiza esto a fondo", c, privado=True)
    assert e.clase == "privada" and modelos_de(e) == [LOCAL]


def test_respaldo_en_la_nube_no_rompe_la_privacidad(tmp_path):
    c, cfg, _ = armar(tmp_path)
    cfg.cambiar("cerebro", "respaldo", SONNET)
    e = elegir("¿Qué recuerdas de mí?", c)
    assert modelos_de(e) == [LOCAL]


def test_conversacion_solo_local(tmp_path):
    c, cfg, _ = armar(tmp_path)
    cfg.cambiar("privacidad", "conversacion", "local")
    e = elegir("Compara dos referentes de vivienda social", c)
    assert modelos_de(e) == [LOCAL] and "solo local" in e.motivo_global


# ---------------------------------------------------------------- presupuesto
def test_presupuesto_sobre_80_por_ciento_no_sube_de_nivel(tmp_path):
    c, cfg, alm = armar(tmp_path)
    alm.registrar_llamada(HAIKU, "claude", 1, usd=4.2)           # 84 % de 5 USD
    e = elegir("Investiga la NSR-10 sobre mampostería confinada", c)
    assert e.clase == "compleja" and modelos_de(e) == [HAIKU, LOCAL]
    assert "no subo de nivel" in e.motivo_global and "84 %" in e.motivo_global


def test_presupuesto_bajo_80_por_ciento_si_sube(tmp_path):
    c, cfg, alm = armar(tmp_path)
    alm.registrar_llamada(HAIKU, "claude", 1, usd=3.0)           # 60 %
    assert modelos_de(elegir("Investiga la NSR-10", c))[0] == OPUS


def test_compleja_no_elige_un_modelo_que_no_cabe_en_lo_que_queda(tmp_path):
    c, cfg, alm = armar(tmp_path)
    cfg.cambiar("cerebro", "presupuesto_mensual_usd", 0.04)   # queda 0,04: Opus (~0,046) no cabe, Sonnet (~0,023) sí
    e = elegir("Analiza la orientación de mi proyecto", c)
    assert modelos_de(e) == [SONNET, HAIKU, LOCAL]


def test_presupuesto_agotado_todo_local_con_aviso(tmp_path):
    c, cfg, alm = armar(tmp_path)
    cfg.cambiar("cerebro", "presupuesto_mensual_usd", 1.0)
    alm.registrar_llamada(HAIKU, "claude", 1, usd=1.5)
    for texto in ("Hola", "¿Qué es un pilote?", "Compara dos losas"):
        e = elegir(texto, c)
        assert modelos_de(e) == [LOCAL] and "presupuesto" in e.aviso


# ---------------------------------------------------------------- salud y claves
def test_modelo_pausado_no_se_elige(tmp_path):
    c, *_ = armar(tmp_path)
    for _ in range(3):
        c.salud.fallo(OPUS, "500")
    e = elegir("Compara la ventilación cruzada y el efecto chimenea", c)
    assert OPUS not in modelos_de(e) and modelos_de(e)[0] == SONNET
    c.salud.fallo(HAIKU, "auth", definitivo=True)
    e = elegir("¿Qué es un muro cortina?", c)
    assert modelos_de(e) == [LOCAL] and "pausa" in e.motivo_global


def test_sin_clave_de_nube_todo_local(tmp_path):
    c, *_ = armar(tmp_path, nube_ok=False)
    for texto, _ in BANCO:
        e = elegir(texto, c)
        assert modelos_de(e) == [LOCAL]
    assert "sin clave" in elegir("¿Qué es un muro cortina?", c).motivo_global


# ---------------------------------------------------------------- modo fijo vs auto
def test_modo_fijo_devuelve_la_cadena_de_siempre(tmp_path):
    c, cfg, alm = armar(tmp_path, modo="fijo")
    for texto in ("¿Qué hora es?", "Analiza la guadua frente al concreto", "¿Qué es un pilote?"):
        e = elegir(texto, c)
        assert e.modo == "fijo" and e.cadena == c.cadena()
    assert elegir("Lee mis notas", c, privado=True).cadena == c.cadena(True)


def test_modo_fijo_vs_auto_en_el_mismo_pedido(tmp_path):
    c, cfg, _ = armar(tmp_path, modo="fijo")
    texto = "Hazme un cronograma para la entrega final de Taller 4"
    fijo = elegir(texto, c)
    cfg.cambiar("cerebro", "modo", "auto")
    auto = elegir(texto, c)
    assert fijo.clase == auto.clase == "compleja"                 # el panel ve la clase en ambos modos
    assert modelos_de(fijo) == [HAIKU, LOCAL] and modelos_de(auto) == [OPUS, HAIKU, LOCAL]


def test_como_dict_para_el_panel_no_incluye_el_texto(tmp_path):
    c, *_ = armar(tmp_path)
    d = elegir("Guarda mi contraseña: gato123", c).como_dict()
    assert d["clase"] == "privada" and "gato123" not in str(d)
    assert set(d) == {"clase", "modo", "motivo", "senales", "cadena", "aviso"}
