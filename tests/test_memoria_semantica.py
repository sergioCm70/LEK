"""Pruebas de la memoria semántica. Sin red y sin Ollama: el embebedor es falso y determinista.
Las pruebas de EmbebedorOllama usan un Ollama de mentira en 127.0.0.1 (no sale del PC)."""
import array
import hashlib
import http.server
import json
import random
import re
import socket
import threading
import time

import pytest

from lek import memoria_semantica as ms
from lek.almacen import VACIAS, Almacen, plano
from lek.memoria_semantica import EmbebedorOllama, ErrorEmbebedor, MemoriaSemantica, es_local

try:
    import numpy  # noqa: F401
    HAY_NUMPY = True
except ImportError:
    HAY_NUMPY = False

# Palabras distintas con el mismo significado van al mismo "concepto": así el embebedor falso
# entiende paráfrasis que la búsqueda por palabras (FTS) no puede encontrar.
CONCEPTOS = {
    "perro": "can", "perrito": "can", "mascota": "can", "cachorro": "can", "toby": "can",
    "entrega": "entrega", "entregar": "entrega", "plazo": "entrega",
    "taller": "taller", "arquitectura": "taller", "maqueta": "taller", "planos": "taller",
    "cafe": "cafe", "tinto": "cafe",
    "feliz": "alegria", "contento": "alegria", "alegre": "alegria",
}


class EmbebedorFalso:
    """Determinista (md5, no hash() de Python): bolsa de conceptos proyectada en `dim` dimensiones."""

    def __init__(self, dim=64, modelo="falso-embed", disponible=True):
        self.dim, self.modelo, self._disponible = dim, modelo, disponible
        self.lote = 16
        self.llamadas = 0
        self.textos = 0
        self.ultimo_consulta = None

    def disponible(self):
        return self._disponible

    def vector(self, texto):
        v = [0.0] * self.dim
        for w in re.findall(r"[a-z0-9]+", plano(texto)):
            if w in VACIAS or len(w) < 3:
                continue
            c = CONCEPTOS.get(w, CONCEPTOS.get(w.rstrip("s"), w.rstrip("s")))
            h = hashlib.md5(c.encode()).digest()
            v[int.from_bytes(h[:4], "little") % self.dim] += 1.0 if h[4] % 2 else -1.0
        return v

    def embeber(self, textos, consulta=False):
        self.llamadas += 1
        self.textos += len(textos)
        self.ultimo_consulta = consulta
        return [self.vector(t) for t in textos]


class EmbebedorRoto(EmbebedorFalso):
    def embeber(self, textos, consulta=False):
        raise ErrorEmbebedor("Ollama se cayó")


@pytest.fixture
def almacen(tmp_path):
    return Almacen(tmp_path / "datos")


def charla(alm):
    ids = [alm.guardar_mensaje("usuario", "Mi mascota Toby es un cachorro muy juguetón"),
           alm.guardar_mensaje("luna", "Qué lindo, me encanta saber de Toby"),
           alm.guardar_mensaje("usuario", "El viernes es la entrega del taller con el profesor"),
           alm.guardar_mensaje("usuario", "Compré tinto colombiano para la oficina"),
           alm.guardar_mensaje("usuario", "ok")]
    return ids


# ---------------------------------------------------------------- esquema e indexado
def test_crea_tabla_vectores_sin_tocar_lo_demas(almacen):
    MemoriaSemantica(almacen, EmbebedorFalso())
    MemoriaSemantica(almacen, EmbebedorFalso())  # dos veces: CREATE TABLE IF NOT EXISTS
    columnas = [f["name"] for f in almacen._q("PRAGMA table_info(vectores)")]
    assert columnas == ["id", "tipo", "ref", "texto", "vector", "modelo", "fecha"]
    almacen.guardar_mensaje("usuario", "sigue funcionando")
    assert almacen.total_mensajes() == 1


