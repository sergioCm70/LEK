# Integración del enrutador automático (lek/cerebros/enrutador.py)

`elegir(texto, cerebro, privado=False) -> Eleccion(clase, cadena, motivo_global, senales, modo, aviso)`:
sin llamar a ningún modelo. Con `cerebro.modo = "fijo"` devuelve exactamente la cadena actual.

## 1. En lek/cerebros/gestor.py (Cerebro)

Renombrar el cuerpo actual de `cadena()` a `_cadena_fija()` (el enrutador la usa en modo fijo
y así no hay recursión) y dejar `cadena()` como puerta de entrada:

```python
from .enrutador import elegir

def _cadena_fija(self, privado=False):
    ...  # el cuerpo actual de cadena(), sin cambios

def cadena(self, privado=False, texto=""):
    if not texto:                                   # llamadas viejas sin texto: igual que hoy
        return self._cadena_fija(privado)
    e = elegir(texto, self, privado)
    self._aviso_cadena = e.aviso
    self.ultima_eleccion = e.como_dict()            # para el panel (no guarda el texto)
    return e.cadena

def chat(self, mensajes, herramientas=None, privado=False, texto=""):
    ...
    cadena = self.cadena(privado, texto)            # única línea que cambia dentro de chat()
```

Añadir `self.ultima_eleccion = {}` en `__init__` y `"eleccion": self.ultima_eleccion` en `estado()`.

## 2. En servidor.py, `responder()`

- Clasificar una vez por turno con el texto del usuario (sin la nota del sistema):
  `e = elegir(texto, CEREBRO)`; `primero = e.cadena[0][0]` en vez de `CEREBRO.cadena()[0][0]`.
- Si `e.clase == "privada"`, empezar el turno con `privado = True`: así la memoria y el contexto
  también se arman solo para el PC.
- Pasar `texto=texto` a `ollama_chat` → `CEREBRO.chat(..., texto=texto)`. Dentro de las rondas de
  herramientas el texto sigue siendo el mismo pedido; si una herramienta privada marca el turno,
  `privado=True` fuerza la cadena solo local aunque la clase fuera otra.

## 3. Qué mostrar en el panel (sección Cerebros)

- Selector **Modo: fijo / auto** (`cerebro.modo`, ya existe en Config). **Última decisión**: clase (etiqueta de color: simple / normal / compleja / privada), el motivo en
  una frase (`motivo`, p. ej. "Pregunta simple: el más rápido medido (Claude Haiku 5.5, 3,6 s)"),
  las señales detectadas (`senales`: "análisis", "menciona salud", "3 preguntas encadenadas"…) y la
  cadena completa con el motivo de cada modelo.
- En modo fijo también se ve la clase ("en auto habría sido *compleja*"); **aviso** si `aviso` no está vacío.
- Barra de gasto del mes con marca en el 80 % (desde ahí las complejas no suben de nivel).

## Reglas (resumen)

| Clase | Elige | Nunca |
|---|---|---|
| simple | el más rápido medido (≥3 éxitos, ≥80 % de éxito); sin mediciones → principal | — |
| normal | el principal | — |
| compleja | el de más razonamiento de la nube que cabe en lo que queda del presupuesto; si gasto > 80 % del tope → el principal | subir con gasto > 80 % |
| privada | solo el respaldo local (si el respaldo configurado es de la nube, el modelo local de .env) | la nube |

Toda cadena termina en el respaldo local. Sin clave, conversación solo local, presupuesto agotado o pausa → se descarta y el motivo lo dice.
