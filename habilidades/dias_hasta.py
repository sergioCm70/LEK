# Habilidad de ejemplo: cuánto falta para una fecha (entregas, parciales)
import datetime

DESCRIPCION = "Calcula cuántos días faltan para una fecha (formato AAAA-MM-DD)."
PARAMETROS = {"fecha": "la fecha en formato AAAA-MM-DD, por ejemplo 2026-12-05"}


def ejecutar(fecha):
    try:
        objetivo = datetime.date.fromisoformat(str(fecha).strip())
    except ValueError:
        return "Necesito la fecha en formato AAAA-MM-DD."
    dias = (objetivo - datetime.date.today()).days
    if dias > 0:
        return f"Faltan {dias} días ({dias // 7} semanas y {dias % 7} días)."
    if dias == 0:
        return "Es hoy."
    return f"Esa fecha pasó hace {-dias} días."
