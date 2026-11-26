# Seguridad de LEK

Este documento describe lo que el código hace hoy (fase 1 de LEK 2.0, 26/11/2026). Cada punto indica cómo se verificó.

## Acceso

| Regla | Dónde | Verificación |
|---|---|---|
| Desde el propio PC (localhost) no se pide PIN. | `lek/seguridad.py` → `autorizar` | Pruebas |
| Desde cualquier otro dispositivo (Wi-Fi o Tailscale) hace falta sesión o PIN. Sin PIN configurado, el acceso remoto está cerrado (403). | `autorizar` | Pruebas; en el PC la consola dice "sin PIN: solo este PC" |
| El PIN se guarda cifrado con PBKDF2-SHA256 (240.000 iteraciones y sal), en `datos/secretos.json`. Si existe `ASISTENTE_PIN` en `.env` (cambiar_pin.bat), se cifra al arrancar. | `_guardar_pin`, `_sincronizar_pin_env` | Pruebas |
| Se rechazan PIN débiles (menos de 4 caracteres, repetidos, 1234…). | `pin_valido` | Pruebas |
| Al acertar el PIN el dispositivo recibe una sesión: token aleatorio guardado solo como hash, que caduca tras 30 días sin uso. La cookie es HttpOnly y SameSite=Strict. El navegador ya no guarda el PIN. | `crear_sesion`, `/api/sesion` | Pruebas |
| Cambiar el PIN cierra todas las sesiones. También se pueden cerrar a mano. | `cambiar_pin`, `/api/seguridad/cerrar_sesiones` | Pruebas |
| 5 PIN incorrectos seguidos bloquean esa IP 1 min, y el doble en cada bloqueo nuevo (máx. 1 h). Más de 30 fallos en 10 min cierran todo el acceso remoto por 15 min. Cada bloqueo genera un aviso de seguridad. | `registrar_fallo` | Pruebas |

## Peticiones de páginas maliciosas

| Defensa | Dónde | Verificación |
|---|---|---|
| **DNS rebinding:** solo se aceptan como `Host` las IP literales, localhost, el nombre del PC y los nombres de Tailscale (`*.ts.net`). | `host_permitido`, middleware `filtro_de_origen` | Pruebas |
| **CSRF:** se rechazan las peticiones a `/api/` con `Sec-Fetch-Site: cross-site` o con un `Origin` distinto del servidor. Los clientes que no son navegador (Atajos, collar) no envían `Origin` y pasan, siempre con PIN. | `origen_permitido` | Pruebas |
| Cabeceras `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` y `Referrer-Policy: no-referrer`. | middleware | Pruebas |

## Habilidades (código que escribe Luna)

- **Aprobación humana:** ninguna habilidad se activa sin la aprobación explícita de Sergio. La activación automática existe, pero solo si Sergio pone `LUNA_AUTOMEJORA_AUTONOMA=si` en `.env`. Luna no tiene ninguna herramienta para aprobar: aprobar solo se puede por HTTP desde el PC o con PIN. *Verificado con pruebas.*
- **Análisis estático (`lek/automejora/politica.py`):** se aceptan solo módulos de una lista blanca; os, subprocess, archivos, eval y dunders bloquean la habilidad. El código de riesgo alto no se ejecuta ni siquiera en pruebas.
- **Ficha de cada propuesta:** la notificación muestra el código completo, el archivo afectado, las dependencias, los permisos, el riesgo y el resultado de las pruebas.
- **Sandbox en Windows (`lek/automejora/aislamiento_windows.py`):** el código corre con una copia de `python.exe` con **integridad baja** y dentro de un **Job Object**, que limita la memoria a 512 MB, permite un solo proceso, bloquea el portapapeles y el escritorio, y mata todo al cerrarse. Al arrancar, Luna hace una autoprueba. Si la integridad baja no funciona en ese PC, la desactiva, deja solo el Job Object y avisa.
  - *Verificado en el PC de Sergio (26/11/2026):* escribir en sus archivos quedó bloqueado (PermissionError); abrir otro programa quedó bloqueado (WinError 1816, cuota del Job); reservar 700 MB quedó bloqueado (MemoryError); un cálculo normal se permitió. Las habilidades reales (clima con internet y escala) funcionaron dentro del sandbox.
  - **Lo que no bloquea:** la red sigue abierta y el código puede **leer** archivos del usuario. No es un contenedor ni una máquina virtual. Por eso siguen haciendo falta el análisis estático y la aprobación de Sergio.

## Inyección de instrucciones

- El resultado de las herramientas que traen contenido de terceros va entre las marcas `[DATOS EXTERNOS …] … [FIN DE DATOS EXTERNOS]`. Esas herramientas son `buscar_internet`, `buscar_documentos`, `analizar_archivo(s)`, `comparar_archivos`, `calcular_tabla` y las habilidades con red.
- En un turno donde entró contenido externo, se bloquean las herramientas que cambian algo: mover archivos, abrir programas o webs, crear habilidades, cambiar el nombre, recordar, olvidar, notas, pendientes y vocabulario. Cada bloqueo se audita y genera un aviso. *Verificado con pruebas.*

## Honestidad operativa

Si Luna dice "guardé", "anoté", "abrí", "organicé"… y en ese turno no ejecutó ninguna herramienta, se le pide una sola vez que use la herramienta o corrija la respuesta. Para lo que queda pendiente existe `anotar_pendiente`. *Verificado con pruebas*, a partir de un caso real del 24/11.

## Privacidad

- La memoria, las notas, los documentos y el pulso solo se procesan en el PC. La conversación puede ir a Claude, como Sergio aprobó.
- La escucha "Luna" y Whisper corren en el PC: el audio no sale.
- La voz del navegador (Web Speech) en Edge/Chrome **sí puede enviar audio a servidores de Microsoft o Google**. La escucha en segundo plano del PC no.

## Auditoría

`luna.db`, tabla `auditoria`:
- Cada herramienta: nombre, argumentos (en las privadas solo los nombres de los argumentos), resultado, milisegundos y modelo.
- Eventos de seguridad: PIN incorrecto, sesiones, cambios de PIN y orígenes rechazados.
- Respaldos, correcciones de afirmaciones y diagnósticos.

No se registran PIN, claves ni contenido privado.

## Secretos

- `.env` y `datos/` están en `.gitignore`.
- La clave de Claude está en `datos/secretos.json` y nunca se muestra completa.
- **Pendiente:** la clave que se pegó en el chat el 23/11 debe rotarse en platform.claude.com.

## Respaldos

- Un zip completo y verificado por día en `datos/respaldos/` (se guardan 14). Incluye `secretos.json`, así que no debe subirse a la nube sin cifrar.
- `restaurar.bat` apaga a Luna, respalda lo actual y restaura el respaldo elegido. *Verificado con pruebas y en el PC: respaldo de 96 mensajes con integridad correcta.*
