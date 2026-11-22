"""Convert the artwork PNGs into 8-bit indexed BMPs for the clip:
    assets/sprites/*.png -> device/sprites/*.bmp   (mood sprites)
    assets/magic8/*.png  -> device/magic8/*.bmp    (Magic 8 Ball screens)
    assets/aquarium/*.png -> device/aquarium/*.bmp (fish spritesheets)
plus the aquarium background, which keeps its smooth colours:
    assets/aquarium/background.jpg -> device/aquarium/background.bmp  (320x170, 16-bit RGB565)

Palette index 0 is reserved for transparency (stored as magenta), so the
device can call palette.make_transparent(0). Needs Pillow:  pip install pillow
Run from the repo folder:  python tools/convert_sprites.py
"""
import struct
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
FOLDERS = (
    (ROOT / "assets" / "sprites", ROOT / "device" / "sprites"),
    (ROOT / "assets" / "magic8", ROOT / "device" / "magic8"),
    (ROOT / "assets" / "aquarium", ROOT / "device" / "aquarium"),
)
BACKGROUND = (ROOT / "assets" / "aquarium" / "background.jpg", ROOT / "device" / "aquarium" / "background.bmp")
SCREEN = (320, 170)
TRANSPARENT_KEY = (255, 0, 255)
MAX_COLORS = 255  # 256 palette slots minus the transparent one


def convert(png_path, target):
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

    out_path = target / (png_path.stem + ".bmp")
    indexed.save(out_path)
    print(f"{png_path.name} -> {out_path.relative_to(ROOT)}  {image.size[0]}x{image.size[1]}, {len(palette)} colors")


def convert_background(source, out_path):
    """Scale to fill the screen (cropping the overflow evenly) and save as a 16-bit RGB565 BMP.

    256-colour BMPs would band the smooth gradients; RGB565 is what the display itself shows.
    Floyd-Steinberg error diffusion hides the remaining 565 steps.
    """
    image = Image.open(source).convert("RGB")
    scale = max(SCREEN[0] / image.width, SCREEN[1] / image.height)
    size = (round(image.width * scale), round(image.height * scale))
    image = image.resize(size, Image.LANCZOS)
    left, top = (size[0] - SCREEN[0]) // 2, (size[1] - SCREEN[1]) // 2
    image = image.crop((left, top, left + SCREEN[0], top + SCREEN[1]))

    width, height = SCREEN
    pixels = [[list(image.getpixel((x, y))) for x in range(width)] for y in range(height)]
    levels = (31, 63, 31)
    data = [[0] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            value = 0
            for c, shift in ((0, 11), (1, 5), (2, 0)):
                old = min(255.0, max(0.0, pixels[y][x][c]))
                q = round(old * levels[c] / 255)
                value |= q << shift
                error = old - q * 255 / levels[c]
                for dx, dy, weight in ((1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1)):
                    if 0 <= x + dx < width and y + dy < height:
                        pixels[y + dy][x + dx][c] += error * weight / 16
            data[y][x] = value

    # BMP with BI_BITFIELDS masks; rows bottom-up, 640 bytes each (no padding needed).
    header_size = 14 + 40 + 12
    image_size = width * height * 2
    with open(out_path, "wb") as f:
        f.write(b"BM" + struct.pack("<IHHI", header_size + image_size, 0, 0, header_size))
        f.write(struct.pack("<IiiHHIIiiII", 40, width, height, 1, 16, 3, image_size, 2835, 2835, 0, 0))
        f.write(struct.pack("<III", 0xF800, 0x07E0, 0x001F))
        for y in range(height - 1, -1, -1):
            f.write(struct.pack("<%dH" % width, *data[y]))
    print(f"{source.name} -> {out_path.relative_to(ROOT)}  {width}x{height}, 16-bit RGB565")


if __name__ == "__main__":
    for source, target in FOLDERS:
        target.mkdir(parents=True, exist_ok=True)
        for png in sorted(source.glob("*.png")):
            convert(png, target)
    if BACKGROUND[0].exists():
        convert_background(*BACKGROUND)
