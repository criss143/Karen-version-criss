# -*- coding: utf-8 -*-
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, r"C:\Users\snayd\jarvis")
log = Path(r"C:\Users\snayd\jarvis\_tts_diag_out.txt")
lines = []

def w(msg):
    lines.append(str(msg))
    print(msg, flush=True)

try:
    from core.boca import Boca, TMP_DIR, VOZ
    w(f"VOZ={VOZ}")
    w(f"TMP={TMP_DIR}")
    b = Boca(bus=None)
    w(f"mixer_ok={b._mixer_ok}")
    t0 = time.time()
    b.decir("Hola Luis, prueba de voz.", esperar=True)
    w(f"elapsed={time.time()-t0:.2f}")
    w(f"hablando={b.hablando}")
    files = list(TMP_DIR.glob("*"))
    w(f"tmp_files={len(files)}")
except Exception:
    w(traceback.format_exc())

log.write_text("\n".join(lines), encoding="utf-8")