def test_indexado_incremental_e_idempotente(almacen):
    emb = EmbebedorFalso()
    mem = MemoriaSemantica(almacen, emb)
    charla(almacen)
    r = mem.indexar_pendientes(limite=2)
    assert r["mensajes"] == 2 and r["pendientes"] == 3
    r = mem.indexar_pendientes()
    assert r["mensajes"] == 2 and r["pendientes"] == 0   # el "ok" (muy corto) se salta pero no queda pendiente
    llamadas = emb.llamadas
    assert mem.indexar_pendientes()["mensajes"] == 0
    assert emb.llamadas == llamadas                       # nada nuevo: ni una llamada al modelo
    almacen.guardar_mensaje("usuario", "Mañana llevo la maqueta")
    assert mem.indexar_pendientes()["mensajes"] == 1
    # aunque se pierda el progreso, no se duplica nada
    almacen._fijar(f"semantica:{mem.modelo}:mensajes", "0")
    assert mem.indexar_pendientes()["mensajes"] == 0
    assert almacen._q("SELECT count(*) AS n FROM vectores")[0]["n"] == 5
    assert emb.ultimo_consulta is False                   # documentos se embeben como documentos


def test_vectores_normalizados_en_float32(almacen):
    mem = MemoriaSemantica(almacen, EmbebedorFalso(dim=32))
    charla(almacen)
    mem.indexar_pendientes()
    for f in almacen._q("SELECT vector FROM vectores"):
        v = array.array("f")
        v.frombytes(f["vector"])
        assert len(v) == 32
        assert abs(sum(x * x for x in v) - 1.0) < 1e-5


def test_recuerdos_se_indexan_y_los_archivados_no_salen(almacen):
    mem = MemoriaSemantica(almacen, EmbebedorFalso())
    almacen.recordar("Su perro se llama Toby")
    almacen.recordar("Toma tinto sin azúcar")
    assert mem.indexar_pendientes()["recuerdos"] == 2
    r = mem.buscar("¿cómo se llama mi mascota?", k=1, tipos=("recuerdo",))
    assert r[0]["dato"] == "Su perro se llama Toby" and r[0]["privado"] == 1
    almacen.archivar_recuerdos("perro")
    r = mem.buscar("¿cómo se llama mi mascota?", k=3, tipos=("recuerdo",))
    assert all("Toby" not in f["texto"] for f in r)


# ---------------------------------------------------------------- búsqueda
def test_encuentra_parafrasis_que_fts_no_ve(almacen):
    mem = MemoriaSemantica(almacen, EmbebedorFalso())
    ids = charla(almacen)
    mem.indexar_pendientes()
    consulta = "¿qué te conté de mi perrito?"
    assert almacen.buscar_mensajes(consulta) == []       # por palabras: nada
    r = mem.buscar(consulta, k=2, tipos=("mensaje",))
    assert r[0]["id"] == ids[0] and r[0]["fuente"] == "semantica"
    assert r[0]["puntaje"] > 0.5
    # mismas claves que Almacen.buscar_mensajes: sirve tal cual en contexto_pasado
    assert {"id", "fecha", "rol", "contenido", "privado"} <= set(r[0])
    h = mem.buscar_hibrido(consulta, k=2, tipos=("mensaje",))
    assert h[0]["id"] == ids[0]


def test_minimo_y_antes_de_id(almacen):
    mem = MemoriaSemantica(almacen, EmbebedorFalso())
    ids = charla(almacen)
    mem.indexar_pendientes()
    assert mem.buscar("algo de astronomía", k=5, minimo=0.5) == []
    r = mem.buscar("mi cachorro", k=5, tipos=("mensaje",), antes_de_id=ids[1])
    assert [f["id"] for f in r] == [ids[0]]


def test_respaldo_fts_sin_embebedor(almacen):
    charla(almacen)
    for emb in (None, EmbebedorFalso(disponible=False), EmbebedorRoto()):
        mem = MemoriaSemantica(almacen, emb)
        r = mem.buscar("entrega del taller", k=3)
        assert r and r[0]["contenido"].startswith("El viernes") and r[0]["fuente"] == "texto"
        h = mem.buscar_hibrido("entrega del taller", k=3)
        assert h[0]["contenido"].startswith("El viernes")
    sin = MemoriaSemantica(almacen, None)
    r = sin.indexar_pendientes()
    assert r["mensajes"] == 0 and r["pendientes"] == 5 and r["error"]
    assert sin.indexar_documento("a.txt", ["hola mundo"])["error"]


