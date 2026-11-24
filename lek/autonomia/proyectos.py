"""Objetivos, proyectos y tareas persistentes de LUNA.

Un OBJETIVO es lo que Sergio quiere lograr (con criterio de éxito, prioridad y fecha límite).
planificar() le pide al cerebro un plan en JSON y crea un PROYECTO con TAREAS y dependencias.
El plan queda "propuesto" hasta que el usuario lo aprueba; solo entonces el programador
(lek/autonomia/programador.py) empieza a ejecutar tareas, de una en una.

Todo vive en el mismo luna.db del Almacen (misma conexión y mismo candado), así que sobrevive
a reinicios. Cada cambio de estado deja un registro en la tabla eventos.

Estados de tarea:
    propuesta -> lista -> en_curso -> (esperando_aprobacion | bloqueada) -> completada | fallida | cancelada
Las transiciones que no están en TRANSICIONES se rechazan con TransicionInvalida.

Nivel de autorización de cada tarea:
    0 = la hace sola, 1 = la hace sola y deja aviso, 2 = necesita aprobación del usuario cada vez.
Una aprobación de nivel 2 se gasta ("usada") ANTES de ejecutar: nunca se reutiliza, así que una
acción de nivel 2 nunca se repite sin una aprobación nueva del usuario.
"""
import collections
import datetime
import json
import re

ESQUEMA = """
CREATE TABLE IF NOT EXISTS objetivos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    criterio_exito TEXT DEFAULT '',
    prioridad INTEGER NOT NULL DEFAULT 3,     -- 1 = máxima, 5 = mínima
    fecha_limite TEXT DEFAULT '',             -- AAAA-MM-DD o vacío
    origen TEXT DEFAULT 'usuario',            -- 'usuario', 'luna'
    estado TEXT NOT NULL DEFAULT 'activo',    -- activo, completado, cancelado
    creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proyectos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    objetivo_id INTEGER,
    titulo TEXT NOT NULL,
    plan TEXT DEFAULT '{}',                   -- JSON del plan tal como se aceptó
    presupuesto_usd REAL NOT NULL DEFAULT 0,
    estado TEXT NOT NULL DEFAULT 'propuesto', -- propuesto, activo, pausado, completado, cancelado
    creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tareas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proyecto_id INTEGER NOT NULL,
    madre_id INTEGER,
    titulo TEXT NOT NULL,
    tipo TEXT DEFAULT 'general',
    depende_de TEXT NOT NULL DEFAULT '[]',    -- JSON: ids de tareas
    nivel_autorizacion INTEGER NOT NULL DEFAULT 0,
    estado TEXT NOT NULL DEFAULT 'propuesta',
    intentos INTEGER NOT NULL DEFAULT 0,
    resultado TEXT DEFAULT '',
    evidencia TEXT DEFAULT '',
    punto_control TEXT,                       -- JSON o NULL
    actualizado TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tareas_proyecto ON tareas(proyecto_id);
CREATE TABLE IF NOT EXISTS aprobaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tarea_id INTEGER NOT NULL,
    accion TEXT NOT NULL,
    riesgo TEXT DEFAULT '',
    costo REAL NOT NULL DEFAULT 0,
    respuesta TEXT NOT NULL DEFAULT 'pendiente', -- pendiente, aprobada, rechazada, usada, anulada
    fecha TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entidad TEXT NOT NULL,                    -- objetivo, proyecto, tarea, aprobacion
    entidad_id INTEGER NOT NULL,
    que TEXT NOT NULL,
    fecha TEXT NOT NULL
);
"""

COLUMNAS = {
    "objetivos": {"id", "titulo", "criterio_exito", "prioridad", "fecha_limite", "origen", "estado", "creado"},
    "proyectos": {"id", "objetivo_id", "titulo", "plan", "presupuesto_usd", "estado", "creado"},
    "tareas": {"id", "proyecto_id", "madre_id", "titulo", "tipo", "depende_de", "nivel_autorizacion", "estado",
               "intentos", "resultado", "evidencia", "punto_control", "actualizado"},
    "aprobaciones": {"id", "tarea_id", "accion", "riesgo", "costo", "respuesta", "fecha"},
    "eventos": {"id", "entidad", "entidad_id", "que", "fecha"},
}

MAX_INTENTOS = 3
MAX_TAREAS_PLAN = 60
TERMINALES = {"completada", "fallida", "cancelada"}

TRANSICIONES = {
    "propuesta": {"lista", "cancelada"},
    "lista": {"en_curso", "bloqueada", "cancelada"},
    "en_curso": {"esperando_aprobacion", "bloqueada", "completada", "fallida", "cancelada",
                 "lista"},                       # 'lista' = reintento o reinicio del PC
    "esperando_aprobacion": {"lista", "cancelada"},  # aprobada -> lista; rechazada -> cancelada
    "bloqueada": {"lista", "completada", "cancelada"},  # desbloquear, el usuario la da por hecha, o cancelar
    "completada": set(), "fallida": set(), "cancelada": set(),
}

TRANSICIONES_PROYECTO = {
    "aprobar": ({"propuesto"}, "activo"),
    "pausar": ({"activo"}, "pausado"),
    "reanudar": ({"pausado"}, "activo"),
    "cancelar": ({"propuesto", "activo", "pausado"}, "cancelado"),
}

