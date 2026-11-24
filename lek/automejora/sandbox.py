"""Ejecución aislada de habilidades: en un SUBPROCESO aparte, para que un error, un bucle infinito
o un uso excesivo de memoria no tumbe a Luna, y sin ninguna clave en el entorno.

Aislamiento que SÍ da: proceso separado (python -I), carpeta de trabajo temporal que se borra,
entorno mínimo (sin CLAUDE_API_KEY, PIN ni nada de .env), tiempo límite que mata el proceso
(y sus hijos), y en Linux/Mac límites de memoria y tamaño de archivo.
Lo que NO da: no es una jaula del sistema operativo. El subproceso corre con el mismo usuario y
podría leer o escribir archivos con rutas absolutas o usar la red. Por eso la puerta real es
politica.analizar(): solo el código de riesgo bajo se ejecuta sin que Sergio lo apruebe.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import politica

MAX_TEXTO = 20_000      # caracteres máximos del resultado
MAX_EJEMPLOS = 10
MEMORIA_MAX = 1024 * 1024 * 1024   # 1 GB (solo Linux/Mac)

# Programa que corre DENTRO del subproceso. Lee la habilidad y los argumentos, captura lo que imprima,
# llama a la función y escribe UNA línea JSON precedida de una marca secreta en la salida estándar.
_LANZADOR = r'''
import io, json, sys, time, traceback, contextlib
marca, ruta_codigo, ruta_args, funcion, memoria = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
salida_real = sys.stdout
try:
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (memoria, memoria))
    resource.setrlimit(resource.RLIMIT_FSIZE, (10 * 1024 * 1024, 10 * 1024 * 1024))
except Exception:
    pass
respuesta = {"ok": False, "resultado": None, "error": None, "impreso": ""}
capturado = io.StringIO()
try:
    with open(ruta_args, encoding="utf-8") as f:
        argumentos = json.load(f)
    with open(ruta_codigo, encoding="utf-8") as f:
        codigo = f.read()
    espacio = {"__name__": "habilidad", "__file__": ruta_codigo}
    with contextlib.redirect_stdout(capturado), contextlib.redirect_stderr(capturado):
        exec(compile(codigo, "habilidad.py", "exec"), espacio)
        fn = espacio.get(funcion)
        if not callable(fn):
            raise NameError(f"la habilidad no tiene la función {funcion}()")
        if isinstance(argumentos, dict):
            valor = fn(**argumentos)
        elif isinstance(argumentos, list):
            valor = fn(*argumentos)
        else:
            valor = fn()
    respuesta["ok"] = True
    respuesta["resultado"] = None if valor is None else str(valor)
except BaseException as e:
    lineas = [l for l in traceback.format_exception(type(e), e, e.__traceback__) if "habilidad.py" in l]
    respuesta["error"] = (f"{type(e).__name__}: {e}" + ("\n" + "".join(lineas[-2:]) if lineas else ""))
respuesta["impreso"] = capturado.getvalue()
for clave in ("resultado", "error", "impreso"):
    if isinstance(respuesta[clave], str):
        respuesta[clave] = respuesta[clave][:LIMITE]
salida_real.write("\n" + marca + json.dumps(respuesta, ensure_ascii=False) + "\n")
salida_real.flush()
'''.replace("LIMITE", str(MAX_TEXTO))


def entorno_minimo(carpeta: str) -> dict:
    """Variables de entorno imprescindibles. NADA de claves: se construye desde cero, no se copia."""
    env = {"HOME": carpeta, "USERPROFILE": carpeta, "TMP": carpeta, "TEMP": carpeta, "TMPDIR": carpeta,
           "APPDATA": carpeta, "LOCALAPPDATA": carpeta, "PYTHONIOENCODING": "utf-8", "LANG": "C.UTF-8"}
    copiar = ["TZ"]
    if os.name == "nt":  # sin SYSTEMROOT Windows no inicia la red ni el azar criptográfico
        copiar += ["SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "PATHEXT", "NUMBER_OF_PROCESSORS",
                   "PROCESSOR_ARCHITECTURE", "PATH"]
    else:
        env["PATH"] = "/usr/bin:/bin"
    for nombre in copiar:
        if os.environ.get(nombre):
            env[nombre] = os.environ[nombre]
    return env


def _matar(proceso: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proceso.pid)], capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            os.killpg(proceso.pid, 9)
    except Exception:
        pass
    try:
        proceso.kill()
    except Exception:
        pass


def ejecutar_aislado(codigo: str, funcion: str = "ejecutar", argumentos=None, tiempo_limite: float = 15) -> dict:
    """Ejecuta funcion(**argumentos) del código en un subproceso aislado.
    Devuelve {"ok", "resultado", "error", "segundos"} (y "impreso": lo que la habilidad imprimió)."""
    inicio = time.monotonic()
    carpeta = tempfile.mkdtemp(prefix="luna_sandbox_")
    marca = "@@LUNA_" + secrets.token_hex(16) + "@@"

    def fin(ok, resultado=None, error=None, impreso=""):
        shutil.rmtree(carpeta, ignore_errors=True)
        return {"ok": ok, "resultado": resultado, "error": error, "segundos": round(time.monotonic() - inicio, 3),
                "impreso": impreso}

    try:
        Path(carpeta, "habilidad.py").write_text(codigo or "", encoding="utf-8")
        Path(carpeta, "argumentos.json").write_text(json.dumps(argumentos or {}, ensure_ascii=False),
                                                    encoding="utf-8")
        Path(carpeta, "_lanzador.py").write_text(_LANZADOR, encoding="utf-8")
    except (TypeError, ValueError) as e:
        return fin(False, error=f"Los argumentos no se pueden pasar al subproceso: {e}")
    comando = [sys.executable, "-I", "-X", "utf8", str(Path(carpeta, "_lanzador.py")), marca,
               str(Path(carpeta, "habilidad.py")), str(Path(carpeta, "argumentos.json")), funcion, str(MEMORIA_MAX)]
    opciones = {"cwd": carpeta, "env": entorno_minimo(carpeta), "stdin": subprocess.DEVNULL,
                "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    if os.name == "nt":
        opciones["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        opciones["start_new_session"] = True  # grupo propio: al vencer el tiempo se matan también sus hijos
    try:
        proceso = subprocess.Popen(comando, **opciones)
    except OSError as e:
        return fin(False, error=f"No pude iniciar el subproceso: {e}")
    try:
        salida, errores = proceso.communicate(timeout=tiempo_limite)
    except subprocess.TimeoutExpired:
        _matar(proceso)
        try:
            proceso.communicate(timeout=5)
        except Exception:
            pass
        return fin(False, error=f"Se pasó del tiempo límite de {tiempo_limite:g} s y la detuve.")
    texto = salida.decode("utf-8", "replace")
    if marca in texto:
        try:
            datos = json.loads(texto.rsplit(marca, 1)[1].strip().splitlines()[0])
            return fin(bool(datos.get("ok")), datos.get("resultado"), datos.get("error"), datos.get("impreso", ""))
        except (ValueError, IndexError):
            pass
    detalle = errores.decode("utf-8", "replace").strip()[-1500:]
    return fin(False, error=f"El subproceso terminó sin respuesta (código {proceso.returncode}). {detalle}".strip())


def _parecido(texto) -> str:
    return " ".join(str(texto or "").casefold().split())


def probar_habilidad(codigo: str, tiempo_limite: float = 15) -> dict:
    """Corre cada caso de EJEMPLOS = [{"args": {...}, "espera_contiene": "..."}] en su propio subproceso.
    {"ok": bool, "casos": [...], "error": str|None}"""
    ejemplos = politica.leer_constante(codigo, "EJEMPLOS")
    if not isinstance(ejemplos, list) or not ejemplos:
        return {"ok": False, "casos": [], "error": "Faltan EJEMPLOS = [{\"args\": {...}, \"espera_contiene\": \"...\"}] "
                                                     "(al menos uno, con valores literales)."}
    casos = []
    for i, ej in enumerate(ejemplos[:MAX_EJEMPLOS], 1):
        if not isinstance(ej, dict) or not isinstance(ej.get("args", {}), (dict, list)) \
                or not isinstance(ej.get("espera_contiene"), str) or not ej["espera_contiene"].strip():
            casos.append({"n": i, "ok": False, "error": "El ejemplo debe tener 'args' (dict) y 'espera_contiene' (texto)."})
            continue
        r = ejecutar_aislado(codigo, "ejecutar", ej.get("args", {}), tiempo_limite)
        paso = r["ok"] and _parecido(ej["espera_contiene"]) in _parecido(r["resultado"])
        casos.append({"n": i, "ok": paso, "args": ej.get("args", {}), "espera_contiene": ej["espera_contiene"],
                      "resultado": r["resultado"], "error": r["error"] if not r["ok"] else
                      (None if paso else "El resultado no contiene lo esperado."), "segundos": r["segundos"]})
    ok = all(c["ok"] for c in casos)
    fallos = [c for c in casos if not c["ok"]]
    return {"ok": ok, "casos": casos,
            "error": None if ok else f"Fallaron {len(fallos)} de {len(casos)} ejemplos: " +
            "; ".join(f"#{c['n']}: {c['error']}" for c in fallos)}


def decidir(codigo: str, modo_autonomo: bool = False, tiempo_limite: float = 15) -> dict:
    """Decide qué hacer con una habilidad nueva. Nunca la activa: solo dice qué hacer.
    {"accion": "activar_sola"|"pedir_aprobacion"|"rechazar", "motivos", "riesgo", "pruebas", "codigo", "resumen"}"""
    codigo = codigo or ""
    analisis = politica.analizar(codigo)
    motivos = list(analisis["motivos"])
    pruebas = {"ok": None, "casos": [], "error": "No se ejecutaron."}

    def salida(accion: str, resumen: str) -> dict:
        return {"accion": accion, "motivos": motivos, "riesgo": analisis["riesgo"], "pruebas": pruebas,
                "codigo": codigo, "resumen": resumen}

    if not analisis["compila"]:
        return salida("rechazar", f"Rechazada: el código {analisis['error']}.")
    if not politica.tiene_funcion(codigo, "ejecutar"):
        motivos.append("falta la función ejecutar(...)")
        return salida("rechazar", "Rechazada: falta la función ejecutar(...).")
    if analisis["riesgo"] != "bajo":
        # el código de riesgo alto NO se ejecuta ni en pruebas: el subproceso no es una jaula del sistema
        pruebas["error"] = "No se ejecutaron: riesgo alto, primero debe aprobarla Sergio."
        return salida("pedir_aprobacion",
                      f"Necesita tu aprobación: riesgo alto ({len(motivos)} motivo(s)): {motivos[0]}.")
    pruebas = probar_habilidad(codigo, tiempo_limite)
    if not pruebas["ok"]:
        motivos.append(pruebas["error"])
        return salida("rechazar", f"Rechazada: {pruebas['error']}")
    n = len(pruebas["casos"])
    if modo_autonomo:
        motivos.append(f"riesgo bajo y {n}/{n} ejemplos pasaron en el sandbox")
        return salida("activar_sola", f"Activada sola: riesgo bajo y {n}/{n} ejemplos pasaron. Te muestro el código.")
    motivos.append("modo autónomo apagado")
    return salida("pedir_aprobacion",
                  f"Riesgo bajo y {n}/{n} ejemplos pasaron, pero el modo autónomo está apagado: necesita tu aprobación.")


def ejecutar_habilidad_aprobada(ruta, argumentos=None, tiempo_limite: float = 30) -> dict:
    """Ejecuta una habilidad ya aprobada (habilidades/x.py) también en un subproceso aislado."""
    try:
        codigo = Path(ruta).read_text(encoding="utf-8")
    except OSError as e:
        return {"ok": False, "resultado": None, "error": f"No pude leer la habilidad: {e}", "segundos": 0.0,
                "impreso": ""}
    return ejecutar_aislado(codigo, "ejecutar", argumentos, tiempo_limite)