def test_embebedor_que_falla_a_mitad_no_pierde_progreso(almacen):
    class FallaLuego(EmbebedorFalso):
        def embeber(self, textos, consulta=False):
            if self.llamadas >= 1:
                raise ErrorEmbebedor("se cayó")
            return super().embeber(textos, consulta)

    emb = FallaLuego()
    emb.lote = 2
    mem = MemoriaSemantica(almacen, emb)
    for i in range(6):
        almacen.guardar_mensaje("usuario", f"mensaje número {i} sobre arquitectura")
    r = mem.indexar_pendientes()
    assert r["mensajes"] == 2 and r["pendientes"] == 4 and "se cayó" in r["error"]
    mem.embebedor = EmbebedorFalso()
    assert mem.indexar_pendientes()["mensajes"] == 4


def test_hibrido_fusiona_por_rango_reciproco(almacen):
    mem = MemoriaSemantica(almacen, EmbebedorFalso())
    a = almacen.guardar_mensaje("usuario", "Toby, mi perro, se comió la maqueta")
    b = almacen.guardar_mensaje("usuario", "Mi cachorro juguetón duerme todo el día")
    almacen.guardar_mensaje("usuario", "El perro del vecino ladra")
    mem.indexar_pendientes()
    h = mem.buscar_hibrido("perro maqueta", k=3, tipos=("mensaje",))
    assert h[0]["id"] == a and h[0]["fuente"] == "ambas"
    assert b in [f["id"] for f in h]                      # solo la semántica lo encuentra
    assert h[0]["puntaje_rrf"] == pytest.approx(2 / 61, abs=1e-4)
    assert h[0]["puntaje_rrf"] >= h[1]["puntaje_rrf"] >= h[2]["puntaje_rrf"]


def test_documentos_incrementales(almacen):
    emb = EmbebedorFalso()
    mem = MemoriaSemantica(almacen, emb)
    trozos = [{"archivo": "taller.pdf", "texto": "La entrega final es el viernes"},
              {"archivo": "taller.pdf", "texto": "Planos a escala 1:100"},
              "Presupuesto de la maqueta"]
    assert mem.indexar_documento("taller.pdf", trozos)["nuevos"] == 3
    textos = emb.textos
    r = mem.indexar_documento("taller.pdf", trozos)
    assert r["nuevos"] == 0 and r["sin_cambios"] == 3 and emb.textos == textos
    r = mem.indexar_documento("taller.pdf", ["La entrega final es el viernes", "Planos a escala 1:50"])
    assert (r["nuevos"], r["sin_cambios"], r["borrados"]) == (1, 1, 1)
    mem.indexar_documento("a", ["otro documento con nombre corto"])
    mem.indexar_documento("a#b.txt", ["nombre raro con almohadilla"])
    r = mem.buscar("¿cuál es el plazo?", k=1, tipos=("documento",))
    assert r[0]["archivo"] == "taller.pdf" and r[0]["trozo"] == 0 and r[0]["privado"] == 1
    assert mem.olvidar_documento("a") == 1                 # no arrastra a "a#b.txt"
    assert mem.documentos_indexados() == ["a#b.txt", "taller.pdf"]
    assert mem.podar_documentos(["taller.pdf"]) == 1
    assert mem.documentos_indexados() == ["taller.pdf"]


def test_otro_modelo_no_mezcla_vectores(almacen):
    charla(almacen)
    MemoriaSemantica(almacen, EmbebedorFalso(dim=64, modelo="uno")).indexar_pendientes()
    otro = MemoriaSemantica(almacen, EmbebedorFalso(dim=32, modelo="dos"))
    assert otro.estado()["vectores"] == {}
    assert otro.indexar_pendientes()["mensajes"] == 4      # su propio progreso
    assert otro.buscar("perrito", k=1, tipos=("mensaje",))[0]["fuente"] == "semantica"


