import json, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from config import GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY, ANTHROPIC_API_KEY

print("Keys presentes:", {k: bool(v) for k, v in {
    "GEMINI": GEMINI_API_KEY, "GROQ": GROQ_API_KEY,
    "OPENROUTER": OPENROUTER_API_KEY, "CLAUDE": ANTHROPIC_API_KEY}.items()})
print("Largo key gemini:", len(GEMINI_API_KEY) if GEMINI_API_KEY else 0)

try:
    t0 = time.time()
    r = requests.get("http://127.0.0.1:11434/api/tags", timeout=3)
    print(f"Ollama: HTTP {r.status_code} en {time.time()-t0:.2f}s ->", [m.get("name") for m in r.json().get("models", [])][:8])
except Exception as e:
    print("Ollama: NO disponible ->", type(e).__name__, e)

if GEMINI_API_KEY:
    models = ["gemini-2.5-flash-lite", "gemini-flash-lite-latest", "gemini-flash-latest", "gemini-3.5-flash-lite", "gemini-2.0-flash-lite", "gemini-2.5-flash"]
    for m in models:
        t0 = time.time()
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}",
                json={"contents": [{"role": "user", "parts": [{"text": "di ok"}]}],
                      "generationConfig": {"maxOutputTokens": 16, "temperature": 0}},
                timeout=6,
            )
            dt = time.time() - t0
            if r.status_code == 200:
                txt = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                print(f"Gemini {m}: OK {dt:.2f}s -> {txt[:40]!r}")
            else:
                print(f"Gemini {m}: HTTP {r.status_code} {r.text[:90]} {dt:.2f}s")
        except Exception as e:
            print(f"Gemini {m}: EXC {type(e).__name__} {time.time()-t0:.2f}s")