PROMPT_PLAN = """Eres Luna y debes planificar un OBJETIVO del usuario como un proyecto de tareas concretas.
OBJETIVO: {titulo}
CRITERIO DE ÉXITO: {criterio}
FECHA LÍMITE: {fecha}

Responde SOLO con un JSON, sin texto alrededor, con esta forma:
{{"titulo": "nombre corto del proyecto", "presupuesto_usd": 0,
  "tareas": [
    {{"clave": "t1", "titulo": "qué hacer", "descripcion": "cómo y para qué", "tipo": "investigar|redactar|calcular|revisar|accion",
      "depende_de": [], "madre": "", "nivel_autorizacion": 0, "costo_usd": 0, "riesgo": ""}}
  ]}}
Reglas: entre 2 y 15 tareas pequeñas y verificables; "depende_de" lista claves de tareas que deben terminar antes;
"madre" es la clave de una tarea que agrupa subtareas (o vacío); nivel_autorizacion 0 = puedes hacerla sola,
1 = sola pero avisando, 2 = necesita permiso del usuario (gastar dinero, enviar algo a otras personas, borrar o
cambiar archivos, publicar). Si dudas, usa 2. No inventes datos: si falta información, crea una tarea para conseguirla."""


class TransicionInvalida(ValueError):
    """Cambio de estado no permitido (o la entidad cambió mientras tanto)."""


def ahora() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _json(texto, defecto):
    if texto is None or texto == "":
        return defecto
    try:
        return json.loads(texto)
    except (TypeError, ValueError):
        return defecto


def extraer_json(texto) -> dict:
    """Saca el primer objeto JSON de la respuesta del cerebro (tolera ```json, <think> y texto alrededor)."""
    if isinstance(texto, dict):
        if "tareas" in texto:
            return texto
        texto = texto.get("content", "")  # mensaje del cerebro: {"role": ..., "content": ...}
    texto = texto if isinstance(texto, str) else str(texto or "")
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.S)
    inicio = texto.find("{")
    if inicio < 0:
        raise ValueError("el plan no trae un JSON")
    profundidad, en_cadena, escape = 0, False, False
    for i in range(inicio, len(texto)):
        c = texto[i]
        if en_cadena:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                en_cadena = False
        elif c == '"':
            en_cadena = True
        elif c == "{":
            profundidad += 1
        elif c == "}":
            profundidad -= 1
            if profundidad == 0:
                return json.loads(texto[inicio:i + 1])
    raise ValueError("el JSON del plan está incompleto")


def validar_plan(plan: dict) -> list:
    """Normaliza las tareas del plan y revisa claves, dependencias y ciclos. Devuelve la lista normalizada."""
    if not isinstance(plan, dict):
        raise ValueError("el plan debe ser un objeto JSON")
    tareas = plan.get("tareas")
    if not isinstance(tareas, list) or not tareas:
        raise ValueError("el plan no tiene tareas")
    if len(tareas) > MAX_TAREAS_PLAN:
        raise ValueError(f"el plan tiene demasiadas tareas ({len(tareas)})")
    normal, claves = [], {}
    for i, t in enumerate(tareas):
        if not isinstance(t, dict) or not str(t.get("titulo", "")).strip():
            raise ValueError(f"la tarea {i + 1} no tiene título")
        clave = str(t.get("clave") or i + 1).strip()
        if clave in claves:
            raise ValueError(f"clave de tarea repetida: {clave}")
        claves[clave] = i
        try:
            nivel = int(t.get("nivel_autorizacion", 0) or 0)
        except (TypeError, ValueError):
            nivel = 2  # si no se entiende, lo más prudente
        try:
            costo = max(0.0, float(t.get("costo_usd", 0) or 0))
        except (TypeError, ValueError):
            costo = 0.0
        normal.append({"clave": clave, "titulo": str(t["titulo"]).strip()[:300],
                       "descripcion": str(t.get("descripcion", "") or "")[:2000],
                       "tipo": str(t.get("tipo", "") or "general")[:40],
                       "depende_de": t.get("depende_de") or [], "madre": t.get("madre") or "",
                       "nivel_autorizacion": min(2, max(0, nivel)), "costo_usd": costo,
                       "riesgo": str(t.get("riesgo", "") or "")[:500]})

    def resolver(ref, quien):
        if isinstance(ref, int) and not isinstance(ref, bool):
            if 1 <= ref <= len(normal):          # número de tarea contando desde 1
                return normal[ref - 1]["clave"]
        elif str(ref).strip() in claves:
            return str(ref).strip()
        raise ValueError(f"la tarea '{quien}' depende de '{ref}', que no existe")

    for t in normal:
        deps = t["depende_de"] if isinstance(t["depende_de"], list) else [t["depende_de"]]
        t["depende_de"] = sorted({resolver(d, t["clave"]) for d in deps}, key=lambda c: claves[c])
        if t["clave"] in t["depende_de"]:
            raise ValueError(f"la tarea '{t['clave']}' depende de sí misma")
        t["madre"] = resolver(t["madre"], t["clave"]) if str(t["madre"]).strip() else ""
        if t["madre"] == t["clave"]:
            raise ValueError(f"la tarea '{t['clave']}' es su propia madre")
    # Ciclos: una tarea espera a sus dependencias, y una madre espera a sus hijas.
    espera = {t["clave"]: set(t["depende_de"]) for t in normal}
    for t in normal:
        if t["madre"]:
            espera[t["madre"]].add(t["clave"])
    color = {}

    def visitar(c):
        color[c] = 1
        for d in espera[c]:
            if color.get(d) == 1:
                raise ValueError(f"el plan tiene un ciclo de dependencias en '{d}'")
            if not color.get(d):
                visitar(d)
        color[c] = 2

    for c in espera:
        if not color.get(c):
            visitar(c)
    return normal


