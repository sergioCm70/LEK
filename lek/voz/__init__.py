"""Voz de LUNA fuera del navegador: palabra de activación local ("Luna") en segundo plano.

Las importaciones son perezosas para que `python -m lek.voz.despertador` funcione sin avisos
y para que importar lek.voz no cargue nada pesado.
"""
_NOMBRES = ("Despertador", "FuenteMemoria", "FuenteMicrofono", "ReconocedorVosk",
            "buscar_modelo", "diagnosticar", "despertador_activado", "tono_wav")

__all__ = list(_NOMBRES)


def __getattr__(nombre):
    if nombre in _NOMBRES:
        from lek.voz import despertador
        return getattr(despertador, nombre)
    raise AttributeError(f"module 'lek.voz' has no attribute {nombre!r}")