def test_cache_se_actualiza_con_lo_nuevo_y_con_borrados(almacen):
    mem = MemoriaSemantica(almacen, EmbebedorFalso())
    charla(almacen)
    mem.indexar_pendientes()
    assert mem.buscar("tinto", k=1)[0]["contenido"].startswith("Compré")
    n = len(mem._cache["ids"])
    mem.indexar_documento("cafe.txt", ["El tinto de la cafetería es barato"])
    assert len(mem._cache["ids"]) == n                    # aún no se ha buscado
    r = mem.buscar("café barato", k=1, tipos=("documento",))
    assert r[0]["archivo"] == "cafe.txt" and len(mem._cache["ids"]) == n + 1
    mem.olvidar_documento("cafe.txt")
    assert mem.buscar("café barato", k=3, tipos=("documento",)) == []


@pytest.mark.skipif(not HAY_NUMPY, reason="numpy no instalado")
def test_numpy_y_puro_python_dan_lo_mismo(almacen):
    charla(almacen)
    emb = EmbebedorFalso()
    con_np = MemoriaSemantica(almacen, emb, usar_numpy=True)
    con_np.indexar_pendientes()
    sin_np = MemoriaSemantica(almacen, emb, usar_numpy=False)
    for q in ("mi perrito", "entrega del taller", "tinto"):
        a = [(f["ref"], f["puntaje"]) for f in con_np.buscar(q, k=4)]
        b = [(f["ref"], f["puntaje"]) for f in sin_np.buscar(q, k=4)]
        assert [x[0] for x in a] == [x[0] for x in b]
        assert [x[1] for x in a] == pytest.approx([x[1] for x in b], abs=1e-4)


# ---------------------------------------------------------------- rendimiento (sin numpy)
class EmbebedorAzar:
    """768 dimensiones pseudoaleatorias pero deterministas por texto."""
    modelo, lote = "azar-768", 64

    def disponible(self):
        return True

    def embeber(self, textos, consulta=False):
        salida = []
        for t in textos:
            rnd = random.Random(t)
            salida.append([rnd.gauss(0, 1) for _ in range(768)])
        return salida


def test_rendimiento_5000_vectores_768_sin_numpy(almacen, capsys):
    mem = MemoriaSemantica(almacen, EmbebedorAzar(), usar_numpy=False)
    emb = EmbebedorAzar()
    # vectores pre-calculados: se mide el almacén y la búsqueda, no el embebedor falso
    filas = [("documento", f"libro.pdf#{i}", f"trozo {i}", ms._normalizado(v))
             for i, v in enumerate(emb.embeber([f"trozo {i}" for i in range(5000)]))]
    t0 = time.perf_counter()
    assert mem._guardar(filas) == 5000
    t_guardar = time.perf_counter() - t0

    t0 = time.perf_counter()
    r = mem.buscar("trozo 1234", k=5)                      # en frío: carga 5000 vectores de SQLite
    t_frio = time.perf_counter() - t0
    assert r[0]["ref"] == "libro.pdf#1234" and r[0]["puntaje"] == pytest.approx(1.0, abs=1e-4)

    tiempos = []
    for q in ("trozo 7", "trozo 4999", "trozo 2500", "algo que no está"):
        t0 = time.perf_counter()
        r = mem.buscar(q, k=5)
        tiempos.append(time.perf_counter() - t0)
    t_caliente = sorted(tiempos)[len(tiempos) // 2]

    mem._guardar([("documento", "libro.pdf#5000", "trozo 5000",
                   ms._normalizado(emb.embeber(["trozo 5000"])[0]))])
    t0 = time.perf_counter()
    assert mem.buscar("trozo 5000", k=1)[0]["ref"] == "libro.pdf#5000"   # carga incremental: solo 1 fila
    t_incremental = time.perf_counter() - t0

    with capsys.disabled():
        print(f"\n[rendimiento sin numpy, 5000x768, sumprod={'sí' if ms._sumprod else 'no'}] "
              f"guardar {t_guardar*1000:.0f} ms | búsqueda en frío {t_frio*1000:.0f} ms | "
              f"en caliente {t_caliente*1000:.0f} ms | tras 1 vector nuevo {t_incremental*1000:.0f} ms")
    assert t_caliente < 2.0      # margen amplio para un PC cargado; aquí ~50 ms


# ---------------------------------------------------------------- EmbebedorOllama contra un Ollama de mentira local
class _OllamaFalso(http.server.BaseHTTPRequestHandler):
    modelos = ["qwen3:8b", "nomic-embed-text:latest"]
    pedidos = []
    emb = EmbebedorFalso(dim=16)

    def log_message(self, *a):
        pass

    def _responder(self, datos):
        cuerpo = json.dumps(datos).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        self._responder({"models": [{"name": n} for n in self.modelos]})

    def do_POST(self):
        datos = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).pedidos.append(datos)
        textos = [re.sub(r"^search_(query|document): ", "", t) for t in datos["input"]]
        self._responder({"model": datos["model"], "embeddings": self.emb.embeber(textos)})


