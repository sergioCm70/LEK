"""Pruebas de la palabra de activación ("Luna") con audio y reconocedor falsos: sin micrófono ni Vosk."""
import array
import io
import json
import sys
import threading
import time
import types
import wave

import pytest

from lek.voz import despertador as dsp
from lek.voz.despertador import Despertador, FuenteMemoria, ReconocedorVosk

CUADROS = 1600  # 100 ms a 16 kHz


# ---------------------------------------------------------------- audio falso
def _bloque(muestras):
    a = array.array("h", muestras)
    if sys.byteorder == "big":
        a.byteswap()
    return a.tobytes()


def voz(palabra: str, volumen: int = 6000) -> bytes:
    """Un bloque 'con voz' que lleva escrita la palabra en sus primeras muestras (la lee el reconocedor falso)."""
    cabeza = [ord(c) * 100 for c in palabra] + [0]
    relleno = [volumen if i % 2 else -volumen for i in range(CUADROS - len(cabeza))]
    return _bloque(cabeza + relleno)


def silencio(n: int = 1, nivel: int = 20) -> list:
    return [_bloque([nivel if i % 2 else -nivel for i in range(CUADROS)]) for _ in range(n)]


def leer_palabra(pcm: bytes) -> str:
    a = array.array("h")
    a.frombytes(pcm[:200])
    if sys.byteorder == "big":
        a.byteswap()
    letras = []
    for m in a:
        if m <= 0 or m % 100:
            break
        letras.append(chr(m // 100))
    return "".join(letras)


class ReconocedorFalso:
    def __init__(self, nombre="luna"):
        self.nombre = nombre
        self.reinicios = 0
        self.transcritos = []

    def palabra(self, pcm):
        return leer_palabra(pcm) == self.nombre

    def reiniciar(self):
        self.reinicios += 1

    def transcribir(self, pcm):
        palabras = [leer_palabra(pcm[i:i + CUADROS * 2]) for i in range(0, len(pcm), CUADROS * 2)]
        texto = " ".join(p for p in palabras if p)
        self.transcritos.append(texto)
        return texto


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def armar(bloques, al_leer=None, **opciones):
    """Despertador síncrono con fuente, reconocedor, reloj y altavoz falsos."""
    reloj = Reloj()
    sonidos, pedidos = [], []

    def avanzar(i):
        reloj.t += 0.1
        if al_leer:
            al_leer(i)

    fuente = FuenteMemoria(bloques, al_leer=avanzar)
    ajustes = dict(sintetizar=lambda t: b"WAV:" + t.encode(), reproducir=sonidos.append,
                   hilo_respuesta=False, reloj=reloj, registro=lambda m: None)
    ajustes.update(opciones)
    d = Despertador("luna", lambda t: pedidos.append(t) or f"respuesta a {t}", fuente, ReconocedorFalso(), **ajustes)
    return d, fuente, pedidos, sonidos


def pedido(*palabras):
    return [voz(p) for p in palabras] + silencio(12)


# ---------------------------------------------------------------- detección
def test_detecta_la_palabra_y_atiende_el_pedido():
    bloques = silencio(5) + [voz("luna")] + silencio(4) + pedido("que", "hora", "es")
    d, _, pedidos, sonidos = armar(bloques)
    d.correr()
    assert pedidos == ["que hora es"]                       # el nombre se quita del comienzo
    assert sonidos[0] == dsp.tono_wav()                     # primero el bip
    assert sonidos[-1] == b"WAV:respuesta a que hora es"    # luego la respuesta hablada
    assert d.activaciones == 1 and d.estado()["estado"] == "apagado"


def test_pedido_dicho_de_corrido_usa_el_audio_previo():
    bloques = silencio(3) + [voz("luna")] + pedido("pon", "musica")
    d, _, pedidos, _ = armar(bloques, tono=False)
    d.correr()
    assert pedidos == ["pon musica"]


def test_ignora_otras_palabras():
    bloques = silencio(3) + [voz(p) for p in ("lunes", "una", "hola", "lunar", "alunizaje")] + silencio(20)
    d, _, pedidos, sonidos = armar(bloques)
    d.correr()
    assert pedidos == [] and sonidos == [] and d.activaciones == 0


def test_falsa_alarma_sin_pedido_no_llama_a_luna():
    bloques = silencio(3) + [voz("luna")] + silencio(60)
    d, _, pedidos, sonidos = armar(bloques)
    d.correr()
    assert d.activaciones == 1
    assert pedidos == [] and sonidos == [dsp.tono_wav()]   # solo el bip, sin respuesta


def test_pedido_largo_se_corta_en_12_segundos():
    bloques = silencio(3) + [voz("luna")] + [voz("bla")] * 200 + silencio(15)
    d, _, pedidos, _ = armar(bloques, tono=False)
    d.correr()
    assert len(pedidos) == 1
    assert pedidos[0].split().count("bla") <= 121


# ---------------------------------------------------------------- no se oye a sí misma
def test_no_se_activa_mientras_luna_habla():
    def al_leer(i):
        if i == 2:
            d.pausar()
        if i == 15:
            d.reanudar()

    bloques = silencio(3) + [voz("luna")] * 5 + silencio(7) + silencio(10) + [voz("luna")] + pedido("hola")
    d, _, pedidos, _ = armar(bloques, al_leer=al_leer, tono=False)
    d.correr()
    assert d.activaciones == 1          # solo la de después de reanudar
    assert pedidos == ["hola"]
    assert d.estado()["en_pausa"] is False


def test_no_se_activa_con_su_propia_respuesta():
    """Mientras reproduce la respuesta (en otro hilo) llegan más 'luna' por el micrófono: se descartan."""
    extra = [voz("luna")] * 10
    bloques = silencio(3) + [voz("luna")] + pedido("chiste") + extra
    total = len(bloques)
    reloj = Reloj()
    fuente = FuenteMemoria(bloques, al_leer=lambda i: setattr(reloj, "t", reloj.t + 0.1))
    en_pausa = []
    fin = threading.Event()

    def reproducir(wav):
        if wav.startswith(b"WAV:"):
            en_pausa.append(d.en_pausa)
            limite = time.monotonic() + 5
            while fuente.leidos < total and time.monotonic() < limite:
                time.sleep(0.005)
            fin.set()

    d = Despertador("luna", lambda t: "jaja", fuente, ReconocedorFalso(), sintetizar=lambda t: b"WAV:" + t.encode(),
                    reproducir=reproducir, reloj=reloj, registro=lambda m: None, tono=False)
    d.correr()
    assert fin.wait(5)
    limite = time.monotonic() + 5
    while d._ocupado and time.monotonic() < limite:
        time.sleep(0.005)
    assert en_pausa == [True]
    assert d.activaciones == 1


def test_hablando_como_bloque():
    d, *_ = armar([])
    with d.hablando():
        assert d.en_pausa
    assert not d.en_pausa


# ---------------------------------------------------------------- enfriamiento
def test_enfriamiento_tras_cada_activacion():
    bloques = (silencio(3) + [voz("luna")] + pedido("uno")
               + [voz("luna")] + silencio(3)       # dentro de los 2 s de enfriamiento: se ignora
               + silencio(25) + [voz("luna")] + pedido("dos"))
    d, _, pedidos, _ = armar(bloques, tono=False, enfriamiento_s=2.0)
    d.correr()
    assert pedidos == ["uno", "dos"]
    assert d.activaciones == 2
    assert d.estado()["ignoradas_por_enfriamiento"] == 1


# ---------------------------------------------------------------- hilo, encender / apagar
def test_encender_y_apagar_en_segundo_plano():
    listo = threading.Event()
    bloques = silencio(3) + [voz("luna")] + pedido("hola") + silencio(2000)
    fuente = FuenteMemoria(bloques, al_leer=lambda i: time.sleep(0.0005))
    d = Despertador("luna", lambda t: listo.set() or "hola", fuente, ReconocedorFalso(),
                    reproducir=lambda w: None, registro=lambda m: None)
    assert d.encender() is True
    assert d.encender() is True                     # dos veces no crea dos hilos
    assert listo.wait(5)
    assert d.estado()["activo"] is True
    d.apagar()
    assert d.activo is False and d.estado()["estado"] == "apagado"
    assert fuente.abierta is False                  # liberó el micrófono


def test_un_error_en_la_respuesta_no_detiene_la_escucha():
    def falla(texto):
        if texto == "uno":
            raise RuntimeError("cerebro caído")
        return "ok"

    bloques = silencio(3) + [voz("luna")] + pedido("uno") + silencio(25) + [voz("luna")] + pedido("dos")
    d, _, _, sonidos = armar(bloques, tono=False)
    d.al_despertar = falla
    d.correr()
    assert d.activaciones == 2
    assert "cerebro caído" in d.estado()["ultimo_error"]
    assert sonidos == [b"WAV:ok"]


def test_transcribir_wav_inyectado_recibe_un_wav_valido():
    recibido = {}

    def whisper(ruta):
        with wave.open(ruta, "rb") as w:
            recibido.update(tasa=w.getframerate(), canales=w.getnchannels(), cuadros=w.getnframes())
        return "Luna, ¿qué hora es?"

    bloques = silencio(3) + [voz("luna")] + pedido("x")
    d, _, pedidos, _ = armar(bloques, tono=False, transcribir_wav=whisper)
    d.correr()
    assert recibido["tasa"] == 16000 and recibido["canales"] == 1 and recibido["cuadros"] > 0
    assert pedidos == ["¿qué hora es?"]


def test_umbral_adaptativo_sube_con_el_ruido():
    d, *_ = armar(silencio(30, nivel=400), tono=False)
    d.correr()
    assert d.estado()["umbral_voz"] > 1000          # ruido ~400 -> umbral ~1200, no 300


# ---------------------------------------------------------------- sin dependencias
def test_estado_sin_dependencias(monkeypatch, tmp_path):
    monkeypatch.setattr(dsp, "_importar", lambda nombre: None)
    monkeypatch.delenv("VOSK_MODELO", raising=False)
    d = Despertador(al_despertar=lambda t: "", carpeta_modelos=tmp_path, registro=lambda m: None)
    assert d.encender() is False                    # no lanza
    e = d.estado()
    assert e["disponible"] is False and e["activo"] is False and e["estado"] == "no disponible"
    texto = " ".join(e["faltan"])
    assert "vosk" in texto and "sounddevice" in texto and "instalar_voz.bat" in texto
    assert "alphacephei.com/vosk/models" in texto
    diag = dsp.diagnosticar(tmp_path)
    assert diag["listo"] is False and len(diag["faltan"]) == 3


def test_estado_real_de_este_entorno_no_lanza():
    e = Despertador(registro=lambda m: None).estado()
    assert isinstance(e["faltan"], list) and "disponible" in e


def test_buscar_modelo(tmp_path, monkeypatch):
    monkeypatch.delenv("VOSK_MODELO", raising=False)
    assert dsp.buscar_modelo(tmp_path) is None
    (tmp_path / "vosk-model-es-0.42" / "am").mkdir(parents=True)
    (tmp_path / "vosk-model-small-es-0.42" / "am").mkdir(parents=True)
    (tmp_path / "vosk-model-small-en-us-0.15" / "am").mkdir(parents=True)
    assert dsp.buscar_modelo(tmp_path).name == "vosk-model-small-es-0.42"


def test_ajuste_por_variable_y_config(monkeypatch):
    class Cfg:
        def __init__(self, valor):
            self.valor = valor

        def get(self, seccion, clave):
            if self.valor is None:
                raise KeyError(clave)
            return self.valor

    monkeypatch.delenv("ASISTENTE_DESPERTADOR", raising=False)
    assert dsp.despertador_activado() is False
    assert dsp.despertador_activado(Cfg(None)) is False
    assert dsp.despertador_activado(Cfg(True)) is True
    monkeypatch.setenv("ASISTENTE_DESPERTADOR", "no")
    assert dsp.despertador_activado(Cfg(True)) is False
    monkeypatch.setenv("ASISTENTE_DESPERTADOR", "si")
    assert dsp.despertador_activado() is True


# ---------------------------------------------------------------- Vosk (módulo falso)
class _VoskFalso:
    """Imita la API de vosk: Model, KaldiRecognizer(modelo, tasa[, gramatica]), AcceptWaveform, Result..."""

    def __init__(self, guion):
        self.guion = list(guion)      # por cada bloque: ("final", dict) o ("parcial", str)
        self.creados = []
        mod = self

        class Model:
            def __init__(self, ruta):
                self.ruta = ruta

        class KaldiRecognizer:
            def __init__(self, modelo, tasa, gramatica=None):
                self.gramatica, self.ultimo = gramatica, None
                mod.creados.append(self)

            def SetWords(self, v):
                pass

            def AcceptWaveform(self, pcm):
                if self.gramatica is None:
                    return False
                self.ultimo = mod.guion.pop(0) if mod.guion else ("parcial", "")
                return self.ultimo[0] == "final"

            def Result(self):
                return json.dumps(self.ultimo[1])

            def PartialResult(self):
                return json.dumps({"partial": self.ultimo[1]})

            def FinalResult(self):
                return json.dumps({"text": "que hora es"})

            def Reset(self):
                pass

        self.Model, self.KaldiRecognizer = Model, KaldiRecognizer
        self.SetLogLevel = lambda n: None


def test_reconocedor_vosk_usa_gramatica_restringida():
    vosk = _VoskFalso([
        ("final", {"text": "luna", "result": [{"word": "luna", "conf": 0.95}]}),
        ("final", {"text": "luna", "result": [{"word": "luna", "conf": 0.3}]}),   # poca confianza
        ("final", {"text": "[unk]", "result": [{"word": "[unk]", "conf": 1.0}]}),
        ("parcial", "luna"),           # un parcial solo no basta...
        ("parcial", "luna"),           # ...dos seguidos sí
        ("parcial", "[unk]"),
    ])
    r = ReconocedorVosk("modelo", "Luna", vosk_mod=vosk)
    assert json.loads(r.gramatica) == ["luna", "[unk]"]
    assert vosk.creados[0].gramatica == r.gramatica
    pcm = b"\x00" * 3200
    assert [r.palabra(pcm) for _ in range(6)] == [True, False, False, False, True, False]
    assert r.transcribir(b"\x00" * 64000) == "que hora es"
    assert vosk.creados[-1].gramatica is None       # la transcripción va sin gramática


# ---------------------------------------------------------------- utilidades
def test_quitar_nombre():
    assert dsp.quitar_nombre("Luna, ¿qué hora es?") == "¿qué hora es?"
    assert dsp.quitar_nombre("oye luna pon música") == "pon música"
    assert dsp.quitar_nombre("la luna está linda") == "la luna está linda"
    assert dsp.quitar_nombre("luna") == ""


def test_tono_es_wav_corto():
    with wave.open(io.BytesIO(dsp.tono_wav()), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        assert 0.05 < w.getnframes() / 16000 < 0.3


def test_reproducir_fuera_de_windows_no_hace_nada(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert dsp.reproducir_wav(dsp.tono_wav()) is None


# ---------------------------------------------------------------- interrumpir: "Luna, para"
def test_es_orden_de_parar():
    assert dsp.es_orden_de_parar("luna para")
    assert dsp.es_orden_de_parar("Luna, cállate ya")
    assert dsp.es_orden_de_parar("oye luna detente")
    assert not dsp.es_orden_de_parar("para luna")                 # el nombre va primero
    assert not dsp.es_orden_de_parar("luna parametriza el muro")  # "para" debe ser palabra completa
    assert not dsp.es_orden_de_parar("silencio")                   # sin el nombre, la TV no la corta


class ReconocedorConOrden(ReconocedorFalso):
    def orden(self, pcm):
        return dsp.es_orden_de_parar(leer_palabra(pcm))


def test_luna_para_mientras_piensa_no_habla():
    interrupciones, cortes = [], []
    d = None

    def luna_piensa(texto):
        d._procesar(voz("luna para"))              # Sergio la interrumpe mientras piensa
        return "una respuesta larguísima"

    bloques = silencio(5) + [voz("luna")] + silencio(4) + pedido("explica", "todo")
    reloj = Reloj()
    sonidos = []
    fuente = FuenteMemoria(bloques, al_leer=lambda i: setattr(reloj, "t", reloj.t + 0.1))
    d = Despertador("luna", luna_piensa, fuente, ReconocedorConOrden(), sintetizar=lambda t: b"WAV:" + t.encode(),
                    reproducir=sonidos.append, hilo_respuesta=False, reloj=reloj, registro=lambda m: None,
                    al_interrumpir=lambda: interrupciones.append(1), detener=lambda: cortes.append(1))
    d.correr()
    assert interrupciones == [1] and cortes == [1] and d.interrupciones == 1
    assert sonidos == [dsp.tono_wav()]                       # el bip sí; la respuesta no se dice


def test_sin_orden_responde_normal_y_no_interrumpe():
    bloques = silencio(5) + [voz("luna")] + pedido("que", "hora", "es")
    d, _, pedidos, sonidos = armar(bloques, al_interrumpir=lambda: pytest.fail("no debía interrumpir"))
    d._reconocedor = ReconocedorConOrden()
    d.correr()
    assert sonidos[-1] == b"WAV:respuesta a que hora es" and d.interrupciones == 0


def test_reconocedor_vosk_orden_con_gramatica_cerrada():
    vosk = _VoskFalso([
        ("final", {"text": "luna para", "result": [{"word": "luna", "conf": 0.9}, {"word": "para", "conf": 0.92}]}),
        ("final", {"text": "luna para", "result": [{"word": "luna", "conf": 0.9}, {"word": "para", "conf": 0.4}]}),
        ("final", {"text": "[unk]", "result": [{"word": "[unk]", "conf": 1.0}]}),
    ])
    r = ReconocedorVosk("modelo", "Luna", confianza_min=0.8, vosk_mod=vosk)
    pcm = b"\x00" * 3200
    assert [r.orden(pcm) for _ in range(3)] == [True, False, False]
    gramatica = json.loads(vosk.creados[-1].gramatica)
    assert "luna para" in gramatica and "luna detente" in gramatica and "[unk]" in gramatica
