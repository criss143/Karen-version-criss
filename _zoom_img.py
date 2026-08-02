# -*- coding: utf-8 -*-
from PIL import Image

im = Image.open(r"C:\temp\hackerai-upload\image.png").convert("RGB")
W, H = im.size
px = im.load()


def clase(r, g, b):
    lum = (r + g + b) / 3
    mx = max(r, g, b)
    mn = min(r, g, b)
    if lum < 30:
        return " "
    if lum > 210:
        return "."
    if mx - mn < 20:
        return ":" if lum < 80 else ";"
    if b > 110 and r < 130 and g < 150:
        return "B"
    if lum > 130:
        return "o"
    return "x"


def mapa(x0, x1, y0, y1):
    for y in range(y0, y1):
        print("".join(clase(*px[x, y]) for x in range(x0, x1)))


print("Logo (x20-90, y28-52):")
mapa(20, 90, 28, 52)
print()
print("Zona media (x20-90, y56-76):")
mapa(20, 90, 56, 76)
print()
print("Barra inferior (x0-70, y98-107):")
mapa(0, 70, 98, 107)
print()
print("Borde derecho (x160-192, y0-107):")
mapa(160, 192, 0, 107)
