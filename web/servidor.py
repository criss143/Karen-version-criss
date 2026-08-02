# Servidor del HUD + API de comandos (también será el punto de entrada de Alexa)
import asyncio
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import BASE
from core.llm_router import (
    ANTHROPIC_API_KEY,
    GEMINI_API_KEY,
    GROQ_API_KEY,
    OPENROUTER_API_KEY,
)

STATIC = os.path.join(BASE, "web", "static")


def crear_app(bus, boca, luces, webmon, cerebro, acciones, oido=None):
    app = FastAPI(title="KAREN HUD", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        # Sin caché: pywebview/WebView2 debe ver el HUD actualizado al recargar
        return FileResponse(
            os.path.join(STATIC, "index.html"),
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        # Enviar estado emocional inicial
        try:
            dom = cerebro.emociones.dominante()
            await websocket.send_json({"tipo": "mood", "datos": {
                "emocion": dom["nombre"],
                "intensidad": round(dom["intensidad"], 2),
                "icono": dom["icono"],
                "color": dom["color"],
            }})
        except Exception:
            pass

        ultima_variacion = asyncio.get_event_loop().time()
        try:
            while True:
                ahora = asyncio.get_event_loop().time()
                # Eventos del bus (oido, boca, mood, etc.)
                for evento in bus.drenar():
                    await websocket.send_json(evento)

                # Micro-variación periódica: mantiene la cara "viva"
                if ahora - ultima_variacion > 2.5:
                    try:
                        micro = cerebro.emociones.micro_variacion()
                        await websocket.send_json({"tipo": "mood", "datos": micro})
                    except Exception:
                        pass
                    ultima_variacion = ahora

                await asyncio.sleep(0.08)
        except (WebSocketDisconnect, RuntimeError):
            pass
        except Exception:
            pass

    @app.post("/hablar")
    def hablar(body: dict):
        texto = (body.get("texto") or "").strip()
        if texto:
            boca.decir(texto, esperar=False)
        return {"ok": True}

    @app.post("/luces")
    def luces_endpoint(body: dict):
        if body.get("off"):
            mensaje = luces.apagar()
        else:
            rgb = [int(body.get(k, 0)) for k in ("r", "g", "b")]
            mensaje = luces.encender(*rgb)
        return {"ok": True, "mensaje": mensaje}

    @app.post("/webs")
    def webs_endpoint():
        return {"resultados": webmon.chequear_todo()}

    @app.post("/comando")
    def comando(body: dict):
        texto = (body.get("texto") or "").strip()
        if not texto:
            return {"respuesta": ""}
        respuesta = cerebro.procesar(texto)
        # Hablar la respuesta (async, no bloquea el HUD)
        if respuesta:
            try:
                boca.set_mood(getattr(cerebro, "mood", None) or cerebro.emociones.dominante()["nombre"])
            except Exception:
                pass
            boca.decir(respuesta, esperar=False)
        return {"respuesta": respuesta}

    @app.post("/estado-pc")
    def estado_pc():
        return {"respuesta": acciones.ejecutar("estado", {})}

    @app.get("/llm/estado")
    def llm_estado():
        """Estado del router multi-motor: motores por sección + disponibilidad."""
        try:
            st = cerebro.llm.estado()
        except Exception as e:
            return {"ok": False, "msg": str(e)}
        st["claves"] = {
            "gemini": bool(GEMINI_API_KEY),
            "groq": bool(GROQ_API_KEY),
            "openrouter": bool(OPENROUTER_API_KEY),
            "claude": bool(ANTHROPIC_API_KEY),
            "ollama": True,  # local, siempre "disponible"
        }
        return st

    @app.post("/llm/motor")
    def llm_motor(body: dict):
        """Cambia el motor preferido de una sección: {"seccion": "codigo", "motor": "claude"}"""
        seccion = (body.get("seccion") or "").strip()
        motor = (body.get("motor") or "auto").strip().lower()
        if not cerebro.llm.set_motor(seccion, motor):
            return {"ok": False, "msg": "sección o motor inválido"}
        return {
            "ok": True,
            "seccion": seccion,
            "motor": cerebro.llm.motor_de(seccion),
        }

    @app.get("/stats")
    def stats():
        """Stats reales del PC para el HUD (CPU/RAM/disco/batería)."""
        try:
            import psutil

            bat = psutil.sensors_battery()
            ram = psutil.virtual_memory()
            disco = psutil.disk_usage(BASE)
            return {
                "ok": True,
                "cpu": round(psutil.cpu_percent(interval=0.3), 1),
                "ram": {
                    "uso": round(ram.percent, 1),
                    "total_gb": round(ram.total / 1e9, 1),
                    "libre_gb": round(ram.available / 1e9, 1),
                },
                "disco": {
                    "uso": round(disco.percent, 1),
                    "total_gb": round(disco.total / 1e9, 1),
                },
                "bateria": {
                    "porcentaje": round(bat.percent, 1) if bat else None,
                    "enchufado": bool(bat.power_plugged) if bat else None,
                },
                "procesos": len(psutil.pids()),
            }
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    @app.get("/voz")
    def voz_estado():
        if oido is None:
            return {"ok": False, "msg": "sin oído"}
        st = oido.voces.estado_hud()
        st["perfil_activo"] = getattr(oido, "ultimo_perfil", st.get("activo"))
        st["score"] = getattr(oido, "ultimo_score", 0)
        st["ok"] = True
        return st

    @app.post("/voz/enroll")
    def voz_enroll(body: dict):
        """Inicia grabación de perfil: {\"perfil\": \"normal\"|\"cris\"}"""
        if oido is None:
            return {"ok": False, "msg": "sin oído"}
        perfil = (body.get("perfil") or "normal").lower()
        if perfil in ("hacker",):
            perfil = "cris"
        if perfil not in ("normal", "cris"):
            perfil = "normal"
        oido.pedir_enroll(perfil, segundos=8.0)
        return {
            "ok": True,
            "perfil": perfil,
            "msg": f"Di algo con voz {perfil} durante unos segundos…",
        }

    return app
