# Lanzador real de apps + YouTube + URLs (Windows)
from __future__ import annotations

import glob
import os
import re
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

from acciones.pc_extra import ejecutar_pc_extra, parsear_pc_extra
from acciones.recordatorios import gestor

# Alias voz → clave canónica
_ALIAS = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "google": "chrome",
    "navegador": "chrome",
    "edge": "edge",
    "microsoft edge": "edge",
    "opera": "opera",
    "opera gx": "opera",
    "firefox": "firefox",
    "code": "vscode",
    "vs code": "vscode",
    "vscode": "vscode",
    "vs": "vscode",
    "vsc": "vscode",
    "visual studio code": "vscode",
    "visual studio": "vscode",
    "visual": "vscode",
    "codigo": "vscode",
    "editor": "vscode",
    "notepad": "notepad",
    "bloc de notas": "notepad",
    "notas": "notepad",
    "bloc": "notepad",
    "calculadora": "calc",
    "calc": "calc",
    "explorador": "explorer",
    "archivos": "explorer",
    "explorer": "explorer",
    "discord": "discord",
    "spotify": "spotify",
    "steam": "steam",
    "obs": "obs",
    "obs studio": "obs",
    "paint": "paint",
    "cmd": "cmd",
    "terminal": "cmd",
    "consola": "cmd",
    "simbolo del sistema": "cmd",
    "powershell": "powershell",
    "power shell": "powershell",
    "word": "word",
    "excel": "excel",
    "powerpoint": "powerpoint",
    "bluestacks": "bluestacks",
    "fivem": "fivem",
    "roblox": "roblox",
    "ollama": "ollama",
    "hackerai": "hackerai",
    "tiktok": "tiktok",
    "tiktok live": "tiktok",
    "voicemod": "voicemod",
    "winrar": "winrar",
    "xampp": "xampp",
    "youtube": "youtube",
    "youtu": "youtube",
    "yt": "youtube",
    "whatsapp": "whatsapp",
    "wasap": "whatsapp",
    "watsap": "whatsapp",
    "wasa": "whatsapp",
    "whats app": "whatsapp",
    "ajustes": "settings",
    "configuracion": "settings",
    "config": "settings",
}

# Procesos a matar al cerrar (clave canónica → nombres de proceso sin .exe)
_PROC = {
    "chrome": ["chrome"],
    "edge": ["msedge"],
    "opera": ["opera"],
    "firefox": ["firefox"],
    "vscode": ["Code"],
    "notepad": ["notepad"],
    "calc": ["CalculatorApp", "Calculator", "calc"],
    "discord": ["Discord"],
    "spotify": ["Spotify"],
    "steam": ["steam", "steamwebhelper"],
    "obs": ["obs64", "obs32", "obs"],
    "paint": ["mspaint"],
    "cmd": ["cmd"],
    "powershell": ["powershell", "pwsh"],
    "word": ["WINWORD"],
    "excel": ["EXCEL"],
    "powerpoint": ["POWERPNT"],
    "bluestacks": ["HD-Player", "BlueStacks"],
    "fivem": ["FiveM", "FiveM_GTAProcess", "FiveM_b"],
    "roblox": ["RobloxPlayerBeta", "Roblox"],
    "ollama": ["ollama", "ollama app"],
    "tiktok": ["TikTok LIVE Studio", "TikTok"],
    "voicemod": ["Voicemod"],
    "winrar": ["WinRAR"],
    "xampp": ["xampp-control"],
    "whatsapp": ["WhatsApp", "WhatsApp.Root"],
    "hackerai": ["HackerAI", "hackerai"],
}

