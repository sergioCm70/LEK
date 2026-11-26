"""Pruebas de lek/analisis: análisis determinista de archivos, tablas, comparación y calculadora.

Todos los archivos se generan en tmp: PDF a mano / con pypdf, DOCX con python-docx, CSV, XLSX mínimo
con zipfile, PNG/JPEG/GLB mínimos escritos byte a byte.
"""
import json
import os
import pathlib
import struct
import sys
import zipfile
import zlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from lek import analisis  # noqa: E402
from lek.analisis import archivos, tablas  # noqa: E402
from lek.analisis.tablas import ErrorAnalisis, Plazo  # noqa: E402


# ---------------------------------------------------------------- generadores de archivos
def pdf_con_texto(ruta, paginas, ancho=595, alto=842):
    """PDF mínimo válido con una línea de texto por renglón (Helvetica)."""
    objetos = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lineas in paginas:
        flujo = "BT /F1 12 Tf 50 780 Td 14 TL " + " ".join(
            f"({l.replace('(', '').replace(')', '')}) Tj T*" for l in lineas) + " ET"
        objetos.append(f"<< /Length {len(flujo.encode('latin-1'))} >>\nstream\n{flujo}\nendstream")
        cont = len(objetos)
        objetos.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {ancho} {alto}] "
                       f"/Resources << /Font << /F1 3 0 R >> >> /Contents {cont} 0 R >>")
        kids.append(f"{len(objetos)} 0 R")
    objetos[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    salida, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objetos, 1):
        offsets.append(len(salida))
        salida += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    salida += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    pathlib.Path(ruta).write_bytes(salida)


def pdf_en_blanco(ruta, paginas=2, ancho=2384, alto=1684):
    from pypdf import PdfWriter
    w = PdfWriter()
    for _ in range(paginas):
        w.add_blank_page(width=ancho, height=alto)
    with open(ruta, "wb") as f:
        w.write(f)


def xlsx_minimo(ruta, hojas):
    """hojas: {nombre: [[valores]]}. Textos como sharedStrings, números como <v>, '=f|v' como fórmula con valor."""
    compartidas, indice = [], {}

    def celda(ref, v):
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"><v>{v}</v></c>'
        if isinstance(v, str) and v.startswith("=") and "|" in v:
            f, val = v[1:].split("|")
            return f'<c r="{ref}"><f>{f}</f><v>{val}</v></c>'
        if isinstance(v, str) and v.startswith("inline:"):
            return f'<c r="{ref}" t="inlineStr"><is><t>{v[7:]}</t></is></c>'
        if v not in indice:
            indice[v] = len(compartidas)
            compartidas.append(v)
        return f'<c r="{ref}" t="s"><v>{indice[v]}</v></c>'

    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    nr = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        hojas_xml, rels = [], []
        for n, (nombre, filas) in enumerate(hojas.items(), 1):
            hojas_xml.append(f'<sheet name="{nombre}" sheetId="{n}" r:id="rId{n}"/>')
            rels.append(f'<Relationship Id="rId{n}" Type="worksheet" Target="worksheets/sheet{n}.xml"/>')
            xml_filas = []
            for i, fila in enumerate(filas, 1):
                celdas = "".join(celda(f"{chr(65 + j)}{i}", v) for j, v in enumerate(fila) if v is not None)
                xml_filas.append(f'<row r="{i}">{celdas}</row>')
            z.writestr(f"xl/worksheets/sheet{n}.xml", f'<worksheet {ns}><sheetData>{"".join(xml_filas)}</sheetData></worksheet>')
        z.writestr("xl/workbook.xml", f'<workbook {ns} {nr}><sheets>{"".join(hojas_xml)}</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(rels) + "</Relationships>")
        z.writestr("xl/sharedStrings.xml", f'<sst {ns}>' + "".join(f"<si><t>{s}</t></si>" for s in compartidas) + "</sst>")


def png_minimo(ruta, ancho=3, alto=2):
    def trozo(tipo, datos):
        return struct.pack(">I", len(datos)) + tipo + datos + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)
    crudo = b"".join(b"\x00" + b"\xff\x00\x00" * ancho for _ in range(alto))
    pathlib.Path(ruta).write_bytes(b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0))
                                   + trozo(b"IDAT", zlib.compress(crudo)) + trozo(b"IEND", b""))


