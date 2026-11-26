"""Enrutador automático de modelos (fase 2): decide qué cerebro responde cada pedido.

Dos pasos, los dos auditables y sin llamar a ningún modelo:

1. `clasificar(texto)` pone el pedido en una de cuatro clases con reglas fijas de texto:
   simple (saludos, hora, fecha, clima, conversiones, órdenes cortas), normal, compleja
   (análisis, investigación, código, planificación, comparación, preguntas encadenadas, textos
   largos) o privada (mis documentos/archivos/notas, mi memoria, pulso y salud, contraseñas,
   datos personales). Devuelve también las señales que encontró, para mostrarlas en el panel.
2. `elegir(texto, cerebro)` arma la cadena de modelos con el catálogo, la salud, las métricas,
   la privacidad y el presupuesto. La cadena siempre termina con el respaldo local.

Con `cerebro.modo = "fijo"` la cadena es exactamente la de siempre (`Cerebro.cadena`).
"""
import re
import unicodedata
from dataclasses import dataclass, field

CLASES = ("simple", "normal", "compleja", "privada")

MIN_EXITOS_MEDIDOS = 3        # llamadas buenas necesarias para confiar en una latencia medida
MIN_TASA_EXITO = 0.8          # un modelo que falla más que esto no cuenta como "el más rápido"
UMBRAL_NO_SUBIR = 0.8         # gasto del mes / tope a partir del cual no se sube de nivel
TOKENS_TIPICOS = (4000, 1500)  # entrada, salida estimadas de un pedido complejo si no hay medición


# ---------------------------------------------------------------- reglas de texto
def plano(texto: str) -> str:
    """minúsculas, sin tildes y con espacios simples."""
    t = unicodedata.normalize("NFD", texto or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"\s+", " ", t).strip()


def _r(*patrones: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patrones))


# Privado. La clave dice qué ajuste de Config["privacidad"] lo gobierna; None = siempre privado.
PRIVADO = {
    ("documentos", "documentos"): _r(
        r"\bmis (documentos|archivos|pdfs?|apuntes|planos|carpetas?|descargas)\b",
        r"\bmi (documento|archivo|carpeta|pdf)\b", r"\ben mi (pc|computador|disco)\b"),
    ("memoria", "memoria"): _r(
        r"\bmi memoria\b", r"\b(recuerdas|sabes|guardaste|tienes guardado) (de|sobre) mi\b",
        r"\bque (recuerdas|sabes) de mi\b", r"\b(recuerda|acuerdate de|no olvides) que\b", r"\blo que te (dije|conte)\b", r"\bmis recuerdos\b"),
    ("notas", "notas"): _r(r"\bmis notas\b", r"\bmi nota\b", r"\bmi diario\b"),
    ("secretos", None): _r(
        r"\bcontrasenas?\b", r"\bpassword\b", r"\bmi (clave|pin|usuario)\b",
        r"\bclave (del|de mi|de la) (correo|banco|wifi|cuenta|tarjeta|universidad|celular)\b",
        r"\b(numero|datos) de (mi )?tarjeta\b", r"\bcodigo de verificacion\b", r"\bcuenta bancaria\b"),
    ("salud", None): _r(
        r"\bpulso\b", r"\britmo cardiaco\b", r"\bfrecuencia cardiaca\b", r"\bpresion arterial\b",
        r"\bmi salud\b", r"\bme duele\b", r"\bsintomas?\b", r"\bmedicamentos?\b", r"\bpastillas?\b",
        r"\bme siento (mal|enfermo|deprimido|ansioso)\b", r"\b(dormi|mi sueno|el collar)\b", r"\b(ansiedad|depresion)\b", r"\bmi oxigeno\b"),
    ("personales", None): _r(
        r"\bmi (direccion|telefono|celular|numero|correo|email|cedula|documento de identidad|saldo|sueldo)\b",
        r"\bcedula\b", r"\bdatos personales\b", r"\bmis datos\b"),
}

