# Coordinador de acciones: las "manos" de JARVIS
import datetime

import psutil

from acciones.luces import Luces
from acciones.pc import PCControl
from acciones.webmon import WebMon


class Acciones:
    def __init__(self, bus):
        self.bus = bus
        self.luces = Luces(bus)
        self.webmon = WebMon(bus)
        self.pc = PCControl(bus)

    def ejecutar(self, intento, args=None):
        args = args or {}
        try:
            if intento == "luces":
                return self.luces.encender(*args.get("color", (0, 80, 255)))
            if intento == "luces_apagar":
                return self.luces.apagar()
            if intento == "hora":
                return (
                    f"Son las {datetime.datetime.now().strftime('%H:%M')}. "
                    f"Tu PC lleva {self._minutos_encendido()} encendido."
                )
            if intento == "apagar":
                return self._apagar_pc()
            if intento in ("pc", "abrir", "app"):
                app = args.get("app") or args.get("nombre") or ""
                return self.pc.abrir_app(app)
            if intento in ("cerrar", "cierra", "close"):
                app = args.get("app") or args.get("nombre") or ""
                return self.pc.cerrar_app(app)
            if intento in ("youtube", "yt"):
                q = args.get("query") or args.get("q") or ""
                if q:
                    return self.pc.youtube_buscar(q)
                return self.pc.youtube_home()
            if intento == "url":
                return self.pc.abrir_url(args.get("url") or "")
            if intento == "web":
                return self.webmon.resumen()
            if intento == "estado":
                return self._estado_pc()
            if intento == "charla":
                return "Aquí estoy contigo. ¿Qué necesitas?"
            # Lenguaje natural completo
            if intento in ("nl", "texto", "comando"):
                return self.pc.ejecutar_desde_texto(args.get("texto") or "")
            return ""
        except Exception as e:
            return f"He tenido un tropiezo con eso: {e}"

    def desde_texto(self, texto: str):
        """Atajo: parsea y ejecuta comando PC/YouTube. None si no aplica."""
        return self.pc.ejecutar_desde_texto(texto or "")

    def _minutos_encendido(self):
        import time

        return str(datetime.timedelta(seconds=int(time.time() - psutil.boot_time())))

    def _estado_pc(self):
        cpu = psutil.cpu_percent(interval=0.3)
        ram = psutil.virtual_memory().percent
        disc = psutil.disk_usage("C:\\").percent
        bat = psutil.sensors_battery()
        pila = (
            f"Batería al {bat.percent}%."
            if bat
            else "Conectado a la corriente."
        )
        return (
            f"PC en forma: CPU {cpu:g}%, RAM {ram:g}%, disco {disc:g}%. {pila}"
        )

    def _apagar_pc(self):
        import subprocess

        self.bus.publicar("estado", "Apagando el PC en 20 segundos…")
        subprocess.Popen("shutdown /s /t 20", shell=True)
        return "Vale, apago el equipo en veinte segundos. Que descanses."
