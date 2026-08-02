import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

from core.eventos import Bus
from core.memoria import Memoria
from acciones import Acciones
from core.cerebro import Cerebro

bus = Bus()
acciones = Acciones(bus)
cerebro = Cerebro(bus, Memoria(), acciones)

print("Proveedores:", cerebro.llm.proveedores())

# 1) Gemini directo
t0 = time.time()
r = cerebro.llm.chat("Cuéntame algo interesante", system="Responde breve en español, 1 frase.", timeout=10, seccion="general")
print(f"chat LLM (cadena): {time.time()-t0:.2f}s -> prov={cerebro.llm.ultimo_proveedor} ms={cerebro.llm.ultimo_ms} -> {str(r)[:60]!r}")

# 2) Ollama directo (fallback local)
t0 = time.time()
r2 = cerebro.llm._ollama("Di hola en una frase corta.", "Responde breve en español.", timeout=25, max_tokens=60)
print(f"ollama directo: {time.time()-t0:.2f}s -> {str(r2)[:60]!r}")

# 3) Cerebro completo (atajo)
for frase in ["¿qué hora es?", "cómo estás", "cuéntame algo interesante", "pon un temporizador de 10 segundos"]:
    t0 = time.time()
    resp = cerebro.procesar(frase)
    dt = time.time() - t0
    print(f"procesar({frase!r}): {dt:.2f}s prov={cerebro.llm.ultimo_proveedor} -> {str(resp)[:70]!r}")