def jpeg_cabecera(ruta, ancho=640, alto=480):
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, alto, ancho, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    pathlib.Path(ruta).write_bytes(b"\xff\xd8" + app0 + sof + b"\xff\xd9")


def glb_minimo(ruta):
    g = {"asset": {"version": "2.0", "generator": "Revit2GLB"},
         "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "Losa"}, {"mesh": 1}],
         "meshes": [{"name": "Losa", "primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]},
                    {"name": "Muro", "primitives": [{"attributes": {"POSITION": 2}}]}],
         "materials": [{"name": "Concreto"}, {"name": "Vidrio"}],
         "accessors": [{"count": 4, "type": "VEC3", "componentType": 5126, "min": [0, 0, 0], "max": [10, 0.3, 8]},
                       {"count": 6, "type": "SCALAR", "componentType": 5123},
                       {"count": 9, "type": "VEC3", "componentType": 5126, "min": [-1, 0, 0], "max": [0, 3, 8]}]}
    js = json.dumps(g).encode()
    js += b" " * (-len(js) % 4)
    binario = b"\x00" * 16
    cuerpo = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(binario), 0x004E4942) + binario
    pathlib.Path(ruta).write_bytes(b"glTF" + struct.pack("<II", 2, 12 + len(cuerpo)) + cuerpo)


CUADRO = """CUADRO DE ÁREAS - CENTRO DE RESILIENCIA;;;
Piso;Espacio;Área (m²);Uso
1;Hall;12,5;comunal
1;Aula;30,25;educativo
2;Aula 2;30,25;educativo
2;Apartamento;1.020,5;vivienda
3;Terraza;45;comunal
TOTAL;;1.138,5;
"""


@pytest.fixture
def carpeta(tmp_path):
    raiz = tmp_path / "docs"
    raiz.mkdir()
    return raiz


@pytest.fixture
def fn(carpeta):
    return analisis.crear_funciones([carpeta])


# ---------------------------------------------------------------- seguridad de rutas
def test_rechaza_rutas_fuera_de_las_raices(carpeta, tmp_path, fn):
    fuera = tmp_path / "secreto.txt"
    fuera.write_text("clave", encoding="utf-8")
    assert "fuera de las carpetas permitidas" in fn["analizar_archivo"](ruta=str(fuera))
    assert "fuera de las carpetas permitidas" in fn["analizar_archivo"](ruta="../secreto.txt")
    assert "No encontré" in fn["analizar_archivo"](ruta="no_existe.pdf")
    assert "Falta la ruta" in fn["analizar_archivo"](ruta="")
    assert "No hay carpetas permitidas" in analisis.crear_funciones([])["analizar_archivo"](ruta=str(fuera))


def test_enlace_simbolico_que_escapa_se_rechaza(carpeta, tmp_path, fn):
    fuera = tmp_path / "secreto.txt"
    fuera.write_text("clave", encoding="utf-8")
    try:
        os.symlink(fuera, carpeta / "atajo.txt")
    except (OSError, NotImplementedError):
        pytest.skip("este sistema no permite enlaces simbólicos")
    assert "fuera de las carpetas permitidas" in fn["analizar_archivo"](ruta="atajo.txt")


def test_busca_por_nombre_y_limita_tamano(carpeta, fn):
    (carpeta / "U" / "Taller").mkdir(parents=True)
    (carpeta / "U" / "Taller" / "Memoria.md").write_text("# Memoria\n## Lugar\ntexto", encoding="utf-8")
    r = fn["analizar_archivo"](ruta="memoria.md")
    assert "Memoria.md" in r and "# Memoria" in r
    grande = carpeta / "grande.csv"
    with open(grande, "wb") as f:
        f.truncate(archivos.MAX_BYTES + 1)
    assert "máximo para analizar es 50 MB" in fn["analizar_archivo"](ruta="grande.csv")


