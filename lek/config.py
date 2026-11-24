"""Configuración central de LUNA: datos/config.json, con valores por defecto y validación.

Todo ajuste que Sergio cambia desde la interfaz vive aquí. Los secretos (claves de API)
van aparte, en datos/secretos.json, para no mezclarlos con lo que se muestra.
"""
import copy
import json
import pathlib
import threading

POR_DEFECTO = {
    "version": 1,
    "cerebro": {
        "modo": "auto",                       # "auto": el enrutador elige el modelo según la pregunta
        "principal": "claude-haiku-5-5",      # se usa si hay clave de Claude
        "respaldo": "",                       # vacío = el modelo local de .env
        "presupuesto_mensual_usd": 5.0,
    },
    "privacidad": {                           # "local" = nunca sale del PC; "nube" = puede ir a la nube
        "memoria": "local",
        "notas": "local",
        "documentos": "local",
        "conversacion": "nube",
    },
    "salud": {
        "fallos_para_pausar": 3,
        "minutos_de_pausa": 5,
        "reintentos": 1,
    },
}

OPCIONES = {
    ("cerebro", "modo"): ("fijo", "auto"),
    ("privacidad", "memoria"): ("local", "nube"),
    ("privacidad", "notas"): ("local", "nube"),
    ("privacidad", "documentos"): ("local", "nube"),
    ("privacidad", "conversacion"): ("local", "nube"),
}


class Config:
    def __init__(self, carpeta: pathlib.Path):
        self.ruta = carpeta / "config.json"
        self.ruta_secretos = carpeta / "secretos.json"
        self._candado = threading.Lock()

    # ---------------------------------------------------------------- lectura
    def todo(self) -> dict:
        datos = copy.deepcopy(POR_DEFECTO)
        try:
            guardado = json.loads(self.ruta.read_text(encoding="utf-8"))
        except Exception:
            guardado = {}
        for seccion, valores in guardado.items():
            if isinstance(valores, dict) and isinstance(datos.get(seccion), dict):
                datos[seccion].update({k: v for k, v in valores.items() if k in datos[seccion]})
        return datos

    def get(self, seccion: str, clave: str):
        return self.todo()[seccion][clave]

    # ---------------------------------------------------------------- escritura
    def cambiar(self, seccion: str, clave: str, valor) -> None:
        if seccion not in POR_DEFECTO or clave not in POR_DEFECTO[seccion]:
            raise KeyError(f"Ajuste desconocido: {seccion}.{clave}")
        permitidas = OPCIONES.get((seccion, clave))
        if permitidas and valor not in permitidas:
            raise ValueError(f"{seccion}.{clave} solo acepta: {', '.join(permitidas)}")
        tipo = type(POR_DEFECTO[seccion][clave])
        if tipo is float:
            valor = float(valor)
        elif not isinstance(valor, tipo):
            raise ValueError(f"{seccion}.{clave} debe ser {tipo.__name__}")
        with self._candado:
            try:
                guardado = json.loads(self.ruta.read_text(encoding="utf-8"))
            except Exception:
                guardado = {"version": 1}
            guardado.setdefault(seccion, {})[clave] = valor
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self.ruta.write_text(json.dumps(guardado, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------------------------------------------------------------- secretos
    def secreto(self, nombre: str) -> str:
        try:
            return str(json.loads(self.ruta_secretos.read_text(encoding="utf-8")).get(nombre, ""))
        except Exception:
            return ""

    def guardar_secreto(self, nombre: str, valor: str) -> None:
        with self._candado:
            try:
                datos = json.loads(self.ruta_secretos.read_text(encoding="utf-8"))
            except Exception:
                datos = {}
            if valor:
                datos[nombre] = valor
            else:
                datos.pop(nombre, None)
            self.ruta_secretos.parent.mkdir(parents=True, exist_ok=True)
            self.ruta_secretos.write_text(json.dumps(datos, indent=2), encoding="utf-8")
