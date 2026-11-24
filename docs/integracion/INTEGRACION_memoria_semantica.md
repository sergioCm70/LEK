# Integración: memoria semántica local (`lek/memoria_semantica.py`)

Busca por significado ("¿qué te conté de mi perrito?" encuentra "mi mascota Toby es un cachorro").
Todo en el PC: vectores en `datos/luna.db` (tabla `vectores`), embeddings con Ollama local.
Si Ollama o el modelo no están, cae sola a la búsqueda por palabras (FTS) de siempre.

## 1. Modelo a bajar
- `ollama pull nomic-embed-text` — unos 274 MB en disco, 768 dimensiones (~0,3-0,5 GB de RAM cargado).
  Con `keep_alive="2m"` Ollama lo descarga a los 2 minutos sin uso (la RAM está al 90 %).
- Aviso: nomic-embed-text está entrenado sobre todo en inglés; en español funciona, pero peor.
  Alternativas multilingües (tamaños aproximados, compruébalos con `ollama list`):
  `granite-embedding:278m` (~0,6 GB) o `bge-m3` (~1,2 GB, mucho mejor en español, más RAM).
  Para cambiar: `EmbebedorOllama(OLLAMA, modelo="bge-m3")`. Cada modelo tiene sus propios
  vectores y su propio progreso: se reindexa solo y los vectores viejos no se mezclan.
- El catálogo de modelos de chat ya ignora los modelos "embed" (`lek/cerebros/catalogo.py`).

## 2. Crear la memoria (servidor.py, después de `ALMACEN = Almacen(DATOS)`)
```python
from lek.memoria_semantica import EmbebedorOllama, MemoriaSemantica
MEMORIA = MemoriaSemantica(ALMACEN, EmbebedorOllama(OLLAMA))   # OLLAMA ya es la URL local
```
Indexar SIEMPRE en segundo plano (nunca dentro de la respuesta: compite por RAM/CPU con el chat):
```python
threading.Thread(target=MEMORIA.indexar_pendientes, kwargs={"limite": 200}, daemon=True).start()
```
Llamarlo al arrancar y al final de `responder()` (es incremental: solo lo nuevo; idempotente).
La primera vez, con miles de mensajes, tarda varios minutos (200 por llamada); se puede repetir
en un bucle `while MEMORIA.indexar_pendientes(500)["pendientes"]: time.sleep(1)` en un hilo.

## 3. contexto_pasado()
Cambiar `ALMACEN.buscar_mensajes(texto, limite=6, antes_de_id=desde_id)` por:
```python
MEMORIA.buscar_hibrido(texto, k=6, tipos=("mensaje",), antes_de_id=desde_id, minimo=0.55)
```
Devuelve filas con las MISMAS claves que `buscar_mensajes` (id, fecha, rol, contenido, privado…),
así que el filtro `para_nube and f["privado"]` y el formato siguen igual. Usa solo `tipos=("mensaje",)`
aquí: documentos y recuerdos no tienen `id` de mensaje y siempre vienen con `privado=1`.
`minimo` (coseno) hay que calibrarlo con datos reales: con nomic, lo no relacionado suele dar 0,3-0,5.

## 4. indexar_documentos() / buscar_documentos()
Cuando cambie la firma, en un hilo aparte:
```python
por_archivo = {}
for t in trozos:
    por_archivo.setdefault(t["archivo"], []).append(t)
for nombre, ts in por_archivo.items():
    MEMORIA.indexar_documento(nombre, ts)        # solo recalcula trozos nuevos o cambiados
MEMORIA.podar_documentos(por_archivo)            # quita los archivos borrados
```
En `buscar_documentos`, primero `r = MEMORIA.buscar(consulta, k=3, tipos=("documento",), minimo=0.5)`;
cada fila trae `archivo`, `trozo`, `texto`, `puntaje`. Si `r` está vacío, seguir con la búsqueda por
palabras actual (es el respaldo para documentos: `_buscar_texto` solo cubre mensajes y recuerdos).
Ojo: `t["archivo"]` es `p.name`; dos archivos iguales en subcarpetas distintas chocarían.

## 5. Diagnóstico
`MEMORIA.estado()` → modelo, disponible, vectores por tipo, pendientes, numpy y motivo del fallo.

## Rendimiento medido (5.000 vectores de 768, Linux de pruebas)
Sin numpy (math.sumprod): ~50 ms por búsqueda en caliente, ~100 ms la primera (carga de SQLite);
sin sumprod (Python < 3.12) ~95 ms. Con numpy: ~3 ms. Memoria de la caché: ~15 MB.
