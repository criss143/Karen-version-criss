# -*- coding: utf-8 -*-
"""audio_sistema.py — El "oído musical" de KAREN.

Captura en tiempo real el sonido que SUENA en la PC (no el micrófono):
música, videos, YouTube… usando WASAPI loopback vía sounddevice (ya instalado,
sin dependencias nuevas). Calcula el nivel (envolvente) y lo publica al HUD
por el bus como {"tipo": "audio_pc", "datos": {...}} para animar el
visualizador de la derecha.

Solo Windows tiene WASAPI loopback; en otros sistemas degrada silencioso.
"""
import threading
import time

import numpy as np

try:
    import sounddevice as sd
    _SD_OK = True
except Exception:
    _SD_OK = False


class AudioSistema:
    def __init__(self, bus=None, fps=15):
        self.bus = bus
        self.fps = max(6, min(30, fps))
        self._stream = None
        self._thread = None
        self._corriendo = threading.Event()
        self._nivel = 0.0          # 0..1 suavizado
        self._bandas = [0.0] * 12  # espectro simple para el visualizador
        self._activo = False       # ¿está sonando algo ahora?

    # ---------------- API pública ----------------

    @property
    def nivel(self) -> float:
        return self._nivel

    @property
    def bandas(self):
        return list(self._bandas)

    @property
    def sonando(self) -> bool:
        return self._activo

    def iniciar(self):
        """Arranca la captura en un hilo. Silencioso si no hay soporte."""
        if not _SD_OK or self._corriendo.is_set():
            return False
        disp = self._buscar_loopback()
        if disp is None:
            self._publicar_estado_no_disponible()
            return False
        self._corriendo.set()
        self._thread = threading.Thread(
            target=self._bucle, args=(disp,), daemon=True, name="audio-pc"
        )
        self._thread.start()
        return True

    def detener(self):
        self._corriendo.clear()
        try:
            if self._stream:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
        self._stream = None

    # ---------------- Interno ----------------

    def _buscar_loopback(self):
        """Encuentra un dispositivo WASAPI en modo loopback (salida capturable).

        En Windows, sounddevice+PortAudio exponen los dispositivos de salida
        como capturables con WasapiSettings(loopback=True). Elegimos la salida
        por defecto.
        """
        try:
            hostapis = sd.query_hostapis()
            wasapi_idx = None
            for i, ha in enumerate(hostapis):
                if "wasapi" in ha["name"].lower():
                    wasapi_idx = i
                    break
            if wasapi_idx is None:
                return None
            # Dispositivo de salida por defecto de WASAPI
            default_out = hostapis[wasapi_idx].get("default_output_device", -1)
            if default_out is None or default_out < 0:
                # Buscar la primera salida WASAPI con canales de salida
                for idx, dev in enumerate(sd.query_devices()):
                    if dev["hostapi"] == wasapi_idx and dev["max_output_channels"] > 0:
                        default_out = idx
                        break
            if default_out is None or default_out < 0:
                return None
            return default_out
        except Exception:
            return None

    def _bucle(self, disp):
        try:
            info = sd.query_devices(disp)
            sr = int(info.get("default_samplerate") or 48000)
            canales = min(2, int(info.get("max_output_channels") or 2)) or 2
            settings = None
            try:
                settings = sd.WasapiSettings(loopback=True)
            except Exception:
                settings = None

            block = int(sr / self.fps)

            def callback(indata, frames, time_info, status):
                if not self._corriendo.is_set():
                    raise sd.CallbackStop()
                self._procesar(indata, sr)

            self._stream = sd.InputStream(
                device=disp,
                channels=canales,
                samplerate=sr,
                blocksize=block,
                dtype="float32",
                callback=callback,
                extra_settings=settings,
            )
            with self._stream:
                while self._corriendo.is_set():
                    time.sleep(0.05)
        except Exception as e:
            self._publicar("estado", f"Audio PC: no pude capturar el sonido ({e}).")
            self._corriendo.clear()

    def _procesar(self, indata, sr):
        # Mezcla a mono
        x = indata.mean(axis=1) if indata.ndim > 1 else indata.ravel()
        if x.size == 0:
            return

        # Nivel RMS → escala perceptual (0..1)
        rms = float(np.sqrt(np.mean(x * x)) + 1e-9)
        # Compresión logarítmica: la música vive en un rango amplio
        nivel = min(1.0, max(0.0, (np.log10(rms + 1e-6) + 3.2) / 3.0))
        # Suavizado: ataque rápido, caída lenta (se ve natural)
        if nivel > self._nivel:
            self._nivel += (nivel - self._nivel) * 0.6
        else:
            self._nivel += (nivel - self._nivel) * 0.18
        self._activo = self._nivel > 0.04

        # Espectro simple con FFT → 12 bandas para las barras del visualizador
        try:
            n = min(2048, x.size)
            win = x[:n] * np.hanning(n)
            mag = np.abs(np.fft.rfft(win))
            # Agrupar en 12 bandas logarítmicas
            bordes = np.logspace(np.log10(2), np.log10(len(mag) - 1), 13).astype(int)
            bandas = []
            for i in range(12):
                a, b = bordes[i], max(bordes[i] + 1, bordes[i + 1])
                seg = mag[a:b]
                v = float(np.mean(seg)) if seg.size else 0.0
                bandas.append(v)
            m = max(bandas) or 1.0
            bandas = [min(1.0, (b / m) ** 0.6) for b in bandas]
            # Suavizado por banda
            self._bandas = [
                self._bandas[i] * 0.5 + bandas[i] * 0.5 for i in range(12)
            ]
        except Exception:
            pass

        self._publicar_nivel()

    _ult_envio = 0.0

    def _publicar_nivel(self):
        ahora = time.time()
        if ahora - self._ult_envio < (1.0 / self.fps):
            return
        self._ult_envio = ahora
        self._publicar("audio_pc", {
            "nivel": round(self._nivel, 3),
            "sonando": self._activo,
            "bandas": [round(b, 3) for b in self._bandas],
        })

    def _publicar(self, canal, dato):
        if self.bus is None:
            return
        try:
            self.bus.publicar(canal, dato)
        except Exception:
            pass

    def _publicar_estado_no_disponible(self):
        self._publicar("estado", "Audio PC: sin WASAPI loopback en este equipo.")
