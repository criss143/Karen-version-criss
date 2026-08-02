# Launcher delgado: siempre ejecuta el main.py actual del proyecto (VS Code).
# AsÃ­ el .exe NO congela el cÃ³digo â€” cada cambio en el repo se refleja al instante.
import os
import subprocess
import sys


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    # Si corre empaquetado con PyInstaller, __file__ puede estar en _MEIPASS;
    # usamos la carpeta del .exe real.
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)

    os.chdir(base)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    venv_py = os.path.join(base, ".venv", "Scripts", "python.exe")
    main_py = os.path.join(base, "main.py")

    if not os.path.isfile(main_py):
        print(f"[JARVIS] No encuentro main.py en:\n  {base}")
        input("Enter para salir...")
        return 1

    if os.path.isfile(venv_py):
        cmd = [venv_py, "-u", main_py]
    else:
        cmd = [sys.executable, "-u", main_py]

    print("  Arrancando JARVIS (cÃ³digo vivo de VS Code)...")
    print(f"  {cmd[0]}")
    print(f"  {main_py}")
    print("  Cierra esta ventana para apagarlo.\n")
    try:
        return subprocess.call(cmd, cwd=base)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
