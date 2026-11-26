"""Memoria por capas de LEK 2.0 (fase 3).

Capas:
- inmediata: los últimos mensajes de la conversación (servidor.responder).
- episódica: todas las conversaciones, guardadas para siempre (tabla mensajes) y los resúmenes por día.
- semántica: recuerdos organizados (este módulo): qué es, de dónde salió, cuándo, con qué confianza y si sigue vigente.
- procedimental: habilidades aprobadas y vocabulario aprendido.
- de trabajo: pendientes (lek/pendientes.py), proyectos y tareas (lek/autonomia) y proyectos contextuales
  (lek/proyectos_contexto.py).

Reglas de los recuerdos:
- Cada uno tiene categoría, tipo de fuente (confirmado por Sergio, inferido, temporal, hipótesis, externo),
  fuente, fechas, confianza y vigencia. Nunca se convierte una suposición en un hecho: lo inferido se muestra como inferido.
- Si un dato cambia, el anterior pasa a "reemplazado" y queda enlazado al nuevo (historial). No se acumulan
  datos contradictorios como si todos fueran ciertos.
- Olvidar invalida el recuerdo, lo saca del índice de vectores y deja de usarlo. Las conversaciones no se borran
  (regla de Sergio). Los respaldos de días anteriores conservan la versión previa hasta que rotan.

Se construye sobre la tabla `recuerdos` existente (se le agregan columnas): el código viejo sigue funcionando
porque `archivado = 1` sigue significando "no usar".
"""
from __future__ import annotations

import datetime
import json
import re

from .almacen import palabras_clave, plano

CATEGORIAS = ("preferencia", "dato_personal", "persona", "decision", "proyecto", "procedimiento", "compromiso",
              "conocimiento", "dato")
TIPOS = ("confirmado", "inferido", "temporal", "hipotesis", "externo")
CONFIANZA = {"confirmado": 1.0, "temporal": 0.9, "externo": 0.6, "inferido": 0.5, "hipotesis": 0.3}
NOMBRE_TIPO = {"confirmado": "confirmado por Sergio", "inferido": "inferido (no confirmado)",
               "temporal": "temporal", "hipotesis": "hipótesis", "externo": "de una fuente externa"}

COLUMNAS = {
    "categoria": "TEXT DEFAULT 'dato'", "tipo": "TEXT DEFAULT 'confirmado'", "fuente": "TEXT DEFAULT ''",
    "actualizado": "TEXT DEFAULT ''", "confianza": "REAL DEFAULT 1.0", "vigencia": "TEXT DEFAULT 'vigente'",
    "reemplaza_id": "INTEGER", "reemplazado_por": "INTEGER", "proyecto": "TEXT DEFAULT ''",
    "clave": "TEXT DEFAULT ''", "expira": "TEXT DEFAULT ''",
}


def _hoy() -> str:
    return datetime.date.today().isoformat()


def _ahora() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _parecido(a: str, b: str) -> float:
    x, y = set(palabras_clave(a)), set(palabras_clave(b))
    return len(x & y) / len(x | y) if x and y else 0.0


