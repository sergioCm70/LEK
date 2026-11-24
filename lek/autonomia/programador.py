"""Programador de LUNA: avanza los proyectos aprobados, de a UNA tarea por vez y solo con el PC libre.

    prog = Programador(gestor, ejecutar_tarea, pc_libre)
    prog.arrancar()      # retoma lo interrumpido y revisa cada 2 minutos en un hilo
    prog.detener()       # se detiene limpio (espera a que termine la tarea en curso)

ejecutar_tarea(tarea: dict, punto: PuntoControl) hace el trabajo:
  - tarea trae titulo, descripcion, tipo, objetivo, criterio_exito, resultados_previos (de sus dependencias)...
  - punto.datos es lo ya avanzado; punto.guardar(paso=2, borrador="...") lo deja en disco al instante.
  - devuelve un texto (resultado) o un dict {"resultado": ..., "evidencia": ...};
    {"estado": "bloqueada", "motivo": "..."} si necesita algo del usuario.
  - si lanza una excepción cuenta como intento fallido (a los 3 la tarea queda 'fallida').
pc_libre() -> bool: True si se puede trabajar sin molestar (no está jugando, renderizando, etc.).
"""
import threading

from .proyectos import GestorProyectos, PuntoControl, TransicionInvalida

INTERVALO = 120.0  # segundos (2 minutos)


class Programador:
    def __init__(self, gestor: GestorProyectos, ejecutar_tarea, pc_libre=None, intervalo: float = INTERVALO):
        self.gestor = gestor
        self.ejecutar_tarea = ejecutar_tarea
        self.pc_libre = pc_libre or (lambda: True)
        self.intervalo = intervalo
        self._ocupado = threading.Lock()   # un solo tick a la vez (hilo + llamadas manuales)
        self._parar = threading.Event()
        self._hilo = None
        self._retomado = False

    # ---------------------------------------------------------------- un paso
    def _libre(self) -> bool:
        try:
            return bool(self.pc_libre())
        except Exception as e:
            print("  pc_libre falló; no trabajo por si acaso:", e)
            return False

    def tick(self) -> dict:
        """Toma UNA tarea lista y la ejecuta. Devuelve qué pasó: {"hecho": ...}."""
        if not self._ocupado.acquire(blocking=False):
            return {"hecho": "ocupado"}
        try:
            return self._tick()
        finally:
            self._ocupado.release()

    def _tick(self) -> dict:
        if not self._libre():
            return {"hecho": "pc_ocupado"}
        fila = self.gestor.siguiente_tarea()
        if not fila:
            return {"hecho": "nada"}
        tid = fila["id"]
        try:
            self.gestor.cambiar_estado(tid, "en_curso", "la toma el programador")
        except TransicionInvalida:  # alguien la canceló o pausó justo ahora
            return {"hecho": "nada"}
        tarea = self.gestor.tarea(tid)
        if tarea["nivel_autorizacion"] >= 2:
            aprobacion = self.gestor.aprobacion_vigente(tid)
            if not aprobacion:
                aid = self.gestor.pedir_aprobacion(tarea)
                return {"hecho": "pide_aprobacion" if aid else "bloqueada", "tarea": tid, "aprobacion": aid}
            self.gestor.usar_aprobacion(aprobacion["id"])  # se gasta ANTES de ejecutar: nunca se repite
        punto = PuntoControl(self.gestor, tid, tarea.get("punto_control"))
        try:
            resultado = self.ejecutar_tarea(tarea, punto)
        except Exception as e:
            try:
                estado = self.gestor.registrar_fallo(tid, f"{type(e).__name__}: {e}")
            except TransicionInvalida:
                estado = "descartada"
            return {"hecho": "fallo", "tarea": tid, "estado": estado, "error": str(e)}
        try:
            estado = self.gestor.terminar(tid, resultado)
        except TransicionInvalida:  # se canceló mientras trabajaba: el resultado no se usa
            return {"hecho": "descartada", "tarea": tid}
        except ValueError as e:
            estado = self.gestor.registrar_fallo(tid, str(e))
            return {"hecho": "fallo", "tarea": tid, "estado": estado, "error": str(e)}
        return {"hecho": estado, "tarea": tid}

    # ---------------------------------------------------------------- reinicio y hilo
    def retomar_al_arrancar(self) -> dict:
        self._retomado = True
        return self.gestor.retomar_al_arrancar()

    @property
    def corriendo(self) -> bool:
        return bool(self._hilo and self._hilo.is_alive())

    def arrancar(self) -> None:
        if self.corriendo:
            return
        if not self._retomado:
            try:
                informe = self.retomar_al_arrancar()
                if any(informe.values()):
                    print("  Proyectos retomados:", informe)
            except Exception as e:
                print("  No pude retomar los proyectos:", e)
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="luna-programador", daemon=True)
        self._hilo.start()

    def _bucle(self) -> None:
        while not self._parar.wait(self.intervalo):
            try:
                self.tick()
            except Exception as e:  # el hilo nunca muere por una tarea
                print("  El programador tuvo un error:", e)

    def detener(self, espera: float = 30.0) -> bool:
        """Pide parar y espera a que termine la tarea en curso. True si el hilo terminó."""
        self._parar.set()
        if self._hilo:
            self._hilo.join(espera)
        return not self.corriendo
