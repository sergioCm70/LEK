"""Autoevaluación medible de LUNA: un banco versionado de casos verificables y un evaluador que compara
modelos por aciertos, tiempo y costo (no por tamaño) y guarda el historial para detectar regresiones."""
from .banco import CASOS, CATEGORIAS, VERSION_BANCO, Caso, Salida, casos
from .evaluador import comparar, evaluar, guardar, historial, informe_comparativo

__all__ = ["CASOS", "CATEGORIAS", "VERSION_BANCO", "Caso", "Salida", "casos", "comparar", "evaluar", "guardar",
           "historial", "informe_comparativo"]
