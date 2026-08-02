# Huella de voz local (numpy puro): memoriza Luis normal + Cris (Voicemod)
# y las reconoce al oír "Jarvis". No es biometría bancaria; sirve para
# personalidades y no dejar pasar a terceros.
from __future__ import annotations

import json
import os
import threading
import time
from typing import Optional

import numpy as np

from config import BASE

RUTA = os.path.join(BASE, "voces_perfil.json")
FS = 16000
N_FFT = 512
HOP = 160
N_MELS = 24
N_FEAT = 48  # mel mean+std + extras
MIN_SAMPLES = int(FS * 0.45)
MAX_SAMPLES_PER_PROFILE = 12
MATCH_UMBRAL = 0.62  # cosine similarity mínima
MATCH_MARGEN = 0.04  # diferencia vs 2º mejor


def _hz_to_mel(hz):
    return 2595.0 * np.log10(1.0 + np.asarray(hz) / 700.0)


def _mel_to_hz(mel):
    return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)


def _mel_filterbank(n_fft, n_mels, sr):
    f_max = sr / 2.0
    mels = np.linspace(_hz_to_mel(0), _hz_to_mel(f_max), n_mels + 2)
    hz = _mel_to_hz(mels)
    bins = np.floor((n_fft + 1) * hz / sr).astype(int)
    bins = np.clip(bins, 0, n_fft // 2)
    fb = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float64)
    for i in range(n_mels):
        left, center, right = bins[i], bins[i + 1], bins[i + 2]
        if center == left:
            center += 1
        if right == center:
            right += 1
        for j in range(left, center):
            if center != left:
                fb[i, j] = (j - left) / (center - left)
        for j in range(center, right):
            if right != center:
                fb[i, j] = (right - j) / (right - center)
    return fb


_FB = _mel_filterbank(N_FFT, N_MELS, FS)


def _preemphasis(x, coef=0.97):
    y = np.empty_like(x)
    y[0] = x[0]
    y[1:] = x[1:] - coef * x[:-1]
    return y


def extraer_embedding(audio: np.ndarray, sr: int = FS) -> Optional[np.ndarray]:
    """Vector de huella a partir de audio mono float32 [-1,1]."""
    if audio is None:
        return None
    x = np.asarray(audio, dtype=np.float64).reshape(-1)
    if sr != FS and sr > 0:
        # resample lineal simple
        n = int(len(x) * FS / sr)
        if n < 8:
            return None
        t_old = np.linspace(0, 1, len(x), endpoint=False)
        t_new = np.linspace(0, 1, n, endpoint=False)
        x = np.interp(t_new, t_old, x)
    if len(x) < MIN_SAMPLES:
        return None
    # normalizar energía
    rms = float(np.sqrt(np.mean(x * x)) + 1e-9)
    x = x / rms
    x = _preemphasis(x)

    # frames
    if len(x) < N_FFT:
        return None
    n_frames = 1 + (len(x) - N_FFT) // HOP
    if n_frames < 3:
        return None
    window = np.hanning(N_FFT)
    mels = []
    zcr = []
    for i in range(n_frames):
        start = i * HOP
        frame = x[start : start + N_FFT] * window
        spec = np.abs(np.fft.rfft(frame)) ** 2
        mel = np.dot(_FB, spec)
        mel = np.log(mel + 1e-8)
        mels.append(mel)
        # zero crossing rate del frame
        s = np.sign(frame)
        s[s == 0] = 1
        zcr.append(float(np.mean(np.abs(np.diff(s)) > 0)))
    M = np.stack(mels, axis=0)  # (T, n_mels)
    mean = M.mean(axis=0)
    std = M.std(axis=0) + 1e-6
    # centroides / bandas gruesas (timbre Voicemod cambia mucho)
    bands = [
        mean[:6].mean(),
        mean[6:12].mean(),
        mean[12:18].mean(),
        mean[18:].mean() if mean.shape[0] > 18 else 0.0,
    ]
    extras = np.array(
        [
            float(np.mean(zcr)),
            float(np.std(zcr) + 1e-6),
            float(rms),
            float(np.percentile(np.abs(x), 90)),
            *bands,
        ],
        dtype=np.float64,
    )
    vec = np.concatenate([mean, std, extras])
    # pad/truncate a N_FEAT
    if len(vec) < N_FEAT:
        vec = np.pad(vec, (0, N_FEAT - len(vec)))
    else:
        vec = vec[:N_FEAT]
    nrm = float(np.linalg.norm(vec) + 1e-9)
    return (vec / nrm).astype(np.float32)


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


