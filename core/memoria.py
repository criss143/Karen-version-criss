# MEMORIA: Jarvis recuerda lo que le cuentas entre sesiones
import json
import os
import threading

from config import BASE

RUTA_MEMORIA = os.path.join(BASE, "memoria.json")


class Memoria:
    def __init__(self, ruta=RUTA_MEMORIA):
        self.ruta = ruta
        self._lock = threading.Lock()
        self.datos = self._cargar()

    def _cargar(self):
        try:
            with open(self.ruta, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"datos": {}, "frases": []}

    def guardar(self):
        with self._lock:
            with open(self.ruta, "w", encoding="utf-8") as f:
                json.dump(self.datos, f, ensure_ascii=False, indent=2)

    def recordar(self, clave, valor):
        with self._lock:
            self.datos["datos"][str(clave)] = valor
            self.guardar()

    def olvidar(self, clave):
        with self._lock:
            self.datos["datos"].pop(str(clave), None)
            self.guardar()

    def recordar_frase(self, frase, texto_usuario):
        with self._lock:
            self.datos["frases"].append({"f": frase, "u": texto_usuario})
            self.datos["frases"] = self.datos["frases"][-50:]
            self.guardar()

    def resumen(self):
        frases = "\n".join(
            f"- {f['f']}" for f in self.datos["frases"][-10:]
        )
        return frases or "(todavía no me has contado nada íntimo)"
