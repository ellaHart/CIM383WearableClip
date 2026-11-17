"""Convert assets/sprites/*.png into 8-bit indexed BMPs in device/sprites/.

Palette index 0 is reserved for transparency (stored as magenta), so the
device can call palette.make_transparent(0). Needs Pillow:  pip install pillow
Run from the repo folder:  python tools/convert_sprites.py
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "sprites"
TARGET = ROOT / "device" / "sprites"
TRANSPARENT_KEY = (255, 0, 255)
MAX_COLORS = 255  # 256 palette slots minus the transparent one


def convert(png_path):
    image = Image.open(png_path).convert("RGBA")
    opaque = [(x, y) for y in range(image.height) for x in range(image.width) if image.getpixel((x, y))[3] >= 128]

    rgb = image.convert("RGB")
    colors = {rgb.getpixel(xy) for xy in opaque}
    if len(colors) > MAX_COLORS:
        rgb = rgb.quantize(colors=MAX_COLORS, method=Image.Quantize.MEDIANCUT).convert("RGB")
        colors = {rgb.getpixel(xy) for xy in opaque}

    palette = [TRANSPARENT_KEY] + sorted(colors)
    index_of = {color: i for i, color in enumerate(palette)}

    indexed = Image.new("P", image.size, 0)
    indexed.putpalette([channel for color in palette for channel in color])
    for xy in opaque:
        indexed.putpixel(xy, index_of[rgb.getpixel(xy)])

    out_path = TARGET / (png_path.stem + ".bmp")
    indexed.save(out_path)
    print(f"{png_path.name} -> {out_path.relative_to(ROOT)}  {image.size[0]}x{image.size[1]}, {len(palette)} colors")


if __name__ == "__main__":
    TARGET.mkdir(parents=True, exist_ok=True)
    for png in sorted(SOURCE.glob("*.png")):
        convert(png)
