"""Notificaciones transparentes de LUNA.

Regla de Sergio: cada vez que Luna genera código, organiza archivos o hace algo por su cuenta,
avisa y lo muestra; nunca lo oculta. Cada aviso:
  1. se guarda para siempre en la tabla `notificaciones` (con el código completo si lo hubo),
  2. queda en la auditoría,
  3. se muestra como notificación nativa de Windows (toast) en un hilo aparte, sin bloquear a Luna.

Si llegan más de 5 avisos del mismo tipo en 1 minuto, los toasts se agrupan en uno solo
("Luna hizo 12 cambios en archivos en el último minuto"), pero TODOS quedan guardados uno por uno.
Si el toast falla o no estamos en Windows, el aviso igual queda guardado y visible en la app.
"""
import base64
import collections
import os
import re
import subprocess
import sys
import threading
import time

from lek.almacen import ahora

TIPOS = ("codigo", "archivos", "sistema", "salud", "proyecto", "aviso")
LIMITE_SIN_AGRUPAR = 5        # hasta 5 toasts sueltos del mismo tipo por minuto
VENTANA_SEGUNDOS = 60.0
ESPERA_GRUPO = 5.0            # segundos que se espera para juntar el resumen de una ráfaga

FRASES_GRUPO = {
    "codigo": "Luna generó código {n} veces",
    "archivos": "Luna hizo {n} cambios en archivos",
    "sistema": "Luna hizo {n} acciones en el sistema",
    "salud": "Luna registró {n} avisos de salud",
    "proyecto": "Luna hizo {n} cambios en el proyecto",
    "aviso": "Luna tiene {n} avisos nuevos",
}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS notificaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    tipo TEXT NOT NULL,            -- codigo | archivos | sistema | salud | proyecto | aviso
    titulo TEXT NOT NULL,
    detalle TEXT NOT NULL DEFAULT '',
    codigo TEXT,                   -- el código completo que Luna generó, si lo hubo
    leida INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS notificaciones_leida ON notificaciones(leida, id);
"""

# Script FIJO: el título y el texto llegan por variables de entorno, jamás interpolados en el comando.
# Usa Windows PowerShell 5.1 (powershell.exe): la sintaxis ContentType = WindowsRuntime no existe en pwsh 7.
SCRIPT_TOAST = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$plantilla = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textos = $plantilla.GetElementsByTagName('text')
$textos.Item(0).AppendChild($plantilla.CreateTextNode($env:LUNA_TOAST_TITULO)) | Out-Null
$textos.Item(1).AppendChild($plantilla.CreateTextNode($env:LUNA_TOAST_TEXTO)) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($plantilla)
$appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
"""

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _limpio(texto, maximo: int) -> str:
    t = _CONTROL.sub(" ", str(texto or "")).strip()
    return t if len(t) <= maximo else t[:maximo - 1] + "…"


def comando_toast() -> list:
    """El comando de PowerShell (constante): no contiene ningún dato del aviso."""
    codificado = base64.b64encode(SCRIPT_TOAST.encode("utf-16-le")).decode("ascii")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-EncodedCommand", codificado]