def test_plazo_corta_analisis_largos(carpeta):
    (carpeta / "c.csv").write_text(CUADRO, encoding="utf-8")
    with pytest.raises(ErrorAnalisis, match="límite"):
        tablas.calcular_tabla(carpeta / "c.csv", "sumar Área", plazo=Plazo(-1))


# ---------------------------------------------------------------- CSV y calcular_tabla
def test_analiza_csv_con_coma_decimal_y_fila_total(carpeta, fn):
    (carpeta / "cuadro.csv").write_text(CUADRO, encoding="utf-8")
    r = fn["analizar_archivo"](ruta="cuadro.csv")
    assert "5 filas de datos × 4 columnas (encabezados en la fila 2)" in r
    assert "Área (m²): número; 5 valores; suma 1138.5, media 227.7, mín 12.5, máx 1020.5" in r
    assert "Uso: texto; 3 distintos" in r
    assert "Fila de total del archivo" in r
    assert len(r) <= 2500


def test_calcular_tabla_suma_por_piso_en_frase(carpeta, fn):
    (carpeta / "cuadro.csv").write_text(CUADRO, encoding="utf-8")
    r = fn["calcular_tabla"](ruta="cuadro.csv", operacion="suma el área por piso")
    assert " - 1: 42.75 (2 valores)" in r
    assert " - 2: 1050.75 (2 valores)" in r
    assert " - 3: 45 (1 valores)" in r
    assert "General: 1138.5" in r
    assert "excluí 1 fila(s) de TOTAL" in r


def test_calcular_tabla_verifica_total_declarado(carpeta, fn):
    (carpeta / "cuadro.csv").write_text(CUADRO, encoding="utf-8")
    r = fn["calcular_tabla"](ruta="cuadro.csv", operacion="sumar", columna="area")
    assert "Suma de 'Área (m²)': 1138.5 (5 valores)" in r
    assert "dice 1138.5: coincide" in r
    (carpeta / "mal.csv").write_text(CUADRO.replace("1.138,5", "1.100"), encoding="utf-8")
    assert "NO coincide (diferencia 38.5)" in fn["calcular_tabla"](ruta="mal.csv", operacion="sumar área")


def test_calcular_tabla_filtros_conteo_y_extremos(carpeta, fn):
    (carpeta / "cuadro.csv").write_text(CUADRO, encoding="utf-8")
    r = fn["calcular_tabla"](ruta="cuadro.csv", operacion="contar por uso donde piso >= 2")
    assert "3 de 5 filas" in r and " - comunal: 1" in r and " - vivienda: 1" in r and "General: 3" in r
    r = fn["calcular_tabla"](ruta="cuadro.csv", operacion="promedio", columna="Área", filtro="Uso = educativo")
    assert "Promedio de 'Área (m²)': 30.25" in r
    assert "Máximo de 'Área (m²)': 1020.5" in fn["calcular_tabla"](ruta="cuadro.csv", operacion="máximo área")
    r = fn["calcular_tabla"](ruta="cuadro.csv", operacion="listar", filtro="uso contiene educ y piso = 2")
    assert "Espacio: Aula 2" in r and "Hall" not in r
    assert "Piso, Espacio, Área (m²), Uso" in fn["calcular_tabla"](ruta="cuadro.csv", operacion="columnas")


def test_calcular_tabla_errores_claros(carpeta, fn):
    (carpeta / "cuadro.csv").write_text(CUADRO, encoding="utf-8")
    assert "No hay una columna 'altura'" in fn["calcular_tabla"](ruta="cuadro.csv", operacion="sumar altura")
    assert "Operación no reconocida" in fn["calcular_tabla"](ruta="cuadro.csv", operacion="bailar")
    assert "No entendí el filtro" in fn["calcular_tabla"](ruta="cuadro.csv", operacion="contar", filtro="piso")


def test_numeros_con_formatos_variados():
    a = tablas.a_numero
    assert a("1.234,56") == tablas.Decimal("1234.56")
    assert a("1,234.56") == tablas.Decimal("1234.56")
    assert a("12,5 m²") == tablas.Decimal("12.5")
    assert a("$ 3.000.000") == tablas.Decimal("3000000")
    assert a("(15)") == tablas.Decimal("-15")
    assert a("1.234", "coma") == tablas.Decimal("1234")
    assert a("hola") is None and a("") is None and a("N/A") is None


