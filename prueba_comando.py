# JARVIS — prueba del cerebro a través del HUD
import json
import os
import requests

PRUEBAS = [
    "¿qué hora es?",
    "cuéntame un chiste",
    "¿cómo estás?",
    "abre el bloc de notas",
    "pon las luces rojas",
    "cómo están mis webs",
    "recuerda que mi color favorito es el verde azulado",
    "¿cuál es mi color favorito?",
]

for t in PRUEBAS:
    try:
        r = requests.post("http://127.0.0.1:8000/comando", json={"texto": t}, timeout=120)
        print(f"[{t}]")
        print(f"   -> {r.json().get('respuesta', '')[:300]}")
    except Exception as e:
        print(f"[{t}] FALLO: {e}")
