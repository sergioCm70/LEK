"""Ficha de cada modelo que LUNA puede usar. Agregar un modelo = agregar una entrada aquí.

Precios en USD por millón de tokens (entrada, salida), verificados en
https://platform.claude.com/docs/en/about-claude/pricing el 2026-11-24.
"razonamiento" es una escala relativa de 1 a 5 que se ajustará con el banco de pruebas (fase 4).
"""

PRECIOS_VERIFICADOS = "2026-11-24"


def catalogo(modelo_local: str) -> dict:
    modelos = {
        "claude-haiku-5-5": {"nombre": "Claude Haiku 5.5", "proveedor": "claude", "ubicacion": "nube",
                             "precio": (0.10, 0.50), "razonamiento": 3, "herramientas": True,
                             "nota": "Rápida y muy barata: el día a día"},
        "claude-sonnet-5-5": {"nombre": "Claude Sonnet 5.5", "proveedor": "claude", "ubicacion": "nube",
                              "precio": (2.0, 10.0), "razonamiento": 4, "herramientas": True,
                              "nota": "Mucho más inteligente, unas 20 veces más cara que Haiku"},
        "claude-opus-5-5": {"nombre": "Claude Opus 5.5", "proveedor": "claude", "ubicacion": "nube",
                            "precio": (4.0, 20.0), "razonamiento": 5, "herramientas": True,
                            "nota": "La más inteligente, unas 40 veces más cara que Haiku"},
    }
    ram = {"qwen3:8b": 5.2, "qwen3:4b": 2.6}.get(modelo_local)
    modelos[modelo_local] = {"nombre": f"{modelo_local} (local)", "proveedor": "ollama", "ubicacion": "local",
                             "precio": (0.0, 0.0), "razonamiento": 2, "herramientas": True,
                             "ram_gb": ram, "nota": "Gratis y privado; lento sin una GPU potente"}
    return modelos


def precios_claude(modelos: dict) -> dict:
    return {k: v["precio"] for k, v in modelos.items() if v["proveedor"] == "claude"}
