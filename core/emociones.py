# Motor emocional con "neuronas" â€” cada emociÃ³n influye en las demÃ¡s.
import time
import random

# Cada emociÃ³n: color, icono, decaimiento por tick, y conexiones a otras
EMOCIONES = {
    "alegria": {
        "color": "#FFD700", "icono": "ðŸ˜„", "decaimiento": 0.018,
        "conexiones": {"sorpresa": 0.25, "amor": 0.20, "enojo": -0.40},
    },
    "tristeza": {
        "color": "#5599ee", "icono": "ðŸ˜¢", "decaimiento": 0.014,
        "conexiones": {"enojo": 0.30, "miedo": 0.15, "alegria": -0.35},
    },
    "enojo": {
        "color": "#ff3838", "icono": "ðŸ˜¤", "decaimiento": 0.032,
        "conexiones": {"tristeza": 0.20, "miedo": 0.10, "alegria": -0.50},
    },
    "sorpresa": {
        "color": "#ff9900", "icono": "ðŸ˜²", "decaimiento": 0.065,
        "conexiones": {"alegria": 0.20, "miedo": 0.18},
    },
    "miedo": {
        "color": "#9944ff", "icono": "ðŸ˜¨", "decaimiento": 0.028,
        "conexiones": {"sorpresa": 0.20, "tristeza": 0.12},
    },
    "amor": {
        "color": "#ff77bb", "icono": "ðŸ¥°", "decaimiento": 0.008,
        "conexiones": {"alegria": 0.45, "tristeza": -0.30},
    },
    "neutral": {
        "color": "#00e5ff", "icono": "ðŸ˜", "decaimiento": 0.0,
        "conexiones": {},
    },
}


