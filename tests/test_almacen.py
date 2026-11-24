import json

from lek.almacen import Almacen


def test_conversaciones_se_guardan_y_se_encuentran(tmp_path):
    a = Almacen(tmp_path)
    a.guardar_mensaje("usuario", "La maqueta del centro de resiliencia va en escala 1:100", fecha="2026-11-20T10:00:00")
    a.guardar_mensaje("luna", "Anotado: escala 1:100.")
    a.guardar_mensaje("usuario", "¿Qué clima hace?")
    assert [m["rol"] for m in a.ultimos_mensajes(2)] == ["luna", "usuario"]
    encontrados = a.buscar_mensajes("¿en qué escala va la maqueta?")
    assert any("1:100" in m["contenido"] for m in encontrados)
    assert len(a.mensajes_del_dia("2026-11-20")) == 1


def test_los_datos_sobreviven_a_reabrir(tmp_path):
    a = Almacen(tmp_path)
    a.guardar_mensaje("usuario", "recuerda esto")
    a.con.close()
    b = Almacen(tmp_path)
    assert b.total_mensajes() == 1


def test_olvidar_archiva_y_no_destruye(tmp_path):
    a = Almacen(tmp_path)
    assert a.recordar("Su entrega final es el viernes")
    assert not a.recordar("su entrega final es el viernes")  # duplicado
    assert a.archivar_recuerdos("entrega") == 1
    assert a.recuerdos() == []
    assert len(a.recuerdos(incluir_archivados=True)) == 1


def test_migracion_desde_json_es_completa_e_idempotente(tmp_path):
    (tmp_path / "conversaciones.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {"fecha": "2026-11-24T00:05:12", "cliente": "web", "usuario": "Hola", "luna": "Hola, Sergio", "segundos": 3},
        {"fecha": "2026-11-24T00:06:09", "cliente": "web", "usuario": "¿qué día es?", "luna": "Martes", "segundos": 2},
    ]), encoding="utf-8")
    (tmp_path / "memoria.json").write_text(json.dumps({"datos": [{"dato": "Vive en Palmira", "fecha": "2026-11-23"}]}),
                                           encoding="utf-8")
    (tmp_path / "estado.json").write_text(json.dumps({"claude": {"tokens_entrada": 100, "tokens_salida": 5,
                                                                 "usd": 0.01, "consultas": 1}}), encoding="utf-8")
    a = Almacen(tmp_path)
    informe = a.migrar_desde_json()
    assert informe == {"estado": "migrado", "mensajes": 4, "recuerdos": 1, "llamadas": 1}
    assert (tmp_path / "respaldo_v0" / "conversaciones.jsonl").exists()
    assert (tmp_path / "conversaciones.jsonl").exists()  # el original no se toca
    assert a.migrar_desde_json() == {"estado": "ya migrado"}
    assert a.total_mensajes() == 4
    assert a.buscar_mensajes("qué día")


def test_respaldo_diario_y_rotacion(tmp_path):
    a = Almacen(tmp_path)
    a.guardar_mensaje("usuario", "hola")
    carpeta = tmp_path / "respaldos"
    carpeta.mkdir()
    for i in range(20):
        (carpeta / f"luna-2026-01-{i + 1:02d}.db").write_text("x")
    destino = a.respaldar(conservar=14)
    assert destino.exists()
    assert len(list(carpeta.glob("luna-*.db"))) == 14


def test_metricas_y_gasto_del_mes(tmp_path):
    a = Almacen(tmp_path)
    a.registrar_llamada("claude-haiku-5-5", "claude", 1.2, 3000, 50, 0.0003)
    a.registrar_llamada("claude-haiku-5-5", "claude", 0, ok=False, error="red")
    a.registrar_llamada("qwen3:8b", "ollama", 20.0)
    s = a.estadisticas_modelos()
    assert s["claude-haiku-5-5"]["llamadas"] == 2 and s["claude-haiku-5-5"]["exitos"] == 1
    assert round(s["claude-haiku-5-5"]["latencia_media"], 1) == 1.2
    assert a.gasto_del_mes() == 0.0003
