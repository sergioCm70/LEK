"""Gestor de cerebros: elige la cadena de modelos, aplica privacidad y presupuesto, reintenta,
cambia al respaldo si algo falla, y registra cada llamada y cada cambio de modelo con su motivo.

El enrutador automático (fase 2) reemplazará `cadena()` sin cambiar nada más.
"""
import time

from .base import ErrorProveedor, Respuesta
from .salud import Salud

OMITIDO = "[Información privada: se procesó solo en el PC y no se envía a la nube.]"


def para_la_nube(mensajes: list) -> list:
    """Copia de los mensajes sin nada marcado como privado."""
    limpio = []
    for m in mensajes:
        m2 = {k: v for k, v in m.items() if k != "privado"}
        if m.get("privado"):
            m2["content"] = OMITIDO
        limpio.append(m2)
    return limpio


def sin_marcas(mensajes: list) -> list:
    return [{k: v for k, v in m.items() if k != "privado"} for m in mensajes]


class Cerebro:
    def __init__(self, config, almacen, proveedores: dict, modelos: dict, modelo_local: str):
        self.config = config
        self.almacen = almacen
        self.proveedores = proveedores       # {"ollama": Ollama, "claude": Claude}
        self.modelos = modelos               # catálogo
        self.modelo_local = modelo_local
        s = config.todo()["salud"]
        self.salud = Salud(s["fallos_para_pausar"], s["minutos_de_pausa"])
        self.ultimo = {"modelo": "", "proveedor": "", "motivo": "", "degradado": False, "aviso": ""}
        self.esperar = time.sleep            # reemplazable en las pruebas
        self._aviso_cadena = ""

    # ---------------------------------------------------------------- elección
    def ubicacion(self, modelo: str) -> str:
        return self.modelos.get(modelo, {}).get("ubicacion", "local")

    def respaldo(self) -> str:
        return self.config.get("cerebro", "respaldo") or self.modelo_local

    def cadena(self, privado: bool = False) -> list:
        """Lista ordenada de (modelo, motivo). El primero que responda gana."""
        cfg = self.config.todo()
        self._aviso_cadena = ""
        principal, respaldo = cfg["cerebro"]["principal"], self.respaldo()
        opciones = []
        info = self.modelos.get(principal)
        if info and principal != respaldo:
            prov = self.proveedores.get(info["proveedor"])
            nube = info["ubicacion"] == "nube"
            if not prov or not prov.configurado():
                pass  # sin clave: ni se intenta
            elif privado and nube:
                pass  # lo privado no sale del PC
            elif nube and cfg["privacidad"]["conversacion"] == "local":
                pass
            elif nube and self.almacen.gasto_del_mes() >= cfg["cerebro"]["presupuesto_mensual_usd"]:
                self._aviso_cadena = "Se alcanzó el presupuesto del mes: uso el cerebro local."
            elif not self.salud.disponible(principal):
                pass
            else:
                opciones.append((principal, "modelo principal"))
        motivo_respaldo = "respaldo local"
        if not opciones:
            if privado:
                motivo_respaldo = "información privada: se procesa en el PC"
            elif not self.proveedores.get(self.modelos.get(principal, {}).get("proveedor", ""), None) or \
                    not self.proveedores[self.modelos[principal]["proveedor"]].configurado():
                motivo_respaldo = "sin clave de la nube: cerebro local"
            elif not self.salud.disponible(principal):
                motivo_respaldo = f"{principal} en pausa por fallos: respaldo local"
        opciones.append((respaldo, motivo_respaldo))
        return opciones

    # ---------------------------------------------------------------- llamada
    def chat(self, mensajes: list, herramientas: list | None = None, privado: bool = False) -> Respuesta:
        reintentos = self.config.get("salud", "reintentos")
        errores = []
        cadena = self.cadena(privado)
        for posicion, (modelo, motivo) in enumerate(cadena):
            info = self.modelos.get(modelo, {"proveedor": "ollama", "ubicacion": "local"})
            prov = self.proveedores[info["proveedor"]]
            enviar = para_la_nube(mensajes) if info["ubicacion"] == "nube" else sin_marcas(mensajes)
            for intento in range(reintentos + 1):
                try:
                    r = prov.chat(modelo, enviar, herramientas)
                except ErrorProveedor as e:
                    definitivo = e.tipo in ("auth", "saldo")
                    self.salud.fallo(modelo, str(e), definitivo=definitivo)
                    self.almacen.registrar_llamada(modelo, info["proveedor"], 0, ok=False, error=str(e), motivo=motivo)
                    errores.append(f"{modelo}: {e}")
                    if e.reintentable and intento < reintentos and self.salud.disponible(modelo):
                        self.esperar(1.5 * (intento + 1))
                        continue
                    break
                self.salud.exito(modelo)
                self.almacen.registrar_llamada(modelo, info["proveedor"], r.latencia, r.tokens_entrada,
                                               r.tokens_salida, r.usd, ok=True, motivo=motivo)
                if modelo != self.ultimo["modelo"]:
                    self.almacen.registrar_cambio_modelo(self.ultimo["modelo"] or "(inicio)", modelo, motivo)
                degradado = posicion > 0
                if degradado:
                    aviso = f"Uso el respaldo ({modelo}) porque falló el principal: {errores[-1][:160]}"
                else:
                    aviso = self._aviso_cadena
                self.ultimo.update(modelo=modelo, proveedor=info["proveedor"], motivo=motivo,
                                   degradado=degradado, aviso=aviso)
                return r
        raise ErrorProveedor("todos", "ningún cerebro respondió: " + " | ".join(errores[-3:]))

    # ---------------------------------------------------------------- para el panel
    def estado(self) -> dict:
        cfg = self.config.todo()
        stats = self.almacen.estadisticas_modelos()
        cargados = {}
        ollama = self.proveedores.get("ollama")
        if ollama and hasattr(ollama, "modelos_cargados"):
            for m in ollama.modelos_cargados():
                cargados[m.get("name", "")] = {"ram_gb": round(m.get("size", 0) / 1e9, 1),
                                               "en_gpu_gb": round(m.get("size_vram", 0) / 1e9, 1)}
        modelos = []
        for mid, info in self.modelos.items():
            prov = self.proveedores.get(info["proveedor"])
            st = stats.get(mid, {})
            d = self.salud.detalle(mid)
            if prov and not prov.configurado():
                d["estado"] = "sin clave"
            modelos.append({
                "id": mid, "nombre": info["nombre"], "proveedor": info["proveedor"], "ubicacion": info["ubicacion"],
                "nota": info.get("nota", ""), "razonamiento": info.get("razonamiento"),
                "precio": info.get("precio"), **d,
                "llamadas_30d": st.get("llamadas", 0) or 0,
                "exito_30d": round((st.get("exitos") or 0) / st["llamadas"] * 100) if st.get("llamadas") else None,
                "latencia_media_s": round(st["latencia_media"], 1) if st.get("latencia_media") else None,
                "usd_30d": round(st.get("usd") or 0, 4),
                "en_memoria": cargados.get(mid),
                "es_principal": mid == cfg["cerebro"]["principal"], "es_respaldo": mid == self.respaldo(),
            })
        return {
            "activo": self.ultimo, "modo": cfg["cerebro"]["modo"], "principal": cfg["cerebro"]["principal"],
            "respaldo": self.respaldo(), "presupuesto_mensual_usd": cfg["cerebro"]["presupuesto_mensual_usd"],
            "gasto_mes_usd": self.almacen.gasto_del_mes(), "privacidad": cfg["privacidad"],
            "modelos": modelos, "cambios": self.almacen.cambios_modelo(),
            "ultimas_llamadas": self.almacen.ultimas_llamadas(8),
        }
