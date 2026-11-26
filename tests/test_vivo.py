"""Fase 6: respuestas en vivo (transmisión) e interrupción."""
import json

import pytest

from conftest import CerebroFalso, ErrorProveedor, Peticion, llamada
from lek import vivo
from lek.cerebros.claude import leer_flujo
from lek.cerebros.ollama import leer_lineas


def sse(*eventos):
    return [f"data: {json.dumps(e)}".encode() for e in eventos]


def test_flujo_de_claude_texto_y_herramienta():
    recibido = []
    lineas = sse({"type": "message_start", "message": {"usage": {"input_tokens": 12}}},
                 {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
                 {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hola, "}},
                 {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Sergio"}},
                 {"type": "content_block_start", "index": 1,
                  "content_block": {"type": "tool_use", "id": "tu1", "name": "buscar_internet", "input": {}}},
                 {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"consulta": "cl'}},
                 {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": 'ima Palmira"}'}},
                 {"type": "message_delta", "usage": {"output_tokens": 7}})
    texto, llamadas, uso = leer_flujo([b"event: x", b""] + lineas, recibido.append)
    assert texto == "Hola, Sergio" and recibido == ["Hola, ", "Sergio"]
    assert llamadas == [{"id": "tu1", "function": {"name": "buscar_internet", "arguments": {"consulta": "clima Palmira"}}}]
    assert uso == {"input_tokens": 12, "output_tokens": 7}


def test_flujo_de_claude_con_error():
    with pytest.raises(ErrorProveedor) as e:
        leer_flujo(sse({"type": "error", "error": {"type": "overloaded_error", "message": "ocupado"}}), lambda f: None)
    assert e.value.reintentable


def test_flujo_de_ollama():
    recibido = []
    lineas = [json.dumps({"message": {"content": "Lis"}}), "", json.dumps({"message": {"content": "to"}}),
              json.dumps({"message": {"content": "", "tool_calls": [{"function": {"name": "hora", "arguments": {}}}]},
                          "done": True, "eval_count": 3})]
    texto, llamadas, final = leer_lineas(lineas, recibido.append)
    assert texto == "Listo" and recibido == ["Lis", "to"] and llamadas[0]["function"]["name"] == "hora"
    assert final["eval_count"] == 3


def test_cancelar_turno():
    t = vivo.nuevo()
    vivo.atar(t)
    t.al_texto("hola")
    assert t.escrito == "hola" and t.id in vivo.activos()
    assert vivo.cancelar(t.id) == 1
    with pytest.raises(vivo.Cancelado):
        vivo.revisar()
    with pytest.raises(vivo.Cancelado):
        t.al_texto("más")
    vivo.terminar(t)
    assert vivo.actual() is None and t.id not in vivo.activos()
    vivo.revisar()                                   # sin turno en vivo no pasa nada


class Transmisor(CerebroFalso):
    transmite = True

    def __init__(self, *a, trozos=None, **kw):
        super().__init__(*a, **kw)
        self.trozos = list(trozos or [])

    def chat(self, modelo, mensajes, herramientas, clave="", al_texto=None):
        r = super().chat(modelo, mensajes, herramientas, clave)
        if al_texto and r.texto:
            for i in range(0, len(r.texto), 4):
                al_texto(r.texto[i:i + 4])
        return r


def eventos_de(luna, texto):
    respuesta = luna.chat_en_vivo(luna.Mensaje(texto=texto), Peticion())
    return [json.loads(linea) for linea in respuesta.body_iterator]


def test_chat_en_vivo_transmite_y_termina(luna):
    local = Transmisor("ollama", "local", respuestas=["Buenas tardes, Sergio."])
    luna.PROVEEDORES["ollama"] = local
    ev = eventos_de(luna, "hola")
    tipos = [e["t"] for e in ev]
    assert tipos[0] == "inicio" and tipos[-1] == "fin"
    assert "".join(e["d"] for e in ev if e["t"] == "texto") == "Buenas tardes, Sergio."
    assert ev[-1]["respuesta"] == "Buenas tardes, Sergio." and ev[-1]["detenido"] is False
    assert luna.ALMACEN.ultimos_mensajes(1)[0]["contenido"] == "Buenas tardes, Sergio."   # quedó guardado


def test_chat_en_vivo_muestra_herramientas_y_reinicia(luna):
    primera = llamada("hora", {})
    primera.texto = "Déjame ver"
    local = Transmisor("ollama", "local", respuestas=[primera, "Son las tres."])
    luna.PROVEEDORES["ollama"] = local
    ev = eventos_de(luna, "¿qué hora es?")
    tipos = [e["t"] for e in ev]
    assert "reinicio" in tipos and {"t": "paso", "d": "Usando hora"} in ev
    assert tipos.index("reinicio") < tipos.index("paso")
    assert ev[-1]["respuesta"] == "Son las tres."


def test_respaldo_borra_lo_escrito_a_medias(luna):
    """Si el cerebro falla después de escribir algo, el cliente recibe 'reinicio' antes del texto del respaldo."""
    class Cortado(Transmisor):
        def chat(self, modelo, mensajes, herramientas, clave="", al_texto=None):
            if al_texto:
                al_texto("Medio tex")
            raise ErrorProveedor("red", "se cortó", reintentable=False)

    luna.PROVEEDORES["ollama"] = Cortado("ollama", "local")
    eventos = []
    with pytest.raises(ErrorProveedor):
        luna.CEREBRO.chat([{"role": "user", "content": "hola"}], None, al_texto=eventos.append)
    assert eventos[0] == "Medio tex" and None in eventos


def test_detener_a_mitad_de_turno(luna):
    """El usuario pulsa Detener mientras Luna usa una herramienta: no hace la siguiente y lo dice."""
    def herramienta_lenta(**_):
        vivo.cancelar()                               # simula el botón Detener mientras trabaja
        return "hecho"

    luna.FUNCIONES["hora"] = herramienta_lenta
    local = Transmisor("ollama", "local", respuestas=[llamada("hora", {}), "No debería llegar aquí."])
    luna.PROVEEDORES["ollama"] = local
    ev = eventos_de(luna, "¿qué hora es?")
    assert ev[-1]["t"] == "fin" and ev[-1]["detenido"] is True
    assert "Me detuve" in ev[-1]["respuesta"] and len(local.recibido) == 1


def test_endpoint_cancelar(luna):
    t = vivo.nuevo()
    assert luna.cancelar_turno(luna.Detener(turno=t.id), Peticion()) == {"detenidos": 1}
    assert t.parar.is_set()
    vivo.terminar(t)
