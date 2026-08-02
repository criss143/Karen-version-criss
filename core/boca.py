# core/boca.py
# Sistema de voz de KAREN — edge-tts + pygame.
# Objetivo: voz femenina cálida y clara (es-MX), sin sonar robótica.
# API pública estable: Boca(bus).decir(texto, esperar=True) — no cambiar firmas.

import asyncio
import atexit
import os
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path

import edge_tts
import pygame

import config

# -- Configuración con valores de respaldo por si faltan en config.py --
VOZ = getattr(config, "VOZ", "es-MX-DaliaNeural")
VOLUMEN = float(getattr(config, "VOLUMEN", 0.9))
VOZ_RATE = getattr(config, "VOZ_RATE", "+8%")
VOZ_PITCH = getattr(config, "VOZ_PITCH", "+1Hz")
VOZ_VOLUME = getattr(config, "VOZ_VOLUME", "+0%")
# Si edge-tts se cuelga (DNS/red), boca.decir no debe congelar el loop
SINTESIS_TIMEOUT = float(getattr(config, "SINTESIS_TIMEOUT", 20))

# Carpeta propia dentro de %TEMP% para no regar MP3 sueltos
TMP_DIR = Path(tempfile.gettempdir()) / "karen_tts"

# Máximo de caracteres por chunk de síntesis (frases largas se parten)
MAX_CHUNK = 240

# Ajustes sutiles de prosodia por emoción, en deltas sobre la base.
# rate en puntos de %, pitch en Hz.
MOODS = {
    "alegria":  {"rate": +6, "pitch": +2},
    "feliz":    {"rate": +6, "pitch": +2},
    "tristeza": {"rate": -3, "pitch": -2},
    "triste":   {"rate": -3, "pitch": -2},
    "enojo":    {"rate": +4, "pitch": -1},
    "enojado":  {"rate": +4, "pitch": -1},
    "amor":     {"rate": +1, "pitch": +1},
    "sorpresa": {"rate": +8, "pitch": +3},
    "miedo":    {"rate": +3, "pitch": +1},
    "neutral":  {"rate": 0,  "pitch": 0},
}

_NUM_UNIDAD = {"%": "por ciento", "°C": "grados", "km/h": "kilómetros por hora",
               "GB": "gigas", "MB": "megas", "TB": "teras"}


def _parse_signed(valor, sufijo):
    """'-8%' -> -8 ; '+4Hz' -> 4. Devuelve int."""
    try:
        return int(str(valor).replace(sufijo, "").replace("+", "").strip())
    except ValueError:
        return 0


def _fmt(valor, sufijo):
    return f"{'+' if valor >= 0 else ''}{valor}{sufijo}"