class Emociones:
    """Sistema emocional con memoria y conexiones entre emociones."""

    def __init__(self, bus=None):
        self.bus = bus
        self.intensidades = {nombre: 0.0 for nombre in EMOCIONES}
        self.intensidades["neutral"] = 1.0
        self._ultimo_tic = time.time()
        self._historial = []  # Ãºltimas emociones sentidas
        self._hablando = False

        # Palabras clave â†’ emociÃ³n (con intensidad)
        self._detectores = {
            "alegria": {
                "palabras": [
                    "feliz", "genial", "jeje", "jaja", "guay", "alegre", "bien",
                    "contento", "divertido", "fiesta", "celebrar", "gracioso",
                    "risa", "bueno", "excelente", "fantÃ¡stico", "maravilloso",
                    "me encanta", "amo", "genial", "chÃ©vere", "padre", "cool",
                ],
                "intensidad": 0.35,
            },
            "tristeza": {
                "palabras": [
                    "triste", "solo", "sola", "mal", "deprimido", "llorar",
                    "extraÃ±o", "nostalgia", "duele", "dolor", "pÃ©rdida",
                    "perdida", "difÃ­cil", "pesado", "no puedo", "cansado",
                    "agotado", "aburrido", "desanimado", "desmotivado",
                ],
                "intensidad": 0.30,
            },
            "enojo": {
                "palabras": [
                    "enfadado", "enojado", "molesto", "rabia", "odio",
                    "fastidia", "insoportable", "harto", "harta", "basta",
                    "demonios", "mierda", "estÃºpido", "idiota", "imbÃ©cil",
                    "frustrado", "injusto", "mentira",
                ],
                "intensidad": 0.40,
            },
            "sorpresa": {
                "palabras": [
                    "sorpresa", "guau", "wow", "increÃ­ble", "impresionante",
                    "no me lo creo", "en serio", "Â¿quÃ©?", "quÃ© dices",
                    "alucinante", "flipante", "no puede ser", "asombroso",
                ],
                "intensidad": 0.50,
            },
            "miedo": {
                "palabras": [
                    "miedo", "asustado", "terror", "pÃ¡nico", "preocupado",
                    "ansioso", "nervioso", "inquietante", "peligro",
                    "amenaza", "oscuro", "fantasma", "pesadilla",
                ],
                "intensidad": 0.35,
            },
            "amor": {
                "palabras": [
                    "te quiero", "te amo", "gracias", "eres genial",
                    "cariÃ±o", "abrazar", "beso", "corazÃ³n", "amigo",
                    "amiga", "hermoso", "precioso", "lindo", "adorable",
                    "me gustas", "especial", "importante",
                ],
                "intensidad": 0.30,
            },
        }

    # ------------------------------------------------------------------
    def procesar(self, texto):
        """Analiza el texto y ajusta las intensidades emocionales."""
        self._decaer()
        texto_l = texto.lower()

        for nombre, detector in self._detectores.items():
            if any(p in texto_l for p in detector["palabras"]):
                self._activar(nombre, detector["intensidad"])

        dom = self.dominante()
        if self.bus:
            self.bus.publicar("mood", {
                "emocion": dom["nombre"],
                "intensidad": round(dom["intensidad"], 2),
                "icono": dom["icono"],
                "color": dom["color"],
            })
        self._historial.append((time.time(), dom["nombre"]))
        if len(self._historial) > 50:
            self._historial = self._historial[-50:]
        return dom

    # ------------------------------------------------------------------
    def _activar(self, nombre, cantidad):
        """Sube una emociÃ³n y propaga a sus conexiones."""
        anterior = self.intensidades[nombre]
        self.intensidades[nombre] = min(1.0, anterior + cantidad)
        # "Neuronas": propaga a las emociones conectadas
        for vecina, peso in EMOCIONES[nombre]["conexiones"].items():
            delta = cantidad * peso * 0.6  # peso amortiguado
            self.intensidades[vecina] = max(0.0, min(1.0, self.intensidades[vecina] + delta))
        # La emociÃ³n opuesta se reduce (ej: alegria baja tristeza)
        self.intensidades["neutral"] = max(0.0, self.intensidades["neutral"] - cantidad * 0.5)

    # ------------------------------------------------------------------
    def _decaer(self):
        """Todas las emociones vuelven lentamente hacia neutral."""
        ahora = time.time()
        ticks = max(1, int((ahora - self._ultimo_tic) * 10))  # ~10 ticks/seg
        self._ultimo_tic = ahora

        for _ in range(min(ticks, 30)):
            for nombre, cfg in EMOCIONES.items():
                if nombre == "neutral":
                    self.intensidades["neutral"] = min(1.0, self.intensidades["neutral"] + 0.015)
                    continue
                if self.intensidades[nombre] > 0.001:
                    self.intensidades[nombre] = max(0.0, self.intensidades[nombre] - cfg["decaimiento"])

    # ------------------------------------------------------------------
    def dominante(self):
        """Devuelve la emociÃ³n mÃ¡s intensa en este momento."""
        mejor = "neutral"
        mejor_val = 0.0
        for nombre, val in self.intensidades.items():
            if nombre == "neutral":
                continue
            if val > mejor_val:
                mejor_val = val
                mejor = nombre
        # Si ninguna emociÃ³n supera el umbral, neutral
        if mejor_val < 0.06:
            return {"nombre": "neutral", "intensidad": 1.0, "icono": EMOCIONES["neutral"]["icono"], "color": EMOCIONES["neutral"]["color"]}
        return {"nombre": mejor, "intensidad": min(1.0, mejor_val), "icono": EMOCIONES[mejor]["icono"], "color": EMOCIONES[mejor]["color"]}

    # ------------------------------------------------------------------
    def resumen(self):
        """Texto corto con el estado emocional para el prompt del LLM."""
        dom = self.dominante()
        if dom["nombre"] == "neutral":
            return "Luis estÃ¡ tranquilo, Ã¡nimo neutral."
        intensidad_txt = "muy " if dom["intensidad"] > 0.6 else "algo " if dom["intensidad"] > 0.3 else "ligeramente "
        return f"Luis estÃ¡ {intensidad_txt}{dom['nombre']} (intensidad {dom['intensidad']:.0%})."

    # ------------------------------------------------------------------
    def micro_variacion(self):
        """PequeÃ±a fluctuaciÃ³n aleatoria para que la cara parezca viva."""
        dom = self.dominante()
        return {
            "emocion": dom["nombre"],
            "intensidad": round(dom["intensidad"] + random.uniform(-0.03, 0.03), 2),
            "icono": dom["icono"],
            "color": dom["color"],
            "hablando": self._hablando,
        }

    def marcar_hablando(self, estado):
        self._hablando = estado