class Memoria:
    def __init__(self, almacen, semantica=None):
        self.almacen = almacen
        self.semantica = semantica

    # ---------------------------------------------------------------- migración (reversible: solo agrega columnas)
    def necesita_migracion(self) -> bool:
        existentes = {f["name"] for f in self.almacen._q("PRAGMA table_info(recuerdos)")}
        return not set(COLUMNAS) <= existentes

    def migrar(self) -> dict:
        existentes = {f["name"] for f in self.almacen._q("PRAGMA table_info(recuerdos)")}
        agregadas = []
        with self.almacen._candado:
            for col, tipo in COLUMNAS.items():
                if col not in existentes:
                    self.almacen.con.execute(f"ALTER TABLE recuerdos ADD COLUMN {col} {tipo}")
                    agregadas.append(col)
            if agregadas:
                self.almacen.con.execute(
                    "UPDATE recuerdos SET vigencia = CASE WHEN archivado = 1 THEN 'olvidado' ELSE 'vigente' END, "
                    "fuente = CASE WHEN coalesce(fuente, '') = '' THEN coalesce(origen, '') ELSE fuente END, "
                    "actualizado = CASE WHEN coalesce(actualizado, '') = '' THEN fecha ELSE actualizado END")
            self.almacen.con.commit()
        if agregadas:
            self.almacen.auditar("migracion", {"tabla": "recuerdos", "columnas": agregadas})
        return {"columnas_agregadas": agregadas}

    # ---------------------------------------------------------------- lectura
    def _expirar(self) -> None:
        self.almacen._x("UPDATE recuerdos SET vigencia = 'expirado', archivado = 1 "
                        "WHERE vigencia = 'vigente' AND coalesce(expira, '') != '' AND expira < ?", (_hoy(),))

    def vigentes(self, categoria: str = "", proyecto: str = "") -> list:
        self._expirar()
        sql, args = "SELECT * FROM recuerdos WHERE vigencia = 'vigente'", []
        if categoria:
            sql += " AND categoria = ?"
            args.append(categoria)
        if proyecto:
            sql += " AND proyecto = ?"
            args.append(proyecto)
        return self.almacen._q(sql + " ORDER BY id", tuple(args))

    def obtener(self, rid: int) -> dict | None:
        filas = self.almacen._q("SELECT * FROM recuerdos WHERE id = ?", (int(rid),))
        return filas[0] if filas else None

    def encontrar(self, ref, solo_vigentes: bool = True) -> list:
        """Por número (id) o por texto contenido (sin tildes ni mayúsculas)."""
        texto = str(ref or "").strip().lstrip("#")
        if texto.isdigit():
            r = self.obtener(int(texto))
            return [r] if r and (r["vigencia"] == "vigente" or not solo_vigentes) else []
        clave = plano(texto)
        if not clave:
            return []
        filas = self.vigentes() if solo_vigentes else self.almacen._q("SELECT * FROM recuerdos ORDER BY id")
        exactos = [r for r in filas if clave in plano(r["dato"])]
        if exactos:
            return exactos
        return [r for r in filas if _parecido(texto, r["dato"]) >= 0.5]

    def buscar(self, consulta: str, k: int = 6, proyecto: str = "") -> list:
        """Recuerdos vigentes relacionados: palabras clave + confianza + recencia (y significado si hay embeddings)."""
        filas = self.vigentes(proyecto=proyecto) if proyecto else self.vigentes()
        if not filas:
            return []
        claves = set(palabras_clave(consulta))
        semanticos = set()
        if self.semantica is not None:
            try:
                semanticos = {int(r["id"]) for r in self.semantica.buscar(consulta, k=k, tipos=("recuerdo",),
                                                                           minimo=0.55)}
            except Exception:
                semanticos = set()
        maximo = max(f["id"] for f in filas)
        puntuados = []
        for f in filas:
            coincide = len(claves & set(palabras_clave(f["dato"] + " " + (f.get("clave") or ""))))
            if not coincide and f["id"] not in semanticos:
                continue
            puntaje = coincide + (1.5 if f["id"] in semanticos else 0) + 0.5 * float(f.get("confianza") or 0) \
                + 0.3 * (f["id"] / maximo)
            puntuados.append((puntaje, f))
        return [f for _, f in sorted(puntuados, key=lambda x: -x[0])[:k]]

    # ---------------------------------------------------------------- escritura
    def recordar(self, contenido: str, categoria: str = "dato", tipo: str = "confirmado", fuente: str = "conversacion",
                 proyecto: str = "", clave: str = "", confianza: float | None = None, expira: str = "") -> dict:
        contenido = " ".join(str(contenido or "").split())[:500]
        if not contenido:
            raise ValueError("No había nada que recordar")
        categoria = categoria if categoria in CATEGORIAS else "dato"
        tipo = tipo if tipo in TIPOS else "confirmado"
        if expira:
            datetime.date.fromisoformat(str(expira)[:10])
        clave = plano(clave).strip()[:60]
        for r in self.vigentes():
            if plano(r["dato"]) == plano(contenido):
                return {"id": r["id"], "estado": "ya_existia", "reemplazados": [], "parecidos": []}
        reemplazar = [r for r in self.vigentes() if clave and r.get("clave") == clave
                      and (r.get("proyecto") or "") == (proyecto or "")]
        parecidos = [] if reemplazar else [
            {"id": r["id"], "dato": r["dato"]} for r in self.vigentes(categoria=categoria)
            if _parecido(contenido, r["dato"]) >= 0.3][:3]
        conf = CONFIANZA[tipo] if confianza is None else max(0.0, min(1.0, float(confianza)))
        cur = self.almacen._x(
            "INSERT INTO recuerdos(dato, fecha, origen, clase, categoria, tipo, fuente, actualizado, confianza, "
            "vigencia, reemplaza_id, proyecto, clave, expira) VALUES (?,?,?,?,?,?,?,?,?, 'vigente', ?,?,?,?)",
            (contenido, _hoy(), "chat", "personal", categoria, tipo, str(fuente)[:120], _ahora(), conf,
             reemplazar[0]["id"] if reemplazar else None, str(proyecto or "")[:80], clave, str(expira or "")[:10]))
        nuevo = cur.lastrowid
        for viejo in reemplazar:
            self._marcar(viejo["id"], "reemplazado", reemplazado_por=nuevo)
        return {"id": nuevo, "estado": "reemplazo" if reemplazar else "nuevo",
                "reemplazados": [{"id": r["id"], "dato": r["dato"]} for r in reemplazar], "parecidos": parecidos}

    def actualizar(self, ref, nuevo: str, motivo: str = "") -> dict:
        """El dato cambió: el viejo queda como 'reemplazado' (con historial) y el nuevo es el vigente."""
        hallados = self.encontrar(ref)
        if not hallados:
            raise KeyError("No encontré ese recuerdo")
        if len(hallados) > 1:
            raise ValueError("Coinciden varios recuerdos: " + "; ".join(f"#{r['id']} {r['dato'][:60]}" for r in hallados[:5]))
        viejo = hallados[0]
        r = self.recordar(nuevo, viejo.get("categoria") or "dato", "confirmado",
                          f"actualización de #{viejo['id']}" + (f": {motivo}" if motivo else ""),
                          viejo.get("proyecto") or "", viejo.get("clave") or "")
        if r["estado"] != "reemplazo":
            self.almacen._x("UPDATE recuerdos SET reemplaza_id = ? WHERE id = ?", (viejo["id"], r["id"]))
            self._marcar(viejo["id"], "reemplazado", reemplazado_por=r["id"])
        return {"anterior": {"id": viejo["id"], "dato": viejo["dato"]}, "nuevo": {"id": r["id"], "dato": nuevo}}

    def olvidar(self, ref) -> list:
        hallados = self.encontrar(ref)
        for r in hallados:
            self._marcar(r["id"], "olvidado")
            self._quitar_de_indices(r["id"])
        if hallados:
            self.almacen.auditar("olvidar", {"ids": [r["id"] for r in hallados]})
        return hallados

    def _marcar(self, rid: int, vigencia: str, reemplazado_por: int | None = None) -> None:
        self.almacen._x("UPDATE recuerdos SET vigencia = ?, archivado = 1, actualizado = ?, "
                        "reemplazado_por = coalesce(?, reemplazado_por) WHERE id = ?",
                        (vigencia, _ahora(), reemplazado_por, int(rid)))

    def _quitar_de_indices(self, rid: int) -> None:
        try:
            self.almacen._x("DELETE FROM vectores WHERE tipo = 'recuerdo' AND ref = ?", (str(rid),))
        except Exception:
            pass                                    # sin tabla de vectores: no hay índice que limpiar
        if self.semantica is not None:
            try:
                self.semantica._cache = None
            except Exception:
                pass

    # ---------------------------------------------------------------- explicar
    def historial(self, rid: int) -> list:
        cadena, visto, actual = [], set(), self.obtener(rid)
        while actual and actual["id"] not in visto:
            visto.add(actual["id"])
            cadena.append(actual)
            actual = self.obtener(actual["reemplaza_id"]) if actual.get("reemplaza_id") else None
        return cadena

    def por_que(self, ref) -> str:
        hallados = self.encontrar(ref, solo_vigentes=False)
        if not hallados:
            return "No tengo ningún recuerdo así."
        partes = []
        for r in hallados[:3]:
            linea = (f"#{r['id']} «{r['dato']}»: {NOMBRE_TIPO.get(r.get('tipo'), r.get('tipo'))}, guardado el {r['fecha']}"
                     f" (fuente: {r.get('fuente') or 'conversación'}, confianza {float(r.get('confianza') or 0):.0%}, "
                     f"estado: {r.get('vigencia')})")
            if r.get("proyecto"):
                linea += f", proyecto {r['proyecto']}"
            previos = self.historial(r["id"])[1:]
            if previos:
                linea += ". Antes decía: " + " → ".join(f"«{p['dato']}» ({p['fecha']})" for p in previos[:3])
            if r.get("reemplazado_por"):
                nuevo = self.obtener(r["reemplazado_por"])
                if nuevo:
                    linea += f". Fue reemplazado por «{nuevo['dato']}»"
            msg = self._mensaje_origen(r)
            if msg:
                linea += f". Lo dijiste así: «{msg[:160]}»"
            partes.append(linea)
        return "\n".join(partes)

    def _mensaje_origen(self, r: dict) -> str:
        m = re.match(r"mensaje:(\d+)", r.get("fuente") or "")
        if not m:
            return ""
        filas = self.almacen._q("SELECT contenido FROM mensajes WHERE id = ?", (int(m.group(1)),))
        return filas[0]["contenido"] if filas else ""

    # ---------------------------------------------------------------- para el cerebro
    def texto_para_prompt(self, limite: int = 60) -> str:
        filas = self.vigentes()
        if not filas:
            return "- (todavía nada)"
        lineas = []
        for f in filas[-limite:]:
            marca = "" if f.get("tipo") in (None, "", "confirmado") else f" [{NOMBRE_TIPO.get(f['tipo'], f['tipo'])}]"
            if f.get("expira"):
                marca += f" [vale hasta {f['expira']}]"
            cat = f.get("categoria") or "dato"
            lineas.append(f"- ({cat}) {f['dato']}{marca}")
        if len(filas) > limite:
            lineas.append(f"- (y {len(filas) - limite} recuerdos más: usa ver_memoria)")
        return "\n".join(lineas)

    def resumen(self, categoria: str = "", proyecto: str = "") -> str:
        filas = self.vigentes(categoria, proyecto)
        if not filas:
            return "No tengo recuerdos guardados" + (f" del proyecto {proyecto}" if proyecto else "") + "."
        por_cat: dict[str, list] = {}
        for f in filas:
            por_cat.setdefault(f.get("categoria") or "dato", []).append(f)
        partes = []
        for cat, lista in por_cat.items():
            partes.append(f"{cat}: " + "; ".join(
                f"#{f['id']} {f['dato']}" + ("" if f.get("tipo") in (None, "", "confirmado")
                                             else f" ({NOMBRE_TIPO.get(f['tipo'], f['tipo'])})") for f in lista))
        return "\n".join(partes)

    # ---------------------------------------------------------------- exportar / importar
    def exportar(self) -> dict:
        return {"formato": "lek-memoria-1", "exportado": _ahora(),
                "recuerdos": self.almacen._q("SELECT * FROM recuerdos ORDER BY id")}

    def importar(self, datos: dict) -> dict:
        if not isinstance(datos, dict) or datos.get("formato") != "lek-memoria-1":
            raise ValueError("No es una exportación de memoria de LEK")
        existentes = {(plano(r["dato"]), r["fecha"]) for r in self.almacen._q("SELECT dato, fecha FROM recuerdos")}
        nuevos = 0
        for r in datos.get("recuerdos", []):
            if not isinstance(r, dict) or not r.get("dato") or (plano(r["dato"]), r.get("fecha", "")) in existentes:
                continue
            vigencia = r.get("vigencia") if r.get("vigencia") in ("vigente", "reemplazado", "olvidado", "expirado") else "vigente"
            self.almacen._x(
                "INSERT INTO recuerdos(dato, fecha, origen, clase, categoria, tipo, fuente, actualizado, confianza, "
                "vigencia, archivado, proyecto, clave, expira) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(r["dato"])[:500], str(r.get("fecha") or _hoy())[:10], "importado", "personal",
                 r.get("categoria") if r.get("categoria") in CATEGORIAS else "dato",
                 r.get("tipo") if r.get("tipo") in TIPOS else "confirmado",
                 f"importado: {str(r.get('fuente') or '')[:80]}", _ahora(), float(r.get("confianza") or 1.0),
                 vigencia, 0 if vigencia == "vigente" else 1, str(r.get("proyecto") or "")[:80],
                 str(r.get("clave") or "")[:60], str(r.get("expira") or "")[:10]))
            nuevos += 1
        self.almacen.auditar("importar_memoria", {"nuevos": nuevos})
        return {"importados": nuevos}


