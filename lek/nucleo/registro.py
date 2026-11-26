"""Registro único de herramientas (LEK 2.0, fase 2).

Antes, cada herramienta vivía en cuatro lugares: la definición para el modelo, la función, la lista de privadas
y las listas de control (externas / con efectos). Aquí se juntan en una ficha por herramienta:

    nombre, descripción, esquema de entrada, función, privacidad, externa, efectos, nivel, categoría

y el registro se encarga de: entregar las definiciones al modelo, validar los argumentos contra el esquema
(requeridos, tipos, sin campos desconocidos), decir si es privada/externa/con efectos y listar todo para la
interfaz (/api/herramientas). Agregar una herramienta ya no exige tocar el núcleo: basta registrarla.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

NIVELES = {0: "consulta", 1: "preparación", 2: "ejecución con permiso", 3: "autonomía limitada",
           4: "autonomía supervisada"}


@dataclass
class Herramienta:
    nombre: str
    descripcion: str
    funcion: Callable
    propiedades: dict = field(default_factory=dict)
    requeridos: list = field(default_factory=list)
    privacidad: str = ""            # clase de privacidad (memoria, notas, documentos, proyectos…); "" = no privada
    siempre_privada: bool = False    # no depende de ningún ajuste (salud)
    externa: bool = False           # su resultado trae contenido de terceros
    efectos: bool = False           # cambia algo fuera de la conversación
    nivel: int = 0                  # nivel de autorización que exige (0 = solo consulta)
    categoria: str = "general"

    def definicion(self) -> dict:
        return {"type": "function", "function": {
            "name": self.nombre, "description": self.descripcion,
            "parameters": {"type": "object", "properties": self.propiedades, "required": list(self.requeridos)}}}

    def ficha(self) -> dict:
        return {"nombre": self.nombre, "descripcion": self.descripcion, "categoria": self.categoria,
                "entradas": {k: v.get("type", "string") for k, v in self.propiedades.items()},
                "requeridos": list(self.requeridos), "privacidad": "siempre" if self.siempre_privada else self.privacidad,
                "externa": self.externa, "efectos": self.efectos, "nivel": self.nivel,
                "nivel_nombre": NIVELES.get(self.nivel, str(self.nivel))}


class ErrorValidacion(ValueError):
    pass


class Registro:
    def __init__(self):
        self._h: dict[str, Herramienta] = {}

    def registrar(self, h: Herramienta) -> Herramienta:
        if not h.nombre or not callable(h.funcion):
            raise ValueError(f"Herramienta inválida: {h.nombre!r}")
        self._h[h.nombre] = h
        return h

    def desde_definicion(self, definicion: dict, funcion: Callable, **meta) -> Herramienta:
        f = definicion["function"]
        p = f.get("parameters") or {}
        return self.registrar(Herramienta(nombre=f["name"], descripcion=f.get("description", ""), funcion=funcion,
                                          propiedades=dict(p.get("properties") or {}),
                                          requeridos=list(p.get("required") or []), **meta))

    def quitar(self, nombre: str) -> None:
        self._h.pop(nombre, None)

    def __contains__(self, nombre: str) -> bool:
        return nombre in self._h

    def get(self, nombre: str) -> Herramienta | None:
        return self._h.get(nombre)

    def nombres(self) -> list:
        return list(self._h)

    def definiciones(self) -> list:
        return [h.definicion() for h in self._h.values()]

    def fichas(self) -> list:
        return [h.ficha() for h in self._h.values()]

    # ---------------------------------------------------------------- validación de argumentos
    def validar(self, nombre: str, argumentos) -> dict:
        h = self._h.get(nombre)
        if h is None:
            raise ErrorValidacion(f"No existe la herramienta {nombre}.")
        if isinstance(argumentos, str):
            try:
                argumentos = json.loads(argumentos or "{}")
            except json.JSONDecodeError:
                raise ErrorValidacion("Los argumentos no son JSON válido.")
        if argumentos is None:
            argumentos = {}
        if not isinstance(argumentos, dict):
            raise ErrorValidacion("Los argumentos deben ser un objeto con nombre: valor.")
        limpios = {}
        for clave, valor in argumentos.items():
            esquema = h.propiedades.get(clave)
            if esquema is None:
                continue                                  # campos inventados por el modelo: se ignoran
            limpios[clave] = self._convertir(clave, valor, esquema.get("type", "string"))
        faltan = [r for r in h.requeridos if limpios.get(r) in (None, "")]
        if faltan:
            raise ErrorValidacion(f"Faltan argumentos para {nombre}: {', '.join(faltan)}.")
        return limpios

    @staticmethod
    def _convertir(clave: str, valor, tipo: str):
        if tipo == "integer":
            try:
                return int(float(valor))
            except (TypeError, ValueError):
                raise ErrorValidacion(f"{clave} debe ser un número entero.")
        if tipo == "number":
            try:
                return float(valor)
            except (TypeError, ValueError):
                raise ErrorValidacion(f"{clave} debe ser un número.")
        if tipo == "boolean":
            return valor if isinstance(valor, bool) else str(valor).strip().lower() in ("true", "si", "sí", "1")
        if tipo in ("object", "array"):
            return valor
        if isinstance(valor, (dict, list)):
            return json.dumps(valor, ensure_ascii=False)
        return "" if valor is None else str(valor)

    # ---------------------------------------------------------------- metadatos
    def es_externa(self, nombre: str) -> bool:
        h = self._h.get(nombre)
        return bool(h and h.externa)

    def tiene_efectos(self, nombre: str) -> bool:
        h = self._h.get(nombre)
        return bool(h and h.efectos)

    def clase_privacidad(self, nombre: str) -> tuple:
        """(siempre_privada, clase)."""
        h = self._h.get(nombre)
        return (bool(h and h.siempre_privada), h.privacidad if h else "")