class Boca:
    def __init__(self, bus=None):
        self.bus = bus
        self.mood = "neutral"
        self._lock = threading.Lock()          # una sola voz a la vez
        self._detener = threading.Event()
        self._hablando = False
        self._mixer_ok = self._init_mixer()

        TMP_DIR.mkdir(exist_ok=True)
        self._limpiar_temporales(todo=True)
        atexit.register(self._limpiar_temporales, todo=True)

        # Si el bus permite suscripción, escuchamos cambios de ánimo.
        # Duck-typing: no rompe si el bus no tiene suscribir().
        for nombre in ("suscribir", "subscribe", "on"):
            fn = getattr(bus, nombre, None)
            if callable(fn):
                try:
                    fn("mood", self._al_cambiar_mood)
                except Exception:
                    pass
                break

    # ---------------- API pública ----------------

    def decir(self, texto, esperar=True):
        """Sintetiza y reproduce `texto`.
        esperar=True  -> bloquea hasta terminar (arranque, main.py).
        esperar=False -> daemon thread, no bloquea FastAPI (/hablar, /comando).
        """
        texto = (texto or "").strip()
        if not texto:
            return
        # Si el lock se quedó colgado (síntesis/red), no encolar para siempre
        if self._lock.locked() and self._hablando is False:
            try:
                self.detener()
            except Exception:
                pass
        if esperar:
            self._trabajo(texto)
        else:
            threading.Thread(target=self._trabajo, args=(texto,),
                             daemon=True, name="boca-tts").start()

    def detener(self):
        """Corta la reproducción en curso (los chunks pendientes se descartan)."""
        self._detener.set()
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass

    def set_mood(self, mood):
        self.mood = str(mood).lower().strip() if mood else "neutral"

    @property
    def hablando(self):
        return self._hablando or self._lock.locked()

    # ---------------- Interno ----------------

    def _al_cambiar_mood(self, dato):
        # El bus manda "alegria" o {"emocion": "alegria"} / {"mood": ...}
        if isinstance(dato, dict):
            dato = dato.get("emocion") or dato.get("mood") or dato.get("valor")
        self.set_mood(dato)

    def _publicar(self, canal, dato):
        if self.bus is None:
            return
        try:
            self.bus.publicar(canal, dato)
        except Exception:
            pass  # el bus jamás debe tumbar la voz

    def _init_mixer(self):
        # edge-tts entrega MP3 a 24 kHz; buffer chico = menos latencia al empezar
        try:
            pygame.mixer.pre_init(frequency=24000, size=-16, channels=1, buffer=1024)
            pygame.mixer.init()
            pygame.mixer.music.set_volume(max(0.0, min(1.0, VOLUMEN)))
            return True
        except Exception as e:
            self._publicar("estado", f"Boca: no pude iniciar el audio ({e}). "
                                     "Revisa el dispositivo de salida en Windows.")
            return False

    def _trabajo(self, texto):
        # No bloquear para siempre si hay otra frase hablando: espera corta y sigue
        got = self._lock.acquire(timeout=25)
        if not got:
            self._publicar("estado", "Boca: ocupada, reintenta en un momento.")
            # Aun así publica el texto al HUD para que se vea la respuesta
            self._publicar("boca", texto)
            return
        try:
            self._detener.clear()
            if not self._mixer_ok:
                self._mixer_ok = self._init_mixer()
                if not self._mixer_ok:
                    self._publicar("boca", texto)
                    self._publicar("estado", "Boca: sin audio de salida.")
                    return
            self._publicar("boca", texto)
            self._hablando = True
            self._publicar("hablando", True)
            try:
                for chunk in self._trocear(self._humanizar(texto)):
                    if self._detener.is_set():
                        break
                    ruta = self._sintetizar(chunk)
                    if ruta is None:
                        break
                    self._reproducir(ruta)
                    time.sleep(0.04)  # micro-corte mínimo entre frases (voz ágil)
            except Exception as e:
                self._publicar("estado", f"Boca: error al hablar ({type(e).__name__}: {e})")
            finally:
                self._hablando = False
                self._publicar("hablando", False)
        finally:
            try:
                self._lock.release()
            except Exception:
                pass

    # ---- Texto: humanización ligera ----

    def _humanizar(self, texto):
        t = re.sub(r"\s+", " ", texto).strip()
        t = re.sub(r"\b(\w{1,20})(?:[\s,;]+\1){2,}\b", r"\1", t, flags=re.I)
        words = re.findall(r"\w+", t.lower())
        if len(words) >= 6:
            from collections import Counter
            w, c = Counter(words).most_common(1)[0]
            if c >= 5 and c / max(len(words), 1) >= 0.4 and len(w) <= 6:
                return "No te entendí bien, Luis. ¿Me lo repites?"
        t = re.sub(r"https?://\S+", "el enlace", t)
        t = t.replace("&", " y ")
        # Palabras EN MAYÚSCULAS suenan deletreadas/gritadas; bajarlas si no son siglas cortas
        t = re.sub(r"\b[A-ZÁÉÍÓÚÑ]{4,}\b", lambda m: m.group(0).capitalize(), t)
        for k, v in _NUM_UNIDAD.items():
            t = t.replace(k, f" {v}")
        # Guiones sueltos -> pausa suave
        t = re.sub(r"\s[-–—]\s", ", ", t)
        # Asegurar espacio tras puntuación (mejora la pausa del motor)
        t = re.sub(r"([,;:.!?])(?=\S)", r"\1 ", t)
        return t.strip()

    def _trocear(self, texto):
        """Divide en frases y agrupa en chunks de hasta MAX_CHUNK caracteres."""
        frases = re.split(r"(?<=[.!?…])\s+", texto)
        chunks, actual = [], ""
        for f in frases:
            if len(actual) + len(f) + 1 <= MAX_CHUNK:
                actual = f"{actual} {f}".strip()
            else:
                if actual:
                    chunks.append(actual)
                # Frase individual demasiado larga: cortar por comas
                while len(f) > MAX_CHUNK:
                    corte = f.rfind(",", 0, MAX_CHUNK)
                    corte = corte if corte > 40 else MAX_CHUNK
                    chunks.append(f[:corte + 1].strip())
                    f = f[corte + 1:].strip()
                actual = f
        if actual:
            chunks.append(actual)
        return chunks or [texto]

    # ---- Prosodia según emoción ----

    def _prosodia(self):
        base_rate = _parse_signed(VOZ_RATE, "%")
        base_pitch = _parse_signed(VOZ_PITCH, "Hz")
        d = MOODS.get(self.mood, MOODS["neutral"])
        return _fmt(base_rate + d["rate"], "%"), _fmt(base_pitch + d["pitch"], "Hz")

    # ---- Síntesis y reproducción ----

    def _sintetizar(self, texto):
        ruta = TMP_DIR / f"{uuid.uuid4().hex}.mp3"
        rate, pitch = self._prosodia()

        async def _run():
            com = edge_tts.Communicate(texto, VOZ, rate=rate, pitch=pitch, volume=VOZ_VOLUME)
            await asyncio.wait_for(com.save(str(ruta)), timeout=SINTESIS_TIMEOUT)

        try:
            asyncio.run(_run())
            if not ruta.exists() or ruta.stat().st_size == 0:
                raise RuntimeError("edge-tts no devolvió audio")
            return ruta
        except asyncio.TimeoutError:
            self._publicar("estado", "Boca: el servicio de voz tardó demasiado. Reintenta.")
            ruta.unlink(missing_ok=True)
            return None
        except Exception as e:
            msg = str(e)
            if any(s in msg.lower() for s in ("getaddrinfo", "dns", "connect", "timed out", "ssl")):
                self._publicar("estado", "Boca: sin conexión con el servicio de voz. "
                                         "Revisa internet o el DNS.")
            else:
                self._publicar("estado", f"Boca: fallo de síntesis ({type(e).__name__}: {e})")
            ruta.unlink(missing_ok=True)
            return None

    def _reproducir(self, ruta):
        try:
            pygame.mixer.music.load(str(ruta))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if self._detener.is_set():
                    pygame.mixer.music.stop()
                    break
                time.sleep(0.05)
        finally:
            # unload libera el archivo en Windows para poder borrarlo
            try:
                pygame.mixer.music.unload()
            except Exception:
                pass
            self._borrar(ruta)

    # ---- Limpieza ----

    @staticmethod
    def _borrar(ruta, intentos=5):
        for _ in range(intentos):
            try:
                Path(ruta).unlink(missing_ok=True)
                return
            except PermissionError:
                time.sleep(0.15)  # Windows a veces suelta el lock con retraso

    @staticmethod
    def _limpiar_temporales(todo=False):
        if not TMP_DIR.exists():
            return
        ahora = time.time()
        for f in TMP_DIR.glob("*.mp3"):
            try:
                if todo or ahora - f.stat().st_mtime > 300:
                    f.unlink()
            except OSError:
                pass
