# -*- coding: utf-8 -*-
"""vista.py — Los "ojos" de KAREN: captura la pantalla y la interpreta.

Cuando Luis pregunta "¿qué ves en mi pantalla?" o "no entiendo esto, ¿me
explicas?", KAREN toma una captura, la manda a un modelo con visión
(Gemini o Claude, según las API keys disponibles) y responde en su voz.

Sin dependencias nuevas: usa mss (ya en el proyecto) + requests.
"""
import base64
import io
import time

import requests

try:
    import mss
    from PIL import Image
    _CAPTURA_OK = True
except Exception:
    _CAPTURA_OK = False

from config import ANTHROPIC_API_KEY, GEMINI_API_KEY, MODELO_CLAUDE


# Redimensionamos la captura antes de enviarla: menos tokens, más rápido,
# y suficiente para que el modelo lea texto y entienda la interfaz.
_MAX_ANCHO = 1280
_JPEG_CALIDAD = 70

# Cache anti-spam: no recapturar dos veces en menos de este tiempo
_ULTIMA = {"t": 0.0, "img": None}


def _capturar_jpeg() -> bytes | None:
    """Captura el monitor principal y devuelve JPEG en bytes (o None)."""
    if not _CAPTURA_OK:
        return None
    try:
        with mss.mss() as sct:
            # monitors[1] = monitor principal (monitors[0] es el conjunto)
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            shot = sct.grab(mon)
            img = Image.frombytes("RGB", shot.size, shot.rgb)
    except Exception:
        return None

    if img.width > _MAX_ANCHO:
        alto = int(img.height * _MAX_ANCHO / img.width)
        img = img.resize((_MAX_ANCHO, alto), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=_JPEG_CALIDAD)
    return buf.getvalue()


def _prompt(pregunta: str) -> str:
    base = (
        "Eres Karen, la asistente de Luis. Estás viendo una captura de su "
        "pantalla. Responde en español mexicano, cálida y directa, en 2 o 3 "
        "frases máximo (sin listas, sin markdown). Describe lo esencial y, si "
        "hay un error o algo confuso, explícale qué es y qué puede hacer."
    )
    if pregunta and pregunta.strip():
        return f"{base}\n\nLuis pregunta: {pregunta.strip()}"
    return f"{base}\n\nLuis pregunta: ¿Qué ves en mi pantalla?"


def _ver_gemini(jpeg: bytes, pregunta: str, timeout=20) -> str | None:
    if not GEMINI_API_KEY:
        return None
    b64 = base64.b64encode(jpeg).decode("ascii")
    models = ["gemini-flash-lite-latest", "gemini-2.0-flash"]
    body = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": _prompt(pregunta)},
                {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
            ],
        }],
        "generationConfig": {"temperature": 0.6, "maxOutputTokens": 400},
    }
    for model in models:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={GEMINI_API_KEY}"
        )
        try:
            r = requests.post(url, json=body, timeout=timeout)
        except Exception:
            continue
        if r.status_code != 200:
            continue
        cands = r.json().get("candidates") or []
        if not cands:
            continue
        parts = ((cands[0].get("content") or {}).get("parts")) or []
        txt = "".join(p.get("text") or "" for p in parts).strip()
        if txt:
            return txt
    return None


def _ver_claude(jpeg: bytes, pregunta: str, timeout=25) -> str | None:
    if not ANTHROPIC_API_KEY:
        return None
    b64 = base64.b64encode(jpeg).decode("ascii")
    models = [MODELO_CLAUDE or "claude-3-5-haiku-latest"]
    if "sonnet" not in models[0]:
        models.append("claude-3-5-sonnet-latest")
    for model in models[:2]:
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 400,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64,
                            }},
                            {"type": "text", "text": _prompt(pregunta)},
                        ],
                    }],
                    "temperature": 0.6,
                },
                timeout=timeout,
            )
        except Exception:
            continue
        if r.status_code != 200:
            continue
        content = r.json().get("content") or []
        txt = "".join(
            c.get("text") or "" for c in content if c.get("type") == "text"
        ).strip()
        if txt:
            return txt
    return None


def ver_pantalla(pregunta: str = "", bus=None) -> str:
    """Captura la pantalla y devuelve la explicación de KAREN en su voz."""
    if not _CAPTURA_OK:
        return ("No pude activar la captura de pantalla. Necesito las "
                "librerías mss y Pillow instaladas.")
    if not (GEMINI_API_KEY or ANTHROPIC_API_KEY):
        return ("No tengo configurada una IA con visión. Agrega tu clave de "
                "Gemini o Claude en secrets.json y podré ver tu pantalla.")

    if bus is not None:
        try:
            bus.publicar("estado", "Mirando tu pantalla…")
        except Exception:
            pass

    jpeg = _capturar_jpeg()
    if not jpeg:
        return "No logré tomar la captura de pantalla. Reintenta en un momento."

    # Gemini primero (más barato/rápido), Claude de respaldo
    resp = _ver_gemini(jpeg, pregunta) or _ver_claude(jpeg, pregunta)
    if resp:
        return resp
    return ("Vi tu pantalla pero la IA de visión no respondió. Puede ser la "
            "conexión o la cuota. Reintenta en un momento.")
