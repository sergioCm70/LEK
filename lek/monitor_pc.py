"""Monitor del PC de LUNA: CPU, RAM, disco, batería, procesos que más RAM usan y tiempo encendido.

Todo local, sin red y sin dependencias obligatorias:
  - si psutil está instalado se usa (import perezoso, solo al primer uso);
  - si no, en Windows: ctypes (memoria, batería, CPU, tiempo encendido) + PowerShell Get-CimInstance (procesos);
  - en Linux: /proc y /sys.
Cada lectura que falle queda en None; el monitor nunca se cae por una lectura.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

RAM_ALERTA = 90.0       # % de RAM usada
BATERIA_ALERTA = 15.0   # % de batería sin cargar
MUESTRA_CPU = 0.25      # segundos entre las dos lecturas de CPU


# ---------------------------------------------------------------- utilidades comunes
def disco_raiz() -> str:
    if sys.platform.startswith("win"):
        return os.environ.get("SystemDrive", "C:") + "\\"
    return "/"


def leer_disco(ruta: str | None = None) -> dict:
    u = shutil.disk_usage(ruta or disco_raiz())
    return {"ruta": ruta or disco_raiz(), "total_gb": u.total / 1024 ** 3, "libre_gb": u.free / 1024 ** 3,
            "porcentaje": (u.used / u.total * 100) if u.total else 0.0}


def agrupar_procesos(pares, cuantos: int = 5) -> list:
    """[(nombre, bytes)] -> top por nombre, sumando procesos con el mismo nombre (chrome x30 = un chrome)."""
    suma = {}
    for nombre, b in pares:
        if not nombre or not b:
            continue
        nombre = str(nombre)
        if nombre.lower().endswith(".exe"):
            nombre = nombre[:-4]
        suma[nombre] = suma.get(nombre, 0) + int(b)
    orden = sorted(suma.items(), key=lambda x: x[1], reverse=True)[:cuantos]
    return [{"nombre": n, "mb": round(b / 1024 ** 2)} for n, b in orden]


# ---------------------------------------------------------------- lector con psutil (opcional)
class LectorPsutil:
    nombre = "psutil"

    def __init__(self, psutil):
        self.ps = psutil

    def cpu(self):
        return float(self.ps.cpu_percent(interval=MUESTRA_CPU))

    def memoria(self):
        m = self.ps.virtual_memory()
        return {"total_mb": m.total / 1024 ** 2, "usada_mb": (m.total - m.available) / 1024 ** 2,
                "porcentaje": float(m.percent)}

    def disco(self):
        return leer_disco()

    def bateria(self):
        b = self.ps.sensors_battery() if hasattr(self.ps, "sensors_battery") else None
        if b is None:
            return None
        return {"porcentaje": float(b.percent), "enchufado": bool(b.power_plugged)}

    def procesos(self):
        pares = []
        for p in self.ps.process_iter(["name", "memory_info"]):
            try:
                mi = p.info.get("memory_info")
                pares.append((p.info.get("name"), mi.rss if mi else 0))
            except Exception:
                continue
        return agrupar_procesos(pares)

    def encendido(self):
        return time.time() - self.ps.boot_time()


# ---------------------------------------------------------------- lector Windows (ctypes + PowerShell)
class LectorWindows:
    nombre = "windows"

    def __init__(self, ejecutar=subprocess.run):
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.wt, self.ejecutar = ctypes, wintypes, ejecutar
        self.k32 = ctypes.windll.kernel32

    def _tiempos(self):
        ft = self.wt.FILETIME
        idle, kernel, user = ft(), ft(), ft()
        if not self.k32.GetSystemTimes(self.ctypes.byref(idle), self.ctypes.byref(kernel), self.ctypes.byref(user)):
            raise OSError("GetSystemTimes falló")
        v = lambda f: (f.dwHighDateTime << 32) | f.dwLowDateTime  # noqa: E731
        return v(idle), v(kernel), v(user)

    def cpu(self):
        i1, k1, u1 = self._tiempos()
        time.sleep(MUESTRA_CPU)
        i2, k2, u2 = self._tiempos()
        total = (k2 - k1) + (u2 - u1)  # el tiempo de kernel incluye el ocioso
        return max(0.0, min(100.0, (1 - (i2 - i1) / total) * 100)) if total else 0.0

    def memoria(self):
        c = self.ctypes

        class MEMORYSTATUSEX(c.Structure):
            _fields_ = [("dwLength", c.c_ulong), ("dwMemoryLoad", c.c_ulong), ("ullTotalPhys", c.c_ulonglong),
                        ("ullAvailPhys", c.c_ulonglong), ("ullTotalPageFile", c.c_ulonglong),
                        ("ullAvailPageFile", c.c_ulonglong), ("ullTotalVirtual", c.c_ulonglong),
                        ("ullAvailVirtual", c.c_ulonglong), ("ullAvailExtendedVirtual", c.c_ulonglong)]
        m = MEMORYSTATUSEX()
        m.dwLength = c.sizeof(MEMORYSTATUSEX)
        if not self.k32.GlobalMemoryStatusEx(c.byref(m)):
            raise OSError("GlobalMemoryStatusEx falló")
        total, libre = m.ullTotalPhys, m.ullAvailPhys
        return {"total_mb": total / 1024 ** 2, "usada_mb": (total - libre) / 1024 ** 2,
                "porcentaje": (total - libre) / total * 100 if total else 0.0}

    def disco(self):
        return leer_disco()

    def bateria(self):
        c = self.ctypes

        class SYSTEM_POWER_STATUS(c.Structure):
            _fields_ = [("ACLineStatus", c.c_ubyte), ("BatteryFlag", c.c_ubyte), ("BatteryLifePercent", c.c_ubyte),
                        ("SystemStatusFlag", c.c_ubyte), ("BatteryLifeTime", c.c_ulong),
                        ("BatteryFullLifeTime", c.c_ulong)]
        s = SYSTEM_POWER_STATUS()
        if not self.k32.GetSystemPowerStatus(c.byref(s)):
            raise OSError("GetSystemPowerStatus falló")
        if s.BatteryFlag == 128 or s.BatteryLifePercent == 255:  # 128 = sin batería (PC de escritorio)
            return None
        return {"porcentaje": float(s.BatteryLifePercent), "enchufado": s.ACLineStatus == 1}

    def procesos(self):
        script = ("Get-CimInstance Win32_Process | Select-Object Name,WorkingSetSize | "
                  "ConvertTo-Json -Compress")
        r = self.ejecutar(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, timeout=20,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        return procesos_desde_json(r.stdout)

    def encendido(self):
        self.k32.GetTickCount64.restype = self.ctypes.c_ulonglong
        return self.k32.GetTickCount64() / 1000.0


def procesos_desde_json(texto: str) -> list:
    datos = json.loads(texto or "[]")
    if isinstance(datos, dict):
        datos = [datos]
    return agrupar_procesos((d.get("Name"), d.get("WorkingSetSize") or 0) for d in datos)


# ---------------------------------------------------------------- lector Linux (/proc y /sys)
def cpu_desde_stat(antes: str, despues: str) -> float:
    def partes(t):
        v = [int(x) for x in t.splitlines()[0].split()[1:]]
        ocioso = v[3] + (v[4] if len(v) > 4 else 0)
        return ocioso, sum(v)
    o1, t1 = partes(antes)
    o2, t2 = partes(despues)
    total = t2 - t1
    return max(0.0, min(100.0, (1 - (o2 - o1) / total) * 100)) if total else 0.0


def memoria_desde_meminfo(texto: str) -> dict:
    v = {}
    for linea in texto.splitlines():
        clave, _, resto = linea.partition(":")
        if resto.strip():
            v[clave.strip()] = int(resto.split()[0])  # kB
    total = v["MemTotal"]
    libre = v.get("MemAvailable", v.get("MemFree", 0) + v.get("Buffers", 0) + v.get("Cached", 0))
    return {"total_mb": total / 1024, "usada_mb": (total - libre) / 1024,
            "porcentaje": (total - libre) / total * 100 if total else 0.0}


class LectorLinux:
    nombre = "linux"

    def __init__(self, proc: str = "/proc", sys_: str = "/sys"):
        self.proc, self.sys = pathlib.Path(proc), pathlib.Path(sys_)

    def cpu(self):
        a = (self.proc / "stat").read_text()
        time.sleep(MUESTRA_CPU)
        return cpu_desde_stat(a, (self.proc / "stat").read_text())

    def memoria(self):
        return memoria_desde_meminfo((self.proc / "meminfo").read_text())

    def disco(self):
        return leer_disco()

    def bateria(self):
        carpeta = self.sys / "class" / "power_supply"
        if not carpeta.is_dir():
            return None
        porcentaje, estado, red = None, "", None
        for d in carpeta.iterdir():
            tipo = (d / "type").read_text().strip() if (d / "type").exists() else ""
            if tipo == "Battery" and (d / "capacity").exists():
                porcentaje = float((d / "capacity").read_text().strip())
                estado = (d / "status").read_text().strip() if (d / "status").exists() else ""
            elif tipo == "Mains" and (d / "online").exists():
                red = (d / "online").read_text().strip() == "1"
        if porcentaje is None:
            return None
        enchufado = red if red is not None else estado in ("Charging", "Full", "Not charging")
        return {"porcentaje": porcentaje, "enchufado": bool(enchufado)}

    def procesos(self):
        pares = []
        for d in self.proc.iterdir():
            if not d.name.isdigit():
                continue
            try:
                nombre, rss = "", 0
                for linea in (d / "status").read_text().splitlines():
                    if linea.startswith("Name:"):
                        nombre = linea.split(None, 1)[1].strip()
                    elif linea.startswith("VmRSS:"):
                        rss = int(linea.split()[1]) * 1024
                pares.append((nombre, rss))
            except (OSError, ValueError, IndexError):
                continue
        return agrupar_procesos(pares)

    def encendido(self):
        return float((self.proc / "uptime").read_text().split()[0])


# ---------------------------------------------------------------- elegir lector y leer
def lector_del_sistema():
    try:
        import psutil  # opcional; import perezoso
        return LectorPsutil(psutil)
    except ImportError:
        pass
    if sys.platform.startswith("win"):
        return LectorWindows()
    return LectorLinux()


LECTURAS = ("cpu", "memoria", "disco", "bateria", "procesos", "encendido")


def leer(lector=None) -> dict:
    """Todas las lecturas; la que falle queda en None (y su error en 'errores')."""
    lector = lector or lector_del_sistema()
    datos, errores = {}, {}
    for clave in LECTURAS:
        try:
            datos[clave] = getattr(lector, clave)()
        except Exception as e:  # una lectura rota no tumba las demás
            datos[clave], errores[clave] = None, f"{type(e).__name__}: {e}"[:200]
    datos["fuente"] = getattr(lector, "nombre", type(lector).__name__)
    datos["errores"] = errores
    datos["alertas"] = alertas(datos)
    return datos


def alertas(d: dict) -> list:
    out = []
    m, b, procs = d.get("memoria"), d.get("bateria"), d.get("procesos") or []
    if m and m.get("porcentaje") is not None and m["porcentaje"] > RAM_ALERTA:
        culpable = f" Lo que más usa: {procs[0]['nombre']} ({_mb(procs[0]['mb'])})." if procs else ""
        out.append(f"ALERTA: la RAM está al {m['porcentaje']:.0f} %; cierra algo para que el PC no se ponga lento.{culpable}")
    if b and b.get("porcentaje") is not None and b["porcentaje"] < BATERIA_ALERTA and not b.get("enchufado"):
        out.append(f"ALERTA: batería al {b['porcentaje']:.0f} % y sin cargar; conecta el cargador ya.")
    return out


# ---------------------------------------------------------------- frase para hablar
def _num(x: float, dec: int = 0) -> str:
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _mb(mb: float) -> str:
    return f"{_num(mb / 1024, 1)} GB" if mb >= 1024 else f"{_num(mb)} MB"


def duracion(segundos: float) -> str:
    s = int(segundos)
    dias, s = divmod(s, 86400)
    horas, s = divmod(s, 3600)
    minutos = s // 60
    if dias:
        return f"{dias} día{'s' if dias != 1 else ''} y {horas} h"
    if horas:
        return f"{horas} h {minutos} min"
    return f"{minutos} min"


def frase(d: dict) -> str:
    partes = []
    if d.get("cpu") is not None:
        partes.append(f"CPU al {d['cpu']:.0f} %")
    m = d.get("memoria")
    if m:
        partes.append(f"RAM al {m['porcentaje']:.0f} % ({_num(m['usada_mb'] / 1024, 1)} de "
                      f"{_num(m['total_mb'] / 1024, 1)} GB)")
    k = d.get("disco")
    if k:
        partes.append(f"disco con {_num(k['libre_gb'])} GB libres de {_num(k['total_gb'])} GB")
    b = d.get("bateria")
    if b:
        partes.append(f"batería al {b['porcentaje']:.0f} % ({'cargando' if b['enchufado'] else 'sin cargar'})")
    if d.get("encendido") is not None:
        partes.append(f"encendido hace {duracion(d['encendido'])}")
    texto = (", ".join(partes) + ".") if partes else "No pude leer el estado del PC."
    texto = texto[0].upper() + texto[1:]
    procs = d.get("procesos")
    if procs:
        texto += " Lo que más RAM usa: " + ", ".join(f"{p['nombre']} ({_mb(p['mb'])})" for p in procs[:3]) + "."
    if d.get("alertas"):
        texto = " ".join(d["alertas"]) + " " + texto
    return texto


def estado_pc(lector=None) -> str:
    """Herramienta de Luna: una frase con lo esencial del PC (y alerta si RAM > 90 % o batería < 15 % sin cargar)."""
    return frase(leer(lector))


HERRAMIENTA = {"type": "function", "function": {
    "name": "estado_pc",
    "description": "Estado actual del PC del usuario: CPU, RAM, disco, batería, programas que más RAM usan "
                   "y tiempo encendido. Avisa si la RAM pasa del 90 % o la batería baja del 15 % sin cargar.",
    "parameters": {"type": "object", "properties": {}, "required": []}}}
