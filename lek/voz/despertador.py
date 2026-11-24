"""Palabra de activación local: Luna escucha su nombre en segundo plano, como Jarvis.

Flujo: micrófono (16 kHz mono) -> Vosk con gramática restringida ["luna", "[unk]"] (barato en CPU)
-> al oír "luna": tono corto -> graba el pedido hasta que haya silencio (VAD por energía, umbral
adaptativo, máximo 12 s) -> lo transcribe (Vosk sin gramática, o la función que se inyecte, p. ej.
faster-whisper) -> al_despertar(texto) devuelve la respuesta -> sintetizar(respuesta) da un WAV
-> se reproduce con winsound (fuera de Windows no suena).

Todo es local: el audio nunca sale del PC. Si faltan vosk, sounddevice o el modelo, no falla:
encender() devuelve False y estado() dice qué falta y cómo instalarlo.

Fuente de audio y reconocedor se pueden inyectar (las pruebas usan audio falso).
"""
from __future__ import annotations

import array
import collections
import contextlib
import importlib
import importlib.util
import io
import json
import math
import os
import pathlib
import re
import sys
import tempfile
import threading
import time
import unicodedata
import wave

TASA = 16000                  # Hz, lo que esperan Vosk y Whisper
BLOQUE_S = 0.1                # cada lectura del micrófono: 100 ms
RAIZ = pathlib.Path(__file__).resolve().parents[2]
CARPETA_MODELOS = RAIZ / "datos" / "modelos"
URL_MODELOS = "https://alphacephei.com/vosk/models"
MODELO_SUGERIDO = "vosk-model-small-es-0.42"

COMO_INSTALAR = {
    "vosk": "Falta la librería vosk. Ejecuta instalar_voz.bat (o: venv\\Scripts\\pip install vosk).",
    "sounddevice": "Falta sounddevice (acceso al micrófono). Ejecuta instalar_voz.bat "
                   "(o: venv\\Scripts\\pip install sounddevice).",
    "modelo": f"Falta el modelo de voz en español. Ejecuta instalar_voz.bat, o descarga "
              f"{MODELO_SUGERIDO}.zip desde {URL_MODELOS} y descomprímelo en datos/modelos/.",
}


# ---------------------------------------------------------------- utilidades de audio y texto
def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return sin_tildes.lower()


def _tokens(texto: str) -> list[str]:
    return re.findall(r"[a-z\[\]]+", _normalizar(texto))


