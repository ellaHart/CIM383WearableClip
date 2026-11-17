# Billboard view: full-width scrolling text on top, pixel-art sprite below.
# Any screen can use it:  view = Billboard({"text": ..., "bg": 0xRRGGBB, "sprite": "name"})
# then call view.tick() once per frame.
import board
import displayio
import terminalio
import vectorio

TEXT_COLOR = 0x111111
TEXT_SCALE = 5        # text size: font is 6x12 px, so 5 -> 60 px tall, 6 -> 72, 7 -> 84
SPRITE_SCALE = 3      # 40x40 sprites -> 120x120
SCROLL_STEP = 5       # pixels per frame; raise for faster scrolling
TEXT_GAP = 40         # extra pause (in pixels) before the text scrolls in again
BORDER = 4

display = board.DISPLAY
WIDTH, HEIGHT = display.width, display.height
SPRITE_SIZE = 40 * SPRITE_SCALE
SPRITE_X = (WIDTH - SPRITE_SIZE) // 2  # centred along the bottom edge
SPRITE_Y = HEIGHT - SPRITE_SIZE

font = terminalio.FONT
CHAR_W, CHAR_H = font.get_bounding_box()[:2]
TEXT_Y = BORDER  # top strip, full width, above the sprite


def load_bmp(path):
    """Load an 8-bit indexed BMP (from tools/convert_sprites.py) into RAM.

    Palette index 0 is transparent.
    """
    with open(path, "rb") as f:
        header = f.read(54)
        data_offset = int.from_bytes(header[10:14], "little")
        dib_size = int.from_bytes(header[14:18], "little")
        width = int.from_bytes(header[18:22], "little")
        height = int.from_bytes(header[22:26], "little")  # positive = rows stored bottom-up
        colors = int.from_bytes(header[46:50], "little") or 256

        f.seek(14 + dib_size)
        raw = f.read(colors * 4)
        palette = displayio.Palette(colors)
        for i in range(colors):
            blue, green, red = raw[i * 4], raw[i * 4 + 1], raw[i * 4 + 2]
            palette[i] = (red << 16) | (green << 8) | blue
        palette.make_transparent(0)

        bitmap = displayio.Bitmap(width, height, colors)
        row_size = (width + 3) & ~3
        f.seek(data_offset)
        for row in range(height):
            line = f.read(row_size)
            y = height - 1 - row
            for x in range(width):
                bitmap[x, y] = line[x]
    return bitmap, palette


def solid(color):
    palette = displayio.Palette(1)
    palette[0] = color
    return palette


def rect(group, color, x, y, width, height):
    group.append(vectorio.Rectangle(pixel_shader=solid(color), x=x, y=y, width=width, height=height))


def text_line(text):
    """One row of built-in-font tiles holding the whole message."""
    palette = displayio.Palette(2)
    palette[0] = 0x000000
    palette.make_transparent(0)
    palette[1] = TEXT_COLOR
    grid = displayio.TileGrid(
        font.bitmap, pixel_shader=palette, width=len(text), height=1,
        tile_width=CHAR_W, tile_height=CHAR_H,
    )
    fallback = font.get_glyph(ord("?"))
    for i, char in enumerate(text):
        glyph = font.get_glyph(ord(char)) or fallback
        grid[i] = glyph.tile_index
    group = displayio.Group(scale=TEXT_SCALE, x=WIDTH, y=TEXT_Y)
    group.append(grid)
    return group


class Billboard:
    def __init__(self, state):
        root = displayio.Group()
        rect(root, state["bg"], 0, 0, WIDTH, HEIGHT)

        try:
            bitmap, palette = load_bmp("/sprites/{}.bmp".format(state["sprite"]))
            sprite = displayio.Group(scale=SPRITE_SCALE, x=SPRITE_X, y=SPRITE_Y)
            sprite.append(displayio.TileGrid(bitmap, pixel_shader=palette))
            root.append(sprite)
        except OSError as error:
            print("Missing sprite", state["sprite"], error)

        # Added after the sprite so the text scrolls over it where they overlap.
        self.text = text_line(state["text"])
        self.text_width = len(state["text"]) * CHAR_W * TEXT_SCALE
        root.append(self.text)

        if state.get("border"):
            rect(root, TEXT_COLOR, 0, 0, WIDTH, BORDER)
            rect(root, TEXT_COLOR, 0, HEIGHT - BORDER, WIDTH, BORDER)
            rect(root, TEXT_COLOR, 0, 0, BORDER, HEIGHT)
            rect(root, TEXT_COLOR, WIDTH - BORDER, 0, BORDER, HEIGHT)

        display.root_group = root

    def tick(self):
        self.text.x -= SCROLL_STEP
        if self.text.x < -self.text_width:
            self.text.x = WIDTH + TEXT_GAP
