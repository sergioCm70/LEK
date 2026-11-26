"""Más formatos para el análisis exacto (LEK 2.0, fase 7), sin librerías nuevas.

- PPTX: diapositivas, títulos, texto y notas (abre el ZIP y lee el XML de cada diapositiva).
- IFC (BIM exportado desde Revit: Archivo → Exportar → IFC): proyecto, niveles con su cota, cantidad de muros,
  losas, puertas, ventanas, columnas, escaleras… y los espacios con su área cuando el IFC trae cantidades.
  Es SOLO lectura: nunca modifica el modelo. Lo que no viene en el archivo se dice que no viene; no se inventa.
- OCR en Windows: lee el texto de una imagen (un plano escaneado, una foto de un tablero) con el OCR que ya trae
  Windows 10/11 (Windows.Media.Ocr), sin internet y sin instalar nada. Fuera de Windows dice que no está disponible.
"""
from __future__ import annotations

import collections
import json
import os
import re
import subprocess
import zipfile
from xml.etree import ElementTree as ET

NS_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
NS_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"


# ---------------------------------------------------------------- PowerPoint
def _textos_xml(datos: bytes) -> tuple:
    """(título, [párrafos]) de una diapositiva."""
    raiz = ET.fromstring(datos)
    titulo, parrafos = "", []
    for forma in raiz.iter(f"{NS_P}sp"):
        es_titulo = any(ph.get("type") in ("title", "ctrTitle") for ph in forma.iter(f"{NS_P}ph"))
        for p in forma.iter(f"{NS_A}p"):
            texto = "".join(t.text or "" for t in p.iter(f"{NS_A}t")).strip()
            if not texto:
                continue
            if es_titulo and not titulo:
                titulo = texto
            else:
                parrafos.append(texto)
    return titulo, parrafos


def _orden(nombre: str) -> int:
    m = re.search(r"(\d+)\.xml$", nombre)
    return int(m.group(1)) if m else 0


def analizar_pptx(ruta, plazo=None) -> str:
    with zipfile.ZipFile(ruta) as z:
        diapos = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=_orden)
        notas = {_orden(n): n for n in z.namelist() if re.match(r"ppt/notesSlides/notesSlide\d+\.xml$", n)}
        if sum(z.getinfo(n).file_size for n in diapos) > 50_000_000:
            return "La presentación es demasiado grande para leerla completa."
        medios = [n for n in z.namelist() if n.startswith("ppt/media/")]
        lineas = [f"Diapositivas: {len(diapos)}. Imágenes y medios incrustados: {len(medios)}."]
        palabras = 0
        for i, nombre in enumerate(diapos, 1):
            if plazo is not None and hasattr(plazo, "revisar"):
                plazo.revisar()
            titulo, parrafos = _textos_xml(z.read(nombre))
            palabras += sum(len(p.split()) for p in parrafos) + len(titulo.split())
            linea = f"{i}. {titulo or '(sin título)'}"
            if parrafos:
                linea += ": " + " / ".join(parrafos)[:300]
            n = notas.get(_orden(nombre))
            if n:
                _, txt = _textos_xml(z.read(n))
                txt = [t for t in txt if not t.isdigit()]
                if txt:
                    linea += f" [notas: {' '.join(txt)[:150]}]"
            lineas.append(linea)
        lineas.insert(1, f"Palabras en las diapositivas: {palabras}.")
    return "\n".join(lineas)


# ---------------------------------------------------------------- IFC (BIM)
CLASES_IFC = {
    "IFCWALL": "muros", "IFCWALLSTANDARDCASE": "muros", "IFCSLAB": "losas", "IFCDOOR": "puertas",
    "IFCWINDOW": "ventanas", "IFCCOLUMN": "columnas", "IFCBEAM": "vigas", "IFCSTAIR": "escaleras",
    "IFCRAILING": "barandas", "IFCROOF": "cubiertas", "IFCCURTAINWALL": "muros cortina",
    "IFCFURNISHINGELEMENT": "mobiliario", "IFCSPACE": "espacios", "IFCBUILDINGSTOREY": "niveles",
}
_ENTIDAD = re.compile(r"^#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*)\);\s*$", re.S)


