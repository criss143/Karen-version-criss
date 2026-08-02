# Mundo real: noticias, clima y stats gratis (sin API key obligatoria)
from __future__ import annotations

import datetime
import re
import time
import xml.etree.ElementTree as ET
from html import unescape
from typing import Optional
from urllib.parse import quote_plus

import requests

_CACHE = {}
_CACHE_TTL = 900  # 15 min


def _cache_get(key):
    item = _CACHE.get(key)
    if not item:
        return None
    if time.time() - item[0] > _CACHE_TTL:
        return None
    return item[1]


def _cache_set(key, val):
    _CACHE[key] = (time.time(), val)
    return val


def _strip_html(s: str) -> str:
    s = unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _get(url, timeout=8, headers=None):
    h = {
        "User-Agent": "JARVIS/1.0 (personal assistant; +local)",
        "Accept": "application/rss+xml, application/xml, text/xml, application/json, */*",
    }
    if headers:
        h.update(headers)
    r = requests.get(url, timeout=timeout, headers=h)
    r.raise_for_status()
    return r


def noticias_hoy(pais="es", max_items=5, tema: Optional[str] = None) -> str:
    """Titulares del día vía Google News RSS (gratis)."""
    ck = f"news:{pais}:{tema or 'top'}:{max_items}"
    hit = _cache_get(ck)
    if hit:
        return hit

    if tema:
        q = quote_plus(tema)
        url = f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=MX&ceid=MX:es-419"
    else:
        # Top stories ES/MX
        url = "https://news.google.com/rss?hl=es-419&gl=MX&ceid=MX:es-419"

    try:
        r = _get(url, timeout=8)
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall(".//item"):
            title = _strip_html((item.findtext("title") or "").strip())
            if not title:
                continue
            # Quitar " - Fuente" al final si es muy largo
            title = re.sub(r"\s+-\s+[^-]{2,40}$", "", title).strip()
            items.append(title)
            if len(items) >= max_items:
                break
        if not items:
            return "No pude sacar titulares ahora. Reintento en un rato."
        fecha = datetime.datetime.now().strftime("%d/%m")
        if tema:
            head = f"Sobre {tema}, hoy {fecha}:"
        else:
            head = f"Titulares de hoy {fecha}:"
        # Para voz: 3 titulares cortos
        cortos = []
        for i, t in enumerate(items[:3], 1):
            words = t.split()
            if len(words) > 14:
                t = " ".join(words[:14]) + "…"
            cortos.append(f"{i}) {t}")
        out = head + " " + " ".join(cortos)
        return _cache_set(ck, out)
    except Exception as e:
        return f"Falló el cable de noticias: {type(e).__name__}."


def clima_simple(ciudad="Mexico City") -> str:
    """Clima gratis vía Open-Meteo (sin key)."""
    ck = f"clima:{ciudad}"
    hit = _cache_get(ck)
    if hit:
        return hit
    try:
        # Geocode
        g = _get(
            f"https://geocoding-api.open-meteo.com/v1/search?name={quote_plus(ciudad)}&count=1&language=es&format=json",
            timeout=6,
        ).json()
        results = g.get("results") or []
        if not results:
            return f"No ubico la ciudad {ciudad}."
        lat = results[0]["latitude"]
        lon = results[0]["longitude"]
        name = results[0].get("name") or ciudad
        w = _get(
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
            f"&timezone=auto",
            timeout=6,
        ).json()
        cur = w.get("current") or {}
        temp = cur.get("temperature_2m")
        hum = cur.get("relative_humidity_2m")
        wind = cur.get("wind_speed_10m")
        code = cur.get("weather_code", 0)
        desc = _wmo(code)
        out = f"En {name}: {temp}°C, {desc}, humedad {hum}%, viento {wind} km/h."
        return _cache_set(ck, out)
    except Exception:
        return "Clima offline un momento."


def _wmo(code: int) -> str:
    m = {
        0: "cielo despejado",
        1: "mayormente despejado",
        2: "parcialmente nublado",
        3: "nublado",
        45: "niebla",
        48: "niebla helada",
        51: "llovizna ligera",
        61: "lluvia ligera",
        63: "lluvia",
        65: "lluvia fuerte",
        71: "nieve ligera",
        80: "chubascos",
        95: "tormenta",
    }
    return m.get(int(code or 0), "condiciones mixtas")


def stats_pc() -> str:
    """Stats del PC (psutil si hay)."""
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=0.15)
        ram = psutil.virtual_memory()
        boot = datetime.datetime.fromtimestamp(psutil.boot_time())
        up = datetime.datetime.now() - boot
        days = up.days
        hours = up.seconds // 3600
        mins = (up.seconds % 3600) // 60
        return (
            f"CPU al {cpu:.0f}%, RAM {ram.percent:.0f}% "
            f"({ram.used // (1024**3)} de {ram.total // (1024**3)} GB). "
            f"Encendido {days}d {hours}h {mins}m."
        )
    except Exception:
        return "No pude leer stats del PC ahora."


def fecha_hoy() -> str:
    ahora = datetime.datetime.now()
    dias = [
        "lunes",
        "martes",
        "miércoles",
        "jueves",
        "viernes",
        "sábado",
        "domingo",
    ]
    meses = [
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ]
    return (
        f"Hoy es {dias[ahora.weekday()]} {ahora.day} de {meses[ahora.month - 1]} "
        f"de {ahora.year}, son las {ahora.strftime('%H:%M')}."
    )


def briefing_manana() -> str:
    """Resumen estilo 'qué dicen los periódicos'."""
    news = noticias_hoy(max_items=4)
    clima = clima_simple()
    return f"{fecha_hoy()} {clima} {news}"
