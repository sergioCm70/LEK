# Registro de cambios

## 2026-11-26 — LEK 2.0, fases 0 y 1 (auditoría y estabilización)

**Por qué:** la auditoría (`docs/AUDITORIA_LEK2.md`) encontró 4 problemas críticos y 7 altos.

**Seguridad de acceso (C1–C3)**
- PIN obligatorio para cualquier dispositivo que no sea el PC. Sin PIN, solo responde el PC.
- PIN cifrado (PBKDF2), sesiones de 30 días, bloqueo progresivo por intentos y bloqueo global.
- Validación de Host (contra DNS rebinding) y de Origin/Sec-Fetch-Site (contra CSRF), más cabeceras de seguridad.
- Ajustes → Seguridad: poner o cambiar el PIN y cerrar todas las sesiones.

**Habilidades (A2, A3)**
- Aprobación humana obligatoria por defecto (`LUNA_AUTOMEJORA_AUTONOMA=no`).
- Ficha de cada propuesta: archivo, dependencias, permisos, riesgo y pruebas.
- Sandbox de Windows: integridad baja + Job Object, con autoprueba al arrancar. Verificado en el PC: las 4 barreras funcionan.

**Inyección y honestidad (A4, A1)**
- Datos externos marcados; acciones bloqueadas en los turnos contaminados.
- Control de afirmaciones sin herramienta.
- Herramientas `anotar_pendiente`, `ver_pendientes` y `cerrar_pendiente`.

**Datos y continuidad (A6, A7, A5)**
- Respaldo zip completo y verificado cada día, endpoints de respaldo y `restaurar.bat`.
- Arranque con Windows (opción `sistema.iniciar_con_windows`, activada porque Sergio lo pidió).
- Lo que la escucha descarta como ruido queda guardado, pero fuera del contexto.

**Otros (M1, M3, M5)**
- Auditoría de cada herramienta.
- Tope de gasto diario (0,5 USD) y aviso al 80 % del mes.
- Caché de 10 s para las mediciones del PC (`nvidia-smi`).
- Tiempo de espera de Claude reducido de 120 s a 90 s, con 10 s para conectar.

**Pruebas:** 338 → 369, todas pasan.

## 2026-11-24 — Voz y fase 2

- Subtítulos en vivo, Whisper con vocabulario, correcciones aprendidas, nota de interpretación y filtro de ruido.
- Enrutador, memoria por significado, automejora en sandbox, proyectos, organizador, análisis, voz en segundo plano, pulso, monitor, evaluación e interfaz HUD.

## 2026-11-23 — Base

- Luna con FastAPI, Claude más Ollama, memoria permanente en SQLite, Tailscale y PIN fuera de casa.
