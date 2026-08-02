# auto_exe.py - Vigila los fuentes y reconstruye JARVIS.exe cuando hace falta.
# El EXE (jarvis_launcher.py) lee el codigo vivo del proyecto, asi que solo se
# recompila cuando cambia el propio launcher. El resto de cambios no requiere rebuild.
#
# Uso:
#   python auto_exe.py          -> modo vigia (polling cada 2 s, infinito)
#   python auto_exe.py build    -> reconstruccion unica y salir
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
PUNTOS_VIGILADOS = [
    "jarvis_launcher.py",
    "main.py",
    "config.py",
    "requirements.txt",
]
CARPETAS_VIGILADAS = ["core", "web", "acciones"]

# El launcher es lo unico que queda congelado dentro del EXE; por eso solo un
# cambio ahi justifica recompilar.
LAUNCHER = "jarvis_launcher.py"


def _snap():
    """Firma actual (mtime + tamano) de los fuentes que importan."""
    firma = {}
    for nombre in PUNTOS_VIGILADOS:
        ruta = os.path.join(BASE, nombre)
        firma[ruta] = _metadatos(ruta)
    for carpeta in CARPETAS_VIGILADAS:
        ruta = os.path.join(BASE, carpeta)
        if not os.path.isdir(ruta):
            continue
        for raiz, _, archivos in os.walk(ruta):
            if "__pycache__" in raiz or "node_modules" in raiz:
                continue
            for archivo in archivos:
                ruta_archivo = os.path.join(raiz, archivo)
                firma[ruta_archivo] = _metadatos(ruta_archivo)
    return firma


def _metadatos(ruta):
    try:
        st = os.stat(ruta)
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


def _exe_actualizado():
    """True si la copia raiz y dist tienen el mismo exe nuevo."""
    raiz = os.path.join(BASE, "JARVIS.exe")
    dist = os.path.join(BASE, "dist", "JARVIS.exe")
    try:
        return os.path.getsize(raiz) == os.path.getsize(dist) and \
            os.path.getmtime(raiz) >= os.path.getmtime(dist) - 1
    except OSError:
        return False


def _exe_en_uso():
    """True si JARVIS.exe esta corriendo (no se puede sobrescribir)."""
    try:
        salida = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq JARVIS.exe", "/NH"],
            capture_output=True, text=True, timeout=15,
        ).stdout
        return "JARVIS.exe" in salida
    except Exception:
        return True  # ante la duda, avisar


def construir(motivo):
    print(f"  [auto_exe] {motivo}")
    print("  [auto_exe] Reconstruyendo JARVIS.exe ...")
    try:
        proc = subprocess.run(
            ["cmd", "/c", "build_exe.bat", "auto"],
            cwd=BASE, timeout=600,
        )
        if proc.returncode == 0:
            if _exe_actualizado():
                print("  [auto_exe] OK - JARVIS.exe actualizado.")
            else:
                print("  [auto_exe] Build OK, pero JARVIS.exe esta en uso: el")
                print("            nuevo EXE quedo en dist\\JARVIS.exe.")
                print("            Cierra la app y corre:  python auto_exe.py build")
            return True
        print("  [auto_exe] ERROR - el build termino con codigo", proc.returncode)
    except subprocess.TimeoutExpired:
        print("  [auto_exe] ERROR - el build excedio 10 minutos.")
    except Exception as exc:
        print("  [auto_exe] ERROR -", exc)
    return False


def build_unico():
    return construir("Build manual solicitado.")


def vigilar():
    print("  [auto_exe] Vigilando fuentes del proyecto (Ctrl+C para salir)...")
    ultima = _snap()
    while True:
        time.sleep(2.0)
        actual = _snap()
        if actual == ultima:
            continue
        cambiados = [ruta for ruta in actual if actual[ruta] != ultima.get(ruta)]
        ultima = actual
        if os.path.join(BASE, LAUNCHER) in cambiados:
            if _exe_en_uso():
                print("  [auto_exe] OJO: JARVIS.exe esta en uso. Cierralo para "
                      "actualizarlo; el build se reintentara al siguiente cambio.")
                continue
            construir(f"Cambio detectado en {LAUNCHER} -> recompilar.")
        else:
            nombres = ", ".join(os.path.basename(r) for r in cambiados[:3])
            print(f"  [auto_exe] Cambio en {nombres}: no requiere rebuild "
                  "(el EXE lee el codigo vivo).")


def main():
    if len(sys.argv) > 1 and sys.argv[1].lower() == "build":
        return 0 if build_unico() else 1
    vigilar()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  [auto_exe] Vigia detenido.")