def rms(pcm: bytes) -> float:
    """Energía (raíz cuadrática media) de un bloque PCM de 16 bits."""
    if len(pcm) < 2:
        return 0.0
    muestras = array.array("h")
    muestras.frombytes(pcm[: len(pcm) // 2 * 2])
    if sys.byteorder == "big":
        muestras.byteswap()
    suma = math.sumprod(muestras, muestras) if hasattr(math, "sumprod") else sum(m * m for m in muestras)
    return math.sqrt(suma / len(muestras))


def pcm_a_wav(pcm: bytes, tasa: int = TASA) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(tasa)
        w.writeframes(pcm)
    return buf.getvalue()


_TONO: dict = {}


def tono_wav(frecuencia: float = 880.0, ms: int = 140, volumen: float = 0.25) -> bytes:
    """Un 'bip' corto (seno con entrada y salida suaves) como WAV en memoria."""
    clave = (frecuencia, ms, volumen)
    if clave not in _TONO:
        n = int(TASA * ms / 1000)
        rampa = max(1, int(TASA * 0.01))
        muestras = array.array("h", (
            int(32767 * volumen * min(1.0, i / rampa, (n - i) / rampa) * math.sin(2 * math.pi * frecuencia * i / TASA))
            for i in range(n)))
        if sys.byteorder == "big":
            muestras.byteswap()
        _TONO[clave] = pcm_a_wav(muestras.tobytes())
    return _TONO[clave]


def reproducir_wav(wav: bytes) -> None:
    """Reproduce un WAV en memoria y espera a que termine. Fuera de Windows no hace nada."""
    if not wav or sys.platform != "win32":
        return
    import winsound
    winsound.PlaySound(wav, winsound.SND_MEMORY | winsound.SND_NODEFAULT)


def quitar_nombre(texto: str, nombre: str = "luna") -> str:
    """'Luna, ¿qué hora es?' -> '¿qué hora es?' (solo al comienzo)."""
    patron = rf"^\s*(?:(?:oye|hey|ey|hola)[\s,]+)?{re.escape(nombre)}\b[\s,.:;!¡]*"
    return re.sub(patron, "", texto or "", count=1, flags=re.I).strip()


# ---------------------------------------------------------------- dependencias
def _importar(nombre: str):
    """Importa un módulo opcional; None si falta o no carga (sounddevice lanza OSError sin PortAudio)."""
    try:
        return importlib.import_module(nombre)
    except Exception:
        return None


def buscar_modelo(carpeta: pathlib.Path | str | None = None) -> pathlib.Path | None:
    """Busca un modelo Vosk en español en datos/modelos/ (o en la variable VOSK_MODELO)."""
    propio = os.getenv("VOSK_MODELO", "").strip()
    if propio and pathlib.Path(propio).is_dir():
        return pathlib.Path(propio)
    carpeta = pathlib.Path(carpeta) if carpeta else CARPETA_MODELOS
    if not carpeta.is_dir():
        return None
    candidatos = [d for d in carpeta.iterdir()
                  if d.is_dir() and d.name.startswith("vosk-model") and "-es" in d.name
                  and ((d / "am").is_dir() or (d / "conf").is_dir())]
    candidatos.sort(key=lambda d: ("small" not in d.name, d.name))  # el pequeño primero: menos RAM
    return candidatos[0] if candidatos else None


def diagnosticar(carpeta_modelos: pathlib.Path | str | None = None) -> dict:
    """Qué hay y qué falta para escuchar en segundo plano, sin lanzar errores."""
    vosk = _importar("vosk") is not None
    sd = _importar("sounddevice") is not None
    modelo = buscar_modelo(carpeta_modelos)
    faltan = [COMO_INSTALAR[k] for k, ok in (("vosk", vosk), ("sounddevice", sd), ("modelo", modelo)) if not ok]
    return {
        "vosk": vosk,
        "sounddevice": sd,
        "modelo": str(modelo) if modelo else None,
        "faster_whisper": importlib.util.find_spec("faster_whisper") is not None,
        "windows": sys.platform == "win32",
        "faltan": faltan,
        "listo": not faltan,
    }


# ---------------------------------------------------------------- fuentes de audio
class FuenteMicrofono:
    """Micrófono por defecto con sounddevice: PCM 16 bits, mono, 16 kHz, bloques de 100 ms.
    La lectura es bloqueante (el hilo duerme mientras llega el audio: casi no gasta CPU)."""

    def __init__(self, tasa: int = TASA, bloque_s: float = BLOQUE_S, dispositivo=None):
        self.tasa, self.cuadros = tasa, int(tasa * bloque_s)
        self.dispositivo = dispositivo
        self._flujo = None

    def abrir(self) -> None:
        import sounddevice as sd
        self._flujo = sd.RawInputStream(samplerate=self.tasa, channels=1, dtype="int16",
                                        blocksize=self.cuadros, device=self.dispositivo)
        self._flujo.start()

    def leer(self) -> bytes | None:
        if self._flujo is None:
            return None
        datos, _desbordado = self._flujo.read(self.cuadros)
        return bytes(datos)

    def cerrar(self) -> None:
        flujo, self._flujo = self._flujo, None
        if flujo is not None:
            with contextlib.suppress(Exception):
                flujo.stop()
            with contextlib.suppress(Exception):
                flujo.close()


class FuenteMemoria:
    """Fuente falsa: entrega los bloques de una lista y luego termina (None). Para pruebas y demos."""

    def __init__(self, bloques, al_leer=None):
        self._bloques = collections.deque(bloques)
        self.al_leer = al_leer          # se llama antes de entregar cada bloque (para simular eventos)
        self.leidos = 0
        self.abierta = False

    def abrir(self) -> None:
        self.abierta = True

    def leer(self) -> bytes | None:
        if not self._bloques:
            return None
        if self.al_leer:
            self.al_leer(self.leidos)
        self.leidos += 1
        return self._bloques.popleft()

    def cerrar(self) -> None:
        self.abierta = False


# ---------------------------------------------------------------- reconocedor
class ReconocedorVosk:
    """Vosk local. Un solo modelo en RAM sirve para las dos tareas:
    - palabra(pcm): reconocedor con gramática ["luna", "[unk]"] (decodificación muy barata)
    - transcribir(pcm): reconocedor sin gramática, creado solo cuando hace falta."""

    def __init__(self, ruta_modelo, nombre: str = "luna", confianza_min: float = 0.6,
                 usar_parciales: bool = True, tasa: int = TASA, vosk_mod=None):
        self._vosk = vosk_mod or importlib.import_module("vosk")
        with contextlib.suppress(Exception):
            self._vosk.SetLogLevel(-1)
        self.nombre = _normalizar(nombre)
        self.tasa, self.confianza_min, self.usar_parciales = tasa, confianza_min, usar_parciales
        self.modelo = self._vosk.Model(str(ruta_modelo))
        self.gramatica = json.dumps([self.nombre, "[unk]"], ensure_ascii=False)
        self._rec = self._vosk.KaldiRecognizer(self.modelo, tasa, self.gramatica)
        with contextlib.suppress(Exception):
            self._rec.SetWords(True)
        self._parciales_seguidos = 0

    def palabra(self, pcm: bytes) -> bool:
        if self._rec.AcceptWaveform(pcm):
            self._parciales_seguidos = 0
            r = json.loads(self._rec.Result() or "{}")
            palabras = r.get("result") or []
            if palabras:
                return any(_normalizar(p.get("word", "")) == self.nombre
                           and float(p.get("conf", 1.0)) >= self.confianza_min for p in palabras)
            return self.nombre in _tokens(r.get("text", ""))
        if not self.usar_parciales:
            return False
        # Parcial: más rápido que esperar el final de la frase. Se exige en dos bloques seguidos
        # para no saltar con una hipótesis pasajera.
        parcial = json.loads(self._rec.PartialResult() or "{}").get("partial", "")
        self._parciales_seguidos = self._parciales_seguidos + 1 if self.nombre in _tokens(parcial) else 0
        return self._parciales_seguidos >= 2

    def reiniciar(self) -> None:
        self._parciales_seguidos = 0
        with contextlib.suppress(Exception):
            self._rec.Reset()

    # ---- dictado en vivo: mientras hablas, el texto aparece en pantalla
    def empezar_dictado(self) -> None:
        self._dictado = self._vosk.KaldiRecognizer(self.modelo, self.tasa)
        self._dictado_hecho = []

    def dictar(self, pcm: bytes) -> str:
        """Alimenta el dictado y devuelve lo entendido hasta ahora (frases cerradas + parcial)."""
        d = getattr(self, "_dictado", None)
        if d is None:
            return ""
        if d.AcceptWaveform(pcm):
            t = json.loads(d.Result() or "{}").get("text", "").strip()
            if t:
                self._dictado_hecho.append(t)
            parcial = ""
        else:
            parcial = json.loads(d.PartialResult() or "{}").get("partial", "").strip()
        return " ".join([*self._dictado_hecho, parcial]).strip()

    def fin_dictado(self) -> str:
        d, self._dictado = getattr(self, "_dictado", None), None
        if d is None:
            return ""
        t = json.loads(d.FinalResult() or "{}").get("text", "").strip()
        return " ".join([*self._dictado_hecho, t]).strip()

    def transcribir(self, pcm: bytes) -> str:
        rec = self._vosk.KaldiRecognizer(self.modelo, self.tasa)
        paso = self.tasa  # medio segundo de audio de 16 bits
        for i in range(0, len(pcm), paso):
            rec.AcceptWaveform(pcm[i:i + paso])
        return json.loads(rec.FinalResult() or "{}").get("text", "").strip()


# ---------------------------------------------------------------- el despertador
class Despertador:
    """Escucha "luna" en un hilo y atiende el pedido que sigue.

    al_despertar(texto) -> str   respuesta de Luna (p. ej. lambda t: responder(t, "voz"))
    sintetizar(texto) -> bytes   WAV de la respuesta (servidor.sintetizar); None = no habla
    fuente_audio                 objeto con abrir(), leer() -> bytes|None, cerrar(); None = micrófono
    reconocedor                  objeto con palabra(pcm)->bool, reiniciar(), transcribir(pcm)->str;
                                 None = ReconocedorVosk con el modelo de datos/modelos/
    transcribir_wav(ruta) -> str si se da, transcribe el pedido con esto (p. ej. faster-whisper)
    reproducir(wav)              reproduce un WAV y espera; por defecto winsound (no-op fuera de Windows)
    """

    def __init__(self, nombre: str = "luna", al_despertar=None, fuente_audio=None, reconocedor=None, *,
                 sintetizar=None, transcribir_wav=None, reproducir=None, carpeta_modelos=None,
                 enfriamiento_s: float = 2.0, silencio_fin_s: float = 0.8, espera_voz_s: float = 5.0,
                 max_pedido_s: float = 12.0, previo_s: float = 0.5, tono_s: float = 0.3,
                 umbral_min: float = 300.0, factor_umbral: float = 3.0, tono: bool = True,
                 hilo_respuesta: bool = True, reloj=time.monotonic, registro=None,
                 confianza_min: float = 0.6, usar_parciales: bool = True):
        self.nombre = nombre
        self.confianza_min, self.usar_parciales = confianza_min, usar_parciales
        self.al_despertar = al_despertar or (lambda texto: "")
        self.sintetizar = sintetizar
        self.transcribir_wav = transcribir_wav
        self._reproducir = reproducir or reproducir_wav
        self._fuente_inyectada, self._reconocedor_inyectado = fuente_audio, reconocedor
        self._fuente, self._reconocedor = fuente_audio, reconocedor
        self.carpeta_modelos = carpeta_modelos
        self.enfriamiento_s, self.silencio_fin_s, self.espera_voz_s = enfriamiento_s, silencio_fin_s, espera_voz_s
        self.max_pedido_s, self.tono_s = max_pedido_s, tono_s
        self.umbral_min, self.factor_umbral = umbral_min, factor_umbral
        self.tono, self.hilo_respuesta = tono, hilo_respuesta
        self._reloj = reloj
        self._registro = registro if registro is not None else (lambda m: print(f"  [voz] {m}"))

        self._candado = threading.Lock()
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._pausas = 0                     # >0: Luna (u otra parte) está hablando; no se escucha
        self._ocupado = False                # atendiendo un pedido
        self._sucio = False                  # hubo pausa: reiniciar el reconocedor antes de seguir
        self._fin_enfriamiento = 0.0
        self._fondo: float | None = None     # nivel de ruido de fondo (para el umbral adaptativo)
        self._previo = collections.deque(maxlen=max(1, round(previo_s / BLOQUE_S)))
        self._grabacion: dict | None = None
        self._estado = "apagado"
        self.parcial = ""                    # lo que va entendiendo mientras hablas (para la pantalla)
        self._dictando = False
        self.activaciones = 0
        self.ignoradas = 0
        self.ultima_activacion: float | None = None
        self.ultimo_texto = ""
        self.ultima_respuesta = ""
        self.ultimo_error = ""

    # ---------------------------------------------------------------- encender / apagar
    def faltan(self) -> list[str]:
        """Lo que falta para funcionar, según lo que no se inyectó."""
        if self._fuente_inyectada is not None and self._reconocedor_inyectado is not None:
            return []
        d = diagnosticar(self.carpeta_modelos)
        faltan = []
        if self._reconocedor_inyectado is None:
            faltan += [COMO_INSTALAR[k] for k in ("vosk", "modelo") if not d[k]]
        if self._fuente_inyectada is None and not d["sounddevice"]:
            faltan.append(COMO_INSTALAR["sounddevice"])
        return faltan

    def encender(self) -> bool:
        """Arranca la escucha en un hilo. Devuelve False (sin lanzar) si falta algo."""
        if self.activo:
            return True
        faltan = self.faltan()
        if faltan:
            self._estado = "no disponible"
            self.ultimo_error = " ".join(faltan)
            self._registro("Escucha en segundo plano desactivada. " + self.ultimo_error)
            return False
        self._parar.clear()
        self._hilo = threading.Thread(target=self._correr_seguro, name="luna-despertador", daemon=True)
        self._hilo.start()
        return True

    def apagar(self, espera_s: float = 3.0) -> None:
        self._parar.set()
        hilo = self._hilo
        if hilo and hilo is not threading.current_thread():
            hilo.join(espera_s)
        self._hilo = None
        self._estado = "apagado"

    @property
    def activo(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive()

    def correr(self) -> None:
        """Escucha en el hilo actual hasta que la fuente se acabe o se llame apagar()."""
        self._parar.clear()
        self._correr_seguro()

    def _correr_seguro(self) -> None:
        try:
            self._preparar()
            self._estado = "escuchando"
            self._registro(f"Escuchando '{self.nombre}' en segundo plano (todo local).")
            while not self._parar.is_set():
                pcm = self._fuente.leer()
                if pcm is None:
                    break
                if pcm:
                    self._procesar(pcm)
        except Exception as e:  # sin micrófono, modelo dañado, etc.: avisar y no tumbar a Luna
            self.ultimo_error = f"{type(e).__name__}: {e}"
            self._registro("La escucha en segundo plano se detuvo: " + self.ultimo_error)
        finally:
            if self._fuente is not None:
                with contextlib.suppress(Exception):
                    self._fuente.cerrar()
            self._estado = "apagado" if not self.ultimo_error or self._parar.is_set() else "error"

    def _preparar(self) -> None:
        if self._reconocedor is None:
            self._estado = "cargando modelo"
            self._reconocedor = ReconocedorVosk(buscar_modelo(self.carpeta_modelos), self.nombre,
                                                confianza_min=self.confianza_min,
                                                usar_parciales=self.usar_parciales)
        if self._fuente is None:
            self._fuente = FuenteMicrofono()
        self._fuente.abrir()

    # ---------------------------------------------------------------- pausa mientras habla
    @contextlib.contextmanager
    def hablando(self):
        """Mientras dure el bloque no se escucha (para que Luna no se oiga a sí misma)."""
        self.pausar()
        try:
            yield
        finally:
            self.reanudar()

    def pausar(self) -> None:
        with self._candado:
            self._pausas += 1
            self._sucio = True

    def reanudar(self, cola_s: float = 0.5) -> None:
        with self._candado:
            self._pausas = max(0, self._pausas - 1)
            if self._pausas == 0:  # el eco de la última palabra todavía puede estar en el búfer
                self._fin_enfriamiento = max(self._fin_enfriamiento, self._reloj() + cola_s)

    @property
    def en_pausa(self) -> bool:
        return self._pausas > 0

    # ---------------------------------------------------------------- el corazón
    def _umbral(self) -> float:
        return max(self.umbral_min, (self._fondo or 0.0) * self.factor_umbral)

    def _procesar(self, pcm: bytes) -> None:
        if self._pausas > 0 or self._ocupado:
            self._grabacion = None
            self._sucio = True
            return
        if self._sucio:
            self._sucio = False
            self._previo.clear()
            self._reconocedor.reiniciar()
        if self._grabacion is not None:
            self._grabar(pcm)
            return
        energia = rms(pcm)
        if self._fondo is None:
            self._fondo = energia
        elif energia < self._umbral():  # solo el ruido (no la voz) mueve el fondo
            self._fondo = 0.95 * self._fondo + 0.05 * energia
        self._previo.append(pcm)
        if not self._reconocedor.palabra(pcm):
            return
        self._reconocedor.reiniciar()
        if self._reloj() < self._fin_enfriamiento:
            self.ignoradas += 1
            return
        self._activar()

    def _activar(self) -> None:
        self.activaciones += 1
        self.ultima_activacion = time.time()
        self._estado = "grabando"
        self._registro(f"Me llamaron ({self.nombre}). Te escucho...")
        # lo dicho justo antes (incluye el nombre) por si el pedido vino seguido: "Luna, ¿qué hora es?"
        self._grabacion = {"bloques": list(self._previo), "tiempo": 0.0, "silencio": 0.0,
                           "voz": False, "saltar": self.tono_s if self.tono else 0.0}
        self.parcial = ""
        self._dictando = False
        if hasattr(self._reconocedor, "empezar_dictado"):
            with contextlib.suppress(Exception):
                self._reconocedor.empezar_dictado()
                self._dictando = True
                for b in self._grabacion["bloques"]:
                    self.parcial = quitar_nombre(self._reconocedor.dictar(b), self.nombre)
        self._previo.clear()
        if self.tono:
            with contextlib.suppress(Exception):
                self._reproducir(tono_wav())

    def _grabar(self, pcm: bytes) -> None:
        g = self._grabacion
        g["bloques"].append(pcm)
        if self._dictando:
            with contextlib.suppress(Exception):
                self.parcial = quitar_nombre(self._reconocedor.dictar(pcm), self.nombre)
        dur = len(pcm) / 2 / TASA
        g["tiempo"] += dur
        if g["tiempo"] > g["saltar"] and rms(pcm) > self._umbral():  # el propio bip no cuenta como voz
            g["voz"], g["silencio"] = True, 0.0
        elif g["voz"]:
            g["silencio"] += dur
        if ((g["voz"] and g["silencio"] >= self.silencio_fin_s)
                or (not g["voz"] and g["tiempo"] >= self.espera_voz_s)
                or g["tiempo"] >= self.max_pedido_s):
            audio = b"".join(g["bloques"])
            self._grabacion = None
            self._ocupado = True
            if self.hilo_respuesta:
                threading.Thread(target=self._atender, args=(audio,), name="luna-pedido", daemon=True).start()
            else:
                self._atender(audio)

    def _transcribir(self, pcm: bytes) -> str:
        dictado = ""
        if self._dictando:
            self._dictando = False
            with contextlib.suppress(Exception):
                dictado = self._reconocedor.fin_dictado()
        if self.transcribir_wav is None:
            return dictado or self._reconocedor.transcribir(pcm)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(pcm_a_wav(pcm))
            ruta = f.name
        try:
            return self.transcribir_wav(ruta) or dictado
        except Exception as e:  # si Whisper falla, vale lo que entendió Vosk
            self._registro(f"Whisper falló ({e}); uso la transcripción de Vosk.")
            return dictado or self._reconocedor.transcribir(pcm)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(ruta)

    def _atender(self, pcm: bytes) -> None:
        try:
            self._estado = "pensando"
            texto = quitar_nombre(self._transcribir(pcm), self.nombre)
            self.ultimo_texto = self.parcial = texto
            if not texto:  # falsa alarma o silencio: no molestar
                self._registro("No escuché ningún pedido.")
                return
            self._registro(f"Escuché: {texto!r}")
            respuesta = (self.al_despertar(texto) or "").strip()
            self.ultima_respuesta = respuesta
            if respuesta and self.sintetizar is not None:
                wav = self.sintetizar(respuesta)
                self._estado = "hablando"
                with self.hablando():
                    self._reproducir(wav)
        except Exception as e:
            self.ultimo_error = f"{type(e).__name__}: {e}"
            self._registro("Error atendiendo el pedido: " + self.ultimo_error)
        finally:
            self._fin_enfriamiento = max(self._fin_enfriamiento, self._reloj() + self.enfriamiento_s)
            self._ocupado = False
            if not self._parar.is_set() and self._estado != "apagado":
                self._estado = "escuchando"

    # ---------------------------------------------------------------- informe
    def estado(self) -> dict:
        faltan = self.faltan()
        return {
            "nombre": self.nombre,
            "activo": self.activo,
            "estado": self._estado,
            "disponible": not faltan,
            "faltan": faltan,
            "en_pausa": self.en_pausa,
            "activaciones": self.activaciones,
            "ignoradas_por_enfriamiento": self.ignoradas,
            "ultima_activacion": self.ultima_activacion,
            "ultimo_texto": self.ultimo_texto,
            "parcial": self.parcial,
            "ultimo_error": self.ultimo_error,
            "umbral_voz": round(self._umbral(), 1),
        }


def despertador_activado(config=None) -> bool:
    """¿Encender la escucha en segundo plano? ASISTENTE_DESPERTADOR=si/no manda; si no está,
    se mira config.get("voz", "despertador") si ese ajuste existe. Apagado por defecto."""
    env = os.getenv("ASISTENTE_DESPERTADOR", "").strip().lower()
    if env:
        return env in ("si", "sí", "1", "true", "on")
    if config is not None:
        with contextlib.suppress(Exception):
            return bool(config.get("voz", "despertador"))
    return False


if __name__ == "__main__":  # prueba manual: python -m lek.voz.despertador
    d = Despertador(al_despertar=lambda t: f"Escuché: {t}", hilo_respuesta=False)
    print(json.dumps(diagnosticar(), ensure_ascii=False, indent=2))
    if d.faltan():
        sys.exit(1)
    print("  Di 'Luna' y luego algo. Ctrl+C para salir.")
    with contextlib.suppress(KeyboardInterrupt):
        d.correr()
