# CEREBRO: KAREN humana + multi-LLM + mundo real
import datetime
import json
import random
import re

from config import MODELO_LLM
from core.emociones import Emociones
from core.llm_router import LLMRouter
from core import mundo

# Personalidad: mujer cercana, clara, leal. Habla como persona real.
PERSONA = """Eres Karen, la compañera de IA de Luis. Eres una persona virtual cálida y clara,
no un robot ni un menú. Hablas como una amiga cercana mexicana: natural, directa, con humor suave
y sentimiento. Nunca suenes a call-center ni digas solo "Dime." / "¿Sí?".

Reglas de oro:
- Español natural. Siempre llama "Luis" (nunca Tony, jamás señor).
- Responde EXACTAMENTE a lo que preguntó. Si pregunta X, habla de X. Cero temas inventados.
- NUNCA repitas la misma palabra muchas veces (prohibido "no no no no...").
- NUNCA copies ejemplos de acciones. Si no hay que ejecutar nada, solo contesta en texto.
- Si no entendiste, una frase útil + duda corta. Prohibido: "reformúlame", "cuéntame más" vacío.
- Tono humano: puedes reír, preocuparte, animar. Emoción de Luis: {contexto_emocional}
- 1 o 2 frases naturales (máximo 35 palabras). Sin markdown, sin emojis, sin listas.
- Modo voz {modo_voz}. Hora: {hora}.
- Datos del mundo (SOLO si preguntan):
{mundo}
- Recuerdos:
{recuerdos}
- Acciones (solo si Luis pide ejecutar algo REAL ahora; una línea al inicio, sin inventar args):
  ACCION|{{"intento":"hora"}}
  ACCION|{{"intento":"estado"}}
  ACCION|{{"intento":"pc","args":{{"app":"NOMBRE_APP"}}}}
  ACCION|{{"intento":"cerrar","args":{{"app":"NOMBRE_APP"}}}}
  ACCION|{{"intento":"youtube","args":{{"query":"TEXTO_QUE_DIJO_LUIS"}}}}
  MEMORIA|dato importante sobre Luis
Si Luis dice solo "abre youtube", usa pc/youtube sin query inventada.
Contesta YA como Karen, con claridad."""

GUIAS = {
    "alegria": "Luis va bien. Sé juguetón y cálido.",
    "tristeza": "Luis bajo. Cercano, suave, sin bromas pesadas.",
    "enojo": "Luis caliente. Breve, firme y útil.",
    "sorpresa": "Curioso y al grano, con energía.",
    "miedo": "Firme y tranquilizador.",
    "amor": "Cálido sin empalagar.",
    "neutral": "Natural, con humor suave. Como un buen amigo.",
}

_SALUDOS = [
    "Hola Luis, qué gusto. ¿En qué andamos?",
    "Aquí estoy contigo. Cuéntame.",
    "Hola. Todo listo de este lado.",
    "Qué tal, Luis. Te escucho.",
]

_ESCUCHO = [
    "Sí, te escucho perfecto. ¿Qué necesitas?",
    "Claro que sí, Luis. Aquí estoy contigo.",
    "Te oigo bien. Dime.",
    "Presente. ¿En qué te ayudo?",
]

_COMO_ESTAS = [
    "Bien, con ganas de ayudarte. ¿Y tú cómo vas?",
    "De buen humor y atenta. ¿Tú qué tal?",
    "Me siento bien, la verdad. ¿Tú cómo estás?",
    "Contenta de que hables conmigo. ¿Cómo te sientes?",
]

_FALLBACK = [
    "No te capté bien. ¿Me lo repites un poquito más claro?",
    "Se me fue. Dímelo otra vez y lo aterrizo.",
    "Estoy contigo, solo no oí bien. ¿Otra vez?",
]


