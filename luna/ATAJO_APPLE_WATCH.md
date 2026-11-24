# Pulso del Apple Watch → Luna (Atajo de iPhone)

El Apple Watch **no habla directo con Luna**: guarda tu pulso en la app **Salud** del iPhone con el que
está emparejado (un Apple Watch solo se empareja con iPhone; con el OPPO/Android no funciona). Un **Atajo**
del iPhone lee esas muestras y se las manda a Luna, que las guarda **solo en tu PC** (nunca en la nube).

> Luna **no es un dispositivo médico**. Los avisos de pulso son orientativos; ante cualquier duda,
> consulta con un profesional de salud.

**Sobre los nombres de las acciones:** escribo los nombres en español como creo que aparecen en iOS, con el
nombre en inglés entre paréntesis. Pueden variar un poco según tu versión de iOS; si no encuentras uno,
búscalo en el buscador de acciones de Atajos con la palabra clave (p. ej. «salud», «URL», «fecha»).

---

## 0. Antes de empezar (una sola vez)

1. **Tailscale en el iPhone**, con la misma cuenta del PC, y conectado (la VPN tiene que estar activa
   cuando corra el Atajo; si no, el Atajo falla con un error de red).
2. **El PIN de Luna** (el que pusiste con `cambiar_pin.bat`).
3. **El certificado (lo más delicado, léelo):** Atajos **no tiene** el botón «Continuar de todos modos» que
   tiene Safari. Si iOS no confía en el certificado, el Atajo simplemente falla. Hay dos caminos:

   **Camino A (recomendado): HTTPS de Tailscale.** Tailscale puede emitir un certificado de verdad
   (Let's Encrypt) para el nombre `tu-pc.tu-red.ts.net`, en el que iOS confía sin instalar nada.
   - En la consola web de Tailscale (DNS): activa **MagicDNS** y **HTTPS Certificates**.
   - En el PC (terminal): `tailscale cert tu-pc.tu-red.ts.net` → crea un `.crt` y un `.key`.
   - Guarda esos dos archivos en `LEK\datos\certificados\` y agrega al `.env`:
     `ASISTENTE_CERT=C:\Users\sergi\Downloads\LEK\datos\certificados\tu-pc.tu-red.ts.net.crt` y
     `ASISTENTE_KEY=...\tu-pc.tu-red.ts.net.key`. Luna los usa al arrancar.
   - Desde ese momento, en el celular entra siempre por `https://tu-pc.tu-red.ts.net:8443` (por la IP
     local saldría aviso, porque el certificado es para ese nombre).
   - El certificado de Tailscale dura ~90 días: hay que renovarlo (volver a correr `tailscale cert`).
   - El nombre `tu-pc.tu-red.ts.net` queda en registros públicos de certificados (así funciona HTTPS).

   **Camino B: confiar en el certificado propio de Luna.** Pasar `datos/certificados/cert.pem` al iPhone
   (AirDrop/correo, renombrado a `.cer` o `.crt`), abrirlo, instalar el perfil en
   *Ajustes → General → VPN y gestión de dispositivos*, y luego activarlo en
   *Ajustes → General → Información → Ajustes de confianza de certificados*.
   Desde la versión de hoy el certificado de Luna cumple lo que pide iOS (vigencia de 800 días, uso
   «servidor» y marca de autoridad para poder confiar en él), así que este camino ya debería funcionar.
   No lo he probado en un iPhone real: si el Atajo igual falla con error de certificado, usa el camino A.

---

## 1. Crear el Atajo «Envía mi pulso a Luna»

Abre la app **Atajos** → pestaña *Atajos* → **+**. Ponle de nombre exactamente
**Envía mi pulso a Luna** (ese nombre es lo que dirás a Siri). Agrega estas acciones en orden:

1. **Buscar muestras de salud** (*Find Health Samples*)
   - Tipo: **Frecuencia cardiaca** (*Heart Rate*).
   - Filtro: **Fecha de inicio** *está en los últimos* **1 hora**.
   - Ordenar por: Fecha de inicio, *más antiguo primero*. Límite: desactivado (o 200).
   - La primera vez iOS te pedirá permiso para que Atajos lea Salud: acéptalo (solo frecuencia cardiaca).
2. **Repetir con cada** (*Repeat with Each*) → elemento de *Muestras de salud*. Dentro del bucle:
   1. **Formatear fecha** (*Format Date*): fecha = *Elemento de repetición* → toca la variable y elige la
      propiedad **Fecha de inicio**; formato **ISO 8601** con **hora incluida**. (No mandes la fecha «tal
      cual»: convertida a texto sale en formato local tipo «24 nov 2026 10:15», que Luna rechaza.)
   2. **Diccionario** (*Dictionary*) con dos campos:
      - `fecha` (Texto) = *Fecha formateada*
      - `bpm` (Número) = *Elemento de repetición* → propiedad **Valor**
   3. **Añadir a variable** (*Add to Variable*): *Diccionario* → variable `muestras`.
