"""Salud de cada modelo: cuenta fallos seguidos y pausa un modelo que falla mucho (cortocircuito)."""
import threading
import time


class Salud:
    def __init__(self, fallos_para_pausar: int = 3, minutos_de_pausa: float = 5):
        self.fallos_para_pausar = fallos_para_pausar
        self.segundos_pausa = minutos_de_pausa * 60
        self._estado: dict[str, dict] = {}
        self._candado = threading.Lock()
        self.reloj = time.monotonic   # reemplazable en las pruebas

    def _e(self, modelo: str) -> dict:
        return self._estado.setdefault(modelo, {"fallos": 0, "pausado_hasta": 0.0, "ultimo_error": "",
                                                 "ultimo_ok": None, "usado": False})

    def disponible(self, modelo: str) -> bool:
        with self._candado:
            return self.reloj() >= self._e(modelo)["pausado_hasta"]

    def exito(self, modelo: str) -> None:
        with self._candado:
            e = self._e(modelo)
            e.update(fallos=0, pausado_hasta=0.0, ultimo_ok=time.time(), usado=True)

    def fallo(self, modelo: str, error: str, definitivo: bool = False) -> None:
        """definitivo = no tiene sentido reintentar pronto (clave inválida, sin saldo)."""
        with self._candado:
            e = self._e(modelo)
            e["fallos"] += 1
            e["ultimo_error"] = error[:300]
            e["usado"] = True
            if definitivo or e["fallos"] >= self.fallos_para_pausar:
                e["pausado_hasta"] = self.reloj() + self.segundos_pausa

    def reactivar(self, modelo: str) -> None:
        with self._candado:
            self._e(modelo).update(fallos=0, pausado_hasta=0.0)

    def estado(self, modelo: str) -> str:
        with self._candado:
            e = self._e(modelo)
            if self.reloj() < e["pausado_hasta"]:
                return "pausado"
            if e["fallos"]:
                return "degradado"
            return "sano" if e["usado"] else "sin usar"

    def detalle(self, modelo: str) -> dict:
        with self._candado:
            e = dict(self._e(modelo))
        restante = max(0, e["pausado_hasta"] - self.reloj())
        return {"estado": self.estado(modelo), "fallos_seguidos": e["fallos"], "ultimo_error": e["ultimo_error"],
                "pausa_restante_s": round(restante)}