class PuntoControl:
    """Lo que la tarea ya avanzó. ejecutar_tarea lo lee (punto.datos) y lo guarda (punto.guardar(...));
    cada guardado queda en disco al instante, así un reinicio continúa sin repetir pasos."""

    def __init__(self, gestor, tarea_id: int, datos: dict | None):
        self._gestor, self.tarea_id = gestor, tarea_id
        self.datos = dict(datos or {})

    def guardar(self, datos: dict | None = None, **valores) -> None:
        self.datos.update(datos or {}, **valores)
        self._gestor.guardar_punto_control(self.tarea_id, self.datos)

    def get(self, clave, defecto=None):
        return self.datos.get(clave, defecto)

    def __contains__(self, clave):
        return clave in self.datos


class GestorProyectos:
    def __init__(self, almacen, avisar=None):
        """almacen: lek.almacen.Almacen (se usan su conexión y su candado).
        avisar: función opcional avisar(texto) para contarle al usuario lo importante."""
        self.almacen = almacen
        self.con = almacen.con
        self._candado = almacen._candado
        self.avisar = avisar or (lambda texto: None)
        self._avisos = collections.deque()
        with self._candado:
            self.con.executescript(ESQUEMA)
            for tabla, columnas in COLUMNAS.items():
                hay = {f[1] for f in self.con.execute(f"PRAGMA table_info({tabla})").fetchall()}
                if not columnas <= hay:
                    raise RuntimeError(f"La tabla '{tabla}' de luna.db ya existe con otra forma "
                                       f"(faltan {sorted(columnas - hay)}); otro módulo usa el mismo nombre.")
            self.con.commit()

    # ---------------------------------------------------------------- utilidades
    def _q(self, sql, args=()) -> list:
        with self._candado:
            return [dict(f) for f in self.con.execute(sql, args).fetchall()]

    def _uno(self, sql, args=()):
        filas = self._q(sql, args)
        return filas[0] if filas else None

    def _evento(self, entidad: str, entidad_id: int, que: str) -> None:
        """Sin commit: va dentro de la misma transacción que el cambio que describe."""
        self.con.execute("INSERT INTO eventos(entidad, entidad_id, que, fecha) VALUES (?, ?, ?, ?)",
                         (entidad, entidad_id, que[:1000], ahora()))

    def _auditar(self, accion: str, detalle) -> None:
        try:
            self.almacen.auditar(accion, detalle)
        except Exception:
            pass

    def _avisar(self, texto: str) -> None:
        """Se encola: los avisos salen después del commit (_soltar_avisos), nunca a mitad de una transacción."""
        self._avisos.append(texto)

    def _soltar_avisos(self) -> None:
        while self._avisos:
            try:
                texto = self._avisos.popleft()
            except IndexError:
                return
            try:
                self.avisar(texto)
            except Exception as e:
                print("  No pude avisar:", e)

    def _cambiar(self, tarea_id: int, nuevo: str, que: str = "", **campos) -> dict:
        """Cambia el estado de una tarea validando la transición. Debe llamarse con el candado tomado;
        no hace commit (lo hace quien abre la operación)."""
        fila = self.con.execute("SELECT estado FROM tareas WHERE id = ?", (tarea_id,)).fetchone()
        if not fila:
            raise TransicionInvalida(f"no existe la tarea {tarea_id}")
        viejo = fila[0]
        if nuevo not in TRANSICIONES.get(viejo, set()):
            raise TransicionInvalida(f"tarea {tarea_id}: no se puede pasar de '{viejo}' a '{nuevo}'")
        campos = {**campos, "estado": nuevo, "actualizado": ahora()}
        sets = ", ".join(f"{k} = ?" for k in campos)
        self.con.execute(f"UPDATE tareas SET {sets} WHERE id = ? AND estado = ?", (*campos.values(), tarea_id, viejo))
        self._evento("tarea", tarea_id, f"{viejo} -> {nuevo}" + (f": {que}" if que else ""))
        return {"de": viejo, "a": nuevo}

    def cambiar_estado(self, tarea_id: int, nuevo: str, que: str = "", **campos) -> dict:
        with self._candado:
            try:
                r = self._cambiar(tarea_id, nuevo, que, **campos)
                self._propagar(self._proyecto_de(tarea_id))
                self.con.commit()
            except Exception:
                self.con.rollback()
                raise
        self._soltar_avisos()
        return r

    def _proyecto_de(self, tarea_id: int) -> int:
        fila = self.con.execute("SELECT proyecto_id FROM tareas WHERE id = ?", (tarea_id,)).fetchone()
        return fila[0] if fila else 0

    # ---------------------------------------------------------------- objetivos y planes
    def crear_objetivo(self, titulo: str, criterio_exito: str = "", prioridad: int = 3, fecha_limite: str = "",
                       origen: str = "usuario") -> int:
        titulo = (titulo or "").strip()
        if not titulo:
            raise ValueError("el objetivo necesita un título")
        try:
            prioridad = min(5, max(1, int(prioridad)))
        except (TypeError, ValueError):
            prioridad = 3
        fecha_limite = (fecha_limite or "").strip()[:10]
        if fecha_limite:
            datetime.date.fromisoformat(fecha_limite)  # ValueError si no es AAAA-MM-DD
        with self._candado:
            cur = self.con.execute("INSERT INTO objetivos(titulo, criterio_exito, prioridad, fecha_limite, origen, "
                                   "estado, creado) VALUES (?, ?, ?, ?, ?, 'activo', ?)",
                                   (titulo[:300], (criterio_exito or "")[:1000], prioridad, fecha_limite,
                                    (origen or "usuario")[:20], ahora()))
            self._evento("objetivo", cur.lastrowid, f"creado: {titulo[:200]}")
            self.con.commit()
        return cur.lastrowid

    def objetivo(self, objetivo_id: int):
        return self._uno("SELECT * FROM objetivos WHERE id = ?", (objetivo_id,))

    def planificar(self, objetivo, pensar, intentos: int = 2) -> int:
        """Pide el plan al cerebro (pensar(prompt) -> texto con JSON) y crea el proyecto y sus tareas.
        El proyecto queda 'propuesto' y sus tareas 'propuesta' hasta aprobar_plan(). Devuelve el id del proyecto."""
        obj = self.objetivo(objetivo) if isinstance(objetivo, int) else dict(objetivo)
        if not obj or not obj.get("id"):
            raise ValueError("objetivo inexistente")
        prompt = PROMPT_PLAN.format(titulo=obj["titulo"], criterio=obj.get("criterio_exito") or "(no dado)",
                                    fecha=obj.get("fecha_limite") or "(sin fecha)")
        error = None
        for _ in range(max(1, intentos)):
            pedido = prompt if error is None else (f"{prompt}\n\nTu respuesta anterior no sirvió ({error}). "
                                                   "Devuelve SOLO el JSON corregido.")
            try:
                plan = extraer_json(pensar(pedido))
                tareas = validar_plan(plan)
                break
            except ValueError as e:  # json.JSONDecodeError también es ValueError
                error = str(e)
        else:
            raise ValueError(f"no logré un plan válido: {error}")
        try:
            presupuesto = max(0.0, float(plan.get("presupuesto_usd", 0) or 0))
        except (TypeError, ValueError):
            presupuesto = 0.0
        titulo = str(plan.get("titulo") or obj["titulo"]).strip()[:300]
        with self._candado:
            try:
                cur = self.con.execute("INSERT INTO proyectos(objetivo_id, titulo, plan, presupuesto_usd, estado, creado) "
                                       "VALUES (?, ?, '{}', ?, 'propuesto', ?)", (obj["id"], titulo, presupuesto, ahora()))
                pid = cur.lastrowid
                ids = {}
                for t in tareas:
                    c = self.con.execute("INSERT INTO tareas(proyecto_id, titulo, tipo, nivel_autorizacion, estado, "
                                         "actualizado) VALUES (?, ?, ?, ?, 'propuesta', ?)",
                                         (pid, t["titulo"], t["tipo"], t["nivel_autorizacion"], ahora()))
                    ids[t["clave"]] = t["id"] = c.lastrowid
                for t in tareas:
                    self.con.execute("UPDATE tareas SET depende_de = ?, madre_id = ? WHERE id = ?",
                                     (json.dumps([ids[d] for d in t["depende_de"]]), ids.get(t["madre"]), t["id"]))
                guardado = {"titulo": titulo, "presupuesto_usd": presupuesto, "tareas": tareas}
                self.con.execute("UPDATE proyectos SET plan = ? WHERE id = ?",
                                 (json.dumps(guardado, ensure_ascii=False), pid))
                self._evento("proyecto", pid, f"plan propuesto con {len(tareas)} tareas (objetivo {obj['id']})")
                self.con.commit()
            except Exception:
                self.con.rollback()
                raise
        return pid

    # ---------------------------------------------------------------- acciones sobre proyectos
    def _accion_proyecto(self, proyecto_id: int, accion: str) -> dict:
        if accion not in TRANSICIONES_PROYECTO:
            raise ValueError(f"acción desconocida: {accion}")
        desde, hacia = TRANSICIONES_PROYECTO[accion]
        with self._candado:
            try:
                fila = self.con.execute("SELECT estado FROM proyectos WHERE id = ?", (proyecto_id,)).fetchone()
                if not fila:
                    raise KeyError(f"no existe el proyecto {proyecto_id}")
                if fila[0] not in desde:
                    raise TransicionInvalida(f"proyecto {proyecto_id}: no se puede '{accion}' estando '{fila[0]}'")
                self.con.execute("UPDATE proyectos SET estado = ? WHERE id = ?", (hacia, proyecto_id))
                self._evento("proyecto", proyecto_id, f"{fila[0]} -> {hacia} ({accion})")
                if accion == "aprobar":
                    for (tid,) in self.con.execute("SELECT id FROM tareas WHERE proyecto_id = ? AND estado = 'propuesta'",
                                                   (proyecto_id,)).fetchall():
                        self._cambiar(tid, "lista", "plan aprobado")
                elif accion == "cancelar":
                    for (tid, est) in self.con.execute("SELECT id, estado FROM tareas WHERE proyecto_id = ?",
                                                       (proyecto_id,)).fetchall():
                        if est not in TERMINALES:
                            self._cambiar(tid, "cancelada", "proyecto cancelado")
                    self.con.execute("UPDATE aprobaciones SET respuesta = 'anulada' WHERE respuesta IN "
                                     "('pendiente', 'aprobada') AND tarea_id IN "
                                     "(SELECT id FROM tareas WHERE proyecto_id = ?)", (proyecto_id,))
                self.con.commit()
            except Exception:
                self.con.rollback()
                raise
        self._auditar(f"proyecto_{accion}", {"proyecto": proyecto_id})
        return {"ok": True, "id": proyecto_id, "estado": hacia}

    def aprobar_plan(self, proyecto_id: int) -> dict:
        return self._accion_proyecto(proyecto_id, "aprobar")

    def pausar(self, proyecto_id: int) -> dict:
        return self._accion_proyecto(proyecto_id, "pausar")

    def reanudar(self, proyecto_id: int) -> dict:
        return self._accion_proyecto(proyecto_id, "reanudar")

    def cancelar(self, proyecto_id: int) -> dict:
        return self._accion_proyecto(proyecto_id, "cancelar")

    def accion(self, proyecto_id: int, accion: str) -> dict:
        """Para los endpoints POST /api/proyectos/{id}/{aprobar|pausar|reanudar|cancelar}."""
        return self._accion_proyecto(proyecto_id, accion)

    # ---------------------------------------------------------------- lectura
    def proyecto(self, proyecto_id: int):
        return self._uno("SELECT * FROM proyectos WHERE id = ?", (proyecto_id,))

    def tareas(self, proyecto_id: int) -> list:
        filas = self._q("SELECT * FROM tareas WHERE proyecto_id = ? ORDER BY id", (proyecto_id,))
        for f in filas:
            f["depende_de"] = _json(f["depende_de"], [])
            f["punto_control"] = _json(f["punto_control"], None)
        return filas

    def tarea(self, tarea_id: int):
        """La tarea con su descripción del plan y el contexto del objetivo (lo que recibe ejecutar_tarea)."""
        t = self._uno("SELECT * FROM tareas WHERE id = ?", (tarea_id,))
        if not t:
            return None
        t["depende_de"] = _json(t["depende_de"], [])
        t["punto_control"] = _json(t["punto_control"], None)
        p = self.proyecto(t["proyecto_id"]) or {}
        plan = _json(p.get("plan"), {})
        extra = next((x for x in plan.get("tareas", []) if x.get("id") == tarea_id), {})
        o = self.objetivo(p.get("objetivo_id") or 0) or {}
        t.update({"descripcion": extra.get("descripcion", ""), "costo_usd": extra.get("costo_usd", 0),
                  "riesgo": extra.get("riesgo", ""), "proyecto": p.get("titulo", ""),
                  "objetivo": o.get("titulo", ""), "criterio_exito": o.get("criterio_exito", ""),
                  "resultados_previos": {d: (self._uno("SELECT resultado FROM tareas WHERE id = ?", (d,)) or {})
                                         .get("resultado", "") for d in t["depende_de"]}})
        return t

    def eventos(self, entidad: str = "", entidad_id: int = 0, n: int = 50) -> list:
        if entidad:
            return self._q("SELECT * FROM eventos WHERE entidad = ? AND entidad_id = ? ORDER BY id DESC LIMIT ?",
                           (entidad, entidad_id, n))
        return self._q("SELECT * FROM eventos ORDER BY id DESC LIMIT ?", (n,))

    def _hojas(self, tareas: list) -> list:
        madres = {t["madre_id"] for t in tareas if t["madre_id"]}
        return [t for t in tareas if t["id"] not in madres]

    def avance(self, proyecto_id: int) -> int:
        """Porcentaje de tareas terminadas (sin contar madres ni canceladas)."""
        hojas = [t for t in self._hojas(self.tareas(proyecto_id)) if t["estado"] != "cancelada"]
        if not hojas:
            p = self.proyecto(proyecto_id)
            return 100 if p and p["estado"] == "completado" else 0
        return round(100 * sum(t["estado"] == "completada" for t in hojas) / len(hojas))

    def resumen_api(self, incluir_cerrados: bool = True) -> dict:
        """Forma de GET /api/proyectos: {proyectos: [{id, titulo, estado, avance, tareas: [{titulo, estado}]}]}."""
        sql = "SELECT id, titulo, estado FROM proyectos"
        if not incluir_cerrados:
            sql += " WHERE estado NOT IN ('completado', 'cancelado')"
        return {"proyectos": [{"id": p["id"], "titulo": p["titulo"], "estado": p["estado"],
                               "avance": self.avance(p["id"]),
                               "tareas": [{"titulo": t["titulo"], "estado": t["estado"]} for t in self.tareas(p["id"])]}
                              for p in self._q(sql + " ORDER BY id DESC")]}

    def aprobaciones_pendientes(self) -> list:
        return self._q("SELECT a.*, t.titulo AS tarea, t.proyecto_id FROM aprobaciones a "
                       "JOIN tareas t ON t.id = a.tarea_id WHERE a.respuesta = 'pendiente' ORDER BY a.id")

    def texto_proyectos(self) -> str:
        """Resumen hablado para la herramienta ver_proyectos de Luna."""
        proyectos = self._q("SELECT * FROM proyectos WHERE estado NOT IN ('completado', 'cancelado') ORDER BY id")
        if not proyectos:
            return "No hay proyectos abiertos."
        partes = []
        for p in proyectos:
            ts = self.tareas(p["id"])
            cuenta = {}
            for t in ts:
                cuenta[t["estado"]] = cuenta.get(t["estado"], 0) + 1
            siguiente = next((t["titulo"] for t in ts if t["estado"] in ("en_curso", "lista")), "")
            partes.append(f"Proyecto #{p['id']} '{p['titulo']}' ({p['estado']}, {self.avance(p['id'])}%): "
                          + ", ".join(f"{n} {e}" for e, n in cuenta.items())
                          + (f". Sigue: {siguiente}" if siguiente else ""))
        pend = self.aprobaciones_pendientes()
        if pend:
            partes.append("Esperan tu permiso: " + "; ".join(f"#{a['id']} {a['accion'][:120]}" for a in pend))
        return "\n".join(partes)

    # ---------------------------------------------------------------- lo que usa el programador
    def siguiente_tarea(self):
        """Una tarea 'lista' de un proyecto activo, con dependencias completas y sin subtareas.
        Primero las que tienen punto de control (retomar), luego por prioridad y fecha límite del objetivo;
        las que ya fallaron van después de las que no lo han intentado."""
        filas = self._q(
            "SELECT t.* FROM tareas t JOIN proyectos p ON p.id = t.proyecto_id "
            "LEFT JOIN objetivos o ON o.id = p.objetivo_id "
            "WHERE t.estado = 'lista' AND p.estado = 'activo' "
            "AND NOT EXISTS (SELECT 1 FROM tareas h WHERE h.madre_id = t.id) "
            "ORDER BY (t.punto_control IS NULL), coalesce(o.prioridad, 3), "
            "CASE WHEN coalesce(o.fecha_limite, '') = '' THEN '9999' ELSE o.fecha_limite END, t.intentos, t.id")
        for f in filas:
            deps = _json(f["depende_de"], [])
            if not deps:
                return f
            hechas = self._q(f"SELECT count(*) AS n FROM tareas WHERE estado = 'completada' AND id IN "
                             f"({','.join('?' * len(deps))})", deps)[0]["n"]
            if hechas == len(set(deps)):
                return f
        return None

    def guardar_punto_control(self, tarea_id: int, datos: dict) -> None:
        with self._candado:
            self.con.execute("UPDATE tareas SET punto_control = ?, actualizado = ? WHERE id = ? AND estado = 'en_curso'",
                             (json.dumps(datos, ensure_ascii=False, default=str), ahora(), tarea_id))
            self.con.commit()

    def aprobacion_vigente(self, tarea_id: int):
        return self._uno("SELECT * FROM aprobaciones WHERE tarea_id = ? AND respuesta = 'aprobada' ORDER BY id DESC "
                         "LIMIT 1", (tarea_id,))

    def pedir_aprobacion(self, tarea: dict) -> int:
        """Nivel 2: crea la aprobación y deja la tarea esperando. Si supera el presupuesto, la bloquea."""
        p = self.proyecto(tarea["proyecto_id"]) or {}
        costo = float(tarea.get("costo_usd") or 0)
        accion = tarea["titulo"] + (f": {tarea['descripcion']}" if tarea.get("descripcion") else "")
        with self._candado:
            try:
                gastado = self.con.execute(
                    "SELECT coalesce(sum(a.costo), 0) FROM aprobaciones a JOIN tareas t ON t.id = a.tarea_id "
                    "WHERE t.proyecto_id = ? AND a.respuesta IN ('aprobada', 'usada')", (tarea["proyecto_id"],)).fetchone()[0]
                if p.get("presupuesto_usd", 0) > 0 and gastado + costo > p["presupuesto_usd"] + 1e-9:
                    self._cambiar(tarea["id"], "bloqueada", "supera el presupuesto",
                                  resultado=f"Costaría {costo} USD y el presupuesto restante es "
                                            f"{round(p['presupuesto_usd'] - gastado, 2)} USD.")
                    self.con.commit()
                    self._avisar(f"La tarea #{tarea['id']} supera el presupuesto del proyecto; quedó bloqueada.")
                    self._soltar_avisos()
                    return 0
                cur = self.con.execute("INSERT INTO aprobaciones(tarea_id, accion, riesgo, costo, respuesta, fecha) "
                                       "VALUES (?, ?, ?, ?, 'pendiente', ?)",
                                       (tarea["id"], accion[:1000], tarea.get("riesgo", ""), costo, ahora()))
                self._evento("aprobacion", cur.lastrowid, f"pedida para la tarea {tarea['id']}")
                self._cambiar(tarea["id"], "esperando_aprobacion", f"aprobación #{cur.lastrowid}")
                self.con.commit()
            except Exception:
                self.con.rollback()
                raise
        self._avisar(f"Necesito tu permiso para: {accion[:200]}" + (f" (costo {costo} USD)" if costo else ""))
        self._soltar_avisos()
        return cur.lastrowid

    def responder_aprobacion(self, aprobacion_id: int, aprobar: bool) -> dict:
        """Solo el usuario (endpoint con PIN), nunca Luna. Aprobada -> la tarea vuelve a 'lista';
        rechazada -> la tarea se cancela."""
        with self._candado:
            try:
                a = self.con.execute("SELECT tarea_id, respuesta FROM aprobaciones WHERE id = ?", (aprobacion_id,)).fetchone()
                if not a:
                    raise KeyError(f"no existe la aprobación {aprobacion_id}")
                if a[1] != "pendiente":
                    raise TransicionInvalida(f"la aprobación {aprobacion_id} ya está '{a[1]}'")
                respuesta = "aprobada" if aprobar else "rechazada"
                self.con.execute("UPDATE aprobaciones SET respuesta = ? WHERE id = ?", (respuesta, aprobacion_id))
                self._evento("aprobacion", aprobacion_id, respuesta)
                self._cambiar(a[0], "lista" if aprobar else "cancelada", f"aprobación #{aprobacion_id} {respuesta}")
                self._propagar(self._proyecto_de(a[0]))
                self.con.commit()
            except Exception:
                self.con.rollback()
                raise
        self._auditar("aprobacion_" + respuesta, {"aprobacion": aprobacion_id, "tarea": a[0]})
        self._soltar_avisos()
        return {"ok": True, "id": aprobacion_id, "respuesta": respuesta}

    def usar_aprobacion(self, aprobacion_id: int) -> None:
        """Se gasta ANTES de ejecutar: si el PC se apaga a mitad, nunca se vuelve a ejecutar con ella."""
        with self._candado:
            cur = self.con.execute("UPDATE aprobaciones SET respuesta = 'usada' WHERE id = ? AND respuesta = 'aprobada'",
                                   (aprobacion_id,))
            if cur.rowcount != 1:
                self.con.rollback()
                raise TransicionInvalida(f"la aprobación {aprobacion_id} ya no está vigente")
            self._evento("aprobacion", aprobacion_id, "usada")
            self.con.commit()

    def registrar_fallo(self, tarea_id: int, error: str) -> str:
        """Suma un intento. Con MAX_INTENTOS queda 'fallida'; si no, vuelve a 'lista' (con su punto de control)."""
        with self._candado:
            try:
                t = self.con.execute("SELECT intentos, estado FROM tareas WHERE id = ?", (tarea_id,)).fetchone()
                intentos = t[0] + 1
                nuevo = "fallida" if intentos >= MAX_INTENTOS else "lista"
                self._cambiar(tarea_id, nuevo, f"intento {intentos}: {error[:300]}", intentos=intentos,
                              resultado=f"Error: {error[:1500]}")
                self._propagar(self._proyecto_de(tarea_id))
                self.con.commit()
            except Exception:
                self.con.rollback()
                raise
        if nuevo == "fallida":
            self._avisar(f"La tarea #{tarea_id} falló {MAX_INTENTOS} veces: {error[:200]}")
        self._soltar_avisos()
        return nuevo

    def desbloquear(self, tarea_id: int) -> dict:
        """bloqueada -> lista. Si es de nivel 2, pedirá una aprobación NUEVA antes de ejecutarse."""
        return self.cambiar_estado(tarea_id, "lista", "desbloqueada por el usuario")

    def marcar_completada(self, tarea_id: int, evidencia: str = "") -> dict:
        """El usuario confirma que una tarea bloqueada ya está hecha."""
        return self.cambiar_estado(tarea_id, "completada", "el usuario la dio por hecha", evidencia=evidencia[:2000])

    def retomar_al_arrancar(self) -> dict:
        """Al encender: lo que quedó 'en_curso' (el PC se apagó o LUNA se cerró a mitad).
        - nivel 2 con aprobación ya usada -> 'bloqueada' (pudo haberse hecho; jamás se repite sola).
        - con punto de control -> 'lista' sin sumar intento; el programador la toma primero y continúa.
        - sin punto de control -> 'lista' sumando un intento (o 'fallida' si llega a 3)."""
        informe = {"continuan": [], "reintentan": [], "bloqueadas": [], "fallidas": []}
        with self._candado:
            try:
                for t in self.con.execute("SELECT * FROM tareas WHERE estado = 'en_curso' ORDER BY id").fetchall():
                    t = dict(t)
                    usada = self.con.execute("SELECT 1 FROM aprobaciones WHERE tarea_id = ? AND respuesta = 'usada'",
                                             (t["id"],)).fetchone()
                    if t["nivel_autorizacion"] >= 2 and usada:
                        self._cambiar(t["id"], "bloqueada", "acción de nivel 2 interrumpida",
                                      resultado="Se interrumpió una acción que requería tu permiso y pudo haberse "
                                                "hecho ya. No la repito sola: revísala y márcala como hecha, "
                                                "desbloquéala (pediré permiso otra vez) o cancélala.")
                        informe["bloqueadas"].append(t["id"])
                    elif t["punto_control"]:
                        self._cambiar(t["id"], "lista", "retomada desde su punto de control")
                        informe["continuan"].append(t["id"])
                    else:
                        intentos = t["intentos"] + 1
                        nuevo = "fallida" if intentos >= MAX_INTENTOS else "lista"
                        self._cambiar(t["id"], nuevo, f"interrumpida sin punto de control (intento {intentos})",
                                      intentos=intentos)
                        informe["fallidas" if nuevo == "fallida" else "reintentan"].append(t["id"])
                    self._propagar(t["proyecto_id"])
                self.con.commit()
            except Exception:
                self.con.rollback()
                raise
        if informe["bloqueadas"]:
            self._avisar(f"Al reiniciar encontré {len(informe['bloqueadas'])} acción(es) con permiso a medio hacer; "
                         "esperan tu revisión.")
        self._soltar_avisos()
        return informe

    def terminar(self, tarea_id: int, resultado, evidencia: str = "") -> str:
        """Guarda lo que devolvió ejecutar_tarea. Devuelve el estado final de la tarea."""
        if isinstance(resultado, dict):
            estado = resultado.get("estado", "completada")
            texto = str(resultado.get("resultado", resultado.get("motivo", "")) or "")
            evidencia = str(resultado.get("evidencia", evidencia) or "")
        else:
            estado, texto = "completada", "" if resultado is None else str(resultado)
        if estado not in ("completada", "bloqueada"):
            raise ValueError(f"ejecutar_tarea devolvió un estado no permitido: {estado}")
        with self._candado:
            nivel = self.con.execute("SELECT nivel_autorizacion FROM tareas WHERE id = ?", (tarea_id,)).fetchone()[0]
        self.cambiar_estado(tarea_id, estado, "" if estado == "completada" else texto[:200],
                            resultado=texto[:4000], evidencia=evidencia[:2000])
        if estado == "bloqueada":
            self._avisar(f"La tarea #{tarea_id} quedó bloqueada: {texto[:200]}")
        elif nivel == 1:
            self._avisar(f"Hice la tarea #{tarea_id}: {texto[:200]}")
        self._soltar_avisos()
        return estado

    # ---------------------------------------------------------------- consecuencias
    def _propagar(self, proyecto_id: int) -> None:
        """Con el candado tomado y sin commit: completa madres, bloquea lo que depende de algo fallido o
        cancelado, y cierra el proyecto (y el objetivo) cuando todo terminó."""
        if not proyecto_id:
            return
        for _ in range(MAX_TAREAS_PLAN):  # hasta que no cambie nada (cadenas de madres)
            cambio = False
            ts = {f["id"]: dict(f) for f in self.con.execute("SELECT * FROM tareas WHERE proyecto_id = ?", (proyecto_id,))}
            hijas = {}
            for t in ts.values():
                if t["madre_id"]:
                    hijas.setdefault(t["madre_id"], []).append(t)
            for t in ts.values():
                if t["estado"] not in ("lista", "propuesta"):
                    continue
                if t["id"] in hijas and t["estado"] == "lista":
                    vivas = [h for h in hijas[t["id"]] if h["estado"] != "cancelada"]
                    if any(h["estado"] == "fallida" for h in vivas):
                        self._cambiar(t["id"], "bloqueada", "una subtarea falló")
                        cambio = True
                    elif vivas and all(h["estado"] == "completada" for h in vivas):
                        self._cambiar(t["id"], "en_curso", "subtareas completas")
                        self._cambiar(t["id"], "completada", "todas sus subtareas terminaron")
                        cambio = True
                    if cambio:
                        break
                malas = [d for d in _json(t["depende_de"], []) if ts.get(d, {}).get("estado") in ("fallida", "cancelada")]
                if malas and t["estado"] == "lista":
                    self._cambiar(t["id"], "bloqueada", f"depende de la tarea {malas[0]}",
                                  resultado=f"No puede seguir: la tarea #{malas[0]} quedó "
                                            f"{ts[malas[0]]['estado']}.")
                    cambio = True
                    break
            if not cambio:
                break
        estados = [f[0] for f in self.con.execute("SELECT estado FROM tareas WHERE proyecto_id = ?", (proyecto_id,))]
        p = self.con.execute("SELECT estado, objetivo_id FROM proyectos WHERE id = ?", (proyecto_id,)).fetchone()
        if p and p[0] == "activo" and estados and all(e in ("completada", "cancelada") for e in estados) \
                and "completada" in estados:
            self.con.execute("UPDATE proyectos SET estado = 'completado' WHERE id = ?", (proyecto_id,))
            self._evento("proyecto", proyecto_id, "activo -> completado")
            self._avisar(f"Terminé el proyecto #{proyecto_id}.")
            abiertos = self.con.execute("SELECT count(*) FROM proyectos WHERE objetivo_id = ? AND estado NOT IN "
                                        "('completado', 'cancelado')", (p[1],)).fetchone()[0]
            if p[1] and not abiertos:
                self.con.execute("UPDATE objetivos SET estado = 'completado' WHERE id = ? AND estado = 'activo'", (p[1],))
                self._evento("objetivo", p[1], "completado (falta que el usuario confirme el criterio de éxito)")


