"""Genera assets/misfondos.ico: monedas doradas apiladas.

Se dibuja a 4x y se reduce con LANCZOS para que los bordes salgan suaves.
Ejecutar: venv\\Scripts\\python tools\\make_icon.py
"""
import os

from PIL import Image, ImageDraw

SS = 4
SIZE = 256
C = SIZE * SS

OUTLINE = (92, 58, 0, 255)
SIDE_DARK = (176, 116, 8, 255)
SIDE_LIGHT = (214, 150, 20, 255)
RIDGE = (140, 90, 5, 255)
FACE = (246, 196, 58, 255)
FACE_RING = (222, 160, 20, 255)
FACE_INNER = (252, 214, 92, 255)
HIGHLIGHT = (255, 240, 170, 255)


def s(v):
    return int(round(v * SS))


def draw_coin(d, cx, cy_top, w, h, thick):
    """Una moneda vista desde arriba en perspectiva: canto (cilindro) + cara superior."""
    left, right = cx - w / 2, cx + w / 2
    cy_bot = cy_top + thick
    lw = s(3)

    # canto: media elipse inferior + rectángulo entre centros
    d.ellipse([s(left), s(cy_bot - h / 2), s(right), s(cy_bot + h / 2)], fill=SIDE_DARK, outline=OUTLINE, width=lw)
    d.rectangle([s(left), s(cy_top), s(right), s(cy_bot)], fill=SIDE_DARK)
    d.line([s(left), s(cy_top), s(left), s(cy_bot)], fill=OUTLINE, width=lw)
    d.line([s(right), s(cy_top), s(right), s(cy_bot)], fill=OUTLINE, width=lw)
    # franja de brillo en el canto
    d.rectangle([s(left + w * 0.12), s(cy_top), s(left + w * 0.30), s(cy_bot + h * 0.35)], fill=SIDE_LIGHT)
    # estrías del canto
    for i in range(1, 12):
        x = left + w * i / 12
        d.line([s(x), s(cy_top + 2), s(x), s(cy_bot + h * 0.3)], fill=RIDGE, width=max(1, s(1)))

    # cara superior
    d.ellipse([s(left), s(cy_top - h / 2), s(right), s(cy_top + h / 2)], fill=FACE, outline=OUTLINE, width=lw)
    d.ellipse([s(left + w * 0.1), s(cy_top - h * 0.36), s(right - w * 0.1), s(cy_top + h * 0.36)],
              fill=FACE_INNER, outline=FACE_RING, width=s(3))
    d.ellipse([s(left + w * 0.2), s(cy_top - h * 0.26), s(left + w * 0.5), s(cy_top - h * 0.04)], fill=HIGHLIGHT)


def draw_stack(d, cx, base_y, n, w, h, thick):
    for i in range(n):  # de abajo a arriba, cada moneda tapa la anterior
        draw_coin(d, cx, base_y - i * thick, w, h, thick)


def main():
    img = Image.new("RGBA", (C, C), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    w, h, thick = 128, 44, 22
    draw_stack(d, cx=158, base_y=184, n=7, w=w, h=h, thick=thick)  # pila trasera, más alta
    draw_stack(d, cx=96, base_y=204, n=4, w=w, h=h, thick=thick)   # pila delantera

    out = img.resize((SIZE, SIZE), Image.LANCZOS)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets = os.path.join(root, "assets")
    os.makedirs(assets, exist_ok=True)
    out.save(os.path.join(assets, "misfondos.ico"),
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    out.save(os.path.join(assets, "misfondos.png"))
    print("icono generado en", assets)


if __name__ == "__main__":
    main()
