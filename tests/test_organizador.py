"""Pruebas del organizador: siempre en carpetas temporales, nunca en las carpetas reales."""
import builtins
import io
import os
import time

import pytest

from lek.almacen import Almacen
from lek.pc import organizador as org
from lek.pc.organizador import CARPETA_LUNA, Organizador

HACE_3_DIAS = time.time() - 3 * 86400


def archivo(carpeta, nombre, contenido="x", viejo=True):
    ruta = carpeta / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")
    if viejo:
        os.utime(ruta, (HACE_3_DIAS, HACE_3_DIAS))
    return ruta


def foto(carpeta):
    """Estado completo del árbol: ruta relativa -> contenido."""
    return {str(p.relative_to(carpeta)): (p.read_bytes() if p.is_file() else None)
            for p in sorted(carpeta.rglob("*"))}


@pytest.fixture
def entorno(tmp_path):
    desc, esc, docs = tmp_path / "Descargas", tmp_path / "Escritorio", tmp_path / "Documentos"
    for c in (desc, esc, docs):
        c.mkdir()
    almacen = Almacen(tmp_path / "datos")
    alias = {"Descargas": desc, "Escritorio": esc, "Documentos": docs}

    def crear(config=None, bloqueado=None):
        return Organizador(almacen, config, bloqueado=bloqueado or (lambda r: False), rutas_alias=alias)
    return desc, esc, docs, almacen, crear


def destino_de(desc, categoria, nombre):
    return desc / CARPETA_LUNA / categoria / nombre


def test_clasifica_y_mueve_archivos_sueltos(entorno):
    desc, esc, _, almacen, crear = entorno
    for n in ("casa.rvt", "casa.0001.rvt", "plano.pdf", "render.png", "modelo.glb", "planta.dwg",
              "D5_Installer.exe", "App.msix", "fotos.zip", "cuadro.xlsx", "raro.xyz"):
        archivo(desc, n)
    archivo(esc, "lamina.jpg")
    o = crear()
    a = o.analizar()
    assert a["resumen"]["total"] == 12
    assert len(a["plan"]) == 12
    informe = o.organizar()
    assert informe["movidos"] == 12 and informe["saltados"] == [] and informe["lote"]
    esperados = {"casa.rvt": "Revit", "casa.0001.rvt": "Respaldos de Revit", "plano.pdf": "PDF y documentos",
                 "render.png": "Imágenes y renders", "modelo.glb": "Modelos 3D", "planta.dwg": "CAD",
                 "D5_Installer.exe": "Instaladores", "App.msix": "Instaladores", "fotos.zip": "Comprimidos",
                 "cuadro.xlsx": "Hojas de cálculo", "raro.xyz": "Otros"}
    for nombre, cat in esperados.items():
        assert destino_de(desc, cat, nombre).read_text() == "x"
        assert not (desc / nombre).exists()
    assert (esc / CARPETA_LUNA / "Imágenes y renders" / "lamina.jpg").exists()
    assert almacen._q("SELECT count(*) AS n FROM auditoria WHERE accion = 'archivos_organizar'")[0]["n"] == 1


def test_nunca_sobrescribe_usa_sufijo(entorno):
    desc, _, _, _, crear = entorno
    archivo(desc / CARPETA_LUNA / "PDF y documentos", "plano.pdf", "viejo")
    archivo(desc / CARPETA_LUNA / "PDF y documentos", "plano (2).pdf", "viejo2")
    archivo(desc, "plano.pdf", "nuevo")
    o = crear()
    plan = o.analizar()["plan"]
    assert plan[0]["destino"].endswith("plano (3).pdf")
    o.organizar()
    base = desc / CARPETA_LUNA / "PDF y documentos"
    assert (base / "plano.pdf").read_text() == "viejo"
    assert (base / "plano (2).pdf").read_text() == "viejo2"
    assert (base / "plano (3).pdf").read_text() == "nuevo"


def test_nunca_borra_nada(entorno):
    desc, esc, _, _, crear = entorno
    contenidos = {f"a{i}.pdf": f"contenido {i}" for i in range(20)}
    for n, c in contenidos.items():
        archivo(desc, n, c)
    o = crear()
    o.organizar()
    todos = {p.name: p.read_text() for p in desc.rglob("*") if p.is_file()}
    assert todos == contenidos


