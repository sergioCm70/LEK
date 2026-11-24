import threading
import time

from lek import notificaciones as nt
from lek.almacen import Almacen
from lek.notificaciones import Notificador


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def nuevo(tmp_path, **k):
    vistos = []
    k.setdefault("lanzador", lambda titulo, texto: vistos.append((titulo, texto)) or True)
    k.setdefault("en_hilo", False)
    k.setdefault("espera_grupo", None)
    a = Almacen(tmp_path)
    return a, Notificador(a, **k), vistos


def test_guarda_audita_y_lista(tmp_path):
    a, n, vistos = nuevo(tmp_path)
    i = n.notificar("codigo", "Creé la habilidad clima", "Habilidad nueva esperando aprobación", codigo="print(1)")
    n.notificar("archivos", "Ordené Descargas", "Moví 3 PDF a Universidad")
    lista = n.listar()
    assert [x["tipo"] for x in lista] == ["archivos", "codigo"]
    assert lista[1] == {"id": i, "fecha": lista[1]["fecha"], "tipo": "codigo", "titulo": "Creé la habilidad clima",
                        "detalle": "Habilidad nueva esperando aprobación", "codigo": "print(1)", "leida": False}
    assert n.contar_no_leidas() == 2
    assert len(vistos) == 2 and "código" in vistos[0][1]
    auditoria = a._q("SELECT * FROM auditoria WHERE accion='notificacion'")
    assert len(auditoria) == 2


def test_tipo_desconocido_no_se_pierde(tmp_path):
    _, n, _ = nuevo(tmp_path)
    n.notificar("raro", "Algo", "x")
    x = n.listar()[0]
    assert x["tipo"] == "aviso" and "raro" in x["detalle"]


def test_marcar_leidas_parcial_y_total(tmp_path):
    _, n, _ = nuevo(tmp_path)
    ids = [n.notificar("aviso", f"a{i}") for i in range(4)]
    assert n.marcar_leidas([ids[0], "no-es-id", ids[1]]) == 2
    assert n.contar_no_leidas() == 2
    assert {x["id"] for x in n.listar(no_leidas=True)} == {ids[2], ids[3]}
    assert n.marcar_leidas([]) == 0
    assert n.marcar_leidas() == 2
    assert n.contar_no_leidas() == 0
    assert len(n.listar(limite=3)) == 3


def test_forma_de_los_endpoints(tmp_path):
    _, n, _ = nuevo(tmp_path)
    i = n.notificar("salud", "Llevas 3 horas sin pausa")
    r = n.api_listar()
    assert r["no_leidas"] == 1 and r["notificaciones"][0]["id"] == i
    assert n.api_marcar({"ids": [i]}) == {"marcadas": 1, "no_leidas": 0}
    assert n.api_marcar({}) == {"marcadas": 0, "no_leidas": 0}


def test_rafaga_se_agrupa_pero_todo_queda_guardado(tmp_path):
    reloj = Reloj()
    _, n, vistos = nuevo(tmp_path, reloj=reloj)
    for i in range(12):
        n.notificar("archivos", f"Moví archivo {i}")
        reloj.t += 1
    n.notificar("codigo", "Otra cosa")  # otro tipo no se agrupa
    assert len(vistos) == 6  # 5 sueltos de archivos + 1 de código
    assert n.vaciar_grupos() == ["Luna hizo 12 cambios en archivos en el último minuto"]
    assert vistos[-1][0] == "Luna hizo 12 cambios en archivos en el último minuto"
    assert len(n.listar(limite=100)) == 13
    assert n.vaciar_grupos() == []  # no repite el resumen


def test_la_ventana_de_un_minuto_se_renueva(tmp_path):
    reloj = Reloj()
    _, n, vistos = nuevo(tmp_path, reloj=reloj)
    for _ in range(5):
        n.notificar("archivos", "x")
    reloj.t += 61
    for _ in range(5):
        n.notificar("archivos", "y")
    assert len(vistos) == 10


def test_temporizador_muestra_el_resumen_solo(tmp_path):
    _, n, vistos = nuevo(tmp_path, espera_grupo=0.05)
    for _ in range(7):
        n.notificar("proyecto", "cambio")
    limite = time.time() + 3
    while len(vistos) < 6 and time.time() < limite:
        time.sleep(0.02)
    assert vistos[-1][0] == "Luna hizo 7 cambios en el proyecto en el último minuto"


def test_no_bloquea_y_si_falla_igual_queda_guardado(tmp_path):
    soltar = threading.Event()

    def lento(titulo, texto):
        soltar.wait(5)
        raise RuntimeError("PowerShell roto")

    _, n, _ = nuevo(tmp_path, lanzador=lento, en_hilo=True)
    inicio = time.time()
    n.notificar("sistema", "Reinicié Ollama")
    assert time.time() - inicio < 1
    soltar.set()
    assert n.listar()[0]["titulo"] == "Reinicié Ollama"


def test_toast_fuera_de_windows_no_hace_nada(monkeypatch):
    monkeypatch.setattr(nt.sys, "platform", "linux")
    assert nt.toast_windows("t", "x", ejecutar=lambda *a, **k: 1 / 0) is False


def test_toast_pasa_textos_por_entorno_y_no_en_el_comando(monkeypatch):
    monkeypatch.setattr(nt.sys, "platform", "win32")
    recibido = {}

    class R:
        returncode = 0

    def ejecutar(cmd, **k):
        recibido["cmd"], recibido["env"] = cmd, k["env"]
        return R()

    malicioso = "'; Remove-Item C:\\ -Recurse; '"
    assert nt.toast_windows(malicioso, "texto\x00 con control", ejecutar=ejecutar) is True
    assert recibido["cmd"][0] == "powershell.exe"
    assert all(malicioso not in parte and "Remove-Item" not in parte for parte in recibido["cmd"])
    assert recibido["cmd"] == nt.comando_toast()  # constante: no depende del aviso
    assert recibido["env"]["LUNA_TOAST_TITULO"] == malicioso
    assert "\x00" not in recibido["env"]["LUNA_TOAST_TEXTO"]
    assert "ToastText02" in nt.SCRIPT_TOAST and "$env:LUNA_TOAST_TITULO" in nt.SCRIPT_TOAST


def test_toast_que_falla_devuelve_false(monkeypatch):
    monkeypatch.setattr(nt.sys, "platform", "win32")

    def roto(*a, **k):
        raise FileNotFoundError("powershell.exe")
    assert nt.toast_windows("t", "x", ejecutar=roto) is False
