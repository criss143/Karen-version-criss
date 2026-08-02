# acciones/recordatorios.py
# Recordatorios y temporizadores de KAREN — solo stdlib (threading).
# Cuando un recordatorio dispara, publica en el bus el evento "decir"
# (main.py lo suscribe a boca.decir) y "estado" (para el HUD).
import re
import threading
import time


class GestorRecordatorios:
    def __init__(self, bus=None):
        self.bus = bus
        self._lock = threading.Lock()
        self._items = {}  # id -> {"texto": str, "disparo": float, "segundos": int}
        self._prox = 1

    def programar(self, texto: str, segundos: int) -> int:
        """Agenda un recordatorio y devuelve su id. El disparo habla por el bus."""
        segundos = max(1, int(segundos))
        texto = (texto or "el recordatorio").strip()
        with self._lock:
            rid = self._prox
            self._prox += 1
            self._items[rid] = {
                "texto": texto,
                "disparo": time.time() + segundos,
                "segundos": segundos,
            }
        threading.Thread(
            target=self._esperar,
            args=(rid, texto, segundos),
            daemon=True,
            name=f"recordatorio-{rid}",
        ).start()
        return rid

    def cancelar_todos(self) -> int:
        with self._lock:
            n = len(self._items)
            self._items.clear()
        return n

    def listar(self):
        """[(texto, restante_segundos)] ordenado por tiempo restante."""
        with self._lock:
            ahora = time.time()
            items = [
                (d["texto"], max(0, int(d["disparo"] - ahora)))
                for d in self._items.values()
            ]
        return sorted(items, key=lambda x: x[1])

    def _esperar(self, rid, texto, segundos):
        time.sleep(segundos)
        with self._lock:
            self._items.pop(rid, None)
        if self.bus is not None:
            try:
                if texto == "el temporizador":
                    self.bus.publicar("decir", "Se acabó el temporizador.")
                else:
                    self.bus.publicar("decir", f"Recuerda: {texto}.")
                self.bus.publicar("estado", f"Recordatorio: {texto}")
            except Exception:
                pass


gestor = GestorRecordatorios()


# ---------- Parseo ----------

_NUM_PALABRA = {
    "un": 1, "una": 1, "uno": 1,
    "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
}
_UNIDADES = {"segundo": 1, "minuto": 60, "hora": 3600}

_ACENTOS = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")


def _norm(t):
    return (t or "").lower().translate(_ACENTOS).strip()


_RE_DURACION = re.compile(
    r"(\d+|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s*"
    r"(minutos?|min\b|segundos?|horas?|h\b)"
)


def _segundos_duracion(m):
    n, u = m.group(1), m.group(2)
    try:
        n = int(n)
    except ValueError:
        n = _NUM_PALABRA.get(n)
        if n is None:
            return None
    clave = "minuto" if u.startswith("min") else (
        "hora" if u.startswith("h") else "segundo"
    )
    return n * _UNIDADES[clave]


def _duracion(t):
    """Extrae '10 minutos' / '5 min' / 'un minuto' / '3 horas' → segundos o None."""
    m = _RE_DURACION.search(t)
    if not m:
        return None
    return _segundos_duracion(m)


def _extraer_duracion(t):
    """(segundos, texto_sin_la_duracion) o None si no hay duración."""
    m = _RE_DURACION.search(t)
    if not m:
        return None
    seg = _segundos_duracion(m)
    if seg is None:
        return None
    resto = (t[: m.start()] + t[m.end() :]).strip()
    return seg, resto


def _formatear_duracion(seg):
    seg = int(seg)
    if seg < 60:
        return f"{seg} segundos"
    if seg < 3600:
        m = seg // 60
        return f"{m} minuto{'s' if m != 1 else ''}"
    h = seg // 3600
    return f"{h} hora{'s' if h != 1 else ''}"


_CABECERAS = (
    "recuerdame|recuerda|recordarme|recordar|"
    "ponme un recordatorio|pon un recordatorio|ponte un recordatorio|"
    "dejame un recordatorio"
)


def _comando_recordatorio(t):
    if not any(k in t for k in ("recuerda", "recordatorio", "recordar",
                                "temporizador", "cronometro", "alarma",
                                "cuenta regresiva", "cuenta atras")):
        return None

    # --- listar / cancelar ---
    if any(k in t for k in ("que recordatorios", "cuales recordatorios",
                            "lista de recordatorios", "mis recordatorios",
                            "cuantos recordatorios", "tengo recordatorios")):
        return {"tipo": "recordatorio_listar"}
    if any(k in t for k in ("cancela los recordatorios", "cancela recordatorios",
                            "borra los recordatorios", "borra recordatorios",
                            "quita los recordatorios", "elimina los recordatorios",
                            "cancela el temporizador", "quita el temporizador",
                            "cancela la alarma")):
        return {"tipo": "recordatorio_cancelar"}

    # --- temporizador / alarma / cuenta regresiva: "temporizador de 10 minutos" ---
    if any(k in t for k in ("temporizador", "cronometro", "alarma",
                            "cuenta regresiva", "cuenta atras")):
        dur = _duracion(t)
        if dur:
            return {"tipo": "recordatorio", "texto": "el temporizador", "segundos": dur}

    # --- recuérdame X en DUR (texto primero) ---
    m = re.search(
        rf"(?:{_CABECERAS})\s+(?:para\s+)?(.+?)\s+en\s+(.+)",
        t,
    )
    if m:
        dur = _duracion(m.group(2))
        if dur:
            texto = re.sub(r"^para\s+", "", m.group(1)).strip()
            return {"tipo": "recordatorio", "texto": texto, "segundos": dur}

    # --- recuérdame en DUR [que] X (duración primero) ---
    m = re.search(r"(?:recuerdame|recuerda|recordarme)\s+en\s+(.+)", t)
    if m:
        d = _extraer_duracion(m.group(1))
        if d:
            dur, resto = d
            resto = re.sub(r"^(?:que\s+|para\s+)?", "", resto).strip()
            if resto and _duracion(resto) is None:
                return {"tipo": "recordatorio", "texto": resto, "segundos": dur}

    return None
