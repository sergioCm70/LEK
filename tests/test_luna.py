"""Pruebas de caracterización: lo que Luna hacía antes debe seguir funcionando, más lo nuevo."""
import pytest

from conftest import Peticion, Respuesta, cargar_luna, llamada


def test_conversacion_se_guarda_y_sobrevive_al_reinicio(luna, tmp_path):
    luna.PROVEEDORES["ollama"].respuestas = ["Anotado, la entrega es el 5 de diciembre."]
    luna.responder("Mi entrega final es el 5 de diciembre")
    assert luna.ALMACEN.total_mensajes() == 2
    luna.ALMACEN.con.close()
    otra = cargar_luna(tmp_path)          # "reiniciar" a Luna
    otra.responder("¿Cuándo es mi entrega?")
    enviados = otra.PROVEEDORES["ollama"].recibido[0]["mensajes"]
    assert any("5 de diciembre" in m["content"] for m in enviados[1:])


def test_nada_se_olvida_busca_en_conversaciones_viejas(luna):
    luna.ALMACEN.guardar_mensaje("usuario", "El auditorio del proyecto tiene 120 sillas", fecha="2026-10-01T09:00:00")
    for i in range(30):
        luna.ALMACEN.guardar_mensaje("usuario", f"mensaje de relleno {i}")
    luna.responder("¿cuántas sillas tiene el auditorio?")
    ultimo = luna.PROVEEDORES["ollama"].recibido[0]["mensajes"][-1]["content"]
    assert "120 sillas" in ultimo                        # traído al contexto aunque sea viejo
    assert "120 sillas" in luna.buscar_conversaciones(consulta="sillas auditorio")
    assert "120 sillas" in luna.buscar_conversaciones(fecha="2026-10-01")


def test_nueva_conversacion_no_borra_nada(luna):
    luna.responder("hola")
    luna.reiniciar(luna.Mensaje(texto="-"), Peticion())
    luna.responder("tema nuevo")
    enviados = luna.PROVEEDORES["ollama"].recibido[-1]["mensajes"]
    assert len(enviados) == 2 and enviados[1]["content"].endswith("tema nuevo")
    assert luna.ALMACEN.total_mensajes() == 4


def test_con_claude_la_memoria_no_sale_del_pc(luna):
    luna.ALMACEN.recordar("Su contraseña del wifi es secreta123")
    nube, local = luna.PROVEEDORES["claude"], luna.PROVEEDORES["ollama"]
    nube._configurado = True
    nube.respuestas = [llamada("ver_memoria", {})]
    local.respuestas = ["Recuerdo que tu wifi tiene una clave guardada."]
    respuesta = luna.responder("dime algo útil para hoy")   # pedido neutro: el modelo de la nube decide ver_memoria
    texto_nube = str(nube.recibido)
    assert "secreta123" not in texto_nube                 # ni en el prompt ni en ningún mensaje
    assert len(nube.recibido) == 1                         # tras la herramienta privada, el turno sigue en el PC
    assert "secreta123" in str(local.recibido[0]["mensajes"])
    assert respuesta.startswith("Recuerdo")
    ultimo = luna.ALMACEN.ultimos_mensajes(1)[0]
    assert ultimo["privado"] == 1
    nube.respuestas = ["ok"]
    luna.responder("gracias")
    assert "wifi tiene una clave" not in str(nube.recibido[-1]["mensajes"])   # la respuesta privada tampoco sale


def test_si_claude_falla_luna_sigue_y_avisa(luna):
    nube = luna.PROVEEDORES["claude"]
    nube._configurado = True
    nube.respuestas = [luna.ErrorProveedor("saldo", "Your credit balance is too low")]
    r = luna.chat(luna.Mensaje(texto="hola"), Peticion())
    assert r["cerebro"] == "qwen3:8b" and r["degradado"] and "credit" in r["aviso"]


def test_si_ningun_cerebro_responde_lo_dice_claro(luna):
    luna.PROVEEDORES["ollama"].respuestas = [luna.ErrorProveedor("red", "x", reintentable=False)]
    assert "no logro pensar" in luna.responder("hola")


