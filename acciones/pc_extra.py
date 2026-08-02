# acciones/pc_extra.py
# Comandos de PC extendidos (portados del repo mod + funciones típicas de JARVIS):
# volumen (pycaw con fallback de teclas multimedia), brillo (WMI vía PowerShell),
# energía (bloquear/suspender/hibernar/apagar/reiniciar), media keys y
# recordatorios/temporizador (delegados a acciones/recordatorios.py).
from __future__ import annotations

import ctypes
import re
import subprocess
import time

from acciones.recordatorios import _comando_recordatorio, gestor

_ACENTOS = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")


def _norm(t):
    return (t or "").lower().translate(_ACENTOS).strip()


# ---------- Volumen ----------

_VK_VOLUME_UP = 0xAF
_VK_VOLUME_DOWN = 0xAE
_VK_VOLUME_MUTE = 0xAD


def _tecla_virtual(vk, repeticiones=1):
    """Envía una tecla virtual (VK_*) con keybd_event. Funciona en todas las apps."""
    try:
        user32 = ctypes.windll.user32
        for _ in range(max(1, repeticiones)):
            user32.keybd_event(vk, 0, 0, 0)
            time.sleep(0.04)
            user32.keybd_event(vk, 0, 0x0002, 0)
            time.sleep(0.04)
        return True
    except Exception:
        return False


def _endpoint_volumen():
    """Devuelve la interfaz IAudioEndpointVolume del dispositivo de salida (pycaw)."""
    try:
        import comtypes
        try:
            comtypes.CoInitialize()
        except Exception:
            pass
        from pycaw.pycaw import AudioUtilities

        dev = AudioUtilities.GetSpeakers()
        if dev is None:
            return None
        return dev.EndpointVolume
    except Exception:
        return None


def _volumen_actual():
    ep = _endpoint_volumen()
    if ep is None:
        return None
    try:
        return round(ep.GetMasterVolumeLevelScalar() * 100)
    except Exception:
        return None


def fijar_volumen(pct):
    """Fija el volumen maestro a un porcentaje. Devuelve el % resultante o None."""
    pct = max(0, min(100, int(pct)))
    ep = _endpoint_volumen()
    if ep is not None:
        try:
            ep.SetMasterVolumeLevelScalar(pct / 100.0, None)
            return pct
        except Exception:
            pass
    _tecla_virtual(_VK_VOLUME_MUTE)  # fallback: teclas multimedia (aproximado)
    _tecla_virtual(_VK_VOLUME_DOWN, 100)
    return None