# ---------------------------------------------------------------- XLSX sin openpyxl
def test_xlsx_minimo_con_lector_zip(carpeta, fn):
    xlsx_minimo(carpeta / "areas.xlsx", {
        "Portada": [["Proyecto"], ["Centro de resiliencia"]],
        "Áreas": [["CUADRO DE ÁREAS"], ["Piso", "Espacio", "Área"], [1, "Hall", 12.5], [1, "inline:Aula", 30.25],
                  [2, "Vivienda", "=SUM(1)|60"], ["TOTAL", None, 102.75]]})
    hojas = tablas.leer_hojas(carpeta / "areas.xlsx", usar_openpyxl=False)
    assert [h[0] for h in hojas] == ["Portada", "Áreas"]
    assert hojas[1][1][3] == ["1", "Aula", "30.25"]
    r = fn["analizar_archivo"](ruta="areas.xlsx")
    assert "Hojas: 2 (Portada, Áreas)" in r
    assert "[Áreas] 3 filas de datos × 3 columnas (encabezados en la fila 2)" in r
    assert "suma 102.75" in r
    r = fn["calcular_tabla"](ruta="areas.xlsx", operacion="sumar Área por Piso", hoja="areas")
    assert " - 1: 42.75" in r and " - 2: 60" in r and "General: 102.75" in r
    assert "No hay hoja 'Fachadas'" in fn["calcular_tabla"](ruta="areas.xlsx", operacion="sumar área", hoja="Fachadas")


def test_xlsx_danado_y_xls_antiguo(carpeta, fn):
    (carpeta / "roto.xlsx").write_bytes(b"esto no es un zip")
    assert "dañado" in fn["analizar_archivo"](ruta="roto.xlsx")
    (carpeta / "viejo.xls").write_bytes(b"\xd0\xcf\x11\xe0")
    assert ".xls antiguos" in fn["analizar_archivo"](ruta="viejo.xls")


# ---------------------------------------------------------------- PDF
def test_pdf_con_texto_paginas_palabras_y_titulos(carpeta, fn):
    pdf_con_texto(carpeta / "memoria.pdf", [["MEMORIA DESCRIPTIVA", "El proyecto se ubica en Las Delicias."],
                                            ["1. Analisis del lugar", "Clima calido y humedo de Palmira."]])
    r = fn["analizar_archivo"](ruta="memoria.pdf")
    assert "Páginas: 2" in r
    assert "Palabras: 19" in r
    assert "2 × A4 vertical" in r
    assert "MEMORIA DESCRIPTIVA" in r and "1. Analisis del lugar" in r
    assert "ESCANEADO" not in r


def test_pdf_escaneado_y_tamano_de_lamina(carpeta, fn):
    pdf_en_blanco(carpeta / "lamina.pdf")             # 2384×1684 pt = A1 horizontal
    r = fn["analizar_archivo"](ruta="lamina.pdf")
    assert "Páginas: 2" in r and "ESCANEADO" in r and "A1 horizontal" in r


# ---------------------------------------------------------------- DOCX
def test_docx_encabezados_parrafos_y_tablas(carpeta, fn):
    import docx
    d = docx.Document()
    d.add_heading("Memoria del proyecto", level=1)
    d.add_paragraph("Primer párrafo del documento.")
    d.add_heading("Programa arquitectónico", level=2)
    d.add_paragraph("Segundo párrafo.")
    t = d.add_table(rows=4, cols=2)
    for i, (a, b) in enumerate([("Espacio", "Área"), ("Aula", "30,5"), ("Hall", "12,25"), ("Baño", "6")]):
        t.cell(i, 0).text, t.cell(i, 1).text = a, b
    d.save(carpeta / "memoria.docx")
    r = fn["analizar_archivo"](ruta="memoria.docx")
    assert "Párrafos con texto: 4" in r
    assert "Encabezados: 2" in r and "Tablas: 1" in r
    assert " - Memoria del proyecto" in r and "Programa arquitectónico" in r
    assert "Tabla 1: 4 filas × 2 columnas" in r
    assert "Área: suma 48.75" in r


