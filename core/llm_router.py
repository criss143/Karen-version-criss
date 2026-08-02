# Router multi-motor: Ollama local (rápido, think off) + APIs cloud opcionales.
# Cadena por sección con fallback automático, circuito anti-proveedor-caído
# y caché de respuestas (salvo consultas sensibles al tiempo).
# API pública estable: chat(), proveedores(), warm(), ultimo_proveedor,
# ultimo_ms + (nuevas) motor_de(), set_motor(), estado().
from __future__ import annotations

import os
import re
import time
from typing import Optional

import requests

from config import MODELO_LLM, OLLAMA_URL, USAR_OLLAMA
from config import SECCIONES_LLM as _CONF_SECCIONES
from config import SECCION_LLM as _CONF_SECCION_LLM

try:
    from config import GROQ_API_KEY as _G
except Exception:
    _G = ""
try:
    from config import GEMINI_API_KEY as _GE
except Exception:
    _GE = ""
try:
    from config import OPENROUTER_API_KEY as _OR
except Exception:
    _OR = ""
try:
    from config import ANTHROPIC_API_KEY as _AN
except Exception:
    _AN = ""
try:
    from config import MODELO_CLAUDE as _MODELO_CLAUDE
except Exception:
    _MODELO_CLAUDE = "claude-3-5-haiku-latest"

def _real_key(*vals) -> str:
    bad = ("pega_aqui", "your_api", "tu_key", "xxx", "changeme", "replace", "example")
    for v in vals:
        s = (v or "").strip()
        if not s or len(s) < 16:
            continue
        low = s.lower()
        if any(b in low for b in bad):
            continue
        return s
    return ""

GROQ_API_KEY = _real_key(os.environ.get("GROQ_API_KEY", ""), _G)
GEMINI_API_KEY = _real_key(
    os.environ.get("GEMINI_API_KEY", ""),
    os.environ.get("GOOGLE_API_KEY", ""),
    _GE,
)
OPENROUTER_API_KEY = _real_key(os.environ.get("OPENROUTER_API_KEY", ""), _OR)
ANTHROPIC_API_KEY = _real_key(
    os.environ.get("ANTHROPIC_API_KEY", ""),
    os.environ.get("CLAUDE_API_KEY", ""),
    _AN,
)

# Orden de la cadena de respaldo (el primer disponible que responda gana)
DEFAULT_CHAIN = ["gemini", "groq", "openrouter", "claude", "ollama"]

SECCIONES_LLM = list(_CONF_SECCIONES) if _CONF_SECCIONES else ["general"]
# Preferencia por defecto de cada sección ("auto" = cadena por defecto)
_SECCION_PREF = dict(_CONF_SECCION_LLM) if _CONF_SECCION_LLM else {
    "codigo": "claude",
    "creativo": "claude",
    "mundo": "groq",
}

# Timeouts por proveedor: rápidos → menos latencia total de la cadena
TIMEOUTS = {"gemini": 4, "groq": 5, "openrouter": 5, "claude": 6, "ollama": 10}
# Tras un fallo, un proveedor queda en espera este tiempo (no reintentar spam)
CIRCUITO_ESPERA = 25

# Caché: respuestas repetidas sin red (TTL corto; consultas temporales la saltan)
CACHE_MAX = 20
CACHE_TTL = 120
_SENSIBLE_TIEMPO = re.compile(
    r"(hora|fecha|clima|llueve|noticia|hoy|mañana|ahora|minuto|día|semana|"
    r"estado del pc|estadística|dólar|peso|precio|tiempo|weather|time\b)",
    re.IGNORECASE,
)


