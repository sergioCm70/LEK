"""Aislamiento real de habilidades en Windows (LEK 2.0, fase 1).

Un subproceso normal NO es un entorno seguro: corre con el mismo usuario y puede escribir en todos
los archivos de Sergio. Aquí se suman dos barreras del sistema operativo:

1. **Nivel de integridad bajo.** El código corre con una copia de python.exe marcada con
   `icacls /setintegritylevel low`. Windows arranca con integridad baja todo proceso que nace de un ejecutable
   así marcado, y un proceso con integridad baja no puede escribir en las carpetas ni en el registro del usuario,
   que tienen integridad media (sí puede leerlos).
2. **Job Object.** Pone un tope de memoria (512 MB) y permite un solo proceso, así que la habilidad no puede
   lanzar programas. Bloquea el portapapeles, el escritorio y el apagado. Si Luna cierra el Job, se mata todo.

Si la copia con integridad baja no se puede preparar, queda solo el Job Object y `estado()` lo dice.
`autoprueba()` comprueba de verdad en este PC qué barreras funcionan.

Limitaciones honestas: la red sigue abierta, el proceso puede LEER archivos del usuario y no es un
contenedor ni una máquina virtual. Por eso cada habilidad sigue necesitando el análisis estático y la
aprobación de Sergio.
"""
from __future__ import annotations

import ctypes
import os
import pathlib
import shutil
import subprocess
import sys

MEMORIA_JOB = 512 * 1024 * 1024
_estado = {"integridad_baja": None, "job": None, "detalle": "", "python": ""}

