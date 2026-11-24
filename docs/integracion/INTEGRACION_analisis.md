# Integración: capacidad de análisis (`lek/analisis`)

Herramientas deterministas (sin modelo), solo lectura, que dan a Luna números exactos.
Pruebas: `python -m pytest -q tests/test_analisis.py`.

## Cambios a hacer en servidor.py (después de definir HERRAMIENTAS, FUNCIONES y HERRAMIENTAS_PRIVADAS)

```python
from lek import analisis
RAICES_ANALISIS = [CONOCIMIENTO]   # + carpetas que Sergio autorice (p. ej. Documentos\Universidad)
HERRAMIENTAS += analisis.HERRAMIENTAS                      # mismo formato que _f()
FUNCIONES.update(analisis.crear_funciones(lambda: RAICES_ANALISIS))   # se relee en cada llamada
HERRAMIENTAS_PRIVADAS.update(analisis.HERRAMIENTAS_PRIVADAS)
```

Las funciones aceptan `**kwargs` extra, nunca lanzan excepciones (devuelven "No pude: …") y el
informe cabe en 2.500 caracteres (por debajo del recorte de 4.000 de `ejecutar_herramienta`).

## PRIVACIDAD

`analizar_archivo`, `calcular_tabla` y `comparar_archivos` leen archivos del usuario: sus resultados
son PRIVADOS, clase **documentos** (la misma de `buscar_documentos`). Con `privacidad.documentos = local`
el turno sigue solo en el PC. `evaluar` no lee archivos y no es privada (si la expresión sale de datos
privados, el turno ya quedó marcado privado por la herramienta que los leyó).

## Herramientas (descripción exacta)

- `analizar_archivo(ruta)` (requerido: ruta): "Analiza un archivo del usuario y da datos EXACTOS: PDF (páginas, palabras, tamaño de lámina, si es escaneado, títulos), Word (encabezados, párrafos, tablas), Excel/CSV (hojas, columnas, tipos, filas, suma/media/mín/máx por columna), imagen (dimensiones, formato, EXIF), GLB/glTF (nodos, mallas, materiales, triángulos) o texto. 'ruta' puede ser la ruta completa o solo el nombre del archivo."
- `calcular_tabla(ruta, operacion, columna, agrupar_por, filtro, hoja)` (requeridos: ruta, operacion): "Calcula sobre una tabla CSV/XLSX (p. ej. un cuadro de áreas) sin hacer cuentas de memoria. 'operacion': sumar, contar, promedio, minimo, maximo, listar o columnas; también en frase, p. ej. 'sumar Área por Piso donde Uso = vivienda'. Opcionales: 'columna', 'agrupar_por', 'filtro' (Piso = 2 y Uso contiene vivienda; operadores = != > < >= <= contiene) y 'hoja'. Acepta decimales con coma y excluye las filas TOTAL del archivo (y dice si cuadran)."
- `comparar_archivos(ruta_a, ruta_b)` (requeridos ambos): "Compara dos archivos del usuario (dos versiones de una memoria, lámina o cuadro de áreas): en tablas dice filas, columnas, celdas y sumas que cambiaron; en PDF/Word/texto, las líneas quitadas y nuevas."
- `evaluar(expresion)` (requerido): "Calculadora exacta: evalúa una expresión matemática (+ - * / ** % paréntesis; funciones sqrt, sin, cos, tan, log, log10, exp, floor, ceil, round, abs, min, max, sum, hypot, radians, degrees; constantes pi, e). Úsala SIEMPRE en vez de calcular de memoria. % es residuo: para un porcentaje escribe 0.15*200."

## Seguridad

- Ruta resuelta (enlaces seguidos) debe quedar dentro de una raíz permitida; si no, se rechaza.
  Un nombre suelto ("cuadro.xlsx") se busca en las raíces; si hay varios, pide cuál.
- Solo lectura; máximo 50 MB por archivo; límite de tiempo cooperativo (20 s; 30 s al comparar);
  máximo 200.000 filas, 200 columnas, 500 páginas de PDF; defensa ante XLSX "bomba zip".
- `evaluar` usa `ast` (nunca `eval`): sin nombres, atributos, cadenas ni lambdas; potencias y factoriales acotados.

## Dependencias

pypdf y python-docx (ya en requisitos). openpyxl y Pillow son OPCIONALES: sin openpyxl el XLSX se lee
como ZIP de XML; sin Pillow, PNG/JPEG/GIF/BMP/WEBP se miden leyendo la cabecera (sin EXIF detallado).