class VozPrint:
    """Memoriza y reconoce perfiles de voz (normal, cris, ...)."""

    def __init__(self, ruta=RUTA):
        self.ruta = ruta
        self._lock = threading.Lock()
        self.perfiles = {}  # nombre -> {"centroid": list, "samples": [list], "n": int}
        self.activo = "normal"
        self._ultimo_score = 0.0
        self._cargar()

    def _cargar(self):
        try:
            with open(self.ruta, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.perfiles = data.get("perfiles") or {}
            self.activo = data.get("activo") or "normal"
        except Exception:
            self.perfiles = {}
            self.activo = "normal"

    def guardar(self):
        with self._lock:
            payload = {
                "perfiles": self.perfiles,
                "activo": self.activo,
                "updated": time.time(),
            }
            tmp = self.ruta + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.ruta)

    def nombres(self):
        return list(self.perfiles.keys())

    def listo(self) -> bool:
        return any(
            (p.get("n") or 0) >= 1 or p.get("centroid") for p in self.perfiles.values()
        )

    def _recalc(self, nombre: str):
        p = self.perfiles.get(nombre)
        if not p:
            return
        samples = p.get("samples") or []
        if not samples:
            p["centroid"] = None
            p["n"] = 0
            return
        mat = np.stack([np.asarray(s, dtype=np.float32) for s in samples], axis=0)
        c = mat.mean(axis=0)
        c = c / (np.linalg.norm(c) + 1e-9)
        p["centroid"] = c.astype(np.float32).tolist()
        p["n"] = len(samples)

    def enroll(self, nombre: str, audio: np.ndarray, sr: int = FS) -> dict:
        """Añade una muestra al perfil (normal / cris)."""
        nombre = (nombre or "normal").strip().lower()
        emb = extraer_embedding(audio, sr=sr)
        if emb is None:
            return {"ok": False, "msg": "Audio muy corto para memorizar"}
        with self._lock:
            p = self.perfiles.setdefault(
                nombre, {"centroid": None, "samples": [], "n": 0}
            )
            samples = p.setdefault("samples", [])
            samples.append(emb.tolist())
            if len(samples) > MAX_SAMPLES_PER_PROFILE:
                del samples[0 : len(samples) - MAX_SAMPLES_PER_PROFILE]
            self._recalc(nombre)
            self.activo = nombre
        self.guardar()
        n = self.perfiles[nombre]["n"]
        return {
            "ok": True,
            "perfil": nombre,
            "muestras": n,
            "msg": f"Voz «{nombre}» guardada ({n} muestra{'s' if n != 1 else ''})",
        }

    def match(self, audio: np.ndarray, sr: int = FS) -> dict:
        """Devuelve mejor perfil y si es Luis (alguna de sus voces)."""
        emb = extraer_embedding(audio, sr=sr)
        if emb is None:
            return {
                "ok": False,
                "perfil": None,
                "score": 0.0,
                "es_luis": False,
                "msg": "sin audio",
            }
        if not self.listo():
            # Sin perfiles aún: acepta a cualquiera y no bloquea
            return {
                "ok": True,
                "perfil": self.activo or "normal",
                "score": 1.0,
                "es_luis": True,
                "msg": "sin perfiles (modo abierto)",
                "emb": emb,
            }

        scores = {}
        with self._lock:
            for nombre, p in self.perfiles.items():
                c = p.get("centroid")
                if not c:
                    continue
                scores[nombre] = _cos(emb, np.asarray(c, dtype=np.float32))

        if not scores:
            return {
                "ok": True,
                "perfil": "normal",
                "score": 1.0,
                "es_luis": True,
                "msg": "sin centroid",
                "emb": emb,
            }

        orden = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_name, best_score = orden[0]
        second = orden[1][1] if len(orden) > 1 else 0.0
        self._ultimo_score = best_score

        es_luis = best_score >= MATCH_UMBRAL and (
            best_score - second >= MATCH_MARGEN or len(orden) == 1
        )
        # Si hay varios perfiles de Luis, cualquiera por encima del umbral cuenta
        if not es_luis:
            es_luis = any(s >= MATCH_UMBRAL for s in scores.values())
            if es_luis:
                best_name, best_score = max(scores.items(), key=lambda kv: kv[1])

        if es_luis:
            self.activo = best_name

        return {
            "ok": True,
            "perfil": best_name if es_luis else None,
            "score": round(float(best_score), 3),
            "es_luis": bool(es_luis),
            "scores": {k: round(float(v), 3) for k, v in scores.items()},
            "msg": (
                f"voz {best_name} ({best_score:.2f})"
                if es_luis
                else f"voz desconocida ({best_score:.2f})"
            ),
            "emb": emb,
        }

    def aprender_si_luis(self, audio, perfil: Optional[str] = None, sr: int = FS):
        """Refuerzo suave: si ya es Luis, añade muestra al perfil activo."""
        nombre = (perfil or self.activo or "normal").lower()
        if nombre not in self.perfiles and self.listo():
            # solo refuerza perfiles existentes
            return
        if not self.listo():
            return
        # throttling: max 1 cada ~8 s se hace en oido
        return self.enroll(nombre, audio, sr=sr)

    def estado_hud(self) -> dict:
        return {
            "activo": self.activo,
            "perfiles": {
                k: {"muestras": v.get("n") or 0} for k, v in self.perfiles.items()
            },
            "listo": self.listo(),
            "score": self._ultimo_score,
        }
