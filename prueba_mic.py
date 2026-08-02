# JARVIS — elige el mejor micrófono (ultra-audición)
# Uso:  .venv\Scripts\python.exe prueba_mic.py
import threading

import numpy as np
import sounddevice as sd

DURACION = 2.0
FS = 16000


def probar(indice, etiqueta):
    nivel = {"pico": 0.0, "min": 1.0}
    try:

        def callback(indata, frames, time_info, status):
            rms = float(np.sqrt(np.mean(np.square(indata[:, 0].astype(np.float32)))) / 32768.0)
            if rms > nivel["pico"]:
                nivel["pico"] = rms
            if rms < nivel["min"]:
                nivel["min"] = rms

        with sd.InputStream(
            samplerate=FS,
            channels=1,
            dtype="int16",
            blocksize=1600,
            device=indice,
            callback=callback,
        ):
            threading.Event().wait(DURACION)
        print(
            f"[OK] device {indice:>2} | {etiqueta}\n"
            f"     silencio ~{nivel['min']:.4f} | ruido max ~{nivel['pico']:.4f}"
        )
        return True
    except Exception as e:
        print(f"[X] device {indice:>2} | {etiqueta}: {e}")
        return False


if __name__ == "__main__":
    todos = sd.query_devices()
    entradas = [d for d in todos if d["max_input_channels"] > 0]
    print("Entrada por defecto de Windows:")
    probar(None, "micrófono por defecto")

    vistos = set()
    for d in entradas:
        nombre = d["name"]
        if "Controlador primario" in nombre or "Asignador" in nombre:
            continue
        if nombre not in vistos:
            vistos.add(nombre)
            probar(d["index"], nombre)
    print("\nPon el índice ganador en config.py -> MIC_DEVICE")