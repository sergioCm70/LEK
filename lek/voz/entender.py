"""Entender mejor lo que Sergio dice por voz.

El reconocimiento de voz se equivoca sobre todo con nombres propios y palabras técnicas
("levit" por "Revit", "julián villa" bien, "lumión" por "Lumion"). Aquí vive:

- un vocabulario (el de base + las palabras que Luna aprende), que se le da a Whisper como pista
  y al cerebro como lista de nombres probables;
- correcciones aprendidas ("cuando oigas X, era Y"), que se aplican solas a lo dictado,
  solo como palabra completa y solo las que Sergio enseñó;
- la nota que acompaña a un mensaje dictado, para que el cerebro interprete la intención en vez
  de tomar la transcripción al pie de la letra.

Todo se guarda en datos/vocabulario.json, en el PC.
"""
from __future__ import annotations

import difflib
import json
import pathlib
import re
import threading
import unicodedata

VOCABULARIO_BASE = [
    "Luna", "LEK", "Sergio", "Revit", "AutoCAD", "SketchUp", "Lumion", "Enscape", "Twinmotion", "Rhino",
    "Grasshopper", "Photoshop", "Illustrator", "InDesign", "Blender", "D5 Render", "V-Ray", "QGIS",
    "Universidad Antonio Nariño", "UAN", "Taller 4", "Julian Villa", "Palmira", "Cali", "Valle del Cauca",
    "Las Delicias", "maqueta", "balso", "cartón paja", "MDF", "planta", "corte", "fachada", "alzado",
    "render", "escala", "lámina", "plancha", "isometría", "axonometría", "programa arquitectónico",
    "equipamiento", "resiliencia climática", "Tailscale", "Ollama", "Claude", "Haiku", "Opus", "Sonnet",
]


def _plano(t: str) -> str:
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


