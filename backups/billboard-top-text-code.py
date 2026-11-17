# Mood Clip: full-width scrolling billboard text on top, pixel-art sprite below.
#
# Buttons:  IO14 (next to RST) = next state,  BOOT (IO0) = previous state.
# The chosen state is saved in non-volatile memory, so it survives restarts.
import time

import board
import displayio
import keypad
import microcontroller
import terminalio
import vectorio

# State number = position in this list (1-9). Colours come from the Figma design.
STATES = (
    {"text": "Hope you have a great day!", "bg": 0xFFBB67, "sprite": "cheer"},          # 1
    {"text": "Hi! Nice to meet you!", "bg": 0xFFFFFF, "sprite": "friendly", "border": True},  # 2
    {"text": "Not Friendly!!! DO NOT APPROACH", "bg": 0xA24A4A, "sprite": "alert"},     # 3
    {"text": "How you doinnnnnnn <3", "bg": 0xFFA7BA, "sprite": "love"},                # 4
    {"text": "Nap Time Nap Time Nap Time", "bg": 0xBC99D4, "sprite": "sleepy"},         # 5
    {"text": "Currently Playing:", "bg": 0x93BA9B, "sprite": "music"},                  # 6
    {"text": "Locked in! Do not disturb", "bg": 0xB8B8B8, "sprite": "laptop"},          # 7
    {"text": "I am hardcore judging you rn", "bg": 0xD9D9D9, "sprite": "judging"},      # 8
    {"text": "Snack Time! Snack Time! Snack Time!", "bg": 0xF7E9AE, "sprite": "eating"},  # 9
)

TEXT_COLOR = 0x111111
TEXT_SCALE = 5        # built-in font is 6x12 px, so 30x60 on screen
SPRITE_SCALE = 3      # 40x40 sprites -> 120x120
SCROLL_STEP = 5       # pixels per frame; raise for faster scrolling
FPS = 18              # measured max is ~19 fps at TEXT_SCALE 5 (~24 at scale 4)
TEXT_GAP = 40         # extra pause (in pixels) before the text scrolls in again
BORDER = 4

display = board.DISPLAY
display.auto_refresh = False
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


def build_screen(state):
    """Returns (root group, scrolling text group, text width in pixels)."""
    root = displayio.Group()
    rect(root, state["bg"], 0, 0, WIDTH, HEIGHT)

    text = text_line(state["text"])
    root.append(text)

    if state.get("border"):
        rect(root, TEXT_COLOR, 0, 0, WIDTH, BORDER)
        rect(root, TEXT_COLOR, 0, HEIGHT - BORDER, WIDTH, BORDER)
        rect(root, TEXT_COLOR, 0, 0, BORDER, HEIGHT)
        rect(root, TEXT_COLOR, WIDTH - BORDER, 0, BORDER, HEIGHT)

    try:
        bitmap, palette = load_bmp("/sprites/{}.bmp".format(state["sprite"]))
        sprite = displayio.Group(scale=SPRITE_SCALE, x=SPRITE_X, y=SPRITE_Y)
        sprite.append(displayio.TileGrid(bitmap, pixel_shader=palette))
        root.append(sprite)
    except OSError as error:
        print("Missing sprite", state["sprite"], error)

    return root, text, len(state["text"]) * CHAR_W * TEXT_SCALE


# --- Saved state (byte 0 of non-volatile memory) ---
def load_saved_index():
    saved = microcontroller.nvm[0]
    return saved if saved < len(STATES) else 0


def save_index(index):
    if microcontroller.nvm[0] != index:
        microcontroller.nvm[0] = index


def show(index):
    global text_group, text_width
    root, text_group, text_width = build_screen(STATES[index])
    display.root_group = root
    save_index(index)
    print("State", index + 1, "-", STATES[index]["text"])


keys = keypad.Keys(
    (microcontroller.pin.GPIO0, microcontroller.pin.GPIO14),
    value_when_pressed=False, pull=True,
)
STEP_FOR_KEY = (-1, 1)  # key 0 = BOOT/IO0 -> previous, key 1 = IO14 -> next

current = load_saved_index()
text_group = None
text_width = 0
show(current)

frame_time = 1 / FPS
while True:
    started = time.monotonic()

    event = keys.events.get()
    if event and event.pressed:
        current = (current + STEP_FOR_KEY[event.key_number]) % len(STATES)
        show(current)

    text_group.x -= SCROLL_STEP
    if text_group.x < -text_width:
        text_group.x = WIDTH + TEXT_GAP
    display.refresh()

    leftover = frame_time - (time.monotonic() - started)
    if leftover > 0:
        time.sleep(leftover)