def herramientas(m: Memoria, mensaje_actual=lambda: 0):
    """Definiciones y funciones para Luna. `mensaje_actual()` da el id del mensaje del usuario en curso (procedencia)."""
    def _f(nombre, descripcion, propiedades, requeridos):
        return {"type": "function", "function": {"name": nombre, "description": descripcion, "parameters": {
            "type": "object", "properties": propiedades, "required": requeridos}}}

    def recordar(dato="", categoria="dato", tipo="confirmado", clave="", proyecto="", expira="", **_):
        try:
            r = m.recordar(dato, categoria, tipo, f"mensaje:{mensaje_actual()}" if mensaje_actual() else "conversacion",
                           proyecto, clave, expira=expira)
        except ValueError as e:
            return f"No lo guardé: {e}"
        if r["estado"] == "ya_existia":
            return f"Eso ya lo tenía guardado (#{r['id']})."
        texto = f"Guardado como recuerdo #{r['id']} ({categoria}, {NOMBRE_TIPO.get(tipo, tipo)})."
        if r["reemplazados"]:
            texto += " Reemplaza a: " + "; ".join(f"#{x['id']} «{x['dato']}»" for x in r["reemplazados"]) + \
                     " (queda en el historial, ya no se usa)."
        if r["parecidos"]:
            texto += (" OJO, se parece a recuerdos que siguen vigentes: " + "; ".join(
                f"#{x['id']} «{x['dato']}»" for x in r["parecidos"]) +
                ". Si el nuevo los contradice, usa actualizar_recuerdo para no tener dos versiones.")
        return texto

    def actualizar(recuerdo="", nuevo="", motivo="", **_):
        try:
            r = m.actualizar(recuerdo, nuevo, motivo)
        except (KeyError, ValueError) as e:
            return f"No lo actualicé: {e}"
        return f"Actualizado: antes «{r['anterior']['dato']}», ahora «{r['nuevo']['dato']}» (#{r['nuevo']['id']})."

    def olvidar(texto="", **_):
        hallados = m.olvidar(texto)
        if not hallados:
            return "No encontré nada parecido en mi memoria."
        return (f"Olvidé {len(hallados)} recuerdo(s): " + "; ".join(f"«{r['dato'][:80]}»" for r in hallados) +
                ". Dejé de usarlos y los saqué del índice; las conversaciones siguen guardadas.")

    definiciones = [
        _f("recordar", "Guarda un dato en tu memoria permanente. Úsala cuando Sergio te pida recordar algo o diga "
           "algo claramente útil a futuro. Marca bien el tipo: 'confirmado' solo si él lo dijo; si lo deduces tú, "
           "'inferido'. Usa 'clave' para datos que pueden cambiar (ej. 'escala preferida') así el nuevo reemplaza al viejo.",
           {"dato": {"type": "string", "description": "el dato, en una frase"},
            "categoria": {"type": "string", "description": "preferencia, dato_personal, persona, decision, proyecto, "
                                                           "procedimiento, compromiso, conocimiento o dato"},
            "tipo": {"type": "string", "description": "confirmado, inferido, temporal, hipotesis o externo"},
            "clave": {"type": "string", "description": "tema corto del dato si puede cambiar en el futuro"},
            "proyecto": {"type": "string", "description": "proyecto relacionado, si hay"},
            "expira": {"type": "string", "description": "AAAA-MM-DD si es temporal"}}, ["dato"]),
        _f("actualizar_recuerdo", "Cuando Sergio cambia o corrige un dato que ya recordabas: el viejo queda en el "
           "historial y el nuevo pasa a ser el vigente.",
           {"recuerdo": {"type": "string", "description": "número (#id) o parte del texto del recuerdo viejo"},
            "nuevo": {"type": "string", "description": "el dato actualizado"},
            "motivo": {"type": "string", "description": "por qué cambió (opcional)"}}, ["recuerdo", "nuevo"]),
        _f("olvidar", "SOLO si Sergio lo pide explícitamente: deja de usar los recuerdos que coincidan y los quita "
           "del índice. Las conversaciones no se borran.",
           {"texto": {"type": "string", "description": "número (#id) o texto del recuerdo"}}, ["texto"]),
        _f("ver_memoria", "Muestra lo que recuerdas de Sergio, agrupado por categoría (solo lo vigente). "
           "Puede filtrar por categoría o por proyecto.",
           {"categoria": {"type": "string", "description": "opcional"},
            "proyecto": {"type": "string", "description": "opcional"}}, []),
        _f("por_que_recuerdo", "Explica de dónde sale un recuerdo: cuándo, quién lo dijo, si está confirmado o "
           "inferido, y qué decía antes si cambió.",
           {"recuerdo": {"type": "string", "description": "número (#id) o parte del texto"}}, ["recuerdo"]),
    ]
    funciones = {"recordar": recordar, "actualizar_recuerdo": actualizar, "olvidar": olvidar,
                 "ver_memoria": lambda categoria="", proyecto="", **_: m.resumen(categoria, proyecto),
                 "por_que_recuerdo": lambda recuerdo="", **_: m.por_que(recuerdo)}
    return definiciones, funciones