# ---------------------------------------------------------------- imágenes y GLB
def test_png_y_jpeg_sin_pillow(carpeta, fn):
    png_minimo(carpeta / "render.png", 3, 2)
    r = archivos.analizar_imagen(carpeta / "render.png", Plazo(), usar_pillow=False)
    assert "Imagen PNG" in r and "3 × 2 px" in r and "RGB, 8 bits/canal" in r
    jpeg_cabecera(carpeta / "foto.jpg", 640, 480)
    r = archivos.analizar_imagen(carpeta / "foto.jpg", Plazo(), usar_pillow=False)
    assert "Imagen JPEG" in r and "640 × 480 px" in r and "0.31 megapíxeles" in r
    assert "3 × 2 px" in fn["analizar_archivo"](ruta="render.png")   # con o sin Pillow instalado


def test_glb_conteos_triangulos_y_extension(carpeta, fn):
    glb_minimo(carpeta / "modelo.glb")
    r = fn["analizar_archivo"](ruta="modelo.glb")
    assert "GLB (glTF binario) versión 2" in r and "coincide" in r
    assert "2 nodos, 2 mallas, 2 materiales" in r
    assert "Primitivas: 2; vértices: 13; triángulos: 5" in r
    assert "11 × 3 × 8" in r
    assert "Concreto, Vidrio" in r and "Revit2GLB" in r
    (carpeta / "malo.glb").write_bytes(b"NOPE" + b"\x00" * 20)
    assert "firma 'glTF'" in fn["analizar_archivo"](ruta="malo.glb")


# ---------------------------------------------------------------- comparar
def test_comparar_textos(carpeta, fn):
    (carpeta / "v1.txt").write_text("Introducción\nEl lote mide 20 m.\nConclusión", encoding="utf-8")
    (carpeta / "v2.txt").write_text("Introducción\nEl lote mide 25 m.\nConclusión\nAnexos", encoding="utf-8")
    r = fn["comparar_archivos"](ruta_a="v1.txt", ruta_b="v2.txt")
    assert "líneas quitadas: 1; líneas nuevas: 2" in r
    assert "- El lote mide 20 m." in r and "+ El lote mide 25 m." in r and "+ Anexos" in r
    (carpeta / "copia.txt").write_bytes((carpeta / "v1.txt").read_bytes())
    assert "IDÉNTICOS" in fn["comparar_archivos"](ruta_a="v1.txt", ruta_b="copia.txt")


def test_comparar_tablas_por_clave(carpeta, fn):
    (carpeta / "a.csv").write_text("Espacio;Área\nHall;12,5\nAula;30\nBaño;6\n", encoding="utf-8")
    (carpeta / "b.csv").write_text("Espacio,Área,Piso\nHall,12.5,1\nAula,32,1\nBodega,5,2\n", encoding="utf-8")
    r = fn["comparar_archivos"](ruta_a="a.csv", ruta_b="b.csv")
    assert "filas: A 3, B 3" in r
    assert "Columnas solo en B: Piso" in r
    assert "Filas solo en A (1) por 'Espacio': Baño" in r and "Filas solo en B (1) por 'Espacio': Bodega" in r
    assert "Aula · Área: 30 → 32" in r
    assert "Hall · Área" not in r                       # 12,5 y 12.5 son el mismo número
    assert "Suma de 'Área': A 48.5, B 49.5 (diferencia 1)" in r


def test_comparar_pdf_y_docx(carpeta, fn):
    pdf_con_texto(carpeta / "a.pdf", [["MEMORIA", "Area total 500 m2"]])
    pdf_con_texto(carpeta / "b.pdf", [["MEMORIA", "Area total 520 m2"]])
    r = fn["comparar_archivos"](ruta_a="a.pdf", ruta_b="b.pdf")
    assert "- Area total 500 m2" in r and "+ Area total 520 m2" in r
    import docx
    for nombre, texto in (("a.docx", "Lote de 20 m"), ("b.docx", "Lote de 25 m")):
        d = docx.Document()
        d.add_heading("Memoria", level=1)
        d.add_paragraph(texto)
        d.save(carpeta / nombre)
    r = fn["comparar_archivos"](ruta_a="a.docx", ruta_b="b.docx")
    assert "- Lote de 20 m" in r and "+ Lote de 25 m" in r and "líneas quitadas: 1; líneas nuevas: 1" in r