def test_respeta_recientes_ocultos_accesos_y_temporales(entorno):
    desc, _, _, _, crear = entorno
    archivo(desc, "nuevo.pdf", viejo=False)            # menos de 24 h
    archivo(desc, ".oculto.pdf")
    archivo(desc, "Revit.lnk")
    archivo(desc, "pagina.url")
    archivo(desc, "bajando.zip.crdownload")
    archivo(desc, "~$informe.docx")
    archivo(desc, "plano.dwl")
    archivo(desc, "desktop.ini")
    os.symlink(desc / "Revit.lnk", desc / "enlace.pdf")
    antes = foto(desc)
    o = crear()
    a = o.analizar()
    assert a["plan"] == []
    motivos = {os.path.basename(s["ruta"]): s["motivo"] for s in a["saltados"]}
    assert "24 h" in motivos["nuevo.pdf"]
    assert set(motivos) >= {"nuevo.pdf", ".oculto.pdf", "Revit.lnk", "pagina.url", "bajando.zip.crdownload",
                            "~$informe.docx", "plano.dwl", "desktop.ini", "enlace.pdf"}
    # aunque alguien pase un plan a mano, se revalida y no se mueve nada
    informe = o.organizar([{"origen": str(desc / n)} for n in motivos])
    assert informe["movidos"] == 0
    assert foto(desc) == antes


def test_las_horas_minimas_no_se_pueden_bajar(entorno):
    desc, _, _, _, crear = entorno
    archivo(desc, "nuevo.pdf", viejo=False)
    o = crear({"horas_minimas": 0, "tope_lote": 99999})
    assert o.horas == 24 and o.tope == 500
    assert o.analizar()["plan"] == []


def test_salta_bloqueados(entorno):
    desc, _, _, _, crear = entorno
    archivo(desc, "abierto.rvt")
    archivo(desc, "libre.rvt")
    o = crear(bloqueado=lambda r: r.endswith("abierto.rvt"))
    informe = o.organizar()
    assert informe["movidos"] == 1
    assert informe["saltados"][0]["ruta"].endswith("abierto.rvt")
    assert "bloqueado" in informe["saltados"][0]["motivo"]
    assert (desc / "abierto.rvt").exists()


def test_carpetas_de_proyecto_y_subcarpetas_no_se_tocan(entorno):
    desc, _, _, _, crear = entorno
    proyecto = desc / "Taller 4"
    for n in ("centro.rvt", "vinculo.dwg", "sitio.skp", "notas.pdf"):
        archivo(proyecto, n)
    archivo(desc / "otra", "suelto_en_sub.pdf")
    archivo(desc, "suelto.pdf")
    antes_proyecto = foto(proyecto)
    o = crear()
    a = o.analizar()
    assert [p["ruta"] for p in a["carpetas_proyecto"]] == [str(proyecto)]
    assert [p["origen"] for p in a["plan"]] == [str(desc / "suelto.pdf")]
    informe = o.organizar([{"origen": str(proyecto / "centro.rvt")}, {"origen": str(desc / "otra" / "suelto_en_sub.pdf")}])
    assert informe["movidos"] == 0
    assert all("no está suelto" in s["motivo"] for s in informe["saltados"])
    o.organizar()
    assert foto(proyecto) == antes_proyecto
    assert (desc / "otra" / "suelto_en_sub.pdf").exists()


def test_plan_manipulado_no_sale_de_las_raices(entorno, tmp_path):
    desc, _, _, _, crear = entorno
    fuera = archivo(tmp_path / "fuera", "secreto.pdf")
    archivo(desc, "a.pdf")
    o = crear()
    informe = o.organizar([{"origen": str(fuera), "destino": str(desc / "robado.pdf")},
                           {"origen": str(desc / "a.pdf"), "destino": str(tmp_path / "fuera" / "a.pdf")}])
    assert fuera.exists() and not (desc / "robado.pdf").exists()
    assert informe["movidos"] == 1
    assert destino_de(desc, "PDF y documentos", "a.pdf").exists()   # el destino del plan se ignora
    assert not (tmp_path / "fuera" / "a.pdf").exists()


def test_documentos_solo_se_analiza_salvo_permiso(entorno):
    desc, _, docs, _, crear = entorno
    archivo(docs, "tesis.pdf")
    archivo(docs, "Proyecto.rvt")
    o = crear({"raices": ["Descargas", "Escritorio", "Documentos"]})   # pedirlo en raíces no basta
    a = o.analizar()
    assert a["resumen"]["total"] == 2 and a["plan"] == [] and a["solo_analisis"] == 2
    assert o.organizar([{"origen": str(docs / "tesis.pdf")}])["movidos"] == 0
    assert (docs / "tesis.pdf").exists()
    permitido = crear({"permitir_documentos": True})
    assert len(permitido.analizar()["plan"]) == 2


def test_rutas_protegidas_se_rechazan(entorno, tmp_path):
    _, _, _, almacen, _ = entorno
    for nombre in ("Windows", "Program Files", "AppData", "ProgramData", ".oculta"):
        carpeta = tmp_path / nombre / "x"
        archivo(carpeta, "a.pdf")
        o = Organizador(almacen, {"raices": [str(carpeta)], "solo_analizar": []}, bloqueado=lambda r: False)
        assert o.raices == []
        assert o.analizar()["plan"] == []
        assert (carpeta / "a.pdf").exists()
    assert org.es_ruta_protegida("C:\\" if os.name == "nt" else "/")


