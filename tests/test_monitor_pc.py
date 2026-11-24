import json
import sys

from lek import monitor_pc as mp


class LectorFalso:
    nombre = "falso"

    def __init__(self, **cambios):
        self.v = {
            "cpu": 23.4,
            "memoria": {"total_mb": 16 * 1024, "usada_mb": 9 * 1024, "porcentaje": 56.25},
            "disco": {"ruta": "C:\\", "total_gb": 476.0, "libre_gb": 120.4, "porcentaje": 74.7},
            "bateria": {"porcentaje": 80.0, "enchufado": True},
            "procesos": [{"nombre": "Revit", "mb": 3100}, {"nombre": "chrome", "mb": 1800},
                         {"nombre": "ollama", "mb": 900}, {"nombre": "python", "mb": 200},
                         {"nombre": "explorer", "mb": 120}],
            "encendido": 3 * 3600 + 12 * 60,
        }
        self.v.update(cambios)

    def __getattr__(self, clave):
        if clave in mp.LECTURAS:
            valor = self.v[clave]
            if isinstance(valor, Exception):
                def falla():
                    raise valor
                return falla
            return lambda: valor
        raise AttributeError(clave)


def test_frase_con_lo_esencial():
    t = mp.estado_pc(LectorFalso())
    for parte in ("CPU al 23 %", "RAM al 56 % (9,0 de 16,0 GB)", "120 GB libres de 476 GB",
                  "batería al 80 % (cargando)", "encendido hace 3 h 12 min", "Revit (3,0 GB)", "chrome (1,8 GB)"):
        assert parte in t, parte
    assert "ALERTA" not in t


def test_alerta_de_ram():
    lector = LectorFalso(memoria={"total_mb": 8192, "usada_mb": 7700, "porcentaje": 94.0})
    d = mp.leer(lector)
    assert len(d["alertas"]) == 1 and "RAM está al 94 %" in d["alertas"][0] and "Revit" in d["alertas"][0]
    assert mp.estado_pc(lector).startswith("ALERTA")


def test_alerta_de_bateria_solo_si_no_carga():
    assert "batería al 12 %" in mp.estado_pc(LectorFalso(bateria={"porcentaje": 12.0, "enchufado": False}))
    assert "ALERTA" not in mp.estado_pc(LectorFalso(bateria={"porcentaje": 12.0, "enchufado": True}))
    assert "ALERTA" not in mp.estado_pc(LectorFalso(bateria={"porcentaje": 15.0, "enchufado": False}))


def test_lecturas_que_fallan_no_tumban_el_monitor():
    d = mp.leer(LectorFalso(cpu=OSError("sin permiso"), bateria=None, procesos=RuntimeError("x")))
    assert d["cpu"] is None and d["procesos"] is None and "cpu" in d["errores"]
    t = mp.frase(d)
    assert "CPU" not in t and "batería" not in t and t.startswith("RAM al 56 %")


def test_sin_ninguna_lectura():
    falla = OSError("nada")
    assert mp.estado_pc(LectorFalso(**{k: falla for k in mp.LECTURAS})) == "No pude leer el estado del PC."


def test_procesos_se_agrupan_por_nombre():
    mb = 1024 ** 2
    top = mp.agrupar_procesos([("chrome.exe", 300 * mb), ("chrome.exe", 400 * mb), ("Revit.exe", 2000 * mb),
                               ("a", 1 * mb), ("b", 2 * mb), ("c", 3 * mb), ("d", 4 * mb), (None, 9 * mb)])
    assert top[:2] == [{"nombre": "Revit", "mb": 2000}, {"nombre": "chrome", "mb": 700}]
    assert len(top) == 5