@pytest.fixture
def ollama_falso():
    _OllamaFalso.pedidos = []
    _OllamaFalso.modelos = ["qwen3:8b", "nomic-embed-text:latest"]
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _OllamaFalso)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_embebedor_ollama_lotes_de_16_y_prefijos(ollama_falso):
    emb = EmbebedorOllama(ollama_falso)
    assert emb.disponible()
    vecs = emb.embeber([f"texto {i}" for i in range(40)])
    assert len(vecs) == 40
    assert [len(p["input"]) for p in _OllamaFalso.pedidos] == [16, 16, 8]
    assert all(p["model"] == "nomic-embed-text" for p in _OllamaFalso.pedidos)
    assert _OllamaFalso.pedidos[0]["input"][0] == "search_document: texto 0"
    emb.embeber(["hola"], consulta=True)
    assert _OllamaFalso.pedidos[-1]["input"] == ["search_query: hola"]


def test_embebedor_ollama_sin_el_modelo(ollama_falso):
    _OllamaFalso.modelos = ["qwen3:8b"]
    emb = EmbebedorOllama(ollama_falso)
    assert not emb.disponible() and "ollama pull nomic-embed-text" in emb.motivo
    assert not EmbebedorOllama(ollama_falso, modelo="nomic-embed-text:v1.5").disponible()


def test_embebedor_ollama_apagado_no_frena(almacen):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()                                             # puerto cerrado: conexión rechazada
    emb = EmbebedorOllama(f"http://127.0.0.1:{puerto}", timeout_sondeo=1.0)
    t0 = time.perf_counter()
    assert not emb.disponible()
    assert not emb.disponible()                           # el segundo usa lo recordado
    assert time.perf_counter() - t0 < 2.5
    almacen.guardar_mensaje("usuario", "El viernes es la entrega del taller")
    mem = MemoriaSemantica(almacen, emb)
    assert mem.buscar("entrega taller")[0]["fuente"] == "texto"


def test_nunca_a_la_nube():
    assert es_local("http://127.0.0.1:11434") and es_local("http://localhost:11434")
    assert es_local("http://192.168.1.20:11434") and es_local("http://100.101.102.103:11434")  # LAN / Tailscale
    assert not es_local("https://api.ejemplo.com") and not es_local("http://8.8.8.8:11434")
    emb = EmbebedorOllama("https://api.ejemplo.com")
    assert not emb.disponible() and "no es local" in emb.motivo
    with pytest.raises(ErrorEmbebedor):
        emb.embeber(["secreto"])


def test_de_punta_a_punta_con_ollama_falso(almacen, ollama_falso):
    mem = MemoriaSemantica(almacen, EmbebedorOllama(ollama_falso))
    ids = charla(almacen)
    assert mem.indexar_pendientes()["mensajes"] == 4
    r = mem.buscar_hibrido("¿qué te conté de mi perrito?", k=2, tipos=("mensaje",))
    assert r[0]["id"] == ids[0]
    assert mem.estado()["vectores"] == {"mensaje": 4}