def test_habilidad_de_escala_sigue_funcionando(luna):
    luna.PROVEEDORES["ollama"].respuestas = [llamada("hab_escala_maqueta", {"medida": "12 m", "escala": "1:100"}),
                                             lambda m: Respuesta(texto=m[-1]["content"])]
    assert "12.0 cm" in luna.responder("¿cuánto miden 12 metros a 1:100?")


def test_crear_y_aprobar_habilidad(luna):
    # Sin EJEMPLOS se rechaza, pero igual se avisa con el código (nunca se oculta)
    sin_ejemplos = 'DESCRIPCION = "Duplica"\nPARAMETROS = {"n": "número"}\ndef ejecutar(n):\n    return str(int(n) * 2)'
    assert "No la guardé" in luna.crear_habilidad("duplicar", sin_ejemplos)
    # Riesgo alto (usa os): espera aprobación y no se activa sola
    riesgosa = ('import os\nDESCRIPCION = "Carpeta"\nPARAMETROS = {"n": "número"}\n'
                'def ejecutar(n):\n    return str(int(n) * 2) + os.sep\n'
                'EJEMPLOS = [{"args": {"n": "2"}, "espera_contiene": "4"}]')
    assert "apruebe" in luna.crear_habilidad("duplicar", riesgosa)
    assert "hab_duplicar" not in luna.cargar_habilidades()
    with pytest.raises(Exception):
        luna.aprobar_habilidad(luna.Nombre(nombre="duplicar"), Peticion(host="192.168.1.9"))
    luna.aprobar_habilidad(luna.Nombre(nombre="duplicar"), Peticion())
    assert luna.ejecutar_herramienta("hab_duplicar", {"n": "21"}).startswith("42")   # corre aislada
    notifs = luna.NOTIF.listar()
    assert all(n["tipo"] in ("codigo", "aprobacion") and n["codigo"] for n in notifs[:2])


def test_habilidad_segura_igual_espera_aprobacion_humana(luna):
    """LEK 2.0: ni siquiera el código de riesgo bajo con pruebas superadas se activa solo."""
    codigo = ('DESCRIPCION = "Triplica"\nPARAMETROS = {"n": "número"}\ndef ejecutar(n):\n    return str(int(n) * 3)\n'
              'EJEMPLOS = [{"args": {"n": "2"}, "espera_contiene": "6"}]')
    r = luna.crear_habilidad("triplicar", codigo)
    assert "apruebe" in r and "hab_triplicar" not in luna.cargar_habilidades()
    n = luna.NOTIF.listar()[0]
    assert n["tipo"] == "aprobacion" and "int(n) * 3" in n["codigo"]
    assert "habilidades/triplicar.py" in n["detalle"] and "1/1 ejemplos pasaron" in n["detalle"]
    luna.aprobar_habilidad(luna.Nombre(nombre="triplicar"), Peticion())
    assert luna.ejecutar_herramienta("hab_triplicar", {"n": "5"}) == "15"


def test_automejora_autonoma_solo_si_sergio_la_activa(luna):
    luna.AUTOMEJORA_AUTONOMA = True
    codigo = ('DESCRIPCION = "Duplica"\nPARAMETROS = {"n": "número"}\ndef ejecutar(n):\n    return str(int(n) * 2)\n'
              'EJEMPLOS = [{"args": {"n": "2"}, "espera_contiene": "4"}]')
    assert "ya está activa" in luna.crear_habilidad("duplica", codigo)
    assert luna.NOTIF.listar()[0]["codigo"]


def test_olvidar_invalida_sin_borrar(luna):
    luna.ejecutar_herramienta("recordar", {"dato": "Le gusta el café"})
    assert "Olvidé 1" in luna.ejecutar_herramienta("olvidar", {"texto": "café"})
    assert luna.ALMACEN.recuerdos(incluir_archivados=True)[0]["vigencia"] == "olvidado"


