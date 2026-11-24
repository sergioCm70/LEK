# Habilidad de ejemplo: medidas reales a escala de maqueta o plano
import re

DESCRIPCION = "Convierte una medida real a escala (maqueta o plano), o una medida a escala a tamaño real."
PARAMETROS = {
    "medida": "la medida con su unidad, por ejemplo '12 m', '350 cm' o '8.5 cm'",
    "escala": "la escala, por ejemplo '1:100' o '1:50'",
    "sentido": "'a_escala' (real -> maqueta) o 'a_real' (maqueta -> real). Por defecto a_escala",
}

A_MM = {"mm": 1, "cm": 10, "m": 1000, "km": 1_000_000}


def _texto(mm: float) -> str:
    if mm >= 1000:
        return f"{mm / 1000:.2f} m"
    if mm >= 10:
        return f"{mm / 10:.1f} cm"
    return f"{mm:.1f} mm"


def ejecutar(medida, escala, sentido="a_escala"):
    m = re.match(r"\s*([\d.,]+)\s*(mm|cm|m|km)?\s*$", str(medida).lower())
    e = re.match(r"\s*1\s*[:/]\s*([\d.,]+)\s*$", str(escala))
    if not m or not e:
        return "No entendí la medida o la escala. Ejemplo: medida '12 m', escala '1:100'."
    valor = float(m.group(1).replace(",", "."))
    mm = valor * A_MM[m.group(2) or "m"]
    factor = float(e.group(1).replace(",", "."))
    if str(sentido).startswith("a_real"):
        return f"{medida} a escala 1:{e.group(1)} equivale a {_texto(mm * factor)} en la realidad."
    return f"{medida} reales a escala 1:{e.group(1)} miden {_texto(mm / factor)} en la maqueta."
