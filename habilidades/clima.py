# Habilidad de ejemplo: el clima (Open-Meteo, gratis y sin clave)
import requests

DESCRIPCION = "Dice el clima actual y el pronóstico de hoy en una ciudad."
PARAMETROS = {"ciudad": "nombre de la ciudad, por ejemplo 'Palmira' o 'Cali'"}

CODIGOS = {0: "despejado", 1: "casi despejado", 2: "parcialmente nublado", 3: "nublado", 45: "con niebla",
           48: "con niebla", 51: "con llovizna", 53: "con llovizna", 55: "con llovizna fuerte",
           61: "con lluvia ligera", 63: "con lluvia", 65: "con lluvia fuerte", 80: "con chubascos",
           81: "con chubascos", 82: "con aguaceros", 95: "con tormenta", 96: "con tormenta", 99: "con tormenta"}


def ejecutar(ciudad="Palmira"):
    lugar = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": ciudad, "count": 1, "language": "es"}, timeout=10).json()
    if not lugar.get("results"):
        return f"No encontré la ciudad {ciudad}."
    r = lugar["results"][0]
    datos = requests.get("https://api.open-meteo.com/v1/forecast", timeout=10, params={
        "latitude": r["latitude"], "longitude": r["longitude"], "timezone": "auto",
        "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"}).json()
    ahora, hoy = datos["current"], datos["daily"]
    estado = CODIGOS.get(ahora["weather_code"], "variable")
    return (f"En {r['name']} hay {ahora['temperature_2m']:.0f} grados y está {estado}. "
            f"Hoy entre {hoy['temperature_2m_min'][0]:.0f} y {hoy['temperature_2m_max'][0]:.0f} grados, "
            f"con {hoy['precipitation_probability_max'][0]}% de probabilidad de lluvia.")
