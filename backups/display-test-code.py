# Display test for the LILYGO T-Display-S3 (no networking yet).
# Uses only built-in modules: board.DISPLAY is set up by CircuitPython itself.
#
# What you should see:
#   - 5 colour bars along the top: red, green, blue, white, yellow
#   - a white dot in each bottom corner (checks the panel edges/offsets)
#   - a green pixel-art blob on the left that blinks
#   - "Mood Clip!" text and an uptime counter on the right
import time

import board
import displayio
import terminalio
import vectorio

display = board.DISPLAY
print("Display:", display.width, "x", display.height, "rotation", display.rotation)

BG = 0x1B1B2F
root = displayio.Group()
display.root_group = root


def solid(color):
    palette = displayio.Palette(1)
    palette[0] = color
    return palette


def rect(color, x, y, width, height):
    root.append(vectorio.Rectangle(pixel_shader=solid(color), x=x, y=y, width=width, height=height))


rect(BG, 0, 0, display.width, display.height)

BARS = (0xFF0000, 0x00FF00, 0x0000FF, 0xFFFFFF, 0xFFD000)
bar_width = display.width // len(BARS)
for i, color in enumerate(BARS):
    rect(color, i * bar_width, 0, bar_width, 16)

rect(0xFFFFFF, 0, display.height - 6, 6, 6)
rect(0xFFFFFF, display.width - 6, display.height - 6, 6, 6)

# --- Pixel-art sprite: 16x16, drawn from text, scaled up 6x ---
SPRITE = (
    "................",
    ".....XXXXXX.....",
    "...XXooooooXX...",
    "..XooooooooooX..",
    ".XooooooooooooX.",
    ".XooEEooooEEooX.",
    ".XooEEooooEEooX.",
    ".XooooooooooooX.",
    ".XoPPooooooPPoX.",
    ".XoooMooooMoooX.",
    ".XooooMMMMooooX.",
    "..XooooooooooX..",
    "...XXooooooXX...",
    ".....XXXXXX.....",
    "................",
    "................",
)
COLOR_INDEX = {".": 0, "X": 1, "o": 2, "E": 3, "M": 3, "P": 4}

sprite_palette = displayio.Palette(5)
sprite_palette[0] = 0x000000
sprite_palette.make_transparent(0)
sprite_palette[1] = 0x2B1B3F  # outline
sprite_palette[2] = 0x9EE6A0  # body
sprite_palette[3] = 0x1A1A1A  # eyes / mouth
sprite_palette[4] = 0xFF8FB1  # cheeks

sprite_bitmap = displayio.Bitmap(16, 16, len(sprite_palette))
for y, row in enumerate(SPRITE):
    for x, char in enumerate(row):
        sprite_bitmap[x, y] = COLOR_INDEX[char]

sprite = displayio.Group(scale=6, x=16, y=30)
sprite.append(displayio.TileGrid(sprite_bitmap, pixel_shader=sprite_palette))
root.append(sprite)

# Top row of each eye; blinking swaps it between eye and body colour.
EYE_PIXELS = [(x, 5) for x, char in enumerate(SPRITE[5]) if char == "E"]


def set_eyes_open(is_open):
    for x, y in EYE_PIXELS:
        sprite_bitmap[x, y] = COLOR_INDEX["E" if is_open else "o"]


# --- Text, using the built-in font (no extra libraries) ---
def text_box(columns, rows, x, y, scale=1, color=0xFFFFFF):
    font = terminalio.FONT
    char_width, char_height = font.get_bounding_box()[:2]
    palette = displayio.Palette(2)
    palette[0] = BG
    palette[1] = color
    grid = displayio.TileGrid(
        font.bitmap, pixel_shader=palette, width=columns, height=rows,
        tile_width=char_width, tile_height=char_height,
    )
    group = displayio.Group(scale=scale, x=x, y=y)
    group.append(grid)
    root.append(group)
    return terminalio.Terminal(grid, font)


status = None
try:
    title = text_box(10, 1, 124, 30, scale=2, color=0xFFD000)
    title.write("Mood Clip!")
    info = text_box(32, 3, 124, 66)
    info.write("{}x{} rot {}\r\n".format(display.width, display.height, display.rotation))
    info.write("Display test OK\r\n")
    info.write("Dots in both corners?")
    status = text_box(16, 1, 124, 120, scale=2, color=0x9EE6A0)
except Exception as error:  # keep the rest of the test visible if text fails
    print("Text failed:", error)

print("Display test running")
start = time.monotonic()
last_print = 0
while True:
    uptime = int(time.monotonic() - start)
    set_eyes_open(uptime % 4 != 3)  # closed for 1 s out of every 4
    if status:
        status.write("\rup {}s  ".format(uptime))
    if uptime - last_print >= 5:
        print("still running, up", uptime, "s")
        last_print = uptime
    time.sleep(0.25)