3. (Fuera del bucle) **Obtener contenido de URL** (*Get Contents of URL*):
   - URL: `https://tu-pc.tu-red.ts.net:8443/api/salud/pulso/lote` (camino A) o
     `https://<nombre-tailscale>:8443/api/salud/pulso/lote`.
   - Método: **POST**.
   - Encabezados: `X-Asistente-Pin` = *tu PIN*.
   - Cuerpo de la solicitud: **JSON**, con dos campos:
     - `muestras` (tipo **Lista/Array**) = variable `muestras`
     - `origen` (Texto) = `apple_watch`
4. (Opcional) **Mostrar resultado** (*Show Result*) con el *Contenido de la URL*: Luna responde algo como
   `{"recibidas": 12, "guardadas": 10, "duplicadas": 2, "rechazadas": 0}`. Mandar la misma hora dos veces
   no duplica nada: Luna descarta las muestras con la misma fecha.

### Plan B si el campo «Lista» del JSON no acepta tu variable
En vez de diccionarios, dentro del bucle arma una línea de texto `FECHA;BPM` (acción **Texto** con
*Fecha formateada* `;` *Valor*) y añádela a la variable `lineas`. Después del bucle:
**Combinar texto** (*Combine Text*) con *Salto de línea*, y en el JSON manda un solo campo `texto` (Texto) =
*Texto combinado*, más `origen` = `apple_watch`. Luna acepta los dos formatos.

### Prueba
Toca ▶ en el Atajo. En el PC (o en el navegador del celular) abre
`https://…:8443/api/salud/pulso?minutos=60` (con el PIN) o pregúntale a Luna «¿cómo está mi pulso?».

---

## 2. Que corra solo: automatización personal

Atajos → pestaña **Automatización** → **+** → **Hora del día** (*Time of Day*).

- Hasta donde sé, la automatización por hora del día solo se repite **diaria, semanal o mensual**: **no
  hay «cada hora»**. Para mandar el pulso cada hora necesitas crear varias automatizaciones (p. ej. una a
  las 8:00, otra a las 9:00…). Como el Atajo manda «la última hora», cada envío cubre su hora; si alguna
  falla, ese tramo se pierde (puedes cambiar el filtro a «últimas 3 horas» sin riesgo de duplicados).
- Acción: **Ejecutar atajo** → *Envía mi pulso a Luna*.
- En iOS 17 y posteriores creo que aparece la opción **Ejecutar inmediatamente** (sin preguntar) y
  «Notificar al ejecutar». En versiones anteriores puede que te pida confirmación con una notificación
  cada vez. **No lo puedo garantizar para tu versión exacta:** pruébalo y mira si corre sin tocar nada.
- **Limitación conocida:** iOS protege los datos de Salud mientras el iPhone está **bloqueado**. Es
  probable que una automatización que corre con la pantalla bloqueada no pueda leer las muestras y falle
  o mande una lista vacía. Si pasa, elige horas en que sueles usar el celular, o usa Siri.
- El reloj tampoco pasa las muestras a Salud al instante: si el reloj estuvo lejos del iPhone, llegarán
  más tarde (por eso ayuda el filtro de varias horas).

## 3. «Oye Siri, envía mi pulso a Luna»

Siri ejecuta un Atajo diciendo su nombre: con el nombre **Envía mi pulso a Luna**, basta decir
«Oye Siri, envía mi pulso a Luna». Desde el Apple Watch puede que Siri o la app Atajos del reloj
también lo lancen, pero no estoy seguro de que «Buscar muestras de salud» funcione corriendo en el reloj;
si falla, lánzalo desde el iPhone.

## 4. Qué hace Luna con los datos

- Guarda cada muestra (fecha, pulso) en `datos/luna.db`, **solo en el PC**. Nunca se manda a la nube; la
  herramienta `mi_pulso` es siempre privada.
- Muestras de más de 90 días se resumen por día (promedio, mínimo, máximo, reposo estimado) y se borra
  el detalle.
- Avisos sobrios y no médicos: si el pulso pasa de 120 durante 10 minutos o más (o baja de 40), Luna te
  lo comenta y sugiere consultar a un profesional si persiste. Un pico aislado no genera aviso. Luna no
  sabe si estabas haciendo ejercicio: tenlo en cuenta al leer el aviso.
