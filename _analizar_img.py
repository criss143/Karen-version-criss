# -*- coding: utf-8 -*-
"""Analiza image.png: paleta, brillo y mapa ASCII del layout."""
import sys
from PIL import Image

im = Image.open(r"C:\temp\hackerai-upload\image.png").convert("RGB")
W, H = im.size
px = im.load()

# --- Paleta dominante ---
cols = im.getcolors(maxcolors=1_000_000)
cols.sort(reverse=True)
print(f"Tamaño: {W}x{H}")
print("Colores dominantes:")
for c, rgb in cols[:15]:
    print(f"  {c:6d}  #{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}  (R{rgb[0]} G{rgb[1]} B{rgb[2]})")

# --- Brillo promedio por filas (para ver bandas claras/oscuras) ---
print("\nBrillo por franjas horizontales (8 filas):")
for y in range(0, H, max(1, H // 8)):
    row = 0.0
    n = 0
    for x in range(0, W, 2):
        r, g, b = px[x, y]
        row += (r + g + b) / 3
        n += 1
    print(f"  y={y:3d}  brillo={row / n:5.1f}")

# --- Mapa ASCII de colores (grid grueso) ---
def clase(r, g, b):
    lum = (r + g + b) / 3
    mx = max(r, g, b)
    mn = min(r, g, b)
    if lum < 30:
        return " "        # negro / muy oscuro
    if lum > 210:
        return "."
    if mx - mn < 20:
        if lum < 80:
            return ":"    # gris oscuro
        return ";"        # gris claro
    if r > 200 and g < 150 and b < 150:
        return "R"
    if g > 150 and r < 160 and b < 160:
        return "G"
    if b > 170 and r < 160:
        return "B"
    if r > 170 and g > 170 and b < 150:
        return "Y"
    if r > 170 and b > 170 and g < 150:
        return "P"
    if r > 140 and g > 100 and b > 100:
        return "O"
    if lum > 130:
        return "o"
    return "x"

print("\nMapa (ancho 64):")
step_x = max(1, W // 64)
step_y = max(1, H // 32)
for y in range(0, H, step_y):
    linea = "".join(clase(*px[x, y]) for x in range(0, W, step_x))
    print(f"  {y:3d}|{linea}|")

# --- Zonas: promedio de color por cuadrante ---
print("\nPromedios por cuadrante (para detectar sidebar/panel):")
q = [(0, 0, W // 2, H), (W // 2, 0, W, H), (0, 0, W, H // 2), (0, H // 2, W, H)]
for x0, y0, x1, y1 in q:
    rs = gs = bs = n = 0
    for x in range(x0, x1, 2):
        for y in range(y0, y1, 2):
            r, g, b = px[x, y]
            rs += r; gs += g; bs += b; n += 1
    print(f"  x{x0}-{x1} y{y0}-{y1}: RGB({rs // n},{gs // n},{bs // n})")

# --- Detectar si hay texto (filas con alta varianza horizontal) ---
import statistics
print("\nFilas con variación alta (posible texto/bordes):")
for y in range(H):
    vals = [sum(px[x, y]) / 3 for x in range(0, W, 1)]
    if max(vals) - min(vals) > 120:
        print(f"  y={y}  min={min(vals):.0f} max={max(vals):.0f}")