def test_procesos_desde_powershell():
    salida = json.dumps([{"Name": "Revit.exe", "WorkingSetSize": 2 * 1024 ** 3},
                         {"Name": "svchost.exe", "WorkingSetSize": 10 * 1024 ** 2},
                         {"Name": "svchost.exe", "WorkingSetSize": 15 * 1024 ** 2}])
    assert mp.procesos_desde_json(salida) == [{"nombre": "Revit", "mb": 2048}, {"nombre": "svchost", "mb": 25}]
    assert mp.procesos_desde_json(json.dumps({"Name": "solo.exe", "WorkingSetSize": 1024 ** 2})) == \
        [{"nombre": "solo", "mb": 1}]


def test_lector_linux_con_proc_falso(tmp_path, monkeypatch):
    proc, sys_ = tmp_path / "proc", tmp_path / "sys"
    proc.mkdir()
    (proc / "meminfo").write_text("MemTotal:       8000000 kB\nMemFree:  100 kB\nMemAvailable:   2000000 kB\n")
    (proc / "uptime").write_text("7260.5 1000.0\n")
    estados = iter(["cpu  100 0 100 800 0 0 0 0\n", "cpu  150 0 150 900 0 0 0 0\n"])
    (proc / "stat").write_text("x")
    for pid, nombre, kb in (("1", "systemd", 10000), ("22", "python3", 50000), ("23", "python3", 30000)):
        (proc / pid).mkdir()
        (proc / pid / "status").write_text(f"Name:\t{nombre}\nVmRSS:\t   {kb} kB\n")
    (proc / "self").mkdir()
    bat, ac = sys_ / "class" / "power_supply" / "BAT0", sys_ / "class" / "power_supply" / "AC"
    bat.mkdir(parents=True)
    ac.mkdir()
    (bat / "type").write_text("Battery\n"), (bat / "capacity").write_text("9\n"), (bat / "status").write_text("Discharging\n")
    (ac / "type").write_text("Mains\n"), (ac / "online").write_text("0\n")

    lector = mp.LectorLinux(str(proc), str(sys_))
    monkeypatch.setattr(mp.time, "sleep", lambda s: (proc / "stat").write_text(next(estados)))
    (proc / "stat").write_text(next(estados))
    d = mp.leer(lector)
    assert d["cpu"] == 50.0
    assert round(d["memoria"]["porcentaje"]) == 75
    assert d["bateria"] == {"porcentaje": 9.0, "enchufado": False}
    assert d["procesos"][0] == {"nombre": "python3", "mb": 78}
    assert d["encendido"] == 7260.5
    assert any("batería al 9 %" in a for a in d["alertas"])
    assert "encendido hace 2 h 1 min" in mp.frase(d)


def test_sin_psutil_usa_respaldo_local(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)  # import psutil -> ImportError
    monkeypatch.setattr(mp.sys, "platform", "linux")
    assert isinstance(mp.lector_del_sistema(), mp.LectorLinux)


def test_con_psutil_falso():
    class B:
        percent, power_plugged = 50, False

    class M:
        total, available, percent = 8 * 1024 ** 3, 2 * 1024 ** 3, 75.0

    class P:
        def __init__(self, nombre, rss):
            self.info = {"name": nombre, "memory_info": type("MI", (), {"rss": rss})()}

    class PsutilFalso:
        cpu_percent = staticmethod(lambda interval: 12.0)
        virtual_memory = staticmethod(lambda: M)
        sensors_battery = staticmethod(lambda: B)
        boot_time = staticmethod(lambda: 0)
        process_iter = staticmethod(lambda campos: [P("Revit.exe", 1024 ** 3)])

    d = mp.leer(mp.LectorPsutil(PsutilFalso))
    assert d["cpu"] == 12.0 and d["memoria"]["usada_mb"] == 6144 and d["bateria"]["enchufado"] is False
    assert d["procesos"] == [{"nombre": "Revit", "mb": 1024}] and d["fuente"] == "psutil"


def test_duracion():
    assert mp.duracion(59) == "0 min"
    assert mp.duracion(90061) == "1 día y 1 h"
    assert mp.duracion(3 * 86400) == "3 días y 0 h"


def test_herramienta_bien_formada():
    assert mp.HERRAMIENTA["function"]["name"] == "estado_pc"
