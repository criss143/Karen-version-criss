# OÍDO: micrófono + VAD + faster-whisper + huella de voz (Luis normal / Cris)
import re
import threading
import time
from collections import deque

import numpy as np
import sounddevice as sd

from config import (
    MIC_DEVICE,
    MODELO_STT,
    UMBRAL_HABLA,
    PALABRA_ACTIVACION,
    SOLO_POR_PALABRA,
    SNR_MIN,
    NO_SPEECH_MAX,
    AVG_LOGPROB_MIN,
    ECO_COOLDOWN,
)
from core.vozprint import VozPrint, FS as VP_FS

FS = 16000
BLOQUE = 0.05
PRE_ROLL = 0.75
MAX_FRASE = 16.0
# Silencio largo = no cortar a mitad de frase (pausas naturales)
SILENCIO_FIN = 1.00
SILENCIO_FIN_WAKE = 1.15
MIN_HABLA_BLOQUES = 2
MIN_AUDIO_S = 0.50
VENTANA_ACTIVA_S = 5.0
COOLDOWN_TRAS_VOZ = 0.55
BLOQUEAR_DESCONOCIDOS = False  # True = solo Luis/Cris; False evita falsos "Voz no reconocida"

# Variantes cercanas a "Karen" (STT malinterpreta a menudo).
_WAKE_RE = re.compile(
    r"\b(karen|caren|karin|karem|karren|karén|"
    r"kren|kaaren|carem|carin|karon|karén|"
    r"jarvis|jarbis|yarbis|javis)\b",  # jarvis legacy por si el STT falla
    re.IGNORECASE,
)

_ENROLL_RE = re.compile(
    r"(memoriza|recuerda|guarda|aprende|graba)\s+(mi\s+)?voz"
    r"|\bvoz\s+(normal|cris|hacker)\b"
    r"|\benroll\b|\bperfil\s+(normal|cris)\b",
    re.I,
)


def _resolver_mic(preferido):
    """Elige mic real. Fifine directo > USB > default. Voicemod al final (casi mudo)."""
    try:
        devs = list(sd.query_devices())
    except Exception:
        return preferido

    # Si el usuario fijó un índice válido y no es Voicemod mudo, respetarlo
    if preferido is not None:
        try:
            d = devs[int(preferido)]
            if int(d.get("max_input_channels") or 0) > 0:
                name = (d.get("name") or "").lower()
                if "voicemod" not in name:
                    return int(preferido)
        except Exception:
            pass

    candidatos = []
    for i, d in enumerate(devs):
        if int(d.get("max_input_channels") or 0) <= 0:
            continue
        name = (d.get("name") or "").lower()
        score = 0
        # Priorizar mic físico; Voicemod suele llegar casi en silencio
        if "fifine" in name and "voicemod" not in name:
            score = 120
        elif "usb" in name and "audio" in name:
            score = 70
        elif "microphone" in name or "mic" in name:
            score = 50
        elif "voicewave" in name or "easeus" in name:
            score = 25
        elif "voicemod" in name:
            score = 10  # último recurso
        if preferido is not None and i == preferido:
            score += 30
        if score > 0:
            candidatos.append((score, -i, i, d.get("name") or f"#{i}"))

    if not candidatos:
        return preferido
    candidatos.sort(reverse=True)
    return candidatos[0][2]


