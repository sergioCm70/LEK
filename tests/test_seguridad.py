"""Seguridad de acceso (LEK 2.0, fase 1): PIN cifrado, sesiones, bloqueo por intentos, Host y Origin."""
import asyncio
import types

import pytest

from conftest import Peticion
from lek.almacen import Almacen
from lek.seguridad import (AccesoDenegado, Seguridad, host_permitido, origen_permitido, pin_valido)


class Reloj:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def seg(tmp_path):
    avisos = []
    reloj = Reloj()
    s = Seguridad(tmp_path, Almacen(tmp_path), avisar=lambda t, d: avisos.append(t), reloj=reloj)
    s.avisos, s.reloj_falso = avisos, reloj
    return s


def test_pin_se_guarda_cifrado_y_se_verifica(seg, tmp_path):
    seg.cambiar_pin("739204", desde_pc=True)
    texto = (tmp_path / "secretos.json").read_text()
    assert "739204" not in texto and "pbkdf2_sha256" in texto
    assert seg.verificar_pin("739204") and not seg.verificar_pin("739205")


def test_pines_debiles_se_rechazan():
    assert pin_valido("123") and pin_valido("1234") and pin_valido("0000")
    assert pin_valido("482917") == ""


def test_cambiar_pin_desde_fuera_exige_el_actual(seg):
    seg.cambiar_pin("739204", desde_pc=True)
    with pytest.raises(AccesoDenegado):
        seg.cambiar_pin("555812", actual="000111")
    seg.cambiar_pin("555812", actual="739204")
    assert seg.verificar_pin("555812")


def test_pin_de_env_se_migra_cifrado(tmp_path):
    s = Seguridad(tmp_path, Almacen(tmp_path), pin_env="864213")
    assert s.verificar_pin("864213")
    assert "864213" not in (tmp_path / "secretos.json").read_text()
    s2 = Seguridad(tmp_path, Almacen(tmp_path), pin_env="864213")    # mismo .env: no lo vuelve a cifrar
    assert s2.verificar_pin("864213")


def test_sin_pin_solo_el_pc(seg):
    seg.autorizar("127.0.0.1", local=True)
    with pytest.raises(AccesoDenegado) as e:
        seg.autorizar("192.168.1.5", local=False, pin="1234")
    assert e.value.codigo == 403


def test_sesion_caduca_y_se_revoca(seg):
    seg.cambiar_pin("739204", desde_pc=True)
    token = seg.crear_sesion("739204", "192.168.1.5", "iPhone")
    seg.autorizar("192.168.1.5", local=False, sesion=token)
    seg.reloj_falso.t += 31 * 86400                       # 31 días sin uso
    assert not seg.sesion_valida(token)
    token2 = seg.crear_sesion("739204", "192.168.1.5")
    assert seg.revocar_sesiones() == 1
    with pytest.raises(AccesoDenegado):
        seg.autorizar("192.168.1.5", local=False, sesion=token2)


def test_cambiar_pin_cierra_las_sesiones(seg):
    seg.cambiar_pin("739204", desde_pc=True)
    token = seg.crear_sesion("739204", "10.0.0.2")
    seg.cambiar_pin("555812", desde_pc=True)
    assert not seg.sesion_valida(token)


def test_bloqueo_por_intentos_y_escalado(seg):
    seg.cambiar_pin("739204", desde_pc=True)
    for _ in range(5):
        with pytest.raises(AccesoDenegado):
            seg.autorizar("10.0.0.9", local=False, pin="000000")
    with pytest.raises(AccesoDenegado) as e:                  # bloqueado aunque ahora acierte
        seg.autorizar("10.0.0.9", local=False, pin="739204")
    assert e.value.codigo == 429
    assert "Intentos de PIN bloqueados" in seg.avisos
    seg.autorizar("10.0.0.10", local=False, pin="739204")     # otra IP no queda bloqueada
    seg.reloj_falso.t += 61
    seg.autorizar("10.0.0.9", local=False, pin="739204")
    for _ in range(5):                                        # segundo bloqueo: el doble
        with pytest.raises(AccesoDenegado):
            seg.autorizar("10.0.0.9", local=False, pin="000000")
    seg.reloj_falso.t += 61
    with pytest.raises(AccesoDenegado) as e:
        seg.autorizar("10.0.0.9", local=False, pin="739204")
    assert e.value.codigo == 429


def test_bloqueo_global(seg):
    seg.cambiar_pin("739204", desde_pc=True)
    for i in range(31):
        with pytest.raises(AccesoDenegado):
            seg.autorizar(f"10.0.1.{i}", local=False, pin="000000")
    with pytest.raises(AccesoDenegado) as e:
        seg.autorizar("10.0.2.1", local=False, pin="739204")
    assert e.value.codigo == 429 and "Acceso remoto bloqueado" in seg.avisos
    seg.autorizar("127.0.0.1", local=True)                    # el PC sigue funcionando


def test_host_contra_dns_rebinding():
    for h in ("localhost:8090", "127.0.0.1:8090", "[::1]:8090", "192.168.20.21:8443", "zaza.tail1234.ts.net:8443"):
        assert host_permitido(h), h
    for h in ("evil.com", "localhost.evil.com:8090", "", "rebind.attacker.net:8090"):
        assert not host_permitido(h), h
    assert host_permitido("mi-pc.casa:8443", {"mi-pc.casa"})


def test_origen_contra_csrf():
    assert origen_permitido("POST", "localhost:8090", "http://localhost:8090", "same-origin")
    assert not origen_permitido("POST", "localhost:8090", "https://evil.com", "cross-site")
    assert not origen_permitido("POST", "localhost:8090", "https://evil.com", "")
    assert not origen_permitido("POST", "localhost:8090", "null", "")
    assert origen_permitido("POST", "192.168.1.2:8443", "", "")          # Atajos / collar: sin Origin
    assert not origen_permitido("GET", "localhost:8090", "", "cross-site")
    assert origen_permitido("GET", "localhost:8090", "", "")


def test_middleware_rechaza_otro_sitio(luna):
    async def siguiente(req):
        return types.SimpleNamespace(headers={}, status_code=200)

    def correr(**kw):
        return asyncio.run(luna.filtro_de_origen(Peticion(**kw), siguiente))

    assert correr(metodo="POST", ruta="/api/archivos/organizar",
                  headers={"origin": "https://evil.com", "sec-fetch-site": "cross-site"}).status_code == 403
    assert correr(headers={"host": "evil.com"}).status_code == 400
    ok = correr(metodo="POST", ruta="/api/chat", headers={"origin": "http://localhost:8090"})
    assert ok.status_code == 200 and ok.headers["X-Frame-Options"] == "DENY"


def test_sesion_por_api(luna):
    pc = Peticion()
    luna.cambiar_pin_api(luna.CambioPin(nuevo="739204"), pc)
    with pytest.raises(Exception) as e:
        luna.abrir_sesion(luna.EntradaPin(pin="111111"), Peticion(host="192.168.1.7"))
    assert e.value.status_code == 401
    r = luna.abrir_sesion(luna.EntradaPin(pin="739204", dispositivo="celular"), Peticion(host="192.168.1.7"))
    token = r.contenido["sesion"]
    assert r.cookies["luna_sesion"][1]["httponly"] and r.cookies["luna_sesion"][1]["samesite"] == "strict"
    luna.revisar_pin(Peticion(host="192.168.1.7", sesion=token))
    assert luna.estado_seguridad(pc)["sesiones"] == 1
    luna.cerrar_sesiones(pc)
    with pytest.raises(Exception):
        luna.revisar_pin(Peticion(host="192.168.1.7", sesion=token))
