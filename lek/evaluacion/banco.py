"""Banco de pruebas de LUNA: 30 casos con respuesta verificable sin intervención humana.

Cada caso trae su verificador: una función que recibe la Salida del modelo (texto final y herramientas
llamadas) y devuelve (ok, motivo). Las respuestas de fechas se calculan aquí con datetime, no se escriben
a mano. Si cambias, agregas o quitas un caso, SUBE VERSION_BANCO: los resultados solo se comparan dentro
de la misma versión (si no, una "mejora" podría ser solo un banco más fácil).
"""
import datetime
import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

VERSION_BANCO = "2026.11.24-1"

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]


def plano(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar sin que una tilde cambie el resultado."""
    t = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower()


def dia_semana(fecha: datetime.date) -> str:
    return DIAS[fecha.weekday()]


# ---------------------------------------------------------------- lo que el modelo produjo
@dataclass
class Salida:
    texto: str = ""
    herramientas: list = field(default_factory=list)   # [(nombre, argumentos: dict)] en el orden en que llamó


# ---------------------------------------------------------------- verificadores
class Verificador:
    descripcion = ""

    def __call__(self, salida: Salida) -> tuple:
        raise NotImplementedError

    def __repr__(self):
        return f"<{self.descripcion}>"


_NUMERO = re.compile(r"\d{1,3}(?:[   ]\d{3})+(?!\d)(?:,\d+)?|\d+(?:[.,]\d+)*")


def _lecturas(token: str) -> set:
    """Todas las lecturas razonables de un número escrito en español o en inglés ("1.500", "3,2", "25 000")."""
    t = re.sub(r"[   ]", "", token)
    if "." in t and "," in t:  # el último separador es el decimal
        dec = "," if t.rfind(",") > t.rfind(".") else "."
        mil = "." if dec == "," else ","
        try:
            return {float(t.replace(mil, "").replace(dec, "."))}
        except ValueError:
            return set()
    for sep in (",", "."):
        if sep in t:
            partes = t.split(sep)
            lecturas = set()
            if all(len(p) == 3 for p in partes[1:]):
                lecturas.add(float("".join(partes)))            # separador de miles
            if len(partes) == 2:
                lecturas.add(float(partes[0] + "." + partes[1]))  # separador decimal
            return lecturas
    return {float(t)}


def numeros_en(texto: str) -> list:
    vistos = []
    for token in _NUMERO.findall(texto or ""):
        vistos.extend(sorted(_lecturas(token)))
    return vistos


class Numero(Verificador):
    """Algún número del texto coincide con alguno de los valores aceptados (p. ej. 6,4 cm o 64 mm)."""

    def __init__(self, *valores: float, tol_rel: float = 0.01, tol_abs: float = 0.0):
        self.valores, self.tol_rel, self.tol_abs = valores, tol_rel, tol_abs
        self.descripcion = "número ≈ " + " o ".join(f"{v:g}" for v in valores)

    def __call__(self, salida):
        encontrados = numeros_en(salida.texto)
        for v in self.valores:
            margen = max(self.tol_abs, self.tol_rel * abs(v))
            if any(abs(n - v) <= margen for n in encontrados):
                return True, "ok"
        return False, f"esperaba {' o '.join(f'{v:g}' for v in self.valores)}; encontré {encontrados[:6] or 'ningún número'}"


class Contiene(Verificador):
    """Cada grupo debe aparecer; dentro de un grupo, "a|b" acepta cualquiera. Sin tildes ni mayúsculas."""

    def __init__(self, *grupos: str):
        self.grupos = grupos
        self.descripcion = "contiene " + " + ".join(grupos)

    def __call__(self, salida):
        t = plano(salida.texto)
        faltan = [g for g in self.grupos if not any(plano(a) in t for a in g.split("|"))]
        return (False, "faltan: " + ", ".join(faltan)) if faltan else (True, "ok")


class NoContiene(Verificador):
    def __init__(self, *prohibidas: str):
        self.prohibidas = prohibidas
        self.descripcion = "no contiene " + ", ".join(prohibidas)

    def __call__(self, salida):
        t = plano(salida.texto)
        vistas = [p for p in self.prohibidas if plano(p) in t]
        return (False, "contiene lo prohibido: " + ", ".join(vistas)) if vistas else (True, "ok")


class Patron(Verificador):
    def __init__(self, regex: str):
        self.regex = re.compile(regex)
        self.descripcion = f"coincide con /{regex}/"

    def __call__(self, salida):
        return (True, "ok") if self.regex.search(plano(salida.texto)) else (False, f"no coincide con /{self.regex.pattern}/")


class Herramienta(Verificador):
    """Llamó a la herramienta esperada (y, si se pide, con argumentos que contienen ciertos textos)."""

    def __init__(self, herramienta: str, /, **argumentos_contienen: str):
        self.nombre, self.args = herramienta, argumentos_contienen
        self.descripcion = f"llama a {herramienta}" + (f" con {argumentos_contienen}" if argumentos_contienen else "")

    def __call__(self, salida):
        llamadas = [a for n, a in salida.herramientas if n == self.nombre]
        if not llamadas:
            return False, f"no llamó a {self.nombre} (llamó a: {[n for n, _ in salida.herramientas] or 'ninguna'})"
        for args in llamadas:
            args = args if isinstance(args, dict) else {}
            if all(plano(v) in plano(str(args.get(k, ""))) for k, v in self.args.items()):
                return True, "ok"
        return False, f"llamó a {self.nombre} con argumentos inesperados: {llamadas[0]}"


class LongitudMaxima(Verificador):
    def __init__(self, caracteres: int):
        self.caracteres = caracteres
        self.descripcion = f"máximo {caracteres} caracteres"

    def __call__(self, salida):
        n = len(salida.texto.strip())
        return (True, "ok") if n <= self.caracteres else (False, f"demasiado largo para voz: {n} > {self.caracteres} caracteres")


_MARKDOWN = re.compile(r"\*\*|__|`|^\s{0,3}#{1,6}\s|^\s*[-*•]\s|^\s*\d+[.)]\s|^\s*\|.*\|", re.M)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐✅]")


class SinMarkdown(Verificador):
    descripcion = "sin markdown, listas ni emojis"

    def __call__(self, salida):
        m = _MARKDOWN.search(salida.texto) or _EMOJI.search(salida.texto)
        return (False, f"formato no apto para voz: {m.group(0).strip()!r}") if m else (True, "ok")


class Todos(Verificador):
    def __init__(self, *verificadores: Verificador):
        self.verificadores = verificadores
        self.descripcion = " y ".join(v.descripcion for v in verificadores)

    def __call__(self, salida):
        for v in self.verificadores:
            ok, motivo = v(salida)
            if not ok:
                return False, motivo
        return True, "ok"


def voz(*otros: Verificador, maximo: int = 450) -> Todos:
    """Formato de voz de Luna: breve y sin markdown, más lo que se pida."""
    return Todos(*otros, LongitudMaxima(maximo), SinMarkdown())


NO_SABE = ("no tengo|no encuentro|no encontre|no se encontr|no hay|no se |no lo se|no recuerdo|no puedo saber|"
           "no cuento con|no aparece|ningun registro|ninguna conversacion|ningun dato|desconozco|no me has dicho|"
           "no me lo has dicho|no tengo registro|no tengo informacion|no consta")


# ---------------------------------------------------------------- herramientas falsas (mismos nombres que servidor.py)
def _f(nombre, descripcion, props=None, requeridos=None):
    return {"type": "function", "function": {
        "name": nombre, "description": descripcion,
        "parameters": {"type": "object", "properties": props or {}, "required": requeridos or []}}}


_txt = {"type": "string"}
HERRAMIENTAS_FALSAS = [
    _f("buscar_internet", "Busca en internet información actual (noticias, precios, clima, datos que no sabes).",
       {"consulta": _txt}, ["consulta"]),
    _f("buscar_documentos", "Busca en los documentos del usuario (carpeta conocimiento: apuntes, PDF, Word de la U).",
       {"consulta": _txt}, ["consulta"]),
    _f("buscar_conversaciones", "Busca en TODAS las conversaciones pasadas con el usuario (se guardan para siempre).",
       {"consulta": _txt}, ["consulta"]),
    _f("ver_memoria", "Muestra todo lo que recuerdas del usuario."),
    _f("guardar_nota", "Guarda una nota o pendiente del usuario.", {"texto": _txt}, ["texto"]),
    _f("abrir_programa", "Abre un programa en el PC del usuario (Revit, AutoCAD, Word, etc.).", {"nombre": _txt}, ["nombre"]),
    _f("recordar", "Guarda en tu memoria permanente un dato importante del usuario.", {"dato": _txt}, ["dato"]),
]
RESULTADO_POR_DEFECTO = {
    "buscar_internet": "Sin resultados.",
    "buscar_documentos": "No se encontró nada en los documentos.",
    "buscar_conversaciones": "No se encontraron conversaciones sobre eso.",
    "ver_memoria": "Recuerdos guardados: estudia arquitectura.",
    "guardar_nota": "Nota guardada.",
    "abrir_programa": "Programa abierto.",
    "recordar": "Guardado.",
}


# ---------------------------------------------------------------- casos
@dataclass
class Caso:
    id: str
    categoria: str
    pregunta: str
    verificador: Verificador
    esperado: str = ""                 # la respuesta correcta en palabras, para los informes
    herramientas: bool = False         # True: se le ofrecen HERRAMIENTAS_FALSAS
    resultados_herramientas: dict = field(default_factory=dict)  # nombre -> texto que devuelve la herramienta falsa


_D = datetime.date
_F1 = _D(2026, 12, 5)
_F2 = _D(2027, 1, 1)
_F3 = (_D(2026, 12, 5) - _D(2026, 11, 24)).days
_F4 = _D(2026, 11, 15) + datetime.timedelta(days=20)
_BISIESTO = (_D(2028, 3, 1) - _D(2028, 2, 1)).days == 29


def _dia(fecha):
    return Todos(Contiene(dia_semana(fecha)), NoContiene(*[d for d in DIAS if d != dia_semana(fecha)]))


CASOS = [
    # escalas de maqueta y plano
    Caso("esc-01", "escalas", "Tengo una maqueta a escala 1:50. Si una columna real mide 3,2 m, ¿cuánto mide en la maqueta?",
         Numero(6.4, 64, 0.064), "6,4 cm"),
    Caso("esc-02", "escalas", "Un edificio tiene 5 pisos de 2,8 m de altura cada uno. ¿Cuánto mide su altura total "
         "en una maqueta a escala 1:50?", Numero(28, 280, 0.28), "28 cm"),
    Caso("esc-03", "escalas", "Una fachada de 18 m de largo, ¿cuánto mide en un plano a escala 1:200?",
         Numero(9, 90, 0.09), "9 cm"),
    Caso("esc-04", "escalas", "En un plano a escala 1:100 mido 43 mm. ¿Cuánto mide eso en la realidad?",
         Numero(4.3, 430), "4,3 m"),
    Caso("esc-05", "escalas", "Una losa de 15 cm de espesor, ¿qué grosor tiene en una maqueta 1:50?",
         Numero(3, 0.3), "3 mm"),
    # conversiones de unidades
    Caso("con-01", "conversiones", "¿Cuántos centímetros cuadrados son 2,5 metros cuadrados?", Numero(25000), "25.000 cm²"),
    Caso("con-02", "conversiones", "¿Cuántos metros cuadrados tienen 3 hectáreas?", Numero(30000), "30.000 m²"),
    Caso("con-03", "conversiones", "Convierte 10 pulgadas a centímetros.", Numero(25.4), "25,4 cm"),
    # fechas (respuestas calculadas con datetime)
    Caso("fec-01", "fechas", "¿Qué día de la semana cae el 5 de diciembre de 2026?", _dia(_F1), dia_semana(_F1)),
    Caso("fec-02", "fechas", "¿Qué día de la semana es el 1 de enero de 2027?", _dia(_F2), dia_semana(_F2)),
    Caso("fec-03", "fechas", "¿Cuántos días hay del 24 de noviembre de 2026 al 5 de diciembre de 2026?",
         Numero(_F3, tol_rel=0), f"{_F3} días"),
    Caso("fec-04", "fechas", "Si hoy fuera 15 de noviembre de 2026, ¿qué fecha sería dentro de 20 días?",
         Patron(rf"\b{_F4.day} de {MESES[_F4.month - 1]}"), f"{_F4.day} de {MESES[_F4.month - 1]}"),
    # áreas y cuadros de áreas
    Caso("are-01", "areas", "¿Cuál es el área de una habitación de 3,5 m por 4 m?", Numero(14), "14 m²"),
    Caso("are-02", "areas", "Cuadro de áreas: sala 18 m², cocina 9,5 m², dos baños de 4,25 m² cada uno y una alcoba "
         "de 12 m². ¿Cuál es el área total?", Numero(48), "48 m²"),
    Caso("are-03", "areas", "Un lote de 20 m por 30 m tiene un índice de ocupación de 0,6. ¿Cuántos metros cuadrados "
         "puedo ocupar en primer piso?", Numero(360), "360 m²"),
    Caso("are-04", "areas", "¿Cuál es el área de un patio circular de 6 m de diámetro?",
         Numero(9 * math.pi, tol_rel=0.005), f"{9 * math.pi:.2f} m²"),
    # conocimiento estable de arquitectura: palabras clave obligatorias
    Caso("arq-01", "conocimiento", "¿Qué arquitecto diseñó la Villa Savoye?", Contiene("corbusier"), "Le Corbusier"),
    Caso("arq-02", "conocimiento", "¿Quién diseñó la Casa de la Cascada?", Contiene("wright"), "Frank Lloyd Wright"),
    Caso("arq-03", "conocimiento", "Nombra los cinco puntos de la arquitectura moderna de Le Corbusier.",
         Contiene("pilotis|pilote", "planta libre", "fachada libre", "ventana", "terraza|cubierta jardin|techo jardin"),
         "pilotis, planta libre, fachada libre, ventana longitudinal, terraza jardín"),
    Caso("arq-04", "conocimiento", "En el concreto reforzado, ¿qué esfuerzo resiste principalmente el acero?",
         Contiene("traccion|tension"), "tracción"),
    # uso correcto de herramientas
    Caso("her-01", "herramientas", "Abre Revit, por favor.", Herramienta("abrir_programa", nombre="revit"),
         "abrir_programa(Revit)", herramientas=True),
    Caso("her-02", "herramientas", "Guárdame una nota: comprar balso para la maqueta el viernes.",
         Herramienta("guardar_nota", texto="balso"), "guardar_nota", herramientas=True),
    Caso("her-03", "herramientas", "¿A cuánto está hoy el dólar en Colombia?", Herramienta("buscar_internet"),
         "buscar_internet", herramientas=True,
         resultados_herramientas={"buscar_internet": "Dato de prueba: el dólar está hoy a 4.000 pesos colombianos."}),
    Caso("her-04", "herramientas", "Busca en mis apuntes de la universidad qué dice sobre la NSR-10.",
         Herramienta("buscar_documentos"), "buscar_documentos", herramientas=True),
    # formato de voz: breve, sin markdown ni listas
    Caso("voz-01", "formato_voz", "Explícame qué es una planta arquitectónica.", voz(Contiene("corte|seccion|horizontal|desde arriba|vista superior")),
         "Corte horizontal, en 1 a 4 frases"),
    Caso("voz-02", "formato_voz", "Dame tres consejos para presentar bien una maqueta.", voz(),
         "Breve, sin listas"),
    Caso("voz-03", "formato_voz", "¿Qué es la NSR-10?", voz(Contiene("sism")), "Reglamento sismo resistente, breve"),
    # negarse a inventar
    Caso("inv-01", "no_inventar", "¿Qué te dije el 3 de enero de 2020?", voz(Contiene(NO_SABE)),
         "Reconoce que no lo sabe", herramientas=True,
         resultados_herramientas={"buscar_conversaciones": "No hay conversaciones del 3 de enero de 2020: "
                                                           "el registro empieza en 2026."}),
    Caso("inv-02", "no_inventar", "¿Qué nota saqué en el primer parcial de Taller 4?",
         voz(Contiene(NO_SABE), NoContiene("sacaste un", "tu nota fue", "obtuviste")), "Reconoce que no lo sabe",
         herramientas=True),
    Caso("inv-03", "no_inventar", "¿Cómo se llama mi perro?", voz(Contiene(NO_SABE)), "Reconoce que no lo sabe",
         herramientas=True),
]

CATEGORIAS = list(dict.fromkeys(c.categoria for c in CASOS))


def casos(categorias: list | None = None) -> list:
    return [c for c in CASOS if not categorias or c.categoria in categorias]
