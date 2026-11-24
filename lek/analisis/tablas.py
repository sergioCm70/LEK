"""Tablas (CSV / XLSX) y calculadora segura para LUNA.

Todo es determinista: lee, cuenta y suma con Decimal (sin errores de coma flotante en las sumas),
para que Luna no tenga que hacer aritmética de memoria.

- leer_hojas(ruta): filas crudas de cada hoja (CSV = una hoja). XLSX con openpyxl si está instalado;
  si no, se lee el ZIP de XML con zipfile + xml.etree.
- estructurar(filas): detecta la fila de encabezados y separa los datos.
- perfil_columnas(...): tipo de cada columna y estadísticas de las numéricas.
- calcular_tabla(...): sumar / contar / promedio / mínimo / máximo / listar, con filtro y agrupación.
- evaluar(expresion): calculadora con ast (sin eval).
"""
from __future__ import annotations

import ast
import csv
import io
import math
import operator
import pathlib
import re
import time
import unicodedata
import zipfile
from decimal import Decimal, InvalidOperation, localcontext
from xml.etree import ElementTree as ET

MAX_FILAS = 200_000
MAX_COLUMNAS = 200
MAX_XML_DESCOMPRIMIDO = 400 * 1024 * 1024   # defensa ante "bombas zip" dentro de un XLSX
LIMITE_INFORME = 2500


class ErrorAnalisis(Exception):
    """Error con mensaje en español pensado para que Luna se lo diga al usuario."""


class Plazo:
    """Límite de tiempo cooperativo: los bucles largos llaman a comprobar()."""

    def __init__(self, segundos: float = 20.0):
        self.fin = time.monotonic() + segundos
        self.segundos = segundos

    def comprobar(self):
        if time.monotonic() > self.fin:
            raise ErrorAnalisis(f"El análisis superó el límite de {self.segundos:g} segundos; el archivo es demasiado grande.")


# ---------------------------------------------------------------- utilidades de texto y números
def norm(texto) -> str:
    """minúsculas, sin tildes, '²' -> '2', espacios simples."""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().lower()


def recortar(texto: str, limite: int = LIMITE_INFORME) -> str:
    if len(texto) <= limite:
        return texto
    aviso = "\n[…informe recortado]"
    return texto[: limite - len(aviso)].rstrip() + aviso


def fmt(n) -> str:
    """Número exacto y legible, con punto decimal y sin separador de miles (lo entiende evaluar())."""
    if n is None:
        return "—"
    if isinstance(n, float):
        if math.isnan(n) or math.isinf(n):
            return str(n)
        n = Decimal(repr(n))
    if isinstance(n, int):
        return str(n)
    try:
        if n == n.to_integral_value():
            return str(n.quantize(Decimal(1)))
        if abs(n.as_tuple().exponent) > 4:
            n = n.quantize(Decimal("0.0001"))
        return format(n.normalize(), "f")
    except InvalidOperation:
        return format(n, "f")


_UNIDADES = re.compile(r"(m2|m²|m3|m³|ml|mts?|cm|mm|km|ha|kg|un|und|\$|cop|usd|%)", re.I)


_COMA_MILES = re.compile(r"\d\.\d{3},\d")
_COMA_DEC = re.compile(r"[-+]?\d+,\d{1,2}|[-+]?\d+,\d{4,}")
_PUNTO_MILES = re.compile(r"\d,\d{3}\.\d")
_PUNTO_DEC = re.compile(r"[-+]?\d+\.\d{1,2}|[-+]?\d+\.\d{4,}")
_SIMPLE = re.compile(r"-?\d+(\.\d+)?")
_FORMA_NUMERO = re.compile(r"[-+]?[\d.,]*\d[\d.,]*([eE][-+]?\d+)?")
_MILES_COMA = re.compile(r"[-+]?\d{1,3}(,\d{3})+")
_MILES_PUNTO = re.compile(r"[-+]?\d{1,3}(\.\d{3})+")


def estilo_decimal(valores) -> str:
    """'coma' si la columna usa coma decimal (12,5 / 1.234,5), 'punto' si usa punto (1,234.5), '' si no se sabe."""
    coma = punto = 0
    for v in valores:
        s = str(v).strip()
        if "," in s and (_COMA_MILES.search(s) or _COMA_DEC.fullmatch(s)):
            coma += 1
        elif "." in s and (_PUNTO_MILES.search(s) or _PUNTO_DEC.fullmatch(s)):
            punto += 1
    if coma > punto:
        return "coma"
    if punto > coma:
        return "punto"
    return ""


