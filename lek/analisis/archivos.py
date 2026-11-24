"""Análisis determinista de archivos para LUNA (solo lectura).

analizar_archivo(ruta, raices): informe con números exactos (≤ 2.500 caracteres) de PDF, DOCX,
XLSX/CSV, imágenes, GLB/glTF y texto.
comparar_archivos(a, b, raices): diferencias de texto o de tablas.

Seguridad: la ruta tiene que quedar (ya resuelta, con enlaces seguidos) dentro de alguna de las
raíces permitidas; nunca se escribe nada; tamaño máximo 50 MB; límite de tiempo cooperativo.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import pathlib
import re
import struct

from .tablas import (ErrorAnalisis, Plazo, a_numero, describir_tabla, estilo_decimal, estructurar, fmt,
                     leer_hojas, norm, perfil_columna, recortar)

MAX_BYTES = 50 * 1024 * 1024
MAX_PAGINAS_TEXTO = 500
TABLAS = (".csv", ".tsv", ".xlsx", ".xlsm")
IMAGENES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff")
TEXTOS = (".txt", ".md", ".json", ".xml", ".html", ".htm", ".py", ".log", ".ini", ".cfg", ".yaml", ".yml",
          ".rtf", ".svg", ".obj", ".mtl", ".ifc", ".dxf")


# ---------------------------------------------------------------- rutas
def _dentro(ruta: pathlib.Path, raiz: pathlib.Path) -> bool:
    r, b = os.path.normcase(str(ruta)), os.path.normcase(str(raiz))
    return r == b or r.startswith(b.rstrip("\\/") + os.sep)


def validar_ruta(ruta, raices) -> pathlib.Path:
    """Devuelve la ruta real del archivo si está dentro de las raíces permitidas; si no, ErrorAnalisis.

    Acepta rutas absolutas, relativas a una raíz, o solo el nombre del archivo (se busca en las raíces).
    """
    raices_ok = []
    for r in raices or []:
        try:
            p = pathlib.Path(r).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if p.is_dir():
            raices_ok.append(p)
    if not raices_ok:
        raise ErrorAnalisis("No hay carpetas permitidas configuradas para analizar archivos.")
    texto = str(ruta or "").strip().strip('"').strip("'")
    if not texto:
        raise ErrorAnalisis("Falta la ruta del archivo.")
    pedido = pathlib.Path(texto).expanduser()
    candidatos = [pedido] if pedido.is_absolute() else [raiz / pedido for raiz in raices_ok]
    for c in candidatos:
        try:
            real = c.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not any(_dentro(real, raiz) for raiz in raices_ok):
            raise ErrorAnalisis("Ese archivo está fuera de las carpetas permitidas; no lo puedo abrir.")
        return _comprobar_archivo(real)
    if pedido.is_absolute() or len(pedido.parts) > 1:
        raise ErrorAnalisis(f"No encontré el archivo '{texto}'.")
    # solo un nombre: se busca (sin distinguir mayúsculas) dentro de las raíces
    buscado, encontrados, vistos = norm(pedido.name), [], 0
    plazo = Plazo(5)
    for raiz in raices_ok:
        for dirpath, dirnames, archivos in os.walk(raiz):
            dirnames[:] = [d for d in dirnames if not d.startswith((".", "__pycache__"))]
            vistos += len(archivos)
            plazo.comprobar()
            for a in archivos:
                if norm(a) == buscado:
                    real = pathlib.Path(dirpath, a).resolve()
                    if any(_dentro(real, r) for r in raices_ok) and real not in encontrados:
                        encontrados.append(real)
            if vistos > 50_000:
                break
    if len(encontrados) == 1:
        return _comprobar_archivo(encontrados[0])
    if len(encontrados) > 1:
        raise ErrorAnalisis("Hay varios archivos con ese nombre; dime cuál: " + "; ".join(str(e) for e in encontrados[:5]))
    raise ErrorAnalisis(f"No encontré '{texto}' en las carpetas permitidas.")


def _comprobar_archivo(p: pathlib.Path) -> pathlib.Path:
    if not p.is_file():
        raise ErrorAnalisis(f"'{p.name}' no es un archivo.")
    tam = p.stat().st_size
    if tam > MAX_BYTES:
        raise ErrorAnalisis(f"'{p.name}' pesa {_tamano(tam)}; el máximo para analizar es 50 MB.")
    return p


def _tamano(n: int) -> str:
    if n < 1024:
        return f"{n} bytes"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 ** 2:.2f} MB"


def _palabras(texto: str) -> int:
    return len(re.findall(r"\w+", texto))


# ---------------------------------------------------------------- PDF
_FORMATOS_MM = {"A0": (841, 1189), "A1": (594, 841), "A2": (420, 594), "A3": (297, 420), "A4": (210, 297),
                "Carta": (216, 279), "Oficio": (216, 330), "Pliego 70×100": (700, 1000), "Tabloide": (279, 432)}


def _nombre_formato(ancho_mm: float, alto_mm: float) -> str:
    a, b = sorted((ancho_mm, alto_mm))
    orient = "horizontal" if ancho_mm > alto_mm else "vertical"
    for nombre, (x, y) in _FORMATOS_MM.items():
        if abs(a - x) <= 4 and abs(b - y) <= 4:
            return f"{nombre} {orient}"
    return f"{round(ancho_mm)}×{round(alto_mm)} mm"


def _titulos_de_texto(textos: list) -> list:
    titulos = []
    for t in textos:
        for linea in t.splitlines():
            l = linea.strip()
            letras = [c for c in l if c.isalpha()]
            if not (4 <= len(l) <= 80) or len(letras) < 3 or l.endswith((".", ",", ";")):
                continue
            mayus = sum(1 for c in letras if c.isupper()) / len(letras)
            if mayus >= 0.8 or re.match(r"^(\d+(\.\d+)*\.?|[IVX]+\.)\s+[A-ZÁÉÍÓÚÑ]", l):
                if l not in titulos:
                    titulos.append(l)
            if len(titulos) >= 15:
                return titulos
    return titulos


def _contorno(lista, salida, nivel=0):
    for x in lista:
        if isinstance(x, list):
            _contorno(x, salida, nivel + 1)
        elif getattr(x, "title", None) and len(salida) < 20:
            salida.append("  " * nivel + str(x.title).strip())


def textos_pdf(ruta, plazo: Plazo) -> tuple:
    from pypdf import PdfReader
    lector = PdfReader(str(ruta))
    if lector.is_encrypted:
        try:
            if not lector.decrypt(""):
                raise ErrorAnalisis("El PDF está protegido con contraseña; no lo puedo leer.")
        except ErrorAnalisis:
            raise
        except Exception:
            raise ErrorAnalisis("El PDF está cifrado y no se puede abrir sin contraseña.")
    textos = []
    for i, pagina in enumerate(lector.pages):
        if i >= MAX_PAGINAS_TEXTO:
            break
        plazo.comprobar()
        try:
            textos.append(pagina.extract_text() or "")
        except Exception:
            textos.append("")
    return lector, textos


def analizar_pdf(ruta, plazo: Plazo) -> str:
    lector, textos = textos_pdf(ruta, plazo)
    n = len(lector.pages)
    lineas = [f"Páginas: {n}"]
    sin_texto = [i + 1 for i, t in enumerate(textos) if len(t.strip()) < 20]
    palabras = sum(_palabras(t) for t in textos)
    lineas.append(f"Palabras: {palabras}" + (f" (solo en las primeras {len(textos)} páginas)" if n > len(textos) else ""))
    if textos and len(sin_texto) == len(textos):
        lineas.append("Parece ESCANEADO o solo imágenes/dibujo vectorial: no tiene texto extraíble (haría falta OCR).")
    elif sin_texto:
        lineas.append(f"Páginas sin texto extraíble ({len(sin_texto)}): " + ", ".join(map(str, sin_texto[:30])) +
                      ("…" if len(sin_texto) > 30 else ""))
    formatos = {}
    for pagina in lector.pages[:MAX_PAGINAS_TEXTO]:
        try:
            caja = pagina.mediabox
            ancho, alto = float(caja.width) * 25.4 / 72, float(caja.height) * 25.4 / 72
            if (pagina.get("/Rotate") or 0) % 180 == 90:
                ancho, alto = alto, ancho
            f = _nombre_formato(ancho, alto)
            formatos[f] = formatos.get(f, 0) + 1
        except Exception:
            continue
    if formatos:
        lineas.append("Tamaño de página: " + ", ".join(f"{c} × {f}" for f, c in formatos.items()))
    try:
        meta = lector.metadata or {}
        if meta.get("/Title"):
            lineas.append(f"Título (metadatos): {str(meta.get('/Title'))[:120]}")
        if meta.get("/Creator") or meta.get("/Producer"):
            lineas.append(f"Creado con: {str(meta.get('/Creator') or meta.get('/Producer'))[:80]}")
    except Exception:
        pass
    marcadores = []
    try:
        _contorno(lector.outline, marcadores)
    except Exception:
        pass
    if marcadores:
        lineas.append("Marcadores del PDF:\n" + "\n".join(" - " + m for m in marcadores))
    else:
        titulos = _titulos_de_texto(textos[:60])
        if titulos:
            lineas.append("Títulos detectados:\n" + "\n".join(" - " + t for t in titulos))
    return "\n".join(lineas)


# ---------------------------------------------------------------- DOCX
def _nivel_titulo(estilo: str):
    e = norm(estilo)
    if e in ("title", "titulo"):
        return 0
    m = re.match(r"(heading|titulo|encabezado)\s*(\d)", e)
    return int(m.group(2)) if m else None


def analizar_docx(ruta, plazo: Plazo) -> str:
    import docx
    d = docx.Document(str(ruta))
    parrafos = [p for p in d.paragraphs if p.text.strip()]
    titulos = []
    for p in parrafos:
        nivel = _nivel_titulo(p.style.name if p.style is not None else "")
        if nivel is not None:
            titulos.append("  " * max(nivel - 1, 0) + p.text.strip()[:90])
    palabras = sum(_palabras(p.text) for p in parrafos)
    celdas = 0
    for t in d.tables:
        plazo.comprobar()
        for fila in t.rows:
            for c in fila.cells:
                palabras += _palabras(c.text)
                celdas += 1
    lineas = [f"Párrafos con texto: {len(parrafos)}", f"Palabras (incluye tablas): {palabras}",
              f"Encabezados: {len(titulos)}", f"Tablas: {len(d.tables)}"]
    try:
        lineas.append(f"Imágenes en línea: {len(d.inline_shapes)}")
        s = d.sections[0]
        ancho, alto = s.page_width.mm, s.page_height.mm
        lineas.append(f"Página: {_nombre_formato(ancho, alto)} ({len(d.sections)} secciones)")
    except Exception:
        pass
    if titulos:
        lineas.append("Estructura:\n" + "\n".join(" - " + t for t in titulos[:25]) +
                      (f"\n (+{len(titulos) - 25} encabezados más)" if len(titulos) > 25 else ""))
    for i, t in enumerate(d.tables[:6], 1):
        filas = [[c.text.strip() for c in f.cells] for f in t.rows]
        ncol = max((len(f) for f in filas), default=0)
        lineas.append(f"Tabla {i}: {len(filas)} filas × {ncol} columnas; primera fila: " +
                      " | ".join(c[:25] for c in (filas[0] if filas else []))[:200])
        if len(filas) > 2:
            t2 = estructurar(filas)
            for j, col in enumerate(t2["encabezados"][:8]):
                p = perfil_columna([f[j] for f in t2["datos"]])
                if p["tipo"] == "número" and p["numeros"] > 1:
                    lineas.append(f"   {col}: suma {fmt(p['suma'])}, mín {fmt(p['minimo'])}, máx {fmt(p['maximo'])}")
    if not titulos and parrafos:
        lineas.append("Sin estilos de título; inicio: " + parrafos[0].text.strip()[:150])
    return "\n".join(lineas)


def textos_docx(ruta) -> list:
    import docx
    d = docx.Document(str(ruta))
    lineas = [p.text for p in d.paragraphs]
    for t in d.tables:
        for f in t.rows:
            lineas.append(" | ".join(c.text.strip() for c in f.cells))
    return lineas


# ---------------------------------------------------------------- imágenes
def _encabezado_imagen(datos: bytes) -> dict:
    """Formato y dimensiones leyendo los bytes de cabecera (sin Pillow)."""
    if datos[:8] == b"\x89PNG\r\n\x1a\n" and datos[12:16] == b"IHDR":
        ancho, alto, prof, color = struct.unpack(">IIBB", datos[16:26])
        modos = {0: "escala de grises", 2: "RGB", 3: "paleta", 4: "grises + alfa", 6: "RGBA"}
        return {"formato": "PNG", "ancho": ancho, "alto": alto, "modo": f"{modos.get(color, color)}, {prof} bits/canal"}
    if datos[:2] == b"\xff\xd8":
        i, exif = 2, False
        while i + 4 <= len(datos):
            if datos[i] != 0xFF:
                i += 1
                continue
            marca = datos[i + 1]
            if marca in (0xD8, 0x01) or 0xD0 <= marca <= 0xD7 or marca == 0xFF:
                i += 1 if marca == 0xFF else 2
                continue
            largo = struct.unpack(">H", datos[i + 2:i + 4])[0]
            if marca == 0xE1 and datos[i + 4:i + 10] == b"Exif\x00\x00":
                exif = True
            if 0xC0 <= marca <= 0xCF and marca not in (0xC4, 0xC8, 0xCC) and i + 9 <= len(datos):
                alto, ancho = struct.unpack(">HH", datos[i + 5:i + 9])
                comps = datos[i + 9] if i + 9 < len(datos) else 0
                return {"formato": "JPEG", "ancho": ancho, "alto": alto,
                        "modo": {1: "escala de grises", 3: "color (YCbCr)", 4: "CMYK"}.get(comps, f"{comps} canales"),
                        "exif": "sí" if exif else "no"}
            i += 2 + largo
        return {"formato": "JPEG"}
    if datos[:6] in (b"GIF87a", b"GIF89a"):
        ancho, alto = struct.unpack("<HH", datos[6:10])
        return {"formato": "GIF", "ancho": ancho, "alto": alto}
    if datos[:2] == b"BM" and len(datos) >= 26:
        ancho, alto = struct.unpack("<ii", datos[18:26])
        return {"formato": "BMP", "ancho": ancho, "alto": abs(alto)}
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        trozo = datos[12:16]
        if trozo == b"VP8X":
            return {"formato": "WEBP", "ancho": int.from_bytes(datos[24:27], "little") + 1,
                    "alto": int.from_bytes(datos[27:30], "little") + 1}
        if trozo == b"VP8L":
            b = int.from_bytes(datos[21:25], "little")
            return {"formato": "WEBP", "ancho": (b & 0x3FFF) + 1, "alto": ((b >> 14) & 0x3FFF) + 1}
        if trozo == b"VP8 ":
            ancho, alto = struct.unpack("<HH", datos[26:30])
            return {"formato": "WEBP", "ancho": ancho & 0x3FFF, "alto": alto & 0x3FFF}
        return {"formato": "WEBP"}
    if datos[:4] in (b"II*\x00", b"MM\x00*"):
        return {"formato": "TIFF"}
    raise ErrorAnalisis("No reconozco el formato de esta imagen.")


def analizar_imagen(ruta, plazo: Plazo, usar_pillow: bool = True) -> str:
    info = None
    if usar_pillow:
        try:
            from PIL import ExifTags, Image
            with Image.open(str(ruta)) as img:             # solo cabecera: no decodifica los píxeles
                info = {"formato": img.format, "ancho": img.width, "alto": img.height, "modo": img.mode}
                if getattr(img, "n_frames", 1) > 1:
                    info["fotogramas"] = img.n_frames
                dpi = img.info.get("dpi")
                if dpi:
                    info["dpi"] = f"{round(float(dpi[0]))}×{round(float(dpi[1]))}"
                exif = img.getexif()
                if exif:
                    campos = []
                    for tag, v in exif.items():
                        nombre = ExifTags.TAGS.get(tag, "")
                        if nombre in ("Make", "Model", "DateTime", "Software", "Orientation"):
                            campos.append(f"{nombre}={str(v).strip()[:40]}")
                    if exif.get(0x8825):
                        campos.append("tiene coordenadas GPS")
                    info["exif"] = "; ".join(campos) or "sí (sin campos comunes)"
                else:
                    info["exif"] = "no"
        except ImportError:
            info = None
        except Exception:
            info = None
    if info is None:
        with open(ruta, "rb") as f:
            info = _encabezado_imagen(f.read(256 * 1024))
    lineas = [f"Imagen {info.get('formato', '?')}"]
    if info.get("ancho"):
        mp = info["ancho"] * info["alto"] / 1_000_000
        lineas.append(f"Dimensiones: {info['ancho']} × {info['alto']} px ({mp:.2f} megapíxeles)")
    for clave, rotulo in (("modo", "Color"), ("dpi", "DPI"), ("fotogramas", "Fotogramas"), ("exif", "EXIF")):
        if info.get(clave):
            lineas.append(f"{rotulo}: {info[clave]}")
    return "\n".join(lineas)


# ---------------------------------------------------------------- GLB / glTF
def _json_glb(ruta) -> tuple:
    with open(ruta, "rb") as f:
        cabecera = f.read(12)
        if len(cabecera) < 12 or cabecera[:4] != b"glTF":
            raise ErrorAnalisis("No es un GLB válido (falta la firma 'glTF').")
        version, declarado = struct.unpack("<II", cabecera[4:12])
        real = os.path.getsize(ruta)
        trozo = f.read(8)
        if len(trozo) < 8:
            raise ErrorAnalisis("GLB truncado: no tiene el bloque JSON.")
        largo, tipo = struct.unpack("<II", trozo)
        if tipo != 0x4E4F534A or largo > real - 20:
            raise ErrorAnalisis("GLB dañado: el bloque JSON no es válido.")
        texto = f.read(largo)
        binario = 0
        extra = f.read(8)
        if len(extra) == 8:
            lb, tb = struct.unpack("<II", extra)
            if tb == 0x004E4942:
                binario = lb
    try:
        datos = json.loads(texto.decode("utf-8").rstrip(" \x00"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ErrorAnalisis("GLB dañado: el JSON interno no se puede leer.")
    return datos, {"version": version, "declarado": declarado, "real": real, "json": largo, "bin": binario}


def analizar_gltf(ruta, plazo: Plazo) -> str:
    if str(ruta).lower().endswith(".glb"):
        g, cab = _json_glb(ruta)
        lineas = [f"GLB (glTF binario) versión {cab['version']}; tamaño declarado {cab['declarado']} bytes "
                  f"({'coincide' if cab['declarado'] == cab['real'] else 'NO coincide: ' + str(cab['real'])} con el archivo); "
                  f"JSON {cab['json']} bytes, datos binarios {cab['bin']} bytes"]
    else:
        try:
            g = json.loads(pathlib.Path(ruta).read_bytes().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ErrorAnalisis("El .gltf no es un JSON válido.")
        lineas = ["glTF (JSON)"]
    if not isinstance(g, dict):
        raise ErrorAnalisis("El glTF no tiene la estructura esperada.")
    activo = g.get("asset") or {}
    lineas.append(f"glTF {activo.get('version', '?')}" + (f", generado por {str(activo['generator'])[:60]}" if activo.get("generator") else ""))
    conteo = {k: len(g.get(k) or []) for k in ("scenes", "nodes", "meshes", "materials", "textures", "images",
                                                 "animations", "cameras", "skins", "accessors")}
    nombres = {"scenes": "escenas", "nodes": "nodos", "meshes": "mallas", "materials": "materiales",
               "textures": "texturas", "images": "imágenes", "animations": "animaciones", "cameras": "cámaras",
               "skins": "esqueletos", "accessors": "accessors"}
    lineas.append(", ".join(f"{conteo[k]} {nombres[k]}" for k in conteo if conteo[k] or k in ("nodes", "meshes", "materials")))
    accesores = g.get("accessors") or []
    vertices = triangulos = primitivas = 0
    minimo, maximo = [float("inf")] * 3, [float("-inf")] * 3
    for malla in g.get("meshes") or []:
        plazo.comprobar()
        for prim in (malla or {}).get("primitives") or []:
            primitivas += 1
            pos = (prim.get("attributes") or {}).get("POSITION")
            if isinstance(pos, int) and 0 <= pos < len(accesores):
                a = accesores[pos]
                vertices += int(a.get("count", 0))
                if isinstance(a.get("min"), list) and isinstance(a.get("max"), list) and len(a["min"]) == 3:
                    minimo = [min(x, float(y)) for x, y in zip(minimo, a["min"])]
                    maximo = [max(x, float(y)) for x, y in zip(maximo, a["max"])]
            if prim.get("mode", 4) == 4:
                idx = prim.get("indices")
                if isinstance(idx, int) and 0 <= idx < len(accesores):
                    triangulos += int(accesores[idx].get("count", 0)) // 3
                elif isinstance(pos, int) and 0 <= pos < len(accesores):
                    triangulos += int(accesores[pos].get("count", 0)) // 3
    lineas.append(f"Primitivas: {primitivas}; vértices: {vertices}; triángulos: {triangulos}")
    if minimo[0] != float("inf"):
        medidas = [maximo[i] - minimo[i] for i in range(3)]
        lineas.append("Extensión de las mallas (X×Y×Z, unidades del modelo, normalmente metros; sin aplicar "
                      "transformaciones de nodos): " + " × ".join(fmt(round(m, 3)) for m in medidas))
    for clave, rotulo in (("meshes", "Mallas"), ("materials", "Materiales")):
        ns = [str(x.get("name")) for x in (g.get(clave) or []) if isinstance(x, dict) and x.get("name")]
        if ns:
            lineas.append(f"{rotulo}: " + ", ".join(n[:30] for n in ns[:12]) + (f" (+{len(ns) - 12})" if len(ns) > 12 else ""))
    extensiones = g.get("extensionsUsed") or []
    if extensiones:
        lineas.append("Extensiones: " + ", ".join(map(str, extensiones[:8])))
    return "\n".join(lineas)


# ---------------------------------------------------------------- texto
def leer_texto(ruta) -> str:
    datos = pathlib.Path(ruta).read_bytes()
    for cod in ("utf-8-sig", "cp1252"):
        try:
            return datos.decode(cod)
        except UnicodeDecodeError:
            continue
    return datos.decode("latin-1")


def analizar_texto(ruta, plazo: Plazo) -> str:
    texto = leer_texto(ruta)
    lineas_txt = texto.splitlines()
    lineas = [f"Líneas: {len(lineas_txt)}; palabras: {_palabras(texto)}; caracteres: {len(texto)}"]
    if str(ruta).lower().endswith(".md"):
        titulos = [l.strip() for l in lineas_txt if re.match(r"^#{1,6}\s", l)]
        if titulos:
            lineas.append("Títulos:\n" + "\n".join(" - " + t[:90] for t in titulos[:20]))
    elif str(ruta).lower().endswith(".json"):
        try:
            d = json.loads(texto)
            if isinstance(d, dict):
                lineas.append("JSON (objeto) con claves: " + ", ".join(list(map(str, d))[:20]))
            elif isinstance(d, list):
                lineas.append(f"JSON (lista) de {len(d)} elementos")
        except json.JSONDecodeError as e:
            lineas.append(f"JSON no válido: {e}")
    inicio = " ".join(l.strip() for l in lineas_txt if l.strip())[:300]
    if inicio:
        lineas.append("Inicio: " + inicio)
    return "\n".join(lineas)


# ---------------------------------------------------------------- API pública
def _tipo(p: pathlib.Path) -> str:
    ext = p.suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in (".docx", ".docm"):
        return "docx"
    if ext in TABLAS or ext == ".xls":
        return "tabla"
    if ext in IMAGENES:
        return "imagen"
    if ext in (".glb", ".gltf"):
        return "gltf"
    if ext in TEXTOS:
        return "texto"
    return "otro"


def analizar_archivo(ruta, raices, plazo: Plazo | None = None, usar_pillow: bool = True,
                     usar_openpyxl: bool = True) -> str:
    plazo = plazo or Plazo()
    p = validar_ruta(ruta, raices)
    tipo = _tipo(p)
    cabeza = f"Archivo: {p.name} ({p.suffix.lstrip('.').upper() or 'sin extensión'}, {_tamano(p.stat().st_size)})\n"
    try:
        if tipo == "pdf":
            cuerpo = analizar_pdf(p, plazo)
        elif tipo == "docx":
            cuerpo = analizar_docx(p, plazo)
        elif tipo == "tabla":
            hojas = leer_hojas(p, plazo, usar_openpyxl)
            cuerpo = (f"Hojas: {len(hojas)} (" + ", ".join(h[0] for h in hojas) + ")\n") if len(hojas) > 1 else ""
            cuerpo += "\n".join(describir_tabla(n, f, 25 if len(hojas) == 1 else 12) for n, f in hojas[:6])
        elif tipo == "imagen":
            cuerpo = analizar_imagen(p, plazo, usar_pillow)
        elif tipo == "gltf":
            cuerpo = analizar_gltf(p, plazo)
        elif tipo == "texto":
            cuerpo = analizar_texto(p, plazo)
        else:
            with open(p, "rb") as f:
                inicio = f.read(4096)
            if inicio and b"\x00" not in inicio:
                cuerpo = analizar_texto(p, plazo)
            else:
                cuerpo = "Formato no soportado para análisis de contenido (solo puedo dar el tamaño)."
    except ErrorAnalisis:
        raise
    except ImportError as e:
        raise ErrorAnalisis(f"Falta una librería para leer este formato ({e.name}).")
    except Exception as e:
        raise ErrorAnalisis(f"No pude analizar '{p.name}': el archivo parece dañado ({type(e).__name__}).")
    return recortar(cabeza + cuerpo)


def _lineas_para_comparar(p: pathlib.Path, plazo: Plazo, usar_openpyxl: bool) -> list:
    tipo = _tipo(p)
    if tipo == "pdf":
        _, textos = textos_pdf(p, plazo)
        lineas = [l for t in textos for l in t.splitlines()]
    elif tipo == "docx":
        lineas = textos_docx(p)
    elif tipo == "tabla":
        lineas = [" | ".join(f) for _, filas in leer_hojas(p, plazo, usar_openpyxl) for f in filas]
    elif tipo in ("texto", "otro"):
        lineas = leer_texto(p).splitlines()
    else:
        lineas = analizar_archivo(p, [p.parent], plazo).splitlines()[1:]
    return [re.sub(r"\s+", " ", l).strip() for l in lineas if l and l.strip()][:20000]


def _sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _comparar_tablas(a, b, plazo: Plazo, usar_openpyxl: bool) -> str:
    hojas_a, hojas_b = leer_hojas(a, plazo, usar_openpyxl), leer_hojas(b, plazo, usar_openpyxl)
    salida = []
    na, nb = [h[0] for h in hojas_a], [h[0] for h in hojas_b]
    if len(hojas_a) > 1 or len(hojas_b) > 1:
        if set(na) - set(nb):
            salida.append("Hojas solo en A: " + ", ".join(sorted(set(na) - set(nb))))
        if set(nb) - set(na):
            salida.append("Hojas solo en B: " + ", ".join(sorted(set(nb) - set(na))))
        pares = [(n, dict(hojas_a)[n], dict(hojas_b)[n]) for n in na if n in nb][:5]
        if not pares:
            pares = [(f"{na[0]} / {nb[0]}", hojas_a[0][1], hojas_b[0][1])]
    else:
        pares = [("tabla", hojas_a[0][1], hojas_b[0][1])]
    for nombre, fa, fb in pares:
        plazo.comprobar()
        ta, tb = estructurar(fa), estructurar(fb)
        ea, eb = ta["encabezados"], tb["encabezados"]
        da, db = ta["datos"], tb["datos"]
        salida.append(f"[{nombre}] filas: A {len(da)}, B {len(db)}; columnas: A {len(ea)}, B {len(eb)}")
        na_, nb_ = [norm(e) for e in ea], [norm(e) for e in eb]
        if set(na_) - set(nb_):
            salida.append(" Columnas solo en A: " + ", ".join(e for e in ea if norm(e) not in nb_))
        if set(nb_) - set(na_):
            salida.append(" Columnas solo en B: " + ", ".join(e for e in eb if norm(e) not in na_))
        comunes = [(ea[i], i, nb_.index(n)) for i, n in enumerate(na_) if n in nb_]
        if not comunes:
            continue
        clave_a, clave_b = comunes[0][1], comunes[0][2]
        ka, kb = [f[clave_a] for f in da], [f[clave_b] for f in db]
        por_clave = len(set(ka)) == len(ka) and len(set(kb)) == len(kb) and all(ka) and all(kb)
        if por_clave:
            ia, ib = {k: f for k, f in zip(ka, da)}, {k: f for k, f in zip(kb, db)}
            solo_a, solo_b = [k for k in ka if k not in ib], [k for k in kb if k not in ia]
            if solo_a:
                salida.append(f" Filas solo en A ({len(solo_a)}) por '{comunes[0][0]}': " + ", ".join(solo_a[:15]))
            if solo_b:
                salida.append(f" Filas solo en B ({len(solo_b)}) por '{comunes[0][0]}': " + ", ".join(solo_b[:15]))
            emparejadas = [(k, ia[k], ib[k]) for k in ka if k in ib]
        else:
            emparejadas = [(f"fila {i + 1}", x, y) for i, (x, y) in enumerate(zip(da, db))]
            if len(da) != len(db):
                salida.append(f" (comparé por posición; sobran {abs(len(da) - len(db))} filas en {'A' if len(da) > len(db) else 'B'})")
        cambios = []
        for k, x, y in emparejadas:
            for col, i, j in comunes:
                va, vb = x[i], y[j]
                if va == vb:
                    continue
                n1, n2 = a_numero(va), a_numero(vb)
                if n1 is not None and n1 == n2:
                    continue
                if norm(va) == norm(vb) and n1 is None:
                    continue
                cambios.append(f"{k} · {col}: {va or '(vacío)'} → {vb or '(vacío)'}")
        if cambios:
            salida.append(f" Celdas cambiadas: {len(cambios)}\n" + "\n".join("  " + c[:150] for c in cambios[:15]) +
                          (f"\n  (+{len(cambios) - 15} más)" if len(cambios) > 15 else ""))
        else:
            salida.append(" Ninguna celda distinta en las filas y columnas comunes.")
        for col, i, j in comunes:
            pa, pb = perfil_columna([f[i] for f in da]), perfil_columna([f[j] for f in db])
            if pa["tipo"] == pb["tipo"] == "número" and pa["suma"] != pb["suma"]:
                salida.append(f" Suma de '{col}': A {fmt(pa['suma'])}, B {fmt(pb['suma'])} (diferencia {fmt(pb['suma'] - pa['suma'])})")
    return "\n".join(salida)


def comparar_archivos(ruta_a, ruta_b, raices, plazo: Plazo | None = None, usar_openpyxl: bool = True) -> str:
    plazo = plazo or Plazo(30)
    a, b = validar_ruta(ruta_a, raices), validar_ruta(ruta_b, raices)
    cabeza = f"A: {a.name} ({_tamano(a.stat().st_size)})\nB: {b.name} ({_tamano(b.stat().st_size)})\n"
    if a == b:
        return cabeza + "Es el mismo archivo."
    if a.stat().st_size == b.stat().st_size and _sha256(a) == _sha256(b):
        return cabeza + "Son IDÉNTICOS byte a byte."
    try:
        if _tipo(a) == "tabla" and _tipo(b) == "tabla":
            return recortar(cabeza + _comparar_tablas(a, b, plazo, usar_openpyxl))
        la, lb = _lineas_para_comparar(a, plazo, usar_openpyxl), _lineas_para_comparar(b, plazo, usar_openpyxl)
    except ErrorAnalisis:
        raise
    except ImportError as e:
        raise ErrorAnalisis(f"Falta una librería para leer este formato ({e.name}).")
    except Exception as e:
        raise ErrorAnalisis(f"No pude leer uno de los archivos ({type(e).__name__}).")
    plazo.comprobar()
    sm = difflib.SequenceMatcher(None, la, lb, autojunk=False)
    quitadas = agregadas = 0
    ejemplos = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        quitadas += i2 - i1
        agregadas += j2 - j1
        if len(ejemplos) < 24:
            ejemplos += ["- " + l[:140] for l in la[i1:min(i2, i1 + 3)]]
            ejemplos += ["+ " + l[:140] for l in lb[j1:min(j2, j1 + 3)]]
        plazo.comprobar()
    pa, pb = sum(_palabras(l) for l in la), sum(_palabras(l) for l in lb)
    salida = cabeza + (f"Líneas con texto: A {len(la)}, B {len(lb)}; palabras: A {pa}, B {pb}\n"
                       f"Similitud: {sm.ratio() * 100:.1f} %; líneas quitadas: {quitadas}; líneas nuevas: {agregadas}\n")
    if not quitadas and not agregadas:
        salida += "El texto es el mismo (cambian el formato u otros datos internos)."
    else:
        salida += "Cambios (- en A, + en B):\n" + "\n".join(ejemplos[:24])
    return recortar(salida)


__all__ = ["MAX_BYTES", "analizar_archivo", "comparar_archivos", "validar_ruta", "ErrorAnalisis", "Plazo",
           "estilo_decimal"]
