# KAREN — cuerpo vivo: oído → cerebro → voz + app
import os
import socket
import sys

# Candado de instancia única ANTES de importar nada pesado (pygame/micrófono).
# Si otra Karen ya está viva, salimos al instante: así nunca se abren dos voces
# ni dos procesos peleando por el micrófono (causa del "eco"/voz doble).
LOCK_PUERTO = 47777


def _candado_instancia_unica():
    """Ocupa un puerto local privado. Si ya está ocupado, otra Karen vive."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PUERTO))
        s.listen(1)
    except OSError:
        print("  Ya hay una instancia de KAREN en ejecución (voz activa).")
        print("  Usa esa ventana en lugar de abrir otra.")
        return None
    return s


def main():
    candado = _candado_instancia_unica()
    if candado is None:
        return

    import random
    import threading

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    import uvicorn

    from config import PALABRA_ACTIVACION, SOLO_POR_PALABRA
    from core.boca import Boca
    from core.cerebro import Cerebro
    from core.eventos import Bus
    from core.memoria import Memoria
    from core.oido import Oido
    from acciones import Acciones
    from web.servidor import crear_app

    PUERTO = 8000

    bus = Bus()
    memoria = Memoria()
    acciones = Acciones(bus)
    boca = Boca(bus)
    # Recordatorios/temporizadores y otros eventos internos hablan por el bus
    bus.suscribir("decir", lambda texto: boca.decir(str(texto), esperar=False))
    oido = Oido(bus)
    cerebro = Cerebro(bus, memoria, acciones)
    cerebro.set_voz_perfil(getattr(oido, "ultimo_perfil", "normal"))

    app = crear_app(bus, boca, acciones.luces, acciones.webmon, cerebro, acciones, oido)
    hilo_hud = threading.Thread(
        target=lambda: uvicorn.run(
            app, host="127.0.0.1", port=PUERTO, log_level="warning", log_config=None
        ),
        daemon=True,
    )
    hilo_hud.start()

    acciones.webmon.iniciar_bucle()

    # Oído musical: captura el sonido de la PC y lo manda al HUD (visualizador)
    audio_pc = None
    try:
        from audio_sistema import AudioSistema
        audio_pc = AudioSistema(bus)
        audio_pc.iniciar()
    except Exception as e:
        print(f"  Audio PC no disponible: {e}")
        audio_pc = None

    # Precarga STT + LLM en background (1er comando sin espera larga)
    def _warm():
        try:
            oido._cargar_modelo()
        except Exception:
            pass
        try:
            cerebro.llm.warm()
        except Exception:
            pass

    threading.Thread(target=_warm, daemon=True).start()

    saludo = "Bienvenido de vuelta."

    threading.Thread(
        target=lambda: boca.decir(saludo, esperar=True),
        daemon=True,
    ).start()

    try:
        print(
            """
    ██╗  ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
    ██║ ██╔╝██╔══██╗██╔══██╗██║   ██║██║██╔════╝
    █████╔╝ ███████║██████╔╝██║   ██║██║███████╗
    ██╔═██╗ ██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
    ██║  ██╗██║  ██║██║  ██║ ╚████╔╝ ██║███████║
    ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝  ╚═╝╚══════╝
    En línea. Ventana de KAREN lista.
    Voces: di "Karen, memoriza mi voz normal" / "… voz cris"
    Mic REPOSO → solo tu voz + "Karen"
    Cierra la ventana para salir.
    """
        )
    except Exception:
        pass

    if not oido.disponible():
        print("Aviso: no hay micrófono activo. La ventana sigue funcionando por teclado.")

    def bucle_oido():
        """Oído → cerebro → voz, en su propio hilo mientras vive la ventana."""
        while True:
            if getattr(boca, "hablando", False):
                threading.Event().wait(0.10)
                continue

            texto = oido.escuchar()
            if texto is None:
                continue

            # Resultado de enroll de voz
            if isinstance(texto, dict) and texto.get("_enroll"):
                msg = texto.get("msg") or "Voz guardada."
                if texto.get("ok"):
                    cerebro.set_voz_perfil(texto.get("perfil") or "normal")
                    boca.decir(msg + ". Listo.", esperar=True)
                else:
                    boca.decir(msg or "No pude guardar la voz.", esperar=True)
                oido.marcar_cooldown(0.4)
                continue

            # Solo wake sin comando → ventana abierta, ack breve 1 vez (no spam)
            if texto == "" and oido._en_ventana_activa():
                if not getattr(oido, "_ack_wake", False):
                    oido._ack_wake = True
                    boca.decir(
                        random.choice(
                            [
                                "Te escucho, Luis.",
                                "Aquí estoy contigo.",
                                "Dime, te oigo.",
                            ]
                        ),
                        esperar=True,
                    )
                    oido.marcar_cooldown(0.35)
                continue
            if not texto:
                continue
            oido._ack_wake = False

            # Sincronizar personalidad con huella detectada
            try:
                cerebro.set_voz_perfil(getattr(oido, "ultimo_perfil", "normal"))
            except Exception:
                pass

            limpio = texto.lower().strip()
            if SOLO_POR_PALABRA and limpio.startswith(PALABRA_ACTIVACION.lower()):
                texto = texto[len(PALABRA_ACTIVACION) :].strip(" .,;:¡!¿?")
                if not texto:
                    oido.abrir_ventana()
                    oido.marcar_cooldown(0.25)
                    continue

            respuesta = cerebro.procesar(texto)
            try:
                boca.set_mood(
                    getattr(cerebro, "mood", None)
                    or cerebro.emociones.dominante()["nombre"]
                )
            except Exception:
                pass
            boca.decir(respuesta, esperar=True)
            oido.marcar_cooldown(0.4)
            try:
                # 5s de silencio tras respuesta → REPOSO (mismo VENTANA_ACTIVA_S)
                oido.abrir_ventana(5.0)
            except Exception:
                pass

    threading.Thread(target=bucle_oido, daemon=True).start()

    # App de escritorio: ventana nativa (pywebview / WebView2), NO navegador.
    try:
        import webview

        ventana = webview.create_window(
            "KAREN",
            f"http://127.0.0.1:{PUERTO}",
            width=1024,
            height=720,
            min_size=(760, 560),
            background_color="#060b1a",
            confirm_close=True,
        )
        webview.start(debug=False)
    except Exception as e:
        print(f"  Ventana nativa no disponible ({e}); el servidor sigue en:")
        print(f"  http://127.0.0.1:{PUERTO}")
        threading.Event().wait()


if __name__ == "__main__":
    main()