def a_numero(valor, estilo: str = "") -> Decimal | None:
    """Convierte '1.234,56', '12,5 m²', '$ 3.000', '1,234.5', 7, 2.5 a Decimal. None si no es número."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return Decimal(valor)
    if isinstance(valor, float):
        return None if (math.isnan(valor) or math.isinf(valor)) else Decimal(repr(valor))
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, str) and _SIMPLE.fullmatch(valor):      # camino rápido: "12" / "12.5"
        if "." not in valor or estilo != "coma" or not _MILES_PUNTO.fullmatch(valor):
            return Decimal(valor)
    s = str(valor).strip().replace(" ", "").replace(" ", "").replace("−", "-")
    if not s:
        return None
    s = _UNIDADES.sub("", s)
    negativo = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if not _FORMA_NUMERO.fullmatch(s):
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")        # 1.234,56
        else:
            s = s.replace(",", "")                          # 1,234.56
    elif "," in s:
        if s.count(",") > 1 or (estilo == "punto" and _MILES_COMA.fullmatch(s)):
            s = s.replace(",", "")                          # 1,234,567 (miles)
        else:
            s = s.replace(",", ".")                         # 12,5 (decimal)
    elif "." in s:
        if s.count(".") > 1 or (estilo == "coma" and _MILES_PUNTO.fullmatch(s)):
            s = s.replace(".", "")                          # 1.234.567 (miles)
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if not d.is_finite():
        return None
    return -d if negativo else d


_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}")
_TOTAL = re.compile(r"^(sub ?)?total(es)?\b")


def es_fila_total(fila) -> bool:
    if not any("otal" in str(c) or "OTAL" in str(c) for c in fila):
        return False
    return any(_TOTAL.match(norm(c)) for c in fila if c not in (None, "") and a_numero(c) is None)


# ---------------------------------------------------------------- lectura de CSV
def _decodificar(datos: bytes) -> str:
    for cod in ("utf-8-sig", "cp1252"):
        try:
            return datos.decode(cod)
        except UnicodeDecodeError:
            continue
    return datos.decode("latin-1")


def _delimitador(texto: str) -> str:
    lineas = [l for l in texto.splitlines()[:30] if l.strip()]
    mejor, puntos = ",", (-1, -1)
    for d in (";", ",", "\t", "|"):
        cuentas = [l.count(d) for l in lineas]
        if not cuentas or max(cuentas) == 0:
            continue
        moda = max(set(cuentas), key=cuentas.count)
        p = (sum(1 for c in cuentas if c == moda and c > 0), moda)
        if p > puntos:
            mejor, puntos = d, p
    return mejor


def leer_csv(ruta, plazo: Plazo | None = None) -> list:
    texto = _decodificar(pathlib.Path(ruta).read_bytes())
    filas = []
    for i, fila in enumerate(csv.reader(io.StringIO(texto), delimiter=_delimitador(texto))):
        if i >= MAX_FILAS:
            break
        if plazo and i % 5000 == 0:
            plazo.comprobar()
        filas.append([c.strip() for c in fila[:MAX_COLUMNAS]])
    return filas


# ---------------------------------------------------------------- lectura de XLSX
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _columna_indice(ref: str) -> int:
    letras = re.match(r"[A-Za-z]+", ref or "")
    if not letras:
        return -1
    n = 0
    for c in letras.group(0).upper():
        n = n * 26 + ord(c) - 64
    return n - 1


def _abrir_miembro(zf: zipfile.ZipFile, nombre: str):
    info = zf.getinfo(nombre)
    if info.file_size > MAX_XML_DESCOMPRIMIDO:
        raise ErrorAnalisis(f"La hoja '{nombre}' descomprimida pesa demasiado para analizarla.")
    return zf.open(info)


def _xlsx_zip(ruta, plazo: Plazo | None = None) -> list:
    """Lee un XLSX sin openpyxl: devuelve [(nombre_hoja, filas)]. Usa el valor guardado de las fórmulas."""
    try:
        zf = zipfile.ZipFile(ruta)
    except zipfile.BadZipFile:
        raise ErrorAnalisis("El XLSX está dañado o no es un libro de Excel moderno (¿es un .xls antiguo?).")
    with zf:
        nombres = set(zf.namelist())
        compartidas = []
        if "xl/sharedStrings.xml" in nombres:
            with _abrir_miembro(zf, "xl/sharedStrings.xml") as fh:
                for _, el in ET.iterparse(fh):
                    if _local(el.tag) == "si":
                        compartidas.append("".join(t.text or "" for t in el.iter() if _local(t.tag) == "t"))
                        el.clear()
        rels = {}
        if "xl/_rels/workbook.xml.rels" in nombres:
            with _abrir_miembro(zf, "xl/_rels/workbook.xml.rels") as fh:
                raiz_rels = ET.parse(fh).getroot()
            for el in raiz_rels:
                destino = el.get("Target", "")
                destino = destino.lstrip("/") if destino.startswith("/") else "xl/" + destino
                rels[el.get("Id")] = destino
        hojas = []
        if "xl/workbook.xml" in nombres:
            with _abrir_miembro(zf, "xl/workbook.xml") as fh:
                raiz_libro = ET.parse(fh).getroot()
            for el in raiz_libro.iter():
                if _local(el.tag) == "sheet":
                    rid = next((v for k, v in el.attrib.items() if _local(k) == "id"), None)
                    hojas.append((el.get("name", f"Hoja{len(hojas) + 1}"), rels.get(rid)))
        if not hojas or not all(r in nombres for _, r in hojas):
            hojas = [(f"Hoja{i + 1}", n) for i, n in enumerate(sorted(
                n for n in nombres if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)))]
        resultado = []
        for nombre_hoja, miembro in hojas:
            with _abrir_miembro(zf, miembro) as fh:
                filas = _filas_hoja(fh, compartidas, plazo)
            resultado.append((nombre_hoja, filas))
        return resultado


def _filas_hoja(fh, compartidas: list, plazo: Plazo | None) -> list:
    filas = []
    for _, el in ET.iterparse(fh):
        if _local(el.tag) != "row":
            continue
        if len(filas) >= MAX_FILAS:
            break
        if plazo and len(filas) % 5000 == 0:
            plazo.comprobar()
        num_fila = int(el.get("r", len(filas) + 1))
        if num_fila > MAX_FILAS:                          # filas lejanas (formato hasta la 1048576)
            break
        while len(filas) < num_fila - 1:                 # filas vacías intermedias
            filas.append([])
        fila = []
        for c in el:
            if _local(c.tag) != "c":
                continue
            i = _columna_indice(c.get("r", "")) if c.get("r") else len(fila)
            if i < 0 or i >= MAX_COLUMNAS:
                continue
            tipo, valor = c.get("t", "n"), None
            v = next((x for x in c if _local(x.tag) == "v"), None)
            if tipo == "inlineStr":
                valor = "".join(t.text or "" for t in c.iter() if _local(t.tag) == "t")
            elif v is not None and v.text is not None:
                if tipo == "s":
                    k = int(v.text)
                    valor = compartidas[k] if 0 <= k < len(compartidas) else ""
                elif tipo == "b":
                    valor = "VERDADERO" if v.text == "1" else "FALSO"
                else:
                    valor = v.text
            while len(fila) < i:
                fila.append("")
            if len(fila) == i:
                fila.append("" if valor is None else str(valor).strip())
        filas.append(fila)
        el.clear()
    return filas


def _xlsx_openpyxl(ruta, plazo: Plazo | None = None) -> list:
    import openpyxl
    libro = openpyxl.load_workbook(str(ruta), read_only=True, data_only=True)
    try:
        resultado = []
        for hoja in libro.worksheets:
            filas = []
            for fila in hoja.iter_rows(values_only=True, max_col=MAX_COLUMNAS):
                if len(filas) >= MAX_FILAS:
                    break
                if plazo and len(filas) % 5000 == 0:
                    plazo.comprobar()
                celdas = []
                for v in fila:
                    if v is None:
                        celdas.append("")
                    elif isinstance(v, float):
                        celdas.append(repr(v))
                    elif hasattr(v, "isoformat"):
                        celdas.append(v.isoformat(sep=" ") if hasattr(v, "hour") else v.isoformat())
                    else:
                        celdas.append(str(v).strip())
                filas.append(celdas)
            resultado.append((hoja.title, filas))
        return resultado
    finally:
        libro.close()


def leer_hojas(ruta, plazo: Plazo | None = None, usar_openpyxl: bool = True) -> list:
    """[(nombre_hoja, filas)] de un CSV/TSV o XLSX/XLSM."""
    ext = str(ruta).lower().rsplit(".", 1)[-1]
    if ext in ("csv", "tsv"):
        return [("CSV", leer_csv(ruta, plazo))]
    if ext in ("xlsx", "xlsm"):
        if usar_openpyxl:
            try:
                return _xlsx_openpyxl(ruta, plazo)
            except ImportError:
                pass
            except ErrorAnalisis:
                raise
            except Exception:
                pass                       # si openpyxl no puede, se intenta con el lector propio
        return _xlsx_zip(ruta, plazo)
    if ext == "xls":
        raise ErrorAnalisis("Los .xls antiguos no se pueden leer; guárdalo como .xlsx o .csv desde Excel.")
    raise ErrorAnalisis("No es una tabla (uso CSV, TSV, XLSX o XLSM).")


# ---------------------------------------------------------------- estructura y perfil
def _es_texto(c) -> bool:
    return c not in (None, "") and a_numero(c) is None and not _FECHA.fullmatch(str(c))


def estructurar(filas: list) -> dict:
    """Detecta la fila de encabezados (los cuadros de áreas suelen tener títulos encima)."""
    filas = [list(f) for f in filas]
    llenas = [sum(1 for c in f if c not in (None, "")) for f in filas[:30]]
    ancho = max(llenas, default=0)
    idx = None
    for i, f in enumerate(filas[:15]):
        n = llenas[i]
        if n >= max(2, math.ceil(ancho * 0.6)) and all(_es_texto(c) for c in f if c not in (None, "")):
            idx = i
            break
    if idx is None:
        idx = next((i for i, n in enumerate(llenas) if n), 0)
    encabezado = filas[idx] if filas else []
    datos = [f for f in filas[idx + 1:] if any(c not in (None, "") for c in f)]
    ncol = max([len(encabezado)] + [len(f) for f in datos]) if filas else 0
    nombres, vistos = [], {}
    for j in range(ncol):
        base = str(encabezado[j]).strip() if j < len(encabezado) and encabezado[j] not in (None, "") else f"Columna {j + 1}"
        vistos[base] = vistos.get(base, 0) + 1
        nombres.append(base if vistos[base] == 1 else f"{base} ({vistos[base]})")
    datos = [f + [""] * (ncol - len(f)) for f in datos]
    marcas = [es_fila_total(f) for f in datos]
    totales = [f for f, m in zip(datos, marcas) if m]
    datos = [f for f, m in zip(datos, marcas) if not m]
    return {"encabezados": nombres, "datos": datos, "totales": totales, "fila_encabezado": idx + 1}


def perfil_columna(valores: list) -> dict:
    no_vacios = [v for v in valores if v not in (None, "")]
    estilo = estilo_decimal(no_vacios)
    nums = [n for n in (a_numero(v, estilo) for v in no_vacios) if n is not None]
    p = {"no_vacios": len(no_vacios), "vacios": len(valores) - len(no_vacios), "estilo": estilo}
    if not no_vacios:
        p["tipo"] = "vacía"
    elif len(nums) >= 0.8 * len(no_vacios):
        p["tipo"] = "número"
        with localcontext() as ctx:
            ctx.prec = 40
            suma = sum(nums, Decimal(0))
            p.update(numeros=len(nums), no_numericos=len(no_vacios) - len(nums), suma=suma,
                     media=suma / len(nums), minimo=min(nums), maximo=max(nums))
    elif sum(1 for v in no_vacios if _FECHA.fullmatch(str(v))) >= 0.8 * len(no_vacios):
        p["tipo"] = "fecha"
        p.update(desde=min(map(str, no_vacios)), hasta=max(map(str, no_vacios)))
    else:
        p["tipo"] = "texto"
        distintos = list(dict.fromkeys(str(v) for v in no_vacios))
        p.update(distintos=len(distintos), ejemplos=distintos[:4])
    return p


def describir_tabla(nombre: str, filas: list, limite_columnas: int = 25) -> str:
    t = estructurar(filas)
    enc, datos = t["encabezados"], t["datos"]
    lineas = [f"[{nombre}] {len(datos)} filas de datos × {len(enc)} columnas (encabezados en la fila {t['fila_encabezado']})"]
    for j, col in enumerate(enc[:limite_columnas]):
        p = perfil_columna([f[j] for f in datos])
        if p["tipo"] == "número":
            extra = f" ({p['no_numericos']} no numéricos)" if p["no_numericos"] else ""
            lineas.append(f" - {col}: número; {p['numeros']} valores{extra}; suma {fmt(p['suma'])}, media {fmt(p['media'])}, "
                          f"mín {fmt(p['minimo'])}, máx {fmt(p['maximo'])}")
        elif p["tipo"] == "texto":
            lineas.append(f" - {col}: texto; {p['distintos']} distintos (" + ", ".join(e[:30] for e in p["ejemplos"]) + ")")
        elif p["tipo"] == "fecha":
            lineas.append(f" - {col}: fecha; {p['desde']} a {p['hasta']}")
        else:
            lineas.append(f" - {col}: vacía")
    if len(enc) > limite_columnas:
        lineas.append(f" (+{len(enc) - limite_columnas} columnas más)")
    for f in t["totales"][:3]:
        lineas.append(" Fila de total del archivo (excluida de las estadísticas): " +
                      " | ".join(str(c) for c in f if c not in (None, ""))[:200])
    return "\n".join(lineas)


# ---------------------------------------------------------------- calcular_tabla
def buscar_columna(nombre: str, encabezados: list) -> int:
    n = norm(nombre).strip("'\"")
    if not n:
        raise ErrorAnalisis("Falta el nombre de la columna. Columnas: " + ", ".join(encabezados))
    normas = [norm(e) for e in encabezados]
    if n in normas:
        return normas.index(n)
    sin_signos = [re.sub(r"[^a-z0-9 ]", " ", e).split() for e in normas]
    palabras_n = re.sub(r"[^a-z0-9 ]", " ", n).split()
    candidatas = [j for j, ps in enumerate(sin_signos) if palabras_n and ps[:len(palabras_n)] == palabras_n]
    if not candidatas:
        candidatas = [j for j, ps in enumerate(sin_signos) if palabras_n and all(p in ps for p in palabras_n)]
    if not candidatas:
        candidatas = [j for j, e in enumerate(normas) if n in e]
    if len(candidatas) == 1:
        return candidatas[0]
    if re.fullmatch(r"[a-z]{1,2}", n) and 0 <= _columna_indice(n) < len(encabezados):
        return _columna_indice(n)                      # letra de Excel: "C"
    if len(candidatas) > 1:
        raise ErrorAnalisis(f"'{nombre}' coincide con varias columnas: " + ", ".join(encabezados[j] for j in candidatas))
    raise ErrorAnalisis(f"No hay una columna '{nombre}'. Columnas: " + ", ".join(encabezados))


_OP_SIMBOLO = re.compile(r"^(.+?)\s*(>=|<=|!=|<>|==|=|>|<)\s*(.+)$")
_OP_PALABRA = re.compile(r"^(.+?)\s+(no contiene|contiene|empieza por|empieza con|es distinto de|es igual a|es)\s+(.+)$", re.I)


def _condiciones(filtro: str, encabezados: list) -> list:
    conds = []
    for parte in re.split(r"\s+y\s+|\s+and\s+|;|&&", filtro.strip(), flags=re.I):
        parte = parte.strip()
        if not parte:
            continue
        m = _OP_SIMBOLO.match(parte) or _OP_PALABRA.match(parte)
        if not m:
            raise ErrorAnalisis(f"No entendí el filtro '{parte}'. Usa por ejemplo: Piso = 2 y Uso contiene vivienda")
        col, op, val = m.group(1).strip(), m.group(2).lower(), m.group(3).strip().strip("'\"")
        op = {"==": "=", "<>": "!=", "es": "=", "es igual a": "=", "es distinto de": "!=",
              "empieza con": "empieza por"}.get(op, op)
        conds.append((buscar_columna(col, encabezados), op, val))
    return conds


def _cumple(fila: list, conds: list) -> bool:
    for j, op, val in conds:
        celda = fila[j] if j < len(fila) else ""
        a, b = a_numero(celda), a_numero(val)
        if op in ("contiene", "no contiene", "empieza por") or a is None or b is None:
            x, y = norm(celda), norm(val)
            ok = {"=": x == y, "!=": x != y, "contiene": y in x, "no contiene": y not in x,
                  "empieza por": x.startswith(y), ">": x > y, "<": x < y, ">=": x >= y, "<=": x <= y}[op]
        else:
            ok = {"=": a == b, "!=": a != b, ">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]
        if not ok:
            return False
    return True


_VERBOS = [
    ("sumar", r"sum\w*|total\w*"),
    ("contar", r"cont\w*|cuent\w*|cuantos|cuantas|numero de filas"),
    ("promedio", r"promedi\w*|media"),
    ("minimo", r"minim\w*|min|menor"),
    ("maximo", r"maxim\w*|max|mayor"),
    ("listar", r"list\w*|mostr\w*|ver|filas"),
    ("columnas", r"columnas|encabezados|estructura"),
]


def interpretar_operacion(texto: str) -> dict:
    """'suma el área por piso donde uso = vivienda' -> {operacion, columna, agrupar_por, filtro}."""
    t = norm(texto)
    r = {"operacion": "", "columna": "", "agrupar_por": "", "filtro": ""}
    m = re.search(r"\s(?:donde|cuando|si|con filtro|filtrando)\s(.+)$", " " + t)
    if m:
        r["filtro"] = m.group(1).strip()
        t = (" " + t)[: m.start()].strip()
    for nombre, patron in _VERBOS:
        mv = re.match(rf"(?:{patron})\b", t)
        if mv:
            r["operacion"] = nombre
            t = t[mv.end():].strip()
            break
    m = re.search(r"(?:^|\s)(?:agrupad[oa]s? )?por\s+(.+)$", t)
    if m:
        r["agrupar_por"] = re.sub(r"^(cada|el|la|los|las)\s+", "", m.group(1).strip())
        t = t[: m.start()].strip()
    t = re.sub(r"^((de|del|el|la|los|las|columna|valores|filas)\s+)+", "", t).strip()
    r["columna"] = t
    return r


def calcular_tabla(ruta, operacion: str, columna: str = "", agrupar_por: str = "", filtro: str = "",
                   hoja: str = "", plazo: Plazo | None = None, usar_openpyxl: bool = True) -> str:
    plazo = plazo or Plazo()
    pedido = interpretar_operacion(operacion or "")
    op = pedido["operacion"] or ("sumar" if columna else "")
    if not op:
        op = next((n for n, p in _VERBOS if re.fullmatch(p, norm(operacion or ""))), "")
    if not op:
        raise ErrorAnalisis("Operación no reconocida. Usa: sumar, contar, promedio, minimo, maximo, listar o columnas "
                            "(ej.: 'sumar Área por Piso donde Uso = vivienda').")
    columna = columna or pedido["columna"]
    agrupar_por = agrupar_por or pedido["agrupar_por"]
    filtro = filtro or pedido["filtro"]

    hojas = leer_hojas(ruta, plazo, usar_openpyxl)
    if hoja:
        elegidas = [h for h in hojas if norm(h[0]) == norm(hoja)] or [h for h in hojas if norm(hoja) in norm(h[0])]
        if not elegidas:
            raise ErrorAnalisis(f"No hay hoja '{hoja}'. Hojas: " + ", ".join(h[0] for h in hojas))
        nombre_hoja, filas = elegidas[0]
    else:
        nombre_hoja, filas = next(((n, f) for n, f in hojas if any(any(c for c in x) for x in f)), hojas[0])
    t = estructurar(filas)
    enc, datos = t["encabezados"], t["datos"]
    otras = f" (el libro tiene {len(hojas)} hojas; usa 'hoja' para elegir otra)" if len(hojas) > 1 and not hoja else ""
    cabeza = f"Hoja '{nombre_hoja}'{otras}. "

    if op == "columnas":
        return recortar(cabeza + f"{len(datos)} filas. Columnas: " + ", ".join(enc))

    conds = _condiciones(filtro, enc) if filtro else []
    usadas = [f for f in datos if _cumple(f, conds)]
    texto_filtro = f" con filtro «{filtro}»" if filtro else ""
    cabeza += f"{len(usadas)} de {len(datos)} filas{texto_filtro}"
    if t["totales"]:
        cabeza += f"; excluí {len(t['totales'])} fila(s) de TOTAL del archivo"
    cabeza += ".\n"

    if op == "listar":
        cols = [buscar_columna(c, enc) for c in re.split(r",| y ", columna) if c.strip()] if columna else range(len(enc))
        lineas = [" | ".join(f"{enc[j]}: {f[j]}" for j in cols if f[j] not in (None, "")) for f in usadas[:25]]
        mas = f"\n(+{len(usadas) - 25} filas más)" if len(usadas) > 25 else ""
        return recortar(cabeza + "\n".join(lineas) + mas)

    jg = buscar_columna(agrupar_por, enc) if agrupar_por else None
    jc = buscar_columna(columna, enc) if columna else None
    if op != "contar" and jc is None:
        raise ErrorAnalisis(f"Falta la columna para '{op}'. Columnas: " + ", ".join(enc))

    estilo = estilo_decimal([f[jc] for f in datos]) if jc is not None else ""
    grupos: dict = {}
    sin_numero = 0
    for f in usadas:
        clave = f[jg] if jg is not None else None
        g = grupos.setdefault(clave, [])
        if jc is None:
            g.append(Decimal(1))
            continue
        if op == "contar":
            if f[jc] not in (None, ""):
                g.append(Decimal(1))
            continue
        n = a_numero(f[jc], estilo)
        if n is None:
            if f[jc] not in (None, ""):
                sin_numero += 1
            continue
        g.append(n)

    def resumen(vals):
        if op == "contar":
            return Decimal(len(vals))
        if not vals:
            return None
        with localcontext() as ctx:
            ctx.prec = 40
            return {"sumar": lambda: sum(vals, Decimal(0)), "promedio": lambda: sum(vals, Decimal(0)) / len(vals),
                    "minimo": lambda: min(vals), "maximo": lambda: max(vals)}[op]()

    nombre_op = {"sumar": "Suma", "contar": "Conteo", "promedio": "Promedio", "minimo": "Mínimo", "maximo": "Máximo"}[op]
    objeto = f" de '{enc[jc]}'" if jc is not None else " de filas"
    salida = cabeza
    todos = [v for g in grupos.values() for v in g]
    if jg is not None:
        def orden(k):
            n = a_numero(k)
            return (0, n, "") if n is not None else (1, Decimal(0), norm(k))
        claves = sorted(grupos, key=orden)
        salida += f"{nombre_op}{objeto} por '{enc[jg]}' ({len(claves)} grupos):\n"
        for k in claves[:60]:
            n_vals = "" if op == "contar" else f" ({len(grupos[k])} valores)"
            salida += f" - {k if k not in (None, '') else '(vacío)'}: {fmt(resumen(grupos[k]))}{n_vals}\n"
        if len(claves) > 60:
            salida += f" (+{len(claves) - 60} grupos más)\n"
        salida += f"General: {fmt(resumen(todos))}"
    else:
        salida += f"{nombre_op}{objeto}: {fmt(resumen(todos))} ({len(todos)} valores)"
    if sin_numero:
        salida += f"\nOjo: {sin_numero} celda(s) de esa columna no son números y no se contaron."
    if op == "sumar" and jc is not None and t["totales"] and not conds:
        declarado = next((a_numero(f[jc], estilo) for f in t["totales"] if a_numero(f[jc], estilo) is not None), None)
        if declarado is not None and jg is None:
            calc = resumen(todos) or Decimal(0)
            veredicto = "coincide" if calc == declarado else f"NO coincide (diferencia {fmt(calc - declarado)})"
            salida += f"\nLa fila TOTAL del archivo dice {fmt(declarado)}: {veredicto} con la suma calculada."
    return recortar(salida)


# ---------------------------------------------------------------- calculadora segura
_BINARIOS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
             ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARIOS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCIONES = {n: getattr(math, n) for n in (
    "sqrt", "cbrt", "exp", "log", "log10", "log2", "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
    "sinh", "cosh", "tanh", "degrees", "radians", "floor", "ceil", "trunc", "fabs", "hypot", "gcd", "lcm",
    "factorial", "comb", "perm", "isqrt", "pow", "fsum", "prod", "dist") if hasattr(math, n)}
_FUNCIONES.update(abs=abs, round=round, min=min, max=max, sum=sum,
                  raiz=math.sqrt, redondear=round, seno=math.sin, coseno=math.cos, tangente=math.tan)
_CONSTANTES = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}
MAX_DIGITOS = 5000


def _grande(x) -> bool:
    return isinstance(x, int) and x.bit_length() > MAX_DIGITOS * 3.33


def _eval(nodo, profundidad=0):
    if profundidad > 60:
        raise ErrorAnalisis("Expresión demasiado anidada.")
    p = profundidad + 1
    if isinstance(nodo, ast.Expression):
        return _eval(nodo.body, p)
    if isinstance(nodo, ast.Constant) and type(nodo.value) in (int, float):
        return nodo.value
    if isinstance(nodo, (ast.List, ast.Tuple)):
        return [_eval(x, p) for x in nodo.elts]
    if isinstance(nodo, ast.Name):
        if nodo.id in _CONSTANTES:
            return _CONSTANTES[nodo.id]
        raise ErrorAnalisis(f"Nombre no permitido: '{nodo.id}'.")
    if isinstance(nodo, ast.UnaryOp) and type(nodo.op) in _UNARIOS:
        return _UNARIOS[type(nodo.op)](_eval(nodo.operand, p))
    if isinstance(nodo, ast.BinOp) and type(nodo.op) in _BINARIOS:
        a, b = _eval(nodo.left, p), _eval(nodo.right, p)
        if isinstance(a, list) or isinstance(b, list):
            raise ErrorAnalisis("Las listas solo valen como argumento de funciones (sum, min, max...).")
        if isinstance(nodo.op, ast.Pow):
            if abs(b) > 10000 or (abs(a) > 1 and abs(b) * math.log10(abs(a)) > MAX_DIGITOS):
                raise ErrorAnalisis("Potencia demasiado grande.")
        r = _BINARIOS[type(nodo.op)](a, b)
        if _grande(r):
            raise ErrorAnalisis("Resultado demasiado grande.")
        return r
    if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and not nodo.keywords:
        nombre = nodo.func.id
        if nombre not in _FUNCIONES:
            raise ErrorAnalisis(f"Función no permitida: '{nombre}'. Permitidas: " + ", ".join(sorted(_FUNCIONES)))
        args = [_eval(a, p) for a in nodo.args]
        if nombre in ("factorial", "comb", "perm") and any(isinstance(a, (int, float)) and a > 2000 for a in args):
            raise ErrorAnalisis("Número demasiado grande para esa función.")
        if nombre == "pow" and len(args) == 2 and abs(args[1]) > 10000:
            raise ErrorAnalisis("Potencia demasiado grande.")
        r = _FUNCIONES[nombre](*args)
        if _grande(r):
            raise ErrorAnalisis("Resultado demasiado grande.")
        return r
    raise ErrorAnalisis(f"Elemento no permitido en la expresión: {type(nodo).__name__}.")


def _preparar(expresion: str) -> str:
    e = expresion.strip().rstrip("=").strip()
    e = (e.replace("×", "*").replace("÷", "/").replace("^", "**").replace("√", "sqrt")
          .replace("²", "**2").replace("³", "**3").replace("−", "-").replace("·", "*"))
    if not re.search(r"[A-Za-z_]", e) and re.search(r"\d,\d", e):
        e = re.sub(r"(?<=\d)\.(?=\d{3}(?!\d))", "", e)                 # 1.234,5: el punto es de miles
    # Fuera de los paréntesis de una función, "12,5" es decimal; dentro de max(1,5) la coma separa argumentos.
    salida, pila = [], []
    for i, c in enumerate(e):
        if c == "(":
            pila.append(bool(re.search(r"[A-Za-z_]\w*\s*$", e[:i])))
        elif c == ")" and pila:
            pila.pop()
        elif c == "," and not any(pila) and 0 < i < len(e) - 1 and e[i - 1].isdigit() and e[i + 1].isdigit():
            c = "."
        salida.append(c)
    return "".join(salida)


def evaluar(expresion: str) -> str:
    if not expresion or not expresion.strip():
        raise ErrorAnalisis("La expresión está vacía.")
    if len(expresion) > 1000:
        raise ErrorAnalisis("Expresión demasiado larga (máximo 1000 caracteres).")
    e = _preparar(expresion)
    try:
        arbol = ast.parse(e, mode="eval")
    except SyntaxError:
        raise ErrorAnalisis("No entendí la expresión. Usa números con punto decimal, + - * / ** % y paréntesis.")
    if sum(1 for _ in ast.walk(arbol)) > 400:
        raise ErrorAnalisis("Expresión demasiado larga.")
    try:
        r = _eval(arbol)
    except ZeroDivisionError:
        raise ErrorAnalisis("División por cero.")
    except OverflowError:
        raise ErrorAnalisis("El resultado es demasiado grande.")
    except (ValueError, TypeError) as ex:
        raise ErrorAnalisis(f"Operación matemática no válida: {ex}.")
    if isinstance(r, list):
        raise ErrorAnalisis("El resultado es una lista; usa sum(), min() o max().")
    if isinstance(r, bool):
        r = int(r)
    if isinstance(r, float):
        if r.is_integer() and abs(r) < 1e15:
            texto = str(int(r))
        else:
            texto = format(r, ".12g")
    else:
        texto = str(r)
    return f"{e} = {texto}"
