# WEBMON: vigila tus páginas web, avisa si caen o van lentas
import threading
import time

import requests

from config import INTERVALO_MONITOREO, LIMITE_LENTO_MS, SITIOS, TG_CHAT_ID, TG_TOKEN


class WebMon:
    def __init__(self, bus):
        self.bus = bus
        self.ultimos = {}
        self._bloqueo = threading.Lock()
        self._caidas = set()
        self._hilo = None

    # ------------------------------------------------------------------
    def _chequear(self, url):
        try:
            t0 = time.time()
            r = requests.get(url, timeout=10,
                             headers={"User-Agent": "Jarvis-Monitor/1.0"})
            ms = (time.time() - t0) * 1000
            d = {"url": url, "codigo": r.status_code, "ms": round(ms),
                 "estado": "ok" if r.status_code < 500 else "caida"}
        except requests.RequestException:
            d = {"url": url, "codigo": None, "ms": 0, "estado": "caida"}
        with self._bloqueo:
            self.ultimos[url] = d
        return d

    def chequear_todo(self):
        resultados = [self._chequear(u) for u in SITIOS]
        self.bus.publicar("estado", "Revisión de webs terminada.")
        return resultados

    # ------------------------------------------------------------------
    def resumen(self):
        if not SITIOS:
            return ("Todavía no has puesto ninguna web en mi configuración. "
                    "Abre config.py y añade tus páginas en SITIOS.")
        partes = []
        for d in self.chequear_todo():
            if d["estado"] == "ok":
                if d["ms"] > LIMITE_LENTO_MS:
                    partes.append(f"{d['url']} responde, pero va lenta: {int(d['ms'])} milisegundos")
                else:
                    partes.append(f"{d['url']} perfecta en {int(d['ms'])} milisegundos")
            else:
                partes.append(f"{d['url']} está CAIDA{', sin respuesta' if d['codigo'] is None else ', código ' + str(d['codigo'])}")
        return "Estado de tus webs: " + ". ".join(partes) + "."

    # ------------------------------------------------------------------
    def iniciar_bucle(self):
        def bucle():
            while True:
                time.sleep(INTERVALO_MONITOREO)
                for d in self.chequear_todo():
                    if d["estado"] == "caida" and d["url"] not in self._caidas:
                        self._caidas.add(d["url"])
                        self._telegram(d)
                        self.bus.publicar("estado",
                                          f"ALERTA: {d['url']} se ha caído.")
                    elif d["estado"] == "ok":
                        self._caidas.discard(d["url"])

        self._hilo = threading.Thread(target=bucle, daemon=True)
        self._hilo.start()

    def _telegram(self, d):
        if not (TG_TOKEN and TG_CHAT_ID):
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                json={"chat_id": TG_CHAT_ID,
                      "text": f"JARVIS: {d['url']} esta CAIDA"},
                timeout=10,
            )
        except Exception:
            pass