def test_tope_por_lote(entorno):
    desc, _, _, _, crear = entorno
    for i in range(7):
        archivo(desc, f"f{i}.pdf")
    o = crear({"tope_lote": 3})
    informe = o.organizar()
    assert informe["movidos"] == 3 and informe["pendientes"] == 4
    assert len(o.analizar()["plan"]) == 4


def test_analizar_no_abre_ni_cambia_nada(entorno, monkeypatch):
    desc, esc, _, _, crear = entorno
    for i in range(5):
        archivo(desc, f"a{i}.rvt")
    archivo(desc / "sub", "b.dwg")
    antes = foto(desc)
    o = crear()

    def prohibido(*a, **k):
        raise AssertionError("analizar no debe abrir archivos")
    monkeypatch.setattr(builtins, "open", prohibido)
    monkeypatch.setattr(io, "open", prohibido)
    monkeypatch.setattr(os, "rename", prohibido)
    monkeypatch.setattr(os, "link", prohibido)
    monkeypatch.setattr(os, "makedirs", prohibido)
    a = o.analizar()
    monkeypatch.undo()
    assert len(a["plan"]) == 5
    assert foto(desc) == antes


def test_limite_de_archivos(entorno):
    desc, _, _, _, crear = entorno
    for i in range(30):
        archivo(desc, f"a{i}.pdf")
    a = crear({"limite_archivos": 10}).analizar()
    assert a["truncado"] and a["resumen"]["total"] == 10


def test_deshacer_restaura_exacto(entorno):
    desc, esc, _, almacen, crear = entorno
    archivo(desc, "casa.rvt", "modelo")
    archivo(esc, "foto.png", "pixeles")
    antes_d, antes_e = foto(desc), foto(esc)
    o = crear()
    informe = o.organizar()
    movs = o.movimientos()
    assert len(movs) == 2 and not any(m["deshecho"] for m in movs)
    r = o.deshacer(movs[0]["id"])
    assert r["ok"]
    assert not o.deshacer(movs[0]["id"])["ok"]          # dos veces no
    lote = o.deshacer_lote(informe["lote"])
    assert lote["deshechos"] == 1 and lote["fallidos"] == []
    assert (desc / "casa.rvt").read_text() == "modelo" and (esc / "foto.png").read_text() == "pixeles"
    # quedan las carpetas vacías de Luna (nunca borra), pero los archivos están exactamente donde estaban
    assert {k: v for k, v in foto(desc).items() if v is not None} == {k: v for k, v in antes_d.items() if v is not None}
    assert {k: v for k, v in foto(esc).items() if v is not None} == {k: v for k, v in antes_e.items() if v is not None}
    assert all(m["deshecho"] for m in o.movimientos())
    assert almacen._q("SELECT count(*) AS n FROM auditoria WHERE accion = 'archivos_deshacer'")[0]["n"] == 2


def test_deshacer_no_sobrescribe_si_el_origen_ya_existe(entorno):
    desc, _, _, _, crear = entorno
    archivo(desc, "plano.pdf", "original")
    o = crear()
    o.organizar()
    archivo(desc, "plano.pdf", "otro nuevo")
    m = o.movimientos()[0]
    r = o.deshacer(m["id"])
    assert not r["ok"] and "no lo sobrescribo" in r["mensaje"]
    assert (desc / "plano.pdf").read_text() == "otro nuevo"
    assert destino_de(desc, "PDF y documentos", "plano.pdf").read_text() == "original"
    assert not o.movimientos()[0]["deshecho"]


def test_forma_exacta_de_la_api(entorno):
    desc, _, _, _, crear = entorno
    archivo(desc, "a.pdf")
    o = crear()
    e = o.api_estado()
    assert set(e) == {"estado", "resumen", "plan", "movimientos"} and e["estado"] == "sin analizar"
    a = o.api_analizar()
    assert set(a["resumen"]) == {"total", "por_tipo"} and a["resumen"]["por_tipo"] == {"PDF y documentos": 1}
    assert set(a["plan"][0]) == {"origen", "destino", "motivo"}
    r = o.api_organizar()
    assert set(r) == {"estado", "resumen", "plan", "movimientos"}
    assert set(r["movimientos"][0]) == {"id", "fecha", "origen", "destino", "deshecho"}
    d = o.api_deshacer(r["movimientos"][0]["id"])
    assert d["movimientos"][0]["deshecho"] is True and (desc / "a.pdf").exists()


def test_herramientas_para_luna(entorno):
    desc, _, _, _, crear = entorno
    archivo(desc, "a.pdf")
    o = crear()
    assert {h["function"]["name"] for h in org.HERRAMIENTAS} == {"analizar_archivos", "organizar_archivos",
                                                                  "deshacer_organizacion"}
    assert "1 archivos sueltos" in o.ejecutar("analizar_archivos")
    assert "Organicé 1" in o.ejecutar("organizar_archivos")
    assert "devueltos" in o.ejecutar("deshacer_organizacion", {})
    assert (desc / "a.pdf").exists()
