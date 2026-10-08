# -*- coding: utf-8 -*-
"""
Draw the application icon (no external assets, pure PIL geometry).

Design: dark rounded-square background + bright cyan bore ring with a soft glow
and a metallic highlight arc + orange centre dot. Drawn at 1024px and exported as
a multi-size .ico so it stays legible at 16x16.

Output: <project>/app_icon.ico  (the patch script deploys it to the app folder)

Usage:
    E:\\robot_project\\robot_inspection\\.venv\\Scripts\\python.exe scripts\\make_app_icon.py
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

PROJ = Path(__file__).resolve().parents[1]
OUT = PROJ / "app_icon.ico"
S = 1024


def main() -> int:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # rounded-square background with a vertical gradient
    bg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bg)
    for y in range(S):
        t = y / (S - 1)
        bd.line([(0, y), (S, y)],
                fill=(int(18 + 10 * (1 - t)), int(40 + 24 * (1 - t)),
                      int(62 + 40 * (1 - t)), 255))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1],
                                           radius=int(S * 0.22), fill=255)
    img.paste(bg, (0, 0), mask)

    # soft top-left highlight
    hl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(hl).ellipse([-S * 0.35, -S * 0.55, S * 0.75, S * 0.35],
                               fill=(255, 255, 255, 26))
    img = Image.alpha_composite(img, hl.filter(ImageFilter.GaussianBlur(S * 0.06)))
    img.putalpha(Image.composite(img.getchannel("A"), Image.new("L", (S, S), 0), mask))

    # bore ring (cyan) + glow
    c = S / 2
    R, W = S * 0.285, S * 0.088
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([c - R, c - R, c + R, c + R],
                                 outline=(64, 232, 200, 170), width=int(W * 1.9))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(S * 0.035)))

    d = ImageDraw.Draw(img)
    d.ellipse([c - R, c - R, c + R, c + R], outline=(70, 240, 206, 255), width=int(W))
    d.ellipse([c - R + W * 1.15, c - R + W * 1.15, c + R - W * 1.15, c + R - W * 1.15],
              fill=(9, 22, 34, 235))                       # hole depth
    d.arc([c - R + W * 0.1, c - R + W * 0.1, c + R - W * 0.1, c + R - W * 0.1],
          start=196, end=272, fill=(220, 255, 250, 210), width=int(W * 0.42))

    # orange centre dot
    r0 = S * 0.052
    d.ellipse([c - r0, c - r0, c + r0, c + r0], fill=(255, 140, 60, 255))
    d.ellipse([c - r0 * 0.45, c - r0 * 0.75, c + r0 * 0.15, c - r0 * 0.15],
              fill=(255, 210, 170, 220))

    img.save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                         (64, 64), (128, 128), (256, 256)])
    print("icon written:", OUT, "({} bytes)".format(OUT.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