class Vocabulario:
    def __init__(self, carpeta: pathlib.Path):
        self.ruta = pathlib.Path(carpeta) / "vocabulario.json"
        self._candado = threading.Lock()

    # ---------------------------------------------------------------- datos
    def _leer(self) -> dict:
        try:
            d = json.loads(self.ruta.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return {"palabras": list(d.get("palabras", [])), "correcciones": dict(d.get("correcciones", {}))}
        except Exception:
            pass
        return {"palabras": [], "correcciones": {}}

    def _guardar(self, d: dict) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.ruta)

    def palabras(self) -> list:
        vistas, salida = set(), []
        for p in self._leer()["palabras"] + VOCABULARIO_BASE:
            k = _plano(p)
            if p and k not in vistas:
                vistas.add(k)
                salida.append(p)
        return salida

    def correcciones(self) -> dict:
        return self._leer()["correcciones"]

    # ---------------------------------------------------------------- aprender
    def aprender_palabra(self, palabra: str) -> str:
        palabra = " ".join(str(palabra or "").split())[:60]
        if not palabra:
            return "No me dijiste qué palabra aprender."
        with self._candado:
            d = self._leer()
            if _plano(palabra) in {_plano(p) for p in d["palabras"]}:
                return f"Ya conocía «{palabra}»."
            d["palabras"].insert(0, palabra)
            d["palabras"] = d["palabras"][:300]
            self._guardar(d)
        return f"Aprendí la palabra «{palabra}»: la reconoceré mejor cuando me hables."

    def aprender_correccion(self, oido: str, correcto: str) -> str:
        oido, correcto = " ".join(str(oido or "").split())[:60], " ".join(str(correcto or "").split())[:60]
        if not oido or not correcto or _plano(oido) == _plano(correcto):
            return "Necesito lo que entendí mal y lo que en realidad dijiste."
        if len(_plano(oido)) < 3:
            return "Esa palabra es muy corta para corregirla sola: podría dañar otras frases."
        with self._candado:
            d = self._leer()
            d["correcciones"][_plano(oido)] = correcto
            if _plano(correcto) not in {_plano(p) for p in d["palabras"]}:
                d["palabras"].insert(0, correcto)
            self._guardar(d)
        return f"Entendido: cuando oiga «{oido}» sabré que dijiste «{correcto}»."

    # ---------------------------------------------------------------- usar
    def aplicar(self, texto: str) -> str:
        """Aplica SOLO las correcciones que Sergio enseñó, como palabra o frase completa."""
        salida = unicodedata.normalize("NFC", texto or "")
        for oido, correcto in sorted(self.correcciones().items(), key=lambda x: -len(x[0])):
            patron = r"(?<!\w)" + r"\s+".join(re.escape(w) for w in oido.split()) + r"(?!\w)"
            # se compara sin tildes: se busca sobre una versión plana y se reemplaza en la original
            plano = _plano(salida)
            partes, i = [], 0
            for m in re.finditer(patron, plano):
                partes.append(salida[i:m.start()])
                partes.append(correcto)
                i = m.end()
            if partes:
                salida = "".join(partes) + salida[i:]
        return salida

    def parecidas(self, texto: str, limite: int = 6) -> list:
        """Palabras del vocabulario que se parecen a lo dictado (pistas, no reemplazos)."""
        voc = self.palabras()
        planos = {_plano(p): p for p in voc}
        tokens = re.findall(r"[\wáéíóúñü]+", _plano(texto))
        candidatos = set(tokens) | {f"{a} {b}" for a, b in zip(tokens, tokens[1:])}
        hallados = []
        for c in candidatos:
            if len(c) < 4 or c in planos:
                continue
            for m in difflib.get_close_matches(c, planos, n=1, cutoff=0.78):
                if planos[m] not in hallados:
                    hallados.append(planos[m])
        return hallados[:limite]

    def pista_whisper(self, maximo: int = 600) -> str:
        """Texto inicial para Whisper: le enseña cómo se escriben los nombres que usas."""
        texto = "Conversación con Luna, la asistente de Sergio, estudiante de arquitectura en Palmira. "
        for p in self.palabras():
            if len(texto) + len(p) + 2 > maximo:
                break
            texto += p + ", "
        return texto.rstrip(", ") + "."

    def nota(self, texto: str, alternativas=None) -> str:
        """Nota para el cerebro cuando el mensaje llegó por voz."""
        partes = [" El usuario HABLÓ (no escribió): la transcripción automática puede traer palabras "
                  "parecidas mal oídas, nombres mal escritos, números en letras o frases cortadas. "
                  "Interpreta lo que quiso decir según el contexto de la conversación, no al pie de la letra. "
                  "Si algo importante queda ambiguo (un nombre, una cifra, una acción que cambia algo), "
                  "confírmalo en pocas palabras antes de actuar. Si te corrige una palabra mal oída, usa "
                  "corregir_oido para no repetir el error."]
        otras = [a for a in (alternativas or []) if a and a.strip().lower() != texto.strip().lower()][:3]
        if otras:
            partes.append(" Otras formas en que se pudo oír: " + " | ".join(f"«{a.strip()}»" for a in otras) + ".")
        pistas = self.parecidas(" ".join([texto, *otras]))
        if pistas:
            partes.append(" Nombres conocidos que suenan parecido a algo de lo dicho: " + ", ".join(pistas) + ".")
        return "".join(partes)


def herramientas(vocabulario: Vocabulario):
    def _f(nombre, descripcion, propiedades, requeridos):
        return {"type": "function", "function": {
            "name": nombre, "description": descripcion,
            "parameters": {"type": "object", "properties": propiedades, "required": requeridos}}}

    definiciones = [
        _f("corregir_oido",
           "Cuando el usuario te corrige una palabra que entendiste mal al escucharlo (por ejemplo «no dije "
           "levit, dije Revit»), guarda la corrección para que no se repita.",
           {"oido": {"type": "string", "description": "lo que se transcribió mal"},
            "correcto": {"type": "string", "description": "lo que en realidad dijo"}}, ["oido", "correcto"]),
        _f("aprender_palabra",
           "Aprende un nombre propio o palabra técnica que el usuario usa (un profesor, un programa, un lugar) "
           "para reconocerlo mejor cuando hable.",
           {"palabra": {"type": "string", "description": "la palabra tal como se escribe"}}, ["palabra"]),
    ]
    funciones = {
        "corregir_oido": lambda oido="", correcto="", **_: vocabulario.aprender_correccion(oido, correcto),
        "aprender_palabra": lambda palabra="", **_: vocabulario.aprender_palabra(palabra),
    }
    return definiciones, funciones
