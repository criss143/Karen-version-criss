# JARVIS â€” comprobaciÃ³n rÃ¡pida de todos los mÃ³dulos
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = os.path.dirname(os.path.abspath(__file__))


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--habla", action="store_true", help="reproduce la voz de prueba")
    arg = args.parse_args()

    print("== JARVIS: comprobaciÃ³n rÃ¡pida ==")
    from core.eventos import Bus
    bus = Bus()

    # 1) audio de salida
    try:
        import pygame
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        print("[OK] Audio de salida (pygame-ce) listo")
    except Exception as e:
        print(f"[X] Audio de salida: {e}")

    # 2) micrÃ³fono
    try:
        import sounddevice as sd
        entradas = sd.query_devices(kind="input")
        print(f"[OK] MicrÃ³fono disponible:\n{entradas}")
    except Exception as e:
        print(f"[X] MicrÃ³fono: {e}")

    # 3) luces BLE
    from acciones.luces import Luces
    print(f"[i] Luces -> {Luces(bus).estado()}")

    # 4) sÃ­ntesis de voz
    try:
        from config import VOZ
        import edge_tts

        async def gen():
            c = edge_tts.Communicate(
                "Hola, Luis. Soy Jarvis. Prueba de voz completada.", VOZ
            )
            await c.save(os.path.join(BASE, "prueba_voz.mp3"))

        asyncio.run(gen())
        print("[OK] Voz sintetizada -> prueba_voz.mp3")
    except Exception as e:
        print(f"[X] edge-tts: {e}")

    # 5) motor de transcripciÃ³n
    try:
        from faster_whisper import WhisperModel
        modelo = WhisperModel("small", device="cpu", compute_type="int8")
        print("[OK] Whisper cargado (oÃ­do listo)")
    except Exception as e:
        print(f"[X] faster-whisper: {e}")

    # 6) reproducciÃ³n (si --habla)
    if arg.habla:
        try:
            pygame.mixer.music.load(os.path.join(BASE, "prueba_voz.mp3"))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                import time
                time.sleep(0.1)
            print("[OK] Â¡Me has oÃ­do hablar!")
        except Exception as e:
            print(f"[X] Reproduciendo voz: {e}")

    print("== Fin de la comprobaciÃ³n ==")


if __name__ == "__main__":
    main()

