# LUCES LED BLE: control de tu tira por Bluetooth Low Energy (protocolo Zengge/LEDENET)
import asyncio

from config import TIRA_BLE_ADDR, TIRA_BLE_NOMBRES

# Características típicas donde se escribe el color en tiras baratas
CARACTERISTICAS_COLOR = (
    "0000ffe5-0000-1000-8000-00805f9b34fb",
    "0000ffe4-0000-1000-8000-00805f9b34fb",
    "0000ffe9-0000-1000-8000-00805f9b34fb",
    "0000ffb2-0000-1000-8000-00805f9b34fb",
)


class Luces:
    def __init__(self, bus):
        self.bus = bus
        self._dir = TIRA_BLE_ADDR
        self._cliente = None

    # ------------------------------------------------------------------
    def _buscar_dispositivo(self):
        """Escanea y devuelve la dirección de una tira LED."""
        try:
            from bleak import BleakScanner
            dispositivo = asyncio.run(self._escanear(BleakScanner))
            if dispositivo is None:
                self.bus.publicar("estado",
                                  "No encontré ninguna tira LED por Bluetooth. "
                                  "Pareja la tira en Windows (Ajustes > Bluetooth) y repite.")
                return None
            self._dir = dispositivo
            return dispositivo
        except Exception as e:
            self.bus.publicar("estado",
                              f"No hay Bluetooth activo: {e}. "
                              "Enciende el servicio de Bluetooth de Windows (te explico al final).")
            return None

    async def _escanear(self, BleakScanner):
        dispositivos = await BleakScanner.discover(timeout=6)
        for d in dispositivos:
            nombre = (d.name or "").strip()
            if nombre and any(p in nombre for p in TIRA_BLE_NOMBRES):
                self.bus.publicar("estado", f"Encontré tu tira: {nombre} ({d.address})")
                return d.address
        return None

    # ------------------------------------------------------------------
    async def _escribir_color(self, dir, rgb):
        from bleak import BleakClient
        async with BleakClient(dir, timeout=10) as cliente:
            servicios = cliente.services
            # si no cargó servicios, lee uno a uno
            if not servicios:
                await cliente.get_services()
            for servicio in servicios:
                for car in servicio.characteristics:
                    if "write" not in car.properties:
                        continue
                    if car.uuid.lower() in CARACTERISTICAS_COLOR or car.uuid[:4].lower() in ("ffe5", "ffe4", "ffe9", "ffb2"):
                        r, g, b = rgb
                        paquete = bytes([0x56, 0x00, 0x00, r, g, b, 0xAA])
                        await cliente.write_gatt_char(car, paquete)
                        self.bus.publicar("estado",
                                          f"Color enviado a la tira: RGB{rgb} — {car.uuid}")
                        return True
        self.bus.publicar("estado", "La tira no expone el canal de color esperado. "
                                    "Abrela con nRF Connect para ver sus características.")
        return False

    # ------------------------------------------------------------------
    def encender(self, r=0, g=80, b=255, esperar=True):
        """Enciende la tira en un color RGB."""
        rgb = (max(0, min(255, int(r))), max(0, min(255, int(g))), max(0, min(255, int(b))))
        dir = self._buscar_dispositivo() if not self._dir else self._dir
        if not dir:
            return "No tengo Bluetooth operativo todavía. En cuanto enciendas el adaptador, soy todo luces."
        try:
            asyncio.run(self._escribir_color(dir, rgb))
            return f"Luces en RGB{rgb}. ¿Qué tal queda?"
        except Exception as e:
            self.bus.publicar("estado", f"Fallo al escribir en la tira: {e}")
            return "La tira no respondió. ¿Está encendida y cerca del PC?"

    def apagar(self):
        self.bus.publicar("estado", "Apagando luces…")
        return self.encender(0, 0, 0)

    def estado(self):
        return "Bluetooth: en espera de parear tu tira (activa el servicio de Windows)."