def toast_windows(titulo: str, texto: str, ejecutar=subprocess.run) -> bool:
    """Muestra un toast nativo de Windows. Devuelve False si no es Windows o si falló (nunca lanza)."""
    if not sys.platform.startswith("win"):
        return False
    entorno = dict(os.environ)
    entorno["LUNA_TOAST_TITULO"] = _limpio(titulo, 120) or "Luna"
    entorno["LUNA_TOAST_TEXTO"] = _limpio(texto, 300)
    try:
        r = ejecutar(comando_toast(), env=entorno, capture_output=True, timeout=20,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        return getattr(r, "returncode", 1) == 0
    except Exception:
        return False


class Notificador:
    def __init__(self, almacen, lanzador=toast_windows, reloj=time.monotonic,
                 espera_grupo: float | None = ESPERA_GRUPO, en_hilo: bool = True):
        """lanzador(titulo, texto) -> bool muestra el aviso en pantalla; reloj y espera_grupo se
        pueden inyectar en pruebas (espera_grupo=None: el resumen de ráfaga solo sale con vaciar_grupos())."""
        self.almacen = almacen
        self.lanzador = lanzador
        self.reloj = reloj
        self.espera_grupo = espera_grupo
        self.en_hilo = en_hilo
        self._candado = threading.Lock()
        self._recientes = collections.defaultdict(collections.deque)  # tipo -> marcas de tiempo
        self._pendientes = set()       # tipos con resumen agrupado por mostrar
        self._temporizador = None
        with almacen._candado:
            almacen.con.executescript(ESQUEMA)
            almacen.con.commit()

    # ---------------------------------------------------------------- guardar y avisar
    def notificar(self, tipo: str, titulo: str, detalle: str = "", codigo: str | None = None) -> int:
        """Guarda el aviso, lo audita y lanza el toast sin bloquear. Devuelve el id guardado."""
        tipo = (tipo or "").strip().lower()
        if tipo not in TIPOS:
            detalle = f"[tipo original: {tipo or 'vacío'}] {detalle or ''}".strip()
            tipo = "aviso"
        titulo = str(titulo or "").strip() or "Luna hizo algo"
        detalle = str(detalle or "")
        with self.almacen._candado:
            cur = self.almacen.con.execute(
                "INSERT INTO notificaciones(fecha, tipo, titulo, detalle, codigo, leida) VALUES (?, ?, ?, ?, ?, 0)",
                (ahora(), tipo, titulo, detalle, codigo))
            self.almacen.con.commit()
            nid = cur.lastrowid
        self.almacen.auditar("notificacion", {"id": nid, "tipo": tipo, "titulo": titulo[:200],
                                              "con_codigo": codigo is not None})
        if self._registrar_y_decidir(tipo):
            texto = detalle or ("Generé código: míralo en Luna." if codigo else "")
            if codigo and detalle:
                texto = f"{detalle} (incluye código: míralo en Luna)"
            self._lanzar(titulo, texto)
        return nid

    def _registrar_y_decidir(self, tipo: str) -> bool:
        """True = mostrar un toast suelto; False = la ráfaga se resume en un toast agrupado."""
        with self._candado:
            ahora_ = self.reloj()
            marcas = self._recientes[tipo]
            while marcas and ahora_ - marcas[0] > VENTANA_SEGUNDOS:
                marcas.popleft()
            marcas.append(ahora_)
            if len(marcas) <= LIMITE_SIN_AGRUPAR:
                return True
            self._pendientes.add(tipo)
            if self.espera_grupo is not None and self._temporizador is None:
                self._temporizador = threading.Timer(self.espera_grupo, self.vaciar_grupos)
                self._temporizador.daemon = True
                self._temporizador.start()
            return False

    def vaciar_grupos(self) -> list:
        """Muestra un toast resumen por cada tipo en ráfaga. Devuelve los títulos mostrados."""
        with self._candado:
            self._temporizador = None
            ahora_ = self.reloj()
            resumenes = []
            for tipo in sorted(self._pendientes):
                marcas = self._recientes[tipo]
                while marcas and ahora_ - marcas[0] > VENTANA_SEGUNDOS:
                    marcas.popleft()
                n = len(marcas)
                if n:
                    resumenes.append((tipo, FRASES_GRUPO[tipo].format(n=n) + " en el último minuto", n))
            self._pendientes.clear()
        for tipo, titulo, n in resumenes:
            self.almacen.auditar("notificacion_agrupada", {"tipo": tipo, "cantidad": n})
            self._lanzar(titulo, "Todas quedaron guardadas, una por una, en las notificaciones de Luna.")
        return [t for _, t, _ in resumenes]

    def _lanzar(self, titulo: str, texto: str) -> None:
        def trabajo():
            try:
                self.lanzador(titulo, texto)
            except Exception:
                pass  # el aviso ya está guardado: un toast fallido no se pierde nada
        if self.en_hilo:
            threading.Thread(target=trabajo, name="luna-toast", daemon=True).start()
        else:
            trabajo()

    # ---------------------------------------------------------------- consultar
    def listar(self, no_leidas: bool = False, limite: int = 50) -> list:
        try:
            limite = max(1, min(int(limite), 500))
        except (TypeError, ValueError):
            limite = 50
        filtro = "WHERE leida = 0 " if no_leidas else ""
        with self.almacen._candado:
            filas = self.almacen.con.execute(
                "SELECT id, fecha, tipo, titulo, detalle, codigo, leida FROM notificaciones "
                f"{filtro}ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
        return [{"id": f["id"], "fecha": f["fecha"], "tipo": f["tipo"], "titulo": f["titulo"],
                 "detalle": f["detalle"], "codigo": f["codigo"], "leida": bool(f["leida"])} for f in filas]

    def marcar_leidas(self, ids=None) -> int:
        """Marca como leídas las indicadas (o todas si ids es None). Devuelve cuántas cambiaron."""
        with self.almacen._candado:
            if ids is None:
                cur = self.almacen.con.execute("UPDATE notificaciones SET leida = 1 WHERE leida = 0")
            else:
                limpios = []
                for i in ids:
                    try:
                        limpios.append(int(i))
                    except (TypeError, ValueError):
                        continue
                if not limpios:
                    return 0
                marcas = ",".join("?" * len(limpios))
                cur = self.almacen.con.execute(
                    f"UPDATE notificaciones SET leida = 1 WHERE leida = 0 AND id IN ({marcas})", limpios)
            self.almacen.con.commit()
            return cur.rowcount

    def contar_no_leidas(self) -> int:
        with self.almacen._candado:
            return self.almacen.con.execute("SELECT count(*) FROM notificaciones WHERE leida = 0").fetchone()[0]

    # ---------------------------------------------------------------- forma de los endpoints
    def api_listar(self, no_leidas: bool = False, limite: int = 50) -> dict:
        """Respuesta de GET /api/notificaciones."""
        return {"notificaciones": self.listar(no_leidas, limite), "no_leidas": self.contar_no_leidas()}

    def api_marcar(self, cuerpo: dict | None) -> dict:
        """Respuesta de POST /api/notificaciones/leidas con cuerpo {ids?}."""
        ids = (cuerpo or {}).get("ids")
        if ids is not None and not isinstance(ids, (list, tuple)):
            ids = [ids]
        return {"marcadas": self.marcar_leidas(ids), "no_leidas": self.contar_no_leidas()}
