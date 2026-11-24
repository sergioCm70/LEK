"""Capacidad de análisis de LUNA: herramientas deterministas (sin modelo) que dan datos exactos.

Uso desde servidor.py (ver INTEGRACION_analisis.md):

    from lek import analisis
    HERRAMIENTAS += analisis.HERRAMIENTAS
    FUNCIONES.update(analisis.crear_funciones([CONOCIMIENTO, ...raíces permitidas...]))
    HERRAMIENTAS_PRIVADAS.update(analisis.HERRAMIENTAS_PRIVADAS)

Todas las funciones devuelven texto en español y nunca lanzan excepciones hacia el servidor:
los errores llegan como "No pude …" para que Luna se los explique al usuario.
"""
from __future__ import annotations

from .archivos import MAX_BYTES, analizar_archivo, comparar_archivos, validar_ruta
from .tablas import ErrorAnalisis, Plazo, calcular_tabla, evaluar

_txt = {"type": "string"}


def _f(nombre, descripcion, props=None, requeridos=None):
    """Mismo formato que _f() de servidor.py."""
    return {"type": "function", "function": {
        "name": nombre, "description": descripcion,
        "parameters": {"type": "object", "properties": props or {}, "required": requeridos or []}}}


DESCRIPCIONES = {
    "analizar_archivo":
        "Analiza un archivo del usuario y da datos EXACTOS: PDF (páginas, palabras, tamaño de lámina, si es "
        "escaneado, títulos), Word (encabezados, párrafos, tablas), Excel/CSV (hojas, columnas, tipos, filas, "
        "suma/media/mín/máx por columna), imagen (dimensiones, formato, EXIF), GLB/glTF (nodos, mallas, "
        "materiales, triángulos) o texto. 'ruta' puede ser la ruta completa o solo el nombre del archivo.",
    "calcular_tabla":
        "Calcula sobre una tabla CSV/XLSX (p. ej. un cuadro de áreas) sin hacer cuentas de memoria. "
        "'operacion': sumar, contar, promedio, minimo, maximo, listar o columnas; también en frase, "
        "p. ej. 'sumar Área por Piso donde Uso = vivienda'. Opcionales: 'columna', 'agrupar_por', "
        "'filtro' (Piso = 2 y Uso contiene vivienda; operadores = != > < >= <= contiene) y 'hoja'. "
        "Acepta decimales con coma y excluye las filas TOTAL del archivo (y dice si cuadran).",
    "comparar_archivos":
        "Compara dos archivos del usuario (dos versiones de una memoria, lámina o cuadro de áreas): en tablas "
        "dice filas, columnas, celdas y sumas que cambiaron; en PDF/Word/texto, las líneas quitadas y nuevas.",
    "evaluar":
        "Calculadora exacta: evalúa una expresión matemática (+ - * / ** % paréntesis; funciones sqrt, sin, cos, "
        "tan, log, log10, exp, floor, ceil, round, abs, min, max, sum, hypot, radians, degrees; constantes pi, e). "
        "Úsala SIEMPRE en vez de calcular de memoria. % es residuo: para un porcentaje escribe 0.15*200.",
}

HERRAMIENTAS = [
    _f("analizar_archivo", DESCRIPCIONES["analizar_archivo"], {"ruta": _txt}, ["ruta"]),
    _f("calcular_tabla", DESCRIPCIONES["calcular_tabla"],
       {"ruta": _txt, "operacion": _txt, "columna": _txt, "agrupar_por": _txt, "filtro": _txt, "hoja": _txt},
       ["ruta", "operacion"]),
    _f("comparar_archivos", DESCRIPCIONES["comparar_archivos"], {"ruta_a": _txt, "ruta_b": _txt}, ["ruta_a", "ruta_b"]),
    _f("evaluar", DESCRIPCIONES["evaluar"], {"expresion": _txt}, ["expresion"]),
]

# Leen archivos del usuario: sus resultados son PRIVADOS (clase "documentos", igual que buscar_documentos).
# evaluar no lee archivos; si la expresión viene de datos privados, el turno ya quedó marcado privado.
HERRAMIENTAS_PRIVADAS = {"analizar_archivo": "documentos", "calcular_tabla": "documentos",
                         "comparar_archivos": "documentos"}


def _seguro(funcion, *args, **kwargs) -> str:
    try:
        return funcion(*args, **kwargs)
    except ErrorAnalisis as e:
        return f"No pude: {e}"
    except MemoryError:
        return "No pude: el archivo es demasiado grande para la memoria disponible."
    except Exception as e:  # nunca tumbar el turno de Luna
        return f"No pude completar el análisis ({type(e).__name__})."


def crear_funciones(raices) -> dict:
    """Funciones listas para FUNCIONES de servidor.py, atadas a las carpetas permitidas.

    'raices' puede ser una lista o una función sin argumentos que la devuelva (para leerlas en cada llamada).
    """
    def _raices():
        return list(raices() if callable(raices) else raices)

    def f_analizar(ruta="", **_):
        return _seguro(analizar_archivo, ruta, _raices())

    def f_calcular(ruta="", operacion="", columna="", agrupar_por="", filtro="", hoja="", **_):
        def hacer():
            return calcular_tabla(validar_ruta(ruta, _raices()), operacion, columna or "", agrupar_por or "",
                                  filtro or "", hoja or "")
        return _seguro(hacer)

    def f_comparar(ruta_a="", ruta_b="", **_):
        return _seguro(comparar_archivos, ruta_a, ruta_b, _raices())

    def f_evaluar(expresion="", **_):
        return _seguro(evaluar, str(expresion))

    return {"analizar_archivo": f_analizar, "calcular_tabla": f_calcular,
            "comparar_archivos": f_comparar, "evaluar": f_evaluar}


__all__ = ["HERRAMIENTAS", "HERRAMIENTAS_PRIVADAS", "DESCRIPCIONES", "crear_funciones", "analizar_archivo",
           "calcular_tabla", "comparar_archivos", "evaluar", "validar_ruta", "ErrorAnalisis", "Plazo", "MAX_BYTES"]