# Rutas típicas / comandos fijos (se complementan con Start Menu)
_FIJOS = {
    "notepad": ["notepad.exe"],
    "calc": ["calc.exe"],
    "explorer": ["explorer.exe"],
    "paint": ["mspaint.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "settings": ["ms-settings:"],
    "youtube": [],  # solo web
}

_PATH_HINTS = {
    "chrome": [
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    ],
    "edge": [
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    ],
    "opera": [
        r"%LocalAppData%\Programs\Opera GX\opera.exe",
        r"%LocalAppData%\Programs\Opera\opera.exe",
    ],
    "firefox": [
        r"%ProgramFiles%\Mozilla Firefox\firefox.exe",
        r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe",
    ],
    "vscode": [
        r"%LocalAppData%\Programs\Microsoft VS Code\Code.exe",
        r"%ProgramFiles%\Microsoft VS Code\Code.exe",
    ],
    "discord": [
        r"%LocalAppData%\Discord\Update.exe",
    ],
    "spotify": [
        r"%AppData%\Spotify\Spotify.exe",
        r"%LocalAppData%\Microsoft\WindowsApps\Spotify.exe",
    ],
    "steam": [
        r"%ProgramFiles(x86)%\Steam\steam.exe",
        r"%ProgramFiles%\Steam\steam.exe",
    ],
    "obs": [
        r"%ProgramFiles%\obs-studio\bin\64bit\obs64.exe",
        r"%ProgramFiles(x86)%\obs-studio\bin\64bit\obs64.exe",
    ],
    "word": [
        r"%ProgramFiles%\Microsoft Office\root\Office16\WINWORD.EXE",
        r"%ProgramFiles(x86)%\Microsoft Office\root\Office16\WINWORD.EXE",
    ],
    "excel": [
        r"%ProgramFiles%\Microsoft Office\root\Office16\EXCEL.EXE",
        r"%ProgramFiles(x86)%\Microsoft Office\root\Office16\EXCEL.EXE",
    ],
    "powerpoint": [
        r"%ProgramFiles%\Microsoft Office\root\Office16\POWERPNT.EXE",
    ],
    "bluestacks": [
        r"%ProgramFiles%\BlueStacks_nxt\HD-Player.exe",
        r"%ProgramData%\Microsoft\Windows\Start Menu\Programs\BlueStacks 5.lnk",
    ],
    "fivem": [
        r"%LocalAppData%\FiveM\FiveM.exe",
    ],
    "ollama": [
        r"%LocalAppData%\Programs\Ollama\ollama app.exe",
        r"%LocalAppData%\Programs\Ollama\ollama.exe",
    ],
}


def _expand(p: str) -> str:
    return os.path.expandvars(p)


def _existe(p: str) -> bool:
    return bool(p) and os.path.isfile(_expand(p))


def _start_menu_dirs():
    bases = [
        os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                     r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("APPDATA", ""),
                     r"Microsoft\Windows\Start Menu\Programs"),
    ]
    return [b for b in bases if b and os.path.isdir(b)]


def _buscar_lnk(nombre: str):
    """Busca .lnk en Start Menu cuyo nombre contenga nombre."""
    nombre = (nombre or "").lower()
    if not nombre:
        return None
    keys = [nombre] + [p for p in nombre.split() if len(p) > 2]
    for base in _start_menu_dirs():
        try:
            for root, _dirs, files in os.walk(base):
                for f in files:
                    if not f.lower().endswith(".lnk"):
                        continue
                    fl = f.lower()
                    if any(k in fl for k in keys):
                        return os.path.join(root, f)
        except Exception:
            continue
    return None


def _resolver_exe(clave: str):
    """Devuelve ruta/comando lanzable o None."""
    if clave in _FIJOS and _FIJOS[clave]:
        return _FIJOS[clave][0]

    for hint in _PATH_HINTS.get(clave, []):
        p = _expand(hint)
        if _existe(p):
            return p
        # Discord Update.exe necesita --processStart
        if clave == "discord" and p.lower().endswith("update.exe") and os.path.isfile(p):
            return p

    # Start Menu
    lnk_names = {
        "chrome": "chrome",
        "edge": "edge",
        "opera": "opera",
        "vscode": "visual studio code",
        "discord": "discord",
        "spotify": "spotify",
        "steam": "steam",
        "obs": "obs",
        "bluestacks": "bluestacks",
        "fivem": "fivem",
        "roblox": "roblox",
        "ollama": "ollama",
        "hackerai": "hackerai",
        "tiktok": "tiktok",
        "voicemod": "voicemod",
        "winrar": "winrar",
        "xampp": "xampp",
        "firefox": "firefox",
    }
    lnk = _buscar_lnk(lnk_names.get(clave, clave))
    if lnk:
        return lnk

    # PATH
    for cand in (clave, f"{clave}.exe", "code" if clave == "vscode" else None):
        if not cand:
            continue
        try:
            r = subprocess.run(
                ["where", cand],
                capture_output=True,
                text=True,
                timeout=3,
                shell=True,
            )
            line = (r.stdout or "").strip().splitlines()
            if line and os.path.isfile(line[0].strip()):
                return line[0].strip()
        except Exception:
            pass
    return None