class Cerebro:
    def __init__(self, bus, memoria, acciones):
        self.bus = bus
        self.memoria = memoria
        self.acciones = acciones
        self.emociones = Emociones(bus)
        self.mood = "neutral"
        self.voz_perfil = "normal"
        self.llm = LLMRouter()
        self._ultimo_prov = "local"

    def set_voz_perfil(self, nombre: str):
        nombre = (nombre or "normal").lower().strip()
        if nombre == "hacker":
            nombre = "cris"
        if nombre not in ("normal", "cris"):
            nombre = "normal"
        self.voz_perfil = nombre
        try:
            self.bus.publicar(
                "voz_perfil",
                {"perfil": self.voz_perfil, "label": self._label_perfil()},
            )
        except Exception:
            pass

    def _label_perfil(self):
        return "CRIS · hacker" if self.voz_perfil == "cris" else "LUIS · normal"

    def procesar(self, texto):
        texto = (texto or "").strip()
        if not texto:
            return random.choice(
                [
                    "Te escucho, Luis.",
                    "Aquí estoy. ¿Qué necesitas?",
                    "Dime, te oigo.",
                ]
            )

        rapido = self._atajos(texto)
        if rapido is not None:
            self._mood_usuario(texto)
            return rapido

        self._mood_usuario(texto)
        dom = self.emociones.dominante()
        self.mood = dom["nombre"]

        momento = datetime.datetime.now().strftime("%H:%M")
        recuerdos = self.memoria.resumen()
        guia = GUIAS.get(dom["nombre"], GUIAS["neutral"])
        modo = "CRIS/hacker" if self.voz_perfil == "cris" else "normal"
        mundo_txt = ""
        low = texto.lower()
        if any(k in low for k in ("noticia", "periód", "period", "titular", "prensa", "dicen")):
            mundo_txt = mundo.noticias_hoy(max_items=3)
        elif any(k in low for k in ("clima", "tiempo", "llueve", "temperatura")):
            mundo_txt = mundo.clima_simple()
        elif any(k in low for k in ("estadística", "estadistica", "stats", "cpu", "ram")):
            mundo_txt = mundo.stats_pc()
        elif any(
            k in low
            for k in (
                "briefing",
                "resumen del día",
                "resumen del dia",
                "mañana",
                "manana",
            )
        ):
            mundo_txt = mundo.briefing_manana()

        sistema = (
            PERSONA.replace("{hora}", momento)
            .replace("{contexto_emocional}", guia)
            .replace("{recuerdos}", recuerdos or "(nada aún)")
            .replace("{modo_voz}", modo)
            .replace("{mundo}", mundo_txt or "(sin datos extra)")
        )

        try:
            self.bus.publicar("estado", "Pensando…")
            self.bus.publicar("mic_status", {"modo": "procesando", "msg": "Pensando…"})
        except Exception:
            pass

        # Tokens moderados: evita monólogos y bucles. La sección decide el motor.
        seccion = self._seccion_de(texto)
        resp = self.llm.chat(
            texto, system=sistema, timeout=16, max_tokens=90, seccion=seccion
        )
        self._ultimo_prov = self.llm.ultimo_proveedor
        try:
            self.bus.publicar(
                "estado",
                f"LLM {self._ultimo_prov} {self.llm.ultimo_ms}ms ({seccion})",
            )
        except Exception:
            pass

        if not resp:
            return self._reglas(texto)

        datos = self._extraer_json(re.search(r"ACCION\|\s*(\{.*\})", resp, re.DOTALL))
        if datos:
            intento = (datos.get("intento") or "").lower()
            args = datos.get("args", {}) or {}
            # No ejecutar YouTube/PC inventados que el usuario no pidió
            if not self._accion_coincide(texto, intento, args):
                datos = None
            else:
                resultado = self._ejecutar(intento, args)
                if resultado:
                    return self._acortar(resultado, 40)
                return self._reglas(texto)

        frase = self._frase_memoria(resp)
        if frase:
            self.memoria.recordar_frase(frase, texto)

        limpio = re.sub(
            r"\s*(\(\s*)?(ACCION|MEMORIA)\|[^\n)]*\)?\s*",
            " ",
            resp,
            flags=re.DOTALL,
        )
        limpio = re.sub(r"\s+", " ", limpio).strip(" *\n-")
        limpio = re.sub(r"\bTony\b", "Luis", limpio, flags=re.I)
        limpio = re.sub(r"\bJarvis\b", "Karen", limpio, flags=re.I)
        limpio = self._colapsar_repeticiones(limpio)
        if self._es_basura(limpio):
            return self._reglas(texto)
        return self._acortar(limpio, 35) or self._reglas(texto)

    # Palabras que delatan la sección del mensaje (para elegir motor LLM).
    _SECCION_PALABRAS = {
        "codigo": (
            "codigo", "programa", "programar", "script", "funcion",
            "python", "bug", "error de", "app", "aplicacion", "desarrolla",
            "desarrollame", "crea un programa", "terminal", "comando", "github",
            "git", "base de datos", "sql", "javascript", "html", "css", "api",
            "algoritmo", "compilar", "ejecuta este", "pantalla azul", "excel",
            "automatiza", "automatizame",
        ),
        "creativo": (
            "idea", "historia", "cuento", "poema", "poesia", "cancion",
            "nombre para", "logo", "diseno", "diseño", "creativo", "creativa",
            "lluvia de ideas", "escribe un", "inventa", "imagina", "personaje",
            "titulo para", "eslogan", "meme", "storytelling",
        ),
        "mundo": (
            "noticia", "noticias", "mundo", "clima", "llueve", "temperatura",
            "precio", "dolar", "peso", "politica", "deporte", "futbol",
            "economia", "mercado", "trafico", "hoy en", "en el mundo",
            "ultima hora", "elecciones", "petroleo", "bitcoin", "cripto",
        ),
    }

    def _seccion_de(self, texto: str) -> str:
        """Clasifica el mensaje: codigo | creativo | mundo | general."""
        t = self._norm(texto)
        for seccion, palabras in self._SECCION_PALABRAS.items():
            if any(p in t for p in palabras):
                return seccion
        return "general"

    def _mood_usuario(self, texto: str):
        """Actualiza emoción solo por lo que dice Luis de sí mismo, no de Karen."""
        t = texto.lower()
        if re.search(
            r"(por\s*qu[eé]|porque).*(est[aá]s|estas).*(feliz|triste|enoj|alegre)",
            t,
        ) or re.search(r"(est[aá]s|estas)\s+(feliz|triste)", t):
            self.emociones._decaer()
            self.mood = self.emociones.dominante()["nombre"]
            return
        self.emociones.procesar(texto)
        self.mood = self.emociones.dominante()["nombre"]

    @staticmethod
    def _colapsar_repeticiones(t: str) -> str:
        if not t:
            return t
        t = re.sub(r"\b(\w{1,20})(?:[\s,;]+\1){2,}\b", r"\1", t, flags=re.I)
        return re.sub(r"\s+", " ", t).strip()

    def _accion_coincide(self, texto: str, intento: str, args: dict) -> bool:
        """Evita que el LLM invente búsquedas (ej. rock) o apps no pedidas."""
        t = self._norm(texto or "")
        intento = (intento or "").lower()
        if not intento:
            return False
        if intento in ("hora", "estado", "noticias", "clima", "briefing", "luces", "luces_apagar"):
            return True
        if intento in ("pc", "abrir", "app", "cerrar", "cierra", "close"):
            app = self._norm(str((args or {}).get("app") or (args or {}).get("nombre") or ""))
            if not app:
                return False
            # debe mencionar abrir/cerrar o el nombre de la app
            if any(k in t for k in ("abre", "abrir", "cierra", "cerrar", "lanza", "quita")):
                return True
            return app in t or any(p in t for p in app.split() if len(p) > 2)
        if intento in ("youtube", "yt"):
            q = self._norm(str((args or {}).get("query") or (args or {}).get("q") or ""))
            if "youtube" not in t and "youtu" not in t and " yt" not in f" {t} ":
                if not any(k in t for k in ("pon ", "reproduce", "musica", "cancion", "video")):
                    return False
            # "abre youtube" solo → ok sin query o query vacía
            if not q:
                return True
            # la query debe aparecer (aprox) en lo que dijo Luis
            tokens = [w for w in q.split() if len(w) > 2 and w not in ("youtube", "busca", "cancion", "musica")]
            if not tokens:
                return True
            hits = sum(1 for w in tokens if w in t)
            return hits >= max(1, len(tokens) // 2)
        return True

    @staticmethod
    def _es_basura(t: str) -> bool:
        if not t or len(t) < 2:
            return True
        low = t.lower().strip()
        words = re.findall(r"\w+", low)
        if len(words) >= 6:
            from collections import Counter
            w, c = Counter(words).most_common(1)[0]
            if c >= 5 and c / max(len(words), 1) >= 0.4:
                return True
        # Respuestas de bot genérico / menú / basura
        basura = (
            "cuéntame un poco más",
            "cuentame un poco mas",
            "entendido. cuéntame",
            "entendido. cuentame",
            "dame más detalles",
            "dame mas detalles",
            "no entiendo",
            "como ia",
            "como una ia",
            "reformúlame",
            "reformulame",
            "puedes reformular",
            "no capté tu mensaje",
            "no capte tu mensaje",
            "¿en qué puedo ayudarte?",
            "en que puedo ayudarte",
            "soy un asistente",
            "como modelo de lenguaje",
            "te dije cómo estás",
            "te dije como estas",
            "responde.",
        )
        if any(b in low for b in basura):
            return True
        if low in ("sí", "si", "ok", "okay", "vale", "dime", "¿sí?", "¿si?", "te escucho.", "no"):
            return True
        if re.fullmatch(r"(no[\s,.]*){3,}", low):
            return True
        return False

    def _ejecutar(self, intento, args):
        intento = (intento or "").lower()
        if intento in ("noticias", "news", "periodico", "periódico"):
            tema = args.get("tema")
            return mundo.noticias_hoy(tema=tema)
        if intento in ("clima", "tiempo"):
            return mundo.clima_simple(args.get("ciudad") or "Mexico City")
        if intento in ("briefing", "resumen"):
            return mundo.briefing_manana()
        if intento in ("stats", "estadisticas", "estadísticas", "estado"):
            try:
                r = self.acciones.ejecutar("estado", args or {})
                if r:
                    return r
            except Exception:
                pass
            return mundo.stats_pc()
        if intento == "fecha":
            return mundo.fecha_hoy()
        try:
            return self.acciones.ejecutar(intento, args)
        except Exception:
            return None

    @staticmethod
    def _acortar(texto: str, max_palabras=48) -> str:
        t = (texto or "").strip()
        # Hasta 3 oraciones naturales
        parts = re.split(r"(?<=[.!?])\s+", t)
        if len(parts) > 3:
            t = " ".join(parts[:3])
        words = t.split()
        if len(words) > max_palabras:
            t = " ".join(words[:max_palabras]).rstrip(",;:") + "."
        return t

    def _norm(self, texto: str) -> str:
        t = texto.lower().strip()
        t = (
            t.replace("á", "a")
            .replace("é", "e")
            .replace("í", "i")
            .replace("ó", "o")
            .replace("ú", "u")
            .replace("ü", "u")
        )
        t = re.sub(r"[¿?¡!.,;:\"']+", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _atajos(self, texto):
        """Solo atajos seguros y unívocos. El resto va al LLM para no desviar el tema."""
        t = self._norm(texto)

        # --- me escuchas / estás ahí ---
        if any(
            p in t
            for p in (
                "me escuchas",
                "me oyes",
                "estas ahi",
                "estas escuchando",
                "me oyes karen",
                "me escuchas karen",
                "hay alguien",
                "estas online",
                "estas ahi karen",
                "me oyes jarvis",
                "me escuchas jarvis",
            )
        ) or t in (
            "me escuchas",
            "me oyes",
            "estas ahi",
            "hola karen",
            "hola jarvis",
        ):
            return random.choice(_ESCUCHO)

        # --- por qué estás feliz / por qué la cara ---
        if re.search(r"por\s*que.*(estas|esta).*(feliz|alegre|contento)", t) or re.search(
            r"porque.*(estas|esta).*(feliz|alegre)", t
        ):
            return random.choice(
                [
                    "Porque estás aquí, Luis. Me pone de buen humor trabajar contigo.",
                    "Sistemas en verde y tú hablando conmigo: eso me alegra de verdad.",
                    "Porque el día va fino y me cae bien estar a tu lado.",
                    "Es mi forma de decirte que todo está bien de este lado. ¿Tú cómo vas?",
                ]
            )

        if re.search(r"por\s*que.*(estas|esta).*(triste|enoj|molesto|serio)", t):
            return "No estoy mal: a veces la cara cambia con el contexto. Estoy bien contigo, Luis."

        if any(
            p in t
            for p in (
                "como te sientes",
                "como estas tu",
                "como estas jarvis",
                "como estas karen",
                "que tal estas",
            )
        ):
            return random.choice(_COMO_ESTAS)

        # --- hora (solo si es claro) ---
        if any(
            p in t
            for p in (
                "que hora",
                "la hora",
                "hora es",
                "me das la hora",
                "dime la hora",
            )
        ):
            return self._ejecutar("hora", {}) or datetime.datetime.now().strftime(
                "Son las %H:%M."
            )

        # --- fecha ---
        if any(p in t for p in ("que dia es", "que fecha", "fecha de hoy", "a que dia")):
            return mundo.fecha_hoy()

        # --- noticias / periódicos ---
        if any(
            p in t
            for p in (
                "noticia",
                "periodico",
                "periodicos",
                "titular",
                "prensa",
                "noticias de hoy",
                "que hay de nuevo en el mundo",
            )
        ):
            tema = None
            m = re.search(r"sobre (.+)$", t)
            if m:
                tema = m.group(1).strip()
            return mundo.noticias_hoy(tema=tema)

        # --- briefing mañana (evitar "que hay hoy" genérico: va al LLM) ---
        if any(
            p in t
            for p in (
                "briefing",
                "resumen del dia",
                "resumen de hoy",
                "actualizame",
                "actualiza me",
                "buenos dias jarvis",
                "buenos dias karen",
            )
        ):
            return mundo.briefing_manana()

        # --- clima ---
        if any(
            p in t
            for p in (
                "clima",
                "tiempo hace",
                "hace frio",
                "hace calor",
                "llueve",
                "temperatura",
                "como esta el clima",
            )
        ):
            return mundo.clima_simple()

        # --- stats PC (exigir señal clara de PC/sistema) ---
        if any(
            p in t
            for p in (
                "estadistica",
                "estadisticas",
                "stats",
                "estado del pc",
                "estado pc",
                "como esta el pc",
                "estado del sistema",
                "uso de cpu",
                "cuanta ram",
            )
        ):
            return self._ejecutar("estado", {}) or mundo.stats_pc()

        # --- saludos cortos exactos ---
        if t in (
            "hola",
            "buenas",
            "hey",
            "que tal",
            "buenos dias",
            "buenas tardes",
            "buenas noches",
            "holi",
            "ey",
            "ea",
            "hello",
        ) or (t.startswith("hola ") and len(t.split()) <= 3):
            return random.choice(_SALUDOS)

        if any(
            p in t
            for p in (
                "como estas",
                "como esta",
                "que tal estas",
                "como te va",
            )
        ) and len(t.split()) <= 6:
            return random.choice(_COMO_ESTAS)

        # --- Visión de pantalla: "¿qué ves en mi pantalla?" / "explícame esto" ---
        if any(p in t for p in (
            "que ves en mi pantalla", "que ves en la pantalla", "que vez en mi pantalla",
            "que hay en mi pantalla", "mira mi pantalla", "ve mi pantalla",
            "revisa mi pantalla", "que estoy viendo", "lee mi pantalla",
        )) or (
            ("pantalla" in t or "esto" in t or "esta pantalla" in t)
            and any(k in t for k in ("explica", "explicame", "que es", "que significa",
                                     "no entiendo", "ayudame con", "que dice"))
        ):
            try:
                from acciones.vista import ver_pantalla
                pregunta = texto
                return ver_pantalla(pregunta, bus=self.bus)
            except Exception as e:
                return f"No pude mirar tu pantalla ahora mismo. ({e})"

        # --- PC / YouTube (apps instaladas, buscar/reproducir) ---
        try:
            pc_r = self.acciones.desde_texto(texto)
            if pc_r:
                return pc_r
        except Exception:
            pass

        if any(p in t for p in ("gracias", "mil gracias", "te pasaste")):
            return random.choice(
                [
                    "De nada, Luis. Cuando quieras.",
                    "Para eso estoy, de verdad.",
                    "Un placer. Aquí sigo.",
                ]
            )

        if any(
            p in t
            for p in (
                "quien eres",
                "como te llamas",
                "que eres",
            )
        ):
            return (
                "Soy Karen, tu compañera de IA. No un bot cualquiera: "
                "estoy aquí para ti, con humor y con ganas de ayudar."
            )

        if any(p in t for p in ("que modelo", "que ia usas", "que llm", "proveedor")):
            provs = ", ".join(self.llm.proveedores())
            return f"Ahora mismo: {self.llm.ultimo_proveedor or MODELO_LLM}. Cadena: {provs}."

        # Sin atajo → LLM (evita respuestas fuera de tema)
        return None

    def _extraer_json(self, coincidencia):
        if not coincidencia:
            return None
        trozo = coincidencia.group(1).strip()
        try:
            return json.loads(trozo)
        except Exception:
            try:
                return json.loads(trozo.replace("'", '"'))
            except Exception:
                return None

    def _frase_memoria(self, resp):
        m = re.search(r"MEMORIA\|\s*(.+?)(?:\)|\]|\*|$)", resp)
        return m.group(1).strip() if m else None

    def _reglas(self, texto):
        t = self._norm(texto)
        if any(p in t for p in ("luce", "encender", "color")):
            return self._ejecutar("luces", {"color": self._color_de(texto)})
        if "hora" in t and len(t.split()) <= 6:
            return self._ejecutar("hora", {})
        if "apaga" in t and "pc" in t:
            return self._ejecutar("apagar", {})
        try:
            pc_r = self.acciones.desde_texto(texto)
            if pc_r:
                return pc_r
        except Exception:
            pass
        if "noticia" in t or "period" in t:
            return mundo.noticias_hoy()
        if "clima" in t or ("tiempo" in t and "hace" in t):
            return mundo.clima_simple()
        if "me escuch" in t or "me oye" in t:
            return random.choice(_ESCUCHO)
        if "feliz" in t and ("por que" in t or "porque" in t):
            return "Porque estás aquí y no hay alarmas. Simple y de verdad."
        if ("como" in t and "estas" in t) or ("como" in t and "te va" in t):
            return random.choice(_COMO_ESTAS)
        # Fallback humano: no menú de opciones
        return random.choice(_FALLBACK)

    def _color_de(self, texto):
        colores = {
            "azul": (0, 80, 255),
            "rojo": (255, 20, 20),
            "verde": (0, 255, 80),
            "amarillo": (255, 220, 0),
            "naranja": (255, 120, 0),
            "morado": (150, 0, 255),
            "rosa": (255, 40, 160),
            "blanco": (255, 255, 255),
        }
        low = (texto or "").lower()
        for nombre, rgb in colores.items():
            if nombre in low:
                return list(rgb)
        return [0, 120, 255]
