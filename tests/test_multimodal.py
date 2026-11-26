"""Fase 7: PowerPoint, IFC (BIM de Revit) y OCR de Windows, sin librerías nuevas."""
import json
import types
import zipfile

from lek.analisis import analizar_archivo
from lek.analisis.multimodal import analizar_ifc, analizar_pptx, ocr_windows

DIAPO = """<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
<p:cSld><p:spTree>
<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:t>{titulo}</a:t></a:r></a:p></p:txBody></p:sp>
<p:sp><p:nvSpPr><p:nvPr/></p:nvSpPr><p:txBody><a:p><a:r><a:t>{texto}</a:t></a:r></a:p></p:txBody></p:sp>
</p:spTree></p:cSld></p:sld>"""


def test_pptx(tmp_path):
    ruta = tmp_path / "entrega.pptx"
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("ppt/slides/slide2.xml", DIAPO.format(titulo="Programa", texto="Vivienda y equipamiento"))
        z.writestr("ppt/slides/slide1.xml", DIAPO.format(titulo="Centro de resiliencia", texto="Las Delicias"))
        z.writestr("ppt/slides/slide10.xml", DIAPO.format(titulo="Conclusiones", texto="Fin"))
        z.writestr("ppt/notesSlides/notesSlide1.xml", DIAPO.format(titulo="", texto="Decir el área total"))
        z.writestr("ppt/media/image1.png", b"x")
    r = analizar_pptx(ruta)
    assert "Diapositivas: 3. Imágenes y medios incrustados: 1." in r
    lineas = r.splitlines()
    assert lineas[2].startswith("1. Centro de resiliencia: Las Delicias") and "notas: Decir el área total" in lineas[2]
    assert lineas[4].startswith("3. Conclusiones")                    # orden numérico, no alfabético
    assert "Programa" in analizar_archivo(str(ruta), [tmp_path])


IFC = """ISO-10303-21;
HEADER;
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCPROJECT('0aaa',$,'Centro de Resiliencia Las Delicias',$,$,$,$,$,$);
#10=IFCBUILDINGSTOREY('1s',$,'Nivel 1',$,$,$,$,$,.ELEMENT.,0.);
#11=IFCBUILDINGSTOREY('2s',$,'Nivel 2',$,$,$,$,$,.ELEMENT.,3500.);
#20=IFCWALLSTANDARDCASE('w1',$,'Muro',$,$,$,$,$,$);
#21=IFCWALL('w2',$,'Muro',$,$,$,$,$,$);
#22=IFCDOOR('d1',$,'Puerta',$,$,$,$,$,$,$,$,$,$);
#23=IFCWINDOW('v1',$,'Ventana',$,$,$,$,$,$,$,$,$,$);
#30=IFCSPACE('s1',$,'101',$,$,$,$,'Sala de reuni\\X2\\00F3\\X0\\n',.ELEMENT.,.INTERNAL.,$);
#31=IFCSPACE('s2',$,'102',$,$,$,$,'Ba\\X2\\00F1\\X0\\o',.ELEMENT.,.INTERNAL.,$);
#40=IFCQUANTITYAREA('NetFloorArea',$,$,24.5,$);
#41=IFCELEMENTQUANTITY('q1',$,'BaseQuantities',$,$,(#40));
#42=IFCRELDEFINESBYPROPERTIES('r1',$,$,$,(#30),#41);
ENDSEC;
END-ISO-10303-21;
"""


def test_ifc_de_revit(tmp_path):
    ruta = tmp_path / "modelo.ifc"
    ruta.write_text(IFC, encoding="latin-1")
    r = analizar_ifc(ruta)
    assert "IFC IFC4" in r and "Proyecto: Centro de Resiliencia Las Delicias" in r
    assert "2 muros" in r and "1 puertas" in r and "1 ventanas" in r
    assert "Nivel 1 (0); Nivel 2 (3500)" in r
    assert "Espacios: 2; con área en el IFC: 1, total 24.50" in r
    assert "- 101 Sala de reunión: 24.50" in r and "- 102 Baño" in r
    assert "Solo lectura" in r


def test_ocr_windows_interpreta_la_respuesta(tmp_path):
    llamadas = []

    def falso(cmd, **kw):
        llamadas.append(kw["env"]["LUNA_OCR_RUTA"])
        salida = json.dumps({"idioma": "es-CO", "lineas": ["PLANTA PRIMER PISO", "ESC 1:100"]}).encode()
        return types.SimpleNamespace(returncode=0, stdout=salida, stderr=b"")
    r = ocr_windows(tmp_path / "plano.png", ejecutar=falso)
    assert "es-CO" in r and "PLANTA PRIMER PISO\nESC 1:100" in r and llamadas


def test_ocr_error_claro():
    falso = lambda cmd, **kw: types.SimpleNamespace(returncode=1, stdout=b"", stderr=b"x\nNo hay idioma de OCR")
    assert "No hay idioma de OCR" in ocr_windows("a.png", ejecutar=falso)
