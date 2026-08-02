# Central de eventos: conecta el oído, la voz, el cerebro y el HUD.
import queue
import time


class Bus:
    """Cola thread-safe que reparte eventos entre módulos y el HUD."""

    def __init__(self):
        self.cola = queue.Queue()
        self._subs = {}  # tipo -> [callbacks]

    def suscribir(self, tipo, callback):
        """Registra un callback síncrono para un tipo de evento (ej. 'mood')."""
        if not callable(callback):
            return
        self._subs.setdefault(tipo, []).append(callback)

    # alias que busca la boca de Claude
    subscribe = suscribir
    on = suscribir

    def publicar(self, tipo, datos=None):
        # Importante: no usar `datos or {}` — False/0 deben preservarse (hablando=False)
        try:
            self.cola.put_nowait(
                {"tipo": tipo, "datos": datos, "ts": time.time()}
            )
        except Exception:
            pass
        for cb in list(self._subs.get(tipo, [])):
            try:
                cb(datos)
            except Exception:
                pass

    def drenar(self, max_items=500):
        items = []
        try:
            while len(items) < max_items:
                items.append(self.cola.get_nowait())
        except queue.Empty:
            pass
        return items
