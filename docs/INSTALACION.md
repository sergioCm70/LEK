# Instalación de Luna (LEK 2.0)

Guía completa para instalar, actualizar, respaldar y desinstalar. Para el uso diario, ver `luna/MANUAL_LUNA.md`
y el `README.md`.

## Requisitos

| | Mínimo | Recomendado |
|---|---|---|
| Sistema | Windows 10/11 | Windows 11 |
| Python | 3.11 | 3.12 o 3.13 (en 3.15 algunas librerías de voz no traen paquete listo) |
| RAM | 8 GB (con cerebro Claude) | 16 GB si se usa el cerebro local `qwen3:8b` |
| Disco | 2 GB | 8 GB con el modelo local |
| Internet | Solo para Claude, búsquedas y actualizar | — |

Luna **no** necesita permisos de administrador y no debe correrse como administrador.

## Instalación (una vez)

1. Descarga el código: `git clone https://github.com/sergioCm70/LEK.git` o, en GitHub, **Code → Download ZIP**.
2. Abre **`instalar.bat`**. Hace esto, en orden:
   - busca Python y, si falta, lo instala con winget;
   - crea el entorno `venv` e instala `requisitos.txt`;
   - copia `env.ejemplo` a `.env` si no existe;
   - busca Ollama (o lo instala) y descarga el modelo local de `ASISTENTE_MODELO` (por defecto `qwen3:8b`).
3. Abre **`iniciar.bat`**. Luna abre su ventana en `http://localhost:8090`.
4. En **Ajustes**:
   - **Cerebro:** pega tu clave de Claude si quieres respuestas rápidas (presupuesto diario por defecto: 0,5 USD).
   - **Seguridad:** pon un PIN de 6 dígitos o más. Sin PIN, Luna solo responde desde este PC.
   - **Autonomía:** escoge el nivel (por defecto, 2: actúa en lo seguro y pregunta lo demás).

## Opcionales

| Archivo | Qué instala | Notas |
|---|---|---|
| `instalar_voz.bat` | Vosk (oído local para "Luna…") y Whisper | Escucha sin navegador. Si faltan paquetes para tu versión de Python, usa un plan B sin VAD |
| `inicio_automatico.bat` | Acceso directo en la carpeta Inicio | También se activa desde Ajustes → Sistema |
| `instalar_tailscale.bat` | Tailscale | Para usar a Luna fuera de casa. Exige PIN |
| `instalar_collar.bat` | Librerías del collar (ESP32) | Requiere el hardware |
| `ollama pull nomic-embed-text` | Memoria por significado | Unos 274 MB, usa RAM |

## Actualizar

Abre **`actualizar.bat`**: baja la última versión de GitHub y actualiza las librerías. La carpeta `datos/`
(memoria, conversaciones, notas, respaldos) no se toca. Las migraciones de la base de datos solo agregan
columnas y hacen antes un respaldo verificado.

## Respaldos y restauración

- Luna hace un respaldo diario (`.zip` verificado) en `datos/respaldos/` y guarda 14 días.
- Manual: Ajustes → Sistema → **Crear respaldo**.
- Restaurar: cierra Luna y abre **`restaurar.bat`**. Lista los respaldos, verifica el elegido y guarda una
  copia del estado actual antes de reemplazarlo.

## Verificar que todo quedó bien

- `probar.bat` corre las pruebas automáticas (necesita `requisitos-dev.txt`).
- Ajustes → Sistema → **Diagnóstico del sandbox**: deben salir las 4 barreras activas.
- `http://localhost:8090/api/herramientas` y `/api/autonomia` responden con datos.

## Desinstalar

1. Cierra Luna. Borra `Luna.bat` de la carpeta Inicio (`Win + R` → `shell:startup`) si lo activaste.
2. Copia `datos/` a otro lugar si quieres conservar tu memoria y conversaciones.
3. Borra la carpeta `LEK`. Ollama, Python y Tailscale se quitan desde Configuración → Aplicaciones.

## Problemas frecuentes

- **No arranca / "puerto en uso":** abre otra vez `iniciar.bat`; la nueva instancia apaga la anterior.
- **Responde lento:** con poca RAM libre el modelo local tarda (más de 100 s con Revit abierto). Usa Claude o
  `qwen3:4b`.
- **El celular no abre:** misma Wi-Fi, firewall con **Redes privadas → Permitir**, y PIN puesto.
- **Error de Claude 520 o similar:** es del servicio; Luna reintenta y, si no, usa el cerebro local.
