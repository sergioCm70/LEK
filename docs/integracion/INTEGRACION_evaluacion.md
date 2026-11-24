# Integración: autoevaluación medible (lek/evaluacion)

Qué hay: `banco.py` (30 casos verificables, `VERSION_BANCO`), `evaluador.py` (`evaluar`, `comparar`,
`informe_comparativo`, `guardar`, `historial`). Pruebas: `python -m pytest -q tests/test_evaluacion.py` (47).
No toca servidor.py ni almacen.py: la tabla `evaluaciones` se crea sola la primera vez que se guarda.

## Conectar en servidor.py (lo hace quien integre)
Dentro de `trabajo()` de `probar_modelos` (o en un endpoint nuevo `/api/inteligencia/evaluar`):

```python
from lek.evaluacion import comparar, guardar, historial
pares = [(PROVEEDORES[MODELOS[m]["proveedor"]], m) for m in locales]
salida = comparar(pares, almacen=ALMACEN, calentar=True)   # calentar: carga el modelo local antes de medir
avisos = [guardar(ALMACEN, r)["aviso"] for r in salida["resultados"]]
EVALUACION.update(informe=salida["informe"], avisos=[a for a in avisos if a])
```

- `salida["informe"]["filas"]`: modelo, pct, mediana_s, usd, usd_por_1000, debiles (categorías < 60 %).
- `salida["informe"]["recomendacion"]`: texto listo para el panel o para que Luna lo diga.
- `historial(ALMACEN, modelo)`: evaluaciones anteriores para graficar la evolución.
- Con `almacen=ALMACEN` cada caso queda en `llamadas` (motivo "autoevaluación..."): cuenta en el presupuesto.
- Correrlo en un hilo, como hoy: 30 casos × modelo local lento pueden ser varios minutos.
- Para medir a Luna tal como responde de verdad, pasar `sistema=<su prompt real>`; el de defecto es uno corto.
- Sugerencia: no cambiar `cerebro.principal` solo; mostrar la recomendación y que Sergio apruebe (nivel 2).

## Reglas del banco
- Cambiar, agregar o quitar un caso = subir `VERSION_BANCO`. Solo se compara (y se avisa regresión) dentro de
  la misma versión; las evaluaciones incompletas (saldo/autenticación) no sirven de referencia.
- Cada caso nuevo necesita en tests una respuesta buena que pase y una mala que falle (`BUENAS`/`MALAS`).
- Evitar casos donde la respuesta correcta sea un número que aparece en la pregunta o en un paso intermedio.
- Las respuestas de fechas se calculan con `datetime` en banco.py, no se escriben a mano.

## Criterio de recomendación
Solo lo medido: entre los modelos a 5 puntos o menos del mejor, el más barato; a igual costo, el más rápido.
Se avisa si el empatado más rápido es 3 veces más veloz. No se usa tamaño, nombre ni "razonamiento" del catálogo.
Regresión: caída de más de 10 puntos frente a la evaluación completa anterior del mismo modelo y banco
(queda en `auditoria` como `regresion_modelo`).

## Limitaciones reales
- 30 casos: un caso vale 3,3 puntos, así que el umbral de empate (5) equivale a ~1 caso. Es ruido estadístico
  alto; repetir la evaluación o ampliar el banco antes de decisiones importantes.
- El verificador numérico acepta si CUALQUIER número del texto coincide: una respuesta que enumere muchos
  números podría pasar por azar. Las palabras clave son subcadenas sin tildes: no entienden negaciones
  ("no fue Le Corbusier" pasaría arq-01).
- Números escritos en letras ("seis coma cuatro") no se reconocen; el prompt pide cifras.
- `no_inventar` solo detecta frases de "no sé"; no detecta todo invento sutil.
- Herramientas falsas copiadas a mano de servidor.py: si allá cambian nombres, actualizar `HERRAMIENTAS_FALSAS`.
- Costo: suma de `Respuesta.usd` del proveedor (Ollama = 0). No incluye electricidad ni tiempo del PC.
- Tiempo: la latencia que reporta el proveedor (o reloj de pared). En Ollama depende de lo demás que corra en el PC.
- Sin red no se probó contra modelos reales; solo con proveedores falsos programados.
