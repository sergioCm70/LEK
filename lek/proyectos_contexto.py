"""Proyectos contextuales (LEK 2.0, fase 3): el contexto vivo de cada proyecto de Sergio.

No son los planes de tareas de lek/autonomia (esos ejecutan pasos). Aquí se guarda lo que hay que saber de un
proyecto para retomarlo sin releer todas las conversaciones:
- decisiones CONFIRMADAS, separadas de las PROPUESTAS pendientes (una idea nueva no reemplaza a una decisión);
- restricciones (geométricas, normativas, del profesor…), fechas, avances, problemas, archivos;
- historial: nada se borra; lo cambiado queda "reemplazado" y enlazado.

"Luna, trabajemos en Las Delicias" → trabajar_en activa el proyecto, y desde ahí cada mensaje queda asociado a él
y el cerebro recibe un resumen corto del proyecto en cada turno.
"""
from __future__ import annotations

import datetime
import json
import re

from .almacen import plano

TIPOS_ITEM = ("decision", "propuesta", "restriccion", "fecha", "avance", "problema", "archivo", "nota")
NOMBRES = {"decision": "Decisiones confirmadas", "propuesta": "Propuestas pendientes (NO confirmadas)",
           "restriccion": "Restricciones", "fecha": "Fechas", "avance": "Últimos avances",
           "problema": "Problemas abiertos", "archivo": "Archivos", "nota": "Notas"}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS proyectos_ctx(
    id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE, nombre TEXT, descripcion TEXT DEFAULT '',
    objetivo TEXT DEFAULT '', alias TEXT DEFAULT '[]', estado TEXT DEFAULT 'activo', creado TEXT, actualizado TEXT);
CREATE TABLE IF NOT EXISTS proyecto_items(
    id INTEGER PRIMARY KEY AUTOINCREMENT, proyecto_id INTEGER, tipo TEXT, contenido TEXT,
    estado TEXT DEFAULT 'vigente', fecha TEXT, actualizado TEXT, fuente TEXT DEFAULT '', reemplaza_id INTEGER,
    fecha_objetivo TEXT DEFAULT '');