def _texto_ifc(s: str) -> str:
    s = s.strip()
    if s.startswith("'") and s.endswith("'"):
        s = s[1:-1].replace("''", "'")
        s = re.sub(r"\\X2\\([0-9A-F]+)\\X0\\", lambda m: "".join(
            chr(int(m.group(1)[i:i + 4], 16)) for i in range(0, len(m.group(1)), 4)), s)
        s = re.sub(r"\\X\\([0-9A-F]{2})", lambda m: bytes.fromhex(m.group(1)).decode("latin-1"), s)
        return s
    return "" if s in ("$", "*") else s


def _argumentos(cuerpo: str) -> list:
    """Divide los argumentos del nivel superior (respeta comillas y paréntesis)."""
    args, actual, nivel, en_texto = [], "", 0, False
    i = 0
    while i < len(cuerpo):
        c = cuerpo[i]
        if c == "'" and en_texto and i + 1 < len(cuerpo) and cuerpo[i + 1] == "'":
            actual += "''"
            i += 2
            continue
        if c == "'":
            en_texto = not en_texto
        elif not en_texto and c == "(":
            nivel += 1
        elif not en_texto and c == ")":
            nivel -= 1
        elif not en_texto and c == "," and nivel == 0:
            args.append(actual.strip())
            actual = ""
            i += 1
            continue
        actual += c
        i += 1
    if actual.strip():
        args.append(actual.strip())
    return args


def leer_ifc(ruta, plazo=None, max_bytes: int = 300_000_000) -> dict:
    tamano = os.path.getsize(ruta)
    if tamano > max_bytes:
        raise ValueError(f"El IFC pesa {tamano // 1_000_000} MB: es demasiado grande para leerlo aquí.")
    entidades, esquema = {}, ""
    with open(ruta, encoding="latin-1", errors="replace") as f:
        texto = f.read()
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", texto)
    esquema = m.group(1) if m else "desconocido"
    for n, linea in enumerate(re.split(r";\s*\n", texto)):
        if plazo is not None and n % 20000 == 0 and hasattr(plazo, "revisar"):
            plazo.revisar()
        e = _ENTIDAD.match(linea.strip() + ";")
        if e:
            entidades[int(e.group(1))] = (e.group(2), e.group(3))
    return {"esquema": esquema, "entidades": entidades}