def test_panel_de_inteligencia(luna):
    datos = luna.ver_inteligencia(Peticion())
    ids = {m["id"] for m in datos["modelos"]}
    assert {"claude-haiku-5-5", "qwen3:8b"} <= ids
    assert datos["privacidad"]["memoria"] == "local"
    with pytest.raises(Exception):
        luna.cambiar_inteligencia(luna.CambioInteligencia(respaldo="claude-haiku-5-5"), Peticion())
    luna.cambiar_inteligencia(luna.CambioInteligencia(principal="claude-sonnet-5-5"), Peticion())
    assert luna.CONFIG.get("cerebro", "principal") == "claude-sonnet-5-5"


def test_propuesta_con_ocho_puntos(luna):
    r = luna.proponer_mejora("Búsqueda semántica", problema="busco por palabras", solucion="embeddings",
                             impacto="alto", dificultad="intermedia")
    assert "impacto alto" in r and "todavía no es una mejora hecha" in r


def test_el_comienzo_del_prompt_no_cambia_entre_turnos(luna):
    """Para que Ollama reutilice lo ya procesado: mismo sistema en cada turno, la fecha va en el último mensaje."""
    luna.responder("hola")
    luna.responder("¿qué hora es?")
    a, b = (r["mensajes"][0]["content"] for r in luna.PROVEEDORES["ollama"].recibido)
    assert a == b
    assert "hoy es" in luna.PROVEEDORES["ollama"].recibido[-1]["mensajes"][-1]["content"]
    guardado = luna.ALMACEN.ultimos_mensajes(2)[0]["contenido"]
    assert guardado == "¿qué hora es?"                    # la nota no se guarda en la conversación


def test_catalogo_incluye_modelos_instalados():
    from lek.cerebros.catalogo import catalogo
    m = catalogo("qwen3:8b", ["qwen3:8b", "qwen3:4b", "nomic-embed-text:latest"])
    assert "qwen3:4b" in m and m["qwen3:4b"]["ubicacion"] == "local"
    assert "nomic-embed-text:latest" not in m


def test_fuera_del_pc_siempre_exige_pin(luna):
    remoto, casa, pc = Peticion(host="100.101.102.103"), Peticion(host="192.168.20.30"), Peticion()
    for p in (remoto, casa):                                   # sin PIN configurado: cerrado para otros dispositivos
        with pytest.raises(Exception) as e:
            luna.revisar_pin(p)
        assert getattr(e.value, "status_code", None) == 403
    luna.revisar_pin(pc)                                       # el propio PC siempre pasa
    luna.cambiar_pin_api(luna.CambioPin(nuevo="582914"), pc)
    with pytest.raises(Exception) as e:
        luna.revisar_pin(casa)
    assert e.value.status_code == 401
    luna.revisar_pin(Peticion(host="192.168.20.30", pin="582914"))
    assert "582914" not in open(luna.DATOS / "secretos.json", encoding="utf-8").read()   # guardado cifrado


def test_certificado_incluye_nombre_de_tailscale(luna):
    from cryptography import x509
    crt, _ = luna.certificado("192.168.20.21", ("100.101.102.103",), ("zaza.tail1234.ts.net",))
    cert = x509.load_pem_x509_certificate(open(crt, "rb").read())
    alt = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "zaza.tail1234.ts.net" in alt.get_values_for_type(x509.DNSName)
    assert any(str(i) == "100.101.102.103" for i in alt.get_values_for_type(x509.IPAddress))


def test_pedido_privado_ni_siquiera_llega_a_la_nube(luna):
    """El enrutador reconoce un pedido sobre la memoria y lo procesa en el PC desde el principio."""
    luna.ALMACEN.recordar("Su contraseña del wifi es secreta123")
    nube, local = luna.PROVEEDORES["claude"], luna.PROVEEDORES["ollama"]
    nube._configurado = True
    local.respuestas = ["Recuerdo varias cosas tuyas."]
    luna.responder("¿qué recuerdas de mí?")
    assert nube.recibido == []
    assert "secreta123" in str(local.recibido[0]["mensajes"])
    assert luna.ALMACEN.ultimos_mensajes(2)[0]["privado"] == 1     # el pedido queda marcado privado