# ---------------------------------------------------------------- herramientas para Luna
def herramientas_luna(gestor: GestorProyectos, pensar) -> tuple:
    """Definiciones (formato de HERRAMIENTAS de servidor.py) y funciones de crear_objetivo y ver_proyectos.
    Luna puede proponer planes, pero solo el usuario los aprueba (endpoint con PIN)."""
    texto = {"type": "string"}
    definiciones = [
        {"type": "function", "function": {
            "name": "crear_objetivo",
            "description": "Crea un objetivo de largo plazo del usuario y propone un plan de tareas para lograrlo. "
                           "El plan NO empieza hasta que el usuario lo aprueba en la app (Proyectos).",
            "parameters": {"type": "object", "properties": {
                "titulo": texto, "criterio_exito": texto,
                "prioridad": {"type": "integer", "description": "1 = máxima, 5 = mínima"},
                "fecha_limite": {"type": "string", "description": "AAAA-MM-DD"}}, "required": ["titulo"]}}},
        {"type": "function", "function": {
            "name": "ver_proyectos",
            "description": "Muestra los proyectos abiertos, su avance y los permisos que esperan al usuario.",
            "parameters": {"type": "object", "properties": {}, "required": []}}},
    ]

    def crear_objetivo(titulo: str, criterio_exito: str = "", prioridad=3, fecha_limite: str = "") -> str:
        try:
            oid = gestor.crear_objetivo(titulo, criterio_exito, prioridad, fecha_limite, origen="usuario")
        except ValueError as e:
            return f"No pude crear el objetivo: {e}"
        try:
            pid = gestor.planificar(oid, pensar)
        except Exception as e:
            return f"Guardé el objetivo #{oid}, pero no logré armar el plan ({e}). Puedo intentarlo de nuevo."
        ts = gestor.tareas(pid)
        lista = "; ".join(f"{i + 1}. {t['titulo']}" + (" (necesita tu permiso)" if t["nivel_autorizacion"] >= 2 else "")
                          for i, t in enumerate(ts))
        return (f"Objetivo #{oid} guardado. Propuse el proyecto #{pid} con {len(ts)} tareas: {lista}. "
                "No empiezo hasta que lo apruebes en la app, en Proyectos.")

    def ver_proyectos() -> str:
        return gestor.texto_proyectos()

    return definiciones, {"crear_objetivo": crear_objetivo, "ver_proyectos": ver_proyectos}