def _clean(txt: str) -> str:
    if not txt:
        return ""
    t = re.sub(r" thinking[\s\S]*? response", "", txt, flags=re.I)
    t = re.sub(r"<\|.*?\|>", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    # Colapsar spam tipo "no no no no..." o la misma palabra 4+
    t = re.sub(r"\b(\w{1,20})(?:\s+[\W]*\1){3,}\b", r"\1", t, flags=re.I)
    # Si >40% es la misma palabra corta → basura
    words = re.findall(r"\w+", t.lower())
    if len(words) >= 8:
        from collections import Counter
        w, c = Counter(words).most_common(1)[0]
        if c >= 6 and c / len(words) >= 0.45 and len(w) <= 6:
            return ""
    return t


class LLMRouter:
    def __init__(self):
        self.ultimo_proveedor = "ninguno"
        self.ultimo_ms = 0
        self._ollama_ok = None
        self._warmed = False
        self._caidos = {}          # prov -> timestamp del último fallo
        self._cache = {}           # (seccion, user.lower()) -> (ts, texto)
        self._motor_manual = {}    # seccion -> override de motor
        self._lat = {}             # prov -> ms de la última respuesta buena

    # ---------------- API pública ----------------

    def proveedores(self) -> list:
        """Proveedores realmente disponibles (con clave válida / activos)."""
        out = []
        if GEMINI_API_KEY:
            out.append("gemini")
        if GROQ_API_KEY:
            out.append("groq")
        if OPENROUTER_API_KEY:
            out.append("openrouter")
        if ANTHROPIC_API_KEY:
            out.append("claude")
        if USAR_OLLAMA:
            out.append("ollama")
        return out or ["ollama"]

    def motor_de(self, seccion: Optional[str] = None) -> str:
        """Motor efectivo de una sección: override manual > preferencia config."""
        seccion = seccion or "general"
        m = (self._motor_manual.get(seccion) or "").strip().lower()
        if m:
            return m
        return (_SECCION_PREF.get(seccion) or "auto").strip().lower() or "auto"

    def set_motor(self, seccion: str, motor: str) -> bool:
        """Fija el motor preferido de una sección. motor='auto' restaura la cadena."""
        motor = (motor or "").strip().lower()
        validos = {"auto", "gemini", "groq", "openrouter", "claude", "ollama"}
        if seccion not in SECCIONES_LLM or motor not in validos:
            return False
        self._motor_manual[seccion] = motor
        return True

    def estado(self) -> dict:
        return {
            "ok": True,
            "secciones": list(SECCIONES_LLM),
            "motores": {s: self.motor_de(s) for s in SECCIONES_LLM},
            "cadena": list(DEFAULT_CHAIN),
            "disponibles": self.proveedores(),
            "latencias": dict(self._lat),
            "ultimo": self.ultimo_proveedor,
            "ms": self.ultimo_ms,
        }

    def warm(self):
        """Precarga Ollama en background (sin bloquear el arranque)."""
        if self._warmed:
            return
        self._warmed = True
        try:
            self._ollama("ok", "di ok", timeout=12)
        except Exception:
            pass

    def chat(
        self,
        user: str,
        system: str = "",
        timeout: float = 16.0,
        max_tokens: int = 90,
        prefer: Optional[str] = None,
        seccion: str = "general",
    ) -> Optional[str]:
        user = (user or "").strip()
        if not user:
            return None

        cacheable = not _SENSIBLE_TIEMPO.search(user)
        clave = (seccion, user.lower())
        if cacheable:
            res, hit = self._cache_get(clave)
            if hit:
                self.ultimo_proveedor = "cache"
                self.ultimo_ms = 0
                return res

        t0 = time.time()
        for prov in self._cadena(seccion, prefer):
            try:
                t_p = time.time()
                if prov == "groq":
                    txt = self._groq(user, system, timeout=min(timeout, TIMEOUTS["groq"]), max_tokens=max_tokens)
                elif prov == "gemini":
                    txt = self._gemini(user, system, timeout=min(timeout, TIMEOUTS["gemini"]), max_tokens=max_tokens)
                elif prov == "openrouter":
                    txt = self._openrouter(user, system, timeout=min(timeout, TIMEOUTS["openrouter"]), max_tokens=max_tokens)
                elif prov == "claude":
                    txt = self._claude(user, system, timeout=min(timeout, TIMEOUTS["claude"]), max_tokens=max_tokens)
                else:
                    txt = self._ollama(user, system, timeout=min(timeout, TIMEOUTS["ollama"]), max_tokens=max_tokens)
                txt = _clean(txt or "")
                if txt and len(txt) > 1:
                    # No pisar detalle tipo gemini:2.5-flash si el provider lo seteó
                    if not (isinstance(self.ultimo_proveedor, str) and self.ultimo_proveedor.startswith(prov + ":")):
                        self.ultimo_proveedor = prov
                    self.ultimo_ms = int((time.time() - t0) * 1000)
                    self._lat[prov] = int((time.time() - t_p) * 1000)
                    if cacheable:
                        self._cache_put(clave, txt)
                    return txt
                # Respondió vacío → cuenta como fallo
                self._caidos[prov] = time.time()
            except Exception:
                self._caidos[prov] = time.time()
                continue
        self.ultimo_proveedor = "fallo"
        self.ultimo_ms = int((time.time() - t0) * 1000)
        return None

    # ---------------- Interno ----------------

    def _cadena(self, seccion: str, prefer: Optional[str] = None) -> list:
        disp = self.proveedores()
        pref = self.motor_de(seccion)
        if prefer and prefer in disp:
            pref = prefer
        if pref in disp:
            chain = [pref] + [p for p in disp if p != pref]
        else:
            # Auto (o preferencia no disponible): ordenar por latencia medida,
            # el más rápido primero → menos tiempo de espera percibido.
            chain = sorted(disp, key=lambda p: (self._lat.get(p, 9999), p))
        # Circuito: saltar proveedores caídos hace <CIRCUITO_ESPERA,
        # salvo que filtrar deje la cadena vacía (entonces reintentar todo).
        ahora = time.time()
        filtrado = [p for p in chain if ahora - self._caidos.get(p, 0) >= CIRCUITO_ESPERA]
        return filtrado or chain

    def _cache_get(self, clave):
        v = self._cache.get(clave)
        if not v:
            return None, False
        ts, res = v
        if res is None or time.time() - ts > CACHE_TTL:
            self._cache.pop(clave, None)
            return None, False
        return res, True

    def _cache_put(self, clave, res):
        if res is None:
            return
        self._cache[clave] = (time.time(), res)
        if len(self._cache) > CACHE_MAX:
            # LRU barato: expulsar la entrada más vieja
            vieja = min(self._cache, key=lambda k: self._cache[k][0])
            self._cache.pop(vieja, None)

    def _ollama(self, user, system, timeout=10.0, max_tokens=90):
        if not USAR_OLLAMA:
            return None
        # think:false es clave: qwen3:8b sin esto se queda pensando y tarda/falla
        payload = {
            "model": MODELO_LLM,
            "prompt": user,
            "system": (system or "") + "\n/no_think",
            "stream": False,
            "think": False,
            "keep_alive": "60m",
            "options": {
                "temperature": 0.55,
                "num_predict": max_tokens,
                "top_p": 0.85,
                "repeat_penalty": 1.35,
                "frequency_penalty": 0.4,
                "num_ctx": 2048,
            },
        }
        r = requests.post(
            f"{OLLAMA_URL}/api/generate", json=payload, timeout=timeout
        )
        if r.status_code != 200:
            return None
        j = r.json()
        return (j.get("response") or "").strip()

    def _groq(self, user, system, timeout=6.0, max_tokens=90):
        if not GROQ_API_KEY:
            return None
        # Llama 3.3 70B en Groq free: muy rápido
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system or "Eres un asistente breve."},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.7,
                "max_tokens": max_tokens,
            },
            timeout=timeout,
        )
        if r.status_code != 200:
            return None
        choices = r.json().get("choices") or []
        if not choices:
            return None
        return (choices[0].get("message") or {}).get("content") or ""

    def _gemini(self, user, system, timeout=5.0, max_tokens=90):
        if not GEMINI_API_KEY:
            return None
        # gemini-flash-latest devuelve texto VACÍO (modelo de pensamiento) y
        # hacía que el router marcara a Gemini como fallo: no incluirlo.
        models = [
            "gemini-flash-lite-latest",  # sin thinking, cuota más holgada
            "gemini-3.5-flash-lite",
        ]
        prompt = f"{system}\n\nUsuario: {user}" if system else user
        # Gemini 3.x gasta thoughtsTokenCount antes del texto: headroom alto.
        out_tokens = max(int(max_tokens) * 6, 768)
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": out_tokens,
            },
        }
        last_err = None
        for model in models:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={GEMINI_API_KEY}"
            )
            try:
                r = requests.post(url, json=body, timeout=timeout)
            except Exception as e:
                last_err = e
                continue
            if r.status_code != 200:
                last_err = r.status_code
                continue
            cands = r.json().get("candidates") or []
            if not cands:
                continue
            parts = ((cands[0].get("content") or {}).get("parts")) or []
            txt = "".join(
                (p.get("text") or "") for p in parts if not p.get("thought")
            ).strip()
            if not txt:
                txt = "".join(p.get("text") or "" for p in parts).strip()
            if txt:
                self.ultimo_proveedor = f"gemini:{model}"
                return txt
        if last_err is not None:
            return None
        return None

    def _claude(self, user, system, timeout=8.0, max_tokens=90):
        if not ANTHROPIC_API_KEY:
            return None
        # Máx 2 modelos por llamada: el configurado + sonnet como respaldo
        models = [_MODELO_CLAUDE or "claude-3-5-haiku-latest"]
        if "sonnet" not in models[0]:
            models.append("claude-3-5-sonnet-latest")
        models = models[:2]
        out_tokens = max(int(max_tokens) + 32, 64)
        for model in models:
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
                        "max_tokens": out_tokens,
                        "system": system or "Eres un asistente breve.",
                        "messages": [{"role": "user", "content": user}],
                        "temperature": 0.7,
                    },
                    timeout=timeout,
                )
            except Exception:
                continue
            if r.status_code != 200:
                continue
            j = r.json()
            content = j.get("content") or []
            txt = "".join(
                (c.get("text") or "") for c in content if c.get("type") == "text"
            ).strip()
            if txt:
                self.ultimo_proveedor = f"claude:{model}"
                return txt
        return None

    def _openrouter(self, user, system, timeout=6.0, max_tokens=90):
        if not OPENROUTER_API_KEY:
            return None
        # Modelo :free de OpenRouter
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://127.0.0.1:8000",
                "X-Title": "KAREN",
            },
            json={
                "model": "meta-llama/llama-3.3-70b-instruct:free",
                "messages": [
                    {"role": "system", "content": system or "Eres un asistente breve."},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.7,
                "max_tokens": max_tokens,
            },
            timeout=timeout,
        )
        if r.status_code != 200:
            return None
        choices = r.json().get("choices") or []
        if not choices:
            return None
        return (choices[0].get("message") or {}).get("content") or ""