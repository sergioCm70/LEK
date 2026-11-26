"""Seguridad de acceso a Luna (LEK 2.0, fase 1).

Reglas:
- Desde el mismo PC (localhost) no se pide PIN: quien ya está en el PC ya tiene los archivos.
- Desde cualquier otro dispositivo (Wi-Fi de la casa o Tailscale) hace falta PIN. Sin PIN configurado,
  el acceso remoto queda cerrado hasta que Sergio ponga uno en el PC.
- El PIN se guarda cifrado (PBKDF2-SHA256 con sal), nunca en texto plano. Si existe ASISTENTE_PIN en .env
  (cambiar_pin.bat), se toma como el PIN vigente y se cifra.
- Al acertar el PIN, el dispositivo recibe una sesión (token aleatorio, guardado solo como hash) que caduca
  a los 30 días sin uso. Las sesiones se pueden cerrar todas de una vez.
- Intentos fallidos: 5 seguidos desde una IP bloquean esa IP (1 min, luego el doble cada vez, máx. 1 h).
  Más de 30 fallos en 10 min bloquean el acceso remoto entero 15 min. Cada bloqueo genera un aviso.
- Validación de Host (contra DNS rebinding) y de Origin/Sec-Fetch-Site (contra CSRF).
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import ipaddress
import json
import os
import pathlib
import secrets
import socket
import threading
import time

ITERACIONES = 240_000
DIAS_SESION = 30
FALLOS_PARA_BLOQUEAR = 5
BLOQUEO_BASE_S = 60
BLOQUEO_MAX_S = 3600
FALLOS_GLOBALES = 30
VENTANA_GLOBAL_S = 600
BLOQUEO_GLOBAL_S = 900


class AccesoDenegado(Exception):
    def __init__(self, codigo: int, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def _hash_pin(pin: str, sal: bytes, iteraciones: int = ITERACIONES) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), sal, iteraciones).hex()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def pin_valido(pin: str) -> str:
    """Devuelve "" si sirve, o el motivo si no."""
    pin = str(pin or "")
    if len(pin) < 4:
        return "El PIN debe tener al menos 4 caracteres (mejor 6 o más)."
    if len(pin) > 64:
        return "El PIN es demasiado largo."
    if len(set(pin)) == 1 or pin in ("1234", "123456", "0000", "000000", "12345678", "4321"):
        return "Ese PIN es demasiado fácil de adivinar."
    return ""


class Seguridad:
    def __init__(self, carpeta: pathlib.Path, almacen, pin_env: str = "", avisar=None, reloj=time.time):
        self.carpeta = pathlib.Path(carpeta)
        self.secretos = self.carpeta / "secretos.json"
        self.almacen = almacen
        self.avisar = avisar or (lambda titulo, detalle: None)
        self.reloj = reloj
        self._candado = threading.Lock()
        self._fallos: dict[str, dict] = {}
        self._fallos_globales: list[float] = []
        self._bloqueo_global_hasta = 0.0
        with almacen._candado:
            almacen.con.execute("""CREATE TABLE IF NOT EXISTS sesiones(
                token_hash TEXT PRIMARY KEY, creada TEXT, ultima TEXT, expira REAL,
                ip TEXT, dispositivo TEXT, revocada INTEGER DEFAULT 0)""")
            almacen.con.commit()
        self._sincronizar_pin_env(pin_env)

    # ---------------------------------------------------------------- secretos.json
    def _leer(self) -> dict:
        try:
            return json.loads(self.secretos.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _escribir(self, datos: dict) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        tmp = self.secretos.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.secretos)

    def _sincronizar_pin_env(self, pin_env: str) -> None:
        """El PIN de .env (cambiar_pin.bat) manda si cambió: se cifra y se guarda su huella."""
        pin_env = (pin_env or "").strip()
        if not pin_env:
            return
        d = self._leer()
        huella = hashlib.sha256(("env:" + pin_env).encode()).hexdigest()
        if d.get("pin_env_huella") == huella and d.get("pin"):
            return
        self._guardar_pin(pin_env, d)
        d = self._leer()
        d["pin_env_huella"] = huella
        self._escribir(d)

    def _guardar_pin(self, pin: str, d: dict | None = None) -> None:
        d = d if d is not None else self._leer()
        sal = secrets.token_bytes(16)
        d["pin"] = {"alg": "pbkdf2_sha256", "iter": ITERACIONES, "sal": sal.hex(), "hash": _hash_pin(pin, sal)}
        d.pop("pin_texto", None)
        self._escribir(d)

    # ---------------------------------------------------------------- PIN
    def hay_pin(self) -> bool:
        return bool(self._leer().get("pin"))

    def verificar_pin(self, pin: str) -> bool:
        p = self._leer().get("pin")
        if not p or not pin:
            return False
        calculado = _hash_pin(str(pin), bytes.fromhex(p["sal"]), int(p.get("iter", ITERACIONES)))
        return hmac.compare_digest(calculado, p["hash"])

    def cambiar_pin(self, nuevo: str, actual: str = "", desde_pc: bool = False) -> str:
        motivo = pin_valido(nuevo)
        if motivo:
            raise AccesoDenegado(400, motivo)
        if self.hay_pin() and not desde_pc and not self.verificar_pin(actual):
            raise AccesoDenegado(401, "El PIN actual no es correcto.")
        self._guardar_pin(str(nuevo))
        self.revocar_sesiones()
        self.almacen.auditar("seguridad", {"accion": "cambiar_pin", "desde_pc": desde_pc})
        self.avisar("PIN cambiado", "Se cerraron las sesiones de todos los dispositivos: vuelve a entrar con el PIN nuevo.")
        return "PIN guardado. Los demás dispositivos tendrán que entrar de nuevo."

    # ---------------------------------------------------------------- sesiones
    def crear_sesion(self, pin: str, ip: str, dispositivo: str = "") -> str:
        self.revisar_bloqueo(ip)
        if not self.verificar_pin(pin):
            self.registrar_fallo(ip)
            raise AccesoDenegado(401, "PIN incorrecto")
        self.registrar_exito(ip)
        token = secrets.token_urlsafe(32)
        ahora = datetime.datetime.now().isoformat(timespec="seconds")
        self.almacen._x("INSERT INTO sesiones(token_hash, creada, ultima, expira, ip, dispositivo) VALUES (?,?,?,?,?,?)",
                        (_hash_token(token), ahora, ahora, self.reloj() + DIAS_SESION * 86400, ip,
                         str(dispositivo)[:80]))
        self.almacen.auditar("seguridad", {"accion": "nueva_sesion", "ip": ip, "dispositivo": str(dispositivo)[:80]})
        return token

    def sesion_valida(self, token: str, ip: str = "") -> bool:
        if not token:
            return False
        h = _hash_token(token)
        filas = self.almacen._q("SELECT expira, revocada FROM sesiones WHERE token_hash = ?", (h,))
        if not filas or filas[0]["revocada"] or filas[0]["expira"] < self.reloj():
            return False
        self.almacen._x("UPDATE sesiones SET ultima = ?, expira = ?, ip = ? WHERE token_hash = ?",
                        (datetime.datetime.now().isoformat(timespec="seconds"),
                         self.reloj() + DIAS_SESION * 86400, ip, h))
        return True

    def revocar_sesiones(self) -> int:
        n = len(self.almacen._q("SELECT token_hash FROM sesiones WHERE revocada = 0 AND expira > ?", (self.reloj(),)))
        self.almacen._x("UPDATE sesiones SET revocada = 1 WHERE revocada = 0")
        return n

    def sesiones_activas(self) -> list:
        return self.almacen._q("SELECT creada, ultima, ip, dispositivo FROM sesiones "
                               "WHERE revocada = 0 AND expira > ? ORDER BY ultima DESC", (self.reloj(),))

    # ---------------------------------------------------------------- intentos fallidos
    def revisar_bloqueo(self, ip: str) -> None:
        ahora = self.reloj()
        if ahora < self._bloqueo_global_hasta:
            raise AccesoDenegado(429, "Demasiados intentos fallidos: el acceso remoto está bloqueado unos minutos.")
        f = self._fallos.get(ip)
        if f and ahora < f.get("hasta", 0):
            espera = int(f["hasta"] - ahora) + 1
            raise AccesoDenegado(429, f"Demasiados PIN incorrectos desde este dispositivo. Espera {espera} s.")

    def registrar_fallo(self, ip: str) -> None:
        ahora = self.reloj()
        with self._candado:
            f = self._fallos.setdefault(ip, {"seguidos": 0, "bloqueos": 0, "hasta": 0})
            f["seguidos"] += 1
            bloqueo = None
            if f["seguidos"] >= FALLOS_PARA_BLOQUEAR:
                bloqueo = min(BLOQUEO_MAX_S, BLOQUEO_BASE_S * (2 ** f["bloqueos"]))
                f["bloqueos"] += 1
                f["seguidos"] = 0
                f["hasta"] = ahora + bloqueo
            self._fallos_globales = [t for t in self._fallos_globales if ahora - t < VENTANA_GLOBAL_S] + [ahora]
            global_ = len(self._fallos_globales) > FALLOS_GLOBALES and ahora >= self._bloqueo_global_hasta
            if global_:
                self._bloqueo_global_hasta = ahora + BLOQUEO_GLOBAL_S
        self.almacen.auditar("seguridad", {"accion": "pin_incorrecto", "ip": ip})
        if bloqueo:
            self.avisar("Intentos de PIN bloqueados",
                        f"Se bloqueó {ip} durante {bloqueo // 60 or 1} min por PIN incorrecto repetido.")
        if global_:
            self.avisar("Acceso remoto bloqueado",
                        "Hubo demasiados PIN incorrectos en pocos minutos: cerré el acceso remoto 15 min.")

    def registrar_exito(self, ip: str) -> None:
        with self._candado:
            f = self._fallos.get(ip)
            if f:
                f["seguidos"] = 0

    # ---------------------------------------------------------------- decisión de acceso
    def autorizar(self, ip: str, local: bool, sesion: str = "", pin: str = "") -> None:
        """Lanza AccesoDenegado si la petición no puede pasar."""
        if local:
            return
        if not self.hay_pin():
            raise AccesoDenegado(403, "Para usar a Luna desde otro dispositivo, primero ponle un PIN en el PC "
                                      "(Ajustes → Seguridad, o cambiar_pin.bat).")
        self.revisar_bloqueo(ip)
        if sesion and self.sesion_valida(sesion, ip):
            return
        if pin:
            if self.verificar_pin(pin):
                self.registrar_exito(ip)
                return
            self.registrar_fallo(ip)
            raise AccesoDenegado(401, "PIN incorrecto")
        raise AccesoDenegado(401, "Falta el PIN")

    def estado(self, local: bool) -> dict:
        return {"hay_pin": self.hay_pin(), "desde_pc": local, "sesiones": len(self.sesiones_activas()),
                "bloqueos": sum(1 for f in self._fallos.values() if f.get("hasta", 0) > self.reloj()),
                "bloqueo_global": self._bloqueo_global_hasta > self.reloj()}


# ---------------------------------------------------------------- origen de las peticiones
def es_local(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def nombres_propios() -> set:
    nombres = {"localhost"}
    try:
        h = socket.gethostname().lower()
        nombres |= {h, h + ".local", h + ".lan", h + ".home"}
    except Exception:
        pass
    return nombres


def host_permitido(host: str, extra: set | frozenset = frozenset()) -> bool:
    """Contra DNS rebinding: solo IPs literales, localhost, el nombre del PC y nombres de Tailscale."""
    if not host:
        return False
    h = host.strip().lower()
    if h.startswith("["):
        h = h[1:h.find("]")] if "]" in h else h
    elif h.count(":") == 1:
        h = h.split(":", 1)[0]
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        pass
    return h in nombres_propios() or h in extra or h.endswith(".ts.net")


def origen_permitido(metodo: str, host: str, origin: str, sec_fetch_site: str) -> bool:
    """Contra CSRF: una página de otro sitio no puede mandar órdenes a Luna.
    Los clientes que no son navegador (Atajos, el collar) no envían Origin y pasan (si traen PIN)."""
    if sec_fetch_site and sec_fetch_site.lower() == "cross-site":
        return False
    if not origin or metodo.upper() in ("GET", "HEAD", "OPTIONS") and not sec_fetch_site:
        return True
    if origin == "null":
        return False
    try:
        from urllib.parse import urlsplit
        o = urlsplit(origin)
        return bool(o.netloc) and o.netloc.lower() == (host or "").lower()
    except Exception:
        return False


def entorno_pin() -> str:
    return os.getenv("ASISTENTE_PIN", "").strip()