def analizar_ifc(ruta, plazo=None) -> str:
    datos = leer_ifc(ruta, plazo)
    ent = datos["entidades"]
    conteo = collections.Counter(t for t, _ in ent.values())
    lineas = [f"IFC {datos['esquema']}, {len(ent)} entidades. Solo lectura: el modelo no se modifica."]
    for t, cuerpo in ent.values():
        if t == "IFCPROJECT":
            a = _argumentos(cuerpo)
            nombre = _texto_ifc(a[2]) if len(a) > 2 else ""
            if nombre:
                lineas.append(f"Proyecto: {nombre}")
            break
    elementos = collections.Counter()
    for t, n in conteo.items():
        if t in CLASES_IFC and t not in ("IFCSPACE", "IFCBUILDINGSTOREY"):
            elementos[CLASES_IFC[t]] += n
    if elementos:
        lineas.append("Elementos: " + ", ".join(f"{v} {k}" for k, v in elementos.most_common()))
    niveles = []
    for t, cuerpo in ent.values():
        if t == "IFCBUILDINGSTOREY":
            a = _argumentos(cuerpo)
            nombre = _texto_ifc(a[2]) if len(a) > 2 else "?"
            cota = a[9] if len(a) > 9 else "$"
            try:
                niveles.append((float(cota), nombre))
            except ValueError:
                niveles.append((float("nan"), nombre))
    if niveles:
        niveles.sort(key=lambda x: (x[0] != x[0], x[0]))
        lineas.append("Niveles (cota en las unidades del modelo): " + "; ".join(
            f"{n} ({c:g})" if c == c else f"{n} (sin cota)" for c, n in niveles))
    # áreas de espacios: IfcRelDefinesByProperties -> IfcElementQuantity -> IfcQuantityArea
    areas_q = {}
    for i, (t, cuerpo) in ent.items():
        if t == "IFCQUANTITYAREA":
            a = _argumentos(cuerpo)
            if len(a) >= 4:
                try:
                    areas_q[i] = (_texto_ifc(a[0]), float(a[3]))
                except ValueError:
                    pass
    cantidades_de = {}
    for i, (t, cuerpo) in ent.items():
        if t == "IFCELEMENTQUANTITY":
            a = _argumentos(cuerpo)
            refs = re.findall(r"#(\d+)", a[5] if len(a) > 5 else "")
            cantidades_de[i] = [areas_q[int(r)] for r in refs if int(r) in areas_q]
    area_de_objeto = {}
    for t, cuerpo in ent.values():
        if t == "IFCRELDEFINESBYPROPERTIES":
            a = _argumentos(cuerpo)
            if len(a) >= 6:
                definicion = re.findall(r"#(\d+)", a[5])
                if definicion and int(definicion[0]) in cantidades_de:
                    qs = cantidades_de[int(definicion[0])]
                    neta = next((v for n, v in qs if "net" in n.lower() and "floor" in n.lower()), None)
                    valor = neta if neta is not None else next((v for n, v in qs if "floor" in n.lower()), None)
                    if valor is not None:
                        for o in re.findall(r"#(\d+)", a[4]):
                            area_de_objeto[int(o)] = valor
    espacios = []
    for i, (t, cuerpo) in ent.items():
        if t == "IFCSPACE":
            a = _argumentos(cuerpo)
            nombre = _texto_ifc(a[2]) if len(a) > 2 else ""
            largo = _texto_ifc(a[7]) if len(a) > 7 else ""
            espacios.append((nombre, largo, area_de_objeto.get(i)))
    if espacios:
        con_area = [e for e in espacios if e[2] is not None]
        lineas.append(f"Espacios: {len(espacios)}" + (f"; con área en el IFC: {len(con_area)}, total "
                                                      f"{sum(e[2] for e in con_area):.2f} (unidades del modelo)"
                                                      if con_area else "; el IFC no trae áreas (expórtalo con "
                                                      "cantidades base para obtenerlas)"))
        for nombre, largo, area in espacios[:40]:
            lineas.append(f"- {nombre} {largo}".rstrip() + (f": {area:.2f}" if area is not None else ""))
        if len(espacios) > 40:
            lineas.append(f"(+{len(espacios) - 40} espacios más)")
    return "\n".join(lineas)


# ---------------------------------------------------------------- OCR de Windows
_PS_OCR = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Esperar($op, [Type]$tipo) { $t = $asTask.MakeGenericMethod($tipo).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$archivo = Esperar ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:LUNA_OCR_RUTA)) ([Windows.Storage.StorageFile])
$flujo = Esperar ($archivo.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$dec = Esperar ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($flujo)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bmp = Esperar ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$motor = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($motor -eq $null) { throw 'No hay idioma de OCR instalado en Windows' }
$res = Esperar ($motor.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
@{ idioma = $motor.RecognizerLanguage.LanguageTag; lineas = @($res.Lines | ForEach-Object { $_.Text }) } | ConvertTo-Json -Compress
"""


def ocr_windows(ruta, ejecutar=subprocess.run) -> str:
    if os.name != "nt" and ejecutar is subprocess.run:
        return "El OCR sin internet usa el de Windows: solo funciona en el PC con Windows."
    env = {**os.environ, "LUNA_OCR_RUTA": str(ruta)}
    try:
        r = ejecutar(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_OCR], capture_output=True,
                     timeout=60, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return "El OCR tardó demasiado (más de 60 s)."
    salida = (r.stdout or b"").decode("utf-8", "replace").strip()
    if r.returncode != 0 or not salida:
        error = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return "No pude leer el texto de la imagen: " + (error[-1][:200] if error else "error desconocido")
    try:
        d = json.loads(salida)
    except json.JSONDecodeError:
        return "No pude interpretar la respuesta del OCR de Windows."
    lineas = d.get("lineas") or []
    if isinstance(lineas, str):
        lineas = [lineas]
    if not lineas:
        return f"El OCR ({d.get('idioma', '?')}) no encontró texto en la imagen."
    texto = "\n".join(lineas)
    return f"Texto leído con el OCR de Windows ({d.get('idioma', '?')}, {len(lineas)} líneas, puede tener errores):\n" + texto[:6000]