class Oido:
    def __init__(self, bus, dispositivo=MIC_DEVICE, umbral=UMBRAL_HABLA):
        self.bus = bus
        self.dispositivo = _resolver_mic(dispositivo)
        self.umbral = float(umbral)
        self._umbral_base = float(umbral)
        self._modelo = None
        self._bloqueo_modelo = threading.Lock()
        self._running = False
        self._disponible = False
        self._ventana_activa_hasta = 0.0
        self._modo = "reposo"
        self._cooldown_hasta = 0.0
        self._mic_nombre = ""
        self._ruido_piso = 0.0
        self.voces = VozPrint()
        self.ultimo_perfil = self.voces.activo or "normal"
        self.ultimo_score = 0.0
        self._ultimo_audio = None
        self._modo_enroll = None  # "normal" | "cris" | None
        self._enroll_hasta = 0.0
        self._last_learn = 0.0
        self._test_dispositivos()
        self._publicar_voz()
        # Anti-eco: conocer cuándo KAREN habla (boca publica "hablando").
        self._karen_habla = False
        self._karen_hablo_hasta = 0.0
        # Duck-typing: no rompe si el bus no tiene suscribir().
        for nombre in ("suscribir", "subscribe", "on"):
            fn = getattr(bus, nombre, None)
            if callable(fn):
                try:
                    fn("hablando", self._al_hablar_karen)
                except Exception:
                    pass
                break

    def _al_hablar_karen(self, dato):
        """Evento 'hablando' de boca: True mientras reproduce su voz."""
        if isinstance(dato, dict):
            dato = dato.get("hablando", dato.get("valor", dato.get("estado")))
        self._karen_habla = bool(dato)
        if self._karen_habla:
            self._karen_hablo_hasta = 0.0
        else:
            # Pequeño margen tras su voz: evita captar la cola de su frase
            self._karen_hablo_hasta = time.time() + ECO_COOLDOWN

    def _publicar_voz(self):
        st = self.voces.estado_hud()
        st["perfil"] = self.ultimo_perfil
        self.bus.publicar("voz_perfil", st)

    def _test_dispositivos(self):
        try:
            entradas = sd.query_devices(kind="input")
            if entradas is None:
                self.bus.publicar("estado", "Sin micrófono detectado.")
                self.bus.publicar("mic_status", {"modo": "off", "msg": "Sin mic"})
                return
            try:
                info = sd.query_devices(self.dispositivo)
                self._mic_nombre = info.get("name") or f"#{self.dispositivo}"
            except Exception:
                self._mic_nombre = f"#{self.dispositivo}"
            self._disponible = True
            self._calibrar_ruido()
            self.bus.publicar("estado", f"Escuchando · {self._mic_nombre}")
            self.bus.publicar(
                "mic_status",
                {
                    "modo": "reposo",
                    "msg": "Escuchando",
                    "mic": self._mic_nombre,
                    "umbral": round(self.umbral, 4),
                },
            )
        except Exception as e:
            self.bus.publicar("estado", f"Micrófono no disponible: {e}")
            self.bus.publicar("mic_status", {"modo": "off", "msg": "Error mic"})

    def _calibrar_ruido(self):
        try:
            rec = sd.rec(
                int(FS * 0.7),
                samplerate=FS,
                channels=1,
                dtype="float32",
                device=self.dispositivo,
            )
            sd.wait()
            rms = float(np.sqrt(np.mean(np.square(rec))))
            self._ruido_piso = rms
            # Fifine en reposo ~0.0001 y habla ~0.003 → no forzar piso 0.008
            # Umbral suave: captura directa, sin filtrar de más
            auto = max(self._umbral_base * 0.85, rms * 1.8 + 0.0005)
            self.umbral = float(min(max(auto, 0.0012), 0.012))
            self.bus.publicar(
                "estado",
                f"Mic listo · ruido {rms:.4f} · umbral {self.umbral:.4f}",
            )
        except Exception as e:
            name = (self._mic_nombre or "").lower()
            if "voicemod" in name:
                self.umbral = max(self._umbral_base, 0.012)
            self.bus.publicar("estado", f"Calibración mic omitida: {e}")

    def disponible(self):
        return self._disponible

    def pedir_enroll(self, perfil: str, segundos=8.0):
        perfil = "cris" if perfil in ("cris", "hacker") else "normal"
        self._modo_enroll = perfil
        self._enroll_hasta = time.time() + segundos
        self.abrir_ventana(segundos + 2)
        self._set_status("activo", f"Graba voz {perfil}")
        return perfil

    def _cargar_modelo(self):
        with self._bloqueo_modelo:
            if self._modelo is None:
                self.bus.publicar("estado", "Procesando…")
                self.bus.publicar(
                    "mic_status", {"modo": "procesando", "msg": "Cargando oído…"}
                )
                from faster_whisper import WhisperModel

                self._modelo = WhisperModel(
                    MODELO_STT, device="cpu", compute_type="int8"
                )
                self.bus.publicar("estado", "Escuchando")
                self.bus.publicar(
                    "mic_status", {"modo": "reposo", "msg": "Escuchando"}
                )
        return self._modelo

    def _transcribir(self, audio, rapido=False):
        try:
            modelo = self._cargar_modelo()
            # vad_filter=False: audio crudo del mic (Fifine), sin recortar voz baja
            segmentos, _ = modelo.transcribe(
                audio,
                language="es",
                beam_size=1,
                best_of=1,
                temperature=0.0,
                condition_on_previous_text=False,
                without_timestamps=True,
                vad_filter=False,
                initial_prompt=(
                    "Karen, abre chrome, cierra whatsapp, busca en youtube, "
                    "qué hora es, cómo estás, memoriza mi voz."
                ),
            )
            # Filtro de confianza: descarta segmentos que faster-whisper
            # marca como "sin voz real" (ruido, eco, tv de fondo).
            keep = []
            for s in segmentos:
                prob = getattr(s, "no_speech_prob", 0.0) or 0.0
                logp = getattr(s, "avg_logprob", 0.0) or 0.0
                # no_speech_prob alto = sin voz; avg_logprob muy negativo =
                # el modelo "inventó" el texto (alucinación) sobre ruido.
                if prob < NO_SPEECH_MAX and logp >= AVG_LOGPROB_MIN:
                    keep.append(s.text)
            texto = " ".join(keep).strip()
            if self._es_alucinacion(texto):
                return ""
            return texto
        except Exception as e:
            self.bus.publicar("estado", f"Error STT: {e}")
            return ""

    def _rms(self, bloque):
        return float(
            np.sqrt(np.mean(np.square(bloque.astype(np.float32)))) / 32768.0
        )

    def _recortar_silencio(self, audio, umbral_sil):
        """Quita el silencio inicial/final. None si no queda voz útil (>=0.25s)."""
        if audio is None or len(audio) == 0:
            return None
        win = int(FS * 0.02)  # ventanas de 20ms
        niveles = [
            float(np.sqrt(np.mean(np.square(audio[i : i + win]))))
            for i in range(0, len(audio) - win + 1, win)
        ]
        arr = np.asarray(niveles)
        arriba = np.where(arr >= umbral_sil)[0]
        if arriba.size == 0:
            return None
        # Pequeño margen para no cortar el arranque de la primera palabra
        ini = max(0, int(arriba[0] * win) - int(FS * 0.08))
        fin = min(len(audio), int(arriba[-1] * win) + win + int(FS * 0.15))
        rec = audio[ini:fin]
        if len(rec) < FS * 0.25:
            return None
        return rec

    @staticmethod
    def _tiene_wake(texto: str) -> bool:
        if not texto:
            return False
        low = texto.lower()
        if PALABRA_ACTIVACION.lower() in low:
            return True
        # Prefijos Karen + residual Jarvis (STT), sin falsos positivos
        # comunes como "cariño" / "carino" / "carina"
        if re.search(r"\b(kar|car)[aei]n\w{0,3}\b", low) and not re.search(
            r"\bcari[nñ]o(?:s)?\b|\bcarin(?:a|os|as)\b", low
        ):
            return True
        if re.search(r"\b(jarv|jarb|yarv)[a-z]{0,6}\b", low):
            return True
        if any(
            p in low
            for p in (
                "oye karen",
                "hey karen",
                "ok karen",
                "hola karen",
                "oye jarvis",
                "hey jarvis",
            )
        ):
            return True
        return bool(_WAKE_RE.search(texto))

    @staticmethod
    def _quitar_wake(texto: str) -> str:
        t = texto.strip()
        t = _WAKE_RE.sub("", t, count=1)
        t = re.sub(
            r"\b(kar|car)[aei]n\w{0,3}\b",
            "",
            t,
            count=1,
            flags=re.I,
        )
        t = re.sub(
            r"\b(jarv|jarb|yarv)[a-z]{0,6}\b",
            "",
            t,
            count=1,
            flags=re.I,
        )
        t = re.sub(
            rf"\b{re.escape(PALABRA_ACTIVACION)}\b", "", t, count=1, flags=re.I
        )
        return t.strip(" .,;:¡!¿?\t\n\"'")

    # Frases típicas que faster-whisper alucina con ruido/tv de fondo:
    # cierres de video de YouTube, saludos genéricos y loops de una palabra.
    _ALUCINACIONES = (
        "gracias por mirar",
        "gracias por ver",
        "gracias por ver este video",
        "gracias por tu visita",
        "suscribete",
        "suscribirte",
        "no olvides suscribirte",
        "suscribete al canal",
        "dale like",
        "danos like",
        "deja tu like",
        "deja un like",
        "un like",
        "comparte el video",
        "comparte este video",
        "activa la campanita",
        "activa las notificaciones",
        "hasta la proxima",
        "nos vemos en el proximo video",
        "si te ha gustado el video",
        "deja un comentario",
        "bienvenidos a mi canal",
        "hola a todos",
        "que tal amigos",
    )

    @classmethod
    def _es_alucinacion(cls, texto: str) -> bool:
        """True si el STT inventó el texto: frases de cierre de video,
        saludos genéricos o una palabra repetida en bucle."""
        if not texto:
            return True
        low = " ".join(texto.lower().split())
        for frase in cls._ALUCINACIONES:
            if frase in low:
                return True
        # Misma palabra 4+ veces seguidas (bucle típico de alucinación)
        if re.search(r"\b(\w{2,})\b(?:\s+\1\b){3,}", low, re.I):
            return True
        # Solo muletillas/ruido corto sin comando útil (una o varias seguidas)
        if low and all(
            p in ("mm", "mmm", "mhm", "mh", "eh", "ah", "um", "a")
            for p in low.split()
        ):
            return True
        return False

    @staticmethod
    def detectar_enroll(texto: str):
        """Devuelve 'normal' | 'cris' | None según la frase."""
        if not texto:
            return None
        low = texto.lower()
        if not _ENROLL_RE.search(low) and "memoriza" not in low and "mi voz" not in low:
            return None
        if any(k in low for k in ("cris", "hacker", "hack", "modulad", "voicemod pitch")):
            return "cris"
        if "normal" in low or "real" in low or "natural" in low:
            return "normal"
        # "memoriza mi voz" sin adjetivo → normal por defecto
        if "voz" in low or "memoriza" in low or "graba" in low:
            return "normal"
        return None

    def _en_ventana_activa(self) -> bool:
        return time.time() < self._ventana_activa_hasta

    def abrir_ventana(self, segundos=None):
        segundos = segundos if segundos is not None else VENTANA_ACTIVA_S
        self._ventana_activa_hasta = time.time() + segundos
        self._modo = "activo"
        self.bus.publicar("estado", "Te escucho")
        self.bus.publicar("mic_status", {"modo": "activo", "msg": "Te escucho"})

    def cerrar_ventana(self):
        self._ventana_activa_hasta = 0.0
        self._modo = "reposo"
        self.bus.publicar("mic_status", {"modo": "reposo", "msg": "Escuchando"})

    def marcar_cooldown(self, segundos=None):
        segundos = COOLDOWN_TRAS_VOZ if segundos is None else segundos
        self._cooldown_hasta = time.time() + segundos

    def _set_status(self, modo, msg):
        self.bus.publicar("estado", msg)
        self.bus.publicar("mic_status", {"modo": modo, "msg": msg})

    def _aplicar_match(self, audio):
        m = self.voces.match(audio, sr=FS)
        self.ultimo_score = m.get("score") or 0.0
        if m.get("es_luis") and m.get("perfil"):
            self.ultimo_perfil = m["perfil"]
            # refuerzo ocasional
            if time.time() - self._last_learn > 12.0:
                try:
                    self.voces.aprender_si_luis(audio, perfil=self.ultimo_perfil, sr=FS)
                    self._last_learn = time.time()
                except Exception:
                    pass
        self._publicar_voz()
        return m

    # ------------------------------------------------------------------
    def _grabar_frase(self, timeout, silencio_fin):
        if self._running:
            return None
        if time.time() < self._cooldown_hasta:
            restante = self._cooldown_hasta - time.time()
            threading.Event().wait(min(restante, 0.35))
            if time.time() < self._cooldown_hasta:
                return None

        self._running = True
        resultado = {}
        anillo = deque(maxlen=max(1, int(PRE_ROLL / BLOQUE)))
        hablando = False
        tramo = []
        silencios = 0
        habla = 0
        bloques_voz = 0
        limite_bloques = int(timeout / BLOQUE)
        n = 0
        max_bloques_frase = int(MAX_FRASE / BLOQUE)
        silencio_bloques = max(4, int(silencio_fin / BLOQUE))
        # No cortar hasta ~0.95s de audio real (evita cortes mid-frase)
        min_bloques_antes_corte = int(0.95 / BLOQUE)
        # Voz real mínima: descarta clips disparados solo por un ruido breve
        min_bloques_voz = max(4, int(0.20 / BLOQUE))
        hangover = 0
        nivel_tick = [0]

        # Piso de ruido móvil: se aprende en los bloques de silencio real.
        # El bug "sigue grabando" venía de medir el silencio contra una fracción
        # fija del umbral de habla (0.38x ≈ 0.00065): el ruido ambiente normal
        # supera eso y el contador de silencio nunca llegaba a cortar.
        piso = [max(self._ruido_piso, 0.00005)]
        tranquilos = deque(maxlen=40)  # RMS de bloques sin voz (~2s)

        def umbral_silencio():
            """Punto medio entre el ruido real y el habla: ni corta frases
            en voz baja ni se queda grabando ruido ambiente."""
            p = piso[0]
            u = p * 2.2 + 0.00035
            return min(u, (p + self.umbral) * 0.5)

        def callback(indata, frames, time_info, status):
            nonlocal hablando, tramo, silencios, habla, bloques_voz, hangover
            nivel = self._rms(indata[:, 0])
            nivel_tick[0] += 1
            if nivel_tick[0] % 3 == 0:
                self.bus.publicar(
                    "nivel", {"v": round(min(nivel / 0.08, 1.0), 3)}
                )

            # Anti-eco: mientras KAREN habla nada entra al pre-roll. Si ya
            # veníamos grabando, aborta: su propia voz jamás se transcribe.
            if self._karen_habla or time.time() < self._karen_hablo_hasta:
                if hablando:
                    tramo.clear()
                    hablando = False
                    silencios = 0
                    habla = 0
                    bloques_voz = 0
                    hangover = 0
                    resultado["fin"] = True
                return

            anillo.append(indata[:, 0].copy())
            if not hablando:
                if nivel > self.umbral:
                    habla += 1
                    if habla >= MIN_HABLA_BLOQUES:
                        hablando = True
                        tramo = list(anillo)
                        silencios = 0
                        hangover = 6  # ~0.3s de gracia al empezar
                        bloques_voz = 1
                        # Semilla del piso con el pre-roll real de ESTA escucha
                        # (el ruido de ahora, no el de la grabación anterior).
                        # Solo si la mediana es ruido real, no voz ni silencio.
                        if len(anillo) >= 3:
                            med = float(
                                np.median([self._rms(b) for b in anillo])
                            )
                            if 1e-5 < med < self.umbral:
                                piso[0] = max(0.00005, piso[0] * 0.5 + med * 0.5)
                        self._set_status("activo", "Te oigo")
                else:
                    habla = max(0, habla - 1)
                    # Aprende el piso de ruido mientras no hay voz
                    tranquilos.append(nivel)
                    if len(tranquilos) >= 12 and nivel_tick[0] % 4 == 0:
                        mediana = float(np.median(tranquilos))
                        piso[0] = max(0.00005, piso[0] * 0.5 + mediana * 0.5)
                        tranquilos.clear()
            else:
                tramo.append(indata[:, 0].copy())
                # Voz real: bloques claramente por encima del umbral de habla
                if nivel > self.umbral * 0.7:
                    bloques_voz += 1
                # Aprende el piso tambien con bloques claramente no-voz.
                # Si el ruido sube durante o despues de hablar (ventilador,
                # aire acondicionado), el umbral dinamico lo sigue y corta.
                if nivel < self.umbral:
                    tranquilos.append(nivel)
                    if len(tranquilos) >= 12 and nivel_tick[0] % 4 == 0:
                        mediana = float(np.median(tranquilos))
                        piso[0] = max(0.00005, piso[0] * 0.5 + mediana * 0.5)
                        tranquilos.clear()
                # Silencio = por debajo del umbral dinámico (medido contra el ruido)
                if nivel > umbral_silencio():
                    silencios = 0
                    hangover = 6
                else:
                    if hangover > 0:
                        hangover -= 1
                    else:
                        silencios += 1
                    if (
                        silencios >= silencio_bloques
                        and len(tramo) >= min_bloques_antes_corte
                    ):
                        resultado["fin"] = True
                if len(tramo) >= max_bloques_frase:
                    resultado["fin"] = True

        try:
            with sd.InputStream(
                samplerate=FS,
                channels=1,
                dtype="int16",
                blocksize=int(FS * BLOQUE),
                device=self.dispositivo,
                callback=callback,
            ):
                while not resultado.get("fin", False) and n < limite_bloques:
                    n += 1
                    threading.Event().wait(BLOQUE * 0.9)
        except Exception as e:
            self.bus.publicar("estado", f"Error de micrófono: {e}")
            if self.dispositivo is not None:
                try:
                    self.dispositivo = None
                    self._mic_nombre = "default"
                except Exception:
                    pass
            self._running = False
            return None

        self._running = False
        self.bus.publicar("nivel", {"v": 0.0})
        # El piso aprendido sirve de arranque para la siguiente grabación
        self._ruido_piso = piso[0]

        if not hablando or not tramo:
            return None

        audio = np.concatenate(tramo).astype(np.float32) / 32768.0
        if len(audio) < FS * MIN_AUDIO_S:
            return None

        # Voz real mínima: descarta clips donde solo hubo un ruido breve
        if bloques_voz < min_bloques_voz:
            return None

        # Recorta silencio inicial/final: el STT alucina menos con audio limpio
        audio = self._recortar_silencio(audio, umbral_silencio())
        if audio is None:
            return None
        return audio

    # ------------------------------------------------------------------
    def escuchar(self, timeout=30.0):
        """Devuelve texto comando, o dict especial para enroll, o ''."""
        if not self._disponible:
            return ""

        # Anti-eco: esperar a que KAREN termine de hablar antes de grabar
        if self._karen_habla or time.time() < self._karen_hablo_hasta:
            espera_hasta = time.time() + 8.0
            while (
                (self._karen_habla or time.time() < self._karen_hablo_hasta)
                and time.time() < espera_hasta
            ):
                threading.Event().wait(0.15)
            if self._karen_habla or time.time() < self._karen_hablo_hasta:
                return ""

        activo = (not SOLO_POR_PALABRA) or self._en_ventana_activa()
        silencio = SILENCIO_FIN if activo else SILENCIO_FIN_WAKE
        to = timeout if activo else min(timeout, 14.0)

        if not activo and self._modo != "reposo":
            self._modo = "reposo"
            self._set_status("reposo", "Escuchando")

        audio = self._grabar_frase(timeout=to, silencio_fin=silencio)
        if audio is None:
            return ""

        # Gate de señal/ruido: si lo capturado es casi puro ruido, descartar.
        # Fifine: ruido ~0.0001 RMS, voz ~0.003 → ratio ~30x (umbral 2.2x).
        rms_audio = float(np.sqrt(np.mean(np.square(audio))))
        if rms_audio / max(self._ruido_piso, 1e-5) < SNR_MIN:
            return ""

        self._ultimo_audio = audio

        # Enroll explícito (después de "memoriza mi voz…")
        if self._modo_enroll and time.time() < self._enroll_hasta:
            perfil = self._modo_enroll
            self._modo_enroll = None
            self._set_status("procesando", f"Guardando voz {perfil}…")
            res = self.voces.enroll(perfil, audio, sr=FS)
            self.ultimo_perfil = perfil
            self._publicar_voz()
            self._set_status("reposo", "Escuchando")
            return {"_enroll": True, **res}

        self._set_status("procesando", "Procesando…")
        texto = self._transcribir(audio, rapido=not activo)
        if not texto:
            if activo and self._en_ventana_activa():
                self._set_status("activo", "Te escucho")
            else:
                self.cerrar_ventana()
                self._set_status("reposo", "Escuchando")
            return ""

        self.bus.publicar("oido", texto)

        # ¿Pide memorizar voz?
        enroll_p = self.detectar_enroll(texto)
        if enroll_p:
            # Si dice la frase y hay audio suficiente, graba YA
            res = self.voces.enroll(enroll_p, audio, sr=FS)
            self.ultimo_perfil = enroll_p
            self._publicar_voz()
            self.abrir_ventana(VENTANA_ACTIVA_S)
            return {"_enroll": True, **res}

        match = self._aplicar_match(audio)

        if not SOLO_POR_PALABRA:
            self.cerrar_ventana()
            return texto

        if self._en_ventana_activa():
            # Ya activo: no exigir wake; opcionalmente validar voz suave
            resto = self._quitar_wake(texto) if self._tiene_wake(texto) else texto
            if self._tiene_wake(texto) and not resto:
                self.abrir_ventana(VENTANA_ACTIVA_S)
                return ""
            self.abrir_ventana(VENTANA_ACTIVA_S)
            return resto if resto else texto

        # REPOSO: exige wake word
        if not self._tiene_wake(texto):
            self._set_status("reposo", "Escuchando")
            return ""

        # Wake detectado → verificar huella si hay perfiles
        if BLOQUEAR_DESCONOCIDOS and self.voces.listo():
            if not match.get("es_luis"):
                self._set_status("reposo", "Escuchando")
                self.bus.publicar("estado", "Voz no reconocida")
                self.bus.publicar(
                    "mic_status", {"modo": "reposo", "msg": "Voz desconocida"}
                )
                return ""

        resto = self._quitar_wake(texto)
        if not resto:
            self.abrir_ventana(VENTANA_ACTIVA_S)
            return ""

        self.abrir_ventana(VENTANA_ACTIVA_S)
        return resto
