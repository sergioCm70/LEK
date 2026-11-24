import pytest

from conftest import CerebroFalso
from lek.almacen import Almacen
from lek.cerebros.base import ErrorProveedor
from lek.cerebros.catalogo import catalogo
from lek.cerebros.gestor import Cerebro, OMITIDO, para_la_nube
from lek.config import Config


def armar(tmp_path, nube_ok=True, respuestas_nube=None, respuestas_local=None):
    cfg, alm = Config(tmp_path), Almacen(tmp_path)
    local = CerebroFalso("ollama", "local", respuestas_local)
    nube = CerebroFalso("claude", "nube", respuestas_nube, configurado=nube_ok)
    c = Cerebro(cfg, alm, {"ollama": local, "claude": nube}, catalogo("qwen3:8b"), "qwen3:8b")
    c.esperar = lambda s: None
    return c, local, nube, cfg, alm


MSG = [{"role": "system", "content": "sistema"}, {"role": "user", "content": "hola"}]


def test_sin_clave_usa_el_local(tmp_path):
    c, local, nube, *_ = armar(tmp_path, nube_ok=False)
    assert c.cadena() == [("qwen3:8b", "sin clave de la nube: cerebro local")]
    assert c.chat(MSG).modelo == "qwen3:8b" and not nube.recibido


def test_con_clave_usa_la_nube_y_registra(tmp_path):
    c, local, nube, cfg, alm = armar(tmp_path)
    r = c.chat(MSG)
    assert r.modelo == "claude-haiku-5-5" and not local.recibido
    assert alm.estadisticas_modelos()["claude-haiku-5-5"]["llamadas"] == 1
    assert alm.cambios_modelo()[0]["a"] == "claude-haiku-5-5"


def test_si_la_nube_falla_responde_el_respaldo(tmp_path):
    c, local, nube, cfg, alm = armar(tmp_path, respuestas_nube=[ErrorProveedor("auth", "clave inválida")])
    r = c.chat(MSG)
    assert r.modelo == "qwen3:8b"
    assert c.ultimo["degradado"] and "clave inválida" in c.ultimo["aviso"]
    assert c.salud.estado("claude-haiku-5-5") == "pausado"     # error definitivo: no insiste
    assert c.cadena()[0][0] == "qwen3:8b"


def test_reintenta_errores_pasajeros(tmp_path):
    c, local, nube, *_ = armar(tmp_path, respuestas_nube=[ErrorProveedor("red", "corte", reintentable=True)])
    assert c.chat(MSG).modelo == "claude-haiku-5-5"
    assert len(nube.recibido) == 2 and not local.recibido


def test_cortocircuito_tras_tres_fallos(tmp_path):
    fallos = [ErrorProveedor("servidor", "500", reintentable=False) for _ in range(3)]
    c, local, nube, *_ = armar(tmp_path, respuestas_nube=fallos)
    for _ in range(3):
        c.chat(MSG)
    assert c.salud.estado("claude-haiku-5-5") == "pausado"
    llamadas_nube = len(nube.recibido)
    c.chat(MSG)
    assert len(nube.recibido) == llamadas_nube   # no se intenta mientras está en pausa
    c.salud.reloj = lambda: 10 ** 9              # pasa el tiempo
    assert c.chat(MSG).modelo == "claude-haiku-5-5"


def test_lo_privado_nunca_va_a_la_nube(tmp_path):
    c, local, nube, *_ = armar(tmp_path)
    assert c.chat(MSG, privado=True).modelo == "qwen3:8b"
    assert not nube.recibido
    limpio = para_la_nube([{"role": "tool", "content": "Vive en Palmira", "privado": True}])
    assert limpio[0]["content"] == OMITIDO and "privado" not in limpio[0]


def test_presupuesto_del_mes(tmp_path):
    c, local, nube, cfg, alm = armar(tmp_path)
    cfg.cambiar("cerebro", "presupuesto_mensual_usd", 0.01)
    alm.registrar_llamada("claude-haiku-5-5", "claude", 1, usd=0.02)
    assert c.chat(MSG).modelo == "qwen3:8b"
    assert "presupuesto" in c.ultimo["aviso"]


def test_si_todos_fallan_lo_dice(tmp_path):
    c, *_ = armar(tmp_path, nube_ok=False,
                  respuestas_local=[ErrorProveedor("red", "sin Ollama", reintentable=True) for _ in range(2)])
    with pytest.raises(ErrorProveedor) as e:
        c.chat(MSG)
    assert e.value.tipo == "todos"


def test_config_valida(tmp_path):
    cfg = Config(tmp_path)
    with pytest.raises(ValueError):
        cfg.cambiar("privacidad", "memoria", "internet")
    with pytest.raises(KeyError):
        cfg.cambiar("cerebro", "inventado", 1)
    cfg.cambiar("privacidad", "memoria", "nube")
    assert Config(tmp_path).get("privacidad", "memoria") == "nube"
    cfg.guardar_secreto("claude_clave", "sk-ant-x")
    assert "sk-ant" not in (tmp_path / "config.json").read_text()
