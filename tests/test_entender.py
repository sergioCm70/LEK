"""Entender mejor la voz: vocabulario, correcciones aprendidas, nota al cerebro y subtítulos."""
import json

from conftest import Peticion, llamada
from lek.voz.entender import Vocabulario


def test_correccion_aprendida_se_aplica_solo_como_palabra(tmp_path):
    v = Vocabulario(tmp_path)
    assert "Revit" in v.aprender_correccion("levit", "Revit")
    assert v.aplicar("abre levit por favor") == "abre Revit por favor"
    assert v.aplicar("Levit, el modelo") == "Revit, el modelo"
    assert v.aplicar("levitación") == "levitación"          # no toca palabras más largas
    assert "corta" in v.aprender_correccion("la", "La Luna")  # nada de corregir palabras muy cortas


def test_correccion_de_frase_y_tildes(tmp_path):
    v = Vocabulario(tmp_path)
    v.aprender_correccion("julián vía", "Julian Villa")
    assert v.aplicar("le escribo a Julian via mañana") == "le escribo a Julian Villa mañana"


def test_parecidas_y_pista_whisper(tmp_path):
    v = Vocabulario(tmp_path)
    v.aprender_palabra("Farnsworth")
    assert "Farnsworth" in v.parecidas("háblame de la casa farnsword")
    assert "Lumion" in v.parecidas("exporta a lumión")
    pista = v.pista_whisper()
    assert pista.startswith("Conversación con Luna") and "Farnsworth" in pista and len(pista) <= 600


def test_nota_incluye_alternativas_sin_repetir(tmp_path):
    v = Vocabulario(tmp_path)
    n = v.nota("abre levit", ["abre levit", "abre Revit", "habré levit"])
    assert "HABLÓ" in n and "«abre Revit»" in n and n.count("«abre levit»") == 0
    assert "Revit" in n


def test_mensaje_por_voz_llega_corregido_e_interpretado(luna):
    luna.VOCABULARIO.aprender_correccion("levit", "Revit")
    local = luna.PROVEEDORES["ollama"]
    local.respuestas = ["Listo."]
    r = luna.chat(luna.Mensaje(texto="abre levit", voz=True, alternativas=["abre revit"]), Peticion())
    assert r["respuesta"] == "Listo."
    enviado = local.recibido[0]["mensajes"][-1]["content"]
    assert "abre Revit" in enviado and "HABLÓ" in enviado
    assert luna.ALMACEN.ultimos_mensajes(2)[0]["contenido"] == "abre Revit"   # se guarda corregido


def test_mensaje_escrito_no_lleva_nota_de_voz(luna):
    local = luna.PROVEEDORES["ollama"]
    local.respuestas = ["Hola."]
    luna.chat(luna.Mensaje(texto="hola"), Peticion())
    assert "HABLÓ" not in local.recibido[0]["mensajes"][-1]["content"]


def test_luna_aprende_la_correccion_cuando_la_corriges(luna):
    local = luna.PROVEEDORES["ollama"]
    local.respuestas = [llamada("corregir_oido", {"oido": "lumen", "correcto": "Lumion"}), "Anotado."]
    luna.responder("no dije lumen, dije Lumion", voz=True)
    assert luna.VOCABULARIO.correcciones() == {"lumen": "Lumion"}


def test_mensajes_nuevos_para_la_pantalla(luna):
    base = luna.mensajes_nuevos(Peticion())["ultimo"]
    luna.PROVEEDORES["ollama"].respuestas = ["Son las tres."]
    luna.responder("qué hora es", "voz", voz=True)
    r = luna.mensajes_nuevos(Peticion(), desde=base)
    assert [m["rol"] for m in r["mensajes"]] == ["usuario", "luna"]
    assert r["mensajes"][0]["cliente"] == "voz" and r["ultimo"] > base


def test_voz_en_vivo_sin_escucha(luna):
    assert luna.voz_en_vivo(Peticion()) == {"activo": False}


class ReconocedorDictado:
    """Reconocedor falso con dictado en vivo: cada bloque suma una palabra."""
    def __init__(self, palabras):
        self.palabras, self.i, self.dictado = palabras, 0, []

    def palabra(self, pcm):
        return pcm == b"L" * 3200

    def reiniciar(self):
        pass

    def empezar_dictado(self):
        self.dictado = []

    def dictar(self, pcm):
        if self.i < len(self.palabras):
            self.dictado.append(self.palabras[self.i]); self.i += 1
        return " ".join(self.dictado)

    def fin_dictado(self):
        return " ".join(self.dictado)

    def transcribir(self, pcm):
        raise AssertionError("con dictado no hace falta transcribir de nuevo")


def test_dictado_en_vivo_y_transcripcion_final():
    from lek.voz.despertador import Despertador, FuenteMemoria
    import struct
    voz = struct.pack("<1600h", *([8000, -8000] * 800))
    silencio = b"\0" * 3200
    vistos, pedidos = [], []
    rec = ReconocedorDictado(["luna", "qué", "hora", "es", "en", "Palmira", "hoy", "por", "favor"])
    fuente = FuenteMemoria([silencio] * 3 + [b"L" * 3200] + [voz] * 4 + [silencio] * 20)
    d = Despertador("luna", lambda t: pedidos.append(t) or "", fuente, rec, tono=False, hilo_respuesta=False,
                    registro=lambda m: None, silencio_fin_s=0.5)
    original = d._grabar
    d._grabar = lambda pcm: (original(pcm), vistos.append(d.parcial))
    d.encender(); d._hilo.join(5)
    final = "qué hora es en Palmira hoy por favor"
    assert pedidos == [final]
    largos = [len(p) for p in vistos if p]
    assert len(set(largos)) >= 3 and largos == sorted(largos)   # se fue escribiendo mientras hablaba
    assert d.estado()["parcial"] == final


def test_ruido_de_fondo_no_se_responde_en_voz_alta(luna):
    local = luna.PROVEEDORES["ollama"]
    local.respuestas = ["[IGNORAR]", "Son las tres."]
    assert luna.atender_voz_de_fondo("mil would en chicago bulls") == ""
    assert "segundo plano" in local.recibido[0]["mensajes"][-1]["content"]
    assert luna.atender_voz_de_fondo("qué hora es") == "Son las tres."