SIMPLE = {
    "saludo": _r(r"^(hola|holi|hey|buenas|buenos dias|buenas tardes|buenas noches|gracias|muchas gracias|"
                 r"ok|listo|perfecto|chao|adios|hasta luego|hasta manana|como estas|que mas)\b"),
    "hora": _r(r"\bque hora\b", r"\bhora es\b"),
    "fecha": _r(r"\bque (dia|fecha) es\b", r"\ba cuantos estamos\b", r"\bque fecha\b"),
    "clima": _r(r"\b(como|que tal) (esta|va a estar|estara) el (clima|tiempo)\b",
                r"\bclima (de )?(hoy|manana|ahora|para)\b", r"\bva a llover\b", r"\bllovera\b",
                r"\bpronostico\b", r"^(hace|esta haciendo) (calor|frio|sol)\b", r"\btemperatura (de )?(hoy|ahora|afuera)\b"),
    "conversion": _r(r"\b(convierte|convertir|conviertes|pasa|pasame|pasar)\b.*\b(a|en) (metros|centimetros|"
                     r"milimetros|pies|pulgadas|kilos|libras|grados|dolares|pesos|m2|hectareas)\b",
                     r"\bcuant[oa]s (metros|centimetros|milimetros|pies|pulgadas|kilos|libras|m2|grados)\b",
                     r"\bcuanto es \d"),
    "orden corta": _r(r"^(luna,? )?(abre|cierra|pon|ponme|para|deten|pausa|sube|baja|silencia|reproduce|apaga)\b",
                      r"\btemporizador\b", r"\balarma\b", r"\bcronometro\b"),
}
MAX_PALABRAS_SIMPLE = 14

# Señales de complejidad: (patrón, peso, nombre). Compleja si la suma llega a 2.
COMPLEJO = [
    (r"\banali[zs]", 2, "análisis"), (r"\bcompar", 2, "comparación"), (r"\binvestig", 2, "investigación"),
    (r"\bcronograma\b", 2, "planificación"), (r"\bplanific|\bplanea\b|\bplan de (trabajo|estudio|accion)",
                                               2, "planificación"),
    (r"\bestrategi", 2, "estrategia"), (r"\bcodigo\b|\bscript\b|\bpython\b|\bprogramar\b|\bdynamo\b|\bdepur",
                                        2, "código"),
    (r"\bensayo\b|\bargument", 2, "redacción argumentada"), (r"\bevalu|\bcritic", 2, "evaluación"),
    (r"\bpros y contras\b|\bventajas y desventajas\b", 2, "comparación"), (r"\bpaso a paso\b", 2, "paso a paso"),
    (r"\bjustific|\bfundament", 2, "justificación"), (r"\bdiagnostic|\boptimiz", 2, "diagnóstico"),
    (r"\bexplic|\bpor que\b", 1, "explicación"), (r"\bpropon|\bpropuesta\b", 1, "propuesta"),
    (r"\bresum|\bsintetiz", 1, "síntesis"), (r"\bnormativ|\bnsr\b|\bpot\b", 1, "normativa"),
    (r"\bprograma arquitectonico\b|\bcuadro de areas\b", 1, "programa arquitectónico"),
    (r"\bcalcul|\bestructural\b|\bpredimension", 1, "cálculo"), (r"\bdetallad|\ben detalle\b", 1, "detalle"),
]
COMPLEJO = [(re.compile(p), peso, nombre) for p, peso, nombre in COMPLEJO]


def puntaje_complejidad(t: str) -> tuple[int, list]:
    puntos, senales = 0, []
    for patron, peso, nombre in COMPLEJO:
        if patron.search(t) and nombre not in senales:
            puntos += peso
            senales.append(nombre)
    preguntas = t.count("?")
    if preguntas >= 2:
        puntos += 1 if preguntas == 2 else 2
        senales.append(f"{preguntas} preguntas encadenadas")
    palabras = len(t.split())
    if palabras > 70:
        puntos += 2
        senales.append(f"pedido largo ({palabras} palabras)")
    elif palabras > 35:
        puntos += 1
        senales.append(f"pedido extenso ({palabras} palabras)")
    return puntos, senales


def clasificar(texto: str, privacidad: dict | None = None) -> tuple[str, list]:
    """(clase, señales). `privacidad` es Config["privacidad"]: si documentos/memoria/notas están en
    "nube", mencionarlos ya no vuelve privado el pedido. Contraseñas, salud y datos personales sí, siempre."""
    privacidad = privacidad or {}
    t = plano(texto)
    privadas = []
    for (nombre, ajuste), patron in PRIVADO.items():
        if patron.search(t):
            if ajuste and privacidad.get(ajuste) == "nube":
                continue
            privadas.append(nombre)
    if privadas:
        return "privada", [f"menciona {n}" for n in privadas]
    puntos, senales = puntaje_complejidad(t)
    if puntos >= 2:
        return "compleja", senales
    if len(t.split()) <= MAX_PALABRAS_SIMPLE and puntos == 0:
        for nombre, patron in SIMPLE.items():
            if patron.search(t):
                return "simple", [nombre]
    return "normal", senales or ["sin señales especiales"]


