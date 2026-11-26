"""Regenera docs/API_LEK.md leyendo las rutas de servidor.py (sin importarlo). Uso: python scripts/generar_api_doc.py"""
import ast
import datetime
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CABECERA = """# API de LEK

Generada desde `servidor.py` ({fecha}). Desde este PC no se pide PIN; desde otro dispositivo hace falta
la cabecera `X-Asistente-Sesion` (de `POST /api/sesion`) o `X-Asistente-Pin`. Las rutas que cambian algo
aceptan peticiones solo del mismo origen (o de clientes sin `Origin`, como Atajos o el collar).

| Método | Ruta | Función | Descripción |
|---|---|---|---|
"""


def rutas():
    arbol = ast.parse((RAIZ / "servidor.py").read_text(encoding="utf-8"))
    for nodo in arbol.body:
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in nodo.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and isinstance(d.func.value, ast.Name)
                    and d.func.value.id == "app" and d.func.attr in ("get", "post", "put", "delete") and d.args
                    and isinstance(d.args[0], ast.Constant)):
                doc = " ".join((ast.get_docstring(nodo) or "").split())[:160].replace("|", "/")
                yield d.func.attr.upper(), d.args[0].value, nodo.name, doc


def main():
    filas = [f"| {m} | `{r}` | `{f}` | {d} |" for m, r, f, d in rutas()]
    texto = CABECERA.format(fecha=datetime.date.today().strftime("%d/%m/%Y")) + "\n".join(filas) + \
        f"\n\nTotal: {len(filas)} rutas.\n"
    (RAIZ / "docs" / "API_LEK.md").write_text(texto, encoding="utf-8")
    print(f"{len(filas)} rutas")


if __name__ == "__main__":
    main()
