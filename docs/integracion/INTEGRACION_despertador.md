# Integración: "Luna" en segundo plano (palabra de activación local)

Módulo: `lek/voz/despertador.py` (clase `Despertador`). Pruebas: `tests/test_despertador.py`.
Escucha el micrófono en un hilo; al oír "luna" suena un bip, graba el pedido hasta el silencio
(máx. 12 s), lo transcribe, llama a `responder()` y reproduce la respuesta con `sintetizar()`.
Todo local: el audio no sale del PC. Si falta algo, no falla: `encender()` devuelve False y
`estado()["faltan"]` dice qué instalar.

## 1. Instalar (una vez)
`instalar_voz.bat` -> instala `vosk` y `sounddevice` en `venv` y descarga
`vosk-model-small-es-0.42` en `datos/modelos/`. Prueba solo del oído:
`venv\Scripts\python -m lek.voz.despertador`.

## 2. Ajuste (apagado por defecto)
- Hoy, sin tocar nada más: `ASISTENTE_DESPERTADOR=si` en `.env` (el servidor ya carga `.env`).
- En config: agregar en `lek/config.py`, dentro de `POR_DEFECTO`, `"voz": {"despertador": False}`.
  `despertador_activado(CONFIG)` lee ese ajuste; la variable de `.env`, si está, manda.

## 3. Arranque en `main()` de servidor.py (antes de `asyncio.run(correr())`)
```python
from lek.voz.despertador import Despertador, despertador_activado
if despertador_activado(CONFIG):
    global DESPERTADOR   # o guárdalo en un atributo del módulo
    DESPERTADOR = Despertador(
        "luna", lambda texto: limpiar_respuesta(responder(texto, "voz")),
        sintetizar=sintetizar if SISTEMA == "Windows" else None,
        transcribir_wav=transcribir if os.getenv("DESPERTADOR_WHISPER", "no") == "si" else None)
    if DESPERTADOR.encender():
        print("  Voz: di 'Luna' en cualquier momento (escucha local)")
```
- Nombre: dejar "luna". Vosk solo reconoce palabras de su vocabulario; un nombre inventado
  (p. ej. "LEK") probablemente no esté y no se detectaría.
- Transcripción: por defecto Vosk (sin RAM extra: reutiliza el mismo modelo). Con
  `DESPERTADOR_WHISPER=si` y faster-whisper instalado usa `transcribir()` (entiende mejor,
  pero carga Whisper `WHISPER_MODELO` en RAM; con la RAM al ~90 % no es recomendable).
- Doble respuesta: la ventana del navegador con `?manos=1` también escucha "Luna". Con el
  despertador encendido, poner `ASISTENTE_ABRIR_VENTANA=no` (o abrirla sin `manos=1`).
- Si otra parte de Luna habla por los parlantes, envolverla en `with DESPERTADOR.hablando():`
  (o `pausar()` / `reanudar()`) para que no se escuche a sí misma.
- Estado para la interfaz (opcional): `@app.get("/api/voz")` -> `DESPERTADOR.estado()`.
- Apagar: `DESPERTADOR.apagar()` libera el micrófono. El hilo es `daemon`: muere con el servidor.

## 4. Consumo esperado (cualitativo; medir en el PC de Sergio)
No hay cifras medidas aquí (este entorno no tiene micrófono ni Vosk). Lo que sí se sabe:
- RAM: un modelo Vosk "small" cargado una vez (la variante para equipos modestos; su tamaño
  figura en alphacephei.com/vosk/models). El modelo grande de español NO se usa.
- CPU: lectura bloqueante del micrófono en bloques de 100 ms (el hilo duerme entre bloques),
  un reconocedor con gramática de 2 palabras (decodificación muy acotada) y una energía RMS
  por bloque (`math.sumprod`, en C). Sin numpy.
- Picos: solo al atender un pedido (transcripción completa + cerebro + voz de Windows).
- Medir: Administrador de tareas -> proceso python, con Luna en reposo y tras 10 activaciones.

## 5. Parámetros útiles de `Despertador(...)`
`enfriamiento_s=2.0`, `silencio_fin_s=0.8`, `espera_voz_s=5.0`, `max_pedido_s=12.0`,
`umbral_min=300` y `factor_umbral=3.0` (umbral = max(mínimo, ruido de fondo x factor)),
`tono=True`. Si se activa sola: pasar `reconocedor=ReconocedorVosk(buscar_modelo(),
confianza_min=0.8, usar_parciales=False)` (reacciona algo más tarde, pero es más estricto).
