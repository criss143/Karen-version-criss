# Configuración única de KAREN - edita aqui tus datos personales
import os

BASE = os.path.dirname(os.path.abspath(__file__))

# Nombre del asistente (HUD, voz, wake)
NOMBRE_ASISTENTE = "Karen"

# ---------- VOZ (boca) ----------
# Dalia: femenina mexicana neural, cálida (estilo Karen)
VOZ = "es-MX-DaliaNeural"
VOLUMEN = 1.0
# Prosodia natural, no robótica
VOZ_RATE = "+2%"
VOZ_PITCH = "-1Hz"
VOZ_VOLUME = "+0%"

# ---------- AUDICIÓN (oído) ----------
PALABRA_ACTIVACION = "karen"   # solo responde cuando dices "Karen"
MODELO_STT = "base"            # base=rápido+español decente | small=más preciso y lento
# 2 = fifine Microphone (directo). Evitar Voicemod: llega casi mudo.
# None = auto (prioriza fifine real sobre Voicemod).
MIC_DEVICE = 2                # 2 = fifine directo (NO Voicemod=1)
UMBRAL_HABLA = 0.0020          # bajo: captura directa sin filtros duros
SOLO_POR_PALABRA = True        # True: mic en REPOSO hasta oír "Karen"

# ---------- CEREBRO (LLM) ----------
# Local gratis (siempre): Ollama qwen3:8b con think=false (rápido)
MODELO_LLM = "qwen3:8b"
OLLAMA_URL = "http://127.0.0.1:11434"
USAR_OLLAMA = True
# APIs cloud (gratis / Pro). Prioridad: env â†’ secrets.json â†’ aquí.
# Gemini AI Studio (tu cuenta Pro sirve): https://aistudio.google.com/apikey
# Groq: https://console.groq.com  |  OpenRouter: https://openrouter.ai
def _load_secrets():
    path = os.path.join(BASE, "secrets.json")
    if not os.path.isfile(path):
        return {}
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

_SECRETS = _load_secrets()

def _key(*vals) -> str:
    """Primera key real; ignora vacíos y placeholders tipo pega_aqui."""
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

GROQ_API_KEY = _key(
    os.environ.get("GROQ_API_KEY", ""),
    _SECRETS.get("GROQ_API_KEY", ""),
)
GEMINI_API_KEY = _key(
    os.environ.get("GEMINI_API_KEY", ""),
    os.environ.get("GOOGLE_API_KEY", ""),
    _SECRETS.get("GEMINI_API_KEY", ""),
    _SECRETS.get("GOOGLE_API_KEY", ""),
)
OPENROUTER_API_KEY = _key(
    os.environ.get("OPENROUTER_API_KEY", ""),
    _SECRETS.get("OPENROUTER_API_KEY", ""),
)
# Anthropic (Claude) â€” deja vacío si aún no tienes clave; la sección degrada sola.
# Consíguela en https://console.anthropic.com y pégala en secrets.json -> "ANTHROPIC_API_KEY"
ANTHROPIC_API_KEY = _key(
    os.environ.get("ANTHROPIC_API_KEY", ""),
    os.environ.get("CLAUDE_API_KEY", ""),
    _SECRETS.get("ANTHROPIC_API_KEY", ""),
)
MODELO_CLAUDE = "claude-3-5-haiku-latest"  # veloz y barato; fallback a sonnet si no existe

# ---------- SECCIONES LLM (multi-motor) ----------
SECCIONES_LLM = ["general", "codigo", "creativo", "mundo"]
# Preferencia por defecto de cada sección ("auto" = cadena por defecto)
SECCION_LLM = {
    "codigo": "claude",
    "creativo": "claude",
    "mundo": "groq",
}

# ---------- AUDIO: anti-eco y filtros ----------
SNR_MIN = 3.0             # señal/ruido mínimo para aceptar la captura (evita ruido de fondo)
NO_SPEECH_MAX = 0.35      # faster-whisper: descarta segmentos con no_speech_prob >= esto
AVG_LOGPROB_MIN = -0.55   # log-prob media del segmento: muy negativa = alucinación forzada
ECO_COOLDOWN = 0.45       # segundos tras los que KAREN sigue "hablando" (menos corte del inicio de tu voz)
SINTESIS_TIMEOUT = 20     # timeout (s) de edge-tts para que boca nunca cuelgue el loop

# ---------- LUCES LED BLE ----------
TIRA_BLE_ADDR = ""             # se rellena automáticamente al parear tu tira
TIRA_BLE_NOMBRES = ("LEDBLE", "LED BLE", "Zengge", "Magic Light", "LEDnet",
                    "Fenix", "Light", "BT-LED", "HM-", "LAMPLED", "XXX")

# ---------- MONITOREO DE WEBS ----------
SITIOS = [
    # "https://tudominio.com",   â† añade aquí tus páginas y descomenta
]
INTERVALO_MONITOREO = 300      # segundos entre revisiones de tus webs
LIMITE_LENTO_MS = 2000         # más de esto = "web lenta"
TG_TOKEN = ""                  # opcional: token de tu bot de Telegram
TG_CHAT_ID = ""                # opcional: tu chat_id de Telegram