def _lanzar(ruta: str, extra_args=None) -> bool:
    extra_args = extra_args or []
    try:
        if ruta.lower().startswith("ms-"):
            os.startfile(ruta)  # type: ignore[attr-defined]
            return True
        if ruta.lower().endswith(".lnk"):
            os.startfile(ruta)  # type: ignore[attr-defined]
            return True
        # Discord especial
        if ruta.lower().endswith("update.exe") and "discord" in ruta.lower():
            subprocess.Popen(
                [ruta, "--processStart", "Discord.exe"],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        if os.path.isfile(ruta):
            subprocess.Popen(
                [ruta, *extra_args],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=os.path.dirname(ruta) or None,
            )
            return True
        # fallback shell
        subprocess.Popen(
            f'"{ruta}"',
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        try:
            os.startfile(ruta)  # type: ignore[attr-defined]
            return True
        except Exception:
            return False


def _norm(s: str) -> str:
    t = (s or "").lower().strip()
    for a, b in (
        ("á", "a"),
        ("é", "e"),
        ("í", "i"),
        ("ó", "o"),
        ("ú", "u"),
        ("ü", "u"),
        ("ñ", "n"),
    ):
        t = t.replace(a, b)
    t = re.sub(r"[¿?¡!.,;:\"']+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parsear_comando_pc(texto: str):
    """
    Detecta intención PC/YouTube desde lenguaje natural.
    Devuelve dict {tipo, ...} o None.
    """
    # URL directa o "abre <url>" (antes de normalizar: _norm rompe la URL)
    m_url = re.match(
        r"^(?:(?:abre|abrir|abre me|abrirme|visita|entra|entrar|ve a|anda a|mete|abre el|abre la)\s+)?(https?://\S+)\s*$",
        texto.strip(),
        re.IGNORECASE,
    )
    if m_url:
        return {"tipo": "url", "url": m_url.group(1)}

    t = _norm(texto)
    if not t:
        return None

    # Quitar muletillas
    t = re.sub(r"\b(por favor|please|oye|eh|este|este)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    # --- YouTube: busca / pon / reproduce / abre ---
    yt = re.search(
        r"(?:abre|abrir|pon|poner|ponme|reproduce|reproducir|busca|buscar|play|"
        r"quiero oir|quiero escuchar|escuchar|dale play a|metele)\s+"
        r"(?:en\s+)?(?:youtube|youtu|yt)\s+(.+)$",
        t,
    )
    if yt:
        q = yt.group(1).strip()
        q = re.sub(r"^(la cancion|el video|el tema|musica|la musica)\s+", "", q)
        if q:
            return {"tipo": "youtube", "query": q}

    # Solo búsqueda si hay verbo de buscar/poner o query explícita (no "abre youtube" solo)
    yt2 = re.search(
        r"(?:busca|buscar|pon|poner|ponme|reproduce|reproducir|play)\s+"
        r"(?:en\s+)?(?:youtube|youtu|yt)\s+(.+)$",
        t,
    )
    if yt2:
        q = yt2.group(1).strip()
        q = re.sub(r"^(la cancion|el video|el tema|musica|la musica)\s+", "", q)
        if q and q not in ("youtube", "youtu", "yt"):
            return {"tipo": "youtube", "query": q}

    yt3 = re.search(
        r"(?:en\s+)?(?:youtube|youtu|yt)\s+(?:busca|buscar|pon|poner|reproduce)\s+(.+)$",
        t,
    )
    if yt3:
        q = yt3.group(1).strip()
        if q and q not in ("youtube", "youtu", "yt"):
            return {"tipo": "youtube", "query": q}

    # "pon bad bunny" / "reproduce despacito" sin decir youtube → youtube
    m_play = re.search(
        r"^(?:pon|poner|ponme|reproduce|reproducir|play|escuchar|quiero oir)\s+(.+)$",
        t,
    )
    if m_play:
        q = m_play.group(1).strip()
        # si parece app, no youtube
        if _ALIAS.get(q) or q in _ALIAS.values():
            pass
        elif len(q) >= 2 and not q.startswith("el pc"):
            # si menciona musica / cancion → yt
            if any(k in t for k in ("cancion", "musica", "tema", "video", "youtube", "yt")):
                q = re.sub(r"\b(cancion|musica|tema|video|de|la|el|un|una|lo|los|las)\b", " ", q)
                q = re.sub(r"\s+", " ", q).strip()
                if q:
                    return {"tipo": "youtube", "query": q}
            # "pon X" corto → youtube búsqueda
            if len(q.split()) <= 8 and not any(
                k in q for k in ("chrome", "code", "discord", "notepad", "steam")
            ):
                return {"tipo": "youtube", "query": q}

    # --- Abrir app ---
    m = re.search(
        r"(?:abre|abrir|abre me|abrirme|lanza|lanzar|inicia|iniciar|ejecuta|ejecutar|"
        r"abre el|abre la|abre me el|abre me la)\s+(.+)$",
        t,
    )
    if m:
        app = m.group(1).strip()
        app = re.sub(r"^(el|la|los|las|un|una|mi|el programa|la app|la aplicacion)\s+", "", app)
        # "abre youtube bad bunny" 
        if app.startswith("youtube") or app.startswith("youtu"):
            resto = re.sub(r"^youtu(?:be|)\s*", "", app).strip()
            if resto:
                return {"tipo": "youtube", "query": resto}
            return {"tipo": "youtube_home"}
        return {"tipo": "app", "app": app}

    # --- Cerrar app (antes de alias sueltos) ---
    m_c = re.search(
        r"(?:cierra|cerrar|cierre|quita|quitar|mata|matar|kill|cierra el|cierra la|"
        r"cierra me|cierrame|apaga el|apaga la)\s+(.+)$",
        t,
    )
    if m_c:
        app = m_c.group(1).strip()
        app = re.sub(
            r"^(el|la|los|las|un|una|mi|el programa|la app|la aplicacion)\s+",
            "",
            app,
        )
        if app and app not in ("pc", "el pc", "la computadora", "el ordenador"):
            return {"tipo": "cerrar", "app": app}

    # "chrome" / "vscode" solo
    if t in _ALIAS or t in _ALIAS.values():
        return {"tipo": "app", "app": t}

    # URL directa
    if re.match(r"https?://", texto.strip()):
        return {"tipo": "url", "url": texto.strip()}

    return None


class PCControl:
    def __init__(self, bus=None):
        self.bus = bus
        self._cache_apps = None
        if gestor.bus is None:
            gestor.bus = bus

    def listar_apps_menu(self):
        """Nombres de accesos del menú inicio (para memoria/HUD)."""
        names = []
        for base in _start_menu_dirs():
            try:
                for root, _d, files in os.walk(base):
                    for f in files:
                        if f.lower().endswith(".lnk"):
                            names.append(os.path.splitext(f)[0])
            except Exception:
                pass
        return sorted(set(names), key=str.lower)

    def abrir_app(self, nombre: str) -> str:
        raw = _norm(nombre)
        for pref in ("el ", "la ", "los ", "las ", "un ", "una ", "mi "):
            if raw.startswith(pref):
                raw = raw[len(pref) :]
        clave = _ALIAS.get(raw, raw.replace(" ", ""))
        if raw in _ALIAS:
            clave = _ALIAS[raw]
        else:
            # fuzzy: contiene
            for k, v in _ALIAS.items():
                if k in raw or raw in k:
                    clave = v
                    break

        if clave == "youtube":
            return self.youtube_home()

        ruta = _resolver_exe(clave)
        if not ruta:
            # último intento: start menu con el nombre crudo
            lnk = _buscar_lnk(raw)
            if lnk:
                if _lanzar(lnk):
                    return f"Listo, abro {nombre}."
            return f"No encuentro {nombre} instalado. Prueba con el nombre exacto."

        ok = _lanzar(ruta)
        if ok:
            return f"Listo, abro {nombre}."
        return f"Intenté abrir {nombre} pero falló."

    def youtube_buscar(self, query: str) -> str:
        q = (query or "").strip()
        if not q:
            return self.youtube_home()
        url = f"https://www.youtube.com/results?search_query={quote_plus(q)}"
        try:
            webbrowser.open(url, new=2)
            return f"Buscando en YouTube: {q}."
        except Exception as e:
            return f"No pude abrir YouTube: {e}"

    def youtube_home(self) -> str:
        try:
            webbrowser.open("https://www.youtube.com", new=2)
            return "Abro YouTube."
        except Exception as e:
            return f"No pude abrir YouTube: {e}"

    def abrir_url(self, url: str) -> str:
        try:
            webbrowser.open(url, new=2)
            return "Abro el enlace."
        except Exception as e:
            return f"No pude abrir el enlace: {e}"

    def _resolver_clave(self, nombre: str) -> str:
        raw = _norm(nombre)
        for pref in ("el ", "la ", "los ", "las ", "un ", "una ", "mi "):
            if raw.startswith(pref):
                raw = raw[len(pref) :]
        if raw in _ALIAS:
            return _ALIAS[raw]
        for k, v in _ALIAS.items():
            if k in raw or raw in k:
                return v
        return raw.replace(" ", "") or raw

    def cerrar_app(self, nombre: str) -> str:
        clave = self._resolver_clave(nombre)
        if clave == "youtube":
            # Cierra pestañas no; mata navegador principal si pidieron youtube
            procs = _PROC.get("chrome", ["chrome"])
        else:
            procs = _PROC.get(clave)
            if not procs:
                # intento genérico: nombre crudo como proceso
                procs = [clave, nombre.strip()]

        muertos = 0
        vistos = set()
        for p in procs:
            p = (p or "").strip()
            if not p or p.lower() in vistos:
                continue
            vistos.add(p.lower())
            try:
                r = subprocess.run(
                    ["taskkill", "/IM", f"{p}.exe", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                out = (r.stdout or "") + (r.stderr or "")
                if r.returncode == 0 or "SUCCESS" in out.upper():
                    muertos += 1
                elif "no se encontr" not in out.lower() and "not found" not in out.lower():
                    # sin .exe
                    r2 = subprocess.run(
                        ["taskkill", "/IM", p, "/F"],
                        capture_output=True,
                        text=True,
                        timeout=8,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    if r2.returncode == 0:
                        muertos += 1
            except Exception:
                continue

        if muertos:
            return f"Listo, cierro {nombre}."
        return f"No vi {nombre} abierto."

    def ejecutar_desde_texto(self, texto: str):
        """Si el texto es comando PC, lo ejecuta y devuelve respuesta; si no, None."""
        cmd = parsear_pc_extra(texto) or parsear_comando_pc(texto)
        if not cmd:
            return None
        respuesta = ejecutar_pc_extra(cmd, self.bus)
        if respuesta is not None:
            return respuesta
        tipo = cmd.get("tipo")
        if tipo == "youtube":
            return self.youtube_buscar(cmd.get("query") or "")
        if tipo == "youtube_home":
            return self.youtube_home()
        if tipo == "url":
            return self.abrir_url(cmd.get("url") or "")
        if tipo == "app":
            return self.abrir_app(cmd.get("app") or "")
        if tipo == "cerrar":
            return self.cerrar_app(cmd.get("app") or "")
        return None