def cambiar_volumen(delta):
    """Sube/baja el volumen actual en `delta` puntos. Devuelve el % o None."""
    actual = _volumen_actual()
    if actual is not None:
        return fijar_volumen(actual + delta)
    vk = _VK_VOLUME_UP if delta > 0 else _VK_VOLUME_DOWN
    _tecla_virtual(vk, min(max(abs(delta) // 2, 1), 20))
    return None


def volumen_mute(mute):
    ep = _endpoint_volumen()
    if ep is not None:
        try:
            ep.SetMute(1 if mute else 0, None)
            return True
        except Exception:
            pass
    return _tecla_virtual(_VK_VOLUME_MUTE)


# ---------- Brillo ----------

def _powershell(comando):
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", comando],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


def brillo_actual():
    """% de brillo del monitor, o None si el equipo no permite ajustarlo."""
    out = _powershell(
        "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness"
    )
    try:
        v = int(out.splitlines()[0].strip())
        return v if 0 <= v <= 100 else None
    except Exception:
        return None


def fijar_brillo(pct):
    pct = max(0, min(100, int(pct)))
    out = _powershell(
        "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods)"
        f".WmiSetBrightness(1,{pct})"
    )
    return not out.strip()


# ---------- Energía ----------

def bloquear_pc():
    try:
        ctypes.windll.user32.LockWorkStation()
        return True
    except Exception:
        return False


def suspender_pc():
    try:
        ctypes.windll.powrprof.SetSuspendState(False, True, False)
        return True
    except Exception:
        return False


def hibernar_pc():
    try:
        ctypes.windll.powrprof.SetSuspendState(True, True, False)
        return True
    except Exception:
        return False


def apagar_pc(delay_s=20):
    try:
        subprocess.Popen(f"shutdown /s /t {int(delay_s)}", shell=True)
        return True
    except Exception:
        return False


def reiniciar_pc(delay_s=10):
    try:
        subprocess.Popen(f"shutdown /r /t {int(delay_s)}", shell=True)
        return True
    except Exception:
        return False


# ---------- Media keys ----------

_VK_MEDIA_PLAY_PAUSE = 0xB3
_VK_MEDIA_NEXT_TRACK = 0xB0
_VK_MEDIA_PREV_TRACK = 0xB1


def media_play_pause():
    return _tecla_virtual(_VK_MEDIA_PLAY_PAUSE)


def media_next():
    return _tecla_virtual(_VK_MEDIA_NEXT_TRACK)


def media_prev():
    return _tecla_virtual(_VK_MEDIA_PREV_TRACK)


# ---------- Parser ----------

def parsear_pc_extra(texto):
    """Reconoce comandos extendidos. Devuelve dict con 'tipo' o None."""
    t = _norm(texto)
    if not t:
        return None

    # --- Recordatorios / temporizador ---
    r = _comando_recordatorio(t)
    if r:
        return r

    # --- Volumen: fijar a un valor ---
    m = re.search(
        r"(?:pon|poner|ponme|deja|ajusta|configura|sube|baja)\s+el\s+volumen\s+(?:al|en|a|para)\s+(\d{1,3})",
        t,
    )
    if not m:
        m = re.search(r"volumen\s+(?:al|en|a|para)\s+(\d{1,3})", t)
    if m:
        return {"tipo": "volumen", "pct": int(m.group(1))}

    # --- Volumen: subir / bajar (con o sin monto) ---
    m = re.search(
        r"(?:sube|subir|aumenta|aumentar|alza)\s+(?:el\s+|un poco el\s+)?volumen(?:\s+a\s+(\d{1,3}))?",
        t,
    )
    if m:
        return {"tipo": "volumen_delta", "delta": int(m.group(1)) if m.group(1) else 10}
    m = re.search(
        r"(?:baja|bajar|disminuye|disminuir|reduce|reducir)\s+(?:el\s+|un poco el\s+)?volumen(?:\s+a\s+(\d{1,3}))?",
        t,
    )
    if m:
        return {"tipo": "volumen_delta", "delta": -int(m.group(1)) if m.group(1) else -10}
    if "volumen" in t and any(k in t for k in ("arriba", "más", "mas", "todo lo alto")):
        return {"tipo": "volumen_delta", "delta": 10}
    if "volumen" in t and any(k in t for k in ("abajo", "menos")):
        return {"tipo": "volumen_delta", "delta": -10}

    # --- Volumen: silenciar / reactivar sonido ---
    if any(k in t for k in (
        "silencia", "silencio", "silenciar", "mutea", "pon en silencio",
        "apaga el sonido", "quita el sonido",
    )):
        return {"tipo": "volumen_mute", "mute": True}
    if any(k in t for k in (
        "activa el sonido", "quita el silencio", "desilencia",
        "reactiva el sonido", "deja de estar en silencio", "deja de estar mudo",
    )):
        return {"tipo": "volumen_mute", "mute": False}

    # --- Brillo ---
    m = re.search(
        r"(?:pon|poner|ponme|deja|ajusta|configura|sube|baja)\s+el\s+brillo\s+(?:al|en|a|para)\s+(\d{1,3})",
        t,
    )
    if not m:
        m = re.search(r"brillo\s+(?:al|en|a|para)\s+(\d{1,3})", t)
    if m:
        return {"tipo": "brillo", "pct": int(m.group(1))}
    m = re.search(
        r"(?:sube|subir|aumenta|aumentar|alza)\s+(?:el\s+|un poco el\s+)?brillo(?:\s+a\s+(\d{1,3}))?",
        t,
    )
    if m:
        return {"tipo": "brillo_delta", "delta": int(m.group(1)) if m.group(1) else 10}
    m = re.search(
        r"(?:baja|bajar|disminuye|disminuir|reduce|reducir)\s+(?:el\s+|un poco el\s+)?brillo(?:\s+a\s+(\d{1,3}))?",
        t,
    )
    if m:
        return {"tipo": "brillo_delta", "delta": -int(m.group(1)) if m.group(1) else -10}
    if "brillo" in t and "arriba" in t:
        return {"tipo": "brillo_delta", "delta": 10}
    if "brillo" in t and "abajo" in t:
        return {"tipo": "brillo_delta", "delta": -10}

    # --- Energía ---
    if any(k in t for k in (
        "bloquea el pc", "bloquea la pc", "bloquea el equipo", "bloquea el ordenador",
        "bloquea la pantalla", "bloquear el pc", "cierra la sesion", "cierra sesion",
    )):
        return {"tipo": "bloquear"}
    if any(k in t for k in (
        "suspende el pc", "suspende la pc", "suspende el equipo", "suspende el ordenador",
        "pon en suspension", "duerme el pc", "modo suspension", "a dormir el pc",
    )):
        return {"tipo": "suspender"}
    if any(k in t for k in (
        "hiberna el pc", "hiberna la pc", "hiberna el equipo",
        "pon a hibernar", "modo hibernacion",
    )):
        return {"tipo": "hibernar"}
    if any(k in t for k in (
        "reinicia el pc", "reinicia la pc", "reinicia el equipo", "reinicia el ordenador",
        "reiniciar el pc", "reiniciar la pc", "reiniciar el equipo",
    )):
        return {"tipo": "reiniciar"}
    if any(k in t for k in (
        "apaga el pc", "apaga la pc", "apaga el equipo", "apaga el ordenador", "apaga mi pc",
    )):
        return {"tipo": "apagar"}

    # --- Media keys ---
    if any(k in t for k in (
        "pausa la musica", "pausa la cancion", "pausar la musica", "pausa el video",
        "pausa la reproduccion", "pon pausa", "para la musica", "deten la musica",
        "para la cancion",
    )):
        return {"tipo": "media", "tecla": "play_pause"}
    if any(k in t for k in (
        "reanuda la musica", "reanuda la cancion", "continua la musica", "sigue la musica",
        "pon play", "dale play", "reproduce la musica", "sigue la cancion",
    )):
        return {"tipo": "media", "tecla": "play_pause"}
    if any(k in t for k in (
        "siguiente cancion", "siguiente tema", "siguiente pista", "siguiente video",
        "pasa la cancion", "cambia de cancion",
    )):
        return {"tipo": "media", "tecla": "next"}
    if any(k in t for k in (
        "cancion anterior", "tema anterior", "pista anterior", "anterior cancion",
        "regresa la cancion", "volver a la cancion anterior",
    )):
        return {"tipo": "media", "tecla": "prev"}

    return None


# ---------- Ejecución ----------

def ejecutar_pc_extra(cmd, bus=None):
    """Ejecuta un dict de parsear_pc_extra y devuelve la respuesta hablable (o None)."""
    from acciones.recordatorios import _formatear_duracion

    tipo = cmd.get("tipo")

    if tipo == "volumen":
        r = fijar_volumen(cmd.get("pct", 50))
        if r is not None:
            return f"Listo, volumen al {r} por ciento."
        return "No pude ajustar el volumen de este equipo."
    if tipo == "volumen_delta":
        r = cambiar_volumen(cmd.get("delta", 10))
        if r is not None:
            return f"Volumen al {r} por ciento."
        return "Listo."
    if tipo == "volumen_mute":
        ok = volumen_mute(cmd.get("mute", True))
        if cmd.get("mute"):
            return "Silencio activado." if ok else "No pude silenciar el equipo."
        return "Sonido activado." if ok else "No pude reactivar el sonido."

    if tipo == "brillo":
        if brillo_actual() is None:
            return "Este equipo no tiene monitor ajustable, así que no puedo tocar el brillo."
        if not fijar_brillo(cmd.get("pct", 50)):
            return "No pude ajustar el brillo."
        return f"Brillo al {cmd.get('pct', 50)} por ciento."
    if tipo == "brillo_delta":
        actual = brillo_actual()
        if actual is None:
            return "Este equipo no tiene monitor ajustable, así que no puedo tocar el brillo."
        nuevo = max(0, min(100, actual + cmd.get("delta", 0)))
        if not fijar_brillo(nuevo):
            return "No pude ajustar el brillo."
        return f"Brillo al {nuevo} por ciento."

    if tipo == "bloquear":
        return "Bloqueo el equipo. Nos vemos en un momento." if bloquear_pc() else "No pude bloquear el equipo."
    if tipo == "suspender":
        return "Vale, pongo el equipo a dormir." if suspender_pc() else "No pude suspender el equipo."
    if tipo == "hibernar":
        return "Vale, hiberno el equipo." if hibernar_pc() else "No pude hibernar el equipo."
    if tipo == "apagar":
        if not apagar_pc(20):
            return "No pude programar el apagado."
        if bus is not None:
            try:
                bus.publicar("estado", "Apagando el PC en 20 segundos…")
            except Exception:
                pass
        return "Vale, apago el equipo en veinte segundos. Que descanses."
    if tipo == "reiniciar":
        if not reiniciar_pc(10):
            return "No pude programar el reinicio."
        if bus is not None:
            try:
                bus.publicar("estado", "Reiniciando el PC en 10 segundos…")
            except Exception:
                pass
        return "Vale, reinicio el equipo en diez segundos."

    if tipo == "media":
        tecla = cmd.get("tecla")
        if tecla == "next":
            return "Siguiente canción." if media_next() else "No pude cambiar la canción."
        if tecla == "prev":
            return "Canción anterior." if media_prev() else "No pude volver a la canción anterior."
        return "Claro." if media_play_pause() else "No pude controlar la reproducción."

    if tipo == "recordatorio":
        seg = cmd.get("segundos", 60)
        texto = cmd.get("texto", "el recordatorio")
        if gestor.bus is None:
            gestor.bus = bus
        gestor.programar(texto, seg)
        if texto == "el temporizador":
            return f"Temporizador de {_formatear_duracion(seg)} activado. Te aviso cuando termine."
        return f"Vale, te recuerdo {texto} en {_formatear_duracion(seg)}."
    if tipo == "recordatorio_listar":
        items = gestor.listar()
        if not items:
            return "No tienes recordatorios pendientes."
        partes = [f"{t} en {_formatear_duracion(s)}" for t, s in items]
        return "Tienes " + "; ".join(partes) + "."
    if tipo == "recordatorio_cancelar":
        n = gestor.cancelar_todos()
        if n:
            return f"Listo, cancelo tus {n} recordatorios."
        return "No había recordatorios que cancelar."

    return None