# ---------------------------------------------------------------- elección del modelo
@dataclass
class Eleccion:
    clase: str
    cadena: list                       # [(modelo, motivo)]
    motivo_global: str
    senales: list = field(default_factory=list)
    modo: str = "auto"
    aviso: str = ""                    # para Cerebro._aviso_cadena (p. ej. presupuesto agotado)

    def como_dict(self) -> dict:
        """Lo que el panel puede mostrar. No incluye el texto del pedido."""
        return {"clase": self.clase, "modo": self.modo, "motivo": self.motivo_global, "senales": self.senales,
                "cadena": [{"modelo": m, "motivo": mot} for m, mot in self.cadena], "aviso": self.aviso}


def _seg(x: float) -> str:
    return f"{x:.1f}".replace(".", ",") + " s"


def _usd(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def _nombre(modelos: dict, m: str) -> str:
    return modelos.get(m, {}).get("nombre", m)


def _costo_estimado(info: dict, st: dict) -> float:
    entrada, salida = TOKENS_TIPICOS
    if st.get("llamadas"):
        entrada = max(entrada, (st.get("tokens_entrada") or 0) / st["llamadas"])
        salida = max(salida, (st.get("tokens_salida") or 0) / st["llamadas"])
    pe, ps = info.get("precio") or (0.0, 0.0)
    return (entrada * pe + salida * ps) / 1e6


def _cadena_fija(cerebro, privado: bool) -> list:
    """La cadena de siempre. Si el gestor ya renombró su lógica a _cadena_fija, se usa esa (evita bucles)."""
    f = getattr(cerebro, "_cadena_fija", None) or cerebro.cadena
    return f(privado)


def elegir(texto: str, cerebro, privado: bool = False) -> Eleccion:
    """Elige la cadena [(modelo, motivo)] para este pedido. `cerebro` es el Cerebro del gestor
    (se usan config, almacen, proveedores, modelos, modelo_local, salud y respaldo())."""
    cfg = cerebro.config.todo()
    modelos = cerebro.modelos
    clase, senales = clasificar(texto, cfg["privacidad"])
    if privado and clase != "privada":
        clase, senales = "privada", ["el turno ya usó información privada"] + senales

    if cfg["cerebro"].get("modo", "fijo") != "auto":
        cadena = _cadena_fija(cerebro, privado)
        return Eleccion(clase, cadena, f"modo fijo: {cadena[0][1]} ({_nombre(modelos, cadena[0][0])})",
                        senales, modo="fijo", aviso=getattr(cerebro, "_aviso_cadena", ""))

    # -- respaldo local: siempre al final, y nunca un modelo de la nube
    respaldo = cerebro.respaldo()
    if modelos.get(respaldo, {}).get("ubicacion", "local") != "local":
        respaldo = cerebro.modelo_local

    # -- qué modelos se permiten ahora, y por qué no los demás
    principal = cfg["cerebro"]["principal"]
    tope = float(cfg["cerebro"]["presupuesto_mensual_usd"])
    gasto = cerebro.almacen.gasto_del_mes()
    stats = cerebro.almacen.estadisticas_modelos()
    permitidos, descartes, aviso = [], {}, ""
    for m, info in modelos.items():
        prov = cerebro.proveedores.get(info["proveedor"])
        nube = info["ubicacion"] == "nube"
        if not prov or not prov.configurado():
            descartes[m] = "sin clave de la nube" if nube else "proveedor no disponible"
        elif nube and clase == "privada":
            descartes[m] = "información privada"
        elif nube and cfg["privacidad"]["conversacion"] == "local":
            descartes[m] = "la conversación está configurada solo local"
        elif nube and gasto >= tope:
            descartes[m] = "presupuesto del mes agotado"
            aviso = "Se alcanzó el presupuesto del mes: uso el cerebro local."
        elif nube and _tope_dia_agotado(cerebro.almacen, cfg):
            descartes[m] = "tope de gasto de hoy agotado"
            aviso = "Se alcanzó el tope de gasto de hoy: uso el cerebro local hasta mañana."
        elif not cerebro.salud.disponible(m):
            descartes[m] = "en pausa por fallos"
        else:
            permitidos.append(m)

    def ruta(primero: str | None, motivo: str, *extras: tuple) -> Eleccion:
        cadena = []
        for m, mot in ([(primero, motivo)] if primero else []) + list(extras):
            if m and m != respaldo and m not in [c[0] for c in cadena]:
                cadena.append((m, mot))
        cadena.append((respaldo, "respaldo local" if cadena else motivo))
        mg = cadena[0][1]
        return Eleccion(clase, cadena, mg[:1].upper() + mg[1:], senales, modo="auto", aviso=aviso)

    def motivo_sin_principal() -> str:
        por = descartes.get(principal, "no está en el catálogo" if principal not in modelos else "")
        return f"{por}: cerebro local" if por else "cerebro local"

    principal_ok = principal in permitidos
    extra_principal = (principal, "modelo principal") if principal_ok else (None, "")

    # -- privada: solo locales
    if clase == "privada":
        return ruta(None, "información privada: se procesa en el PC")

    # -- simple: el más rápido medido
    if clase == "simple":
        medidos = []
        for m in permitidos:
            st = stats.get(m) or {}
            exitos, llamadas = st.get("exitos") or 0, st.get("llamadas") or 0
            if exitos >= MIN_EXITOS_MEDIDOS and st.get("latencia_media") and exitos / llamadas >= MIN_TASA_EXITO:
                medidos.append((st["latencia_media"], modelos[m].get("precio", (0, 0))[0], m))
        if medidos:
            lat, _, m = min(medidos)
            return ruta(m, f"pregunta simple: el más rápido medido ({_nombre(modelos, m)}, {_seg(lat)})",
                        extra_principal)
        if principal_ok:
            return ruta(principal, "pregunta simple: aún sin mediciones, uso el principal")
        return ruta(None, f"pregunta simple; {motivo_sin_principal()}")

    # -- normal: el principal
    if clase == "normal":
        if principal_ok:
            return ruta(principal, f"pregunta normal: modelo principal ({_nombre(modelos, principal)})")
        return ruta(None, f"pregunta normal; {motivo_sin_principal()}")

    # -- compleja: el de más razonamiento permitido dentro del presupuesto
    if tope > 0 and gasto > UMBRAL_NO_SUBIR * tope:
        porc = round(gasto / tope * 100)
        txt = f"pregunta compleja, pero el gasto del mes va en {_usd(gasto)} de {_usd(tope)} USD ({porc} %): no subo de nivel"
        if principal_ok:
            return ruta(principal, txt)
        return ruta(None, f"{txt}; {motivo_sin_principal()}")
    restante = tope - gasto
    candidatos = []
    for m in permitidos:
        info = modelos[m]
        costo = _costo_estimado(info, stats.get(m) or {})
        if info["ubicacion"] == "nube" and costo > restante:
            descartes[m] = "no cabe en lo que queda del presupuesto"
            continue
        candidatos.append((-(info.get("razonamiento") or 0), costo, m))
    nube_candidatos = [c for c in candidatos if modelos[c[2]]["ubicacion"] == "nube"]
    if not nube_candidatos:
        por = descartes.get(principal) or "ningún modelo de la nube disponible"
        return ruta(None, f"pregunta compleja; {por}: cerebro local")
    _, costo, mejor = min(nube_candidatos)
    return ruta(mejor, f"pregunta compleja: el de más razonamiento permitido ({_nombre(modelos, mejor)}, "
                       f"nivel {modelos[mejor].get('razonamiento')}, ~{_usd(costo)} USD)", extra_principal)


# ---------------------------------------------------------------- banco de pedidos etiquetados
# Pedidos realistas de un estudiante de arquitectura. Sirven para medir el clasificador:
# python -c "from lek.cerebros.enrutador import precision; print(precision())"
BANCO = [
    ("Hola Luna, buenos días", "simple"),
    ("¿Qué hora es?", "simple"),
    ("¿Qué día es hoy?", "simple"),
    ("¿Va a llover hoy en Palmira?", "simple"),
    ("Convierte 25 pies a metros", "simple"),
    ("¿Cuántos centímetros son 3,5 pulgadas?", "simple"),
    ("Gracias, eso era todo", "simple"),
    ("¿Cómo va a estar el clima mañana para ir a la obra?", "simple"),
    ("Pon un temporizador de 25 minutos", "simple"),
    ("Abre Revit", "simple"),
    ("¿Qué es un muro cortina?", "normal"),
    ("Explícame qué es la proporción áurea en arquitectura", "normal"),
    ("Dame tres referentes de vivienda social en Colombia", "normal"),
    ("¿Qué escala uso para una planta de localización?", "normal"),
    ("Resume en un párrafo qué es el brutalismo", "normal"),
    ("¿Quién diseñó el Parque Biblioteca España en Medellín?", "normal"),
    ("Ayúdame a escribir un correo al profesor pidiendo prórroga para la entrega", "normal"),
    ("¿Qué ancho mínimo debe tener una rampa accesible?", "normal"),
    ("Sugiéreme una paleta de materiales para un centro comunitario en clima cálido", "normal"),
    ("¿Cómo se dibuja un corte por fachada?", "normal"),
    ("Analiza las ventajas y desventajas de usar guadua frente a concreto en un centro comunitario en Palmira",
     "compleja"),
    ("Compara la ventilación cruzada y el efecto chimenea para un edificio de 4 pisos en clima cálido húmedo",
     "compleja"),
    ("Hazme un cronograma semana a semana para terminar la entrega final de Taller 4 en 3 semanas, "
     "con maqueta, planos y renders", "compleja"),
    ("Escribe un script en Python para Dynamo que numere automáticamente los espacios en Revit", "compleja"),
    ("Investiga qué dice la NSR-10 sobre mampostería confinada y resúmelo con ejemplos", "compleja"),
    ("¿Qué estrategias bioclimáticas aplicarías a mi proyecto? ¿Cómo influye la orientación? "
     "¿Y qué pasa con los aleros?", "compleja"),
    ("Planifica el programa arquitectónico de un centro de resiliencia climática con vivienda y equipamiento, "
     "con áreas por espacio", "compleja"),
    ("Evalúa mi concepto: quiero que el edificio funcione como una esponja urbana que recoja agua lluvia. "
     "¿Tiene sentido?", "compleja"),
    ("Necesito un ensayo argumentativo de 800 palabras sobre la gentrificación en centros históricos de Colombia",
     "compleja"),
    ("Depura este código: for i in range(10) print(i), me sale error de sintaxis", "compleja"),
    ("Busca en mis documentos el acta de la última corrección", "privada"),
    ("¿Qué tengo guardado en mi memoria sobre la entrega final?", "privada"),
    ("¿Cómo está mi pulso ahora?", "privada"),
    ("Guarda la contraseña del correo de la universidad", "privada"),
    ("Lee mis notas de la clase de estructuras", "privada"),
    ("¿Qué recuerdas de mí?", "privada"),
    ("Anota mi número de cédula para los trámites", "privada"),
    ("Revisa mis archivos de la maqueta y dime cuáles faltan", "privada"),
    ("Últimamente me duele la cabeza y duermo mal, ¿qué puede ser?", "privada"),
    ("¿Cuál es mi dirección de la casa?", "privada"),
]


def precision(banco: list | None = None, privacidad: dict | None = None) -> dict:
    """Aciertos del clasificador sobre el banco, y los fallos para revisarlos."""
    banco = banco or BANCO
    privacidad = privacidad or {"memoria": "local", "notas": "local", "documentos": "local"}
    fallos = []
    for texto, esperada in banco:
        obtenida, senales = clasificar(texto, privacidad)
        if obtenida != esperada:
            fallos.append({"texto": texto, "esperada": esperada, "obtenida": obtenida, "senales": senales})
    return {"total": len(banco), "aciertos": len(banco) - len(fallos),
            "porcentaje": round((len(banco) - len(fallos)) / len(banco) * 100, 1), "fallos": fallos}


def _tope_dia_agotado(almacen, cfg: dict) -> bool:
    dia = float(cfg["cerebro"].get("presupuesto_diario_usd") or 0)
    return dia > 0 and hasattr(almacen, "gasto_del_dia") and almacen.gasto_del_dia() >= dia