"""


def slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", plano(texto)).strip("-")[:60]


def _ahora() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


class ProyectosContexto:
    def __init__(self, almacen):
        self.almacen = almacen
        with almacen._candado:
            almacen.con.executescript(ESQUEMA)
            columnas = {f[1] for f in almacen.con.execute("PRAGMA table_info(mensajes)").fetchall()}
            if "proyecto" not in columnas:          # migración reversible: solo agrega una columna
                almacen.con.execute("ALTER TABLE mensajes ADD COLUMN proyecto TEXT DEFAULT ''")
            almacen.con.commit()

    # ---------------------------------------------------------------- proyectos
    def crear(self, nombre: str, descripcion: str = "", objetivo: str = "", alias=None) -> dict:
        nombre = " ".join(str(nombre or "").split())[:80]
        s = slug(nombre)
        if not s:
            raise ValueError("El proyecto necesita un nombre")
        if self.obtener(s):
            raise ValueError(f"Ya existe el proyecto {nombre}")
        alias = [a for a in (alias or []) if isinstance(a, str) and a.strip()][:8]
        self.almacen._x("INSERT INTO proyectos_ctx(slug, nombre, descripcion, objetivo, alias, creado, actualizado) "
                        "VALUES (?,?,?,?,?,?,?)", (s, nombre, str(descripcion)[:500], str(objetivo)[:300],
                                                   json.dumps(alias, ensure_ascii=False), _ahora(), _ahora()))
        return self.obtener(s)

    def obtener(self, s: str) -> dict | None:
        filas = self.almacen._q("SELECT * FROM proyectos_ctx WHERE slug = ?", (s,))
        if not filas:
            return None
        p = filas[0]
        p["alias"] = json.loads(p.get("alias") or "[]")
        return p

    def todos(self) -> list:
        return [self.obtener(f["slug"]) for f in self.almacen._q("SELECT slug FROM proyectos_ctx ORDER BY actualizado DESC")]

    def buscar(self, texto: str) -> dict | None:
        """Por nombre, slug o alias (sin tildes); también si el texto contiene el nombre."""
        t = plano(texto or "").strip()
        if not t:
            return None
        candidatos = self.todos()
        for p in candidatos:
            if t in (p["slug"], plano(p["nombre"])) or t in [plano(a) for a in p["alias"]] or slug(t) == p["slug"]:
                return p
        for p in candidatos:
            nombres = [plano(p["nombre"])] + [plano(a) for a in p["alias"]]
            if any(n and (n in t or t in n) for n in nombres):
                return p
        return None

    def detectar(self, texto: str) -> dict | None:
        """Proyecto mencionado en un mensaje (nombre o alias como palabras completas)."""
        t = " " + re.sub(r"[^a-z0-9]+", " ", plano(texto or "")) + " "
        for p in self.todos():
            for n in [p["nombre"]] + p["alias"]:
                n2 = " " + re.sub(r"[^a-z0-9]+", " ", plano(n)).strip() + " "
                if n2.strip() and n2 in t:
                    return p
        return None

    # ---------------------------------------------------------------- proyecto activo
    def activar(self, s: str) -> dict:
        p = self.obtener(s)
        if not p:
            raise KeyError(s)
        self.almacen._fijar("proyecto_activo", s)
        self.almacen._x("UPDATE proyectos_ctx SET actualizado = ? WHERE slug = ?", (_ahora(), s))
        return p

    def desactivar(self) -> None:
        self.almacen._fijar("proyecto_activo", "")

    def activo(self) -> dict | None:
        s = self.almacen.meta("proyecto_activo", "") or ""
        return self.obtener(s) if s else None

    def etiquetar_mensaje(self, mensaje_id: int, s: str) -> None:
        self.almacen._x("UPDATE mensajes SET proyecto = ? WHERE id = ?", (s, int(mensaje_id)))

    # ---------------------------------------------------------------- contenido
    def registrar(self, s: str, tipo: str, contenido: str, reemplaza: int | None = None, fecha_objetivo: str = "",
                  fuente: str = "") -> dict:
        p = self.obtener(s)
        if not p:
            raise KeyError(s)
        if tipo not in TIPOS_ITEM:
            raise ValueError(f"tipo debe ser uno de: {', '.join(TIPOS_ITEM)}")
        contenido = " ".join(str(contenido or "").split())[:600]
        if not contenido:
            raise ValueError("Falta el contenido")
        if fecha_objetivo:
            datetime.date.fromisoformat(str(fecha_objetivo)[:10])
        if reemplaza:
            viejo = self.item(int(reemplaza))
            if not viejo or viejo["proyecto_id"] != p["id"]:
                raise KeyError(f"item {reemplaza}")
        cur = self.almacen._x("INSERT INTO proyecto_items(proyecto_id, tipo, contenido, fecha, actualizado, fuente, "
                              "reemplaza_id, fecha_objetivo) VALUES (?,?,?,?,?,?,?,?)",
                              (p["id"], tipo, contenido, _ahora(), _ahora(), str(fuente)[:80],
                               int(reemplaza) if reemplaza else None, str(fecha_objetivo or "")[:10]))
        if reemplaza:
            self.almacen._x("UPDATE proyecto_items SET estado = 'reemplazado', actualizado = ? WHERE id = ?",
                            (_ahora(), int(reemplaza)))
        self.almacen._x("UPDATE proyectos_ctx SET actualizado = ? WHERE id = ?", (_ahora(), p["id"]))
        return self.item(cur.lastrowid)

    def item(self, iid: int) -> dict | None:
        filas = self.almacen._q("SELECT * FROM proyecto_items WHERE id = ?", (int(iid),))
        return filas[0] if filas else None

    def aprobar(self, iid: int) -> dict:
        """Una propuesta pasa a ser decisión confirmada (la propuesta queda como 'aprobada')."""
        it = self.item(iid)
        if not it or it["tipo"] != "propuesta" or it["estado"] != "vigente":
            raise ValueError("Solo se aprueba una propuesta vigente")
        p = self.almacen._q("SELECT slug FROM proyectos_ctx WHERE id = ?", (it["proyecto_id"],))[0]["slug"]
        self.almacen._x("UPDATE proyecto_items SET estado = 'aprobada', actualizado = ? WHERE id = ?", (_ahora(), iid))
        return self.registrar(p, "decision", it["contenido"], fuente=f"propuesta #{iid} aprobada")

    def cerrar(self, iid: int, estado: str) -> dict:
        if estado not in ("descartada", "resuelto"):
            raise ValueError("estado: descartada o resuelto")
        if not self.item(iid):
            raise KeyError(iid)
        self.almacen._x("UPDATE proyecto_items SET estado = ?, actualizado = ? WHERE id = ?", (estado, _ahora(), iid))
        return self.item(iid)

    def items(self, s: str, tipo: str = "", incluir_historial: bool = False) -> list:
        p = self.obtener(s)
        if not p:
            return []
        sql, args = "SELECT * FROM proyecto_items WHERE proyecto_id = ?", [p["id"]]
        if tipo:
            sql += " AND tipo = ?"
            args.append(tipo)
        if not incluir_historial:
            sql += " AND estado = 'vigente'"
        return self.almacen._q(sql + " ORDER BY id", tuple(args))

    def conversaciones(self, s: str) -> dict:
        filas = self.almacen._q("SELECT count(*) AS n, max(fecha) AS ultima FROM mensajes WHERE proyecto = ?", (s,))
        return filas[0] if filas else {"n": 0, "ultima": None}

    # ---------------------------------------------------------------- resumen para retomar
    def resumen(self, s: str, corto: bool = False) -> str:
        p = self.obtener(s)
        if not p:
            return "No existe ese proyecto."
        lineas = [f"Proyecto {p['nombre']}" + (f": {p['descripcion']}" if p["descripcion"] else ""),]
        if p["objetivo"]:
            lineas.append(f"Objetivo: {p['objetivo']}")
        limite = 4 if corto else 12
        hoy = datetime.date.today().isoformat()
        for tipo in ("decision", "propuesta", "restriccion", "fecha", "problema", "avance", "archivo", "nota"):
            if corto and tipo in ("archivo", "nota"):
                continue
            filas = self.items(s, tipo)
            if tipo == "fecha":
                filas = sorted(filas, key=lambda f: f.get("fecha_objetivo") or "9999")
                filas = [f for f in filas if not f.get("fecha_objetivo") or f["fecha_objetivo"] >= hoy] or filas
            if tipo == "avance":
                filas = filas[-limite:]
            if filas:
                lineas.append(NOMBRES[tipo] + ": " + "; ".join(
                    f"#{f['id']} {f['contenido']}" + (f" ({f['fecha_objetivo']})" if f.get("fecha_objetivo") else "")
                    for f in filas[:limite]) + (f" (+{len(filas) - limite} más)" if len(filas) > limite else ""))
        c = self.conversaciones(s)
        if c.get("n"):
            lineas.append(f"Conversaciones asociadas: {c['n']} mensajes, la última el {str(c['ultima'])[:10]}.")
        if len(lineas) <= 2:
            lineas.append("Todavía no hay decisiones ni propuestas registradas.")
        return "\n".join(lineas)


def herramientas(pc: ProyectosContexto, buscar_conversaciones=None):
    def _f(nombre, descripcion, propiedades, requeridos):
        return {"type": "function", "function": {"name": nombre, "description": descripcion, "parameters": {
            "type": "object", "properties": propiedades, "required": requeridos}}}

    def _proyecto(nombre):
        p = pc.buscar(nombre) if nombre else pc.activo()
        if not p:
            raise KeyError(nombre or "ninguno activo")
        return p

    def trabajar_en(proyecto="", **_):
        p = pc.buscar(proyecto)
        if not p:
            p = pc.crear(proyecto)
            pc.activar(p["slug"])
            texto = f"No existía el proyecto {p['nombre']}: lo creé vacío y quedó activo."
            if buscar_conversaciones:
                previas = buscar_conversaciones(proyecto)
                if previas and not previas.startswith("No encontré"):
                    texto += ("\nConversaciones anteriores que lo mencionan (úsalas para proponer qué registrar, "
                              "pero NO las registres como decisiones sin que Sergio lo confirme):\n" + previas[:2500])
            return texto
        pc.activar(p["slug"])
        return "Proyecto activo.\n" + pc.resumen(p["slug"])

    def crear(nombre="", descripcion="", objetivo="", alias="", **_):
        lista = [a.strip() for a in str(alias or "").split(",") if a.strip()]
        try:
            p = pc.crear(nombre, descripcion, objetivo, lista)
        except ValueError as e:
            return f"No lo creé: {e}"
        pc.activar(p["slug"])
        return f"Proyecto {p['nombre']} creado y activo."

    def anotar(tipo="nota", contenido="", proyecto="", reemplaza="", fecha="", **_):
        try:
            p = _proyecto(proyecto)
            it = pc.registrar(p["slug"], tipo, contenido, int(reemplaza) if str(reemplaza).strip().isdigit() else None,
                              fecha)
        except (KeyError, ValueError) as e:
            return f"No lo anoté: {e}"
        aviso = " (queda como propuesta: no es una decisión hasta que Sergio la apruebe)" if tipo == "propuesta" else ""
        return f"Anotado en {p['nombre']} como {tipo} #{it['id']}{aviso}."

    def aprobar(id="", **_):
        try:
            it = pc.aprobar(int(id))
        except (ValueError, KeyError) as e:
            return f"No la aprobé: {e}"
        return f"La propuesta quedó como decisión confirmada #{it['id']}."

    def ver(proyecto="", **_):
        try:
            return pc.resumen(_proyecto(proyecto)["slug"])
        except KeyError:
            nombres = ", ".join(p["nombre"] for p in pc.todos()) or "ninguno"
            return f"No hay proyecto activo con ese nombre. Proyectos: {nombres}."

    def salir(**_):
        pc.desactivar()
        return "Listo, ya no hay proyecto activo."

    definiciones = [
        _f("trabajar_en", "Cuando Sergio dice que trabajen en un proyecto (ej. 'trabajemos en Las Delicias'): lo "
           "activa y devuelve su contexto (decisiones confirmadas, propuestas pendientes, restricciones, fechas, "
           "problemas, avances). Si no existe, lo crea vacío.",
           {"proyecto": {"type": "string", "description": "nombre del proyecto"}}, ["proyecto"]),
        _f("crear_proyecto", "Crea un proyecto contextual nuevo y lo deja activo.",
           {"nombre": {"type": "string"}, "descripcion": {"type": "string"}, "objetivo": {"type": "string"},
            "alias": {"type": "string", "description": "otros nombres separados por coma"}}, ["nombre"]),
        _f("anotar_en_proyecto", "Registra algo en el proyecto (el activo si no se dice otro). Tipo: 'decision' SOLO "
           "si Sergio la confirmó; una idea tuya o sin confirmar es 'propuesta'. También: restriccion, fecha, avance, "
           "problema, archivo, nota. Si cambia algo anterior, pasa su número en 'reemplaza'.",
           {"tipo": {"type": "string"}, "contenido": {"type": "string"}, "proyecto": {"type": "string"},
            "reemplaza": {"type": "string", "description": "número del item que reemplaza (opcional)"},
            "fecha": {"type": "string", "description": "AAAA-MM-DD para tipo fecha"}}, ["tipo", "contenido"]),
        _f("aprobar_propuesta", "Cuando Sergio aprueba una propuesta del proyecto: pasa a decisión confirmada.",
           {"id": {"type": "string", "description": "número de la propuesta"}}, ["id"]),
        _f("ver_proyecto", "Muestra el contexto de un proyecto (o del activo).",
           {"proyecto": {"type": "string", "description": "opcional"}}, []),
        _f("salir_de_proyecto", "Deja de trabajar en el proyecto activo.", {}, []),
    ]
    funciones = {"trabajar_en": trabajar_en, "crear_proyecto": crear, "anotar_en_proyecto": anotar,
                 "aprobar_propuesta": aprobar, "ver_proyecto": ver, "salir_de_proyecto": salir}
    return definiciones, funciones