if os.name == "nt":
    from ctypes import wintypes as wt

    class _BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]

    class _IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOps", "WriteOps", "OtherOps",
                                                   "ReadBytes", "WriteBytes", "OtherBytes")]

    class _EXTENDIDO(ctypes.Structure):
        _fields_ = [("Basic", _BASIC), ("Io", _IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class _UI(ctypes.Structure):
        _fields_ = [("UIRestrictionsClass", wt.DWORD)]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    _k32.CreateJobObjectW.restype = wt.HANDLE
    _k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
    _k32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
    _k32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    _k32.CloseHandle.argtypes = [wt.HANDLE]
    _ntdll.NtResumeProcess.argtypes = [wt.HANDLE]

LIMITE_MEMORIA_PROCESO = 0x100
LIMITE_PROCESOS = 0x8
MATAR_AL_CERRAR = 0x2000
MORIR_SI_FALLA = 0x400
UI_TODO = 0x1 | 0x2 | 0x4 | 0x8 | 0x10 | 0x20 | 0x40 | 0x80   # handles, portapapeles, parámetros, escritorio…
CREAR_SUSPENDIDO = 0x4


def disponible() -> bool:
    return os.name == "nt"


class Job:
    """Job Object con límites; al cerrarse mata los procesos que contiene."""

    def __init__(self, memoria: int = MEMORIA_JOB):
        self.h = _k32.CreateJobObjectW(None, None)
        if not self.h:
            raise OSError(ctypes.get_last_error(), "CreateJobObject falló")
        info = _EXTENDIDO()
        info.Basic.LimitFlags = LIMITE_MEMORIA_PROCESO | LIMITE_PROCESOS | MATAR_AL_CERRAR | MORIR_SI_FALLA
        info.Basic.ActiveProcessLimit = 1
        info.ProcessMemoryLimit = memoria
        if not _k32.SetInformationJobObject(self.h, 9, ctypes.byref(info), ctypes.sizeof(info)):
            err = ctypes.get_last_error()
            self.cerrar()
            raise OSError(err, "SetInformationJobObject falló")
        ui = _UI(UI_TODO)
        _k32.SetInformationJobObject(self.h, 4, ctypes.byref(ui), ctypes.sizeof(ui))

    def meter(self, proceso: subprocess.Popen) -> None:
        if not _k32.AssignProcessToJobObject(self.h, int(proceso._handle)):
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject falló")

    def cerrar(self) -> None:
        if self.h:
            _k32.CloseHandle(self.h)
            self.h = None


def python_base() -> pathlib.Path:
    """El python.exe real (no el lanzador del venv, que abre un segundo proceso)."""
    return pathlib.Path(getattr(sys, "_base_executable", "") or sys.executable).resolve()


def preparar_python_baja(carpeta: pathlib.Path) -> pathlib.Path | None:
    """Copia python.exe (y sus DLL) a `carpeta` y la marca con integridad baja. Se hace una vez."""
    base = python_base()
    destino = pathlib.Path(carpeta) / "python_baja.exe"
    marca = pathlib.Path(carpeta) / "integridad_baja.ok"
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        firma = f"{base}|{base.stat().st_size}|{base.stat().st_mtime_ns}"
        if destino.exists() and marca.exists() and marca.read_text(encoding="utf-8") == firma:
            return destino
        shutil.copy2(base, destino)
        for dll in base.parent.glob("*.dll"):          # python3XX.dll, python3.dll, vcruntime…
            shutil.copy2(dll, pathlib.Path(carpeta) / dll.name)
        r = subprocess.run(["icacls", str(destino), "/setintegritylevel", "low"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=20)
        if r.returncode != 0:
            raise OSError(r.stderr.decode("mbcs", "replace") or r.stdout.decode("mbcs", "replace"))
        marca.write_text(firma, encoding="utf-8")
        return destino
    except Exception as e:
        _estado["detalle"] = f"Sin integridad baja: {e}"
        return None


def lanzar(comando: list, opciones: dict, carpeta_exe: pathlib.Path):
    """Arranca el comando (comando[0] se reemplaza por el python adecuado) suspendido, lo mete en el Job y lo
    reanuda. Devuelve (proceso, job). Si algo falla en el Job, mata el proceso: nunca corre sin límites."""
    exe = preparar_python_baja(carpeta_exe)
    _estado["integridad_baja"] = exe is not None
    comando = [str(exe or python_base())] + list(comando[1:])
    env = dict(opciones.get("env") or {})
    env["PYTHONHOME"] = sys.base_prefix                # la copia está fuera de su carpeta: le decimos dónde está Lib
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    opciones = {**opciones, "env": env,
                "creationflags": opciones.get("creationflags", 0) | CREAR_SUSPENDIDO}
    _estado["python"] = comando[0]
    proceso = subprocess.Popen(comando, **opciones)
    try:
        job = Job()
        job.meter(proceso)
        _estado["job"] = True
    except Exception as e:
        _estado["job"] = False
        _estado["detalle"] = f"Job Object falló: {e}"
        proceso.kill()
        raise
    _ntdll.NtResumeProcess(int(proceso._handle))
    return proceso, job


def estado() -> dict:
    return dict(_estado, disponible=disponible())


PRUEBAS = {
    "escribir en tus archivos": ("def ejecutar(ruta):\n    open(ruta, 'w').write('x')\n    return 'escribió'\n", True),
    "abrir otro programa": ("import subprocess\ndef ejecutar():\n"
                            "    subprocess.run(['cmd', '/c', 'echo hola'], check=True)\n    return 'abrió'\n", True),
    "usar más de 512 MB": ("def ejecutar():\n    b = bytearray(700 * 1024 * 1024)\n    return 'reservó'\n", True),
    "calcular normalmente": ("def ejecutar():\n    return str(sum(range(10)))\n", False),
}


def autoprueba(ejecutar_aislado, carpeta_prueba: pathlib.Path) -> dict:
    """Ejecuta código de prueba (fijo, escrito aquí) y comprueba qué barreras funcionan en este PC."""
    carpeta_prueba.mkdir(parents=True, exist_ok=True)
    objetivo = carpeta_prueba / "no_debe_escribirse.txt"
    objetivo.unlink(missing_ok=True)
    resultados = {}
    for nombre, (codigo, debe_fallar) in PRUEBAS.items():
        args = {"ruta": str(objetivo)} if "ruta" in codigo else {}
        r = ejecutar_aislado(codigo, argumentos=args, tiempo_limite=30)
        bloqueado = not r.get("ok")
        if nombre == "escribir en tus archivos":
            bloqueado = bloqueado and not objetivo.exists()
        resultados[nombre] = {"esperado": "bloqueado" if debe_fallar else "permitido",
                              "obtenido": "bloqueado" if bloqueado else "permitido",
                              "ok": bloqueado == debe_fallar, "detalle": (r.get("error") or r.get("resultado") or "")[:200]}
    objetivo.unlink(missing_ok=True)
    return {"estado": estado(), "pruebas": resultados, "todo_ok": all(v["ok"] for v in resultados.values())}