# ---------------------------------------------------------------- calculadora
@pytest.mark.parametrize("expresion,esperado", [
    ("2 + 3 * 4", "14"), ("(2 + 3) * 4", "20"), ("10 / 4", "2.5"), ("2 ** 10", "1024"), ("2^10", "1024"),
    ("17 % 5", "2"), ("0.1 + 0.2", "0.3"), ("12,5 * 3", "37.5"), ("1.234,5 * 2", "2469"),
    ("sqrt(16) + 12,5", "16.5"), ("max(1,5)", "5"), ("round(10/3, 2)", "3.33"), ("pi * 2**2", "12.5663706144"),
    ("hypot(3, 4)", "5"), ("-3 + abs(-7)", "4"), ("sum([1, 2, 3.5])", "6.5"), ("factorial(10)", "3628800"),
])
def test_evaluar_correcto(expresion, esperado):
    assert analisis.evaluar(expresion).endswith("= " + esperado)


@pytest.mark.parametrize("expresion,mensaje", [
    ("__import__('os').system('dir')", "no permitid"), ("open('x')", "no permitida"),
    ("(1).__class__", "no permitido"), ("lambda: 1", "no permitido"), ("x + 1", "no permitido"),
    ("2 ** 99999999", "demasiado grande"), ("9 ** 9 ** 9", "demasiado grande"), ("factorial(100000)", "demasiado grande"),
    ("1 / 0", "División por cero"), ("sqrt(-1)", "no válida"), ("", "vacía"), ("1 +", "No entendí"),
    ("'a' * 3", "no permitido"), ("[1] * 10**9", "listas"),
])
def test_evaluar_rechaza_lo_peligroso(expresion, mensaje):
    r = analisis.crear_funciones([])["evaluar"](expresion=expresion)
    assert r.startswith("No pude") and mensaje in r


# ---------------------------------------------------------------- integración con servidor.py
def test_herramientas_con_formato_de_servidor_y_privacidad():
    nombres = [h["function"]["name"] for h in analisis.HERRAMIENTAS]
    assert nombres == ["analizar_archivo", "calcular_tabla", "comparar_archivos", "evaluar", "leer_texto_imagen"]
    for h in analisis.HERRAMIENTAS:
        assert h["type"] == "function" and h["function"]["parameters"]["type"] == "object"
        assert set(h["function"]["parameters"]["required"]) <= set(h["function"]["parameters"]["properties"])
    assert analisis.HERRAMIENTAS_PRIVADAS == {"analizar_archivo": "documentos", "calcular_tabla": "documentos",
                                             "comparar_archivos": "documentos", "leer_texto_imagen": "documentos"}
    assert set(analisis.crear_funciones([])) == set(nombres)


def test_funciones_nunca_lanzan_y_aceptan_argumentos_extra(carpeta, fn):
    (carpeta / "raro.bin").write_bytes(bytes(range(256)) * 10)
    assert "no soportado" in fn["analizar_archivo"](ruta="raro.bin", otro="x")
    (carpeta / "roto.pdf").write_bytes(b"%PDF-1.4 basura")
    assert fn["analizar_archivo"](ruta="roto.pdf").startswith(("No pude", "Archivo"))
    raices = [carpeta]
    dinamicas = analisis.crear_funciones(lambda: raices)
    (carpeta / "n.txt").write_text("hola mundo", encoding="utf-8")
    assert "palabras: 2" in dinamicas["analizar_archivo"](ruta="n.txt")


def test_informe_largo_se_recorta(carpeta, fn):
    cols = ";".join(f"Columna número {i}" for i in range(60))
    filas = "\n".join(";".join(str(i * j) for j in range(60)) for i in range(300))
    (carpeta / "ancha.csv").write_text(cols + "\n" + filas, encoding="utf-8")
    r = fn["analizar_archivo"](ruta="ancha.csv")
    assert len(r) <= 2500 and "300 filas de datos × 60 columnas" in r
